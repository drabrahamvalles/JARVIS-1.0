"""Avisos de salida: le dicen al Dr. Valles, en voz alta, cuándo salir a cada evento.

El despertador de Cloud Scheduler llama POST /tareas/avisos cada 10 minutos de 4:00 a
23:50. Para cada evento con hora de las próximas horas:

1. Hora de llegada: la del evento; en vuelos, 3 h antes si es internacional y 2 h si es
   nacional (aeropuertos de config.yaml).
2. Hora real de salida = llegada − camino con tráfico (Routes API, con la predicción para
   la hora de salida). Desde una hora antes de salir se recalcula cada 15 minutos.
3. Tres avisos: 20 min antes de la hora real («salga en 15 minutos», con 5 de colchón),
   5 min antes («ya es hora de salir») y a la hora real, solo si sigue donde estaba
   («ya se tiene que ir, ya va tarde»).

Para que el iPhone hable sin que lo toquen, cada aviso es un correo de JARVIS a la misma
cuenta de Gmail con el asunto «Aviso de JARVIS»; un Atajo con el disparador de correo lo
lee en voz alta. No hay secretos nuevos: Routes API se llama con la cuenta de servicio.
"""

import logging
import math
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from starlette.concurrency import run_in_threadpool

from app.calendario import Evento, get_calendar
from app.expediente import read_all as read_profile
from app.expediente import resolve_place
from app.gmail import get_gmail
from app.storage import Store

usage_logger = logging.getLogger("jarvis.usage")

ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
SCOPES = ("https://www.googleapis.com/auth/cloud-platform",)
ASUNTO = "Aviso de JARVIS"
HORIZONTE = timedelta(hours=6)
# Primer cálculo del camino cuando falta esto para la hora de llegada.
PRIMER_CALCULO = timedelta(hours=4)
# Desde una hora antes de salir, el camino se recalcula cada 15 minutos.
VIGILAR_DESDE = timedelta(hours=1)
RECALCULAR_CADA = timedelta(minutes=15)
RECALCULAR_LEJOS = timedelta(hours=1)
ANTICIPO_NACIONAL = timedelta(hours=2)
ANTICIPO_INTERNACIONAL = timedelta(hours=3)
UBICACION_VIEJA = timedelta(hours=12)
# Si la ubicación nueva está a más de esto de donde estaba en el primer aviso, ya salió.
YA_SALIO_METROS = 300
MAX_CONSULTAS_DIA = 40
SIN_CAMINO_ANTES = timedelta(minutes=30)
_IATA = re.compile(r"\b[A-Z]{3}\b")
# (aviso, minutos antes de la hora real de salida)
AVISOS = (("aviso_15", 20), ("aviso_hora", 5), ("aviso_tarde", 0))


def distance_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 6_371_000 * 2 * math.asin(math.sqrt(h))


@dataclass(frozen=True)
class Plan:
    llegada: datetime
    destino: str | None
    motivo: str


