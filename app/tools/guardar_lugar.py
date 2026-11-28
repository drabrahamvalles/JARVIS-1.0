from starlette.concurrency import run_in_threadpool

from app.context import ToolContext
from app.expediente import save_place
from app.registry import tool


@tool
async def guardar_lugar(nombre: str, direccion: str, *, context: ToolContext) -> dict[str, object]:
    """Guarda un lugar frecuente del usuario con su dirección («mi consultorio está en
    Av. Gonzalitos 123», «la casa de mi abuela es en…»). Así los avisos de salida
    calculan el tráfico aunque el evento solo diga «Consultorio». nombre: corto, como
    «Consultorio», «Hospital» o «Casa de la abuela». Si ya existía, se reemplaza.
    Responde «Anotado, Dr. Valles.».
    """
    if context.store is None:
        return {"ok": False, "mensaje": "No puedo guardar el lugar en este momento."}
    if not nombre.strip() or not direccion.strip():
        return {"ok": False, "mensaje": "Necesito el nombre del lugar y su dirección."}
    place = await run_in_threadpool(save_place, context.store, nombre, direccion)
    return {"ok": True, "lugar": place}
