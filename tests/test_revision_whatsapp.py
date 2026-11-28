from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest

from app import calendario
from app.context import ToolContext
from app.revision_correo import EventoExtraido, Extraccion, RevisorCorreo, notice_sentence
from app.revision_whatsapp import LoteWhatsApp, RevisorWhatsApp
from app.settings import load_config
from app.storage import LocalStore

ZONE = ZoneInfo("America/Monterrey")
NOW = datetime(2026, 11, 28, 15, 0, tzinfo=ZONE)


class FakeCalendar:
    def __init__(self):
        self.created = []

    async def list_events(self, first_day, last_day, zone_name, text=None):
        return []

    async def create_event(self, title, start, end, zone_name, location=None):
        self.created.append((title, start, location))


class Clock(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW.astimezone(tz) if tz else NOW


@pytest.fixture
def setup(tmp_path, monkeypatch):
    fake = FakeCalendar()
    calendario.set_calendar(fake)
    monkeypatch.setattr("app.revision_correo.datetime", Clock)
    monkeypatch.setattr("app.revision_whatsapp.datetime", Clock)
    event = EventoExtraido(
        correo=0,
        titulo="Cena con la abuela",
        fecha="2026-11-29",
        hora_inicio="19:00",
        hora_fin=None,
        lugar=None,
        seguro=True,
    )
    parse = AsyncMock(
        return_value=SimpleNamespace(
            status="completed", output_parsed=Extraccion(eventos=[event]), usage=None
        )
    )
    client = SimpleNamespace(responses=SimpleNamespace(parse=parse))
    service = RevisorWhatsApp(RevisorCorreo(client, load_config()))
    store = LocalStore("principal", tmp_path / "estado.json")
    context = ToolContext("America/Monterrey", "coordenadas", "Monterrey", store=store)
    yield service, context, fake, parse
    calendario.set_calendar(None)


def batch():
    return LoteWhatsApp.model_validate(
        {
            "mensajes": [
                {
                    "id": "c1",
                    "chat": "Mamá",
                    "de_mi": False,
                    "texto": "¿Vienes?",
                    "fecha": "2026-11-28T13:58:00-06:00",
                    "contexto": True,
                },
                {
                    "id": "m1",
                    "chat": "Mamá",
                    "de_mi": False,
                    "texto": "Mañana nos juntamos con tu abuela a las 7 de la noche",
                    "fecha": "2026-11-28T14:00:00-06:00",
                },
                {
                    "id": "m2",
                    "chat": "Juan Pérez",
                    "de_mi": False,
                    "texto": "Doctor, ya tengo los resultados del laboratorio, ¿lo veo mañana?",
                    "fecha": "2026-11-28T14:10:00-06:00",
                },
            ]
        }
    )


async def test_schedules_and_hides_names_and_clinical_chats(setup):
    service, context, fake, parse = setup
    result = await service.revisar(batch(), context)
    assert result["chats"] == 1 and result["clinicos"] == 1
    assert fake.created[0][0] == "Cena con la abuela"
    sent = parse.call_args.kwargs["input"][0]["content"]
    # Ni el nombre del chat ni el chat clínico llegan al modelo.
    assert "Mamá" not in sent and "Juan" not in sent and "laboratorio" not in sent
    assert "Otra persona: Mañana nos juntamos con tu abuela" in sent
    assert "¿Vienes?" in sent  # El contexto sí viaja, anónimo.
    notices = context.store.read_correo_revision()["avisos"]
    assert notice_sentence(notices) == (
        "De WhatsApp agregué a su calendario: Cena con la abuela el domingo 29 de noviembre "
        "a las 19:00. En WhatsApp llegó un mensaje que parece clínico; revíselo usted."
    )

    # La segunda vez los mismos mensajes ya están procesados.
    parse.reset_mock()
    again = await service.revisar(batch(), context)
    assert again == {"chats": 0, "clinicos": 0, "agregados": []}
    parse.assert_not_called()


def test_mixed_notice_sentence():
    text = notice_sentence(
        [
            {"titulo": "Junta", "inicio": "2026-12-03 10:00"},
            {"titulo": "Cena", "inicio": "2026-12-04 20:00", "origen": "whatsapp"},
        ]
    )
    assert text.startswith("De sus correos agregué a su calendario: Junta")
    assert "De WhatsApp agregué a su calendario: Cena el viernes 4 de diciembre" in text


def test_endpoint_requires_token_and_validates(client):
    from tests.conftest import AUTH

    assert client.post("/whatsapp/mensajes", json={"mensajes": []}).status_code == 401
    bad = {"mensajes": [{"id": "x", "chat": "a", "de_mi": False, "texto": "t", "fecha": "ayer"}]}
    assert client.post("/whatsapp/mensajes", json=bad, headers=AUTH).status_code == 422
