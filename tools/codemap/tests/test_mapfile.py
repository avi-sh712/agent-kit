"""Scenarios 21, 22, 23, 61, 64: caps, flags, two writers, cache keys, source-1 outage. Also the row helpers."""
import fcntl
import os
import subprocess
import sys
from pathlib import Path

import pytest
from codemap import mapfile, summary

TOOLS = str(Path(__file__).resolve().parents[2])
HEADER = {"ref": "a" * 40, "wide": "", "sources": "s1,s1w,s2,s3", "python": "9.1", "usd": "0", "model": "m1",
          "index": "idx@rev#p1", "serena": "ser1", "judge_ignored": "0"}
INPUTS = {"config": "tools/codemap/configs/example.json", "config_sha256": "c" * 64, "tool_tree": "d" * 40,
          "inventory": False}


def R(loc, source="s1", verdict="exact", seed="alpha", func="fn", snippet=None, kind="call", hop="0", rel="calls"):
    return (hop, kind, loc, rel, func, seed, source, verdict, snippet if snippet is not None else f"code at {loc}")


def S(kind, source="-"):
    return ("-", kind, "-", "-", "-", "-", source, "-", "-")


def build(rows, names=("alpha", "beta"), old=None, inputs=None, key="ABC-1", header=None):
    """(map text, summary text) written the way the tool writes them."""
    h = {**HEADER, **(header or {})}
    text = mapfile.write_map(h, rows, list(names))
    hdr, parsed = mapfile.read_map(text)
    return text, summary.write_summary(hdr, parsed, key, inputs or INPUTS, old_summary=old)


def test_too_many_keeps_every_row():
    rows = [R(f"pkg/m{i}.py:{i}") for i in range(401)] + [R("pkg/z.py:1", seed="gamma")]
    text, summ = build(rows, names=("alpha", "beta", "gamma"))
    header, got = mapfile.read_map(text)
    kinds = [r[1] for r in got]
    assert "too-many:alpha 401" in kinds and "no-hit:beta" in kinds and "too-many:gamma 1" not in kinds
    assert sum(1 for r in got if r[5] == "alpha" and not r[1].startswith("too-many")) == 401  # nothing was cut
    assert header["health"] == "ok" and "health=ok" in summ
    assert summary.parse_summary(summ)["counts"]["name"] == {"alpha": 401, "beta": 0, "gamma": 1}
    assert mapfile.write_map(header, got, ["alpha", "beta", "gamma"]) == text  # a rewrite is stable


def test_size_cap_refuses_never_cuts(tmp_path):
    many = [R(f"pkg/m{i % 50}.py:{i}", seed=f"n{i % 9}") for i in range(8001)]
    with pytest.raises(ValueError, match=r"caps 8000 rows and 1048576 bytes; 5 biggest names: n0=\d+, n1=\d+, n2=\d+, n3=\d+, n4=\d+"):
        mapfile.write_map(HEADER, many, [])
    big = [R(f"pkg/b{i}.py:1", snippet="x" * 400_000) for i in range(3)]
    with pytest.raises(ValueError, match="caps 8000 rows and 1048576 bytes"):
        mapfile.write_map(HEADER, big, ["alpha"])
    assert not (tmp_path / "cache").exists() and not list(tmp_path.iterdir())  # nothing was written anywhere
    many_kinds = [R(f"pkg/k{i}.py:1", kind=f"kind{i}") for i in range(401)]
    with pytest.raises(ValueError, match=r"summary would be \d+ lines with 0 decision lines; cap 400"):
        build(many_kinds)
    with pytest.raises(ValueError, match="caps 8000 rows"):  # store_map holds the same cap
        mapfile.store_map(str(tmp_path / "c"), "K-1", "# codemap v1 \n" + "\n" * 8002)
    assert not (tmp_path / "c").exists()


