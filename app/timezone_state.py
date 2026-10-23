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


def is_valid_timezone(name: str) -> bool:
    return name in AVAILABLE_TIMEZONES


def read_timezone_state() -> TimezoneState:
    with _LOCK:
        try:
            raw = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError, TypeError, UnicodeError):
            return TimezoneState()
        if not isinstance(raw, dict):
            return TimezoneState()
        if raw.get("modo") == "automatico":
            return TimezoneState()
        city = raw.get("ciudad")
        zone = raw.get("zona_horaria")
        if (
            raw.get("modo") == "manual"
            and isinstance(city, str)
            and city.strip()
            and isinstance(zone, str)
            and is_valid_timezone(zone)
        ):
            return TimezoneState("manual", city.strip(), zone)
        return TimezoneState()


def write_timezone_state(state: TimezoneState) -> None:
    with _LOCK:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=STATE_PATH.parent,
                prefix=".estado-",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary = Path(handle.name)
                json.dump(asdict(state), handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, STATE_PATH)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
