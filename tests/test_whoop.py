import json
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs

import httpx
import pytest

from app import whoop
from app.context import ToolContext
from app.storage import LocalStore
from app.tools.consultar_whoop import consultar_whoop
from app.whoop import Credenciales, Whoop, build_summary, color_recuperacion, credentials_from_env

ZONE = "America/Monterrey"
TODAY = date(2026, 11, 28)
CREDS = Credenciales("cliente", "secreto-de-prueba", "refresh-inicial")
NIGHT = {
    "id": "sueno-1",
    "nap": False,
    "score_state": "SCORED",
    "start": "2026-11-28T05:30:00.000Z",
    # 12:40 UTC = 06:40 en Monterrey del 28.
    "end": "2026-11-28T12:40:00.000Z",
    "score": {
        "stage_summary": {
            "total_light_sleep_time_milli": 12_600_000,
            "total_slow_wave_sleep_time_milli": 5_400_000,
            "total_rem_sleep_time_milli": 7_800_000,
        },
        "sleep_performance_percentage": 91.6,
        "sleep_efficiency_percentage": 93.2,
        "sleep_needed": {"baseline_milli": 27_000_000, "need_from_sleep_debt_milli": 1_800_000},
    },
}
NAP = {**NIGHT, "id": "siesta", "nap": True, "end": "2026-11-28T20:00:00.000Z"}
RECOVERY = {
    "sleep_id": "sueno-1",
    "score_state": "SCORED",
    "score": {
        "recovery_score": 72.4,
        "hrv_rmssd_milli": 58.3,
        "resting_heart_rate": 51.6,
        "user_calibrating": False,
    },
}
CYCLES = [
    {"score_state": "PENDING_SCORE", "score": None},
    {"score_state": "SCORED", "score": {"strain": 12.43}},
]


def test_recovery_colors_follow_whoop_bands():
    assert [color_recuperacion(v) for v in (100, 67, 66, 34, 33, 0)] == [
        "verde",
        "verde",
        "amarilla",
        "amarilla",
        "roja",
        "roja",
    ]


def test_ready_summary_is_written_by_the_server():
    result = build_summary(RECOVERY, [NAP, NIGHT], CYCLES, ZONE, TODAY)
    assert result["estado"] == "listo"
    assert result["texto"] == (
        "Su recuperación es de 72 por ciento, verde. Durmió 7 horas y 10 minutos, con 92 por "
        "ciento de rendimiento de sueño. Su variabilidad cardiaca es de 58 milisegundos y su "
        "frecuencia en reposo de 52 latidos por minuto. Ayer su esfuerzo fue de 12,4."
    )
    assert result["sueno"]["profundo_min"] == 90
    assert result["sueno"]["rem_min"] == 130
    assert result["sueno"]["necesario_min"] == 480
    assert result["esfuerzo_ayer"] == 12.4


def test_night_not_closed_or_recovery_pending_is_calculating():
    yesterday = {**NIGHT, "end": "2026-11-27T12:40:00.000Z"}
    assert build_summary(RECOVERY, [yesterday], CYCLES, ZONE, TODAY)["estado"] == "calculando"
    pending = {**RECOVERY, "score_state": "PENDING_SCORE"}
    assert build_summary(pending, [NIGHT], CYCLES, ZONE, TODAY)["estado"] == "calculando"
    # La recuperación más reciente todavía es de la noche anterior.
    old = {**RECOVERY, "sleep_id": "otra"}
    assert build_summary(old, [NIGHT], CYCLES, ZONE, TODAY)["estado"] == "calculando"
    assert build_summary(None, [], [], ZONE, TODAY)["estado"] == "sin_datos"


def test_unscorable_and_calibrating():
    unscorable = {**RECOVERY, "score_state": "UNSCORABLE", "score": None}
    result = build_summary(unscorable, [NIGHT], [], ZONE, TODAY)
    assert result["estado"] == "listo"
    assert result["texto"].startswith("WHOOP no pudo calcular su recuperación de hoy.")
    calibrating = {**RECOVERY, "score": {**RECOVERY["score"], "user_calibrating": True}}
    text = build_summary(calibrating, [NIGHT], [], ZONE, TODAY)["texto"]
    assert text.endswith("WHOOP todavía se está calibrando, así que tómelo con reserva.")


def test_credentials_come_from_environment():
    raw = json.dumps({"client_id": "a", "client_secret": "b", "refresh_token": "c"})
    assert credentials_from_env({"JARVIS_WHOOP": raw}) == Credenciales("a", "b", "c")
    assert credentials_from_env({}) is None
    with pytest.raises(ValueError):
        credentials_from_env({"JARVIS_WHOOP": "{}"})