def test_summary_byte_and_line_caps_refuse(tmp_path):
    """Review r1 fix 2: under 400 lines but over 65,536 bytes; and one line over 400 bytes."""
    wide = [R(f"pkg/f{i:03d}_{'x' * 180}.py:1") for i in range(400)]  # two names per files line, ~390 bytes each
    with pytest.raises(ValueError, match=r"^summary would be \d+ bytes with 0 decision lines; cap 65536$"):
        build(wide)
    text, summ = build([R("pkg/a.py:1"), R("pkg/w.py:5", source="s1w", seed="beta", func="wfn", snippet="wide code")])
    long_reason = "this row is a real reader " + "y" * 400
    with pytest.raises(ValueError, match=r"^summary line \d+ would be over 400 bytes$"):
        mapfile.add_decision(summ, text, "pkg/w.py:5", "keep", "amy", long_reason)
    assert summary.parse_summary(summ)["decisions"] == 0 and not list(tmp_path.iterdir())  # nothing was written


def _writer(tmp_path, text, summ, wait="60"):
    code = ("import sys\nsys.path.insert(0, sys.argv[1])\nfrom codemap import mapfile\n"
            "mapfile.commit(sys.argv[2], 'ABC-1', open(sys.argv[3]).read(), sys.argv[4], open(sys.argv[5]).read(), lock_wait=float(sys.argv[6]))\n")
    mp, sp = tmp_path / f"m{len(text)}.txt", tmp_path / f"s{len(summ)}.txt"
    mp.write_text(text)
    sp.write_text(summ)
    args = [sys.executable, "-c", code, TOOLS, str(tmp_path / "cache"), str(mp), str(tmp_path / "out" / "sum.txt"), str(sp), wait]
    return subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def test_two_runs_same_summary_never_half(tmp_path):
    (t1, s1), (t2, s2) = build([R("pkg/a.py:1")]), build([R("pkg/a.py:1"), R("pkg/b.py:2")])
    procs = [_writer(tmp_path, t, x) for t, x in ((t1, s1), (t2, s2), (t1, s1), (t2, s2))]
    for p in procs:
        out, err = p.communicate(timeout=60)
        assert p.returncode == 0, err
    final = (tmp_path / "out" / "sum.txt").read_text()
    assert final in (s1, s2)  # a whole summary, not a mix
    folder = tmp_path / "cache" / "maps" / "ABC-1"
    named = summary.parse_summary(final)["full_sha256"]
    assert (folder / f"{named}.tsv").read_text() in (t1, t2)
    assert summary.full_sha256((folder / f"{named}.tsv").read_text()) == named
    assert not [p for p in tmp_path.rglob("*.tmp")]  # no .tmp left
    # the lock: a holder blocks commit, and the error names the holder
    fd = os.open(folder / "summary.lock", os.O_RDWR)
    fcntl.flock(fd, fcntl.LOCK_EX)
    os.ftruncate(fd, 0)
    os.write(fd, b"4242")
    try:
        with pytest.raises(ValueError, match="summary is locked by pid 4242"):
            mapfile.commit(str(tmp_path / "cache"), "ABC-1", t1, str(tmp_path / "out" / "sum.txt"), s1, lock_wait=1)
    finally:
        os.close(fd)
    assert (tmp_path / "out" / "sum.txt").read_text() == final  # the refused commit changed nothing
    mapfile.commit(str(tmp_path / "cache"), "ABC-1", t1, str(tmp_path / "out" / "sum.txt"), s1, lock_wait=1)


def test_commit_renames_the_cache_map_before_the_summary(tmp_path, monkeypatch):
    text, summ = build([R("pkg/a.py:1")])
    seen = []
    real = os.replace
    srcs = []
    monkeypatch.setattr(os, "replace", lambda a, b: (seen.append(os.path.basename(b)), srcs.append((a, b)), real(a, b))[2])
    mapfile.commit(str(tmp_path / "c"), "ABC-1", text, str(tmp_path / "s.txt"), summ)
    assert seen == [summary.full_sha256(text) + ".tsv", "s.txt"]
    assert all(str(a).endswith(".tmp") and a != b for a, b in srcs)  # tmp + rename, never a write in place


