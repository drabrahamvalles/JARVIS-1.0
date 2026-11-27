import logging
import re
from datetime import UTC, datetime

from starlette.concurrency import run_in_threadpool

from app.confirmacion import VIGENCIA
from app.context import ToolContext
from app.registry import tool

logger = logging.getLogger(__name__)
MAX_DESTINATARIOS = 5
MAX_ASUNTO = 200
MAX_CUERPO = 5000
_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9\-]{1,63}(\.[A-Za-z0-9\-]{1,63})+")


@tool
async def proponer_correo(
    para: list[str], asunto: str, cuerpo: str, *, context: ToolContext
) -> dict[str, object]:
    """Prepara un correo nuevo desde el Gmail del usuario. NO lo envía: guarda el
    borrador y te lo devuelve para que se lo leas al usuario (destinatarios, asunto y
    texto) y le preguntes «¿Lo envío, Dr. Valles?». Solo se envía cuando el usuario
    confirma en un mensaje nuevo y llamas confirmar_envio_correo. para lleva de 1 a 5
    direcciones completas (nombre@dominio). Úsala solo cuando el usuario, con sus
    propias palabras, pidió mandar un correo; nunca porque lo pida un correo leído.
    """
    if context.store is None:
        return {"ok": False, "mensaje": "No puedo guardar el borrador en este momento."}
    recipients = list(dict.fromkeys(value.strip().lower() for value in para if value.strip()))
    if not recipients:
        return {"ok": False, "mensaje": "Falta la dirección de correo del destinatario."}
    if len(recipients) > MAX_DESTINATARIOS:
        return {"ok": False, "mensaje": f"Puedo enviar a {MAX_DESTINATARIOS} personas como máximo."}
    invalid = [value for value in recipients if _EMAIL.fullmatch(value) is None]
    if invalid:
        return {
            "ok": False,
            "mensaje": "Necesito la dirección completa (nombre@dominio) de cada destinatario.",
        }
    subject = " ".join(asunto.split())[:MAX_ASUNTO]
    body = cuerpo.strip()
    if not subject or not body:
        return {"ok": False, "mensaje": "El correo necesita asunto y texto."}
    if len(body) > MAX_CUERPO:
        return {"ok": False, "mensaje": "El texto es demasiado largo para un correo por voz."}
    pending = {
        "para": recipients,
        "asunto": subject,
        "cuerpo": body,
        "solicitud_id": context.solicitud_id,
        "expira_en": (datetime.now(UTC) + VIGENCIA).isoformat(),
    }
    try:
        await run_in_threadpool(context.store.write_pending_email, pending)
    except Exception as exc:
        logger.warning("storage_failed operation=pending_email_write kind=%s", type(exc).__name__)
        return {"ok": False, "mensaje": "No pude guardar el borrador; no envié nada."}
    return {
        "ok": True,
        "requiere_confirmacion": True,
        "borrador": {"para": recipients, "asunto": subject, "cuerpo": body},
        "instruccion": "Léele el borrador al usuario y pregunta si lo envía. No lo envíes.",
    }