class FakeWhoop:
    def __init__(self):
        self.refreshes = []
        self.valid = {"refresh-inicial"}
        self.counter = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/oauth/oauth2/token":
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            assert form["scope"] == "offline" and form["client_secret"] == "secreto-de-prueba"
            self.refreshes.append(form["refresh_token"])
            if form["refresh_token"] not in self.valid:
                return httpx.Response(400, json={"error": "invalid_grant"})
            # WHOOP rota el refresh token: el usado deja de servir.
            self.valid.discard(form["refresh_token"])
            self.counter += 1
            new = f"refresh-{self.counter}"
            self.valid.add(new)
            return httpx.Response(
                200, json={"access_token": "acceso", "refresh_token": new, "expires_in": 3600}
            )
        assert request.headers["Authorization"] == "Bearer acceso"
        path = request.url.path.removeprefix("/developer/v2/")
        records = {"recovery": [RECOVERY], "activity/sleep": [NIGHT], "cycle": CYCLES}[path]
        return httpx.Response(200, json={"records": records})


def client_for(fake, credentials=CREDS):
    return Whoop(credentials, transport=httpx.MockTransport(fake.handler))


async def test_rotated_refresh_token_is_saved_and_reused(tmp_path):
    store = LocalStore("principal", tmp_path / "estado.json")
    fake = FakeWhoop()
    await client_for(fake).summary(ZONE, store)
    assert fake.refreshes == ["refresh-inicial"]
    assert store.read_whoop_token()["refresh_token"] == "refresh-1"
    # Otro arranque del servidor (cliente nuevo) usa el token guardado, no el del secreto.
    await client_for(fake).summary(ZONE, store)
    assert fake.refreshes == ["refresh-inicial", "refresh-1"]
    assert store.read_whoop_token()["refresh_token"] == "refresh-2"


async def test_new_authorization_replaces_the_saved_token(tmp_path):
    store = LocalStore("principal", tmp_path / "estado.json")
    store.write_whoop_token({"refresh_token": "viejo", "origen": CREDS.origen})
    fake = FakeWhoop()
    fake.valid = {"refresh-reautorizado"}
    reauthorized = Credenciales("cliente", "secreto-de-prueba", "refresh-reautorizado")
    await client_for(fake, reauthorized).summary(ZONE, store)
    assert fake.refreshes == ["refresh-reautorizado"]


async def test_tool_reports_missing_configuration(monkeypatch):
    monkeypatch.delenv("JARVIS_WHOOP", raising=False)
    whoop.set_whoop(None)
    result = await consultar_whoop(context=ToolContext(ZONE, "coordenadas", "Monterrey"))
    assert result == {"ok": False, "mensaje": "WHOOP todavía no está conectado a JARVIS."}


@pytest.mark.parametrize(
    ("summary", "expected"),
    [
        (None, {"respuesta": "Buenos días."}),
        (
            {"estado": "calculando", "texto": "x"},
            {
                "respuesta": "Buenos días. WHOOP todavía está calculando su noche; en cuanto "
                "termine le doy su recuperación.",
                "whoop_pendiente": True,
            },
        ),
        (
            {"estado": "listo", "texto": "Su recuperación es de 72 por ciento, verde."},
            {
                "respuesta": "Buenos días. Su recuperación es de 72 por ciento, verde.",
                "whoop_pendiente": False,
            },
        ),
    ],
)
def test_briefing_appends_whoop(client, monkeypatch, summary, expected):
    from tests.conftest import AUTH

    monkeypatch.setattr("app.main.whoop_summary", AsyncMock(return_value=summary))
    client.app.state.briefing = SimpleNamespace(create=AsyncMock(return_value="Buenos días."))
    response = client.post(
        "/briefing",
        json={"fecha_iso": "2026-11-28", "eventos": [], "recordatorios": []},
        headers=AUTH,
    )
    assert response.status_code == 200
    assert response.json() == expected


def test_whoop_endpoint_for_the_shortcut(client, monkeypatch):
    from tests.conftest import AUTH

    assert client.post("/whoop", json={}).status_code == 401
    monkeypatch.setattr(
        "app.main.whoop_summary", AsyncMock(return_value={"estado": "calculando", "texto": "Aún."})
    )
    assert client.post("/whoop", json={}, headers=AUTH).json() == {
        "listo": False,
        "respuesta": "Aún.",
    }
    monkeypatch.setattr(
        "app.main.whoop_summary", AsyncMock(return_value={"estado": "listo", "texto": "Verde."})
    )
    assert client.post("/whoop", json={}, headers=AUTH).json() == {
        "listo": True,
        "respuesta": "Verde.",
    }
