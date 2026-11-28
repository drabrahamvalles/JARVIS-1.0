import asyncio
import logging
import secrets as secure
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI, RateLimitError
from starlette.concurrency import run_in_threadpool

from app.avisos import Avisos
from app.brain import Brain, BrainError
from app.briefing import Briefing, BriefingError
from app.calendario import CalendarioError, CalendarioNoConfigurado
from app.context import TimezoneResolver, active_timezone
from app.gmail import GmailError, GmailNoConfigurado
from app.registry import ToolRegistry
from app.revision_correo import RevisorCorreo, notice_sentence
from app.revision_whatsapp import LoteWhatsApp, RevisorWhatsApp
from app.rutina import Rutina, distance_m
from app.schemas import (
    AskRequest,
    AskResponse,
    BriefingRequest,
    BriefingResponse,
    CapturaRequest,
    CapturaResponse,
    WhoopRequest,
    WhoopResponse,
)
from app.settings import ROOT, AppConfig, Secrets, load_config, load_secrets, runtime_environment
from app.storage import Store, build_store
from app.tools.captura import (
    Captura,
    CapturaError,
    ImagenDemasiadoGrandeError,
    ImagenInvalidaError,
)
from app.whoop import WhoopError, WhoopNoConfigurado, get_whoop

logger = logging.getLogger(__name__)
bearer = HTTPBearer(auto_error=False)
WHOOP_PENDIENTE = (
    "WHOOP todavía está calculando su noche; en cuanto termine le doy su recuperación."
)


def append_location_log(store, location: dict) -> None:
    """Historial para aprender lugares; se salta puntos repetidos de menos de 20 minutos."""
    log = store.read_ubicaciones() or {}
    points = list(log.get("puntos") or [])
    if points:
        last = points[-1]
        recent = datetime.fromisoformat(location["en"]) - datetime.fromisoformat(last["en"])
        close = distance_m((last["lat"], last["lon"]), (location["lat"], location["lon"])) < 100
        if recent < timedelta(minutes=20) and close:
            return
    points.append({k: location[k] for k in ("lat", "lon", "en")})
    store.write_ubicaciones({"puntos": points[-1000:]})


async def remember_location(context) -> None:
    """Guarda la última ubicación del iPhone para calcular los avisos de salida."""
    if context.store is None or context.lat is None or context.lon is None:
        return
    location = {
        "lat": context.lat,
        "lon": context.lon,
        "en": datetime.now(UTC).isoformat(),
    }
    try:
        await run_in_threadpool(context.store.write_ubicacion, location)
        await run_in_threadpool(append_location_log, context.store, location)
    except Exception as exc:
        logger.warning("storage_failed operation=location_write kind=%s", type(exc).__name__)


async def append_email_notices(answer: str, context) -> str:
    """Agrega al briefing lo que la revisión de correo agendó y vacía la lista de avisos."""
    store = context.store
    if store is None:
        return answer
    try:
        state = await run_in_threadpool(store.read_correo_revision)
        sentence = notice_sentence((state or {}).get("avisos") or [])
        if sentence is None:
            return answer
        await run_in_threadpool(store.write_correo_revision, {**state, "avisos": []})
    except Exception as exc:
        logger.warning("storage_failed operation=email_notices kind=%s", type(exc).__name__)
        return answer
    return f"{answer} {sentence}"


async def whoop_summary(context) -> dict | None:
    """Resumen de WHOOP, o None si no está conectado o no respondió."""
    zone, _ = active_timezone(context)
    try:
        return await get_whoop().summary(zone, context.store)
    except WhoopNoConfigurado:
        return None
    except (WhoopError, TimeoutError, ValueError) as exc:
        logger.warning("whoop_failed kind=%s", type(exc).__name__)
        return None


