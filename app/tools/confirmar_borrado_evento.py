import logging
import re
import unicodedata
from datetime import UTC, datetime

from starlette.concurrency import run_in_threadpool

from app.calendario import CalendarioError, CalendarioNoConfigurado, get_calendar
from app.context import ToolContext
from app.registry import tool

logger = logging.getLogger(__name__)

AFIRMACION = re.compile(
    r"\b(si|confirmo|confirmado|borralo|borrala|eliminalo|eliminala|adelante|hazlo|dale|claro"
    r"|correcto|de acuerdo|ok|okay)\b"
)
NEGACION = re.compile(r"\b(no|espera|cancela|cancelalo|mejor no|todavia no|aun no)\b")


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(character for character in decomposed if not unicodedata.combining(character))


def es_confirmacion(text: str) -> bool:
    normalized = _normalize(text)
    return bool(AFIRMACION.search(normalized)) and not NEGACION.search(normalized)


@tool
async def confirmar_borrado_evento(*, context: ToolContext) -> dict[str, object]:
    """Borra el evento que propuso proponer_borrado_evento. Llámala solo cuando el
    usuario, en un mensaje posterior a tu pregunta, confirme explícitamente el borrado
    (por ejemplo «sí, bórralo»). Si duda, cambia de tema o dice que no, no la llames.
    """
    if context.store is None:
        return {"ok": False, "mensaje": "No puedo leer la confirmación en este momento."}
    try:
        pending = await run_in_threadpool(context.store.read_pending_delete)
    except Exception as exc:
        logger.warning("storage_failed operation=pending_delete_read kind=%s", type(exc).__name__)
        return {"ok": False, "mensaje": "No pude leer la confirmación; no borré nada."}
    if not pending:
        return {"ok": False, "mensaje": "No hay ningún borrado pendiente de confirmar."}
    try:
        expired = datetime.fromisoformat(pending["expira_en"]) <= datetime.now(UTC)
    except (KeyError, TypeError, ValueError):
        expired = True
    if expired:
        await run_in_threadpool(context.store.write_pending_delete, None)
        return {"ok": False, "mensaje": "La propuesta de borrado venció; vuelve a proponerla."}
    # El servidor exige que la confirmación llegue en otra petición y que sea afirmativa.
    if pending.get("solicitud_id") == context.solicitud_id or not es_confirmacion(
        context.texto_usuario
    ):
        return {
            "ok": False,
            "mensaje": "Falta la confirmación explícita del usuario; pregúntale primero.",
        }
    try:
        deleted = await get_calendar().delete_event(pending["evento_id"])
    except (CalendarioNoConfigurado, CalendarioError, ValueError):
        return {"ok": False, "mensaje": "Google Calendar no respondió; no borré nada."}
    await run_in_threadpool(context.store.write_pending_delete, None)
    if not deleted:
        return {"ok": False, "mensaje": "El evento ya no existía."}
    return {
        "ok": True,
        "borrado": {"titulo": pending.get("titulo"), "inicio": pending.get("inicio")},
    }
