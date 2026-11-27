import json
import logging
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi.testclient import TestClient
from google.auth.credentials import AnonymousCredentials
from google.cloud import firestore
from google.cloud.firestore_v1.types import (
    BatchGetDocumentsResponse,
    BeginTransactionResponse,
    CommitResponse,
    RunQueryResponse,
    WriteResult,
)

from app.main import create_app
from app.settings import Secrets
from app.storage import FirestoreStore, LocalStore
from app.timezone_state import TimezoneState
from tests.conftest import AUTH, TOKEN
from tests.test_brain import response


class FirestoreRPC:
    def __init__(self):
        self.documents = {}
        self.commits = []

    def begin_transaction(self, **kwargs):
        return BeginTransactionResponse(transaction=b"test-transaction")

    def batch_get_documents(self, *, request, **kwargs):
        path = request["documents"][0]
        now = datetime.now(UTC)
        if path in self.documents:
            return iter([BatchGetDocumentsResponse(found=self.documents[path], read_time=now)])
        return iter([BatchGetDocumentsResponse(missing=path, read_time=now)])

    def commit(self, *, request, **kwargs):
        self.commits.append(request)
        for write in request["writes"]:
            self.documents[write.update.name] = write.update
        now = datetime.now(UTC)
        return CommitResponse(
            write_results=[WriteResult(update_time=now) for _ in request["writes"]],
            commit_time=now,
        )

    def run_query(self, *, request, **kwargs):
        query = request["structured_query"]
        prefix = request["parent"] + "/" + query.from_[0].collection_id + "/"
        rows = [doc for path, doc in self.documents.items() if path.startswith(prefix)]
        rows.sort(key=lambda doc: doc.fields["turno"].integer_value)
        return iter(
            RunQueryResponse(document=row, read_time=datetime.now(UTC))
            for row in rows[: query.limit]
        )


def firestore_store(rpc, user):
    client = firestore.Client(project="jarvis-test", credentials=AnonymousCredentials())
    client._firestore_api_internal = rpc
    return FirestoreStore(user, client=client)


@pytest.mark.parametrize("backend", ["archivo", "firestore"])
def test_turns_and_zone_survive_restart_and_isolate_users(backend, tmp_path, monkeypatch):
    class Clock(datetime):
        current = datetime(2026, 11, 26, tzinfo=UTC)

        @classmethod
        def now(cls, tz):
            return cls.current

    monkeypatch.setattr("app.storage.datetime", Clock)
    rpc = FirestoreRPC()

    def make_store(user):
        if backend == "firestore":
            return firestore_store(rpc, user)
        return LocalStore(user, tmp_path / "estado.json")

    first = make_store("principal")
    other = make_store("otro")
    manual = TimezoneState("manual", "Houston", "America/Chicago")
    for number in range(11):
        first.append_turn(f"Pregunta {number}", f"Respuesta {number}")
    first.write_timezone(manual)
    other.append_turn("Pregunta privada", "Respuesta privada")

    restarted = make_store("principal")
    history = restarted.read_history()
    assert history[::2] == [
        {"role": "user", "content": f"Pregunta {number}"} for number in range(1, 11)
    ]
    assert restarted.read_timezone() == manual
    assert other.read_timezone() == TimezoneState()
    assert other.read_history()[0]["content"] == "Pregunta privada"

    if backend == "firestore":
        rows = [doc for path, doc in rpc.documents.items() if "/turnos_conversacion/" in path]
        assert len(rows) == 11
        assert {doc.fields["usuario_id"].string_value for doc in rpc.documents.values()} == {
            "principal",
            "otro",
        }
        for doc in rows:
            assert doc.fields["expira_en"].timestamp_value == Clock.current + timedelta(days=7)
        assert rpc.commits[0]["transaction"] == b"test-transaction"
        assert len(rpc.commits[0]["writes"]) == 2

    Clock.current += timedelta(days=7)
    assert restarted.read_history() == []
    assert restarted.read_timezone() == manual
    restarted.write_timezone(TimezoneState())
    assert make_store("principal").read_timezone() == TimezoneState()


@pytest.fixture
def degraded_app(config, monkeypatch):
    def make(store, create):
        model = SimpleNamespace(responses=SimpleNamespace(create=create), close=AsyncMock())
        monkeypatch.setattr("app.main.AsyncOpenAI", lambda **kwargs: model)
        return TestClient(
            create_app(
                config=config.model_copy(update={"modo_zona_horaria": "fijo"}),
                secrets=Secrets(openai_api_key="test-key", jarvis_token=TOKEN),
                store=store,
            )
        )

    return make