def create_app(
    *, config: AppConfig | None = None, secrets: Secrets | None = None, store: Store | None = None
) -> FastAPI:
    env = runtime_environment()
    host = (env.get("HOST") or "127.0.0.1").strip()
    expose_docs = host == "127.0.0.1"

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.config = config if config is not None else load_config()
        app.state.secrets = secrets if secrets is not None else load_secrets()
        registry = ToolRegistry.discover()
        personality = (ROOT / "config/personalidad.md").read_text(encoding="utf-8")
        storage = store if store is not None else build_store(env)
        resolver = await run_in_threadpool(TimezoneResolver, storage)
        app.state.resolver = resolver
        client = None
        app.state.brain = None
        app.state.briefing = None
        app.state.captura = None
        app.state.revisor = None
        app.state.avisos = Avisos(
            {
                code: airport.alias[0]
                for code, airport in app.state.config.zonas_horarias_vuelos.items()
            }
        )
        try:
            if app.state.secrets.openai_api_key:
                client = AsyncOpenAI(
                    api_key=app.state.secrets.openai_api_key,
                    timeout=20.0,
                    max_retries=1,
                )
                app.state.brain = Brain(
                    client, app.state.config, personality, registry, store=storage
                )
                app.state.briefing = Briefing(client, app.state.config, personality)
                app.state.captura = Captura(client, app.state.config, personality)
                app.state.revisor = RevisorCorreo(client, app.state.config)
            else:
                logger.warning("OPENAI_API_KEY no configurada; endpoints de OpenAI no disponibles")
            if not app.state.secrets.jarvis_token:
                logger.warning("JARVIS_TOKEN no configurado; endpoints protegidos cerrados")
            yield
        finally:
            if client is not None:
                await client.close()
            await run_in_threadpool(resolver.close)

    application = FastAPI(
        title="JARVIS · Fase 5",
        version="0.5.0",
        lifespan=lifespan,
        docs_url="/docs" if expose_docs else None,
        redoc_url="/redoc" if expose_docs else None,
        openapi_url="/openapi.json" if expose_docs else None,
    )

    async def require_token(
        request: Request,
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    ) -> None:
        expected = request.app.state.secrets.jarvis_token
        if not expected:
            raise HTTPException(503, "JARVIS_TOKEN no configurado")
        if credentials is None or not secure.compare_digest(
            credentials.credentials.encode("utf-8"), expected.encode("utf-8")
        ):
            raise HTTPException(
                401, "Token inválido o ausente", headers={"WWW-Authenticate": "Bearer"}
            )

    @application.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.post(
        "/ask",
        response_model=AskResponse,
        response_model_exclude_none=True,
        dependencies=[Depends(require_token)],
    )
    async def ask(payload: AskRequest, request: Request) -> AskResponse:
        brain = request.app.state.brain
        if brain is None:
            raise HTTPException(503, "OPENAI_API_KEY no configurada")
        try:
            async with asyncio.timeout(90):
                context = await run_in_threadpool(
                    request.app.state.resolver.resolve, payload, request.app.state.config
                )
                await remember_location(context)
                answer = await brain.ask(payload, context)
            reminder = context.acciones[-1] if context.acciones else {}
            return AskResponse(
                respuesta=answer,
                recordatorio_titulo=reminder.get("titulo"),
                recordatorio_alerta=reminder.get("alerta"),
            )
        except (APITimeoutError, TimeoutError):
            raise HTTPException(504, "OpenAI tardó demasiado en responder") from None
        except RateLimitError:
            raise HTTPException(503, "OpenAI está ocupado o sin cuota disponible") from None
        except (APIStatusError, APIConnectionError, BrainError) as exc:
            logger.warning("ask_failed kind=%s", type(exc).__name__)
            raise HTTPException(502, "No fue posible obtener una respuesta de OpenAI") from None

    @application.post(
        "/briefing",
        response_model=BriefingResponse,
        response_model_exclude_none=True,
        dependencies=[Depends(require_token)],
    )
    async def briefing(payload: BriefingRequest, request: Request) -> BriefingResponse:
        service = request.app.state.briefing
        if service is None:
            raise HTTPException(503, "OPENAI_API_KEY no configurada")
        try:
            async with asyncio.timeout(90):
                context = await run_in_threadpool(
                    request.app.state.resolver.resolve, payload, request.app.state.config
                )
                await remember_location(context)
                answer, whoop = await asyncio.gather(
                    service.create(payload, context), whoop_summary(context)
                )
                answer = await append_email_notices(answer, context)
            # El texto de WHOOP lo arma el servidor con los números exactos.
            if whoop is None or whoop["estado"] == "sin_datos":
                return BriefingResponse(respuesta=answer)
            if whoop["estado"] == "calculando":
                return BriefingResponse(
                    respuesta=f"{answer} {WHOOP_PENDIENTE}", whoop_pendiente=True
                )
            return BriefingResponse(respuesta=f"{answer} {whoop['texto']}", whoop_pendiente=False)
        except (APITimeoutError, TimeoutError):
            raise HTTPException(504, "OpenAI tardó demasiado en responder") from None
        except RateLimitError:
            raise HTTPException(503, "OpenAI está ocupado o sin cuota disponible") from None
        except (APIStatusError, APIConnectionError, BriefingError) as exc:
            logger.warning("briefing_failed kind=%s", type(exc).__name__)
            raise HTTPException(502, "No fue posible generar el briefing") from None

    @application.post(
        "/captura", response_model=CapturaResponse, dependencies=[Depends(require_token)]
    )
    async def captura(payload: CapturaRequest, request: Request) -> CapturaResponse:
        service = request.app.state.captura
        if service is None:
            raise HTTPException(503, "OPENAI_API_KEY no configurada")
        try:
            async with asyncio.timeout(90):
                context = await run_in_threadpool(
                    request.app.state.resolver.resolve, payload, request.app.state.config
                )
                await remember_location(context)
                return await service.analyze(payload, context)
        except ImagenDemasiadoGrandeError:
            raise HTTPException(413, "La imagen supera el límite de 5 MB") from None
        except ImagenInvalidaError:
            raise HTTPException(
                422, "La imagen debe ser Base64 válido en formato PNG, JPEG, WebP o GIF no animado"
            ) from None
        except (APITimeoutError, TimeoutError):
            raise HTTPException(504, "OpenAI tardó demasiado en responder") from None
        except RateLimitError:
            raise HTTPException(503, "OpenAI está ocupado o sin cuota disponible") from None
        except (APIStatusError, APIConnectionError, CapturaError) as exc:
            logger.warning("captura_failed kind=%s", type(exc).__name__)
            raise HTTPException(502, "No fue posible analizar la captura") from None

    @application.post("/whatsapp/mensajes", dependencies=[Depends(require_token)])
    async def whatsapp_mensajes(payload: LoteWhatsApp, request: Request) -> dict:
        """El lector de WhatsApp de la Mac manda aquí los mensajes nuevos con posibles citas."""
        service = request.app.state.revisor
        if service is None:
            raise HTTPException(503, "OPENAI_API_KEY no configurada")
        context = await run_in_threadpool(
            request.app.state.resolver.resolve, WhoopRequest(), request.app.state.config
        )
        try:
            async with asyncio.timeout(150):
                return await RevisorWhatsApp(service).revisar(payload, context)
        except CalendarioNoConfigurado:
            raise HTTPException(503, "Calendar no está conectado") from None
        except (
            CalendarioError,
            TimeoutError,
            APIStatusError,
            APIConnectionError,
            APITimeoutError,
            RateLimitError,
            RuntimeError,
        ) as exc:
            logger.warning("whatsapp_failed kind=%s", type(exc).__name__)
            raise HTTPException(502, "No fue posible revisar WhatsApp") from None

    @application.post("/ubicacion", dependencies=[Depends(require_token)])
    async def ubicacion(payload: WhoopRequest, request: Request) -> dict:
        """El Atajo automático manda aquí la ubicación cada 2 horas para aprender lugares."""
        if payload.lat is None or payload.lon is None:
            raise HTTPException(422, "Faltan lat y lon")
        context = await run_in_threadpool(
            request.app.state.resolver.resolve, payload, request.app.state.config
        )
        await remember_location(context)
        return {"ok": True}

    @application.post("/tareas/avisos", dependencies=[Depends(require_token)])
    async def avisos(request: Request) -> dict:
        """El despertador la llama cada 10 minutos: avisa cuándo salir a cada evento."""
        service = request.app.state.avisos
        context = await run_in_threadpool(
            request.app.state.resolver.resolve, WhoopRequest(), request.app.state.config
        )
        if context.store is None:
            raise HTTPException(503, "Sin almacenamiento")
        zone, _ = active_timezone(context)
        try:
            async with asyncio.timeout(60):
                result = await service.run(context.store, zone)
                # Aprender lugares y hacer preguntas por iniciativa propia (según la hora).
                result.update(await Rutina(service.speak).run(context.store, zone))
                return result
        except (CalendarioNoConfigurado, GmailNoConfigurado):
            return {"hablados": []}
        except (CalendarioError, GmailError, TimeoutError, httpx.HTTPError) as exc:
            logger.warning("avisos_failed kind=%s", type(exc).__name__)
            raise HTTPException(502, "No fue posible revisar los avisos") from None

    @application.post("/tareas/revisar-correo", dependencies=[Depends(require_token)])
    async def revisar_correo(request: Request) -> dict:
        """Cloud Scheduler la llama a las 6:00, 15:00 y 21:00."""
        service = request.app.state.revisor
        if service is None:
            raise HTTPException(503, "OPENAI_API_KEY no configurada")
        context = await run_in_threadpool(
            request.app.state.resolver.resolve, WhoopRequest(), request.app.state.config
        )
        try:
            async with asyncio.timeout(150):
                return await service.revisar(context)
        except (GmailNoConfigurado, CalendarioNoConfigurado):
            raise HTTPException(503, "Gmail o Calendar no están conectados") from None
        except (
            GmailError,
            CalendarioError,
            TimeoutError,
            APIStatusError,
            APIConnectionError,
            APITimeoutError,
            RateLimitError,
            RuntimeError,
        ) as exc:
            logger.warning("revision_correo_failed kind=%s", type(exc).__name__)
            raise HTTPException(502, "No fue posible revisar el correo") from None

    @application.post("/whoop", response_model=WhoopResponse, dependencies=[Depends(require_token)])
    async def whoop(payload: WhoopRequest, request: Request) -> WhoopResponse:
        """El Atajo del briefing lo llama cada 30 s mientras WHOOP calcula la noche."""
        context = await run_in_threadpool(
            request.app.state.resolver.resolve, payload, request.app.state.config
        )
        try:
            async with asyncio.timeout(20):
                summary = await whoop_summary(context)
        except TimeoutError:
            summary = None
        if summary is None:
            return WhoopResponse(listo=False, respuesta="No pude consultar WHOOP.")
        if summary["estado"] == "calculando":
            return WhoopResponse(listo=False, respuesta=summary["texto"])
        return WhoopResponse(listo=True, respuesta=summary["texto"])

    return application


app = create_app()
