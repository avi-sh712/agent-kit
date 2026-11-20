"""The four shas, the derived count lines, the packed `files` lines and the parser."""
import hashlib

import pytest
from codemap import mapfile, summary
from test_mapfile import HEADER, R, S, build


def parsed(rows, **kw):
    return summary.parse_summary(build(rows, **kw)[1])


def test_shas_ignore_verdicts_and_follow_rows():
    a = [R("pkg/a.py:1"), R("pkg/w.py:5", source="s1w", verdict="kept", seed="beta"), R("pkg/t.py:2", source="s2"),
         R("pkg/s.py:9", source="s3", verdict="dropped:judged unrelated code")]
    b = [r[:7] + ("unchecked:no-judge",) + r[8:] if r[6] in ("s1w", "s3") else r for r in a]
    x, y = parsed(a), parsed(b)
    assert all(x[k] == y[k] for k in ("det_sha256", "s2_sha256", "s3_sha256")) and x["full_sha256"] != y["full_sha256"]
    assert parsed(a + [R("pkg/b.py:3")])["det_sha256"] != x["det_sha256"]  # a new s1 row moves det only
    assert parsed(a + [R("pkg/b.py:3")])["s2_sha256"] == x["s2_sha256"]
    assert parsed(a + [R("pkg/b.py:3", source="s2")])["s2_sha256"] != x["s2_sha256"]
    assert parsed(a, header={"ref": "9" * 40})["det_sha256"] != x["det_sha256"]  # det covers ref=, names= and wide=
    assert parsed(a, names=("alpha", "beta", "gamma"))["det_sha256"] != x["det_sha256"]
    assert parsed(a, header={"serena": "other", "index": "other", "usd": "9"})["det_sha256"] == x["det_sha256"]
    assert parsed([])["s2_sha256"] == hashlib.sha256(b"").hexdigest()  # zero s2 rows: the sha over nothing
    ordered = mapfile.read_map(build(a)[0])[1]
    assert build(list(reversed(a)))[0] == build(a)[0] and ordered == sorted(ordered)


def test_count_lines_are_derived_from_the_rows():
    rows = [R("pkg/a.py:1"), R("pkg/a.py:2", kind="mcp-tool"), R("pkg/w.py:5", source="s1w", verdict="kept", seed="beta"),
            S("source-partial:s3 503 1 of 3 batches", "s3"), S("cap-hit:1.00"), S("s3-more:cve 12")]
    text, summ = build(rows, names=("alpha", "beta", "gamma"))
    got = summary.parse_summary(summ)
    n = len(mapfile.read_map(text)[1])
    assert got["rows"] == n == 6 + 1 and got["bytes"] == len(text.encode())  # +1: the no-hit:gamma row
    assert sum(got["counts"]["source"].values()) == n and sum(got["counts"]["verdict"].values()) == n
    assert got["counts"]["source"] == {"-": 2, "s1": 3, "s1w": 1, "s3": 1}  # the no-hit row counts under s1
    assert got["counts"]["kind"] == {"call": 2, "mcp-tool": 1} and got["counts"]["name"] == {"alpha": 2, "beta": 1, "gamma": 0}
    assert got["statuses"] == 3 and got["status_lines"] == sorted(got["status_lines"]) and "s3-more:cve 12" not in got["status_lines"]
    assert got["health"] == "partial:s3 503 1 of 3 batches" and got["inventory"] == "no"


def test_files_lines_pack_to_400_bytes_and_parse_back():
    names = [f"module_with_a_long_name_{i:03d}.py" for i in range(40)]
    rows = [R(f"pkg/deep/{n}:1") for n in names] + [R("top.py:4"), R("pkg/gone.py:2", source="s1w", verdict="dropped:judged unrelated code"),
                                                      R("pkg/mixed.py:2", source="s1w", verdict="dropped:judged unrelated code"),
                                                      R("pkg/mixed.py:3")]
    text, summ = build(rows)
    got = summary.parse_summary(summ)
    lines = [ln for ln in summ.splitlines() if ln.startswith("files ")]
    assert len(lines) > 3 and all(len(ln.encode()) <= 400 for ln in lines) and "files ./ top.py" in lines
    want = sorted([f"pkg/deep/{n}" for n in names] + ["top.py", "pkg/mixed.py"])
    assert sorted(got["file_paths"]) == want and got["files"] == len(want)  # an all-dropped file is not listed
    with pytest.raises(ValueError, match="file name with a space"):
        build([R("pkg/a b.py:1")])


def test_fields_are_cleaned_and_the_parser_is_strict():
    text, summ = build([R("pkg/a.py:1", snippet="x = 1\tand\ny = 2")], names=("alpha",))
    row = mapfile.read_map(text)[1][0]
    assert row[8] == "x = 1 and y = 2" and len(row) == 9
    with pytest.raises(ValueError, match="header is not"):
        summary.parse_summary("nope\n")
    with pytest.raises(ValueError, match="cannot be read"):
        summary.parse_summary(summ + "garbage line\n")
    with pytest.raises(ValueError, match="has 3 fields, not 9"):
        mapfile.read_map(text + "a\tb\tc\n")
    with pytest.raises(ValueError, match="header is not"):
        mapfile.read_map("hello\n")
    with pytest.raises(ValueError, match="bad design key"):
        summary.write_summary(HEADER, [], "../x", {})
    assert summary.parse_summary(summ)["key"] == "ABC-1" and summ.endswith("\n") and "\r" not in summ
