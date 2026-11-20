"""Load project.yml and answer questions about it.

Every check script and every agent instruction reads its settings from here, so
the rest of the kit contains no project names, paths or commands.

Design rule: a missing value is NEVER silently defaulted into something that
might run. `require()` raises, the caller reports NOT RUN with the reason. This
is the whole point of the kit — an agent must not run a wrong command and then
report success.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

CONFIG_NAME = "project.yml"


class ConfigError(RuntimeError):
    """Raised when a required setting is absent. Message names the key."""


def _find_config(start: Path | None = None) -> Path:
    """Walk up from `start` looking for agent-kit/project.yml."""
    here = (start or Path(__file__).resolve().parent).resolve()
    # Both supported layouts: the kit nested under .claude/, and the kit copied
    # to the repository root. Missing the second one made every check report
    # "misconfigured" for a correctly installed kit.
    relatives = (
        Path(CONFIG_NAME),
        Path("agent-kit") / CONFIG_NAME,
        Path(".claude") / "agent-kit" / CONFIG_NAME,
    )
    for directory in [here, *here.parents]:
        for relative in relatives:
            candidate = directory / relative
            if candidate.is_file():
                return candidate
    raise ConfigError(
        f"{CONFIG_NAME} not found. Copy project.example.yml to {CONFIG_NAME} "
        "and fill it in before running any check."
    )


def _parse(text: str) -> dict[str, Any]:
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - environment specific
        raise ConfigError(
            "PyYAML is required to read project.yml (pip install pyyaml)."
        ) from exc
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ConfigError(f"{CONFIG_NAME} must contain a mapping at the top level.")
    return data


class Config:
    """Read-only view of project.yml with dotted-path lookup."""

    def __init__(self, data: dict[str, Any], path: Path) -> None:
        self._data = data
        self.path = path

    @classmethod
    def load(cls, start: Path | None = None) -> "Config":
        override = os.environ.get("AGENT_KIT_CONFIG")
        path = Path(override).resolve() if override else _find_config(start)
        if not path.is_file():
            raise ConfigError(f"Config file does not exist: {path}")
        return cls(_parse(path.read_text(encoding="utf-8")), path)

    def get(self, dotted: str, default: Any = None) -> Any:
        """Return a value, or `default` when absent or explicitly null."""
        node: Any = self._data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return default if node is None else node

    def require(self, dotted: str) -> Any:
        """Return a value, or raise naming the key the operator must fill in."""
        value = self.get(dotted)
        if value is None or value == "":
            raise ConfigError(
                f"'{dotted}' is not set in {self.path}. "
                "Fill it in, or the agent must report NOT RUN for this step."
            )
        return value

    def command(self, name: str, area: str | None = None) -> str:
        """Return a runnable command string from the `commands:` block.

        `{area}` is replaced with the path the agent touched. Raises when the
        command is not configured, so the agent says NOT RUN rather than
        substituting a command from another project.
        """
        template = self.require(f"commands.{name}")
        if "{area}" in template:
            template = template.replace("{area}", area or ".")
        return template

    def has_command(self, name: str) -> bool:
        return self.get(f"commands.{name}") is not None

    @property
    def max_file_lines(self) -> int:
        return int(self.get("limits.max_file_lines", 300))

    @property
    def file_size_exempt(self) -> list[str]:
        patterns = self.get("limits.file_size_exempt", []) or []
        return [str(p) for p in patterns]

    @property
    def helper_names_allowed(self) -> list[str]:
        """Entry-point names the duplicate-helpers check must not count."""
        names = self.get("limits.helper_names_allowed", []) or []
        return [str(n) for n in names]

    @property
    def ticket_pattern(self) -> str:
        return str(self.require("tracker.ticket_pattern"))

    @property
    def protected_main(self) -> bool:
        return bool(self.get("branches.protected", True))

    @property
    def main_branch(self) -> str:
        return str(self.get("branches.main", "main"))


def load(start: Path | None = None) -> Config:
    return Config.load(start)
