"""Cliente de solo lectura para WHOOP (recuperación, sueño y esfuerzo).

El secreto JARVIS_WHOOP guarda client_id, client_secret y el refresh_token inicial
que crea scripts/autorizar_whoop.py. WHOOP rota el refresh_token cada vez que se usa:
el anterior deja de servir. Por eso el más reciente se guarda en Firestore
(usuarios/{id}/estado/whoop_token) y se usa en lugar del del secreto, salvo que el
secreto cambie porque se volvió a autorizar.

Los números y el texto que se lee en voz alta los decide este módulo; el modelo
nunca los calcula.
"""

import asyncio
import cmath
import hashlib
import json
import logging
import math
import os
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from starlette.concurrency import run_in_threadpool

from app.storage import Store

logger = logging.getLogger(__name__)

API = "https://api.prod.whoop.com/developer/v2"
TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"
SCOPES = (
    "offline",
    "read:recovery",
    "read:cycles",
    "read:sleep",
    "read:workout",
    "read:profile",
    "read:body_measurement",
)


class WhoopNoConfigurado(Exception):
    """Falta el secreto JARVIS_WHOOP."""


class WhoopError(Exception):
    """WHOOP no respondió como se esperaba."""


@dataclass(frozen=True)
class Credenciales:
    client_id: str
    client_secret: str
    refresh_token: str

    @property
    def origen(self) -> str:
        # Huella del token del secreto: si cambia, hubo una autorización nueva.
        return hashlib.sha256(self.refresh_token.encode()).hexdigest()[:16]


def credentials_from_env(env: dict[str, str] | None = None) -> Credenciales | None:
    raw = (env if env is not None else os.environ).get("JARVIS_WHOOP", "").strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return Credenciales(
            client_id=str(data["client_id"]),
            client_secret=str(data["client_secret"]),
            refresh_token=str(data["refresh_token"]),
        )
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError("JARVIS_WHOOP no tiene el formato esperado") from exc


def color_recuperacion(score: float) -> str:
    # Bandas de WHOOP: verde 67-100, amarillo 34-66, rojo 0-33.
    if score >= 67:
        return "verde"
    if score >= 34:
        return "amarilla"
    return "roja"


def _minutes(milli: Any) -> int:
    try:
        return round(float(milli) / 60000)
    except (TypeError, ValueError):
        return 0


def _hours_and_minutes(total_minutes: int) -> str:
    hours, minutes = divmod(total_minutes, 60)
    hours_text = "1 hora" if hours == 1 else f"{hours} horas"
    if minutes == 0:
        return hours_text
    minutes_text = "1 minuto" if minutes == 1 else f"{minutes} minutos"
    return f"{hours_text} y {minutes_text}" if hours else minutes_text


def _decimal(value: float) -> str:
    # Siri lee «12,4» como «doce coma cuatro».
    return f"{value:.1f}".replace(".", ",")


def _local_date(value: str | None, zone: ZoneInfo) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(zone).date()
    except ValueError:
        return None


