from datetime import date, datetime
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    texto: str = Field(min_length=1, max_length=12000, strict=True)
    lat: Annotated[float, Field(ge=-90, le=90, allow_inf_nan=False, strict=True)] | None = None
    lon: Annotated[float, Field(ge=-180, le=180, allow_inf_nan=False, strict=True)] | None = None
    dispositivo: str | None = Field(default=None, min_length=1, max_length=120, strict=True)

    @model_validator(mode="after")
    def paired_coordinates(self) -> Self:
        if (self.lat is None) != (self.lon is None):
            raise ValueError("Envía lat y lon juntas, o ninguna")
        return self


class AskResponse(BaseModel):
    respuesta: str


BriefingItem = Annotated[str, Field(min_length=1, max_length=1000, strict=True)]


class BriefingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    fecha_iso: date
    lat: Annotated[float, Field(ge=-90, le=90, allow_inf_nan=False, strict=True)] | None = None
    lon: Annotated[float, Field(ge=-180, le=180, allow_inf_nan=False, strict=True)] | None = None
    ciudad: str | None = Field(default=None, min_length=1, max_length=120, strict=True)
    eventos: list[BriefingItem] = Field(max_length=100)
    recordatorios: list[BriefingItem] = Field(max_length=100)

    @field_validator("fecha_iso", mode="before")
    @classmethod
    def parse_shortcuts_date(cls, value: Any) -> date:
        if isinstance(value, datetime):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("La fecha-hora ISO debe incluir zona horaria")
            return value.date()
        if isinstance(value, date):
            return value
        if not isinstance(value, str):
            raise ValueError("Se requiere una fecha ISO")
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("Se requiere AAAA-MM-DD o una fecha-hora ISO 8601") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("La fecha-hora ISO debe incluir zona horaria")
        return parsed.date()

    @field_validator("lat", "lon", mode="before")
    @classmethod
    def empty_coordinate_is_missing(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("ciudad", mode="before")
    @classmethod
    def empty_city_is_missing(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("eventos", "recordatorios", mode="before")
    @classmethod
    def shortcuts_repetition_results(cls, value: Any) -> Any:
        if isinstance(value, str):
            return [line.strip() for line in value.splitlines() if line.strip()]
        return value

    @model_validator(mode="after")
    def paired_coordinates(self) -> Self:
        if (self.lat is None) != (self.lon is None):
            raise ValueError("Envía lat y lon juntas, o ninguna")
        return self


class BriefingResponse(BaseModel):
    respuesta: str


class CapturaRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    texto: str = Field(max_length=4000, strict=True)
    imagen_base64: str = Field(min_length=1, strict=True)
    lat: Annotated[float, Field(ge=-90, le=90, allow_inf_nan=False, strict=True)] | None = None
    lon: Annotated[float, Field(ge=-180, le=180, allow_inf_nan=False, strict=True)] | None = None
    ciudad: str | None = Field(default=None, min_length=1, max_length=120, strict=True)
    dispositivo: str | None = Field(default=None, min_length=1, max_length=120, strict=True)

    @field_validator("lat", "lon", mode="before")
    @classmethod
    def empty_coordinate_is_missing(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("ciudad", "dispositivo", mode="before")
    @classmethod
    def empty_optional_text_is_missing(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def paired_coordinates(self) -> Self:
        if (self.lat is None) != (self.lon is None):
            raise ValueError("Envía lat y lon juntas, o ninguna")
        return self


class CapturaResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tipo: Literal["evento", "recordatorio", "ninguno"]
    titulo: str | None
    inicio: str | None
    fin: str | None
    lugar: str | None
    notas: str | None
    respuesta: str
