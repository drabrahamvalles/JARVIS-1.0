import logging
from dataclasses import dataclass, field, replace
from typing import Literal, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from timezonefinder import TimezoneFinder

from app.settings import AppConfig
from app.storage import Store
from app.timezone_state import (
    TimezoneState,
    TimezoneWriteError,
    read_timezone_state,
    write_timezone_state,
)

TimezoneOrigin = Literal["coordenadas", "por_defecto", "fijo", "manual"]
logger = logging.getLogger(__name__)


class CoordinatesRequest(Protocol):
    lat: float | None
    lon: float | None


@dataclass
class TimezoneSession:
    store: Store
    state: TimezoneState
    read_failed: bool = False


@dataclass(frozen=True)
class ToolContext:
    zona_horaria: str
    origen_zona_horaria: TimezoneOrigin
    ciudad_referencia: str
    lat: float | None = None
    lon: float | None = None
    dispositivo: str | None = None
    zona_horaria_automatica: str | None = None
    origen_zona_horaria_automatica: TimezoneOrigin | None = None
    latitud_clima: float | None = None
    longitud_clima: float | None = None
    timezone_session: TimezoneSession | None = field(default=None, repr=False, compare=False)
    zona_por_coordenadas: str | None = None

    def read_timezone(self) -> TimezoneState:
        return self.timezone_session.state if self.timezone_session else read_timezone_state()

    def automatic_after_read_failure(self, store: Store) -> "ToolContext":
        return replace(
            self, timezone_session=TimezoneSession(store, TimezoneState(), read_failed=True)
        )


def active_timezone(context: ToolContext) -> tuple[str, TimezoneOrigin]:
    state = context.read_timezone()
    if state.modo == "manual" and state.zona_horaria is not None:
        return state.zona_horaria, "manual"
    if (
        context.timezone_session
        and context.timezone_session.read_failed
        and context.zona_por_coordenadas
    ):
        return context.zona_por_coordenadas, "coordenadas"
    return (
        context.zona_horaria_automatica or context.zona_horaria,
        context.origen_zona_horaria_automatica or context.origen_zona_horaria,
    )


def save_timezone(state: TimezoneState, context: ToolContext | None) -> None:
    session = context.timezone_session if context else None
    try:
        if session is None:
            write_timezone_state(state)
        else:
            session.store.write_timezone(state)
            session.state = state
    except Exception as exc:
        logger.warning("storage_failed operation=timezone_write kind=%s", type(exc).__name__)
        raise TimezoneWriteError from None


class TimezoneResolver:
    def __init__(self, store: Store | None = None) -> None:
        # Un único índice local por servidor, reutilizado entre solicitudes.
        self.finder = TimezoneFinder()
        self.store = store

    def resolve(self, request: CoordinatesRequest, config: AppConfig) -> ToolContext:
        name = config.zona_horaria_por_defecto
        source = "fijo" if config.modo_zona_horaria == "fijo" else "por_defecto"
        coordinates_zone = None
        if request.lat is not None and (
            self.store is not None or config.modo_zona_horaria == "automatico"
        ):
            candidate = self.finder.timezone_at(lat=request.lat, lng=request.lon)
            if candidate:
                try:
                    ZoneInfo(candidate)
                except (ZoneInfoNotFoundError, ValueError):
                    pass
                else:
                    coordinates_zone = candidate
        if config.modo_zona_horaria == "automatico" and coordinates_zone is not None:
            name, source = coordinates_zone, "coordenadas"
        automatic_name, automatic_source = name, source
        read_failed = False
        try:
            state = self.store.read_timezone() if self.store is not None else read_timezone_state()
        except Exception as exc:
            logger.warning("storage_failed operation=timezone_read kind=%s", type(exc).__name__)
            read_failed = True
            state = TimezoneState()
        if state.modo == "manual" and state.zona_horaria is not None:
            name, source = state.zona_horaria, "manual"
        return ToolContext(
            zona_horaria=name,
            origen_zona_horaria=source,
            ciudad_referencia=config.ciudad,
            lat=request.lat,
            lon=request.lon,
            dispositivo=getattr(request, "dispositivo", None),
            zona_horaria_automatica=automatic_name,
            origen_zona_horaria_automatica=automatic_source,
            latitud_clima=(request.lat if request.lat is not None else config.latitud_por_defecto),
            longitud_clima=(
                request.lon if request.lon is not None else config.longitud_por_defecto
            ),
            timezone_session=(
                TimezoneSession(self.store, state, read_failed) if self.store is not None else None
            ),
            zona_por_coordenadas=coordinates_zone,
        )

    def close(self) -> None:
        self.finder.cleanup()
