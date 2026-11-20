"""The full map: rows, caps, cache store by sha, lock, find_cache_map, decide. Stdlib only apart from summary."""
import fcntl
import hashlib
import os
import re
import time
from collections import Counter

from .summary import (HEADER_KEYS, KEY_RE, MAP_HEAD, clean_field, det_sha256, full_sha256, health_of, is_status,
                      map_text, parse_summary, s2_sha256, s3_sha256, snip12, write_summary)

MAX_ROWS, MAX_BYTES, TOO_MANY = 8000, 1048576, 400
__all__ = ["health_of", "write_map", "read_map", "store_map", "commit", "find_cache_map", "add_decision"]


def read_map(text):
    """(header dict, rows sorted). Rows are 9-tuples: hop kind file:line relation function seed source verdict snippet."""
    lines = text.split("\n")
    if lines[-1] == "":
        lines.pop()
    if not lines or not lines[0].startswith(MAP_HEAD):
        raise ValueError("map header is not '# codemap v1 ...'")
    parts = re.split(" (?=(?:" + "|".join(HEADER_KEYS) + ")=)", lines[0][len(MAP_HEAD):])
    rows = [tuple(ln.split("\t")) for ln in lines[1:]]
    for n, r in enumerate(rows, 2):
        if len(r) != 9:
            raise ValueError(f"map line {n} has {len(r)} fields, not 9")
    return {k: v for k, _, v in (p.partition("=") for p in parts)}, sorted(rows)


def _caps(n_rows, size, rows):
    if n_rows > MAX_ROWS or size > MAX_BYTES:
        big = ", ".join(f"{n}={c}" for n, c in Counter(r[5] for r in rows if not is_status(r)).most_common(5))
        raise ValueError(f"map would be {n_rows} rows and {size} bytes; caps {MAX_ROWS} rows and {MAX_BYTES} bytes; "
                         f"5 biggest names: {big}")


def write_map(header, rows, names):
    """Map text. Adds the no-hit: and too-many: rows, sets health from the rows, refuses past the caps (never cuts)."""
    rows = [tuple(clean_field(f) for f in r) for r in rows if not r[1].startswith(("no-hit:", "too-many:"))]
    seen = Counter(r[5] for r in rows if not is_status(r))
    for n in names:
        if seen[n] == 0:
            rows.append(("-", f"no-hit:{n}", "-", "-", "-", "-", "s1", "-", "-"))
        elif seen[n] > TOO_MANY:
            rows.append(("-", f"too-many:{n} {seen[n]}", "-", "-", "-", "-", "s1", "-", "-"))
    text = map_text({**header, "names": ",".join(names), "health": health_of(rows)}, rows)
    _caps(len(rows), len(text.encode()), rows)
    return text


def _dir(cache_dir, key):
    if not re.fullmatch(KEY_RE, key):
        raise ValueError(f"bad design key {key!r}")
    return os.path.join(cache_dir, "maps", key)


def _put(path, data):
    """tmp + rename: a reader sees the old file or the whole new one, never half."""
    tmp = f"{path}.{os.getpid()}.{time.monotonic_ns()}.tmp"
    try:
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def store_map(cache_dir, key, text):
    """Content-addressed: `<cache>/maps/<key>/<full_sha256>.tsv`. The same text twice is one file."""
    data, folder = text.encode("utf-8"), _dir(cache_dir, key)
    _caps(text.count("\n") - 1, len(data), [])
    sha = hashlib.sha256(data).hexdigest()
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, sha + ".tsv")
    if not os.path.exists(path):
        _put(path, data)
    return sha


def _holder(fd):
    who = os.pread(fd, 32, 0).decode("ascii", "replace").strip()
    return who if who.isdigit() else "unknown"


