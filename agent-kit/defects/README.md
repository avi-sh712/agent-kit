# Defect records — the input to the self-learning loop

One file per mistake, named `YYYY-MM-DD-short-slug.json`. The retro agent reads
everything added since its last run.

**What counts as a defect:** an error that reached production; a ticket that was
marked done and had to be reopened; a mistake an agent recorded about its own
work. All three are the same thing — a control that did not hold.

**What does not:** a test that failed and was fixed before commit. That is the
process working.

## Fields

| Field | Meaning |
|---|---|
| `date` | when it was noticed |
| `what_happened` | one or two plain sentences, no jargon |
| `rule_broken` | the rule that should have caught it, or "none — no rule existed" |
| `layer` | frontend / backend / database / security / process |
| `category` | root cause, from the list below |
| `would_have_caught_it` | the specific check that would have stopped it |
| `current_rung` | 1 note · 2 checklist · 3 script · 4 setting |
| `reference` | ticket id, commit, or error link |

## Categories

- `spec-wrong` — the spec stated something about the code or data that was false
- `test-inert` — a test or a deliberate break that could not have failed
- `tooling` — a tool lied: a silent exit code, a truncated read, a stale cache
- `merge-branch` — branch state, cherry-picks, or a merge that looked clean
- `review-shallow` — accepted a claim without checking it first-hand
- `fabricated-claim` — a number or state asserted that was never measured
- `env-drift` — a local environment difference mistaken for a code bug

Add a category only when nothing fits, and say why in the record.
