"""A helper that already exists twice must not be written a third time.

Measured on one real repository: a function named `_now` existed in 22 separate
modules, `_now_iso` in 10, `_slug` in 7. The charter said "search before adding
a helper". Nothing checked, so nobody searched.
"""

from __future__ import annotations

import re
from pathlib import Path

from git_ctx import Context
from kit_config import Config

# Module-level defs only (column 0). A method (`    def add(self)`) or a nested
# function is not a helper anyone could import, so it is neither a new copy nor
# an existing owner. Unanchored, the check flagged a new method named `add`
# because three other classes have one (found wiring the local gate).
NEW_DEF = re.compile(r"^(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(")
EXISTING_DEF = re.compile(r"^(?:async\s+)?def\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", re.MULTILINE)

# Names that are supposed to repeat: framework hooks and entry points.
ALLOWED = {
    "main", "run", "setup", "teardown", "__init__", "handler",
    "forward", "get", "post", "put", "delete", "patch",
}

SHARED_HINT = ("shared", "common", "util", "utils", "lib")


def _in_shared_module(path: str) -> bool:
    return any(part in path.lower() for part in SHARED_HINT)


def _lane(path: str) -> str:
    """The top-level folder a file lives in ("" for a file at the repo root)."""
    return path.split("/", 1)[0] if "/" in path else ""


def _existing_owners(repo_root: Path, name: str, skip: set[str], lane: str | None = None) -> list[str]:
    """Modules that already define `name` at module level.

    With `lane`, only modules in the same top-level folder count: a copy the new
    file cannot import (a standalone script in scripts/ cannot import from
    backend/app/) is a different function that shares a name, not an owner.
    Without it, a branch adding gate scripts named `classify` or `judge` was
    told to import unrelated app functions (found wiring the local gate).
    """
    owners = []
    for source in repo_root.rglob("*.py"):
        rel = str(source.relative_to(repo_root))
        if rel in skip or "/.git/" in f"/{rel}" or "test" in rel.lower():
            continue
        if lane is not None and _lane(rel) != lane:
            continue
        try:
            text = source.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if any(found == name for found in EXISTING_DEF.findall(text)):
            owners.append(rel)
        if len(owners) > 3:
            break
    return owners


def run(ctx: Context, config: Config | None = None, threshold: int = 2) -> list[str]:
    """Flag a newly added def whose name already lives in `threshold`+ modules.

    `config` adds the project's own entry-point names
    (`limits.helper_names_allowed`) to ALLOWED; the kit keeps only the
    generic ones here.
    """
    allowed = ALLOWED | set(config.helper_names_allowed if config else [])
    problems = []
    changed = set(ctx.paths())
    for change in ctx.changes:
        if not change.path.endswith(".py") or _in_shared_module(change.path):
            continue
        # Test files are never owners (see _existing_owners), so they are not
        # subjects either: a test's `_run` wrapper is not a third copy of an
        # app helper. Found wiring the local gate.
        if "test" in change.path.lower():
            continue
        for line in change.added_lines:
            match = NEW_DEF.match(line)
            if not match:
                continue
            name = match.group(1)
            if name in allowed or name.startswith("test_"):
                continue
            owners = _existing_owners(ctx.repo_root, name, skip=changed, lane=_lane(change.path))
            if len(owners) >= threshold:
                where = ", ".join(owners[:3])
                problems.append(
                    f"{change.path} adds '{name}', which already exists in "
                    f"{len(owners)}+ modules ({where}). Import the existing one, "
                    "or move it to a shared module — do not write a third copy."
                )
    return problems
