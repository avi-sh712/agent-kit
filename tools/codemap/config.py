"""Config loader, the tool's own git tree hash, and the rebuild checks. Stdlib only.
summary.py was over its 220 lines, so rebuild_refusal, rebuild_command and remake_command live here (config imports summary).
"""
import hashlib
import json
import os
import shlex
import subprocess
import sys

from .summary import parse_summary

REQUIRED = ("repo_id", "roots", "exclude", "name_filter", "kinds", "query_key_companions", "concept_queries",
            "embedder", "prices", "api_key_env", "default_model")
NESTED = {"name_filter": ("min_len", "stoplist"), "prices": ("file", "variable"),
          "kinds": ("mcp_tool_decorators", "task_decorators", "export_path_words", "export_calls", "cache_words",
                    "pool_prefixes", "skill_md_glob"),
          "embedder": ("url", "key_header", "key_env", "max_texts", "max_chars", "batch", "model_revision", "probe_text")}


def _inside(path, folder):
    path, folder = os.path.realpath(path), os.path.realpath(folder)
    return path == folder or path.startswith(folder.rstrip(os.sep) + os.sep)


def load_config(path, repo=None):
    """Read the JSON config; a missing key is a ValueError naming it. `repo` turns on the cache-inside-repo check."""
    try:
        with open(path, encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, ValueError) as e:
        raise ValueError(f"config {path} cannot be read ({type(e).__name__})") from None
    if not isinstance(cfg, dict):
        raise ValueError(f"config {path} is not a JSON object")
    for key in REQUIRED:
        if key not in cfg:
            raise ValueError(f"config is missing the key {key}")
        for sub in NESTED.get(key, ()):
            if sub not in cfg[key]:
                raise ValueError(f"config is missing the key {key}.{sub}")
    cache = os.path.abspath(os.path.expanduser(cfg.get("cache_root", "~/.cache/codemap")))
    ledger = os.path.abspath(os.path.expanduser(cfg.get("ledger_root", f"~/.local/state/codemap/{cfg['repo_id']}")))
    if _inside(ledger, cache):
        raise ValueError(f"ledger_root {ledger} is inside cache_root {cache}; the ledger must survive a cache wipe")
    if repo is not None and _inside(cache, repo) and os.path.basename(cache.rstrip(os.sep)) != "cache":
        raise ValueError(f"cache_root {cache} is inside the repo {repo} and its last part is not 'cache'")
    return {**cfg, "cache_root": cache, "ledger_root": ledger}


def python_minor():
    v = sys.version_info
    return f"{v[0]}.{v[1]}"


def _obj(kind, data):
    return hashlib.sha1(kind + b" %d\0" % len(data) + data, usedforsecurity=False)


def _tree(path):
    ents = []
    for e in os.scandir(path):
        if e.name == "__pycache__" or e.name.endswith(".pyc"):
            continue
        if e.is_symlink():
            mode, sha = b"120000", _obj(b"blob", os.readlink(e.path).encode()).digest()
        elif e.is_dir(follow_symlinks=False):
            sub = _tree(e.path)
            if sub is None:
                continue
            mode, sha = b"40000", sub
        elif e.is_file(follow_symlinks=False):
            with open(e.path, "rb") as f:
                mode, sha = (b"100755" if e.stat().st_mode & 0o100 else b"100644"), _obj(b"blob", f.read()).digest()
        else:
            continue
        name = e.name.encode()
        ents.append((name + (b"/" if mode == b"40000" else b""), name, mode, sha))
    if not ents:
        return None
    return _obj(b"tree", b"".join(m + b" " + n + b"\0" + s for _, n, m, s in sorted(ents))).digest()


def tool_tree(package_dir):
    """Git's tree-object sha of the package folder, in pure Python; skips __pycache__/ and *.pyc only."""
    sub = _tree(package_dir)
    return sub.hex() if sub else _obj(b"tree", b"").hexdigest()


def _git(cwd, *args):
    try:
        return subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise ValueError(f"CANNOT LOOK: git did not answer ({type(e).__name__})") from None


