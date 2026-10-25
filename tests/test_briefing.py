import json
import logging
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest

from app.briefing import Briefing, _clothing_recommendation, _weekly_overview
from app.context import TimezoneResolver, ToolContext
from app.schemas import BriefingRequest


def forecast(
    start: date,
    *,
    minimums: list[float] | None = None,
    maximums: list[float] | None = None,
    rain: list[float] | None = None,
    timezone: str = "America/Mazatlan",
) -> dict[str, object]:
    minimums = minimums or [20] * 8
    maximums = maximums or [30] * 8
    rain = rain or [10] * 8
    return {
        "zona_horaria": timezone,
        "dias": [
            {
                "fecha": (start + timedelta(days=index)).isoformat(),
                "minima_c": minimums[index],
                "maxima_c": maximums[index],
                "lluvia_pct": rain[index],
            }
            for index in range(8)
        ],
    }


def openai_response(text: str) -> SimpleNamespace:
    usage = SimpleNamespace(
        input_tokens=200,
        input_tokens_details=SimpleNamespace(cached_tokens=20, cache_write_tokens=0),
        output_tokens=80,
        output_tokens_details=SimpleNamespace(reasoning_tokens=10),
    )
    return SimpleNamespace(
        status="completed",
        output_text=text,
        model="gpt-6-luna",
        usage=usage,
    )


def service(config, text: str) -> tuple[Briefing, AsyncMock]:
    create = AsyncMock(return_value=openai_response(text))
    client = SimpleNamespace(responses=SimpleNamespace(create=create))
    return Briefing(client, config, "Personalidad de prueba"), create


def trusted_data(create: AsyncMock) -> dict:
    content = create.await_args.kwargs["input"][0]["content"]
    return json.loads(content)


def freeze_local_hour(monkeypatch, hour: int) -> None:
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            value = cls(2026, 11, 2, hour, tzinfo=ZoneInfo("America/Mazatlan"))
            return value.astimezone(tz) if tz is not None else value

    monkeypatch.setattr("app.briefing.datetime", FixedDateTime)


@pytest.mark.parametrize(
    ("minimum", "maximum", "rain", "expected_attribute"),
    [
        (7, 20, 0, "texto_chamarra"),
        (8, 20, 0, "texto_sueter"),
        (16, 20, 50, "texto_paraguas"),
        (16, 33, 0, "texto_ropa_ligera"),
    ],
)
def test_clothing_rule_boundaries(config, minimum, maximum, rain, expected_attribute):
    today = {"minima_c": minimum, "maxima_c": maximum, "lluvia_pct": rain}
    assert _clothing_recommendation(today, config) == [
        getattr(config.reglas_ropa, expected_attribute)
    ]


def test_weekly_overview_keeps_only_relevant_thresholds(config):
    weather = forecast(
        date(2026, 10, 26),
        minimums=[16, 16, 16, 7, 12, 12, 12, 12],
        maximums=[34, 34, 29, 29, 29, 29, 29, 29],
        rain=[49, 50, 10, 10, 10, 10, 10, 10],
    )
    overview = _weekly_overview(weather["dias"], config)
    assert overview["dias_con_lluvia"] == [{"dia": "martes", "lluvia_pct": 50}]
    assert overview["frio_notable"] == [{"dia": "jueves", "minima_c": 7}]
    assert overview["calor_notable"] == [
        {"dia": "lunes", "maxima_c": 34},
        {"dia": "martes", "maxima_c": 34},
    ]
    assert overview["cambios_temperatura"] == [
        {"a_partir_de": "miércoles", "cambio_maxima_c": -5},
        {"a_partir_de": "jueves", "cambio_minima_c": -9},
        {"a_partir_de": "viernes", "cambio_minima_c": 5},
    ]


