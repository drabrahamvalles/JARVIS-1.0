from starlette.concurrency import run_in_threadpool

from app.context import ToolContext
from app.expediente import CATEGORIAS, add_fact
from app.registry import tool


@tool
async def recordar_dato(categoria: str, texto: str, *, context: ToolContext) -> dict[str, object]:
    """Guarda en el expediente un dato duradero que el usuario dijo de sí mismo: rutinas
    («como a las 2», «los martes doy clase»), preferencias, personas importantes
    («mi abuela se llama Rosa»), trabajo o su propia salud. Llámala sin pedir permiso
    cuando él lo cuente o diga «recuerda que…», y responde «Anotado, Dr. Valles.».
    categoria: rutina, preferencia, persona, trabajo, salud u otro. texto: el dato en
    tercera persona y breve. Nunca guardes datos de pacientes ni contraseñas.
    """
    if context.store is None:
        return {"ok": False, "mensaje": "No puedo guardar el dato en este momento."}
    if not texto.strip():
        return {"ok": False, "mensaje": "Falta el dato."}
    fact = await run_in_threadpool(add_fact, context.store, categoria.strip().lower(), texto)
    return {"ok": True, "dato": fact, "categorias": list(CATEGORIAS)}
