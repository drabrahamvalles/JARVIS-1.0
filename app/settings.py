import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ROOT = Path(__file__).resolve().parents[1]


class ModelPricing(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    entrada: float = Field(ge=0)
    entrada_cache: float = Field(ge=0)
    escritura_cache: float = Field(ge=0)
    salida: float = Field(ge=0)


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    modelo_rapido: str = Field(min_length=1)
    modelo_profundo: str = Field(min_length=1)
    precios_modelos: dict[str, ModelPricing]
    ciudad: str = Field(min_length=1)
    zona_horaria_por_defecto: str
    modo_zona_horaria: Literal["automatico", "fijo"] = "automatico"
    razonamiento_rapido: Literal["low", "medium", "high", "xhigh", "max"] = "low"
    razonamiento_profundo: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    razonamiento_a_fondo: Literal["low", "medium", "high", "xhigh", "max"] = "high"
    max_output_tokens: int = Field(default=1200, ge=128, le=8000)
    max_output_tokens_cientifico: int = Field(default=4000, ge=128, le=8000)
    max_rondas_herramientas: int = Field(default=3, ge=0, le=6)

    @field_validator("zona_horaria_por_defecto")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Se requiere una zona horaria IANA válida") from exc
        return value

    @model_validator(mode="after")
    def prices_exist_for_selected_models(self) -> Self:
        missing = {
            model
            for model in (self.modelo_rapido, self.modelo_profundo)
            if model not in self.precios_modelos
        }
        if missing:
            raise ValueError("Faltan precios para los modelos configurados")
        return self


@dataclass(frozen=True)
class Secrets:
    openai_api_key: str | None = field(default=None, repr=False)
    jarvis_token: str | None = field(default=None, repr=False)


def runtime_environment(env_file: Path = ROOT / ".env") -> dict[str, str]:
    """Las variables del proveedor tienen prioridad sobre el archivo local."""
    local = dotenv_values(env_file) if env_file.is_file() else {}
    return {**{k: v for k, v in local.items() if v is not None}, **os.environ}


def load_secrets(env_file: Path = ROOT / ".env") -> Secrets:
    env = runtime_environment(env_file)
    return Secrets(
        openai_api_key=env.get("OPENAI_API_KEY", "").strip() or None,
        jarvis_token=env.get("JARVIS_TOKEN", "").strip() or None,
    )


def load_config(path: Path = ROOT / "config/config.yaml") -> AppConfig:
    return AppConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
