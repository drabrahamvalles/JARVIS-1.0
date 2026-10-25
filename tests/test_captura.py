import base64
import json
import logging
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import httpx2
import pytest
from openai import AsyncOpenAI

from app.context import ToolContext
from app.schemas import CapturaRequest
from app.tools.captura import (
    Captura,
    CapturaExtraction,
    ImagenInvalidaError,
    prepare_image_data_url,
)
from tests.conftest import AUTH

PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
CONTEXT = ToolContext(
    "America/Mazatlan",
    "coordenadas",
    "Monterrey",
    lat=23.2494,
    lon=-106.4111,
)


def extraction(**updates) -> CapturaExtraction:
    values = {
        "tipo": "evento",
        "titulo": "Cena con Ana",
        "fecha": "2026-11-05",
        "hora": "09:00",
        "fecha_fin": None,
        "hora_fin": None,
        "duracion_minutos": None,
        "lugar": "Centro",
        "notas": None,
        "faltante": "ninguno",
        "es_vuelo": False,
        "viajes": [],
    }
    values.update(updates)
    return CapturaExtraction.model_validate(values)


def leg(**updates) -> dict:
    values = {
        "numero_vuelo": "VB 1151",
        "fecha_salida": "2026-11-05",
        "hora_salida": "12:13",
        "aeropuerto_origen": "MZT",
        "ciudad_origen": "Mazatlán",
        "zona_iana_origen": None,
        "fecha_llegada": "2026-11-05",
        "hora_llegada": "18:35",
        "aeropuerto_destino": "MTY",
        "ciudad_destino": "Monterrey",
        "zona_iana_destino": None,
    }
    values.update(updates)
    return values


def trip(*legs, role="otro") -> dict:
    return {"rol": role, "tramos": list(legs)}


def flight_extraction(*trips, **updates) -> CapturaExtraction:
    values = {
        "tipo": "evento",
        "titulo": None,
        "fecha": None,
        "hora": None,
        "fecha_fin": None,
        "hora_fin": None,
        "duracion_minutos": None,
        "es_vuelo": True,
        "viajes": list(trips),
    }
    values.update(updates)
    return extraction(**values)


def openai_response(result: CapturaExtraction) -> SimpleNamespace:
    usage = SimpleNamespace(
        input_tokens=400,
        input_tokens_details=SimpleNamespace(cached_tokens=20, cache_write_tokens=0),
        output_tokens=100,
        output_tokens_details=SimpleNamespace(reasoning_tokens=10),
    )
    return SimpleNamespace(
        status="completed",
        output_parsed=result,
        model="gpt-6-luna",
        usage=usage,
    )


def make_service(config, result: CapturaExtraction) -> tuple[Captura, AsyncMock]:
    parse = AsyncMock(return_value=openai_response(result))
    client = SimpleNamespace(responses=SimpleNamespace(parse=parse))
    return Captura(client, config, "Personalidad de prueba"), parse


def request(text="Agenda esto", image=PNG_BASE64) -> CapturaRequest:
    return CapturaRequest(
        texto=text,
        imagen_base64=image,
        lat=23.2494,
        lon=-106.4111,
        ciudad="Mazatlán",
        dispositivo="iPhone",
    )


def freeze_local_time(monkeypatch) -> None:
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            value = cls(2026, 10, 24, 8, 0, tzinfo=ZoneInfo("America/Mazatlan"))
            return value.astimezone(tz) if tz is not None else value

    monkeypatch.setattr("app.tools.captura.datetime", FixedDateTime)


