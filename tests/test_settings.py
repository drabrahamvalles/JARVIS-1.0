from unittest.mock import patch

import pytest
import yaml
from pydantic import ValidationError

from app.__main__ import build_log_config, main
from app.settings import AppConfig, load_config, load_secrets, runtime_environment


def test_invalid_timezone_fails_early(config):
    with pytest.raises(ValidationError):
        AppConfig.model_validate({**config.model_dump(), "zona_horaria_por_defecto": "Bogus/Zone"})


def test_environment_overrides_dotenv_without_exposing_secrets(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text("OPENAI_API_KEY=local-secret\nJARVIS_TOKEN=local-token\n")
    monkeypatch.setenv("OPENAI_API_KEY", "provider-secret")
    monkeypatch.delenv("JARVIS_TOKEN", raising=False)
    result = load_secrets(path)
    assert result.openai_api_key == "provider-secret"
    assert result.jarvis_token == "local-token"
    assert "secret" not in repr(result) and "token" not in repr(result)
    assert runtime_environment(path)["OPENAI_API_KEY"] == "provider-secret"


@pytest.mark.parametrize(
    "env,host,port",
    [
        ({}, "127.0.0.1", 8000),
        ({"PORT": "", "HOST": ""}, "127.0.0.1", 8000),
        ({"PORT": "4567"}, "0.0.0.0", 4567),
        ({"PORT": "8001", "HOST": "127.0.0.1"}, "127.0.0.1", 8001),
    ],
)
def test_same_start_command_supports_mac_and_provider(env, host, port):
    with (
        patch("app.__main__.runtime_environment", return_value=env),
        patch("app.__main__.uvicorn.run") as run,
    ):
        main()
    assert run.call_args.kwargs["host"] == host
    assert run.call_args.kwargs["port"] == port
    assert run.call_args.kwargs["log_config"]["loggers"]["jarvis.usage"] == {
        "handlers": ["default"],
        "level": "INFO",
        "propagate": False,
    }


def test_usage_logger_is_visible_once_in_uvicorn():
    logger_config = build_log_config()["loggers"]["jarvis.usage"]
    assert logger_config["handlers"] == ["default"]
    assert logger_config["propagate"] is False


@pytest.mark.parametrize("port", ["invalid", "0", "65536"])
def test_invalid_port_does_not_start(port):
    with (
        patch("app.__main__.runtime_environment", return_value={"PORT": port}),
        pytest.raises(SystemExit),
    ):
        main()


def test_config_is_read_from_yaml(tmp_path, config):
    path = tmp_path / "config.yaml"
    contents = config.model_dump()
    contents["modelo_rapido"] = "otro-modelo"
    contents["precios_modelos"]["otro-modelo"] = contents["precios_modelos"]["gpt-6-luna"]
    path.write_text(yaml.safe_dump(contents))
    assert load_config(path).modelo_rapido == "otro-modelo"


def test_selected_models_require_pricing(config):
    contents = config.model_dump()
    contents["precios_modelos"].pop(config.modelo_profundo)
    with pytest.raises(ValidationError, match="Faltan precios"):
        AppConfig.model_validate(contents)


@pytest.mark.parametrize("value", ["9:00", "24:00", "09:60", "mañana"])
def test_default_reminder_time_requires_valid_hh_mm(config, value):
    with pytest.raises(ValidationError, match="HH:MM"):
        AppConfig.model_validate({**config.model_dump(), "hora_recordatorio_por_defecto": value})


def test_capture_model_requires_configured_pricing(config):
    contents = config.model_dump()
    contents["modelo_captura"] = "modelo-sin-precio"
    with pytest.raises(ValidationError, match="Faltan precios"):
        AppConfig.model_validate(contents)
