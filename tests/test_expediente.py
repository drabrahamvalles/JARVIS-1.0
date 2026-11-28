from datetime import datetime
from zoneinfo import ZoneInfo

from app.context import ToolContext
from app.expediente import add_fact, for_instructions, forget, read_all, resolve_place, save_place
from app.settings import load_config
from app.storage import LocalStore
from app.tools.consultar_expediente import consultar_expediente
from app.tools.guardar_lugar import guardar_lugar
from app.tools.olvidar_dato import olvidar_dato
from app.tools.recordar_dato import recordar_dato
from app.whoop import sleep_habits_from


def store_at(tmp_path):
    return LocalStore("principal", tmp_path / "estado.json")


def test_facts_are_deduplicated_and_forgettable(tmp_path):
    store = store_at(tmp_path)
    first = add_fact(store, "rutina", "Come  a las 14:00")
    again = add_fact(store, "rutina", "come a las 14:00.")
    assert first == again
    weird = add_fact(store, "inventada", "Le gusta el café sin azúcar")
    assert weird["categoria"] == "otro"
    assert [f["texto"] for f in read_all(store)["datos"]] == [
        "Come a las 14:00",
        "Le gusta el café sin azúcar",
    ]
    assert forget(store, first["id"]) is True
    assert forget(store, "noexiste") is False
    assert len(read_all(store)["datos"]) == 1


def test_places_replace_by_name_and_resolve(tmp_path):
    store = store_at(tmp_path)
    save_place(store, "Consultorio", "Av. Gonzalitos 100, Monterrey")
    save_place(store, "consultorio", "Av. Gonzalitos 200, Monterrey")
    save_place(store, "Casa de la abuela", "Calle Roble 5, San Pedro")
    places = read_all(store)["lugares"]
    assert len(places) == 2
    assert resolve_place(places, "Consultorio", None) == "Av. Gonzalitos 200, Monterrey"
    assert resolve_place(places, None, "Cena en casa de la abuela") == "Calle Roble 5, San Pedro"
    assert resolve_place(places, "Hospital Zambrano", "Junta") is None
    text = for_instructions(read_all(store))
    assert "(lugar) Casa de la abuela: Calle Roble 5, San Pedro" in text


async def test_tools_round_trip(tmp_path):
    context = ToolContext("America/Monterrey", "coordenadas", "Monterrey", store=store_at(tmp_path))
    saved = await recordar_dato("rutina", "Sale del hospital a las 15:00", context=context)
    assert saved["ok"] is True
    assert (await guardar_lugar("Hospital", "Av. Madero 3000", False, context=context))["ok"]
    assert (await guardar_lugar("Hospital", " ", False, context=context))["ok"] is False
    # «Aquí es mi casa» sin ubicación del iPhone no se puede.
    assert (await guardar_lugar("Casa", None, True, context=context))["ok"] is False
    everything = await consultar_expediente(context=context)
    assert everything["datos"][0]["texto"] == "Sale del hospital a las 15:00"
    assert everything["lugares"][0]["nombre"] == "Hospital"
    assert (await olvidar_dato(saved["dato"]["id"], context=context))["ok"] is True
    assert (await consultar_expediente(context=context))["datos"] == []


def test_sleep_habits_average_across_midnight():
    nights = [
        {"nap": False, "start": "2026-11-27T05:50:00Z", "end": "2026-11-27T12:30:00Z"},
        {"nap": False, "start": "2026-11-26T06:10:00Z", "end": "2026-11-26T12:40:00Z"},
        {"nap": False, "start": "2026-11-25T06:00:00Z", "end": "2026-11-25T12:35:00Z"},
        {"nap": True, "start": "2026-11-25T20:00:00Z", "end": "2026-11-25T20:30:00Z"},
    ]
    habits = sleep_habits_from(nights, "America/Monterrey")
    # 23:50, 00:10 y 00:00 promedian medianoche; despierta 6:35 en promedio.
    assert habits == {"se_duerme": "00:00", "despierta": "06:35", "noches": 3}
    assert sleep_habits_from(nights[:2], "America/Monterrey") is None


def test_brain_instructions_include_the_profile(tmp_path):
    from types import SimpleNamespace

    from app.brain import Brain

    store = store_at(tmp_path)
    add_fact(store, "persona", "Su abuela se llama Rosa")
    brain = Brain.__new__(Brain)
    brain.personality = "Personalidad."
    brain.config = load_config()
    context = ToolContext(
        "America/Monterrey",
        "coordenadas",
        "Monterrey",
        expediente=for_instructions(read_all(store)),
    )
    text = brain._instructions(context, SimpleNamespace(reason="normal"))
    assert "Expediente del Dr. Valles" in text and "Su abuela se llama Rosa" in text
    plain = brain._instructions(
        ToolContext("America/Monterrey", "coordenadas", "Monterrey"), SimpleNamespace(reason="x")
    )
    assert "Expediente del Dr. Valles" not in plain


def test_alert_uses_saved_place(tmp_path):
    from app.avisos import Plan, plan_for
    from app.calendario import Evento

    event = Evento(
        "0:a", "Consulta", "2026-11-28 12:00", "2026-11-28 13:00", False, "Consultorio", 0
    )
    start = datetime(2026, 11, 28, 12, tzinfo=ZoneInfo("America/Monterrey"))
    plan = plan_for(event, start, {})
    places = [{"id": "x", "nombre": "Consultorio", "direccion": "Av. Gonzalitos 200"}]
    saved = resolve_place(places, event.lugar, event.titulo)
    assert isinstance(plan, Plan) and saved == "Av. Gonzalitos 200"
