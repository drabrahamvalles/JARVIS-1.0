from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.calendario import CalendarioError, CalendarioNoConfigurado, get_calendar
from app.context import ToolContext, active_timezone
from app.registry import tool

DURACION_POR_DEFECTO = timedelta(hours=1)


def _parse(value: str, zone: ZoneInfo) -> datetime | date:
    text = value.strip()
    if len(text) == 10:
        return date.fromisoformat(text)
    return datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=zone)


@tool
async def crear_evento(
    titulo: str, inicio: str, fin: str | None, lugar: str | None, *, context: ToolContext
) -> dict[str, object]:
    """Agenda un evento en el Google Calendar del usuario cuando lo pida («agenda…»,
    «ponme una cita…»). No pidas confirmación. inicio: «AAAA-MM-DD HH:MM» local, o solo
    «AAAA-MM-DD» para un evento de todo el día. fin: mismo formato o null (dura 1 hora).
    lugar: texto o null. Nunca pongas nombres de pacientes en el título.
    """
    title = " ".join(titulo.split())[:200]
    if not title:
        return {"ok": False, "mensaje": "Falta el nombre del evento; pregúntale al usuario."}
    zone_name, _ = active_timezone(context)
    zone = ZoneInfo(zone_name)
    try:
        start = _parse(inicio, zone)
        if fin and fin.strip():
            end = _parse(fin, zone)
        elif isinstance(start, datetime):
            end = start + DURACION_POR_DEFECTO
        else:
            end = start
    except ValueError:
        return {"ok": False, "mensaje": "No entendí la fecha u hora; pide que la aclare."}
    if isinstance(start, datetime) != isinstance(end, datetime):
        return {"ok": False, "mensaje": "Inicio y fin deben ser ambos con hora o ambos sin hora."}
    if isinstance(start, datetime):
        if end <= start or end - start > timedelta(days=14):
            return {"ok": False, "mensaje": "La duración del evento no es válida."}
        if start < datetime.now(zone) - timedelta(hours=1):
            return {"ok": False, "mensaje": "Esa fecha ya pasó; pregunta si es otro día."}
    else:
        if end < start or (end - start).days > 14:
            return {"ok": False, "mensaje": "La duración del evento no es válida."}
        end = end + timedelta(days=1)  # Google usa fin exclusivo en eventos de todo el día.
    place = " ".join((lugar or "").split())[:300] or None
    try:
        event = await get_calendar().create_event(title, start, end, zone_name, place)
    except CalendarioNoConfigurado:
        return {"ok": False, "mensaje": "El calendario todavía no está conectado a JARVIS."}
    except CalendarioError:
        return {"ok": False, "mensaje": "Google Calendar no respondió; no se agendó nada."}
    return {"ok": True, "evento": event.para_modelo()}
