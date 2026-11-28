from starlette.concurrency import run_in_threadpool

from app.context import ToolContext
from app.expediente import save_place
from app.registry import tool


@tool
async def guardar_lugar(
    nombre: str, direccion: str | None, aqui: bool, *, context: ToolContext
) -> dict[str, object]:
    """Guarda un lugar frecuente del usuario. Dos formas: con su dirección («mi
    consultorio está en Av. Gonzalitos 123») o con aqui=true cuando dice que está en
    él («aquí es mi consultorio», «ya llegué a mi casa, guárdala»), que usa la ubicación
    exacta del iPhone. Así los avisos de salida calculan el tráfico aunque el evento solo
    diga «Consultorio», y JARVIS sabe cuándo está en casa. nombre: corto, como «Casa»,
    «Consultorio», «Hospital» o «Casa de la abuela». Si ya existía, se reemplaza.
    Responde «Anotado, Dr. Valles.».
    """
    if context.store is None:
        return {"ok": False, "mensaje": "No puedo guardar el lugar en este momento."}
    if not nombre.strip():
        return {"ok": False, "mensaje": "Necesito el nombre del lugar."}
    if aqui:
        if context.lat is None or context.lon is None:
            return {"ok": False, "mensaje": "No recibí la ubicación del iPhone; dime la dirección."}
        place = await run_in_threadpool(
            save_place,
            context.store,
            nombre,
            direccion or "ubicación guardada desde el iPhone",
            context.lat,
            context.lon,
        )
        return {"ok": True, "lugar": place}
    if not direccion or not direccion.strip():
        return {"ok": False, "mensaje": "Necesito la dirección, o que me digas que estás ahí."}
    place = await run_in_threadpool(save_place, context.store, nombre, direccion)
    return {"ok": True, "lugar": place}
