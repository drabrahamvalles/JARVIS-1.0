from datetime import datetime
from zoneinfo import ZoneInfo

from app.context import ToolContext, active_timezone
from app.registry import tool


@tool
def obtener_hora_actual(*, context: ToolContext) -> dict[str, str]:
    """Obtiene la fecha y hora actuales usando siempre la zona horaria activa."""
    zone, origin = active_timezone(context)
    return {
        "fecha_hora": datetime.now(ZoneInfo(zone)).isoformat(timespec="seconds"),
        "zona_horaria": zone,
        "origen": origin,
    }
