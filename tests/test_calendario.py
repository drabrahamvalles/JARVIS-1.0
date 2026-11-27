import json
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest

from app import calendario
from app.calendario import (
    CalendarioNoConfigurado,
    GoogleCalendar,
    calendar_ids_from_env,
    decode_event_id,
)
from app.context import ToolContext
from app.storage import LocalStore
from app.tools.confirmar_borrado_evento import confirmar_borrado_evento, es_confirmacion
from app.tools.consultar_agenda import consultar_agenda
from app.tools.proponer_borrado_evento import proponer_borrado_evento

CALENDARS = ("principal@example.com", "otro@example.com")
FLIGHT = {
    "id": "vuelo123",
    "status": "confirmed",
    "summary": "Vuelo MZT → MTY (VB 1151 / VB 1126)",
    "location": "Aeropuerto de Mazatlán",
    "start": {"dateTime": "2026-10-25T12:13:00-07:00"},
    "end": {"dateTime": "2026-10-25T17:35:00-07:00"},
}
CONGRESS = {
    "id": "congreso9",
    "summary": "Congreso de Psiquiatría",
    "start": {"date": "2026-11-05"},
    "end": {"date": "2026-11-07"},
}


class FakeGoogle:
    def __init__(self, items_by_calendar):
        self.items = items_by_calendar
        self.requests = []
        self.deleted = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert request.headers["Authorization"] == "Bearer token-de-prueba"
        parts = request.url.path.split("/")
        calendar = httpx.URL(f"https://x/{parts[4]}").path[1:]
        calendar = calendar.replace("%40", "@")
        items = self.items.get(calendar)
        if items is None:
            return httpx.Response(404)
        if request.method == "GET" and parts[-1] == "events":
            return httpx.Response(200, json={"items": items})
        event = next((item for item in items if item["id"] == parts[-1]), None)
        if event is None:
            return httpx.Response(404)
        if request.method == "DELETE":
            assert request.url.params["sendUpdates"] == "none"
            self.deleted.append(event["id"])
            items.remove(event)
            return httpx.Response(204)
        return httpx.Response(200, json=event)


@pytest.fixture
def google(monkeypatch):
    fake = FakeGoogle(
        {CALENDARS[0]: [FLIGHT.copy(), CONGRESS.copy()], CALENDARS[1]: [FLIGHT.copy()]}
    )
    client = GoogleCalendar(
        CALENDARS,
        credentials=SimpleNamespace(valid=True, token="token-de-prueba"),
        transport=httpx.MockTransport(fake.handler),
    )
    calendario.set_calendar(client)
    yield fake
    calendario.set_calendar(None)


def context_for(tmp_path, *, request_id="peticion-1", text="", zone="America/Mazatlan"):
    store = LocalStore("principal", tmp_path / "estado.json")
    return ToolContext(
        zone, "coordenadas", "Monterrey", store=store, solicitud_id=request_id, texto_usuario=text
    )


def test_calendar_ids_come_from_environment():
    assert calendar_ids_from_env({"JARVIS_CALENDARIOS": " a@x.com, ,b@y.com "}) == (
        "a@x.com",
        "b@y.com",
    )
    assert calendar_ids_from_env({}) == ()
    with pytest.raises(ValueError):
        calendar_ids_from_env({"JARVIS_CALENDARIOS": "a/../b"})
    with pytest.raises(CalendarioNoConfigurado):
        GoogleCalendar(())


def test_event_ids_are_validated():
    assert decode_event_id("1:abc_123") == (1, "abc_123")
    for value in ("abc", "x:abc", "1:", "1:a/b"):
        with pytest.raises(ValueError):
            decode_event_id(value)


async def test_agenda_lists_local_times_dedupes_and_handles_all_day(google, tmp_path):
    result = await consultar_agenda(
        "2026-10-20", "2026-11-10", None, context=context_for(tmp_path, zone="America/Monterrey")
    )
    assert result["ok"] is True
    assert result["eventos"] == [
        {
            "id": "0:vuelo123",
            "titulo": "Vuelo MZT → MTY (VB 1151 / VB 1126)",
            # 12:13 en Mazatlán son las 13:13 en Monterrey.
            "inicio": "2026-10-25 13:13",
            "fin": "2026-10-25 18:35",
            "todo_el_dia": False,
            "lugar": "Aeropuerto de Mazatlán",
        },
        {
            "id": "0:congreso9",
            "titulo": "Congreso de Psiquiatría",
            "inicio": "2026-11-05",
            "fin": "2026-11-06",
            "todo_el_dia": True,
            "lugar": None,
        },
    ]
    params = google.requests[0].url.params
    assert params["singleEvents"] == "true"
    assert params["timeZone"] == "America/Monterrey"
    assert params["timeMin"] == "2026-10-20T00:00:00-06:00"
    assert "q" not in params


async def test_agenda_search_text_and_limits(google, tmp_path):
    context = context_for(tmp_path)
    await consultar_agenda("2026-10-25", "2026-10-25", " vuelo ", context=context)
    assert google.requests[-1].url.params["q"] == "vuelo"
    too_long = await consultar_agenda("2026-01-01", "2026-03-01", None, context=context)
    assert too_long["ok"] is False
    invalid = await consultar_agenda("mañana", "2026-03-01", None, context=context)
    assert invalid["ok"] is False