def storage_with_history():
    return Mock(
        read_timezone=Mock(return_value=TimezoneState("manual", "Boston", "America/New_York")),
        read_history=Mock(return_value=[{"role": "user", "content": "private-history"}]),
    )


@pytest.mark.parametrize(
    "failure,operation",
    [("read_history", "history_read"), ("read_timezone", "timezone_read")],
)
def test_ask_with_failed_read_skips_history_and_uses_coordinates(
    failure, operation, degraded_app, caplog
):
    store = storage_with_history()
    getattr(store, failure).side_effect = RuntimeError("private-storage-error")
    create = AsyncMock(return_value=response(text="Respuesta breve."))
    caplog.set_level(logging.WARNING)

    with degraded_app(store, create) as client:
        result = client.post(
            "/ask", headers=AUTH, json={"texto": "Consulta", "lat": 35.6762, "lon": 139.6503}
        )

    assert result.status_code == 200
    assert result.json() == {"respuesta": "Respuesta breve."}
    call = create.await_args.kwargs
    assert len(call["input"]) == 1
    assert '"zona_horaria": "Asia/Tokyo"' in call["instructions"]
    assert '"origen_zona_horaria": "coordenadas"' in call["instructions"]
    assert f"operation={operation} kind=RuntimeError" in caplog.text
    assert "private-storage-error" not in caplog.text


def test_ask_with_failed_history_write_keeps_the_answer(degraded_app, caplog):
    store = storage_with_history()
    store.append_turn.side_effect = OSError("private-storage-error")
    create = AsyncMock(return_value=response(text="private-answer"))
    caplog.set_level(logging.WARNING)

    with degraded_app(store, create) as client:
        result = client.post("/ask", headers=AUTH, json={"texto": "private-question"})

    assert result.status_code == 200
    assert result.json() == {"respuesta": "private-answer"}
    assert "operation=history_write kind=OSError" in caplog.text
    assert all(
        private not in caplog.text
        for private in ("private-storage-error", "private-question", "private-answer")
    )


@pytest.mark.parametrize(
    "name,arguments,question",
    [
        (
            "fijar_zona_horaria",
            {"ciudad": "Tokio", "zona_iana": "Asia/Tokyo"},
            "Fija mi zona horaria a Tokio.",
        ),
        ("volver_a_automatico", {}, "Vuelve a la zona horaria automática."),
    ],
)
def test_ask_reports_failed_explicit_zone_write(degraded_app, caplog, name, arguments, question):
    store = storage_with_history()
    store.write_timezone.side_effect = OSError("private-storage-error")
    call = SimpleNamespace(
        type="function_call", name=name, arguments=json.dumps(arguments), call_id="call_test"
    )
    create = AsyncMock(return_value=response(output=[call]))
    caplog.set_level(logging.WARNING)

    with degraded_app(store, create) as client:
        result = client.post("/ask", headers=AUTH, json={"texto": question})

    assert result.status_code == 200
    assert result.json() == {"respuesta": "No pude guardarlo, Dr. Valles."}
    assert create.await_count == 1
    assert "operation=timezone_write kind=OSError" in caplog.text
    assert "private-storage-error" not in caplog.text


@pytest.mark.parametrize("backend", ["archivo", "firestore"])
def test_pending_delete_roundtrip_and_isolation(backend, tmp_path):
    rpc = FirestoreRPC()

    def make_store(user):
        if backend == "firestore":
            return firestore_store(rpc, user)
        return LocalStore(user, tmp_path / "estado.json")

    store, other = make_store("principal"), make_store("otro")
    assert store.read_pending_delete() is None
    pending = {"evento_id": "0:abc", "titulo": "Cita", "solicitud_id": "s1", "expira_en": "x"}
    store.write_pending_delete(pending)
    assert make_store("principal").read_pending_delete() == {"usuario_id": "principal", **pending}
    assert other.read_pending_delete() is None
    several = {"eventos": [{"evento_id": "0:a"}, {"evento_id": "0:b"}], "solicitud_id": "s2"}
    store.write_pending_delete(several)
    assert store.read_pending_delete() == {"usuario_id": "principal", **several}
    store.write_pending_delete(None)
    assert store.read_pending_delete() is None
