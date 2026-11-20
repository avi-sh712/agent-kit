"""Config rules, python_minor, the tool tree hash, and the fixture-repo helpers the other test files import."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from codemap import config

PKG = Path(__file__).resolve().parents[1]
REAL_CONFIG = PKG / "configs" / "example.json"
IDENT = ["-c", "user.name=codemap-test", "-c", "user.email=codemap-test@example.invalid", "-c", "commit.gpgsign=false"]
ENV = {**{k: v for k, v in os.environ.items() if not k.startswith("GIT_")}, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


def git(cwd, *args):
    """Git runs only in fixture repos under tmp_path (never the real checkout), with a fixed identity."""
    r = subprocess.run(["git", *IDENT, "-C", str(cwd), *args], capture_output=True, text=True, timeout=60, check=True, env=ENV)
    return r.stdout.strip()


def commit_all(repo):
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "fixture")


def make_repo(tmp_path, name="repo"):
    """A fixture git repo holding a copy of this package at tools/codemap, plus a gitignored __pycache__/x.pyc."""
    repo = tmp_path / name
    shutil.copytree(PKG, repo / "tools" / "codemap", ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"))
    (repo / ".gitignore").write_text("__pycache__/\n*.pyc\n")
    git(tmp_path, "init", "-q", "-b", "main", str(repo))
    pyc = repo / "tools" / "codemap" / "__pycache__" / "x.pyc"
    pyc.parent.mkdir()
    pyc.write_bytes(b"\0\1\2")
    commit_all(repo)
    return repo


def write_cfg(tmp_path, **changes):
    cfg = json.loads(REAL_CONFIG.read_text())
    cfg.update(changes)
    for k in [k for k, v in changes.items() if v is None]:
        del cfg[k]
    path = tmp_path / "cfg.json"
    path.write_text(json.dumps(cfg))
    return path


def test_real_config_loads_with_every_key():
    cfg = config.load_config(REAL_CONFIG)
    assert cfg["repo_id"] and cfg["exclude"] == [] and cfg["concept_queries"] == []
    assert sorted(cfg["kinds"]) == sorted(["mcp_tool_decorators", "task_decorators", "export_path_words", "export_calls",
                                           "cache_words", "pool_prefixes", "skill_md_glob"])
    assert cfg["name_filter"]["min_len"] == 4 and len(cfg["name_filter"]["stoplist"]) == 9
    assert cfg["embedder"]["probe_text"] == "codemap index fingerprint probe v1"
    assert set(cfg["prices"]) == {"file", "variable"}
    assert not any(ch.isdigit() for v in cfg["prices"].values() for ch in v)  # prices hold names only, never a number
    assert "~" not in cfg["cache_root"] and "~" not in cfg["ledger_root"]


@pytest.mark.parametrize("key", ["repo_id", "roots", "name_filter", "kinds", "embedder", "prices", "default_model"])
def test_missing_key_is_refused_by_name(tmp_path, key):
    with pytest.raises(ValueError, match=key):
        config.load_config(write_cfg(tmp_path, **{key: None}))


def test_missing_nested_key_is_refused_by_name(tmp_path):
    cfg = json.loads(REAL_CONFIG.read_text())
    del cfg["embedder"]["probe_text"]
    with pytest.raises(ValueError, match=r"embedder\.probe_text"):
        config.load_config(write_cfg(tmp_path, embedder=cfg["embedder"]))


def test_ledger_root_inside_cache_root_is_refused(tmp_path):
    cache = tmp_path / "cache-home"
    with pytest.raises(ValueError, match="ledger_root .* is inside cache_root"):
        config.load_config(write_cfg(tmp_path, cache_root=str(cache), ledger_root=str(cache / "ledger")))
    ok = config.load_config(write_cfg(tmp_path, cache_root=str(cache), ledger_root=str(tmp_path / "ledger")))
    assert ok["ledger_root"] == str(tmp_path / "ledger")


def test_cache_root_inside_the_repo_is_refused_unless_named_cache(tmp_path):
    repo = tmp_path / "work"
    repo.mkdir()
    path = write_cfg(tmp_path, cache_root=str(repo / "stuff"), ledger_root=str(tmp_path / "led"))
    with pytest.raises(ValueError, match="inside the repo"):
        config.load_config(path, repo=str(repo))
    assert config.load_config(path)["cache_root"] == str(repo / "stuff")  # no repo given: the check does not run
    ok = write_cfg(tmp_path, cache_root=str(repo / "cache"), ledger_root=str(tmp_path / "led"))
    assert config.load_config(ok, repo=str(repo))["cache_root"] == str(repo / "cache")


def test_tilde_is_expanded(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg = config.load_config(write_cfg(tmp_path, cache_root="~/c", ledger_root="~/l"))
    assert (cfg["cache_root"], cfg["ledger_root"]) == (str(tmp_path / "c"), str(tmp_path / "l"))


def test_python_minor_reads_sys_version_at_call_time(monkeypatch):
    assert config.python_minor() == f"{sys.version_info[0]}.{sys.version_info[1]}"
    with monkeypatch.context() as m:
        m.setattr(sys, "version_info", (9, 7, 1, "final", 0))
        assert config.python_minor() == "9.7"


def test_tool_tree_matches_git_for_modes_order_and_skips(tmp_path):
    repo = tmp_path / "r"
    pkg = repo / "pkg"
    (pkg / "a").mkdir(parents=True)
    (pkg / "a" / "x.txt").write_text("x\n")
    (pkg / "a.b").write_text("dot b\n")  # git sorts the folder `a` as `a/`, so it comes after `a.b`
    (pkg / "run.sh").write_text("#!/bin/sh\n")
    (pkg / "run.sh").chmod(0o755)
    (pkg / "empty").mkdir()  # git does not store an empty folder
    (pkg / "link").symlink_to("a.b")
    git(tmp_path, "init", "-q", "-b", "main", str(repo))
    (repo / ".gitignore").write_text("__pycache__/\n*.pyc\n")
    (pkg / "__pycache__").mkdir()
    (pkg / "__pycache__" / "m.pyc").write_bytes(b"1")
    (pkg / "top.pyc").write_bytes(b"2")
    commit_all(repo)
    assert config.tool_tree(pkg) == git(repo, "rev-parse", "HEAD:pkg")


def test_tool_tree_dirty_sees_edits_and_new_files_only_inside_a_work_tree(tmp_path):
    repo = make_repo(tmp_path)
    pkg = repo / "tools" / "codemap"
    assert config.tool_tree_dirty(pkg) is False
    (pkg / "summary.py").write_text("# changed\n")
    assert config.tool_tree_dirty(pkg) is True
    git(repo, "checkout", "--", "tools/codemap/summary.py")
    (pkg / "new_file.py").write_text("x = 1\n")
    assert config.tool_tree_dirty(pkg) is True
    loose = tmp_path / "loose" / "codemap"
    loose.mkdir(parents=True)
    assert config.tool_tree_dirty(loose) is False  # in no work tree


def test_tool_tree_dirty_refuses_an_ignored_test_cache_but_not_pycache(tmp_path):
    """Review r1 fix 1: a plain pytest run adds the git-ignored .pytest_cache/, which tool_tree would hash."""
    repo = make_repo(tmp_path)
    pkg = repo / "tools" / "codemap"
    (repo / ".gitignore").write_text("__pycache__/\n*.pyc\n.pytest_cache/\n")  # the real repo's .gitignore rule
    commit_all(repo)
    (pkg / "top.pyc").write_bytes(b"1")  # with the fixture's __pycache__/x.pyc: run-only files, skipped
    assert config.tool_tree_dirty(pkg) is False
    (pkg / ".pytest_cache").mkdir()
    (pkg / ".pytest_cache" / "x").write_text("cache\n")
    assert git(repo, "status", "--porcelain") == ""  # plain git status cannot see it
    assert config.tool_tree_dirty(pkg) is True


def test_tool_tree_dirty_sees_new_files_when_git_config_hides_untracked(tmp_path):
    """Review r2 fix: a user's status.showUntrackedFiles=no must not hide a new .py or an ignored .pytest_cache/."""
    repo = make_repo(tmp_path)
    pkg = repo / "tools" / "codemap"
    (repo / ".gitignore").write_text("__pycache__/\n*.pyc\n.pytest_cache/\n")
    commit_all(repo)
    git(repo, "config", "status.showUntrackedFiles", "no")
    assert config.tool_tree_dirty(pkg) is False  # control: the setting alone, no new files, stays clean
    (pkg / "brand_new.py").write_text("x = 1\n")
    assert config.tool_tree_dirty(pkg) is True
    (pkg / "brand_new.py").unlink()
    (pkg / ".pytest_cache").mkdir()
    (pkg / ".pytest_cache" / "x").write_text("cache\n")
    assert git(repo, "status", "--porcelain", "--ignored") == ""  # the setting hides both from a plain check
    assert config.tool_tree_dirty(pkg) is True
