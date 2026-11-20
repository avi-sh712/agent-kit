# Code-search tools to run next to the kit

The kit's roles tell an agent to check a claim about the code before stating
it. Two outside tools make that check cheaper on a large codebase. Neither is
part of this repository, each has its own licence, and the kit works without
them.

| Tool | What it gives the agent | Where it keeps its files |
|---|---|---|
| [Serena](https://github.com/oraios/serena) | Looks up and edits code by symbol, through a local MCP server | `~/.serena/`, plus `.serena/` in your repository |
| [graphify](https://github.com/Graphify-Labs/graphify) | A graph of your code to query before grepping | `graphify-out/` in your repository, plus a skill under `~/.claude/` |

Everything below was run on Linux with Serena 2.1.0 and graphify 0.9.113, both
installed with [uv](https://docs.astral.sh/uv/), in throwaway folders. It is
what we saw, not a full guide. Each tool's own docs go further.

## Serena

```bash
uv tool install -p 3.13 serena-agent
serena init
```

Then, from the root of your repository:

```bash
claude mcp add serena -- serena start-mcp-server --context claude-code --project "$(pwd)"
```

What we saw:

- `serena init` wrote `~/.serena/serena_config.yml`.
- `claude mcp add` saved the server under this project in your own
  `~/.claude.json`. It added no file to the repository, so it is set per
  person and not shared through git.
- The first start of the server added `.serena/project.yml` and
  `.serena/.gitignore` to the repository.
- The server answered the MCP handshake and offered two tools:
  `initial_instructions` and `serena_repl`.

What we did not test:

- A full Claude Code session that uses Serena. Serena's docs say to confirm
  the connection with `/mcp` inside Claude Code.
- The dashboard. We started the server with
  `--enable-web-dashboard False --open-web-dashboard False`.

## graphify

The package on PyPI is `graphifyy`, with two y's. The command is `graphify`.

```bash
uv tool install graphifyy
graphify install
```

Then, from the root of your repository:

```bash
graphify update .
graphify claude install
```

What we saw:

- `graphify install` put a skill in `~/.claude/skills/graphify/` and created
  `~/.claude/CLAUDE.md`.
- `graphify update .` built the graph from code alone, with no AI key set, and
  wrote it to `graphify-out/`.
- `graphify query "what calls helper"` and `graphify explain "helper"`
  answered from that graph.
- `graphify claude install` wrote a `CLAUDE.md` section in the repository and
  hooks in `.claude/settings.json`.

What we did not test:

- A home folder or a repository that already has a `CLAUDE.md` or a
  `.claude/settings.json`. Ours had neither, so we did not see how graphify
  merges with existing files. Back yours up first.
- A full Claude Code session that uses the graph.

### One clash with the kit

`graphify-out/graph.html` came to 476 lines for a two-file repository. If you
commit `graphify-out/`, the kit's `file-growth` check fails on it:

```
[FAIL] file-growth
        - graphify-out/graph.html is a NEW file of 476 lines, over the 300-line limit. Split it before committing.
```

Add the folder to the exemptions in `project.yml`, and the check passes:

```yaml
limits:
  file_size_exempt:
    - "graphify-out/*"
```

Or keep `graphify-out/` out of git.

## codemap

`tools/codemap/` in this repository is our own code, and it is not ready to
use. It holds the storage layer of a tool that will list the places that read
or write the data a design touches. There is no command to run yet. Its 49
tests pass, and [its README](tools/codemap/README.md) says what is and is not
there.
