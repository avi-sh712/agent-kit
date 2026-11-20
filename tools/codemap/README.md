# codemap

A small, self-contained tool that lists the places that read or write the data a design touches, so the
drafter sees them before the first review round. This folder holds the storage layer only:
the config loader, the full map kept in a cache folder, and the small summary file that goes in git.
There is no command line, no finder, no Serena, no embedder and no AI call yet.

## Status: early
- You cannot run it on your code yet. It is a library with tests.
- `rebuild_command` and `remake_command` return shell text that ends in a `python3 -m codemap map` call. That
  command is not in this folder, so that part cannot run yet.
- The map header has `serena`, `index` and `model` fields, so a later finder can record which search source answered.
  Nothing here calls Serena, an embedder or an AI model.
- Tested on Linux only. The code uses `fcntl`, and the tests run `git`, `bash`, `tar` and `mv -T`.
- Some comments and test names carry scenario, rule and step numbers from a design document that is not public.

## What it keeps
- **Full map** (cache only, never in git): one tab-separated file per map, named by its own sha256, under
  `<cache_root>/<repo_id>/maps/<KEY>/`. First line is the header, then one row per line. Nine fields per row:
  `hop`, `kind`, `file:line`, `relation`, `function`, `seed`, `source`, `verdict`, `snippet`.
  Status rows (`no-hit:`, `too-many:`, `source-down:`, `source-partial:`, `ai-unavailable:`, `cap-hit:`,
  `kept-by-stale:`, `s3-more:`) put their text in `kind` and `-` in the fields that do not apply.
- **Summary** (small, goes in git next to the design): counts, the four shas, the rebuild inputs, the list of kept
  files, status lines and every human decision line. It holds no code text. Decision lines are never dropped; a
  line whose code is gone is marked `stale` (written as `decision stale <verdict> ...`).
- A map is `partial` when a search source (s1, s1w, s2, s3) was down or only partly answered. A partial map or
  summary is never used in place of a healthy one.

## Library use
```python
import sys
sys.path.insert(0, "<repo>/tools")
import codemap
cfg = codemap.load_config(config_path, repo=repo_path)
text = codemap.write_map(header, rows, names)
header, rows = codemap.read_map(text)
summary = codemap.write_summary(header, rows, key, inputs, old_summary=None)
codemap.commit(cache_dir, key, text, summary_path, summary)
path, reasons = codemap.find_cache_map(cache_dir, summary, rebuild_cmd)
```
Every refusal is a `ValueError` with the exact message and nothing is written.

## Rules the code keeps
- Stdlib only. The tool knows no repository names: every name comes from the config file in `configs/`.
- Caps: a map holds at most 8,000 rows and 1 MiB; a summary at most 400 lines and 65,536 bytes. Over a cap the
  write is refused. Nothing is ever cut.
- Writes are temp file plus rename. A summary and the map it names are written under one lock file, map first.
- `tool_tree()` is git's tree sha of this folder, computed without git. A rebuild must run from that exact tree.

## Config keys
`repo_id`, `roots`, `exclude`, `name_filter`, `kinds`, `query_key_companions`, `concept_queries`, `embedder`,
`prices`, `api_key_env`, `default_model`, `cache_root` (default `~/.cache/codemap`), `ledger_root` (default
`~/.local/state/codemap/<repo_id>`, never inside `cache_root`). A `cache_root` inside the repo must end in `cache`.

`configs/example.json` is a starting point with made-up values. Copy it and edit it. `load_config` checks that every
key is there. This folder uses the values of `repo_id`, `cache_root` and `ledger_root` only; the other keys are for
parts that are not here yet.

## Tests
`python3 -m pytest tools/codemap/tests -q --noconftest -p no:cacheprovider -o addopts=` (the package has its own
`pytest.ini`). Tests run git only in fixture repos under a temp folder.

## Requirements
`requirements.txt` holds no package on purpose: the core needs nothing but Python. The tests need pytest.
`requirements-judge.txt` pins the SDK for an AI step that is not in this folder. No code here imports it.