def test_commit_sweeps_old_tmp_files_and_refuses_a_summary_naming_another_map(tmp_path):
    text, summ = build([R("pkg/a.py:1")])
    folder = tmp_path / "c" / "maps" / "ABC-1"
    folder.mkdir(parents=True)
    (folder / "dead.tsv.12.34.tmp").write_text("half")
    (tmp_path / "s.txt.99.1.tmp").write_text("half")
    with pytest.raises(ValueError, match="does not name this key and this map"):
        mapfile.commit(str(tmp_path / "c"), "ABC-1", text + "x\n", str(tmp_path / "s.txt"), summ)
    assert (folder / "dead.tsv.12.34.tmp").exists()  # a refused commit touches nothing
    mapfile.commit(str(tmp_path / "c"), "ABC-1", text, str(tmp_path / "s.txt"), summ)
    assert not list(tmp_path.rglob("*.tmp"))


def test_cache_keys_never_collide(tmp_path):
    cache = str(tmp_path / "cache")
    maps = {("ABC-1", "r1"): build([R("pkg/a.py:1")], header={"ref": "1" * 40})[0],
            ("ABC-1", "r2"): build([R("pkg/a.py:1")], header={"ref": "2" * 40})[0],
            ("ABC-2", "r1"): build([R("pkg/a.py:1")], header={"ref": "1" * 40}, names=("alpha",))[0],
            ("ABC-2", "r2"): build([R("pkg/a.py:1")], header={"ref": "2" * 40}, names=("alpha",))[0]}
    shas = {k: mapfile.store_map(cache, k[0], t) for k, t in maps.items()}
    assert len(set(shas.values())) == 4
    for (key, _), sha in shas.items():
        assert (tmp_path / "cache" / "maps" / key / f"{sha}.tsv").read_text() == maps[(key, _)]
    first = maps[("ABC-1", "r1")]
    assert mapfile.store_map(cache, "ABC-1", first) == shas[("ABC-1", "r1")]  # the same map twice
    assert len(list((tmp_path / "cache" / "maps" / "ABC-1").iterdir())) == 2  # is one whole file
    for bad in ("../x", "a/b", ".hidden", ""):
        with pytest.raises(ValueError, match="bad design key"):
            mapfile.store_map(cache, bad, first)


def test_s1_down_and_cannot_parse(tmp_path):
    """Storage half only: parser faked; P1b proves the real ast.parse path and the bad ref."""
    bad = S("source-partial:s1 cannot-parse:pkg/bad.py", "s1")
    text, summ = build([R("pkg/a.py:1"), bad])
    header, rows = mapfile.read_map(text)
    assert header["health"] == "partial:s1 cannot-parse:pkg/bad.py"
    assert "health=partial:s1 cannot-parse:pkg/bad.py" in summ and "health=partial:s1 cannot-parse:pkg/bad.py" in text
    assert mapfile.health_of(rows) == header["health"]
    down = [S("source-down:s2 not-installed", "s2"), S("source-partial:s3 503 1 of 3 batches", "s3"), S("ai-unavailable:no-key")]
    assert mapfile.health_of(down) == "partial:s2 not-installed,s3 503 1 of 3 batches"  # an AI status never sets it
    assert mapfile.health_of([S("cap-hit:1.00"), S("source-down:s4 x", "s4")]) == "ok"
    refused = mapfile.write_map  # a refused write leaves no .tmp: an over-cap map never reaches the folder
    with pytest.raises(ValueError):
        refused(HEADER, [R(f"p/{i}.py:1") for i in range(8001)], ["alpha"])
    assert not list(tmp_path.rglob("*.tmp")) and not list(tmp_path.iterdir())
    mapfile.commit(str(tmp_path / "c"), "ABC-1", text, str(tmp_path / "s.txt"), summ)  # a partial map is still stored
    assert not list(tmp_path.rglob("*.tmp"))
