# Agent kit — a reusable architect/executor/reviewer/retro setup

Four agent roles, one core charter, a set of checks that enforce it, and a loop
that turns mistakes into new checks. **Everything project-specific lives in one
file**, so dropping this into a new codebase is a copy plus a config edit.

## Why it is shaped this way

It comes out of a measured audit of one real project running this pattern for six
weeks: 3,275 commits, 1,374 agent sessions, 1,114 tickets closed.

The finding that shaped everything here: **rules with a script behind them held;
rules written as prose did not.** The one rule with a check ran at 100%
compliance. The prose rules beside it ran at 58%, with 71 unreviewed commits on
the deploy branch and 90% of safety refusals worked around within three tool
calls. So in this kit, a rule that matters becomes a check, and the charter keeps
only what no script can express.

Second finding: **the author cannot grade their own work.** Self-review passed
94% of changes while the same author later recorded a miss on 21% of what they
had passed. Hence a reviewer role that never sees the plan.

## Install

1. Copy `agent-kit/` into the target repository's `.claude/` directory.
2. Copy `agent-kit/agents/*.md` into `.claude/agents/`.
3. `cp agent-kit/project.example.yml agent-kit/project.yml` and fill it in.
   Leave anything you do not have as `null` — the agents will report NOT RUN
   rather than invent a command.
4. Check it: `python3 agent-kit/checks/run_all.py --list`
5. Wire the checks into your pipeline and, optionally, a commit hook:
   `python3 agent-kit/checks/run_all.py --base origin/main --head HEAD`

Requires Python 3.10+ and PyYAML. Nothing else.

## What is in here

| Path | What it is |
|---|---|
| `project.yml` | **the only file you edit per project** |
| `charter-core.md` | rules true in any codebase (150-line budget) |
| `agents/architect.md` | designs and specs; never writes code |
| `agents/executor.md` | builds one spec in its own worktree |
| `agents/reviewer.md` | judges the diff cold, without the plan |
| `agents/retro.md` | weekly: turns mistakes into checks |
| `checks/` | the scripts that enforce the rules, with tests |
| `defects/` | the record the retro agent learns from |

## The rule this kit is built on

**A lesson is learned only when it is a check that can fail.** A note in memory
is a reminder; a script that turns a commit red is a learned lesson. Every
recorded mistake sits at one of four rungs — note, checklist, script, setting —
and a mistake that repeats gets promoted one rung. That is the whole loop.

## Adding a check

Write it beside the others, taking a `Context` and returning a list of problems.
Add its tests. Then break it on purpose and prove the tests go red, restore, and
prove green. Paste that into the pull request. A check whose tests cannot fail is
exactly the thing this kit exists to prevent, and it is not exempt from its own
rule.

## Running the kit's own tests

```
cd agent-kit/checks && python3 -m pytest tests/ -q
```
