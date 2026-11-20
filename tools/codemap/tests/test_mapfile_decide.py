"""Scenarios 22 (the decide cap, build note 12), 59b and build note 5: human decisions live in the summary and only grow."""
import pytest
from codemap import mapfile, summary
from test_mapfile import INPUTS, R, build

W1 = dict(source="s1w", seed="beta", func="wfn", snippet="wide code one")
W2 = dict(source="s1w", seed="beta", func="gfn", snippet="wide code two")
S3 = dict(source="s3", rel="cosine=0.9000", func="sfn", snippet="meaning code", verdict="unchecked:no-judge")


def base():
    return [R("pkg/a.py:1"), R("pkg/w.py:5", verdict="kept", **W1), R("pkg/s.py:9", **S3)]


def lines_of(text):
    return text.splitlines()


def test_decide_only_on_s1w_and_s3_rows():
    text, summ = build(base() + [R("pkg/t.py:2", source="s2")])
    for loc, src in (("pkg/a.py:1", "s1"), ("pkg/t.py:2", "s2")):
        with pytest.raises(ValueError, match=f"decide runs only on s1w and s3 rows; {loc} is {src}"):
            mapfile.add_decision(summ, text, loc, "keep", "amy", "this row is a real reader")
    for loc in ("pkg/w.py:5", "pkg/s.py:9"):
        new_summ, new_map = mapfile.add_decision(summ, text, loc, "keep", "amy", "this row is a real reader")
        got = summary.parse_summary(new_summ)
        assert got["decisions"] == 1 and got["decision_lines"][0]["verdict"] == "kept-by:amy" and got["decision_lines"][0]["loc"] == loc
        assert any(r[2] == loc and r[7] == "kept-by:amy this row is a real reader" for r in mapfile.read_map(new_map)[1])
        old = summary.parse_summary(summ)  # verdicts are blanked in the three shas, so only full_sha256 moves
        assert all(got[k] == old[k] for k in ("det_sha256", "s2_sha256", "s3_sha256")) and got["full_sha256"] != old["full_sha256"]
        assert got["full_sha256"] == summary.full_sha256(new_map)
    for args in (("maybe", "amy", "this row is a real reader"), ("keep", "a my", "this row is a real reader"), ("keep", "amy", "too short")):
        with pytest.raises(ValueError, match="decide needs keep or drop"):
            mapfile.add_decision(summ, text, "pkg/w.py:5", *args)
    with pytest.raises(ValueError, match="matches 0 rows"):
        mapfile.add_decision(summ, text, "pkg/none.py:1", "keep", "amy", "this row is a real reader")


def test_decide_again_replaces_the_line():
    text, summ = build(base())
    s1, m1 = mapfile.add_decision(summ, text, "pkg/w.py:5", "keep", "amy", "first look says reader")
    s2, m2 = mapfile.add_decision(s1, m1, "pkg/s.py:9", "keep", "amy", "second row is a reader")
    before = [i for i, ln in enumerate(lines_of(s2)) if ln.startswith("decision ")]
    s3, m3 = mapfile.add_decision(s2, m2, "pkg/w.py:5", "drop", "bob", "on a second look unrelated")
    after = [i for i, ln in enumerate(lines_of(s3)) if ln.startswith("decision ")]
    assert before == after and len(after) == 2  # replaced in place, not appended
    got = summary.parse_summary(s3)
    assert got["decisions"] == 2
    assert [(d["loc"], d["verdict"]) for d in got["decision_lines"]] == [("pkg/s.py:9", "kept-by:amy"), ("pkg/w.py:5", "dropped:bob")]
    row = next(r for r in mapfile.read_map(m3)[1] if r[2] == "pkg/w.py:5")
    assert row[7] == "dropped:bob on a second look unrelated"
    assert got["counts"]["dropped"]["s1w"] == 1  # a hand drop is still a dropped: row to the counts


