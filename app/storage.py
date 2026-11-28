import json
import logging
import os
import re
import threading
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit

from google.api_core.retry import Retry
from google.cloud import firestore

from app import timezone_state
from app.timezone_state import TimezoneState

MAX_TURNS = 10
RETENTION = timedelta(days=7)
DEFAULT_USER = "principal"
RPC_TIMEOUT = 2.0
RPC_RETRY = Retry(initial=0.1, maximum=0.5, timeout=2.0)
_LOCAL_HISTORY_LOCK = threading.RLock()


class Store(Protocol):
    def read_history(self) -> list[dict[str, str]]: ...
    def append_turn(self, question: str, answer: str) -> None: ...
    def read_timezone(self) -> TimezoneState: ...
    def write_timezone(self, state: TimezoneState) -> None: ...
    def read_pending_delete(self) -> dict | None: ...
    def write_pending_delete(self, pending: dict | None) -> None: ...
    def read_pending_email(self) -> dict | None: ...
    def write_pending_email(self, pending: dict | None) -> None: ...
    def read_whoop_token(self) -> dict | None: ...
    def read_correo_revision(self) -> dict | None: ...
    def read_avisos_salida(self) -> dict | None: ...
    def write_avisos_salida(self, state: dict) -> None: ...
    def read_ubicacion(self) -> dict | None: ...
    def read_expediente(self) -> dict | None: ...
    def write_expediente(self, data: dict) -> None: ...
    def write_ubicacion(self, location: dict) -> None: ...
    def write_correo_revision(self, state: dict) -> None: ...
    def write_whoop_token(self, token: dict) -> None: ...


def _unexpired(turns: list[dict], user_id: str, now: datetime) -> list[dict]:
    return [turn for turn in turns if turn["usuario_id"] == user_id and turn["expira_en"] > now]


def _messages(turns: list[dict]) -> list[dict[str, str]]:
    return [
        message
        for turn in turns
        for message in (
            {"role": "user", "content": turn["pregunta"]},
            {"role": "assistant", "content": turn["respuesta"]},
        )
    ]


