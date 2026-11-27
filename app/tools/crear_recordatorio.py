from datetime import datetime
from zoneinfo import ZoneInfo

from app.context import ToolContext, active_timezone
from app.registry import tool

HORA_POR_DEFECTO = "09:00"


@tool
def crear_recordatorio(titulo: str, cuando: str | None, *, context: ToolContext) -> dict:
    """Crea un recordatorio en la app Recordatorios del iPhone cuando el usuario lo pida
    («recuérdame…»). titulo: la tarea, breve y sin datos de pacientes. cuando: fecha y
    hora local «AAAA-MM-DD HH:MM», solo la fecha «AAAA-MM-DD» (se usa 09:00) o null si
    no dijo cuándo. El iPhone lo guarda al recibir la respuesta; confirma en una oración.
    """
    title = " ".join(titulo.split())[:200]
    if not title:
        return {"ok": False, "mensaje": "Falta qué recordar; pregúntale al usuario."}
    zone, _ = active_timezone(context)
    alert = None
    if cuando and cuando.strip():
        text = cuando.strip()
        if len(text) == 10:
            text = f"{text} {HORA_POR_DEFECTO}"
        try:
            moment = datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=ZoneInfo(zone))
        except ValueError:
            return {"ok": False, "mensaje": "No entendí la fecha; pídele al usuario que la aclare."}
        if moment <= datetime.now(ZoneInfo(zone)):
            return {"ok": False, "mensaje": "Esa hora ya pasó; pregunta para cuándo lo quiere."}
        alert = moment.strftime("%Y-%m-%d %H:%M")
    context.acciones.append({"titulo": title, "alerta": alert})
    return {"ok": True, "titulo": title, "alerta": alert, "zona_horaria": zone}
