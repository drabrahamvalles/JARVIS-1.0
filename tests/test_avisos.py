import json
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import httpx
import pytest

from app import avisos as avisos_module
from app import calendario, gmail
from app.avisos import Avisos, distance_m, message_for, plan_for
from app.calendario import Evento
from app.storage import LocalStore

ZONE = ZoneInfo("America/Monterrey")
AIRPORTS = {"MTY": "Monterrey", "MEX": "Ciudad de México"}
HOME = (25.6500, -100.4000)


def at(hour, minute=0):
    return datetime(2026, 11, 28, hour, minute, tzinfo=ZONE)


def event(title="Cita", start="2026-11-28 12:00", place="Hospital Zambrano", all_day=False):
    return Evento("0:e1", title, start, start, all_day, place, 0)


def test_flights_arrive_two_or_three_hours_before():
    national = plan_for(event("Vuelo MTY → MEX (VB 1151)", place=None), at(10), AIRPORTS)
    assert national.llegada == at(8) and national.destino == "Aeropuerto de Monterrey"
    assert "como es nacional, debe estar en el aeropuerto 2 horas antes, a las 08:00" in (
        national.motivo
    )
    international = plan_for(event("Vuelo MTY → IAH (UA 1234)", place=None), at(10), AIRPORTS)
    assert international.llegada == at(7) and "internacional" in international.motivo
    normal = plan_for(event(), at(12), AIRPORTS)
    assert normal.llegada == at(12) and normal.motivo == "su Cita es a las 12:00"


def test_messages():
    plan = plan_for(event(), at(12), AIRPORTS)
    assert message_for("aviso_15", plan, 30) == (
        "Doctor, le recomiendo salir en 15 minutos: su Cita es a las 12:00. "
        "Hay 30 minutos de camino."
    )
    assert message_for("aviso_hora", plan, 30).startswith("Doctor, ya es hora de salir")
    assert message_for("aviso_tarde", plan, 30).startswith(
        "Doctor, ya se tiene que ir, ya va tarde"
    )


def test_distance():
    assert distance_m(HOME, HOME) == 0
    assert 1000 < distance_m(HOME, (25.66, -100.4)) < 1200


class FakeCalendar:
    def __init__(self, events):
        self.events = events

    async def list_events(self, first_day, last_day, zone_name, text=None):
        return self.events


class FakeGmail:
    def __init__(self):
        self.sent = []

    async def own_address(self):
        return "dr@example.com"

    async def send(self, to, subject, body):
        self.sent.append((to, subject, body))


class FakeRoutes:
    def __init__(self, minutes):
        self.minutes = list(minutes)
        self.calls = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["X-Goog-User-Project"] == "proyecto"
        body = json.loads(request.content)
        assert body["routingPreference"] == "TRAFFIC_AWARE"
        self.calls.append(body)
        minutes = self.minutes.pop(0) if len(self.minutes) > 1 else self.minutes[0]
        return httpx.Response(200, json={"routes": [{"duration": f"{minutes * 60}s"}]})


class Clock(datetime):
    current = at(8)

    @classmethod
    def now(cls, tz=None):
        return cls.current.astimezone(tz) if tz else cls.current


@pytest.fixture
def world(tmp_path, monkeypatch):
    fake_gmail = FakeGmail()
    gmail.set_gmail(fake_gmail)
    calendario.set_calendar(FakeCalendar([event()]))
    monkeypatch.setattr(avisos_module, "datetime", Clock)
    store = LocalStore("principal", tmp_path / "estado.json")

    def build(minutes):
        routes = FakeRoutes(minutes)
        service = Avisos(
            AIRPORTS,
            credentials=SimpleNamespace(valid=True, token="acceso"),
            project="proyecto",
            transport=httpx.MockTransport(routes.handler),
        )
        return service, routes

    yield store, fake_gmail, build
    gmail.set_gmail(None)
    calendario.set_calendar(None)


def place(store, where, when):
    store.write_ubicacion({"lat": where[0], "lon": where[1], "en": when.isoformat()})


