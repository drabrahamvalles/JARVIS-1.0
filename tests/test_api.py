from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx2
import pytest
from fastapi.testclient import TestClient
from openai import APIConnectionError, APIStatusError, APITimeoutError, RateLimitError

from app.brain import BrainError
from app.main import create_app
from app.settings import Secrets
from tests.conftest import AUTH, TOKEN

BRIEFING_PAYLOAD = {
    "fecha_iso": "2026-10-24",
    "lat": 23.2494,
    "lon": -106.4111,
    "ciudad": "Mazatlán",
    "eventos": [],
    "recordatorios": [],
}


def test_health_without_credentials(config):
    with TestClient(create_app(config=config, secrets=Secrets())) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        assert client.post("/ask", json={"texto": "Hola"}).status_code == 503


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_interactive_docs_are_available_on_mac(config, monkeypatch, path):
    monkeypatch.setenv("HOST", "127.0.0.1")
    with TestClient(create_app(config=config, secrets=Secrets())) as client:
        assert client.get(path).status_code == 200


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_interactive_docs_are_disabled_on_cloud_run(config, monkeypatch, path):
    monkeypatch.setenv("HOST", "0.0.0.0")
    with TestClient(create_app(config=config, secrets=Secrets())) as client:
        assert client.get(path).status_code == 404


@pytest.mark.parametrize(
    "headers", [{}, {"Authorization": "Bearer incorrecto"}, {"Authorization": "Basic incorrecto"}]
)
def test_ask_requires_bearer(client, headers):
    response = client.post("/ask", json={"texto": "Hola"}, headers=headers)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    client.app.state.brain.ask.assert_not_awaited()


@pytest.mark.parametrize(
    "headers", [{}, {"Authorization": "Bearer incorrecto"}, {"Authorization": "Basic x"}]
)
def test_briefing_requires_bearer(client, headers):
    response = client.post("/briefing", json=BRIEFING_PAYLOAD, headers=headers)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    client.app.state.briefing.create.assert_not_awaited()


def test_missing_openai_key_is_explicit(config):
    with TestClient(create_app(config=config, secrets=Secrets(jarvis_token=TOKEN))) as client:
        response = client.post("/ask", json={"texto": "Hola"}, headers=AUTH)
        assert response.status_code == 503
        assert response.json() == {"detail": "OPENAI_API_KEY no configurada"}
        briefing = client.post("/briefing", json=BRIEFING_PAYLOAD, headers=AUTH)
        assert briefing.status_code == 503
        assert briefing.json() == {"detail": "OPENAI_API_KEY no configurada"}


def test_ask_contract_and_default_timezone(client):
    response = client.post("/ask", json={"texto": "Hola"}, headers=AUTH)
    assert response.status_code == 200
    assert response.json() == {"respuesta": "A su servicio, Dr. Valles."}
    payload, context = client.app.state.brain.ask.await_args.args
    assert payload.texto == "Hola"
    assert context.zona_horaria == "America/Monterrey"
    assert context.origen_zona_horaria == "por_defecto"


def test_ask_gps_changes_timezone_for_this_request_only(client):
    payload = {"texto": "¿Qué hora es?", "lat": 35.6762, "lon": 139.6503, "dispositivo": "iPhone"}
    assert client.post("/ask", json=payload, headers=AUTH).status_code == 200
    _, context = client.app.state.brain.ask.await_args.args
    assert context.zona_horaria == "Asia/Tokyo"
    assert context.origen_zona_horaria == "coordenadas"
    assert context.dispositivo == "iPhone"
    assert client.post("/ask", json={"texto": "Hola"}, headers=AUTH).status_code == 200
    _, next_context = client.app.state.brain.ask.await_args.args
    assert next_context.zona_horaria == "America/Monterrey"


