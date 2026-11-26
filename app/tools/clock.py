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


def format_local_time(context: ToolContext, home_zone: str, *, include_zone: bool) -> str:
    reading = obtener_hora_actual(context=context)
    time = datetime.fromisoformat(reading["fecha_hora"])
    hour = time.hour % 12 or 12
    opening = "Es la" if hour == 1 else "Son las"
    if time.hour < 6:
        period = "madrugada"
    elif time.hour < 12:
        period = "mañana"
    elif time.hour < 19:
        period = "tarde"
    else:
        period = "noche"

    zone = reading["zona_horaria"]
    location = ""
    if include_zone:
        location = f" en la zona horaria {zone}"
    elif reading["origen"] == "manual" or zone != home_zone:
        area, _, city = zone.rpartition("/")
        if city and area and area != "Etc":
            location = f" en la zona horaria de {city.replace('_', ' ')}"
        else:
            location = f" en la zona horaria {zone}"
    return f"{opening} {hour}:{time.minute:02d} de la {period}{location}, Dr. Valles."
