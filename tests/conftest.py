from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app import timezone_state
from app.main import create_app
from app.settings import Secrets, load_config

TOKEN = "test-token-do-not-use-in-production"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture(autouse=True)
def isolated_timezone_state(tmp_path, monkeypatch):
    monkeypatch.setattr(timezone_state, "STATE_PATH", tmp_path / "data/estado.json")


@pytest.fixture
def config():
    return load_config()


@pytest.fixture
def client(config):
    app = create_app(config=config, secrets=Secrets(jarvis_token=TOKEN))
    with TestClient(app) as client:
        app.state.brain = SimpleNamespace(ask=AsyncMock(return_value="A su servicio, Dr. Valles."))
        app.state.briefing = SimpleNamespace(
            create=AsyncMock(return_value="Buenos días, Dr. Valles. Hoy no tiene pendientes.")
        )
        yield client
