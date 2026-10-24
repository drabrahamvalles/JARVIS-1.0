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


def test_missing_openai_key_is_explicit(config):
    with TestClient(create_app(config=config, secrets=Secrets(jarvis_token=TOKEN))) as client:
        response = client.post("/ask", json={"texto": "Hola"}, headers=AUTH)
        assert response.status_code == 503
        assert response.json() == {"detail": "OPENAI_API_KEY no configurada"}


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