async def test_unshared_calendar_is_skipped(tmp_path, monkeypatch):
    fake = FakeGoogle({CALENDARS[0]: [CONGRESS.copy()]})
    calendario.set_calendar(
        GoogleCalendar(
            CALENDARS,
            credentials=SimpleNamespace(valid=True, token="token-de-prueba"),
            transport=httpx.MockTransport(fake.handler),
        )
    )
    try:
        result = await consultar_agenda(
            "2026-11-01", "2026-11-30", None, context=context_for(tmp_path)
        )
    finally:
        calendario.set_calendar(None)
    assert [event["titulo"] for event in result["eventos"]] == ["Congreso de Psiquiatría"]


async def test_agenda_without_configuration_says_so(tmp_path, monkeypatch):
    monkeypatch.delenv("JARVIS_CALENDARIOS", raising=False)
    calendario.set_calendar(None)
    result = await consultar_agenda("2026-11-01", "2026-11-02", None, context=context_for(tmp_path))
    assert result == {"ok": False, "mensaje": "El calendario todavía no está conectado a JARVIS."}


async def test_delete_requires_a_new_request_with_explicit_confirmation(google, tmp_path):
    first = context_for(tmp_path, request_id="pregunta", text="borra el vuelo del domingo")
    proposal = await proponer_borrado_evento("0:vuelo123", context=first)
    assert proposal["requiere_confirmacion"] is True
    assert google.deleted == []

    # El modelo intenta confirmar en la misma petición: el servidor lo rechaza.
    same_turn = await confirmar_borrado_evento(context=first)
    assert same_turn["ok"] is False and google.deleted == []

    # Una respuesta que no confirma tampoco borra.
    doubt = context_for(tmp_path, request_id="respuesta-1", text="no, espera")
    assert (await confirmar_borrado_evento(context=doubt))["ok"] is False
    assert google.deleted == []

    yes = context_for(tmp_path, request_id="respuesta-2", text="Sí, bórralo")
    result = await confirmar_borrado_evento(context=yes)
    assert result == {
        "ok": True,
        "borrado": {"titulo": "Vuelo MZT → MTY (VB 1151 / VB 1126)", "inicio": "2026-10-25 12:13"},
    }
    assert google.deleted == ["vuelo123"]
    # La propuesta se consume: un segundo «sí» no borra otra cosa.
    again = await confirmar_borrado_evento(
        context=context_for(tmp_path, request_id="r3", text="sí")
    )
    assert again["ok"] is False


async def test_expired_proposal_is_not_executed(google, tmp_path):
    context = context_for(tmp_path, request_id="pregunta")
    await proponer_borrado_evento("0:congreso9", context=context)
    store = context.store
    pending = store.read_pending_delete()
    pending["expira_en"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    store.write_pending_delete({k: v for k, v in pending.items() if k != "usuario_id"})
    result = await confirmar_borrado_evento(
        context=context_for(tmp_path, request_id="respuesta", text="sí")
    )
    assert result["ok"] is False
    assert google.deleted == []
    assert store.read_pending_delete() is None


async def test_proposal_for_missing_or_invalid_event(google, tmp_path):
    context = context_for(tmp_path)
    assert (await proponer_borrado_evento("0:noexiste", context=context))["ok"] is False
    assert (await proponer_borrado_evento("basura", context=context))["ok"] is False
    assert (await proponer_borrado_evento("7:vuelo123", context=context))["ok"] is False
    assert context.store.read_pending_delete() is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Sí, bórralo", True),
        ("adelante", True),
        ("confirmo", True),
        ("no", False),
        ("mejor no, gracias", False),
        ("¿cuál vuelo?", False),
        ("sí... no, espera", False),
    ],
)
def test_confirmation_phrases(text, expected):
    assert es_confirmacion(text) is expected


def test_calendar_day_bounds_are_inclusive():
    assert calendario.parse_local_day("2026-11-05") == date(2026, 11, 5)


async def test_brain_gives_each_request_its_own_id(config):
    from unittest.mock import AsyncMock

    from app.brain import Brain
    from app.registry import ToolRegistry
    from app.schemas import AskRequest
    from tests.test_brain import CONTEXT, response

    seen = []
    registry = ToolRegistry.discover()
    original = registry.execute

    async def spy(name, arguments, context):
        seen.append((context.solicitud_id, context.texto_usuario))
        return json.dumps({"ok": True})

    registry.execute = spy
    call = SimpleNamespace(
        type="function_call", name="obtener_hora_actual", arguments="{}", call_id="c"
    )
    create = AsyncMock(
        side_effect=[response(output=[call]), response(), response(output=[call]), response()]
    )
    brain = Brain(SimpleNamespace(responses=SimpleNamespace(create=create)), config, "P", registry)
    await brain.ask(AskRequest(texto="¿qué tengo mañana?"), CONTEXT)
    await brain.ask(AskRequest(texto="sí"), CONTEXT)
    assert seen[0][1] == "¿qué tengo mañana?" and seen[1][1] == "sí"
    assert seen[0][0] and seen[1][0] and seen[0][0] != seen[1][0]
    registry.execute = original
