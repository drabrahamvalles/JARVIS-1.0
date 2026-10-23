from app.registry import tool
from app.timezone_state import TimezoneState, is_valid_timezone, write_timezone_state


@tool
def fijar_zona_horaria(ciudad: str, zona_iana: str) -> dict[str, str | bool]:
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
    write_timezone_state(TimezoneState("manual", city, zone))
    return {"ok": True, "modo": "manual", "ciudad": city, "zona_horaria": zone}