@pytest.mark.parametrize(
    ("fecha_iso", "expected"),
    [
        ("2026-10-24", date(2026, 10, 24)),
        ("2026-10-24T07:00:00-07:00", date(2026, 10, 24)),
    ],
)
def test_briefing_accepts_both_iso_date_formats(client, fecha_iso, expected):
    response = client.post(
        "/briefing", json={**BRIEFING_PAYLOAD, "fecha_iso": fecha_iso}, headers=AUTH
    )
    assert response.status_code == 200
    assert response.json() == {"respuesta": "Buenos días, Dr. Valles. Hoy no tiene pendientes."}
    payload, context = client.app.state.briefing.create.await_args.args
    assert payload.fecha_iso == expected
    assert payload.ciudad == "Mazatlán"
    assert context.zona_horaria == "America/Mazatlan"


def test_briefing_empty_location_uses_configured_coordinates(client, config):
    payload = {
        "fecha_iso": "2026-10-24T07:00:00-07:00",
        "lat": "",
        "lon": "",
        "eventos": [],
        "recordatorios": [],
    }
    assert client.post("/briefing", json=payload, headers=AUTH).status_code == 200
    request, context = client.app.state.briefing.create.await_args.args
    assert request.lat is None and request.lon is None and request.ciudad is None
    assert context.latitud_clima == config.latitud_por_defecto
    assert context.longitud_clima == config.longitud_por_defecto
    assert context.zona_horaria == "America/Monterrey"


@pytest.mark.parametrize(
    ("eventos", "recordatorios", "expected_events", "expected_reminders"),
    [
        (
            "09:00 Reunión\n\n12:30 Llamada\n",
            "Comprar café\n  \nEnviar informe",
            ["09:00 Reunión", "12:30 Llamada"],
            ["Comprar café", "Enviar informe"],
        ),
        (
            ["09:00 Reunión", "12:30 Llamada"],
            ["Comprar café"],
            ["09:00 Reunión", "12:30 Llamada"],
            ["Comprar café"],
        ),
        ("\n  \n", "", [], []),
    ],
)
def test_briefing_accepts_shortcuts_text_lists_and_empty_values(
    client, eventos, recordatorios, expected_events, expected_reminders
):
    payload = {
        **BRIEFING_PAYLOAD,
        "eventos": eventos,
        "recordatorios": recordatorios,
    }
    assert client.post("/briefing", json=payload, headers=AUTH).status_code == 200
    request, _ = client.app.state.briefing.create.await_args.args
    assert request.eventos == expected_events
    assert request.recordatorios == expected_reminders


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"texto": " "},
        {"texto": 123},
        {"texto": "a" * 12001},
        {"texto": "Hola", "lat": 20},
        {"texto": "Hola", "lon": -100},
        {"texto": "Hola", "lat": 91, "lon": 0},
        {"texto": "Hola", "lat": 0, "lon": -181},
        {"texto": "Hola", "lat": "20", "lon": 0},
        {"texto": "Hola", "lat": True, "lon": 0},
        {"texto": "Hola", "dispositivo": " "},
        {"texto": "Hola", "no_existe": True},
    ],
)
def test_invalid_input_never_reaches_openai(client, payload):
    assert client.post("/ask", json=payload, headers=AUTH).status_code == 422
    client.app.state.brain.ask.assert_not_awaited()


@pytest.mark.parametrize(
    "kind,expected_status",
    [("timeout", 504), ("rate", 503), ("connection", 502), ("status", 502), ("brain", 502)],
)
def test_upstream_errors_do_not_leak_details(client, kind, expected_status):
    request = httpx2.Request("POST", "https://api.openai.com/v1/responses")
    response = httpx2.Response(500, request=request)
    errors = {
        "timeout": APITimeoutError(request=request),
        "rate": RateLimitError("secret-private-data", response=response, body=None),
        "connection": APIConnectionError(request=request),
        "status": APIStatusError("secret-private-data", response=response, body=None),
        "brain": BrainError("secret-private-data"),
    }
    client.app.state.brain = SimpleNamespace(ask=AsyncMock(side_effect=errors[kind]))
    result = client.post("/ask", json={"texto": "Hola"}, headers=AUTH)
    assert result.status_code == expected_status
    assert "secret-private-data" not in result.text
