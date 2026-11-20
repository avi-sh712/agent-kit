"""Every behaviour-changing commit names its ticket, or says why it has none.

Untracked work is invisible work, and invisible work gets built twice.
"""

from __future__ import annotations

import re

from git_ctx import Context
from kit_config import Config

NO_TICKET = re.compile(r"^No-Ticket:\s*\S+", re.MULTILINE)
# Commit types that describe the code rather than change its behaviour.
EXEMPT_TYPES = ("docs", "chore", "style", "ci", "build", "revert", "merge")


def _subject_type(message: str) -> str:
    subject = message.strip().splitlines()[0] if message.strip() else ""
    match = re.match(r"^([a-z]+)(\([^)]*\))?!?:", subject)
    return match.group(1) if match else ""


def run(ctx: Context, config: Config) -> list[str]:
    if ctx.is_merge:
        return []  # git's own merge message; the merged commits carry the keys
    message = ctx.commit_message
    if _subject_type(message) in EXEMPT_TYPES:
        return []
    if NO_TICKET.search(message):
        return []
    if re.search(config.ticket_pattern, message):
        return []
    return [
        "No ticket named. Put the ticket id in the commit subject "
        f"(pattern {config.ticket_pattern!r}), or add a line "
        "'No-Ticket: <reason>' so the choice is on the record."
    ]
