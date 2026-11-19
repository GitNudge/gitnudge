"""Configuration management for GitNudge."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

import tomli_w  # noqa: E402, I001

from gitnudge.logging_utils import get_logger

log = get_logger(__name__)


DEFAULT_MODEL = "claude-sonnet-5-5"
RETIRED_MODELS = frozenset({
    "claude-sonnet-4-20250514",
    "claude-opus-4-20250514",
    "claude-opus-4-1-20250805",
    "claude-3-haiku-20240307",
})
CONFIG_DIR = Path.home() / ".config" / "gitnudge"
CONFIG_FILE = CONFIG_DIR / "config.toml"

VALID_VERBOSITY = ("quiet", "normal", "verbose")


def default_config_path() -> Path:
    """Return the config path, honouring GITNUDGE_CONFIG."""
    env_path = os.environ.get("GITNUDGE_CONFIG", "").strip()
    return Path(env_path).expanduser() if env_path else CONFIG_FILE


class APIConfig(BaseModel):
    """API configuration settings."""

    model_config = ConfigDict(validate_assignment=True, extra="ignore")

    api_key: str = ""
    model: str = DEFAULT_MODEL
    max_tokens: int = Field(default=16000, ge=1, le=200_000)

    @field_validator("api_key")
    @classmethod
    def _strip_key(cls, v: str) -> str:
        return (v or "").strip()

    @field_validator("model")
    @classmethod
    def _validate_model(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("model must not be empty")
        return v

    def to_dict(self) -> dict[str, Any]:
        return {
            "api_key": self.api_key,
            "model": self.model,
            "max_tokens": self.max_tokens,
        }


class BehaviorConfig(BaseModel):
    """Behavior configuration settings."""

    model_config = ConfigDict(validate_assignment=True, extra="ignore")

    auto_stage: bool = True
    show_previews: bool = True
    max_context_lines: int = Field(default=500, ge=10, le=10_000)
    auto_resolve: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "auto_stage": self.auto_stage,
            "show_previews": self.show_previews,
            "max_context_lines": self.max_context_lines,
            "auto_resolve": self.auto_resolve,
        }


class UIConfig(BaseModel):
    """UI configuration settings."""

    model_config = ConfigDict(validate_assignment=True, extra="ignore")

    color: bool = True
    verbosity: str = "normal"

    @field_validator("verbosity")
    @classmethod
    def _validate_verbosity(cls, v: str) -> str:
        if v not in VALID_VERBOSITY:
            raise ValueError(
                f"Invalid verbosity level: {v}. Must be one of {VALID_VERBOSITY}"
            )
        return v

    def to_dict(self) -> dict[str, Any]:
        return {
            "color": self.color,
            "verbosity": self.verbosity,
        }


class Config(BaseModel):
    """Main configuration class for GitNudge."""

    model_config = ConfigDict(validate_assignment=True, extra="ignore")

    api: APIConfig = Field(default_factory=APIConfig)
    behavior: BehaviorConfig = Field(default_factory=BehaviorConfig)
    ui: UIConfig = Field(default_factory=UIConfig)

    @classmethod
    def load(cls, config_path: Path | None = None, apply_env: bool = True) -> Config:
        """Load configuration from file and (optionally) environment variables.

        Priority (highest to lowest):
        1. Environment variables (when apply_env is True)
        2. Config file
        3. Default values
        """
        if config_path is None:
            config_path = default_config_path()

        if config_path.exists():
            config = cls._load_from_file(config_path)
        else:
            config = cls()

        if apply_env:
            config = cls._apply_env_vars(config)
        return cls._replace_retired_model(config)

    @staticmethod
    def _replace_retired_model(config: Config) -> Config:
        """Swap a retired model ID for the current default."""
        if config.api.model in RETIRED_MODELS:
            log.warning(
                "Model %s is retired; using %s. Update it with "
                "'gitnudge config --model %s'.",
                config.api.model, DEFAULT_MODEL, DEFAULT_MODEL,
            )
            config.api.model = DEFAULT_MODEL
        return config

    @classmethod
    def _load_from_file(cls, path: Path) -> Config:
        """Load configuration from a TOML file."""
        try:
            with open(path, "rb") as f:
                data = tomllib.load(f)
        except (OSError, tomllib.TOMLDecodeError) as e:
            log.error("Failed to load config file %s: %s", path, e)
            raise ConfigError(f"Failed to load config file: {e}") from e

        try:
            return cls.model_validate(
                {
                    "api": data.get("api", {}),
                    "behavior": data.get("behavior", {}),
                    "ui": data.get("ui", {}),
                }
            )
        except Exception as e:
            log.error("Invalid config in %s: %s", path, e)
            raise ConfigError(f"Invalid configuration: {e}") from e

    @classmethod
    def _apply_env_vars(cls, config: Config) -> Config:
        """Apply environment variable overrides."""
        try:
            env_key = os.environ.get("ANTHROPIC_API_KEY")
            if env_key:
                config.api.api_key = env_key

            env_model = os.environ.get("GITNUDGE_MODEL")
            if env_model:
                config.api.model = env_model
        except ValidationError as e:
            log.error("Invalid environment override: %s", e.errors()[0].get("msg", e))
            raise ConfigError(
                f"Invalid environment variable value: {e.errors()[0].get('msg', e)}"
            ) from e

        if os.environ.get("GITNUDGE_NO_COLOR") or os.environ.get("NO_COLOR"):
            config.ui.color = False

        return config

    def save(self, config_path: Path | None = None) -> None:
        """Save configuration to file atomically with restricted permissions."""
        if config_path is None:
            config_path = default_config_path()

        config_path.parent.mkdir(parents=True, exist_ok=True)
        if config_path.parent == CONFIG_DIR:
            try:
                config_path.parent.chmod(0o700)
            except OSError:
                pass

        data = {
            "api": self.api.to_dict(),
            "behavior": self.behavior.to_dict(),
            "ui": self.ui.to_dict(),
        }

        if not data["api"]["api_key"]:
            del data["api"]["api_key"]

        fd, tmp_path = tempfile.mkstemp(
            prefix=".config.", suffix=".tmp", dir=str(config_path.parent)
        )
        try:
            with os.fdopen(fd, "wb") as f:
                tomli_w.dump(data, f)
            os.chmod(tmp_path, 0o600)
            os.replace(tmp_path, config_path)
            log.debug("Saved config to %s", config_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def to_dict(self) -> dict[str, Any]:
        """Convert config to dictionary."""
        return {
            "api": self.api.to_dict(),
            "behavior": self.behavior.to_dict(),
            "ui": self.ui.to_dict(),
        }

    def validate(self) -> list[str]:  # type: ignore[override]
        """Validate configuration and return list of errors."""
        errors = []

        if not self.api.api_key:
            errors.append(
                "API key is not set. Set ANTHROPIC_API_KEY or run 'gitnudge config --set-key'"
            )

        if self.ui.verbosity not in VALID_VERBOSITY:
            errors.append(f"Invalid verbosity level: {self.ui.verbosity}")

        if self.behavior.max_context_lines < 10:
            errors.append("max_context_lines must be at least 10")

        return errors


class ConfigError(Exception):
    """Configuration error."""
    pass
