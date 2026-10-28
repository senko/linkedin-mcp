from pathlib import Path

import pytest

from linkedin_mcp.config import DEFAULT_CACHE_TTL, DEFAULT_TIMEOUT, Settings, load_settings
from linkedin_mcp.errors import ConfigurationError


@pytest.fixture
def env_file(tmp_path: Path) -> Path:
    path = tmp_path / ".env"
    path.write_text(
        "LINKEDIN_CLIENT_ID=ignored\nLINKEDIN_ACCESS_TOKEN=file-token\nLINKEDIN_CACHE_TTL=60\n"
    )
    return path


def test_loads_settings_from_env_file(env_file: Path) -> None:
    settings = load_settings(env_file, environ={})

    assert settings == Settings(access_token="file-token", cache_ttl=60.0, timeout=DEFAULT_TIMEOUT)


def test_environment_overrides_env_file(env_file: Path) -> None:
    settings = load_settings(
        env_file, environ={"LINKEDIN_ACCESS_TOKEN": "env-token", "LINKEDIN_TIMEOUT": "5"}
    )

    assert settings.access_token == "env-token"
    assert settings.cache_ttl == 60.0
    assert settings.timeout == 5.0


def test_missing_env_file_is_not_an_error(tmp_path: Path) -> None:
    settings = load_settings(tmp_path / "missing.env", environ={"LINKEDIN_ACCESS_TOKEN": "t"})

    assert settings.access_token == "t"
    assert settings.cache_ttl == DEFAULT_CACHE_TTL


def test_env_file_can_be_disabled(env_file: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(env_file.parent)

    with pytest.raises(ConfigurationError):
        load_settings(None, environ={})


def test_uses_process_environment_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LINKEDIN_ACCESS_TOKEN", "process-token")

    assert load_settings(None).access_token == "process-token"


@pytest.mark.parametrize("token", ["", "   "])
def test_missing_token_raises(token: str) -> None:
    with pytest.raises(ConfigurationError, match="token-generator"):
        load_settings(None, environ={"LINKEDIN_ACCESS_TOKEN": token})


def test_empty_numeric_setting_uses_default() -> None:
    settings = load_settings(None, environ={"LINKEDIN_ACCESS_TOKEN": "t", "LINKEDIN_CACHE_TTL": ""})

    assert settings.cache_ttl == DEFAULT_CACHE_TTL


def test_zero_cache_ttl_is_allowed() -> None:
    settings = load_settings(
        None, environ={"LINKEDIN_ACCESS_TOKEN": "t", "LINKEDIN_CACHE_TTL": "0"}
    )

    assert settings.cache_ttl == 0


@pytest.mark.parametrize(
    ("value", "message"), [("soon", "must be a number"), ("-1", "must not be negative")]
)
def test_invalid_numeric_setting_raises(value: str, message: str) -> None:
    with pytest.raises(ConfigurationError, match=message):
        load_settings(None, environ={"LINKEDIN_ACCESS_TOKEN": "t", "LINKEDIN_CACHE_TTL": value})


def test_settings_repr_hides_token() -> None:
    assert "secret" not in repr(Settings(access_token="secret"))
