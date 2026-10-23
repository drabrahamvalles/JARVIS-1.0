from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


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
