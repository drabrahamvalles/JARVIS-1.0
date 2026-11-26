from app.context import ToolContext, save_timezone
from app.registry import tool
from app.timezone_state import TimezoneState


@tool
def volver_a_automatico(*, context: ToolContext | None = None) -> dict[str, str | bool]:
    """Desactiva la zona manual y vuelve a resolverla por coordenadas o configuración."""
    save_timezone(TimezoneState(), context)
    return {"ok": True, "modo": "automatico"}
