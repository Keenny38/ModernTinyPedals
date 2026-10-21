"""Module data global (minfo): new code takes it from its context (ctx.minfo, see neopedal/context.py), so the
modules importing the global never grow in number (ratchet, lower when moving a module to its context)"""

import ast
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent.parent / "neopedal"
# Modules importing minfo global: lower when a module reads ctx.minfo instead (never raise)
MAX_GLOBAL_MINFO_MODULES = 132


def imports_global_minfo(path: Path) -> bool:
    """Whether module imports minfo from module_info (module or function level)"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[-1] == "module_info":
            if any(alias.name == "minfo" for alias in node.names):
                return True
    return False


def global_minfo_modules() -> list[str]:
    return sorted(path.relative_to(PACKAGE).as_posix() for path in PACKAGE.rglob("*.py")
                  if path.name != "module_info.py" and imports_global_minfo(path))


def test_global_minfo_imports_never_grow():
    found = global_minfo_modules()
    assert len(found) <= MAX_GLOBAL_MINFO_MODULES, (
        f"{len(found)} modules import minfo global (max {MAX_GLOBAL_MINFO_MODULES}): take it from ctx.minfo "
        "(widget, DataModule & PageBackend have ctx)")


def test_mapping_module_writes_to_its_context():
    """Mapping module: output from its context (tests hand a fake ModuleInfo), no global import"""
    assert "module/module_mapping.py" not in global_minfo_modules()


def test_scanner_finds_imports():
    assert imports_global_minfo(PACKAGE / "widget" / "track_map.py")
    assert not imports_global_minfo(PACKAGE / "context.py")


def test_context_reads_found_by_module_scan():
    """Data read through a context (self.ctx.minfo.<field>) counts for module dependencies (on demand modules,
    module page), as minfo.<field> does"""
    from neopedal.module_control import MODULE_PACKAGE, CodeScan, scan_code

    def reads():
        return context.ctx.minfo.mapping, context.minfo.delta  # noqa: F821

    assert scan_code(reads.__code__, "test", False)[0] == {"mapping", "delta"}
    assert "mapping" in CodeScan().fields_of(f"{MODULE_PACKAGE}.module_mapping", MODULE_PACKAGE)
