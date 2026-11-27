import logging
from datetime import UTC, datetime, timedelta

from starlette.concurrency import run_in_threadpool

from app.calendario import CalendarioError, CalendarioNoConfigurado, get_calendar
from app.context import ToolContext, active_timezone
from app.registry import tool

logger = logging.getLogger(__name__)
VIGENCIA_CONFIRMACION = timedelta(minutes=10)


@tool
async def proponer_borrado_evento(evento_id: str, *, context: ToolContext) -> dict[str, object]:
    """Prepara el borrado de un evento del calendario usando el id que devolvió
    consultar_agenda. NO borra nada: guarda la propuesta y devuelve el evento para que
    le preguntes al usuario si lo confirma. Solo se borra cuando el usuario confirma en
    un mensaje nuevo y llamas confirmar_borrado_evento.
    """
    if context.store is None:
        return {"ok": False, "mensaje": "No puedo guardar la confirmación en este momento."}
    zone, _ = active_timezone(context)
    try:
        event = await get_calendar().get_event(evento_id, zone)
    except ValueError:
        return {"ok": False, "mensaje": "Ese identificador de evento no es válido."}
    except CalendarioNoConfigurado:
        return {"ok": False, "mensaje": "El calendario todavía no está conectado a JARVIS."}
    except CalendarioError:
        return {"ok": False, "mensaje": "Google Calendar no respondió; intenta más tarde."}
    if event is None:
        return {"ok": False, "mensaje": "No encontré ese evento; puede que ya no exista."}
    pending = {
        "evento_id": event.id,
        "titulo": event.titulo,
        "inicio": event.inicio,
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
        "evento": event.para_modelo(),
        "instruccion": "Pregunta al usuario si confirma el borrado de este evento. No lo borres.",
    }
