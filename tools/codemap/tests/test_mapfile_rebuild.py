"""Scenarios 59c, 65, 68 and the partial-summary refusal (build note 4): the checks a rebuild runs before any source."""
import subprocess
import sys

from codemap import config, summary
from test_config import git, make_repo
from test_mapfile import HEADER, INPUTS, R, S, build

SUMMARY_PATH = "designs/maps/ABC-1-map-summary.txt"  # a path given by the caller, the package never builds one


def made(tool_tree=INPUTS["tool_tree"], config_sha=INPUTS["config_sha256"], header=None, extra=()):
    return build([R("pkg/a.py:1"), *extra], header=header, inputs={**INPUTS, "tool_tree": tool_tree, "config_sha256": config_sha})[1]


def refusal(summ, tmp_path, **kw):
    args = {"summary_path": SUMMARY_PATH, "repo": str(tmp_path / "repo"), "cache_dir": str(tmp_path / "cache"),
            "scratch_path": str(tmp_path / "scratch.txt"), "python": HEADER["python"], "config_sha256": INPUTS["config_sha256"]}
    return config.rebuild_refusal(summ, **{**args, **kw})


def test_rebuild_runs_the_pinned_tool_tree(tmp_path):
    repo = make_repo(tmp_path)
    pkg = repo / "tools" / "codemap"
    tree = config.tool_tree(pkg)
    assert tree == git(repo, "rev-parse", "HEAD:tools/codemap")  # (b) pure-Python hash = git's, with a gitignored x.pyc present
    assert (pkg / "__pycache__" / "x.pyc").exists()
    summ = made(tool_tree=tree)
    cache = tmp_path / "cache"
    cmd = config.rebuild_command(summ, repo=str(repo), cache_dir=str(cache), summary_path=SUMMARY_PATH, scratch_path=str(tmp_path / "s.txt"))
    export, run = cmd.split("\n")
    target = cache / f"tool-{tree[:12]}"
    assert run.startswith(f"PYTHONPATH={target} python3 -m codemap map --repo {repo} ")
    assert f"--config {target}/codemap/configs/example.json --from-summary {SUMMARY_PATH} --no-judge --summary " in run
    procs = [subprocess.Popen(["bash", "-c", export], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
    for p in procs:  # (a) two exports at once both finish
        _, err = p.communicate(timeout=60)
        assert p.returncode == 0, err
    assert config.tool_tree(target / "codemap") == tree  # one whole folder, the pinned tree
    assert [p.name for p in cache.iterdir()] == [target.name]  # no tmp folder left
    assert subprocess.run(["bash", "-c", export], timeout=60).returncode == 0  # a third run finds it and does nothing
    bad = export.replace(tree, "f" * 40).replace(f"tool-{tree[:12]}", "tool-other")  # a failed archive removes its own tmp folder
    subprocess.run(["bash", "-c", bad], capture_output=True, timeout=60, check=False)
    assert [p.name for p in cache.iterdir()] == [target.name]
    assert refusal(summ, tmp_path, tool_tree="e" * 40) == f"tool tree {'e' * 12} differs from the summary {tree[:12]}; run the printed rebuild command"
    assert refusal(summ, tmp_path, tool_tree=tree) is None
    assert config.tool_tree_dirty(pkg) is False
    (pkg / "mapfile.py").write_text("# edited\n")  # (c) an uncommitted change
    assert config.tool_tree_dirty(pkg) is True
    assert refusal(summ, tmp_path, tool_tree=tree, dirty=True) == "tool tree is dirty"
    assert config.tool_tree(pkg) != tree


def test_rebuild_refuses_other_python_and_config(tmp_path, monkeypatch):
    summ = made()
    with monkeypatch.context() as m:
        m.setattr(sys, "version_info", (9, 2, 0, "final", 0))
        other = config.python_minor()
    assert other == "9.2"
    assert refusal(summ, tmp_path, python=other) == f"python 9.2 is not the summary's python={HEADER['python']}; run the rebuild with python {HEADER['python']}"
    wrong = "0" * 64
    assert refusal(summ, tmp_path, config_sha256=wrong) == (
        f"config sha256 {wrong} is not the summary's config_sha256={INPUTS['config_sha256']}; run the printed rebuild command")
    assert refusal(summ, tmp_path) is None
    assert not (tmp_path / "cache").exists() and not (tmp_path / "scratch.txt").exists()  # nothing was written


def test_rebuild_refuses_other_serena_and_index(tmp_path):
    summ = made()
    remake = config.remake_command(summ, SUMMARY_PATH)
    assert refusal(summ, tmp_path, serena="ser9") == f"Serena ser9 is not the summary's serena=ser1; rebuild where Serena ser1 runs, or re-make: {remake}"
    assert refusal(summ, tmp_path, index="idx@rev#p9") == (
        f"embedder index idx@rev#p9 is not the summary's index=idx@rev#p1; rebuild where index idx@rev#p1 runs, or re-make: {remake}")
    assert refusal(summ, tmp_path, serena="ser1", index="idx@rev#p1") is None
    both = refusal(summ, tmp_path, serena="ser9", index="idx@rev#p9", python="9.8")
    assert both.startswith("python 9.8 is not")  # python is checked before Serena, Serena before the index
    assert refusal(summ, tmp_path, serena="ser9", index="idx@rev#p9").startswith("Serena ser9")
    assert not (tmp_path / "cache").exists()


def test_from_summary_refuses_partial_summary(tmp_path):
    summ = made(extra=[S("source-partial:s3 503 1 of 3 batches", "s3")])
    remake = config.remake_command(summ, SUMMARY_PATH)
    want = f"map summary is partial (s3 503 1 of 3 batches); re-make it where every source answers: {remake}"
    assert refusal(summ, tmp_path) == want
    assert refusal(summ, tmp_path, dirty=True, python="9.9", serena="x", index="y", tool_tree="e" * 40) == want  # M1 comes first


def test_remake_command_is_built_from_the_summary_text(tmp_path):
    h = {"wide": "post_url,username", "ref": "b" * 40}
    summ = build([R("pkg/a.py:1")], header=h, inputs={**INPUTS, "inventory": True})[1]
    assert config.remake_command(summ, SUMMARY_PATH) == (
        f"PYTHONPATH=tools python3 -m codemap map --repo . --config {INPUTS['config']} --ref {'b' * 40} --names alpha,beta "
        f"--wide post_url,username --inventory --prev {SUMMARY_PATH} --summary {SUMMARY_PATH}")
    plain = config.remake_command(made(), "x y.txt")
    assert "--wide" not in plain and "--inventory" not in plain and "--prev 'x y.txt' --summary 'x y.txt'" in plain
    assert summary.parse_summary(summ)["inventory"] == "yes"
