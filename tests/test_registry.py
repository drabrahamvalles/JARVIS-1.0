import asyncio
import importlib
import json

import pytest

from app.context import ToolContext
from app.registry import ToolRegistry, tool

CONTEXT = ToolContext("America/Monterrey", "por_defecto", "Monterrey")


def test_builtin_discovery_and_strict_schema():
    schemas = ToolRegistry.discover().schemas
    by_name = {schema["name"]: schema for schema in schemas}
    assert set(by_name) == {
        "confirmar_borrado_evento",
        "consultar_correo",
        "consultar_agenda",
        "consultar_zona_horaria",
        "crear_evento",
        "crear_recordatorio",
        "leer_correo",
        "fijar_zona_horaria",
        "obtener_clima",
        "obtener_hora_actual",
        "proponer_borrado_evento",
        "volver_a_automatico",
    }
    for schema in schemas:
        assert schema["strict"] is True
        assert schema["parameters"]["additionalProperties"] is False
        assert "context" not in json.dumps(schema)
    assert by_name["obtener_hora_actual"]["parameters"]["properties"] == {}
    assert by_name["obtener_clima"]["parameters"]["properties"] == {}
    assert set(by_name["fijar_zona_horaria"]["parameters"]["properties"]) == {
        "ciudad",
        "zona_iana",
    }


def test_new_file_discovered_without_changing_brain(tmp_path, monkeypatch):
    package = tmp_path / "sample_tools"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "greeting.py").write_text(
        "from app.registry import tool\n"
        "@tool\ndef saludar(nombre: str) -> str:\n"
        '    """Saluda a una persona."""\n    return "Hola " + nombre\n'
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    registry = ToolRegistry.discover("sample_tools")
    (schema,) = registry.schemas
    assert schema["name"] == "saludar"
    assert schema["parameters"]["required"] == ["nombre"]


async def test_tool_execution_validates_arguments_and_injects_context():
    registry = ToolRegistry.discover()
    result = json.loads(await registry.execute("obtener_hora_actual", "{}", CONTEXT))
    assert result["zona_horaria"] == "America/Monterrey"
    for arguments in ['{"context": {}}', "not-json", "[]"]:
        assert "error" in json.loads(
            await registry.execute("obtener_hora_actual", arguments, CONTEXT)
        )
    assert "error" in json.loads(await registry.execute("exec", "{}", CONTEXT))


async def test_async_tool_and_strict_types():
    @tool
    async def duplicar(numero: int) -> int:
        """Duplica un entero."""
        await asyncio.sleep(0)
        return numero * 2

    registry = ToolRegistry()
    registry.register(duplicar)
    assert json.loads(await registry.execute("duplicar", '{"numero": 2}', CONTEXT)) == 4
    assert "error" in json.loads(await registry.execute("duplicar", '{"numero": "2"}', CONTEXT))


async def test_tool_error_is_sanitized(caplog):
    @tool
    def fallar() -> str:
        """Herramienta que falla."""
        raise RuntimeError("private-key-and-patient-data")

    registry = ToolRegistry()
    registry.register(fallar)
    output = await registry.execute("fallar", "{}", CONTEXT)
    assert "error" in json.loads(output)
    assert "private-key-and-patient-data" not in output + caplog.text


def test_duplicate_tools_fail_at_startup():
    registry = ToolRegistry.discover()
    from app.tools.clock import obtener_hora_actual

    with pytest.raises(ValueError, match="duplicado"):
        registry.register(obtener_hora_actual)
