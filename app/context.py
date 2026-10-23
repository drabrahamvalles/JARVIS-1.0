from dataclasses import dataclass
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from timezonefinder import TimezoneFinder

from app.schemas import AskRequest
from app.settings import AppConfig
from app.timezone_state import read_timezone_state

TimezoneOrigin = Literal["coordenadas", "por_defecto", "fijo", "manual"]


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

    def resolve(self, request: AskRequest, config: AppConfig) -> ToolContext:
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
            dispositivo=request.dispositivo,
            zona_horaria_automatica=automatic_name,
            origen_zona_horaria_automatica=automatic_source,
        )

    def close(self) -> None:
        self.finder.cleanup()