def plan_for(event: Evento, start: datetime, airports: dict[str, str]) -> Plan:
    """Hora a la que hay que llegar, a dónde y cómo explicarlo."""
    title = event.titulo
    if "vuelo" not in title.casefold():
        return Plan(start, event.lugar, f"su {title} es a las {start:%H:%M}")
    codes = _IATA.findall(title)
    national = bool(codes) and all(code in airports for code in codes)
    lead = ANTICIPO_NACIONAL if national else ANTICIPO_INTERNACIONAL
    first = codes[0] if codes else None
    if event.lugar:
        destination = event.lugar
    elif first in airports:
        destination = f"Aeropuerto de {airports[first]}"
    else:
        destination = f"Aeropuerto {first}" if first else None
    arrive = start - lead
    hours = int(lead.total_seconds() // 3600)
    kind = "nacional" if national else "internacional"
    return Plan(
        arrive,
        destination,
        f"su vuelo sale a las {start:%H:%M}; como es {kind}, debe estar en el aeropuerto "
        f"{hours} horas antes, a las {arrive:%H:%M}",
    )


def message_for(notice: str, plan: Plan, minutes: int | None) -> str:
    way = f" Hay {minutes} minutos de camino." if minutes is not None else ""
    if notice == "aviso_15":
        return f"Doctor, le recomiendo salir en 15 minutos: {plan.motivo}.{way}"
    if notice == "aviso_hora":
        return f"Doctor, ya es hora de salir: {plan.motivo}.{way}"
    return f"Doctor, ya se tiene que ir, ya va tarde: {plan.motivo}.{way}"


def _start(event: Evento, zone: ZoneInfo) -> datetime | None:
    if event.todo_el_dia:
        return None
    try:
        return datetime.strptime(event.inicio, "%Y-%m-%d %H:%M").replace(tzinfo=zone)
    except ValueError:
        return None


def due_notice(info: dict[str, Any], leave: datetime, now: datetime) -> str | None:
    """El aviso que toca ahora (el más reciente que ya venció y no se ha dicho)."""
    due = None
    for notice, before in AVISOS:
        if now >= leave - timedelta(minutes=before):
            due = notice
    if due is None or info.get(due):
        return None
    return due


class Avisos:
    def __init__(
        self,
        airports: dict[str, str],
        *,
        credentials: Any = None,
        project: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.airports = airports
        self._credentials = credentials
        self._project = project
        self._transport = transport
        self._lock = threading.Lock()
        self._own_address: str | None = None

    def _token(self) -> tuple[str, str]:
        with self._lock:
            if self._credentials is None:
                import google.auth

                self._credentials, project = google.auth.default(scopes=list(SCOPES))
                self._project = self._project or project
            if not self._credentials.valid:
                from google.auth.transport.requests import Request

                self._credentials.refresh(Request())
            return self._credentials.token, self._project or ""

    async def travel_minutes(
        self, origin: tuple[float, float], destination: str, departure: datetime | None
    ) -> int | None:
        token, project = await run_in_threadpool(self._token)
        body: dict[str, Any] = {
            "origin": {"location": {"latLng": {"latitude": origin[0], "longitude": origin[1]}}},
            "destination": {"address": destination},
            "travelMode": "DRIVE",
            "routingPreference": "TRAFFIC_AWARE",
            "languageCode": "es-MX",
        }
        if departure is not None:
            # Predicción del tráfico para la hora en que va a salir.
            body["departureTime"] = departure.isoformat()
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(8.0, connect=3.0), transport=self._transport
        ) as client:
            response = await client.post(
                ROUTES_URL,
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-Goog-User-Project": project,
                    "X-Goog-FieldMask": "routes.duration",
                },
                json=body,
            )
        usage_logger.info("routes_api status=%d", response.status_code)
        if response.status_code != 200:
            return None
        routes = response.json().get("routes") or []
        try:
            seconds = int(str(routes[0]["duration"]).rstrip("s"))
        except (IndexError, KeyError, ValueError):
            return None
        return max(1, round(seconds / 60))

    async def speak(self, text: str) -> None:
        gmail = get_gmail()
        if self._own_address is None:
            self._own_address = await gmail.own_address()
        await gmail.send([self._own_address], ASUNTO, text)

    async def run(self, store: Store, zone_name: str) -> dict[str, Any]:
        zone = ZoneInfo(zone_name)
        now = datetime.now(zone)
        state = await run_in_threadpool(store.read_avisos_salida) or {}
        tracked: dict[str, dict[str, Any]] = dict(state.get("eventos") or {})
        today = now.date().isoformat()
        calls = int((state.get("consultas") or {}).get(today, 0))

        here = None
        location = await run_in_threadpool(store.read_ubicacion)
        if location:
            try:
                if now - datetime.fromisoformat(location["en"]) <= UBICACION_VIEJA:
                    here = (float(location["lat"]), float(location["lon"]))
            except (KeyError, TypeError, ValueError):
                here = None

        try:
            places = (await run_in_threadpool(read_profile, store))["lugares"]
        except Exception:
            places = []
        events = await get_calendar().list_events(now.date(), (now + HORIZONTE).date(), zone_name)
        spoken = []
        for event in events:
            start = _start(event, zone)
            if start is None or not now <= start <= now + HORIZONTE:
                continue
            plan = plan_for(event, start, self.airports)
            # «Consultorio» o «Cita en el hospital» se traducen a la dirección guardada.
            saved = resolve_place(places, event.lugar, event.titulo)
            if saved and not ("vuelo" in event.titulo.casefold() and event.lugar):
                plan = Plan(plan.llegada, saved, plan.motivo)
            if plan.llegada - now > PRIMER_CALCULO:
                continue
            info = tracked.setdefault(f"{event.id}@{event.inicio}", {})
            minutes = info.get("minutos")

            if plan.destino and here is not None and not info.get("aviso_tarde"):
                leave = plan.llegada - timedelta(minutes=minutes) if minutes else None
                checked = info.get("calculado_en")
                age = now - datetime.fromisoformat(checked) if checked else None
                watching = leave is not None and leave - now <= VIGILAR_DESDE
                every = RECALCULAR_CADA if watching else RECALCULAR_LEJOS
                if (age is None or age >= every) and calls < MAX_CONSULTAS_DIA:
                    calls += 1
                    departure = leave if leave is not None and leave > now else None
                    new = await self.travel_minutes(here, plan.destino, departure)
                    if new is not None:
                        minutes = info["minutos"] = new
                        info["calculado_en"] = now.isoformat()

            if minutes is None:
                # Sin lugar, sin ubicación o sin ruta: un solo aviso media hora antes.
                if plan.llegada - now <= SIN_CAMINO_ANTES and not info.get("aviso_hora"):
                    await self.speak(message_for("aviso_hora", plan, None))
                    info["aviso_hora"] = now.isoformat()
                    spoken.append(event.titulo)
                continue

            leave = plan.llegada - timedelta(minutes=minutes)
            notice = due_notice(info, leave, now)
            if notice is None:
                continue
            if notice == "aviso_tarde":
                # Solo si sigue en el mismo lugar que en el primer aviso.
                origin = info.get("origen")
                if origin and here and distance_m((origin[0], origin[1]), here) > YA_SALIO_METROS:
                    info[notice] = "ya_salio"
                    continue
            await self.speak(message_for(notice, plan, minutes))
            for earlier, _ in AVISOS[: [n for n, _ in AVISOS].index(notice) + 1]:
                info.setdefault(earlier, now.isoformat())
            if here and "origen" not in info:
                info["origen"] = list(here)
            spoken.append(event.titulo)

        cutoff = now - timedelta(days=1)
        kept = {}
        for key, value in tracked.items():
            try:
                when = datetime.strptime(key.rsplit("@", 1)[1], "%Y-%m-%d %H:%M")
            except (IndexError, ValueError):
                continue
            if when.replace(tzinfo=zone) >= cutoff:
                kept[key] = value
        await run_in_threadpool(
            store.write_avisos_salida, {"eventos": kept, "consultas": {today: calls}}
        )
        usage_logger.info("avisos_salida eventos=%d hablados=%d", len(events), len(spoken))
        return {"hablados": spoken}
