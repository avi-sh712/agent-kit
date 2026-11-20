"""The small summary kept in git: write, parse, the four shas, decision lines. Stdlib only, imports no package module."""
import hashlib
import re
from collections import Counter

HEAD = "# codemap summary v1"
MAP_HEAD = "# codemap v1 "
MAX_LINES, MAX_BYTES, MAX_LINE = 400, 65536, 400
HEADER_KEYS = ("ref", "names", "wide", "sources", "health", "python", "usd", "model", "index", "serena", "judge_ignored")
STATUS = ("no-hit:", "too-many:", "source-down:", "source-partial:", "ai-unavailable:", "cap-hit:", "kept-by-stale:", "s3-more:")
SEARCH = ("s1", "s1w", "s2", "s3")
INTS = ("files", "decisions", "statuses")
KEY_RE = r"[A-Za-z0-9][A-Za-z0-9_.-]*"


def clean_field(value):
    """Tabs and newlines become one space, so a row stays on one line."""
    return re.sub(r"[\t\r\n]+", " ", str(value))


def is_status(row):
    return row[1].startswith(STATUS)


def snip12(row):
    return hashlib.sha256(row[8].encode("utf-8")).hexdigest()[:12]


def map_text(header, rows):
    """The one place a full map is serialised: canonical header, then sorted 9-field rows."""
    head = MAP_HEAD + " ".join(f"{k}={clean_field(header.get(k, '-'))}" for k in HEADER_KEYS)
    body = sorted(tuple(clean_field(f) for f in r) for r in rows)
    for r in body:
        if len(r) != 9:
            raise ValueError(f"map row has {len(r)} fields, not 9")
    return "\n".join([head, *("\t".join(r) for r in body)]) + "\n"


def health_of(rows):
    """`ok`, or `partial:<s> <reason>,...` when a search source (s1, s1w, s2, s3) was down or partial."""
    bad = [r[1].partition(":")[2] for r in sorted(map(tuple, rows))
           if r[1].startswith(("source-down:", "source-partial:")) and r[6] in SEARCH]
    return "partial:" + ",".join(bad) if bad else "ok"


def _sha(lines):
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def _blank(rows, sources):
    """Rows of these sources, verdict blanked, sorted after blanking (a verdict never moves a row)."""
    return sorted("\t".join(r[:7] + ("",) + r[8:]) for r in map(tuple, rows) if r[6] in sources)


def det_sha256(header, rows):
    return _sha([f"{k}={header.get(k, '')}" for k in ("ref", "names", "wide")] + _blank(rows, ("s1", "s1w")))


def s2_sha256(rows):
    return _sha(_blank(rows, ("s2",)))


def s3_sha256(rows):
    return _sha(_blank(rows, ("s3",)))


def full_sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _dkey(d):
    return (d["loc"].rsplit(":", 1)[0], d["function"], d["sha12"])


def _dline(d):
    return "decision " + ("stale " if d["stale"] else "") + " ".join(
        (d["verdict"], d["loc"], d["function"] or "-", d["sha12"], d["source"], d["reason"]))


def _dparse(line):
    p = line.split(" ", 2)
    stale = p[1] == "stale"
    p = line.split(" ", 7 if stale else 6)
    if stale:
        del p[1]
    if len(p) != 7:
        raise ValueError(f"decision line cannot be read: {line[:60]}")
    return dict(zip(("verdict", "loc", "function", "sha12", "source", "reason"), p[1:]), stale=stale)


def carry_decisions(old_summary, new_rows):
    """Copy every old decision line (never drop one); code that is gone makes it `stale` plus a status row."""
    rows = [tuple(r) for r in new_rows]
    where = {}
    for r in rows:
        if not is_status(r):
            where.setdefault((r[2].rsplit(":", 1)[0], r[4] or "-", snip12(r)), []).append(r[2])
    out = []
    for d in parse_summary(old_summary)["decision_lines"]:
        locs = where.get(_dkey(d), [])
        if d["stale"] or not locs:
            d["stale"] = True
        elif d["loc"] not in locs:
            d["loc"] = locs[0]
        out.append(d)
    have = Counter(r[1] for r in rows)
    need = Counter("kept-by-stale:" + d["verdict"].partition(":")[2] for d in out if d["stale"])
    for kind, n in sorted(need.items()):
        rows += [("-", kind, "-", "-", "-", "-", "-", "-", "-")] * max(0, n - have[kind])
    return sorted(out, key=lambda d: (d["loc"], d["function"], d["sha12"])), rows


def _count(items):
    c = Counter(items)
    return " ".join(f"{k}={c[k]}" for k in sorted(c))


def _files_lines(files):
    out, by = [], {}
    for p in files:
        if " " in p:
            raise ValueError(f"file name with a space cannot be listed: {p}")
        folder, _, name = p.rpartition("/")
        by.setdefault((folder or ".") + "/", []).append(name)
    for folder, names in sorted(by.items()):
        line = "files " + folder
        for n in names:
            if len(line.encode()) + 1 + len(n.encode()) > MAX_LINE:
                out.append(line)
                line = "files " + folder
            line += " " + n
        out.append(line)
    return out