async def test_monday_with_rain_includes_city_week_and_umbrella(config, monkeypatch, caplog):
    freeze_local_hour(monkeypatch, 7)
    weather = forecast(
        date(2026, 11, 2),
        minimums=[18.9, 18, 17, 15, 14, 20, 21, 22],
        maximums=[26.7, 30, 31, 22, 24, 30, 31, 32],
        rain=[70, 20, 65, 10, 10, 55, 15, 5],
    )
    monkeypatch.setattr("app.briefing.obtener_clima", AsyncMock(return_value=weather))
    result_text = "Buenos días, Dr. Valles. Hoy es lunes 2 de noviembre. En Mazatlán habrá lluvia."
    briefing, create = service(config, result_text)
    request = BriefingRequest(
        fecha_iso="2026-11-02T07:00:00-07:00",
        lat=23.2494,
        lon=-106.4111,
        ciudad="Mazatlán",
        eventos=["09:00 Reunión"],
        recordatorios=["Comprar café"],
    )
    context = ToolContext(
        "America/Mazatlan",
        "coordenadas",
        "Monterrey",
        lat=23.2494,
        lon=-106.4111,
        latitud_clima=23.2494,
        longitud_clima=-106.4111,
    )
    caplog.set_level(logging.INFO, logger="jarvis.usage")

    assert await briefing.create(request, context) == result_text

    data = trusted_data(create)
    assert data["saludo_exacto"] == "Buenos días, Dr. Valles"
    assert data["fecha_hablada_exacta"] == "hoy es lunes 2 de noviembre"
    assert data["ciudad"] == "Mazatlán"
    assert data["clima_hoy"]["minima_c"] == 19
    assert data["clima_hoy"]["maxima_c"] == 27
    assert data["es_lunes"] is True
    assert [item["dia"] for item in data["panorama_semana"]["dias_con_lluvia"]] == [
        "lunes",
        "miércoles",
        "sábado",
    ]
    assert [item["a_partir_de"] for item in data["panorama_semana"]["cambios_temperatura"]] == [
        "jueves",
        "sábado",
    ]
    assert data["panorama_semana"]["frio_notable"] == []
    assert data["panorama_semana"]["calor_notable"] == []
    assert config.reglas_ropa.texto_paraguas in data["recomendaciones_ropa"]
    call = create.await_args.kwargs
    assert call["model"] == "gpt-6-luna"
    assert call["store"] is False
    assert call["reasoning"] == {"mode": "standard", "effort": "low"}
    assert "una o dos oraciones naturales" in call["instructions"]
    assert "no enumeres los siete días" in call["instructions"]
    assert "Semana fresca" in call["instructions"]
    usage_log = "\n".join(
        record.getMessage() for record in caplog.records if record.name == "jarvis.usage"
    )
    assert 'modelo="gpt-6-luna"' in usage_log
    assert "tokens_entrada=200" in usage_log and "latencia_ms=" in usage_log
    assert "Mazatlán" not in usage_log and "Reunión" not in usage_log
    assert "23.2494" not in usage_log and "-106.4111" not in usage_log


async def test_tuesday_without_pending_items(config, monkeypatch):
    freeze_local_hour(monkeypatch, 14)
    monkeypatch.setattr(
        "app.briefing.obtener_clima",
        AsyncMock(return_value=forecast(date(2026, 11, 3))),
    )
    result_text = "Buenas tardes, Dr. Valles. Hoy no tiene pendientes."
    briefing, create = service(config, result_text)
    request = BriefingRequest(
        fecha_iso="2026-11-03",
        lat=23.2494,
        lon=-106.4111,
        eventos=[],
        recordatorios=[],
    )
    context = ToolContext(
        "America/Mazatlan",
        "coordenadas",
        "Monterrey",
        latitud_clima=23.2494,
        longitud_clima=-106.4111,
    )

    assert await briefing.create(request, context) == result_text

    data = trusted_data(create)
    assert data["saludo_exacto"] == "Buenas tardes, Dr. Valles"
    assert data["fecha_hablada_exacta"] == "hoy es martes 3 de noviembre"
    assert data["ciudad"] is None
    assert data["panorama_semana"] is None
    assert data["eventos"] == [] and data["recordatorios"] == []
    assert "omite por completo la agenda" in create.await_args.kwargs["instructions"]


async def test_saturday_night_with_weather_and_empty_agenda_is_repaired(config, monkeypatch):
    freeze_local_hour(monkeypatch, 21)
    weather = forecast(
        date(2026, 10, 24),
        minimums=[24] * 8,
        maximums=[34] * 8,
        rain=[60] * 8,
    )
    monkeypatch.setattr("app.briefing.obtener_clima", AsyncMock(return_value=weather))
    model_text = (
        "Buenas noches, Dr. Valles. Hoy es sábado 24 de octubre, en Mazatlán. "
        "La mínima será de 24 grados y la máxima de 34; se recomienda llevar paraguas, "
        "usar ropa ligera y mantenerse hidratado. No hay clima disponible."
    )
    briefing, _ = service(config, model_text)
    request = BriefingRequest(
        fecha_iso="2026-10-24T21:19:00-07:00",
        lat=23.2494,
        lon=-106.4111,
        ciudad="Mazatlán",
        eventos=[],
        recordatorios=[],
    )
    context = ToolContext(
        "America/Mazatlan",
        "coordenadas",
        "Monterrey",
        latitud_clima=23.2494,
        longitud_clima=-106.4111,
    )

    result = await briefing.create(request, context)

    assert result == (
        "Buenas noches, Dr. Valles. Hoy es sábado 24 de octubre, en Mazatlán. "
        "La mínima será de 24 grados y la máxima de 34; se recomienda llevar paraguas, "
        "usar ropa ligera y mantenerse hidratado. Hoy no tiene pendientes."
    )
    assert "No hay clima disponible" not in result


