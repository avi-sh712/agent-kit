"""Rule 3 — a new test must be shown to FAIL when its feature is removed.

The commit that adds or changes a test has to carry the proof: the word RED
(the red run), or an explicit exemption naming why no break was possible.

Why this is a script and not a sentence in a charter: measured on one real
repository over six weeks, the prose version held on 58% of commits while the
one rule that had a script behind it held on 100%.
"""

from __future__ import annotations

import re

from git_ctx import Context

# Case-sensitive on purpose. Lowercase "red" appears inside credits, required,
# redis and rendered; the uppercase token does not.
RED_TOKEN = re.compile(r"\bRED\b")
EXEMPT = re.compile(r"^Rule3-Exempt:\s*\S+", re.MULTILINE)

TEST_MARKERS = ("test_", "_test.", ".test.", ".spec.", "/tests/", "/test/", "__tests__")
# Prose whose NAME happens to contain "test" is not a test: memory notes such
# as reference_backend_local_test_env.md were flagged when the local gate was
# first wired.
PROSE_SUFFIXES = (".md", ".txt", ".rst")


def touches_tests(path: str) -> bool:
    lowered = path.lower()
    if lowered.endswith(PROSE_SUFFIXES):
        return False
    return any(marker in lowered for marker in TEST_MARKERS)


def run(ctx: Context) -> list[str]:
    """Return a list of problems. Empty list means the check passed."""
    if ctx.is_merge:
        return []  # git's own merge message; each merged commit carried its RED
    test_files = [c.path for c in ctx.changes if touches_tests(c.path)]
    if not test_files:
        return []
    if EXEMPT.search(ctx.commit_message):
        return []
    if RED_TOKEN.search(ctx.commit_message):
        return []
    listed = ", ".join(sorted(test_files)[:5])
    more = "" if len(test_files) <= 5 else f" (+{len(test_files) - 5} more)"
    return [
        "Rule 3: this commit changes tests but shows no failing run. "
        f"Files: {listed}{more}. "
        "Break the code the test covers, paste the RED output into the commit "
        "message, restore it and confirm GREEN. If the behaviour genuinely "
        "cannot be broken, add a 'Rule3-Exempt: <reason>' line saying why."
    ]
