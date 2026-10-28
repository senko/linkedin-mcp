"""Settings loaded from environment variables and an optional `.env` file."""

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values

from linkedin_mcp.errors import TOKEN_GENERATOR_URL, ConfigurationError

DEFAULT_ENV_FILE = Path(".env")
DEFAULT_CACHE_TTL = 3600.0
DEFAULT_TIMEOUT = 30.0


@dataclass(frozen=True)
class Settings:
    """Runtime settings for the LinkedIn client and the MCP server.

    Attributes:
        access_token: OAuth 2.0 access token with the `r_dma_portability_self_serve` scope.
        cache_ttl: Seconds to keep fetched snapshot data in memory.
        timeout: HTTP request timeout in seconds.
    """

    access_token: str = field(repr=False)
    cache_ttl: float = DEFAULT_CACHE_TTL
    timeout: float = DEFAULT_TIMEOUT


def load_settings(
    env_file: Path | None = DEFAULT_ENV_FILE,
    environ: Mapping[str, str] | None = None,
) -> Settings:
    """Load settings from the environment, falling back to values in a `.env` file.

    Process environment variables take precedence over the `.env` file. A missing
    `.env` file is not an error.

    Args:
        env_file: Path to a `.env` file, or None to skip reading one.
        environ: Environment mapping to use instead of `os.environ` (for tests).

    Returns:
        The loaded settings.

    Raises:
        ConfigurationError: If the access token is missing or a numeric value is invalid.
    """
    values: dict[str, str] = {}
    if env_file is not None and env_file.is_file():
        values.update({k: v for k, v in dotenv_values(env_file).items() if v is not None})
    values.update(os.environ if environ is None else environ)

    access_token = values.get("LINKEDIN_ACCESS_TOKEN", "").strip()
    if not access_token:
        raise ConfigurationError(
            "LINKEDIN_ACCESS_TOKEN is not set. Generate a token with the "
            f"r_dma_portability_self_serve scope at {TOKEN_GENERATOR_URL}."
        )

    return Settings(
        access_token=access_token,
        cache_ttl=_non_negative_float(values, "LINKEDIN_CACHE_TTL", DEFAULT_CACHE_TTL),
        timeout=_non_negative_float(values, "LINKEDIN_TIMEOUT", DEFAULT_TIMEOUT),
    )


def _non_negative_float(values: Mapping[str, str], name: str, default: float) -> float:
    """Read a non-negative float setting.

    Args:
        values: Mapping of setting names to raw string values.
        name: Name of the setting to read.
        default: Value to use when the setting is absent or empty.

    Returns:
        The parsed value.

    Raises:
        ConfigurationError: If the value is not a non-negative number.
    """
    raw = values.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        raise ConfigurationError(f"{name} must be a number, got {raw!r}") from None
    if value < 0:
        raise ConfigurationError(f"{name} must not be negative, got {raw!r}")
    return value