async def tick(service, store, when, where=HOME):
    Clock.current = when
    place(store, where, when)
    return await service.run(store, "America/Monterrey")


async def test_three_spoken_alerts_when_he_does_not_leave(world):
    store, fake_gmail, build = world
    service, routes = build([30])
    # Cita a las 12:00, 30 min de camino: salida real 11:30.
    assert (await tick(service, store, at(7, 50)))["hablados"] == []  # Falta más de 4 h.
    assert routes.calls == []
    await tick(service, store, at(8))  # Primer cálculo.
    assert len(routes.calls) == 1 and "departureTime" not in routes.calls[0]
    await tick(service, store, at(8, 30))  # Lejos: no recalcula hasta 1 h después.
    assert len(routes.calls) == 1
    await tick(service, store, at(10, 40))  # Ya vigila: recalcula con la hora de salida.
    assert len(routes.calls) == 2 and routes.calls[1]["departureTime"].startswith(
        "2026-11-28T11:30"
    )
    await tick(service, store, at(10, 50))  # Menos de 15 min desde el último cálculo.
    assert len(routes.calls) == 2 and fake_gmail.sent == []

    await tick(service, store, at(11, 10))
    await tick(service, store, at(11, 20))  # Nada nuevo entre avisos.
    await tick(service, store, at(11, 25))
    await tick(service, store, at(11, 30))
    await tick(service, store, at(11, 40))  # No repite.
    bodies = [body for _, _, body in fake_gmail.sent]
    assert [body.split(":")[0] for body in bodies] == [
        "Doctor, le recomiendo salir en 15 minutos",
        "Doctor, ya es hora de salir",
        "Doctor, ya se tiene que ir, ya va tarde",
    ]
    assert all(
        to == ["dr@example.com"] and subject == "Aviso de JARVIS"
        for to, subject, _ in fake_gmail.sent
    )


async def test_no_late_alert_if_he_already_left(world):
    store, fake_gmail, build = world
    service, _ = build([30])
    await tick(service, store, at(11, 10))
    await tick(service, store, at(11, 25))
    await tick(service, store, at(11, 30), where=(25.70, -100.35))  # Ya va en camino.
    assert len(fake_gmail.sent) == 2


async def test_heavier_traffic_moves_the_alert_earlier(world):
    store, fake_gmail, build = world
    service, routes = build([30, 50])
    await tick(service, store, at(10, 20))  # 30 min: salir 11:30.
    await tick(service, store, at(10, 40))  # Ahora 50 min: salir 11:10 → aviso de 15 a las 10:50.
    assert fake_gmail.sent == []
    await tick(service, store, at(10, 50))
    assert len(fake_gmail.sent) == 1 and "Hay 50 minutos de camino" in fake_gmail.sent[0][2]


async def test_late_start_skips_to_the_current_alert(world):
    store, fake_gmail, build = world
    service, _ = build([30])
    await tick(service, store, at(11, 27))  # Ya pasó el de 15: solo el de «ya es hora».
    assert [body.split(":")[0] for _, _, body in fake_gmail.sent] == ["Doctor, ya es hora de salir"]


async def test_without_place_one_simple_alert(world):
    store, fake_gmail, build = world
    calendario.set_calendar(FakeCalendar([event(place=None)]))
    service, routes = build([30])
    await tick(service, store, at(11, 20))
    await tick(service, store, at(11, 35))
    await tick(service, store, at(11, 45))
    assert routes.calls == []
    assert [body for _, _, body in fake_gmail.sent] == [
        "Doctor, ya es hora de salir: su Cita es a las 12:00."
    ]


def test_location_is_remembered_and_endpoint_needs_token(client):
    from tests.conftest import AUTH

    assert client.post("/tareas/avisos").status_code == 401
    client.post("/ask", json={"texto": "hola", "lat": 25.65, "lon": -100.4}, headers=AUTH)
    saved = client.app.state.resolver.store.read_ubicacion()
    assert (saved["lat"], saved["lon"]) == (25.65, -100.4)
