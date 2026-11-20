# Contributing

Thank you for looking. This kit is small on purpose. It stays useful only if
every part of it keeps earning its place.

## Run the tests

```
python3 -m pip install pyyaml pytest
cd agent-kit/checks
python3 -m pytest tests/ -q
```

Each test builds its case by hand, so the suite needs no network and no setup.

## The one rule for a new check

A check must be able to fail. Before you open a pull request:

1. Write the check beside the others in `agent-kit/checks/`. It takes a
   `Context` and returns a list of problems. An empty list means it passed.
2. Register it in the `CHECKS` table in `agent-kit/checks/run_all.py`.
3. Add its tests to `agent-kit/checks/tests/`.
4. Break the check on purpose and watch its tests go red.
5. Restore it and watch them go green.
6. Paste both runs into the pull request.

A check whose tests cannot fail is the exact thing this kit exists to prevent,
and the kit is not exempt from its own rule.

## What belongs where

| You want to add | It goes in |
|---|---|
| A rule that is true in any codebase | `agent-kit/charter-core.md`, inside its 150-line budget |
| A rule a script can enforce | a check; then the sentence leaves the charter |
| A name, a path, a command or a tracker id | `agent-kit/project.example.yml`, as a key that defaults to `null` |
| Anything about one framework or one company | your own project's charter, not this repository |

## Keep pull requests small

One check per pull request, so each one can be judged, or rejected, on its own.

Commit messages use the same words the checks read:

- a commit that changes a test shows its failing run and says `RED`, or carries
  a line `Rule3-Exempt: <reason>`;
- a `docs`, `chore`, `style`, `ci`, `build` or `revert` commit needs no issue.
  Every other commit names its issue, or carries a line `No-Ticket: <reason>`.

## Reporting a problem

Open an issue. Say what you ran, what you expected, and what it printed.

The most useful report is a check that passed something it should have failed.

## Licence

By contributing you agree that your work is released under the MIT licence in
`LICENSE`.
