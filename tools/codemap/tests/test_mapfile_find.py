"""Scenarios 58, 67 (find_cache_map half) and 69: which cache map may stand in for a summary."""
import os

import pytest
from codemap import mapfile, summary
from test_mapfile import R, S, build

CMD = "bash rebuild-it"
FOLDER = "maps/ABC-1"


def rows(verdicts=("kept", "kept", "kept")):
    wide = [R(f"pkg/w{i}.py:{i}", source="s1w", verdict=v, seed="beta") for i, v in enumerate(verdicts, 1)]
    return [R("pkg/a.py:1"), R("pkg/t.py:2", source="s2"), R("pkg/s.py:9", source="s3", verdict="unchecked:x", rel="cosine=0.9000"), *wide]


def put(cache, text):
    return mapfile.store_map(str(cache), "ABC-1", text)


def test_cache_sha_mismatch_is_refused(tmp_path):
    text, summ = build(rows())
    summ, text = mapfile.add_decision(summ, text, "pkg/w1.py:1", "keep", "bob", "this wide hit is a real reader")
    own = summary.parse_summary(summ)["full_sha256"]
    folder = tmp_path / FOLDER
    folder.mkdir(parents=True)
    (folder / f"{own}.tsv").write_text("".join(text.splitlines(True)[:-1]))  # named by the summary sha, one row trimmed
    undecided = put(tmp_path, build(rows())[0])  # same rows, decision lines differ
    trimmed = put(tmp_path, build(rows()[1:])[0])  # an s1 row removed: det_sha256 differs
    path, reasons = mapfile.find_cache_map(str(tmp_path), summ, CMD)
    assert path is None
    by = {r.split(":")[0]: r for r in reasons}
    assert by[own[:12]].startswith(f"{own[:12]}: full_sha256 ")
    assert by[undecided[:12]] == f"{undecided[:12]}: decided rows differ from the summary's decision lines"
    assert by[trimmed[:12]].startswith(f"{trimmed[:12]}: det_sha256 ") and " is not " in by[trimmed[:12]]
    (folder / f"{own}.tsv").write_text(text)  # the whole file is found at once
    assert mapfile.find_cache_map(str(tmp_path), summ)[0] == str(folder / f"{own}.tsv")


@pytest.mark.parametrize("status", [S("source-partial:s2 timeout", "s2"), S("source-down:s2 not-installed", "s2"),
                                    S("source-partial:s3 503 after 3 tries", "s3"), S("source-down:s3 503", "s3")])
def test_partial_rebuild_never_stands_in(tmp_path, status):
    base = rows(("kept", "dropped:judge said unrelated thing", "kept"))
    summ = build(base)[1]
    again = [r[:7] + ("unchecked:no-judge",) + r[8:] if r[6] in ("s1w", "s3") else r for r in base]
    sick = put(tmp_path, build(again + [status])[0])  # the rebuild ran where a source was down: marked partial
    path, reasons = mapfile.find_cache_map(str(tmp_path), summ, CMD)
    why = status[1].partition(":")[2]
    assert path is None
    assert reasons == [f"{sick[:12]}: cache map {sick[:12]} is partial ({why}); rebuild where every source answers: {CMD}"]
    healthy = put(tmp_path, build(again)[0])  # the second rebuild is healthy: found with no new summary
    path, reasons = mapfile.find_cache_map(str(tmp_path), summ, CMD)
    assert path == str(tmp_path / FOLDER / f"{healthy}.tsv") and len(reasons) <= 1


def test_partial_summary_finds_only_its_own_file(tmp_path):
    text, summ = build(rows() + [S("source-down:s2 not-installed", "s2")])
    assert "health=partial:s2 not-installed" in summ
    put(tmp_path, build(rows())[0])  # a healthy map under the key is never a fallback for a partial summary
    assert mapfile.find_cache_map(str(tmp_path), summ) == (None, [])
    own = put(tmp_path, text)
    assert mapfile.find_cache_map(str(tmp_path), summ)[0] == str(tmp_path / FOLDER / f"{own}.tsv")


def test_other_serena_index_or_python_in_a_map_is_refused(tmp_path):
    summ = build(rows())[1]
    for header, field in (({"serena": "ser2"}, "serena"), ({"index": "idx@rev#p2"}, "index"), ({"python": "9.9"}, "python")):
        other = put(tmp_path, build(rows(), header=header)[0])
        _, reasons = mapfile.find_cache_map(str(tmp_path), summ)
        assert f"{other[:12]}: {field} " in "\n".join(reasons)
    assert mapfile.find_cache_map(str(tmp_path), summ)[0] is None
    assert mapfile.find_cache_map(str(tmp_path / "nowhere"), summ) == (None, [])


def test_fallback_with_ai_drops_refused(tmp_path):
    base = rows(("dropped:reads only a log line", "dropped:builds only a label", "kept"))
    text, summ = build(base)
    assert "count dropped s1=0 s1w=2 s2=0 s3=0" in summ
    own = put(tmp_path, text)
    os.remove(tmp_path / FOLDER / f"{own}.tsv")  # the full_sha256 file is gone
    judged = [r[:7] + (f"dropped:judged again reason {i}",) + r[8:] if r[6] == "s1w" else r for i, r in enumerate(base)]
    later = put(tmp_path, build(judged)[0])  # a --rejudge map: same det, s2, s3, but 3 AI drops
    judged2 = [r[:7] + (f"dropped:other model reason {i}",) + r[8:] if r[6] == "s1w" else r for i, r in enumerate(base)]
    from_summary = put(tmp_path, build(judged2)[0])  # a judged --from-summary map
    path, reasons = mapfile.find_cache_map(str(tmp_path), summ, CMD)
    m8 = "holds 3 AI dropped: rows the summary does not decide; only the full_sha256 map may hold AI drops"
    assert path is None and sorted(reasons) == sorted([f"{later[:12]}: {m8}", f"{from_summary[:12]}: {m8}"])
    assert put(tmp_path, text) == own  # with the full_sha256 file back, it is accepted
    assert mapfile.find_cache_map(str(tmp_path), summ)[0] == str(tmp_path / FOLDER / f"{own}.tsv")
    os.remove(tmp_path / FOLDER / f"{own}.tsv")
    free = [r[:7] + ("unchecked:no-judge",) + r[8:] if r[6] == "s1w" else r for r in base]
    nojudge = put(tmp_path, build(free)[0])  # a --no-judge rebuild is accepted
    assert mapfile.find_cache_map(str(tmp_path), summ)[0] == str(tmp_path / FOLDER / f"{nojudge}.tsv")
