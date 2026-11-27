from app.context import ToolContext, active_timezone
from app.registry import tool
from app.whoop import WhoopError, WhoopNoConfigurado, get_whoop


@tool
async def consultar_whoop(*, context: ToolContext) -> dict[str, object]:
    """Consulta el WHOOP del usuario: recuperación de hoy (porcentaje y color),
    cómo durmió anoche (horas, rendimiento, sueño profundo y REM, variabilidad cardiaca,
    frecuencia en reposo) y el esfuerzo (strain) de ayer. Úsala para preguntas como
    «¿cómo dormí?» o «¿cuál es mi recuperación?». Si estado es «calculando», dile que
    WHOOP todavía está procesando la noche. Usa los números tal como vienen; no los
    recalcules.
    """
    zone, _ = active_timezone(context)
    try:
        return {"ok": True, **(await get_whoop().summary(zone, context.store))}
    except WhoopNoConfigurado:
        return {"ok": False, "mensaje": "WHOOP todavía no está conectado a JARVIS."}
    except WhoopError:
        return {"ok": False, "mensaje": "WHOOP no respondió; intenta más tarde."}