def build_summary(
    recovery: dict[str, Any] | None,
    sleeps: list[dict[str, Any]],
    cycles: list[dict[str, Any]],
    zone_name: str,
    today: date | None = None,
) -> dict[str, Any]:
    """Arma el resumen de la noche. estado: listo, calculando o sin_datos."""
    zone = ZoneInfo(zone_name)
    today = today or datetime.now(zone).date()
    sleep = next((item for item in sleeps if not item.get("nap")), None)
    if sleep is None:
        return {"estado": "sin_datos", "texto": "WHOOP no tiene registros de sueño recientes."}
    if _local_date(sleep.get("end"), zone) != today or sleep.get("score_state") == "PENDING_SCORE":
        return {
            "estado": "calculando",
            "texto": "WHOOP todavía está calculando su noche.",
        }

    result: dict[str, Any] = {"estado": "listo"}
    sentences: list[str] = []
    same_night = recovery is not None and recovery.get("sleep_id") == sleep.get("id")
    recovery_state = recovery.get("score_state") if same_night else None
    if recovery_state in (None, "PENDING_SCORE"):
        return {"estado": "calculando", "texto": "WHOOP todavía está calculando su recuperación."}
    if recovery_state == "SCORED":
        score = recovery.get("score") or {}
        value = round(float(score.get("recovery_score", 0)))
        hrv = round(float(score.get("hrv_rmssd_milli", 0)))
        resting = round(float(score.get("resting_heart_rate", 0)))
        result["recuperacion"] = {
            "porcentaje": value,
            "color": color_recuperacion(value),
            "variabilidad_ms": hrv,
            "frecuencia_reposo": resting,
            "calibrando": bool(score.get("user_calibrating")),
        }
        sentences.append(f"Su recuperación es de {value} por ciento, {color_recuperacion(value)}.")
    else:
        sentences.append("WHOOP no pudo calcular su recuperación de hoy.")

    sleep_score = sleep.get("score") or {}
    stages = sleep_score.get("stage_summary") or {}
    asleep = sum(
        _minutes(stages.get(key))
        for key in (
            "total_light_sleep_time_milli",
            "total_slow_wave_sleep_time_milli",
            "total_rem_sleep_time_milli",
        )
    )
    if sleep.get("score_state") == "SCORED" and asleep:
        performance = sleep_score.get("sleep_performance_percentage")
        needed = sleep_score.get("sleep_needed") or {}
        need_minutes = sum(_minutes(value) for value in needed.values())
        result["sueno"] = {
            "dormido_min": asleep,
            "rendimiento_pct": round(performance) if performance is not None else None,
            "eficiencia_pct": (
                round(sleep_score["sleep_efficiency_percentage"])
                if sleep_score.get("sleep_efficiency_percentage") is not None
                else None
            ),
            "profundo_min": _minutes(stages.get("total_slow_wave_sleep_time_milli")),
            "rem_min": _minutes(stages.get("total_rem_sleep_time_milli")),
            "necesario_min": need_minutes or None,
        }
        sleep_sentence = f"Durmió {_hours_and_minutes(asleep)}"
        if performance is not None:
            sleep_sentence += f", con {round(performance)} por ciento de rendimiento de sueño"
        sentences.append(sleep_sentence + ".")

    if "recuperacion" in result:
        data = result["recuperacion"]
        sentences.append(
            f"Su variabilidad cardiaca es de {data['variabilidad_ms']} milisegundos y su "
            f"frecuencia en reposo de {data['frecuencia_reposo']} latidos por minuto."
        )
        if data["calibrando"]:
            sentences.append("WHOOP todavía se está calibrando, así que tómelo con reserva.")

    # El ciclo más reciente es el de hoy (recién empieza); el anterior es el de ayer.
    previous = cycles[1] if len(cycles) > 1 else None
    if previous and previous.get("score_state") == "SCORED":
        strain = (previous.get("score") or {}).get("strain")
        if strain is not None:
            result["esfuerzo_ayer"] = round(float(strain), 1)
            sentences.append(f"Ayer su esfuerzo fue de {_decimal(float(strain))}.")

    result["texto"] = " ".join(sentences)
    return result


