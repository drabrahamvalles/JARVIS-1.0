from dataclasses import replace
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from app import timezone_state
from app.context import TimezoneResolver, ToolContext
from app.schemas import AskRequest
from app.timezone_state import read_timezone_state
from app.tools.clock import obtener_hora_actual
from app.tools.consultar_zona_horaria import consultar_zona_horaria
from app.tools.fijar_zona_horaria import fijar_zona_horaria
from app.tools.volver_a_automatico import volver_a_automatico


@pytest.fixture(scope="module")
def resolver():
    result = TimezoneResolver()
    yield result
    result.close()


@pytest.mark.parametrize(
    "city,lat,lon,zone",
    [
        ("Monterrey", 25.6866, -100.3161, "America/Monterrey"),
        ("Ciudad de México", 19.4326, -99.1332, "America/Mexico_City"),
        ("Madrid", 40.4168, -3.7038, "Europe/Madrid"),
        ("Nueva York", 40.7128, -74.0060, "America/New_York"),
        ("Miami", 25.7617, -80.1918, "America/New_York"),
        ("Houston", 29.7604, -95.3698, "America/Chicago"),
    ],
)
def test_automatic_timezone_by_coordinates(resolver, config, city, lat, lon, zone):
    context = resolver.resolve(AskRequest(texto=f"Hora en {city}", lat=lat, lon=lon), config)
    assert context.zona_horaria == zone
    assert context.origen_zona_horaria == "coordenadas"


def test_missing_location_uses_default(resolver, config):
    result = resolver.resolve(AskRequest(texto="Hola"), config)
    assert result.zona_horaria == "America/Monterrey"
    assert result.origen_zona_horaria == "por_defecto"


def test_unresolvable_location_uses_default(resolver, config):
    with patch.object(type(resolver.finder), "timezone_at", return_value=None):
        result = resolver.resolve(AskRequest(texto="Hola", lat=0, lon=0), config)
    assert result.zona_horaria == "America/Monterrey"
    assert result.origen_zona_horaria == "por_defecto"


def test_fixed_config_ignores_gps(resolver, config):
    fixed = config.model_copy(update={"modo_zona_horaria": "fijo"})
    result = resolver.resolve(AskRequest(texto="Hola", lat=35, lon=139), fixed)
    assert result.zona_horaria == "America/Monterrey"
    assert result.origen_zona_horaria == "fijo"


@pytest.mark.parametrize(
    "city,zone",
    [
        ("Monterrey", "America/Monterrey"),
        ("Miami", "America/New_York"),
        ("Boston", "America/New_York"),
        ("Houston", "America/Chicago"),
        ("Tokio", "Asia/Tokyo"),
    ],
)
def test_manual_tool_accepts_any_valid_iana_zone(city, zone):
    result = fijar_zona_horaria(city, zone)
    assert result == {"ok": True, "modo": "manual", "ciudad": city, "zona_horaria": zone}
    assert read_timezone_state().zona_horaria == zone


def test_invalid_iana_zone_requests_clarification_without_changing_state():
    result = fijar_zona_horaria("Springfield", "America/Por_Aclarar")
    assert result["ok"] is False
    assert result["requiere_aclaracion"] is True
    assert read_timezone_state().modo == "automatico"


def test_malformed_state_falls_back_to_automatic():
    timezone_state.STATE_PATH.parent.mkdir(parents=True)
    timezone_state.STATE_PATH.write_text("[]", encoding="utf-8")
    assert read_timezone_state().modo == "automatico"


def test_manual_mode_and_return_to_automatic_in_same_context(resolver, config):
    houston_request = AskRequest(texto="Hora", lat=29.7604, lon=-95.3698)
    fijar_zona_horaria("Boston", "America/New_York")
    context = resolver.resolve(houston_request, config)
    assert context.zona_horaria == "America/New_York"
    assert context.origen_zona_horaria == "manual"
    assert consultar_zona_horaria(context=context)["modo"] == "manual"
    assert obtener_hora_actual(context=context)["zona_horaria"] == "America/New_York"

    assert volver_a_automatico() == {"ok": True, "modo": "automatico"}
    # El mismo contexto conserva la alternativa automática calculada al iniciar la petición.
    assert obtener_hora_actual(context=context)["zona_horaria"] == "America/Chicago"
    automatic = resolver.resolve(houston_request, config)
    assert automatic.zona_horaria == "America/Chicago"
    assert automatic.origen_zona_horaria == "coordenadas"


def test_clock_uses_active_request_timezone():
    tokyo = ToolContext("Asia/Tokyo", "coordenadas", "Monterrey")
    mazatlan = replace(tokyo, zona_horaria="America/Mazatlan")
    assert (
        datetime.fromisoformat(obtener_hora_actual(context=tokyo)["fecha_hora"])
        .utcoffset()
        .total_seconds()
        == 9 * 3600
    )
    assert (
        datetime.fromisoformat(obtener_hora_actual(context=mazatlan)["fecha_hora"])
        .utcoffset()
        .total_seconds()
        == -7 * 3600
    )


def test_houston_is_one_hour_ahead_of_monterrey_in_summer():
    day = datetime(2026, 7, 15, 12)
    houston_offset = day.replace(tzinfo=ZoneInfo("America/Chicago")).utcoffset()
    monterrey_offset = day.replace(tzinfo=ZoneInfo("America/Monterrey")).utcoffset()
    assert houston_offset.total_seconds() - monterrey_offset.total_seconds() == 3600


def test_new_york_zone_applies_daylight_saving_rules():
    zone = ZoneInfo("America/New_York")
    assert datetime(2026, 1, 15, tzinfo=zone).utcoffset().total_seconds() == -5 * 3600
    assert datetime(2026, 7, 15, tzinfo=zone).utcoffset().total_seconds() == -4 * 3600
