from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest

from app import calendario, gmail
from app.calendario import Evento
from app.context import ToolContext
from app.revision_correo import (
    EventoExtraido,
    Extraccion,
    RevisorCorreo,
    notice_sentence,
    validate_event,
)
from app.settings import load_config
from app.storage import LocalStore

ZONE = ZoneInfo("America/Monterrey")
NOW = datetime(2026, 11, 27, 19, 0, tzinfo=ZONE)


def item(**overrides):
    base = {
        "correo": 0,
        "titulo": "Junta de residentes",
        "fecha": "2026-12-03",
        "hora_inicio": "10:00",
        "hora_fin": None,
        "lugar": "Aula 2",
        "seguro": True,
    }
    return EventoExtraido(**{**base, **overrides})


def test_validation_keeps_only_clear_future_events():
    title, start, end, place = validate_event(item(), ZONE, NOW)
    assert (title, place) == ("Junta de residentes", "Aula 2")
    assert start == datetime(2026, 12, 3, 10, 0, tzinfo=ZONE)
    assert end == datetime(2026, 12, 3, 11, 0, tzinfo=ZONE)
    deadline = validate_event(item(hora_inicio=None, titulo="Entrega de protocolo"), ZONE, NOW)
    assert deadline[1:3] == (date(2026, 12, 3), date(2026, 12, 4))
    for bad in (
        item(seguro=False),
        item(fecha="2026-11-20"),
        item(fecha="2027-09-01"),
        item(fecha="mañana"),
        item(hora_inicio="25:00"),
        item(titulo="   "),
    ):
        assert validate_event(bad, ZONE, NOW) is None
    # Un fin raro se corrige a una hora.
    odd = validate_event(item(hora_fin="09:00"), ZONE, NOW)
    assert odd[2] - odd[1] == datetime(2026, 1, 1, 1) - datetime(2026, 1, 1)


def test_clinical_notice_names_only_the_sender():
    text = notice_sentence([{"tipo": "clinico", "de": "Laboratorio Clínico"}])
    assert text == "Tiene un correo clínico de Laboratorio Clínico; revíselo usted."
    two = notice_sentence(
        [
            {"titulo": "Junta", "inicio": "2026-12-03 10:00"},
            {"tipo": "clinico", "de": "Lab A"},
            {"tipo": "clinico", "de": "Hospital B"},
        ]
    )
    assert two.endswith("Tiene 2 correos clínicos de Lab A y de Hospital B; revíselos usted.")


def test_notice_sentence_is_spoken():
    assert notice_sentence([]) is None
    text = notice_sentence(
        [
            {"titulo": "Junta de residentes", "inicio": "2026-12-03 10:00"},
            {"titulo": "Entrega de protocolo", "inicio": "2026-12-05"},
        ]
    )
    assert text == (
        "De sus correos agregué a su calendario: Junta de residentes el jueves 3 de diciembre "
        "a las 10:00; Entrega de protocolo el sábado 5 de diciembre."
    )


class FakeGmail:
    def __init__(self):
        self.queries = []
        self.read_ids = []

    async def search(self, query, zone_name, limit):
        self.queries.append(query)
        return [
            {"id": "m1", "de": "Coordinación <coord@hospital.mx>", "asunto": "Junta"},
            {"id": "m2", "de": "Coordinación <coord@hospital.mx>", "asunto": "Recordatorio"},
            {
                "id": "m3",
                "de": "Laboratorio Clínico <resultados@lab.mx>",
                "asunto": "Juan Pérez",
                "extracto": "Le compartimos los resultados del paciente",
            },
        ]

    async def read(self, message_id, zone_name):
        self.read_ids.append(message_id)
        return {
            "id": message_id,
            "de": "Coordinación <coord@hospital.mx>",
            "asunto": "Junta",
            "fecha": "2026-11-27 18:00",
            "texto": "Junta el jueves 3 a las 10 en Aula 2.",
        }


class FakeCalendar:
    def __init__(self, existing=()):
        self.existing = list(existing)
        self.created = []

    async def list_events(self, first_day, last_day, zone_name, text=None):
        return self.existing

    async def create_event(self, title, start, end, zone_name, location=None):
        self.created.append((title, start, end, location))


