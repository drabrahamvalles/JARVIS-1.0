import logging
from datetime import UTC, datetime

from starlette.concurrency import run_in_threadpool

from app.confirmacion import es_confirmacion
from app.context import ToolContext
from app.gmail import GmailError, GmailNoConfigurado, GmailSinPermisoDeEnvio, get_gmail
from app.registry import tool

logger = logging.getLogger(__name__)


@tool
async def confirmar_envio_correo(*, context: ToolContext) -> dict[str, object]:
    """Envía el correo que preparó proponer_correo. Llámala una sola vez y solo cuando
    el usuario, en un mensaje posterior a tu pregunta, confirme explícitamente el envío
    (por ejemplo «sí, envíalo»). Si duda, quiere cambiar algo o dice que no, no la
    llames.
    """
    if context.store is None:
        return {"ok": False, "mensaje": "No puedo leer el borrador en este momento."}
    try:
        pending = await run_in_threadpool(context.store.read_pending_email)
    except Exception as exc:
        logger.warning("storage_failed operation=pending_email_read kind=%s", type(exc).__name__)
        return {"ok": False, "mensaje": "No pude leer el borrador; no envié nada."}
    if not pending:
        return {"ok": False, "mensaje": "No hay ningún correo pendiente de enviar."}
    try:
        expired = datetime.fromisoformat(pending["expira_en"]) <= datetime.now(UTC)
    except (KeyError, TypeError, ValueError):
        expired = True
    if expired:
        await run_in_threadpool(context.store.write_pending_email, None)
        return {"ok": False, "mensaje": "El borrador venció; vuelve a prepararlo."}
    # Igual que el borrado: la confirmación llega en otra petición y debe ser afirmativa.
    if pending.get("solicitud_id") == context.solicitud_id or not es_confirmacion(
        context.texto_usuario
    ):
        return {
            "ok": False,
            "mensaje": "Falta la confirmación explícita del usuario; pregúntale primero.",
        }
    # Se consume antes de enviar: un error de red nunca termina en un correo duplicado.
    await run_in_threadpool(context.store.write_pending_email, None)
    try:
        await get_gmail().send(pending["para"], pending["asunto"], pending["cuerpo"])
    except GmailSinPermisoDeEnvio:
        return {"ok": False, "mensaje": "JARVIS todavía no tiene permiso para enviar correos."}
    except GmailNoConfigurado:
        return {"ok": False, "mensaje": "El correo todavía no está conectado a JARVIS."}
    except GmailError:
        return {"ok": False, "mensaje": "Gmail no respondió; no sé si se envió. Revisa Enviados."}
    return {"ok": True, "enviado": {"para": pending["para"], "asunto": pending["asunto"]}}