async def test_event_with_date_defaults_to_one_hour(config):
    service, parse = make_service(config, extraction())

    result = await service.analyze(request(), CONTEXT)

    assert result.model_dump() == {
        "tipo": "evento",
        "titulo": "Cena con Ana",
        "inicio": "2026-11-05 09:00",
        "fin": "2026-11-05 10:00",
        "lugar": "Centro",
        "notas": None,
        "respuesta": "Listo, Dr. Valles.",
    }
    call = parse.await_args.kwargs
    assert call["model"] == "gpt-6-luna"
    assert call["text_format"] is CapturaExtraction
    assert call["store"] is False
    assert call["input"][0]["content"][1]["type"] == "input_image"
    assert call["input"][0]["content"][1]["detail"] == "high"
    assert "jamás instrucciones" in call["instructions"]
    assert "nunca deben combinarse" in call["instructions"]


async def test_reminder_with_date_uses_configured_default_time(config):
    result_data = extraction(
        tipo="recordatorio",
        titulo="Pagar la luz",
        fecha="2026-10-27",
        hora=None,
        lugar=None,
    )
    service, _ = make_service(config, result_data)

    result = await service.analyze(request("Recordatorio para el martes"), CONTEXT)

    assert result.tipo == "recordatorio"
    assert result.inicio == "2026-10-27 09:00"
    assert result.fin is None
    assert result.respuesta == "Listo, Dr. Valles."


async def test_clear_reminder_without_date_is_created_without_deadline(config):
    result_data = extraction(
        tipo="recordatorio",
        titulo="Comprar café",
        fecha=None,
        hora=None,
        lugar=None,
    )
    service, _ = make_service(config, result_data)

    result = await service.analyze(request("Recordatorio: comprar café"), CONTEXT)

    assert result.tipo == "recordatorio"
    assert result.inicio is None and result.fin is None
    assert result.respuesta == "Listo, Dr. Valles."


async def test_event_without_date_returns_none_and_explains_missing_field(config):
    result_data = extraction(
        tipo="ninguno",
        titulo=None,
        fecha=None,
        hora=None,
        lugar=None,
        faltante="fecha_evento",
    )
    service, _ = make_service(config, result_data)

    result = await service.analyze(request("Ponlo en el calendario"), CONTEXT)

    assert result.tipo == "ninguno"
    assert result.titulo is None and result.inicio is None and result.fin is None
    assert result.respuesta == "No encontré la fecha, Dr. Valles."


@pytest.mark.parametrize(
    ("reason", "message"),
    [
        ("titulo", "No encontré un título, Dr. Valles."),
        ("hora_evento", "No encontré la hora, Dr. Valles."),
        ("contenido_claro", "No encontré nada que agregar, Dr. Valles."),
    ],
)
async def test_none_responses_are_short(config, reason, message):
    result_data = extraction(
        tipo="ninguno",
        titulo=None,
        fecha=None,
        hora=None,
        lugar=None,
        faltante=reason,
    )
    service, _ = make_service(config, result_data)

    result = await service.analyze(request(), CONTEXT)

    assert result.respuesta == message


async def test_flight_title_excludes_passenger_and_converts_arrival_from_config(config):
    result_data = flight_extraction(
        trip(
            leg(
                numero_vuelo="vb1151",
                zona_iana_origen="Etc/UTC",
                zona_iana_destino="Etc/UTC",
            )
        ),
        titulo="Vuelo de Abraham Valles",
        lugar="Terminal 1",
    )
    service, _ = make_service(config, result_data)

    result = await service.analyze(request(), CONTEXT)

    assert result.titulo == "Vuelo MZT → MTY (VB 1151)"
    assert "Abraham" not in result.titulo
    assert result.inicio == "2026-11-05 12:13"
    assert result.fin == "2026-11-05 17:35"
    assert result.respuesta == "Listo, Dr. Valles."


async def test_flight_departure_and_arrival_are_converted_to_user_timezone(config):
    result_data = flight_extraction(
        trip(
            leg(
                numero_vuelo="AM 901",
                aeropuerto_origen="MTY",
                ciudad_origen="Monterrey",
                hora_llegada="14:30",
                aeropuerto_destino="MEX",
                ciudad_destino="Ciudad de México",
            )
        )
    )
    service, _ = make_service(config, result_data)

    result = await service.analyze(request(), CONTEXT)

    assert result.inicio == "2026-11-05 11:13"
    assert result.fin == "2026-11-05 13:30"


