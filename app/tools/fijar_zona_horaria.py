from app.context import ToolContext, save_timezone
from app.registry import tool
from app.timezone_state import TimezoneState, is_valid_timezone


@tool
def fijar_zona_horaria(
    ciudad: str, zona_iana: str, *, context: ToolContext | None = None
) -> dict[str, str | bool]:
    """Fija una ciudad y zona IANA manuales. Propón zona_iana; si la ciudad es ambigua,
    pregunta primero al usuario y no llames la herramienta hasta aclararla.
    """
    city = ciudad.strip()
    zone = zona_iana.strip()
    if not city or len(city) > 120 or not is_valid_timezone(zone):
        return {
            "ok": False,
            "requiere_aclaracion": True,
            "mensaje": "La ciudad o la zona IANA no es válida; pide al usuario que la aclare.",
        }
    save_timezone(TimezoneState("manual", city, zone), context)
    return {"ok": True, "modo": "manual", "ciudad": city, "zona_horaria": zone}