async def test_two_validation_errors_use_deterministic_fallback(config, monkeypatch, caplog):
    freeze_local_hour(monkeypatch, 21)
    weather = forecast(
        date(2026, 10, 24),
        minimums=[24] * 8,
        maximums=[34] * 8,
        rain=[60] * 8,
    )
    monkeypatch.setattr("app.briefing.obtener_clima", AsyncMock(return_value=weather))
    model_text = (
        "Buenas noches, Dr. Valles. Hoy es sábado 24 de octubre, en Mazatlán. "
        "No hay clima disponible. El pronóstico no está disponible."
    )
    briefing, _ = service(config, model_text)
    request = BriefingRequest(
        fecha_iso="2026-10-24T21:19:00-07:00",
        lat=23.2494,
        lon=-106.4111,
        ciudad="Mazatlán",
        eventos=[],
        recordatorios=[],
    )
    context = ToolContext(
        "America/Mazatlan",
        "coordenadas",
        "Monterrey",
        latitud_clima=23.2494,
        longitud_clima=-106.4111,
    )
    caplog.set_level(logging.WARNING, logger="app.briefing")

    result = await briefing.create(request, context)

    assert result == (
        "Buenas noches, Dr. Valles. Hoy es sábado 24 de octubre, en Mazatlán. "
        "La mínima será de 24 grados y la máxima de 34 grados. "
        "Para hoy se recomienda paraguas y ropa ligera e hidratación. "
        "Hoy no tiene pendientes."
    )
    assert "briefing_validation_fallback errors=2 reason=multiple" in caplog.text


async def test_cold_day_orders_three_events_and_recommends_jacket(config, monkeypatch):
    freeze_local_hour(monkeypatch, 21)
    weather = forecast(
        date(2026, 11, 4),
        minimums=[7, 9, 10, 11, 12, 13, 14, 15],
        maximums=[18] * 8,
    )
    monkeypatch.setattr("app.briefing.obtener_clima", AsyncMock(return_value=weather))
    briefing, create = service(config, "Buenas noches, Dr. Valles. Lleve chamarra.")
    request = BriefingRequest(
        fecha_iso="2026-11-04",
        lat=25.6866,
        lon=-100.3161,
        eventos=["17:30 Cena", "08:00 Desayuno", "12:15 Llamada"],
        recordatorios=[],
    )
    context = ToolContext(
        "America/Monterrey",
        "coordenadas",
        "Monterrey",
        latitud_clima=25.6866,
        longitud_clima=-100.3161,
    )

    await briefing.create(request, context)

    data = trusted_data(create)
    assert data["saludo_exacto"] == "Buenas noches, Dr. Valles"
    assert data["eventos"] == ["08:00 Desayuno", "12:15 Llamada", "17:30 Cena"]
    assert data["recomendaciones_ropa"] == [config.reglas_ropa.texto_chamarra]
    assert data["ciudad"] is None


async def test_open_meteo_failure_still_generates_briefing(config, monkeypatch, caplog):
    freeze_local_hour(monkeypatch, 7)
    weather = AsyncMock(side_effect=RuntimeError("private-location-and-event"))
    monkeypatch.setattr("app.briefing.obtener_clima", weather)
    result_text = "Buenos días, Dr. Valles. No hay clima disponible; hoy no tiene pendientes."
    briefing, create = service(config, result_text)
    request = BriefingRequest(
        fecha_iso="2026-11-05",
        eventos=[],
        recordatorios=[],
    )
    context = ToolContext(
        "America/Monterrey",
        "por_defecto",
        "Monterrey",
        latitud_clima=config.latitud_por_defecto,
        longitud_clima=config.longitud_por_defecto,
    )
    caplog.set_level(logging.WARNING, logger="app.briefing")

    assert await briefing.create(request, context) == (
        "Buenos días, Dr. Valles. No hay clima disponible. Hoy no tiene pendientes."
    )

    data = trusted_data(create)
    assert data["clima_hoy"] is None
    assert data["recomendaciones_ropa"] == []
    assert "omite por completo el clima" in create.await_args.kwargs["instructions"]
    assert "private-location-and-event" not in caplog.text
    assert "kind=RuntimeError" in caplog.text


async def test_empty_location_uses_monterrey_for_weather_and_spoken_city(config, monkeypatch):
    freeze_local_hour(monkeypatch, 7)
    captured = {}

    async def weather(*, context):
        captured["context"] = context
        return forecast(date(2026, 11, 6), timezone="America/Monterrey")

    monkeypatch.setattr("app.briefing.obtener_clima", weather)
    briefing, create = service(config, "Buenos días, Dr. Valles. En Monterrey estará templado.")
    request = BriefingRequest(
        fecha_iso="2026-11-06T07:00:00-06:00",
        lat="",
        lon="",
        eventos=[],
        recordatorios=[],
    )
    resolver = TimezoneResolver()
    try:
        context = resolver.resolve(request, config)
        await briefing.create(request, context)
    finally:
        resolver.close()

    data = trusted_data(create)
    assert data["ciudad"] == "Monterrey"
    assert captured["context"].latitud_clima == config.latitud_por_defecto
    assert captured["context"].longitud_clima == config.longitud_por_defecto
    assert captured["context"].zona_horaria == "America/Monterrey"
