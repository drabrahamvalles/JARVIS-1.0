import asyncio
import inspect
import json
import logging
import pkgutil
import re
from collections.abc import Callable
from dataclasses import dataclass
from importlib import import_module
from typing import Any, get_type_hints

from openai import pydantic_function_tool
from pydantic import BaseModel, ConfigDict, ValidationError, create_model
from starlette.concurrency import run_in_threadpool

from app.context import ToolContext

logger = logging.getLogger(__name__)


def tool(function: Callable) -> Callable:
    """Marca una función tipada de app/tools/ para descubrirla al arrancar."""
    function.__jarvis_tool__ = True
    return function


@dataclass(frozen=True)
class RegisteredTool:
    handler: Callable
    arguments: type[BaseModel]
    inject_context: bool
    schema: dict[str, Any]


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}

    @classmethod
    def discover(cls, package_name: str = "app.tools") -> "ToolRegistry":
        registry = cls()
        package = import_module(package_name)
        modules = [
            package,
            *(
                import_module(info.name)
                for info in sorted(
                    pkgutil.walk_packages(package.__path__, package.__name__ + "."),
                    key=lambda info: info.name,
                )
                if not info.name.rsplit(".", 1)[-1].startswith("_")
            ),
        ]
        for module in modules:
            for _, function in inspect.getmembers(module, inspect.isfunction):
                if function.__module__ == module.__name__ and getattr(
                    function, "__jarvis_tool__", False
                ):
                    registry.register(function)
        return registry

    def register(self, function: Callable) -> None:
        name = function.__name__
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", name) or name in self._tools:
            raise ValueError(f"Nombre de herramienta inválido o duplicado: {name}")
        description = inspect.getdoc(function)
        if not description:
            raise ValueError(f"La herramienta {name} requiere docstring")
        hints = get_type_hints(function)
        fields = {}
        inject_context = False
        for parameter in inspect.signature(function).parameters.values():
            if parameter.kind not in (parameter.POSITIONAL_OR_KEYWORD, parameter.KEYWORD_ONLY):
                raise ValueError(f"Firma no admitida: {name}")
            annotation = hints.get(parameter.name)
            if annotation is None:
                raise ValueError(f"Falta tipo para {name}.{parameter.name}")
            if parameter.name == "context":
                if annotation is not ToolContext:
                    raise ValueError("context debe tener tipo ToolContext")
                inject_context = True
                continue
            default = ... if parameter.default is inspect.Parameter.empty else parameter.default
            fields[parameter.name] = (annotation, default)
        arguments = create_model(
            f"{name}Arguments", __config__=ConfigDict(extra="forbid", strict=True), **fields
        )
        definition = pydantic_function_tool(arguments, name=name, description=description)[
            "function"
        ]
        self._tools[name] = RegisteredTool(
            handler=function,
            arguments=arguments,
            inject_context=inject_context,
            schema={"type": "function", **definition},
        )

    @property
    def schemas(self) -> list[dict[str, Any]]:
        return [registered.schema for registered in self._tools.values()]

    async def execute(self, name: str, raw_arguments: str, context: ToolContext) -> str:
        registered = self._tools.get(name)
        if registered is None:
            return json.dumps({"error": "Herramienta desconocida"})
        try:
            arguments = registered.arguments.model_validate_json(raw_arguments)
        except ValidationError:
            return json.dumps({"error": "Argumentos inválidos para la herramienta"})
        kwargs = {key: getattr(arguments, key) for key in type(arguments).model_fields}
        if registered.inject_context:
            kwargs["context"] = context
        try:
            async with asyncio.timeout(10):
                if inspect.iscoroutinefunction(registered.handler):
                    result = await registered.handler(**kwargs)
                else:
                    result = await run_in_threadpool(registered.handler, **kwargs)
            return json.dumps(result, ensure_ascii=False, allow_nan=False)
        except Exception as exc:
            # Los errores pueden incluir texto clínico o secretos: registrar solo el tipo.
            logger.warning("tool_failed tool=%s kind=%s", name, type(exc).__name__)
            return json.dumps({"error": "La herramienta no pudo completar la consulta"})
