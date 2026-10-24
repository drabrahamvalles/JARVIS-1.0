from datetime import date, timedelta

import httpx
import pytest

from app.context import ToolContext
from app.tools.clima import ClimaError, obtener_clima


def open_meteo_payload(start: date, timezone: str = "America/Mazatlan") -> dict:
    days = [(start + timedelta(days=index)).isoformat() for index in range(8)]
    return {
        "timezone": timezone,
        "daily_units": {
            "temperature_2m_min": "°C",
            "temperature_2m_max": "°C",
            "precipitation_probability_max": "%",
        },
        "daily": {
            "time": days,
            "temperature_2m_min": [18, 19, 20, 21, 22, 23, 24, 25],
            "temperature_2m_max": [28, 29, 30, 31, 32, 33, 34, 35],
            "precipitation_probability_max": [10, 20, 30, 40, 50, 60, 70, 80],
        },
    }


async def test_weather_requests_eight_days_in_resolved_timezone(monkeypatch):
    captured = {}
    payload = open_meteo_payload(date(2026, 10, 24))

    async def transport(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, json=payload, request=request)

    real_client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    monkeypatch.setattr("app.tools.clima.httpx.AsyncClient", lambda **kwargs: real_client)
    context = ToolContext(
        "America/Mazatlan",
        "coordenadas",
        "Monterrey",
        lat=23.2494,
        lon=-106.4111,
        latitud_clima=23.2494,
        longitud_clima=-106.4111,
    )

    result = await obtener_clima(context=context)

    params = captured["request"].url.params
    assert params["timezone"] == "America/Mazatlan"
    assert params["forecast_days"] == "8"
    assert params["temperature_unit"] == "celsius"
    assert set(params["daily"].split(",")) == {
        "temperature_2m_min",
        "temperature_2m_max",
        "precipitation_probability_max",
    }
    assert len(result["dias"]) == 8
    assert result["dias"][0] == {
        "fecha": "2026-10-24",
        "minima_c": 18.0,
        "maxima_c": 28.0,
        "lluvia_pct": 10.0,
    }
    assert "latitude" not in result and "longitude" not in result


async def test_weather_rejects_incomplete_open_meteo_response(monkeypatch):
    async def transport(request: httpx.Request) -> httpx.Response:
        payload = open_meteo_payload(date(2026, 10, 24))
        payload["daily"]["temperature_2m_min"] = [18]
        return httpx.Response(200, json=payload, request=request)

    real_client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    monkeypatch.setattr("app.tools.clima.httpx.AsyncClient", lambda **kwargs: real_client)
    context = ToolContext(
        "America/Mazatlan",
        "coordenadas",
        "Monterrey",
        latitud_clima=23.2494,
        longitud_clima=-106.4111,
    )

    with pytest.raises(ClimaError):
        await obtener_clima(context=context)
