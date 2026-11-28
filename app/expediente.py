"""Expediente del Dr. Valles: lo que JARVIS aprende de él para ayudarle mejor.

Hay dos fuentes:
- Datos que él dice («yo como a las dos», «mi consultorio está en…»). El modelo los
  guarda con recordar_dato o guardar_lugar y se le pasan en cada pregunta.
- Hábitos que se calculan solos, como sus horas de dormir y despertar (WHOOP).

Todo vive en usuarios/{id}/estado/expediente. Él puede preguntar «¿qué sabes de mí?» y
pedir que se borre cualquier dato. Nunca se guardan datos de pacientes.
"""

import secrets
import unicodedata
from datetime import UTC, datetime
from typing import Any

from app.storage import Store

MAX_DATOS = 60
MAX_TEXTO = 300
CATEGORIAS = ("rutina", "preferencia", "persona", "trabajo", "salud", "otro")


def normalized(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    kept = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join("".join(c if c.isalnum() else " " for c in kept).split())


def _load(store: Store) -> dict[str, Any]:
    data = store.read_expediente() or {}
    return {"datos": list(data.get("datos") or []), "lugares": list(data.get("lugares") or [])}


def _save(store: Store, data: dict[str, Any]) -> None:
    store.write_expediente({"datos": data["datos"], "lugares": data["lugares"]})


def add_fact(store: Store, category: str, text: str) -> dict[str, str]:
    data = _load(store)
    text = " ".join(text.split())[:MAX_TEXTO]
    category = category if category in CATEGORIAS else "otro"
    key = normalized(text)
    for fact in data["datos"]:
        if normalized(fact["texto"]) == key:
            return fact
    fact = {
        "id": secrets.token_hex(4),
        "categoria": category,
        "texto": text,
        "fecha": datetime.now(UTC).date().isoformat(),
    }
    # Si se llena, se olvida lo más viejo.
    data["datos"] = (data["datos"] + [fact])[-MAX_DATOS:]
    _save(store, data)
    return fact


def save_place(
    store: Store,
    name: str,
    address: str,
    lat: float | None = None,
    lon: float | None = None,
) -> dict[str, Any]:
    data = _load(store)
    name = " ".join(name.split())[:80]
    address = " ".join(address.split())[:MAX_TEXTO]
    key = normalized(name)
    places = [place for place in data["lugares"] if normalized(place["nombre"]) != key]
    place: dict[str, Any] = {"id": secrets.token_hex(4), "nombre": name, "direccion": address}
    if lat is not None and lon is not None:
        place["lat"], place["lon"] = round(lat, 6), round(lon, 6)
    data["lugares"] = (places + [place])[-MAX_DATOS:]
    _save(store, data)
    return place


def forget(store: Store, item_id: str) -> bool:
    data = _load(store)
    before = len(data["datos"]) + len(data["lugares"])
    data["datos"] = [fact for fact in data["datos"] if fact["id"] != item_id]
    data["lugares"] = [place for place in data["lugares"] if place["id"] != item_id]
    if len(data["datos"]) + len(data["lugares"]) == before:
        return False
    _save(store, data)
    return True


def read_all(store: Store) -> dict[str, Any]:
    return _load(store)


def resolve_place(places: list[dict[str, Any]], *texts: str | None) -> str | None:
    """Destino de un lugar guardado si el lugar o el título del evento lo nombra: sus
    coordenadas («lat,lon») si las tiene, si no su dirección."""
    for text in texts:
        if not text:
            continue
        value = normalized(text)
        for place in sorted(places, key=lambda p: -len(p["nombre"])):
            name = normalized(place["nombre"])
            if name and (value == name or f" {name} " in f" {value} "):
                if place.get("lat") is not None:
                    return f"{place['lat']},{place['lon']}"
                return place["direccion"]
    return None


def for_instructions(data: dict[str, Any]) -> str | None:
    """Resumen corto para las instrucciones del modelo."""
    lines = [f"- ({fact['categoria']}) {fact['texto']}" for fact in data.get("datos", [])]
    lines += [
        f"- (lugar) {place['nombre']}: {place['direccion']}" for place in data.get("lugares", [])
    ]
    return "\n".join(lines) or None
