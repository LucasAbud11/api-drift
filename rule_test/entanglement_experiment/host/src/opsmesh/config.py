"""Application configuration loading for OpsMesh.

Configuration can come from environment variables or an optional YAML
file. Env vars always take precedence over file values, which is
convenient for overriding a couple of settings in CI without editing
the file.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from opsmesh.exceptions import ConfigError

_ENV_PREFIX = "OPSMESH_"


@dataclass
class UpstreamServerSpec:
    """A single upstream MCP server the orchestrator can talk to."""

    name: str
    url: str
    description: str = ""


@dataclass
class OpsMeshConfig:
    server_name: str = "opsmesh"
    log_level: str = "INFO"
    host: str = "0.0.0.0"
    port: int = 8765
    github_token: str | None = None
    pagerduty_token: str | None = None
    upstream_servers: list[UpstreamServerSpec] = field(default_factory=list)

    @classmethod
    def load(cls, path: str | Path | None = None) -> "OpsMeshConfig":
        data: dict[str, Any] = {}
        if path is not None:
            data = _load_yaml(Path(path))

        upstream = [
            UpstreamServerSpec(**entry) for entry in data.get("upstream_servers", [])
        ]

        return cls(
            server_name=_env("SERVER_NAME", data.get("server_name", "opsmesh")),
            log_level=_env("LOG_LEVEL", data.get("log_level", "INFO")),
            host=_env("HOST", data.get("host", "0.0.0.0")),
            port=int(_env("PORT", data.get("port", 8765))),
            github_token=_env("GITHUB_TOKEN", data.get("github_token")),
            pagerduty_token=_env("PAGERDUTY_TOKEN", data.get("pagerduty_token")),
            upstream_servers=upstream,
        )


def _env(key: str, default: Any = None) -> Any:
    return os.environ.get(_ENV_PREFIX + key, default)


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"config file not found: {path}")
    try:
        with path.open("r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {path}: {exc}") from exc