def write_summary(header, rows, key, inputs, old_summary=None):
    """The summary text for this map. Every derived line is computed from `rows`, never copied (build note 5)."""
    if not re.fullmatch(KEY_RE, key):
        raise ValueError(f"bad design key {key!r}")
    rows = [tuple(clean_field(f) for f in r) for r in rows]
    decs = []
    if old_summary is not None:
        decs, with_status = carry_decisions(old_summary, rows)
        if sorted(with_status) != sorted(rows):
            raise ValueError("rows lack the kept-by-stale: status rows; call carry_decisions before write_map")
    new = {_dkey(d): d for d in inputs.get("decisions", [])}
    decs = sorted([d for d in decs if _dkey(d) not in new] + list(new.values()),
                  key=lambda d: (d["loc"], d["function"], d["sha12"]))
    real = [r for r in rows if not is_status(r)]
    stats = [r[1] for r in rows if is_status(r) and not r[1].startswith("s3-more:")]
    kept = sorted({r[2].rsplit(":", 1)[0] for r in real if not r[7].startswith("dropped:")})
    drops = Counter(r[6] for r in rows if r[7].startswith("dropped:"))
    names = [n for n in header.get("names", "").split(",") if n]
    seeds = Counter(r[5] for r in real)
    mtext = map_text(header, rows)
    head = [("key", key), ("ref", header["ref"]), ("config", inputs["config"]), ("config_sha256", inputs["config_sha256"]),
            ("tool_tree", inputs["tool_tree"]), ("python", header["python"]), ("serena", header.get("serena", "-")),
            ("index", header.get("index", "-")), ("model", header.get("model", "-")), ("usd", header.get("usd", "0")),
            ("health", health_of(rows)), ("names", ",".join(names)), ("wide", header.get("wide", "")),
            ("inventory", "yes" if inputs.get("inventory") else "no"),
            ("det_sha256", det_sha256(header, rows)), ("s2_sha256", s2_sha256(rows)),
            ("s3_sha256", s3_sha256(rows)), ("full_sha256", full_sha256(mtext))]
    lines = [HEAD, *(f"{k}={v}" for k, v in head), f"rows={len(rows)} bytes={len(mtext.encode())}", f"files={len(kept)}",
             f"decisions={len(decs)}", f"statuses={len(stats)}", "count source " + _count(r[6] for r in rows),
             "count verdict " + _count(re.split(r"[: ]", r[7], maxsplit=1)[0] for r in rows),
             "count dropped " + " ".join(f"{s}={drops[s]}" for s in SEARCH)]
    lines += [f"count kind {k.replace(' ', '_')}={c}" for k, c in sorted(Counter(r[1] for r in real).items())]
    lines += [f"count name {n}={seeds[n]}" for n in names]
    lines += _files_lines(kept) + [f"status {s}" for s in stats] + [_dline(d) for d in decs]
    text = "\n".join(lines) + "\n"
    if len(lines) > MAX_LINES:
        raise ValueError(f"summary would be {len(lines)} lines with {len(decs)} decision lines; cap {MAX_LINES}")
    if len(text.encode()) > MAX_BYTES:
        raise ValueError(f"summary would be {len(text.encode())} bytes with {len(decs)} decision lines; cap {MAX_BYTES}")
    for n, ln in enumerate(lines, 1):
        if len(ln.encode()) > MAX_LINE:
            raise ValueError(f"summary line {n} would be over {MAX_LINE} bytes")
    return text


def parse_summary(text):
    """Fields as strings (`files`, `decisions`, `statuses`, `rows`, `bytes` as ints) plus counts and the line lists."""
    out = {"counts": {}, "file_paths": [], "status_lines": [], "decision_lines": []}
    lines = text.split("\n")
    if lines[-1] == "":
        lines.pop()
    if not lines or lines[0] != HEAD:
        raise ValueError("map summary header is not '# codemap summary v1'")
    for n, ln in enumerate(lines[1:], 2):
        word, _, rest = ln.partition(" ")
        if word == "count":
            kind, _, body = rest.partition(" ")
            pairs = (t.rpartition("=") for t in body.split(" ") if t)
            out["counts"].setdefault(kind, {}).update({k: int(v) for k, _, v in pairs})
        elif word == "files":
            folder, *names = rest.split(" ")
            out["file_paths"] += [("" if folder == "./" else folder) + x for x in names]
        elif word == "status":
            out["status_lines"].append(rest)
        elif word == "decision":
            out["decision_lines"].append(_dparse(ln))
        elif "=" in ln:
            for tok in ([x for x in ln.split(" ") if "=" in x] if ln.startswith("rows=") else [ln]):
                k, _, v = tok.partition("=")
                out[k] = int(v) if k in INTS + ("rows", "bytes") else v
        else:
            raise ValueError(f"summary line {n} cannot be read")
    return out