class Whoop:
    def __init__(
        self,
        credentials: Credenciales | None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if credentials is None:
            raise WhoopNoConfigurado
        self._credentials = credentials
        self._transport = transport
        self._token: str | None = None
        self._expires = 0.0
        self._lock = asyncio.Lock()

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=httpx.Timeout(8.0, connect=3.0), transport=self._transport)

    async def _current_refresh_token(self, store: Store | None) -> str:
        if store is None:
            return self._credentials.refresh_token
        try:
            saved = await run_in_threadpool(store.read_whoop_token)
        except Exception as exc:
            logger.warning("storage_failed operation=whoop_token_read kind=%s", type(exc).__name__)
            saved = None
        if saved and saved.get("origen") == self._credentials.origen:
            return str(saved["refresh_token"])
        return self._credentials.refresh_token

    async def _access_token(self, store: Store | None) -> str:
        # Un solo refresco a la vez: WHOOP invalida el token anterior en cuanto lo usa.
        async with self._lock:
            if self._token and time.monotonic() < self._expires:
                return self._token
            refresh_token = await self._current_refresh_token(store)
            async with self._client() as client:
                response = await client.post(
                    TOKEN_URL,
                    data={
                        "grant_type": "refresh_token",
                        "refresh_token": refresh_token,
                        "client_id": self._credentials.client_id,
                        "client_secret": self._credentials.client_secret,
                        "scope": "offline",
                    },
                )
            if response.status_code != 200:
                logger.warning("whoop_token_failed status=%d", response.status_code)
                raise WhoopError(f"token HTTP {response.status_code}")
            data = response.json()
            new_refresh = data.get("refresh_token")
            if new_refresh and store is not None:
                try:
                    await run_in_threadpool(
                        store.write_whoop_token,
                        {"refresh_token": new_refresh, "origen": self._credentials.origen},
                    )
                except Exception as exc:
                    # Sin guardarlo, el próximo refresco fallará: queda en el registro.
                    logger.error(
                        "storage_failed operation=whoop_token_write kind=%s", type(exc).__name__
                    )
            self._token = data["access_token"]
            self._expires = time.monotonic() + int(data.get("expires_in", 3600)) - 60
            return self._token

    async def _get(self, path: str, params: dict[str, Any], store: Store | None) -> Any:
        token = await self._access_token(store)
        async with self._client() as client:
            response = await client.get(
                f"{API}/{path}", params=params, headers={"Authorization": f"Bearer {token}"}
            )
        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            raise WhoopError(f"HTTP {response.status_code}")
        return response.json()

    async def sleep_habits(self, zone_name: str, store: Store | None) -> dict[str, Any] | None:
        """Horas promedio de dormir y despertar de las últimas dos semanas."""
        sleeps = await self._get("activity/sleep", {"limit": 25}, store)
        return sleep_habits_from((sleeps or {}).get("records") or [], zone_name)

    async def summary(self, zone_name: str, store: Store | None) -> dict[str, Any]:
        # El primer GET refresca el token; los otros dos lo reutilizan.
        recovery = await self._get("recovery", {"limit": 1}, store)
        sleeps, cycles = await asyncio.gather(
            self._get("activity/sleep", {"limit": 5}, store),
            self._get("cycle", {"limit": 2}, store),
        )
        records = (recovery or {}).get("records") or []
        return build_summary(
            records[0] if records else None,
            (sleeps or {}).get("records") or [],
            (cycles or {}).get("records") or [],
            zone_name,
        )


def _clock_average(moments: list[datetime]) -> str:
    """Promedio de horas del día en un círculo (23:50 y 00:10 promedian 00:00)."""
    angles = [2 * math.pi * (m.hour * 60 + m.minute) / 1440 for m in moments]
    mean = cmath.phase(sum(cmath.exp(1j * angle) for angle in angles))
    minutes = round((mean % (2 * math.pi)) / (2 * math.pi) * 1440) % 1440
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def sleep_habits_from(sleeps: list[dict[str, Any]], zone_name: str) -> dict[str, Any] | None:
    zone = ZoneInfo(zone_name)
    nights = [
        item for item in sleeps if not item.get("nap") and item.get("start") and item.get("end")
    ][:14]
    if len(nights) < 3:
        return None

    def local(value: str) -> datetime:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(zone)

    return {
        "se_duerme": _clock_average([local(item["start"]) for item in nights]),
        "despierta": _clock_average([local(item["end"]) for item in nights]),
        "noches": len(nights),
    }


_client: Whoop | None = None
_client_lock = threading.Lock()


def get_whoop() -> Whoop:
    global _client
    with _client_lock:
        if _client is None:
            _client = Whoop(credentials_from_env())
        return _client


def set_whoop(client: Whoop | None) -> None:
    """Para pruebas: reemplaza el cliente compartido."""
    global _client
    with _client_lock:
        _client = client
