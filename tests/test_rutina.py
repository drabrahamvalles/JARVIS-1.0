from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app import rutina as rutina_module
from app.avisos import _waypoint
from app.context import ToolContext
from app.expediente import read_all, resolve_place, save_place
from app.main import append_location_log
from app.rutina import PREGUNTA_MISA, Rutina, cluster, describe_days
from app.storage import LocalStore
from app.tools.guardar_lugar import guardar_lugar
from app.tools.nombrar_lugar_frecuente import nombrar_lugar_frecuente

ZONE = ZoneInfo("America/Monterrey")
HOME = (25.58502, -100.27513)
HOSPITAL = (25.6900, -100.3500)


def at(day, hour, minute=0):
    # 2026-11-23 es lunes; 2026-11-28 es sábado.
    return datetime(2026, 11, day, hour, minute, tzinfo=ZONE)


def log_points():
    points = []
    for day in range(16, 28):  # Dos semanas.
        moment = datetime(2026, 11, day, tzinfo=ZONE)
        for hour in (7, 21, 23):
            points.append((HOME, moment.replace(hour=hour)))
        if moment.weekday() < 5:
            for hour in (9, 11, 13):
                spot = (HOSPITAL[0] + 0.0003, HOSPITAL[1]) if hour == 11 else HOSPITAL
                points.append((spot, moment.replace(hour=hour)))
    return [{"lat": p[0], "lon": p[1], "en": when.isoformat()} for p, when in points]


def test_clusters_and_patterns():
    places = cluster(log_points(), ZONE)
    assert len(places) == 2
    home, hospital = places
    assert home["noche"] >= home["puntos"] // 2
    assert hospital["dias"] == [0, 1, 2, 3, 4]
    assert (hospital["desde"], hospital["hasta"]) == (9, 13)
    assert describe_days(hospital["dias"]) == "entre semana"
    assert describe_days([1, 3]) == "los martes y jueves"


def test_location_log_skips_repeats(tmp_path):
    store = LocalStore("principal", tmp_path / "estado.json")
    base = at(28, 10)
    append_location_log(store, {"lat": HOME[0], "lon": HOME[1], "en": base.isoformat()})
    append_location_log(
        store, {"lat": HOME[0], "lon": HOME[1], "en": (base + timedelta(minutes=5)).isoformat()}
    )
    append_location_log(
        store,
        {"lat": HOSPITAL[0], "lon": HOSPITAL[1], "en": (base + timedelta(minutes=6)).isoformat()},
    )
    assert len(store.read_ubicaciones()["puntos"]) == 2


class Clock(datetime):
    current = at(28, 22)

    @classmethod
    def now(cls, tz=None):
        return cls.current.astimezone(tz) if tz else cls.current


@pytest.fixture
def world(tmp_path, monkeypatch):
    store = LocalStore("principal", tmp_path / "estado.json")
    store.write_ubicaciones({"puntos": log_points()})
    spoken = []

    async def speak(text):
        spoken.append(text)

    monkeypatch.setattr(rutina_module, "datetime", Clock)
    return store, spoken, Rutina(speak)


def here(store, place, when):
    store.write_ubicacion({"lat": place[0], "lon": place[1], "en": when.isoformat()})


async def test_learns_asks_and_names_places(world):
    store, spoken, routine = world
    Clock.current = at(27, 22, 5)
    assert (await routine.run(store, "America/Monterrey"))["rutina"] == ["aprendio"]
    assert len(store.read_rutina()["sin_nombre"]) == 2
    # Sin «Casa» guardada no sabe si está en casa: no pregunta.
    Clock.current = at(28, 19, 30)
    here(store, HOME, Clock.current)
    assert (await routine.run(store, "America/Monterrey"))["rutina"] == []

    # El usuario guarda su casa desde el iPhone («aquí es mi casa»).
    context = ToolContext(
        "America/Monterrey", "coordenadas", "Monterrey", lat=HOME[0], lon=HOME[1], store=store
    )
    assert (await guardar_lugar("Casa", None, True, context=context))["ok"] is True

    # Sábado en casa: la pregunta de la misa, una sola vez, y queda en el historial.
    assert (await routine.run(store, "America/Monterrey"))["rutina"] == ["misa"]
    assert spoken == [PREGUNTA_MISA]
    assert store.read_history()[-1] == {"role": "assistant", "content": PREGUNTA_MISA}
    Clock.current = at(28, 19, 40)
    await routine.run(store, "America/Monterrey")
    assert spoken == [PREGUNTA_MISA]

    # Domingo en casa: pregunta por el lugar frecuente sin nombre (el hospital).
    Clock.current = at(29, 20)
    here(store, HOME, Clock.current)
    store.write_rutina({**store.read_rutina(), "sin_nombre": store.read_rutina()["sin_nombre"][1:]})
    assert (await routine.run(store, "America/Monterrey"))["rutina"] == ["pregunta"]
    assert spoken[-1] == (
        "Doctor, veo que suele ir a un mismo lugar entre semana de 9:00 a 14:00. ¿Qué lugar es?"
    )
    named = await nombrar_lugar_frecuente("Hospital", context=context)
    assert named["ok"] is True
    places = read_all(store)["lugares"]
    assert {p["nombre"] for p in places} == {"Casa", "Hospital"}
    assert store.read_rutina()["pregunta_pendiente"] is None

    # Esa noche aprende el patrón del hospital y lo anota en el expediente.
    Clock.current = at(29, 22, 10)
    await routine.run(store, "America/Monterrey")
    learned = [f["texto"] for f in read_all(store)["datos"] if f.get("origen") == "aprendido"]
    assert "Suele estar en Hospital entre semana, de 9:00 a 14:00" in learned


async def test_not_at_home_no_questions(world):
    store, spoken, routine = world
    save_place(store, "Casa", "x", *HOME)
    Clock.current = at(28, 20)
    here(store, HOSPITAL, Clock.current)
    await routine.run(store, "America/Monterrey")
    assert spoken == []


def test_named_place_with_coordinates_routes_by_lat_lon(tmp_path):
    store = LocalStore("principal", tmp_path / "estado.json")
    save_place(store, "Consultorio", "Av. Gonzalitos 200", 25.7, -100.3)
    destination = resolve_place(read_all(store)["lugares"], "Consultorio")
    assert destination == "25.7,-100.3"
    assert _waypoint(destination) == {
        "location": {"latLng": {"latitude": 25.7, "longitude": -100.3}}
    }
    assert _waypoint("Hospital Zambrano") == {"address": "Hospital Zambrano"}


def test_location_endpoint(client):
    from tests.conftest import AUTH

    assert client.post("/ubicacion", json={"lat": 25.6, "lon": -100.3}).status_code == 401
    assert client.post("/ubicacion", json={}, headers=AUTH).status_code == 422
    assert client.post("/ubicacion", json={"lat": 25.6, "lon": -100.3}, headers=AUTH).json() == {
        "ok": True
    }
    assert len(client.app.state.resolver.store.read_ubicaciones()["puntos"]) == 1
