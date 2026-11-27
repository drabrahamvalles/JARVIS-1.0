import asyncio
import logging
import secrets as secure
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI, RateLimitError
from starlette.concurrency import run_in_threadpool

from app.brain import Brain, BrainError
from app.briefing import Briefing, BriefingError
from app.context import TimezoneResolver, active_timezone
from app.registry import ToolRegistry
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
                answer, whoop = await asyncio.gather(
                    service.create(payload, context), whoop_summary(context)
                )
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
