import json
import os
import tempfile
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal
from zoneinfo import available_timezones

from app.settings import ROOT

STATE_PATH = ROOT / "data/estado.json"
AVAILABLE_TIMEZONES = frozenset(available_timezones())
_LOCK = threading.RLock()


@dataclass(frozen=True)
class TimezoneState:
    modo: Literal["automatico", "manual"] = "automatico"
    ciudad: str | None = None
    zona_horaria: str | None = None


class TimezoneWriteError(Exception):
    """No se pudo guardar una solicitud explícita de cambio de zona."""


def is_valid_timezone(name: str) -> bool:
    return name in AVAILABLE_TIMEZONES


def decode_timezone_state(raw: object) -> TimezoneState:
    if not isinstance(raw, dict) or raw.get("modo") != "manual":
        return TimezoneState()
    city = raw.get("ciudad")
    zone = raw.get("zona_horaria")
    if isinstance(city, str) and city.strip() and isinstance(zone, str) and is_valid_timezone(zone):
        return TimezoneState("manual", city.strip(), zone)
    return TimezoneState()


def read_timezone_state(path: Path | None = None, *, strict: bool = False) -> TimezoneState:
    with _LOCK:
        try:
            raw = json.loads((path or STATE_PATH).read_text(encoding="utf-8"))
        except FileNotFoundError:
            return TimezoneState()
        except (json.JSONDecodeError, OSError, TypeError, UnicodeError):
            if strict:
                raise
            return TimezoneState()
        return decode_timezone_state(raw)


def write_timezone_state(state: TimezoneState, path: Path | None = None) -> None:
    with _LOCK:
        write_json_atomically(path or STATE_PATH, asdict(state))


def write_json_atomically(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=".jarvis-", delete=False
        ) as handle:
            temporary = Path(handle.name)
            json.dump(data, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
