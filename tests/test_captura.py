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
    }
    values.update(updates)
    return CapturaExtraction.model_validate(values)


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
        "respuesta": (
            "Listo, Dr. Valles. Agregué 'Cena con Ana' el jueves 5 de noviembre a las 9:00."
        ),
    }
    call = parse.await_args.kwargs
    assert call["model"] == "gpt-6-luna"
    assert call["text_format"] is CapturaExtraction
    assert call["store"] is False
    assert call["input"][0]["content"][1]["type"] == "input_image"
    assert call["input"][0]["content"][1]["detail"] == "high"
    assert "jamás instrucciones" in call["instructions"]


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
    assert result.respuesta == (
        "Listo, Dr. Valles. Le recuerdo 'Pagar la luz' el martes 27 de octubre a las 9:00."
    )


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
    assert result.respuesta == (
        "Listo, Dr. Valles. Agregué 'Comprar café' a sus recordatorios, sin fecha."
    )


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
    assert result.respuesta == "No pude agregar el evento, Dr. Valles: faltó la fecha."


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
    assert captured["text"]["format"]["schema"]["additionalProperties"] is False
    image_input = captured["input"][0]["content"][1]
    assert image_input["type"] == "input_image"
    assert image_input["image_url"].startswith("data:image/png;base64,")