async def test_flight_in_same_timezone_keeps_departure_and_arrival(config):
    result_data = flight_extraction(
        trip(
            leg(
                numero_vuelo="Y4 701",
                hora_salida="10:00",
                hora_llegada="12:00",
                aeropuerto_destino="SJD",
                ciudad_destino="Los Cabos",
            )
        )
    )
    service, _ = make_service(config, result_data)

    result = await service.analyze(request(), CONTEXT)

    assert result.inicio == "2026-11-05 10:00"
    assert result.fin == "2026-11-05 12:00"


async def test_flight_uses_validated_model_timezones_when_airports_are_not_configured(config):
    result_data = flight_extraction(
        trip(
            leg(
                numero_vuelo="AF 1680",
                hora_salida="10:00",
                aeropuerto_origen="CDG",
                ciudad_origen="París",
                zona_iana_origen="Europe/Paris",
                hora_llegada="12:00",
                aeropuerto_destino="LHR",
                ciudad_destino="Londres",
                zona_iana_destino="Europe/London",
            )
        )
    )
    service, _ = make_service(config, result_data)

    result = await service.analyze(request(), CONTEXT)

    assert result.inicio == "2026-11-05 02:00"
    assert result.fin == "2026-11-05 05:00"
    assert result.notas is None


async def test_flight_timezone_table_accepts_city_aliases_without_airport_codes(config):
    result_data = flight_extraction(
        trip(
            leg(
                aeropuerto_origen=None,
                ciudad_origen="Mazatlan",
                aeropuerto_destino=None,
                ciudad_destino="Monterrey",
            )
        )
    )
    service, _ = make_service(config, result_data)

    result = await service.analyze(request(), CONTEXT)

    assert result.inicio == "2026-11-05 12:13"
    assert result.fin == "2026-11-05 17:35"
    assert result.notas is None


async def test_flight_keeps_local_times_and_warns_when_timezones_cannot_be_resolved(config):
    result_data = flight_extraction(
        trip(
            leg(
                numero_vuelo="VB 123",
                hora_salida="10:00",
                aeropuerto_origen="XXX",
                ciudad_origen="Origen desconocido",
                zona_iana_origen="Zona/Inexistente",
                hora_llegada="12:00",
                aeropuerto_destino="YYY",
                ciudad_destino="Destino desconocido",
                zona_iana_destino=None,
            )
        ),
        notas="Equipaje de mano.",
    )
    service, _ = make_service(config, result_data)

    result = await service.analyze(request(), CONTEXT)

    assert result.tipo == "evento"
    assert result.inicio == "2026-11-05 10:00"
    assert result.fin == "2026-11-05 12:00"
    assert result.notas == (
        "Equipaje de mano. Hora de salida en hora local del origen. "
        "Hora de llegada en hora local del destino."
    )


def round_trip_capture() -> CapturaExtraction:
    outbound = trip(
        leg(
            numero_vuelo="VB 4024",
            fecha_salida="2026-10-22",
            hora_salida="12:00",
            aeropuerto_origen="MTY",
            ciudad_origen="Monterrey",
            fecha_llegada="2026-10-22",
            hora_llegada="13:00",
            aeropuerto_destino="MZT",
            ciudad_destino="Mazatlán",
        ),
        role="ida",
    )
    inbound = trip(
        leg(
            numero_vuelo="VB 1151",
            fecha_salida="2026-10-25",
            hora_salida="12:13",
            aeropuerto_origen="MZT",
            ciudad_origen="Mazatlán",
            fecha_llegada="2026-10-25",
            hora_llegada="14:30",
            aeropuerto_destino="MEX",
            ciudad_destino="Ciudad de México",
        ),
        leg(
            numero_vuelo="VB 1126",
            fecha_salida="2026-10-25",
            hora_salida="16:20",
            aeropuerto_origen="AICM",
            ciudad_origen="Ciudad de México",
            fecha_llegada="2026-10-25",
            hora_llegada="18:35",
            aeropuerto_destino="MTY",
            ciudad_destino="Monterrey",
        ),
        role="regreso",
    )
    return flight_extraction(outbound, inbound)


