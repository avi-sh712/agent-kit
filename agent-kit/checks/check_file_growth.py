"""A file already over the size limit must not grow.

Existing large files are grandfathered, but only until someone touches them.
The moment a change lands in an oversized file, that change carries the split.

This is the shape that works: a hard rule on every file would block all work on
a legacy codebase, while a rule enforced only by a reviewer reading line counts
gets skipped about half the time.
"""

from __future__ import annotations

from fnmatch import fnmatch

from git_ctx import Context
from kit_config import Config

# Binary and generated files have no meaningful line count.
ALWAYS_EXEMPT = ("*.gen.ts", "*.gen.json", "*.lock", "*.snap", "*.svg", "*.min.*")


def _exempt(path: str, patterns: list[str]) -> bool:
    return any(fnmatch(path, p) for p in (*ALWAYS_EXEMPT, *patterns))


def run(ctx: Context, config: Config) -> list[str]:
    limit = config.max_file_lines
    exempt = config.file_size_exempt
    problems = []
    for change in ctx.changes:
        if _exempt(change.path, exempt):
            continue
        if change.lines_after <= limit:
            continue
        if not change.grew:
            continue  # already oversized, but this change did not make it worse
        if change.is_new:
            problems.append(
                f"{change.path} is a NEW file of {change.lines_after} lines, "
                f"over the {limit}-line limit. Split it before committing."
            )
        else:
            problems.append(
                f"{change.path} is {change.lines_after} lines "
                f"(was {change.lines_before}), over the {limit}-line limit and "
                "growing. Split it in its own commit first, then make the change."
            )
    return problems
