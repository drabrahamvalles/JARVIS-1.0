from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.context import ToolContext
from app.tools.crear_recordatorio import crear_recordatorio
from tests.conftest import AUTH


def make_context():
    return ToolContext("America/Monterrey", "coordenadas", "Monterrey")


def test_reminder_with_time_date_only_and_none():
    context = make_context()
    tomorrow = (datetime.now(ZoneInfo("America/Monterrey")) + timedelta(days=1)).date()
    with_time = crear_recordatorio("  revisar   los labs ", f"{tomorrow} 17:00", context=context)
    date_only = crear_recordatorio("pagar la tarjeta", tomorrow.isoformat(), context=context)
    no_date = crear_recordatorio("comprar el First Aid", None, context=context)
    assert with_time["ok"] and with_time["alerta"] == f"{tomorrow} 17:00"
    assert date_only["alerta"] == f"{tomorrow} 09:00"
    assert no_date["alerta"] is None
    assert context.acciones == [
        {"titulo": "revisar los labs", "alerta": f"{tomorrow} 17:00"},
        {"titulo": "pagar la tarjeta", "alerta": f"{tomorrow} 09:00"},
        {"titulo": "comprar el First Aid", "alerta": None},
    ]


def test_reminder_rejects_past_invalid_or_empty():
    context = make_context()
    assert crear_recordatorio("algo", "2020-01-01 10:00", context=context)["ok"] is False
    assert crear_recordatorio("algo", "el martes", context=context)["ok"] is False
    assert crear_recordatorio("   ", None, context=context)["ok"] is False
    assert context.acciones == []


def test_ask_returns_reminder_fields(client):
    async def fake_ask(payload, context):
        context.acciones.append({"titulo": "revisar los labs", "alerta": "2030-01-01 17:00"})
        return "Listo, Dr. Valles."

    client.app.state.brain.ask = fake_ask
    body = client.post("/ask", json={"texto": "recuérdame revisar los labs"}, headers=AUTH).json()
    assert body == {
        "respuesta": "Listo, Dr. Valles.",
        "recordatorio_titulo": "revisar los labs",
        "recordatorio_alerta": "2030-01-01 17:00",
    }


def test_ask_without_reminder_only_returns_the_answer(client):
    body = client.post("/ask", json={"texto": "hola"}, headers=AUTH).json()
    assert body == {"respuesta": "A su servicio, Dr. Valles."}


def test_reminder_without_date_omits_alert(client):
    async def fake_ask(payload, context):
        context.acciones.append({"titulo": "comprar café", "alerta": None})
        return "Listo, Dr. Valles."

    client.app.state.brain.ask = fake_ask
    body = client.post("/ask", json={"texto": "recuérdame comprar café"}, headers=AUTH).json()
    assert body == {"respuesta": "Listo, Dr. Valles.", "recordatorio_titulo": "comprar café"}
