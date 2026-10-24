from dataclasses import dataclass
from typing import Literal, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from timezonefinder import TimezoneFinder

from app.settings import AppConfig
from app.timezone_state import read_timezone_state

TimezoneOrigin = Literal["coordenadas", "por_defecto", "fijo", "manual"]


class CoordinatesRequest(Protocol):
    lat: float | None
    lon: float | None


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


def active_timezone(context: ToolContext) -> tuple[str, TimezoneOrigin]:
    state = read_timezone_state()
    if state.modo == "manual" and state.zona_horaria is not None:
        return state.zona_horaria, "manual"
    return (
        context.zona_horaria_automatica or context.zona_horaria,
        context.origen_zona_horaria_automatica or context.origen_zona_horaria,
    )


class TimezoneResolver:
    def __init__(self) -> None:
        # Un único índice local por servidor, reutilizado entre solicitudes.
        self.finder = TimezoneFinder()

    def resolve(self, request: CoordinatesRequest, config: AppConfig) -> ToolContext:
        name = config.zona_horaria_por_defecto
        source = "fijo" if config.modo_zona_horaria == "fijo" else "por_defecto"
        if config.modo_zona_horaria == "automatico" and request.lat is not None:
            candidate = self.finder.timezone_at(lat=request.lat, lng=request.lon)
            if candidate:
                try:
                    ZoneInfo(candidate)
                except (ZoneInfoNotFoundError, ValueError):
                    pass
                else:
                    name, source = candidate, "coordenadas"
        automatic_name, automatic_source = name, source
        state = read_timezone_state()
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
        )

    def close(self) -> None:
        self.finder.cleanup()
