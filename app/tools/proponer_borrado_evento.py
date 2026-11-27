import logging
from datetime import UTC, datetime, timedelta

from starlette.concurrency import run_in_threadpool

from app.calendario import CalendarioError, CalendarioNoConfigurado, get_calendar
from app.context import ToolContext, active_timezone
from app.registry import tool

logger = logging.getLogger(__name__)
VIGENCIA_CONFIRMACION = timedelta(minutes=10)
MAX_BORRADOS = 10


@tool
async def proponer_borrado_evento(
    evento_ids: list[str], *, context: ToolContext
) -> dict[str, object]:
    """Prepara el borrado de uno o varios eventos del calendario usando los id que
    devolvió consultar_agenda. Si el usuario pide borrar varios («bórralos», «borra
    todo»), pásalos todos en una sola llamada. NO borra nada: guarda la propuesta y
    devuelve los eventos para que le preguntes al usuario una sola vez si confirma.
    Solo se borran cuando el usuario confirma en un mensaje nuevo y llamas
    confirmar_borrado_evento.
    """
    if context.store is None:
        return {"ok": False, "mensaje": "No puedo guardar la confirmación en este momento."}
    ids = list(dict.fromkeys(value.strip() for value in evento_ids if value.strip()))
    if not ids:
        return {"ok": False, "mensaje": "No indicaste qué evento borrar."}
    if len(ids) > MAX_BORRADOS:
        return {"ok": False, "mensaje": f"Puedo borrar hasta {MAX_BORRADOS} eventos a la vez."}
    zone, _ = active_timezone(context)
    events = []
    for evento_id in ids:
        try:
            event = await get_calendar().get_event(evento_id, zone)
        except ValueError:
            return {"ok": False, "mensaje": "Un identificador de evento no es válido."}
        except CalendarioNoConfigurado:
            return {"ok": False, "mensaje": "El calendario todavía no está conectado a JARVIS."}
        except CalendarioError:
            return {"ok": False, "mensaje": "Google Calendar no respondió; intenta más tarde."}
        if event is None:
            return {
                "ok": False,
                "mensaje": "No encontré uno de los eventos; puede que ya no exista.",
            }
        events.append(event)
    pending = {
        "eventos": [
            {"evento_id": event.id, "titulo": event.titulo, "inicio": event.inicio}
            for event in events
        ],
        "solicitud_id": context.solicitud_id,
        "expira_en": (datetime.now(UTC) + VIGENCIA_CONFIRMACION).isoformat(),
    }
    try:
        await run_in_threadpool(context.store.write_pending_delete, pending)
    except Exception as exc:
        logger.warning("storage_failed operation=pending_delete_write kind=%s", type(exc).__name__)
        return {"ok": False, "mensaje": "No pude guardar la confirmación; no borré nada."}
    return {
        "ok": True,
        "requiere_confirmacion": True,
        "eventos": [event.para_modelo() for event in events],
        "instruccion": (
            "Pregunta una sola vez si confirma el borrado de estos eventos. No los borres."
        ),
    }
