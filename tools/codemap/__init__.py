"""codemap: library API. Stdlib only. Each name is imported from its module on first use."""
from importlib import import_module

_WHERE = {
    "load_config": "config", "python_minor": "config", "tool_tree": "config", "tool_tree_dirty": "config",
    "rebuild_refusal": "config", "rebuild_command": "config", "remake_command": "config",
    "write_map": "mapfile", "read_map": "mapfile", "health_of": "mapfile", "store_map": "mapfile", "commit": "mapfile",
    "find_cache_map": "mapfile", "add_decision": "mapfile",
    "write_summary": "summary", "parse_summary": "summary", "carry_decisions": "summary", "det_sha256": "summary",
    "s2_sha256": "summary", "s3_sha256": "summary", "full_sha256": "summary",
}
__all__ = sorted(_WHERE)


def __getattr__(name):
    if name not in _WHERE:
        raise AttributeError(f"module 'codemap' has no attribute {name!r}")
    return getattr(import_module(f".{_WHERE[name]}", __name__), name)
