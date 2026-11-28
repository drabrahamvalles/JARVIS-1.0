from starlette.concurrency import run_in_threadpool

from app.context import ToolContext
from app.expediente import forget
from app.registry import tool


@tool
async def olvidar_dato(dato_id: str, *, context: ToolContext) -> dict[str, object]:
    """Borra un dato o lugar del expediente cuando el usuario lo pida («olvida que…»,
    «borra eso»). dato_id es el id que devolvió consultar_expediente; si no lo tienes,
    llama primero consultar_expediente. Responde «Listo, Dr. Valles. Lo olvidé.».
    """
    if context.store is None:
        return {"ok": False, "mensaje": "No puedo modificar el expediente en este momento."}
    removed = await run_in_threadpool(forget, context.store, dato_id.strip())
    if not removed:
        return {"ok": False, "mensaje": "No encontré ese dato en el expediente."}
    return {"ok": True}