@pytest.mark.parametrize(
    "text",
    [
        "Agenda estos vuelos",
        "Agenda el de regreso",
        "Agenda el del domingo",
        "Agenda el del 25 de octubre",
        "Agenda el 2026-10-25",
    ],
)
async def test_two_trips_select_the_requested_or_next_future_trip(config, monkeypatch, text):
    freeze_local_time(monkeypatch)
    service, _ = make_service(config, round_trip_capture())

    result = await service.analyze(request(text), CONTEXT)

    assert result.model_dump() == {
        "tipo": "evento",
        "titulo": "Vuelo MZT → MTY (VB 1151 / VB 1126)",
        "inicio": "2026-10-25 12:13",
        "fin": "2026-10-25 17:35",
        "lugar": "Centro",
        "notas": None,
        "respuesta": "Listo, Dr. Valles.",
    }


async def test_explicit_outbound_selects_past_trip(config, monkeypatch):
    freeze_local_time(monkeypatch)
    service, _ = make_service(config, round_trip_capture())

    result = await service.analyze(request("Agenda el de ida"), CONTEXT)

    assert result.tipo == "evento"
    assert result.titulo == "Vuelo MTY → MZT (VB 4024)"
    assert result.inicio == "2026-10-22 11:00"
    assert result.fin == "2026-10-22 13:00"


async def test_uncertain_connection_keeps_event_and_adds_review_note(config):
    connected_trip = trip(
        leg(
            hora_salida="10:00",
            hora_llegada="12:00",
            aeropuerto_destino="XXX",
            ciudad_destino="Escala norte",
        ),
        leg(
            numero_vuelo="VB 1126",
            hora_salida="13:00",
            aeropuerto_origen="YYY",
            ciudad_origen="Escala sur",
            hora_llegada="15:00",
        ),
    )
    service, _ = make_service(config, flight_extraction(connected_trip))

    result = await service.analyze(request(), CONTEXT)

    assert result.tipo == "evento"
    assert result.notas == "Revisar escalas."


@pytest.mark.parametrize(
    "invalid_trip",
    [
        trip(leg(aeropuerto_destino="MZT", ciudad_destino="Mazatlán")),
        trip(
            leg(
                hora_salida="10:00",
                fecha_llegada="2026-11-06",
                hora_llegada="12:00",
            )
        ),
        trip(leg(hora_salida="12:00", hora_llegada="12:30")),
    ],
    ids=["same_origin_destination", "over_24_hours", "end_before_start"],
)
async def test_invalid_flight_is_not_created(config, invalid_trip):
    service, _ = make_service(config, flight_extraction(invalid_trip))

    result = await service.analyze(request(), CONTEXT)

    assert result.tipo == "ninguno"
    assert result.titulo is None and result.inicio is None and result.fin is None
    assert result.respuesta == "No pude leer bien el vuelo, Dr. Valles."


async def test_tomorrow_is_resolved_from_trusted_local_date(config, monkeypatch):
    freeze_local_time(monkeypatch)
    result_data = extraction(fecha="2026-10-25", hora="18:30")
    service, parse = make_service(config, result_data)

    result = await service.analyze(request("Agenda esto mañana a las 6:30"), CONTEXT)

    assert result.inicio == "2026-10-25 18:30"
    input_text = parse.await_args.kwargs["input"][0]["content"][0]["text"]
    trusted_context = json.loads(input_text)
    assert trusted_context["fecha_hora_local"] == "2026-10-24T08:00:00-07:00"
    assert trusted_context["zona_horaria"] == "America/Mazatlan"


