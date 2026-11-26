from app.context import ToolContext, active_timezone
from app.registry import tool


@tool
def consultar_zona_horaria(*, context: ToolContext) -> dict[str, str | None]:
    """Devuelve el modo y la zona horaria activos."""
    state = context.read_timezone()
    zone, origin = active_timezone(context)
    return {
        "modo": state.modo,
        "ciudad": state.ciudad,
        "zona_horaria": zone,
        "origen": origin,
    }