def tool_tree_dirty(package_dir):
    """True when git sees a change or an ignored file other than __pycache__/ and *.pyc. Work tree from the package path."""
    pkg = os.path.realpath(package_dir)
    top = _git(pkg, "rev-parse", "--show-toplevel")
    if top.returncode != 0:
        return False
    st = _git(top.stdout.strip(), "status", "--porcelain", "--ignored", "--untracked-files=all", "--", pkg)  # beats showUntrackedFiles=no
    if st.returncode != 0:
        raise ValueError("CANNOT LOOK: git status failed")
    return any(not (ln[:3] == "!! " and ("__pycache__" in ln[3:].strip('"').split("/") or ln.rstrip('"').endswith(".pyc")))
               for ln in st.stdout.splitlines())


def remake_command(summary_text, summary_path):
    s, q = parse_summary(summary_text), shlex.quote
    wide = f" --wide {q(s['wide'])}" if s["wide"] not in ("", "-") else ""
    inv = " --inventory" if s["inventory"] == "yes" else ""
    return (f"PYTHONPATH=tools python3 -m codemap map --repo . --config {q(s['config'])} --ref {s['ref']} "
            f"--names {q(s['names'])}{wide}{inv} --prev {q(summary_path)} --summary {q(summary_path)}")


def rebuild_command(summary_text, *, repo, cache_dir, summary_path, scratch_path):
    """Line 1 exports the pinned tool tree (safe for two at once); line 2 runs the rebuild from it."""
    s, q = parse_summary(summary_text), shlex.quote
    t = f"{cache_dir}/tool-{s['tool_tree'][:12]}"
    export = ("set -o pipefail; [ -d @T@/codemap ] || { mkdir -p @TMP@ && { git -C @REPO@ archive --prefix=codemap/ @TREE@ "
              "| tar -x -C @TMP@; } && { mv -T @TMP@ @T@ || rm -rf @TMP@; } || rm -rf @TMP@; }")
    for old, new in (("@TMP@", q(t) + ".tmp-$$"), ("@T@", q(t)), ("@REPO@", q(repo)), ("@TREE@", s["tool_tree"])):
        export = export.replace(old, new)
    return export + "\n" + (f"PYTHONPATH={q(t)} python3 -m codemap map --repo {q(repo)} "
                            f"--config {q(t)}/codemap/configs/{q(os.path.basename(s['config']))} --from-summary {q(summary_path)} "
                            f"--no-judge --summary {q(scratch_path)}")


def rebuild_refusal(summary_text, *, summary_path, repo, cache_dir, scratch_path, python, config_sha256,
                    serena=None, index=None, tool_tree=None, dirty=False):
    """The first reason a rebuild must not start (M1, M6, M7, config, M4, M5), or None. Runs before any source."""
    s = parse_summary(summary_text)
    remake = remake_command(summary_text, summary_path)
    if s["health"] != "ok":
        return f"map summary is partial ({s['health'].removeprefix('partial:')}); re-make it where every source answers: {remake}"
    if dirty:
        return "tool tree is dirty"
    if tool_tree is not None and tool_tree != s["tool_tree"]:
        return f"tool tree {tool_tree[:12]} differs from the summary {s['tool_tree'][:12]}; run the printed rebuild command"
    if python != s["python"]:
        return f"python {python} is not the summary's python={s['python']}; run the rebuild with python {s['python']}"
    if config_sha256 != s["config_sha256"]:
        return (f"config sha256 {config_sha256} is not the summary's config_sha256={s['config_sha256']}; "
                "run the printed rebuild command")
    if serena is not None and serena != s["serena"]:
        return f"Serena {serena} is not the summary's serena={s['serena']}; rebuild where Serena {s['serena']} runs, or re-make: {remake}"
    if index is not None and index != s["index"]:
        return f"embedder index {index} is not the summary's index={s['index']}; rebuild where index {s['index']} runs, or re-make: {remake}"
    return None
