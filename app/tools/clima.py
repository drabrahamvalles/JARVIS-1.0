import math
from datetime import date
from typing import Any

import httpx

from app.context import ToolContext, active_timezone
from app.registry import tool

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
DAILY_FIELDS = (
    "temperature_2m_min",
    "temperature_2m_max",
    "precipitation_probability_max",
)


class ClimaError(Exception):
    """Open-Meteo no entregó un pronóstico diario utilizable."""


def _numeric_series(daily: dict[str, Any], field: str) -> list[float]:
    values = daily.get(field)
    if not isinstance(values, list) or len(values) < 8:
        raise ClimaError("Pronóstico incompleto")
    result: list[float] = []
    for value in values[:8]:
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ClimaError("Dato meteorológico inválido")
        number = float(value)
        if not math.isfinite(number):
            raise ClimaError("Dato meteorológico inválido")
        result.append(number)
    return result


def _parse_forecast(payload: Any, expected_timezone: str) -> dict[str, object]:
    if not isinstance(payload, dict) or payload.get("timezone") != expected_timezone:
        raise ClimaError("Zona horaria inesperada")
    daily = payload.get("daily")
    units = payload.get("daily_units")
    if not isinstance(daily, dict) or not isinstance(units, dict):
        raise ClimaError("Respuesta meteorológica inválida")
    if units.get("temperature_2m_min") != "°C" or units.get("temperature_2m_max") != "°C":
        raise ClimaError("Unidad de temperatura inesperada")
    if units.get("precipitation_probability_max") != "%":
        raise ClimaError("Unidad de lluvia inesperada")

    raw_dates = daily.get("time")
    if not isinstance(raw_dates, list) or len(raw_dates) < 8:
        raise ClimaError("Pronóstico incompleto")
    dates: list[str] = []
    for value in raw_dates[:8]:
        if not isinstance(value, str):
            raise ClimaError("Fecha meteorológica inválida")
        try:
            parsed = date.fromisoformat(value)
        except ValueError as exc:
            raise ClimaError("Fecha meteorológica inválida") from exc
        dates.append(parsed.isoformat())

    minimums = _numeric_series(daily, "temperature_2m_min")
    maximums = _numeric_series(daily, "temperature_2m_max")
    rain = _numeric_series(daily, "precipitation_probability_max")
    days = [
        {
            "fecha": dates[index],
            "minima_c": minimums[index],
            "maxima_c": maximums[index],
            "lluvia_pct": rain[index],
        }
        for index in range(8)
    ]
    return {"zona_horaria": expected_timezone, "dias": days}


@tool
async def obtener_clima(*, context: ToolContext) -> dict[str, object]:
    """Obtiene mínima, máxima y probabilidad de lluvia de hoy y los próximos siete días."""
    if context.latitud_clima is None or context.longitud_clima is None:
        raise ClimaError("No hay ubicación meteorológica")
    timezone, _ = active_timezone(context)
    params = {
        "latitude": context.latitud_clima,
        "longitude": context.longitud_clima,
        "daily": ",".join(DAILY_FIELDS),
        "temperature_unit": "celsius",
        "timezone": timezone,
        "forecast_days": 8,
    }
    timeout = httpx.Timeout(8.0, connect=3.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(OPEN_METEO_URL, params=params)
        response.raise_for_status()
    return _parse_forecast(response.json(), timezone)
