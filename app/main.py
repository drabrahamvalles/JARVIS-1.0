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
from app.context import TimezoneResolver
from app.registry import ToolRegistry
from app.schemas import AskRequest, AskResponse
from app.settings import ROOT, AppConfig, Secrets, load_config, load_secrets, runtime_environment

logger = logging.getLogger(__name__)
bearer = HTTPBearer(auto_error=False)


def create_app(*, config: AppConfig | None = None, secrets: Secrets | None = None) -> FastAPI:
    host = (runtime_environment().get("HOST") or "127.0.0.1").strip()
    expose_docs = host == "127.0.0.1"

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.config = config if config is not None else load_config()
        app.state.secrets = secrets if secrets is not None else load_secrets()
        registry = ToolRegistry.discover()
        personality = (ROOT / "config/personalidad.md").read_text(encoding="utf-8")
        resolver = await run_in_threadpool(TimezoneResolver)
        app.state.resolver = resolver
        client = None
        app.state.brain = None
        try:
            if app.state.secrets.openai_api_key:
                client = AsyncOpenAI(
                    api_key=app.state.secrets.openai_api_key,
                    timeout=20.0,
                    max_retries=1,
                )
                app.state.brain = Brain(client, app.state.config, personality, registry)
            else:
                logger.warning("OPENAI_API_KEY no configurada; /ask no está disponible")
            if not app.state.secrets.jarvis_token:
                logger.warning("JARVIS_TOKEN no configurado; /ask permanece cerrado")
            yield
        finally:
            if client is not None:
                await client.close()
            await run_in_threadpool(resolver.close)

    application = FastAPI(
        title="JARVIS · Fase 1",
        version="0.1.0",
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

    @application.post("/ask", response_model=AskResponse, dependencies=[Depends(require_token)])
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
            return AskResponse(respuesta=answer)
        except (APITimeoutError, TimeoutError):
            raise HTTPException(504, "OpenAI tardó demasiado en responder") from None
        except RateLimitError:
            raise HTTPException(503, "OpenAI está ocupado o sin cuota disponible") from None
        except (APIStatusError, APIConnectionError, BrainError) as exc:
            logger.warning("ask_failed kind=%s", type(exc).__name__)
            raise HTTPException(502, "No fue posible obtener una respuesta de OpenAI") from None

    return application


app = create_app()