def test_decide_after_rebuild_recomputes_counts():
    old_rows = [R("pkg/a.py:1"), R("pkg/w1.py:1", verdict="dropped:reads only a log line", **W1),
                R("pkg/w2.py:2", verdict="dropped:builds only a label", **W2), R("pkg/s.py:9", **S3)]
    old_text, old_summ = build(old_rows)
    assert "count dropped s1=0 s1w=2 s2=0 s3=0" in old_summ
    rebuilt = [r[:7] + ("unchecked:no-judge",) + r[8:] if r[7].startswith("dropped:") else r for r in old_rows]
    rebuilt_text = build(rebuilt)[0]  # the free rebuild: AI drops became unchecked:no-judge
    new_summ, new_map = mapfile.add_decision(old_summ, rebuilt_text, "pkg/s.py:9", "keep", "amy", "this meaning hit is real")
    hdr, rows = mapfile.read_map(new_map)
    fresh = summary.write_summary(hdr, rows, "ABC-1", INPUTS, old_summary=new_summ)
    assert fresh == new_summ  # every derived line equals a fresh write_summary of the new map
    got, old = summary.parse_summary(new_summ), summary.parse_summary(old_summ)
    assert got["counts"]["dropped"] == {"s1": 0, "s1w": 0, "s2": 0, "s3": 0} and got["counts"]["verdict"]["unchecked"] == 2 and got["counts"]["verdict"]["kept-by"] == 1
    assert got["bytes"] == len(new_map.encode()) and got["rows"] == len(rows) and got["decisions"] == 1
    assert all(got[k] == old[k] for k in ("det_sha256", "s2_sha256", "s3_sha256")) and got["full_sha256"] != old["full_sha256"]


def _padded(n):
    return build(base() + [R("pkg/k.py:%d" % (100 + i), kind=f"kind{i}") for i in range(n)])


def test_decide_cap_refused_and_nothing_written():
    n = 400 - len(lines_of(_padded(0)[1])) - 1
    text, summ = _padded(n)
    assert len(lines_of(summ)) == 399
    s1, m1 = mapfile.add_decision(summ, text, "pkg/w.py:5", "keep", "amy", "first look says reader")
    assert len(lines_of(s1)) == 400
    s1b, _ = mapfile.add_decision(s1, m1, "pkg/w.py:5", "drop", "amy", "second look says unrelated")
    assert len(lines_of(s1b)) == 400  # a re-decide replaces a line, so it fits
    with pytest.raises(ValueError, match="^summary would be 401 lines with 2 decision lines; cap 400$"):
        mapfile.add_decision(s1, m1, "pkg/s.py:9", "keep", "amy", "second row is a reader")
    assert summary.parse_summary(s1)["decisions"] == 1


def test_decision_lines_never_dropped():
    old = [R("pkg/a.py:1"), R("pkg/w.py:5", verdict="kept", **W1), R("pkg/gone.py:3", verdict="kept", **W2)]
    text, summ = build(old)
    summ, text = mapfile.add_decision(summ, text, "pkg/w.py:5", "keep", "amy", "first look says reader")
    summ, text = mapfile.add_decision(summ, text, "pkg/gone.py:3", "keep", "amy", "second look says reader")
    assert summary.parse_summary(summ)["decisions"] == 2
    new = [R("pkg/a.py:1"), R("pkg/w.py:50", verdict="kept", **W1)]  # a new ref: the first moved, the second code is gone
    lines, rows = summary.carry_decisions(summ, new)
    assert len(lines) == 2 and [d["stale"] for d in sorted(lines, key=lambda d: d["function"])] == [True, False]
    assert next(d for d in lines if d["function"] == "wfn")["loc"] == "pkg/w.py:50"  # the live line follows its row
    assert [r[1] for r in rows if r[1].startswith("kept-by-stale")] == ["kept-by-stale:amy"]
    with pytest.raises(ValueError, match="call carry_decisions before write_map"):
        build(new, old=summ)  # a map without the stale status row cannot be summarised
    _, summ2 = build(rows, old=summ)
    got = summary.parse_summary(summ2)
    assert got["decisions"] == 2 and got["statuses"] == 1 and got["status_lines"] == ["kept-by-stale:amy"]
    assert [d["stale"] for d in got["decision_lines"]] == [True, False] and "decision stale kept-by:amy pkg/gone.py:3 gfn" in summ2
    again, rows3 = summary.carry_decisions(summ2, rows)  # a re-run on top of it changes nothing and still drops nothing
    assert rows3 == rows and len(again) == 2
    assert build(rows3, old=summ2)[1] == summ2
    both_gone, rows4 = summary.carry_decisions(summ2, [R("pkg/a.py:1")])  # now both decided codes are gone
    _, summ3 = build(rows4, old=summ2, names=("alpha",))
    got3 = summary.parse_summary(summ3)
    assert len(both_gone) == 2 and got3["decisions"] == 2 and got3["statuses"] == 2