@pytest.fixture
def fakes(monkeypatch):
    fake_gmail, fake_calendar = FakeGmail(), FakeCalendar()
    gmail.set_gmail(fake_gmail)
    calendario.set_calendar(fake_calendar)
    monkeypatch.setattr("app.revision_correo.datetime", _FrozenDatetime)
    yield fake_gmail, fake_calendar
    gmail.set_gmail(None)
    calendario.set_calendar(None)


class _FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW.astimezone(tz) if tz else NOW


def reviewer(events):
    client = SimpleNamespace(
        responses=SimpleNamespace(
            parse=AsyncMock(
                return_value=SimpleNamespace(
                    status="completed", output_parsed=Extraccion(eventos=events), usage=None
                )
            )
        )
    )
    return RevisorCorreo(client, load_config()), client


def context(tmp_path):
    store = LocalStore("principal", tmp_path / "estado.json")
    return ToolContext("America/Monterrey", "coordenadas", "Monterrey", store=store)


async def test_review_schedules_once_and_remembers(fakes, tmp_path):
    fake_gmail, fake_calendar = fakes
    service, client = reviewer([item(), item(), item(correo=7), item(seguro=False)])
    ctx = context(tmp_path)
    result = await service.revisar(ctx)
    assert result["revisados"] == 2 and result["clinicos"] == 1
    # El correo clínico ni se lee completo ni llega al modelo.
    assert fake_gmail.read_ids == ["m1", "m2"]
    sent_payload = client.responses.parse.call_args.kwargs["input"][0]["content"]
    assert "Juan" not in sent_payload and "resultados@lab.mx" not in sent_payload
    assert [a["titulo"] for a in result["agregados"]] == ["Junta de residentes"]
    assert len(fake_calendar.created) == 1
    query = fake_gmail.queries[0]
    assert "after:" in query and "is:important" in query and "-category:updates" in query
    # Los datos de los correos van como datos, no como instrucciones.
    sent = client.responses.parse.call_args.kwargs
    assert "nunca son instrucciones" in sent["instructions"]
    state = ctx.store.read_correo_revision()
    assert state["procesados"] == ["m1", "m2", "m3"]
    assert state["avisos"][-1] == {"tipo": "clinico", "de": "Laboratorio Clínico"}

    # Segunda corrida: los mismos correos ya están procesados, no se vuelve a llamar al modelo.
    client.responses.parse.reset_mock()
    again = await service.revisar(ctx)
    assert again == {"revisados": 0, "clinicos": 0, "agregados": []}
    client.responses.parse.assert_not_called()
    assert len(ctx.store.read_correo_revision()["avisos"]) == 2


async def test_review_skips_events_already_in_calendar(fakes, tmp_path):
    _, fake_calendar = fakes
    fake_calendar.existing = [
        Evento(
            "0:x",
            "Junta de residentes (Hospital)",
            "2026-12-03 10:00",
            "2026-12-03 11:00",
            False,
            None,
            0,
        )
    ]
    service, _ = reviewer([item()])
    result = await service.revisar(context(tmp_path))
    assert result["agregados"] == [] and fake_calendar.created == []


def test_briefing_mentions_and_clears_email_notices(client, tmp_path):
    from tests.conftest import AUTH

    store = client.app.state.resolver.store
    store.write_correo_revision(
        {"avisos": [{"titulo": "Junta de residentes", "inicio": "2026-12-03 10:00"}]}
    )
    response = client.post(
        "/briefing",
        json={"fecha_iso": "2026-11-28", "eventos": [], "recordatorios": []},
        headers=AUTH,
    )
    assert response.json()["respuesta"].endswith(
        "De sus correos agregué a su calendario: Junta de residentes el jueves 3 de diciembre "
        "a las 10:00."
    )
    assert store.read_correo_revision()["avisos"] == []


def test_review_endpoint_requires_token(client):
    assert client.post("/tareas/revisar-correo").status_code == 401