def commit(cache_dir, key, map_text, summary_path, summary_text, lock_wait=60):
    """Under `summary.lock`: sweep old .tmp files, rename the cache map in, then the summary. Both whole, or neither."""
    s = parse_summary(summary_text)
    if s["key"] != key or s["full_sha256"] != full_sha256(map_text):
        raise ValueError("the summary does not name this key and this map")
    folder = _dir(cache_dir, key)
    os.makedirs(folder, exist_ok=True)
    os.makedirs(os.path.dirname(os.path.abspath(summary_path)), exist_ok=True)
    fd = os.open(os.path.join(folder, "summary.lock"), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        end = time.monotonic() + lock_wait
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= end:
                    raise ValueError(f"summary is locked by pid {_holder(fd)}") from None
                time.sleep(0.05)
        os.ftruncate(fd, 0)
        os.write(fd, str(os.getpid()).encode())
        sdir, sname = os.path.split(os.path.abspath(summary_path))
        for where, keep in ((folder, lambda n: n.endswith(".tmp")), (sdir, lambda n: n.startswith(sname + ".") and n.endswith(".tmp"))):
            for n in filter(keep, os.listdir(where)):
                os.unlink(os.path.join(where, n))
        store_map(cache_dir, key, map_text)
        _put(os.path.abspath(summary_path), summary_text.encode("utf-8"))
    finally:
        os.close(fd)


def _decided(rows, lines):
    """Rows a human decided: every kept-by: row, and a dropped: row that has a decision line (else it is an AI drop)."""
    keys = {(d["loc"], d["function"], d["sha12"]) for d in lines}
    return {(r[7].split(" ")[0], r[2], r[4] or "-", snip12(r)) for r in rows if r[7].startswith("kept-by:")
            or (r[7].startswith("dropped:") and (r[2], r[4] or "-", snip12(r)) in keys)}


def _refusal(name, text, s, cmd):
    """Why this fallback map cannot stand in for the summary, or None (table 1b: M2, field mismatch, decided rows, M8)."""
    try:
        header, rows = read_map(text)
    except ValueError:
        return "cannot be read"
    health = health_of(rows)
    if health != "ok":
        return f"cache map {name[:12]} is partial ({health.removeprefix('partial:')}); rebuild where every source answers: {cmd}".rstrip()
    for field, got, want in (("det_sha256", det_sha256(header, rows), s["det_sha256"]), ("s2_sha256", s2_sha256(rows), s["s2_sha256"]),
                             ("s3_sha256", s3_sha256(rows), s["s3_sha256"]), ("serena", header.get("serena", "-"), s["serena"]),
                             ("index", header.get("index", "-"), s["index"]), ("python", header.get("python", "-"), s["python"])):
        if got != want:
            return f"{field} {got[:12] if field.endswith('sha256') else got} is not {want[:12] if field.endswith('sha256') else want}"
    live = [d for d in s["decision_lines"] if not d["stale"]]
    decided = _decided(rows, live)
    if decided != {(d["verdict"], d["loc"], d["function"] or "-", d["sha12"]) for d in live}:
        return "decided rows differ from the summary's decision lines"
    drops = sum(1 for r in rows if r[7].startswith("dropped:") and (r[7].split(" ")[0], r[2], r[4] or "-", snip12(r)) not in decided)
    if drops:
        return f"holds {drops} AI dropped: rows the summary does not decide; only the full_sha256 map may hold AI drops"
    return None


def find_cache_map(cache_dir, summary_text, rebuild_cmd=""):
    """(path or None, reasons): the full_sha256 file if whole, else the first healthy map that matches (rule 21)."""
    s = parse_summary(summary_text)
    folder, own = _dir(cache_dir, s["key"]), s["full_sha256"] + ".tsv"
    names = sorted(n for n in os.listdir(folder) if n.endswith(".tsv")) if os.path.isdir(folder) else []
    reasons = []
    for name in ([own] if own in names else []) + ([] if s["health"] != "ok" else [n for n in names if n != own]):
        path = os.path.join(folder, name)
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except (OSError, UnicodeDecodeError):
            reasons.append(f"{name[:12]}: cannot be read")
            continue
        if name == own:
            why = None if full_sha256(text) == s["full_sha256"] else f"full_sha256 {full_sha256(text)[:12]} is not {s['full_sha256'][:12]}"
        else:
            why = _refusal(name, text, s, rebuild_cmd)
        if why is None:
            return path, reasons
        reasons.append(f"{name[:12]}: {why}")
    return None, reasons


def add_decision(summary_text, map_text, row, verdict, who, reason):
    """Library half of `codemap decide`: a human keeps or drops one s1w or s3 row. Returns (new_summary, new_map)."""
    s, (header, rows) = parse_summary(summary_text), read_map(map_text)
    kind = {"keep": "kept-by", "kept": "kept-by", "drop": "dropped", "dropped": "dropped"}.get(verdict)
    if kind is None or not who or " " in who or len(reason.split()) < 3:
        raise ValueError("decide needs keep or drop, a <who> with no space, and a reason of 3 or more words")
    hits = [i for i, r in enumerate(rows) if not is_status(r) and (r[2] == row if isinstance(row, str) else r == tuple(row))]
    if len(hits) != 1:
        raise ValueError(f"row {row} matches {len(hits)} rows; give an exact file:line")
    old = rows[hits[0]]
    if old[6] not in ("s1w", "s3"):
        raise ValueError(f"decide runs only on s1w and s3 rows; {old[2]} is {old[6]}")
    rows[hits[0]] = old[:7] + (f"{kind}:{who} {clean_field(reason)}",) + old[8:]
    new_map = write_map(header, rows, [n for n in header["names"].split(",") if n])
    dec = {"stale": False, "verdict": f"{kind}:{who}", "loc": old[2], "function": old[4] or "-", "sha12": snip12(old),
           "source": old[6], "reason": clean_field(reason)}
    inputs = {k: s[k] for k in ("config", "config_sha256", "tool_tree")}
    inputs.update(inventory=s["inventory"] == "yes", decisions=[dec])
    return write_summary(*read_map(new_map), s["key"], inputs, old_summary=summary_text), new_map
