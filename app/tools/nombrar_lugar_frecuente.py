from starlette.concurrency import run_in_threadpool

from app.context import ToolContext
from app.expediente import save_place
from app.registry import tool


def _name_pending(store, name: str) -> dict | None:
    state = store.read_rutina() or {}
    pending = state.get("pregunta_pendiente")
    if not pending or pending.get("lat") is None:
        return None
    place = save_place(
        store, name, "lugar aprendido por ubicación", float(pending["lat"]), float(pending["lon"])
    )
    state["pregunta_pendiente"] = None
    state["sin_nombre"] = [
        p
        for p in state.get("sin_nombre") or []
        if (p["lat"], p["lon"]) != (pending["lat"], pending["lon"])
    ]
    store.write_rutina(state)
    return place


@tool
async def nombrar_lugar_frecuente(nombre: str, *, context: ToolContext) -> dict[str, object]:
    """Ponle nombre al lugar frecuente por el que JARVIS acaba de preguntar («veo que
    suele ir a un mismo lugar… ¿qué lugar es?» o «¿es su casa?»). Llámala cuando el
    usuario conteste con el nombre («es el hospital», «sí, es mi casa» → «Casa»).
    Responde «Anotado, Dr. Valles.».
    """
    if context.store is None or not nombre.strip():
        return {"ok": False, "mensaje": "No pude guardar el nombre del lugar."}
    place = await run_in_threadpool(_name_pending, context.store, nombre.strip())
    if place is None:
        return {"ok": False, "mensaje": "No tengo ningún lugar pendiente de nombre."}
    return {"ok": True, "lugar": place}
