import base64
import json
from urllib.parse import parse_qs

import httpx
import pytest

from app import gmail
from app.context import ToolContext
from app.gmail import Credenciales, Gmail, credentials_from_env, validate_message_id
from app.tools.consultar_correo import consultar_correo
from app.tools.leer_correo import leer_correo

CREDS = Credenciales("cliente", "secreto-de-prueba", "refresh-de-prueba")


def b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


MESSAGES = {
    "m1": {
        "id": "m1",
        "labelIds": ["INBOX", "UNREAD"],
        "snippet": "Su vuelo VB 1151 sale a las 12:13 &amp; aborda en sala 3",
        # 2026-11-27 16:00 UTC = 10:00 en Monterrey.
        "internalDate": "1795795200000",
        "payload": {
            "mimeType": "multipart/alternative",
            "headers": [
                {"name": "From", "value": "Viva Aerobus <avisos@vivaaerobus.com>"},
                {"name": "Subject", "value": "Pase de abordar"},
            ],
            "parts": [
                {"mimeType": "text/plain", "body": {"data": b64("Hola Dr.\n\n\n\nSala   3.")}},
                {"mimeType": "text/html", "body": {"data": b64("<p>ignorado</p>")}},
            ],
        },
    },
    "m2": {
        "id": "m2",
        "labelIds": ["INBOX"],
        "snippet": "Programa preliminar",
        "internalDate": "1795708800000",
        "payload": {
            "mimeType": "text/html",
            "headers": [{"name": "Subject", "value": "Congreso"}],
            "body": {"data": b64("<style>x{}</style><p>Día&nbsp;1</p><div>Plenaria</div>")},
        },
    },
}


class FakeGmail:
    def __init__(self, token_status=200):
        self.token_status = token_status
        self.token_calls = 0
        self.requests = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.googleapis.com":
            self.token_calls += 1
            form = parse_qs(request.content.decode())
            assert form["grant_type"] == ["refresh_token"]
            assert form["refresh_token"] == ["refresh-de-prueba"]
            if self.token_status != 200:
                return httpx.Response(self.token_status, json={"error": "invalid_grant"})
            return httpx.Response(200, json={"access_token": "acceso", "expires_in": 3600})
        self.requests.append(request)
        assert request.method == "GET"
        assert request.headers["Authorization"] == "Bearer acceso"
        path = request.url.path.removeprefix("/gmail/v1/users/me/")
        if path == "messages":
            ids = ["m1", "m2"][: int(request.url.params["maxResults"])]
            return httpx.Response(200, json={"messages": [{"id": i} for i in ids]})
        message = MESSAGES.get(path.removeprefix("messages/"))
        return httpx.Response(200, json=message) if message else httpx.Response(404)


@pytest.fixture
def fake():
    fake = FakeGmail()
    gmail.set_gmail(Gmail(CREDS, transport=httpx.MockTransport(fake.handler)))
    yield fake
    gmail.set_gmail(None)


CONTEXT = ToolContext("America/Monterrey", "coordenadas", "Monterrey")


def test_credentials_come_from_environment():
    raw = json.dumps({"client_id": "a", "client_secret": "b", "refresh_token": "c"})
    assert credentials_from_env({"JARVIS_GMAIL": raw}) == Credenciales("a", "b", "c")
    assert credentials_from_env({}) is None
    with pytest.raises(ValueError):
        credentials_from_env({"JARVIS_GMAIL": '{"client_id": "a"}'})


def test_message_ids_are_validated():
    assert validate_message_id(" 18c2abF ") == "18c2abF"
    for value in ("", "../x", "a/b", "x" * 65):
        with pytest.raises(ValueError):
            validate_message_id(value)


async def test_search_returns_local_summaries_and_reuses_the_token(fake):
    result = await consultar_correo(None, None, context=CONTEXT)
    assert result["ok"] is True
    assert result["busqueda"] == "in:inbox newer_than:2d"
    assert result["correos"][0] == {
        "id": "m1",
        "de": "Viva Aerobus <avisos@vivaaerobus.com>",
        "asunto": "Pase de abordar",
        "fecha": "2026-11-27 10:00",
        "extracto": "Su vuelo VB 1151 sale a las 12:13 & aborda en sala 3",
        "no_leido": True,
    }
    assert result["correos"][1]["asunto"] == "Congreso"
    assert result["correos"][1]["de"] == ""
    await consultar_correo("is:unread", 1, context=CONTEXT)
    assert fake.token_calls == 1
    assert fake.requests[-2].url.params["q"] == "is:unread"
    assert fake.requests[-2].url.params["maxResults"] == "1"
    assert fake.requests[1].url.params.get_list("metadataHeaders") == ["From", "Subject"]


async def test_quantity_is_clamped(fake):
    await consultar_correo("x", 50, context=CONTEXT)
    assert fake.requests[0].url.params["maxResults"] == "10"
    await consultar_correo("x", 0, context=CONTEXT)
    assert fake.requests[-2].url.params["maxResults"] == "1"


async def test_read_prefers_plain_text_and_falls_back_to_html(fake):
    first = await leer_correo("m1", context=CONTEXT)
    assert first["correo"]["texto"] == "Hola Dr.\n\nSala 3."
    second = await leer_correo("m2", context=CONTEXT)
    assert second["correo"]["texto"] == "Día 1\nPlenaria"
    assert "x{}" not in second["correo"]["texto"]
    assert (await leer_correo("noexiste", context=CONTEXT))["ok"] is False
    assert (await leer_correo("../m1", context=CONTEXT))["ok"] is False


async def test_without_configuration_or_with_revoked_token(monkeypatch):
    monkeypatch.delenv("JARVIS_GMAIL", raising=False)
    gmail.set_gmail(None)
    result = await consultar_correo(None, None, context=CONTEXT)
    assert result == {"ok": False, "mensaje": "El correo todavía no está conectado a JARVIS."}
    revoked = FakeGmail(token_status=400)
    gmail.set_gmail(Gmail(CREDS, transport=httpx.MockTransport(revoked.handler)))
    try:
        result = await consultar_correo(None, None, context=CONTEXT)
    finally:
        gmail.set_gmail(None)
    assert result == {"ok": False, "mensaje": "Gmail no respondió; intenta más tarde."}