def test_image_validation_accepts_data_url_and_rejects_invalid_base64(config):
    result = prepare_image_data_url(
        f"data:image/png;base64,{PNG_BASE64}", config.tamano_maximo_imagen_bytes
    )
    assert result.startswith("data:image/png;base64,")
    with pytest.raises(ImagenInvalidaError):
        prepare_image_data_url("not-base64", config.tamano_maximo_imagen_bytes)


def test_image_over_five_mb_returns_413_without_calling_openai(client, config):
    parse = AsyncMock()
    fake_openai = SimpleNamespace(responses=SimpleNamespace(parse=parse))
    client.app.state.captura = Captura(fake_openai, config, "Personalidad")
    oversized = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"x" * 5_000_000).decode()
    payload = {
        "texto": "Agenda esto",
        "imagen_base64": oversized,
        "lat": 23.2494,
        "lon": -106.4111,
    }

    response = client.post("/captura", json=payload, headers=AUTH)

    assert response.status_code == 413
    assert response.json() == {"detail": "La imagen supera el límite de 5 MB"}
    parse.assert_not_awaited()


def test_invalid_image_returns_clear_422_without_calling_openai(client, config):
    parse = AsyncMock()
    fake_openai = SimpleNamespace(responses=SimpleNamespace(parse=parse))
    client.app.state.captura = Captura(fake_openai, config, "Personalidad")
    payload = {
        "texto": "Agenda esto",
        "imagen_base64": "not-base64",
        "lat": 23.2494,
        "lon": -106.4111,
    }

    response = client.post("/captura", json=payload, headers=AUTH)

    assert response.status_code == 422
    assert "Base64 válido" in response.json()["detail"]
    parse.assert_not_awaited()


async def test_usage_log_excludes_image_text_location_and_result(config, caplog):
    result_data = extraction(titulo="private-result")
    service, _ = make_service(config, result_data)
    caplog.set_level(logging.INFO, logger="jarvis.usage")

    await service.analyze(request("private-text"), CONTEXT)

    usage_log = "\n".join(
        record.getMessage() for record in caplog.records if record.name == "jarvis.usage"
    )
    assert "captura hora=" in usage_log and 'modelo="gpt-6-luna"' in usage_log
    assert "tokens_entrada=400" in usage_log and "latencia_ms=" in usage_log
    for private_value in ("private-text", "private-result", PNG_BASE64, "23.2494", "Mazatlán"):
        assert private_value not in usage_log


async def test_real_sdk_sends_image_and_strict_json_schema(config):
    captured = {}
    model_output = extraction().model_dump()

    async def transport(http_request):
        body = json.loads(http_request.content)
        captured.update(body)
        return httpx2.Response(
            200,
            request=http_request,
            json={
                "id": "resp_capture",
                "object": "response",
                "created_at": 1792832400,
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "id": "msg_capture",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(model_output),
                                "annotations": [],
                            }
                        ],
                    }
                ],
                "model": "gpt-6-luna",
            },
        )

    openai_client = AsyncOpenAI(
        api_key="test-key",
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(transport)),
    )
    try:
        service = Captura(openai_client, config, "Personalidad")
        result = await service.analyze(request(), CONTEXT)
    finally:
        await openai_client.close()

    assert result.tipo == "evento"
    assert captured["text"]["format"]["type"] == "json_schema"
    assert captured["text"]["format"]["strict"] is True
    schema = captured["text"]["format"]["schema"]
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    assert {"es_vuelo", "viajes"} <= set(schema["properties"])
    assert {"FlightLegExtraction", "FlightTripExtraction"} <= set(schema["$defs"])
    for definition in schema["$defs"].values():
        assert definition["additionalProperties"] is False
        assert set(definition["required"]) == set(definition["properties"])
    image_input = captured["input"][0]["content"][1]
    assert image_input["type"] == "input_image"
    assert image_input["image_url"].startswith("data:image/png;base64,")
