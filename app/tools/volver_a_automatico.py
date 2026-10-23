from app.registry import tool
from app.timezone_state import TimezoneState, write_timezone_state


@tool
def volver_a_automatico() -> dict[str, str | bool]:
    """Desactiva la zona manual y vuelve a resolverla por coordenadas o configuración."""
    write_timezone_state(TimezoneState())
    return {"ok": True, "modo": "automatico"}