class LocalStore:
    def __init__(self, user_id: str, state_path: Path) -> None:
        self.user_id = user_id
        user_path = state_path.parent / "usuarios" / user_id
        self.history_path = user_path / "historial.json"
        self.state_path = state_path if user_id == DEFAULT_USER else user_path / "estado.json"
        self.pending_path = user_path / "borrado_pendiente.json"
        self.email_path = user_path / "correo_pendiente.json"
        self.whoop_path = user_path / "whoop_token.json"
        self.revision_path = user_path / "revision_correo.json"
        self.avisos_path = user_path / "avisos_salida.json"
        self.ubicacion_path = user_path / "ubicacion.json"
        self.expediente_path = user_path / "expediente.json"

    def _read_turns(self, now: datetime) -> list[dict]:
        try:
            saved = json.loads(self.history_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        for turn in saved:
            turn["expira_en"] = datetime.fromisoformat(turn["expira_en"])
        return _unexpired(saved, self.user_id, now)

    def read_history(self) -> list[dict[str, str]]:
        with _LOCAL_HISTORY_LOCK:
            return _messages(self._read_turns(datetime.now(UTC))[-MAX_TURNS:])

    def append_turn(self, question: str, answer: str) -> None:
        with _LOCAL_HISTORY_LOCK:
            now = datetime.now(UTC)
            turns = self._read_turns(now)[-(MAX_TURNS - 1) :]
            turns.append(
                {
                    "usuario_id": self.user_id,
                    "pregunta": question,
                    "respuesta": answer,
                    "expira_en": now + RETENTION,
                }
            )
            for turn in turns:
                turn["expira_en"] = turn["expira_en"].isoformat()
            timezone_state.write_json_atomically(self.history_path, turns)

    def read_timezone(self) -> TimezoneState:
        return timezone_state.read_timezone_state(self.state_path, strict=True)

    def write_timezone(self, state: TimezoneState) -> None:
        timezone_state.write_timezone_state(state, self.state_path)

    def read_pending_delete(self) -> dict | None:
        try:
            data = json.loads(self.pending_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        return data if isinstance(data, dict) and data.get("usuario_id") == self.user_id else None

    def write_pending_delete(self, pending: dict | None) -> None:
        data = None if pending is None else {"usuario_id": self.user_id, **pending}
        timezone_state.write_json_atomically(self.pending_path, data)

    def read_pending_email(self) -> dict | None:
        try:
            data = json.loads(self.email_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        return data if isinstance(data, dict) and data.get("usuario_id") == self.user_id else None

    def write_pending_email(self, pending: dict | None) -> None:
        data = None if pending is None else {"usuario_id": self.user_id, **pending}
        timezone_state.write_json_atomically(self.email_path, data)

    def read_whoop_token(self) -> dict | None:
        try:
            data = json.loads(self.whoop_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        return data if isinstance(data, dict) and data.get("usuario_id") == self.user_id else None

    def write_whoop_token(self, token: dict) -> None:
        timezone_state.write_json_atomically(self.whoop_path, {"usuario_id": self.user_id, **token})

    def read_correo_revision(self) -> dict | None:
        try:
            data = json.loads(self.revision_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        return data if isinstance(data, dict) and data.get("usuario_id") == self.user_id else None

    def write_correo_revision(self, state: dict) -> None:
        timezone_state.write_json_atomically(
            self.revision_path, {"usuario_id": self.user_id, **state}
        )

    def _read_owned(self, path) -> dict | None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        return data if isinstance(data, dict) and data.get("usuario_id") == self.user_id else None

    def read_avisos_salida(self) -> dict | None:
        return self._read_owned(self.avisos_path)

    def write_avisos_salida(self, state: dict) -> None:
        timezone_state.write_json_atomically(
            self.avisos_path, {"usuario_id": self.user_id, **state}
        )

    def read_ubicacion(self) -> dict | None:
        return self._read_owned(self.ubicacion_path)

    def write_ubicacion(self, location: dict) -> None:
        timezone_state.write_json_atomically(
            self.ubicacion_path, {"usuario_id": self.user_id, **location}
        )

    def read_expediente(self) -> dict | None:
        return self._read_owned(self.expediente_path)

    def write_expediente(self, data: dict) -> None:
        timezone_state.write_json_atomically(
            self.expediente_path, {"usuario_id": self.user_id, **data}
        )


def _stage_firestore_turn(transaction, counter, turns, turn):
    snapshot = counter.get(transaction=transaction, retry=RPC_RETRY, timeout=RPC_TIMEOUT)
    sequence = snapshot.to_dict()["siguiente_turno"] if snapshot.exists else 0
    transaction.set(turns.document(str(sequence % MAX_TURNS)), {**turn, "turno": sequence})
    transaction.set(counter, {"usuario_id": turn["usuario_id"], "siguiente_turno": sequence + 1})


class FirestoreStore:
    def __init__(
        self, user_id: str, *, project: str | None = None, client: firestore.Client | None = None
    ) -> None:
        self.user_id = user_id
        self._project = project
        self._client = client
        self._client_lock = threading.Lock()

    @property
    def client(self) -> firestore.Client:
        with self._client_lock:
            if self._client is None:
                self._client = firestore.Client(project=self._project, database="(default)")
            return self._client

    @property
    def _user(self):
        return self.client.collection("usuarios").document(self.user_id)

    def read_history(self) -> list[dict[str, str]]:
        query = self._user.collection("turnos_conversacion").order_by("turno").limit(MAX_TURNS)
        snapshots = query.get(retry=RPC_RETRY, timeout=RPC_TIMEOUT)
        rows = [snapshot.to_dict() for snapshot in snapshots]
        return _messages(_unexpired(rows, self.user_id, datetime.now(UTC)))

    def append_turn(self, question: str, answer: str) -> None:
        now = datetime.now(UTC)
        user = self._user
        firestore.transactional(_stage_firestore_turn)(
            self.client.transaction(max_attempts=2),
            user.collection("estado").document("memoria"),
            user.collection("turnos_conversacion"),
            {
                "usuario_id": self.user_id,
                "pregunta": question,
                "respuesta": answer,
                "creado_en": now,
                "expira_en": now + RETENTION,
            },
        )

    def read_timezone(self) -> TimezoneState:
        reference = self._user.collection("estado").document("zona_horaria")
        snapshot = reference.get(retry=RPC_RETRY, timeout=RPC_TIMEOUT)
        data = snapshot.to_dict()
        if not data or data.get("usuario_id") != self.user_id:
            return TimezoneState()
        return timezone_state.decode_timezone_state(data)

    def write_timezone(self, state: TimezoneState) -> None:
        reference = self._user.collection("estado").document("zona_horaria")
        reference.set(
            {"usuario_id": self.user_id, **asdict(state)}, retry=RPC_RETRY, timeout=RPC_TIMEOUT
        )

    def read_pending_delete(self) -> dict | None:
        reference = self._user.collection("estado").document("borrado_pendiente")
        data = reference.get(retry=RPC_RETRY, timeout=RPC_TIMEOUT).to_dict()
        if not data or data.get("usuario_id") != self.user_id:
            return None
        if not (data.get("eventos") or data.get("evento_id")):
            return None
        return data

    def write_pending_delete(self, pending: dict | None) -> None:
        reference = self._user.collection("estado").document("borrado_pendiente")
        # Un documento vacío equivale a «no hay borrado pendiente» sin necesitar permiso de borrar.
        data = {"usuario_id": self.user_id, **(pending or {"evento_id": None})}
        reference.set(data, retry=RPC_RETRY, timeout=RPC_TIMEOUT)

    def read_pending_email(self) -> dict | None:
        reference = self._user.collection("estado").document("correo_pendiente")
        data = reference.get(retry=RPC_RETRY, timeout=RPC_TIMEOUT).to_dict()
        if not data or data.get("usuario_id") != self.user_id or not data.get("para"):
            return None
        return data

    def write_pending_email(self, pending: dict | None) -> None:
        reference = self._user.collection("estado").document("correo_pendiente")
        data = {"usuario_id": self.user_id, **(pending or {"para": None})}
        reference.set(data, retry=RPC_RETRY, timeout=RPC_TIMEOUT)

    def read_whoop_token(self) -> dict | None:
        reference = self._user.collection("estado").document("whoop_token")
        data = reference.get(retry=RPC_RETRY, timeout=RPC_TIMEOUT).to_dict()
        if not data or data.get("usuario_id") != self.user_id or not data.get("refresh_token"):
            return None
        return data

    def write_whoop_token(self, token: dict) -> None:
        reference = self._user.collection("estado").document("whoop_token")
        reference.set({"usuario_id": self.user_id, **token}, retry=RPC_RETRY, timeout=RPC_TIMEOUT)

    def read_correo_revision(self) -> dict | None:
        reference = self._user.collection("estado").document("revision_correo")
        data = reference.get(retry=RPC_RETRY, timeout=RPC_TIMEOUT).to_dict()
        if not data or data.get("usuario_id") != self.user_id:
            return None
        return data

    def write_correo_revision(self, state: dict) -> None:
        reference = self._user.collection("estado").document("revision_correo")
        reference.set({"usuario_id": self.user_id, **state}, retry=RPC_RETRY, timeout=RPC_TIMEOUT)

    def _read_state(self, name: str) -> dict | None:
        reference = self._user.collection("estado").document(name)
        data = reference.get(retry=RPC_RETRY, timeout=RPC_TIMEOUT).to_dict()
        return data if data and data.get("usuario_id") == self.user_id else None

    def _write_state(self, name: str, data: dict) -> None:
        reference = self._user.collection("estado").document(name)
        reference.set({"usuario_id": self.user_id, **data}, retry=RPC_RETRY, timeout=RPC_TIMEOUT)

    def read_avisos_salida(self) -> dict | None:
        return self._read_state("avisos_salida")

    def write_avisos_salida(self, state: dict) -> None:
        self._write_state("avisos_salida", state)

    def read_ubicacion(self) -> dict | None:
        return self._read_state("ubicacion")

    def write_ubicacion(self, location: dict) -> None:
        self._write_state("ubicacion", location)

    def read_expediente(self) -> dict | None:
        return self._read_state("expediente")

    def write_expediente(self, data: dict) -> None:
        self._write_state("expediente", data)


def build_store(env: dict[str, str]) -> Store:
    user_id = env.get("JARVIS_USER_ID") or DEFAULT_USER
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", user_id):
        raise ValueError("JARVIS_USER_ID debe ser un identificador alfanumérico válido")
    emulator = os.environ.get("FIRESTORE_EMULATOR_HOST")
    if env.get("K_SERVICE") and emulator:
        raise ValueError("FIRESTORE_EMULATOR_HOST solo se admite en local")
    if emulator:
        host = urlsplit(f"//{emulator}").hostname
        if host not in {"127.0.0.1", "::1", "localhost"}:
            raise ValueError("El emulador de Firestore debe estar en la Mac")
    if env.get("K_SERVICE") or emulator:
        sdk_logger = logging.getLogger("google.cloud.firestore_v1")
        sdk_logger.handlers = [logging.NullHandler()]
        sdk_logger.propagate = False
        return FirestoreStore(user_id, project="jarvis-local" if emulator else None)
    return LocalStore(user_id, timezone_state.STATE_PATH)
