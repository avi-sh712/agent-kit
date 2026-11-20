"""Scenario 54: no repo names in the package, stdlib-only import chain, every file at most 300 lines."""
import ast
import shutil
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
BANNED = ("backend/", "frontend/", "plugins/", "rm-", "reach", "8090", "decisions.py", "prompts/")  # design 10b: the 8 strings
SKIP = {"configs", "tests", "__pycache__"}
BUDGET = {"__init__.py": 30, "config.py": 150, "mapfile.py": 220, "summary.py": 220}
DIRECTION = {"summary": set(), "mapfile": {"summary"}, "config": {"summary"}}  # mapfile imports summary, never the reverse


def name_problems(root):
    """Every package file (py and not py) except configs/ and tests/, as lowercase text, for the 8 banned strings."""
    out = []
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.suffix == ".pyc" or SKIP & set(p.relative_to(root).parts[:-1]):
            continue
        text = p.read_text(encoding="utf-8", errors="replace").lower()
        out += [f"{p.relative_to(root)} holds {w!r}" for w in BANNED if w in text]
    return out


def chain_problems(root, start):
    """Follow the package-internal imports from `start`; every import must be stdlib or inside the package."""
    seen, todo, out = set(), list(start), []
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        tree = ast.parse((root / f"{name}.py").read_text(encoding="utf-8"))
        for fn in (n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))):
            out += [f"{name}: import inside {fn.name}" for n in ast.walk(fn) if isinstance(n, (ast.Import, ast.ImportFrom))]
        mine = set()
        for n in (n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))):
            mods = [a.name for a in n.names] if isinstance(n, ast.Import) else [n.module or ""]
            for mod in mods:
                if isinstance(n, ast.ImportFrom) and n.level:
                    mine |= {mod.split(".")[0]} if mod else {a.name for a in n.names}
                elif mod.split(".")[0] == "codemap":
                    mine |= {mod.split(".")[1]} if "." in mod else {a.name for a in n.names}
                elif mod.split(".")[0] not in sys.stdlib_module_names:
                    out.append(f"{name}: imports {mod}, which is not stdlib")
        todo += sorted(mine)
        if name in DIRECTION and mine - DIRECTION[name]:
            out.append(f"{name}: imports {sorted(mine - DIRECTION[name])}, against the import direction")
    return out


def starts(root):
    return ["__init__", "config", "mapfile", "summary"] + (["gatecheck"] if (root / "gatecheck.py").exists() else [])


def copy_pkg(tmp_path, name):
    dest = tmp_path / name
    shutil.copytree(PKG, dest, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return dest


def test_no_repo_names_stdlib_gate_path_and_300_lines(tmp_path):
    assert name_problems(PKG) == []
    assert chain_problems(PKG, starts(PKG)) == []
    for p in sorted(PKG.rglob("*")):
        if p.is_file() and p.suffix != ".pyc" and "__pycache__" not in p.parts:
            n = len(p.read_text(encoding="utf-8").splitlines())
            assert n <= 300, f"{p.relative_to(PKG)} has {n} lines"
            assert n <= (BUDGET.get(p.name, 300) if p.parent == PKG else 300), f"{p.name} is over its budget"
    for file, text in (("mapfile.py", "\n# reads backend/app\n"), ("README.md", "\nsee frontend/src\n"), ("pytest.ini", "\n# 8090\n")):
        copy = copy_pkg(tmp_path, f"plant-{file}")  # a planted string in a .py or a non-.py file fails the scan
        with open(copy / file, "a", encoding="utf-8") as f:
            f.write(text)
        assert name_problems(copy), file
    copy = copy_pkg(tmp_path, "plant-config")
    with open(copy / "configs" / "example.json", "a", encoding="utf-8") as f:
        f.write("backend/ reach")
    with open(copy / "tests" / "test_config.py", "a", encoding="utf-8") as f:
        f.write("# prompts/\n")
    assert name_problems(copy) == []  # configs/ and tests/ are not scanned


def test_the_import_checker_catches_plants(tmp_path):
    copy = copy_pkg(tmp_path, "pkg")
    with open(copy / "summary.py", "a", encoding="utf-8") as f:
        f.write("import requests\n\n\ndef late():\n    import json\n    return json\n")
    got = chain_problems(copy, starts(copy))
    assert "summary: imports requests, which is not stdlib" in got and "summary: import inside late" in got
    with open(copy / "summary.py", "a", encoding="utf-8") as f:
        f.write("from .mapfile import commit\n")  # the reverse direction
    assert any("against the import direction" in p for p in chain_problems(copy, starts(copy)))
