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


class ClothingRules(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    chamarra_menor_que_c: float
    sueter_desde_c: float
    sueter_hasta_c: float
    paraguas_desde_pct: float = Field(ge=0, le=100)
    ropa_ligera_desde_c: float
    texto_chamarra: str = Field(min_length=1)
    texto_sueter: str = Field(min_length=1)
    texto_paraguas: str = Field(min_length=1)
    texto_ropa_ligera: str = Field(min_length=1)
    texto_sin_recomendacion: str = Field(min_length=1)

    @model_validator(mode="after")
    def valid_temperature_ranges(self) -> Self:
        if self.sueter_desde_c != self.chamarra_menor_que_c:
            raise ValueError("El suéter debe comenzar donde termina la regla de chamarra")
        if self.sueter_hasta_c < self.sueter_desde_c:
            raise ValueError("El intervalo del suéter no es válido")
        return self


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    modelo_rapido: str = Field(min_length=1)
    modelo_profundo: str = Field(min_length=1)
    modelo_briefing: str = Field(min_length=1)
    terminos_modelo_profundo: tuple[str, ...] = Field(min_length=1)
    precios_modelos: dict[str, ModelPricing]
    ciudad: str = Field(min_length=1)
    latitud_por_defecto: float = Field(ge=-90, le=90, allow_inf_nan=False)
    longitud_por_defecto: float = Field(ge=-180, le=180, allow_inf_nan=False)
    zona_horaria_por_defecto: str
    reglas_ropa: ClothingRules
    modo_zona_horaria: Literal["automatico", "fijo"] = "automatico"
    razonamiento_rapido: Literal["low", "medium", "high", "xhigh", "max"] = "low"
    razonamiento_profundo: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    razonamiento_a_fondo: Literal["low", "medium", "high", "xhigh", "max"] = "high"
    max_output_tokens: int = Field(default=1200, ge=128, le=8000)
    max_output_tokens_cientifico: int = Field(default=4000, ge=128, le=8000)
    max_output_tokens_briefing: int = Field(default=300, ge=128, le=1000)
    max_rondas_herramientas: int = Field(default=3, ge=0, le=6)

    @field_validator("zona_horaria_por_defecto")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Se requiere una zona horaria IANA válida") from exc
        return value

    @field_validator("terminos_modelo_profundo")
    @classmethod
    def valid_deep_model_terms(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("Los términos del modelo profundo no pueden estar vacíos")
        if len({value.casefold() for value in cleaned}) != len(cleaned):
            raise ValueError("Los términos del modelo profundo no pueden repetirse")
        return cleaned

    @model_validator(mode="after")
    def prices_exist_for_selected_models(self) -> Self:
        missing = {
            model
            for model in (self.modelo_rapido, self.modelo_profundo, self.modelo_briefing)
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
