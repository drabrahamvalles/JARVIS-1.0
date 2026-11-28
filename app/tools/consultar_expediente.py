from starlette.concurrency import run_in_threadpool

from app.context import ToolContext, active_timezone
from app.expediente import read_all
from app.registry import tool
from app.whoop import WhoopError, WhoopNoConfigurado, get_whoop


@tool
async def consultar_expediente(*, context: ToolContext) -> dict[str, object]:
    """Devuelve todo lo que JARVIS sabe del usuario: los datos y lugares que él pidió
    recordar (con su id, para poder borrarlos) y sus hábitos de sueño calculados con
    WHOOP. Úsala para «¿qué sabes de mí?», «¿a qué hora me suelo dormir?» o antes de
    borrar un dato.
    """
    if context.store is None:
        return {"ok": False, "mensaje": "No puedo leer el expediente en este momento."}
    data = await run_in_threadpool(read_all, context.store)
    zone, _ = active_timezone(context)
    try:
        habits = await get_whoop().sleep_habits(zone, context.store)
    except (WhoopNoConfigurado, WhoopError):
        habits = None
    return {"ok": True, **data, "habitos_sueno": habits}
