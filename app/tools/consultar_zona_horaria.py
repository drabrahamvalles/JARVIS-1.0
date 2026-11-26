from app.context import ToolContext, active_timezone
from app.registry import tool
from app.timezone_state import read_timezone_state


@tool
def consultar_zona_horaria(*, context: ToolContext) -> dict[str, str | None]:
    """Devuelve el modo y la zona horaria activos."""
    state = read_timezone_state()
    zone, origin = active_timezone(context)
    return {
        "modo": state.modo,
        "ciudad": state.ciudad,
        "zona_horaria": zone,
        "origen": origin,
    }
