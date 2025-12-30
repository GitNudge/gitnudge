"""Configuration management for GitNudge."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

import tomli_w  # noqa: E402, I001


DEFAULT_MODEL = "claude-sonnet-4-20250514"
CONFIG_DIR = Path.home() / ".config" / "gitnudge"
CONFIG_FILE = CONFIG_DIR / "config.toml"


@dataclass
class APIConfig:
    """API configuration settings."""

    api_key: str = ""
    model: str = DEFAULT_MODEL
    max_tokens: int = 4096

    def to_dict(self) -> dict[str, Any]:
        return {
            "api_key": self.api_key,
            "model": self.model,
            "max_tokens": self.max_tokens,
        }


@dataclass
class BehaviorConfig:
    """Behavior configuration settings."""

    auto_stage: bool = True
    show_previews: bool = True
    max_context_lines: int = 500
    auto_resolve: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "auto_stage": self.auto_stage,
            "show_previews": self.show_previews,
            "max_context_lines": self.max_context_lines,
            "auto_resolve": self.auto_resolve,
        }


@dataclass
class UIConfig:
    """UI configuration settings."""

    color: bool = True
    verbosity: str = "normal"

    def to_dict(self) -> dict[str, Any]:
        return {
            "color": self.color,
            "verbosity": self.verbosity,
        }


@dataclass
class Config:
    """Main configuration class for GitNudge."""

    api: APIConfig = field(default_factory=APIConfig)
    behavior: BehaviorConfig = field(default_factory=BehaviorConfig)
    ui: UIConfig = field(default_factory=UIConfig)

    @classmethod
    def load(cls, config_path: Path | None = None) -> Config:
        """Load configuration from file and environment variables.

        Priority (highest to lowest):
        1. Environment variables
        2. Config file
        3. Default values
        """
        config = cls()

        if config_path is None:
            config_path = Path(os.environ.get("GITNUDGE_CONFIG", CONFIG_FILE))

        if config_path.exists():
            config = cls._load_from_file(config_path)

        config = cls._apply_env_vars(config)

        return config

    @classmethod
    def _load_from_file(cls, path: Path) -> Config:
        """Load configuration from a TOML file."""
        try:
            with open(path, "rb") as f:
                data = tomllib.load(f)
        except (OSError, tomllib.TOMLDecodeError) as e:
            raise ConfigError(f"Failed to load config file: {e}") from e

        config = cls()

        if "api" in data:
            api_data = data["api"]
            config.api.api_key = api_data.get("api_key", "")
            config.api.model = api_data.get("model", DEFAULT_MODEL)
            config.api.max_tokens = api_data.get("max_tokens", 4096)

        if "behavior" in data:
            beh_data = data["behavior"]
            config.behavior.auto_stage = beh_data.get("auto_stage", True)
            config.behavior.show_previews = beh_data.get("show_previews", True)
            config.behavior.max_context_lines = beh_data.get("max_context_lines", 500)
            config.behavior.auto_resolve = beh_data.get("auto_resolve", False)

        if "ui" in data:
            ui_data = data["ui"]
            config.ui.color = ui_data.get("color", True)
            config.ui.verbosity = ui_data.get("verbosity", "normal")

        return config

    @classmethod
    def _apply_env_vars(cls, config: Config) -> Config:
        """Apply environment variable overrides."""
        env_key = os.environ.get("ANTHROPIC_API_KEY")
        if env_key:
            config.api.api_key = env_key

        env_model = os.environ.get("GITNUDGE_MODEL")
        if env_model:
            config.api.model = env_model

        if os.environ.get("GITNUDGE_NO_COLOR") or os.environ.get("NO_COLOR"):
            config.ui.color = False

        return config

    def save(self, config_path: Path | None = None) -> None:
        """Save configuration to file."""
        if config_path is None:
            config_path = CONFIG_FILE

        config_path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "api": self.api.to_dict(),
            "behavior": self.behavior.to_dict(),
            "ui": self.ui.to_dict(),
        }

        if not data["api"]["api_key"]:
            del data["api"]["api_key"]

        with open(config_path, "wb") as f:
            tomli_w.dump(data, f)

        config_path.chmod(0o600)

    def to_dict(self) -> dict[str, Any]:
        """Convert config to dictionary."""
        return {
            "api": self.api.to_dict(),
            "behavior": self.behavior.to_dict(),
            "ui": self.ui.to_dict(),
        }

    def validate(self) -> list[str]:
        """Validate configuration and return list of errors."""
        errors = []

        if not self.api.api_key:
            errors.append(
                "API key is not set. Set ANTHROPIC_API_KEY or run 'gitnudge config --set-key'"
            )

        if self.ui.verbosity not in ("quiet", "normal", "verbose"):
            errors.append(f"Invalid verbosity level: {self.ui.verbosity}")

        if self.behavior.max_context_lines < 10:
            errors.append("max_context_lines must be at least 10")

        return errors


class ConfigError(Exception):
    """Configuration error."""
    pass
