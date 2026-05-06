"""
Root-level conftest.py.

Stubs the gateway package and pre-loads the napcat adapter sub-modules so
that pytest can set up the root package (hermes-napcat/__init__.py) without
hitting an ImportError from the gateway or the relative .adapter import.
"""

from __future__ import annotations

import importlib.util as _ilu
import pathlib
import sys
import types

_root = pathlib.Path(
    __file__
).parent.parent  # E:\project\hermes-napcat\ (project root, one level up from tests/)

# ---------------------------------------------------------------------------
# 1. Stub the gateway package (not installed in the test environment)
# ---------------------------------------------------------------------------


def _stub(name: str) -> types.ModuleType:
    if name not in sys.modules:
        sys.modules[name] = types.ModuleType(name)
    return sys.modules[name]


for _m in (
    "gateway",
    "gateway.platforms",
    "gateway.platforms.base",
    "gateway.config",
    "gateway.platforms.helpers",
):
    _stub(_m)

# Provide the minimal symbols that adapter.py / __init__.py import from gateway.
_gpb = sys.modules["gateway.platforms.base"]
for _attr in (
    "BasePlatformAdapter",
    "MessageEvent",
    "MessageType",
    "ProcessingOutcome",
    "SendResult",
    "_ssrf_redirect_guard",
    "cache_audio_from_url",
    "cache_image_from_url",
):
    if not hasattr(_gpb, _attr):
        setattr(_gpb, _attr, type(_attr, (), {}))

_gc = sys.modules["gateway.config"]
for _attr in ("Platform", "PlatformConfig"):
    if not hasattr(_gc, _attr):
        setattr(_gc, _attr, type(_attr, (), {}))

_gph = sys.modules["gateway.platforms.helpers"]
if not hasattr(_gph, "strip_markdown"):
    _gph.strip_markdown = lambda s: s  # type: ignore[attr-defined]

# ---------------------------------------------------------------------------
# 2. Create the 'napcat' package alias and pre-load source modules
# ---------------------------------------------------------------------------

_PKG = "napcat"

_pkg_mod = types.ModuleType(_PKG)
_pkg_mod.__path__ = [str(_root)]  # type: ignore[assignment]
_pkg_mod.__package__ = _PKG
sys.modules[_PKG] = _pkg_mod


def _load(filename: str, short: str) -> types.ModuleType:
    """Import *filename* from the project root as 'napcat.<short>'."""
    full = f"{_PKG}.{short}"
    if full in sys.modules:
        return sys.modules[full]
    spec = _ilu.spec_from_file_location(full, _root / filename)
    mod = _ilu.module_from_spec(spec)  # type: ignore[arg-type]
    mod.__package__ = _PKG
    sys.modules[full] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    setattr(_pkg_mod, short, mod)
    return mod


# Load in dependency order (adapter excluded — needs full gateway runtime)
_load("constants.py", "constants")
_load("utils.py", "utils")
_load("message_builder.py", "message_builder")
_load("event_parser.py", "event_parser")
_load("group_commands.py", "group_commands")
_load("observability.py", "observability")

# ---------------------------------------------------------------------------
# 3. Stub napcat.adapter so that __init__.py's relative import succeeds
#    when pytest's Package.setup() tries to import the root __init__.py.
# ---------------------------------------------------------------------------

_adapter_stub = types.ModuleType(f"{_PKG}.adapter")
_adapter_stub.NapCatAdapter = type("NapCatAdapter", (), {})  # type: ignore[attr-defined]
_adapter_stub.check_napcat_requirements = lambda: True  # type: ignore[attr-defined]
sys.modules[f"{_PKG}.adapter"] = _adapter_stub
setattr(_pkg_mod, "adapter", _adapter_stub)

# Pre-import the root __init__.py with the correct package context so that
# `from .adapter import NapCatAdapter` resolves to our stub above.
_init_spec = _ilu.spec_from_file_location(
    _PKG,
    _root / "__init__.py",
)
_init_mod = _ilu.module_from_spec(_init_spec)  # type: ignore[arg-type]
_init_mod.__package__ = _PKG
# Overwrite the simple pkg_mod with the real (but adapter-stubbed) __init__
sys.modules[_PKG] = _init_mod
_init_spec.loader.exec_module(_init_mod)  # type: ignore[union-attr]
# Re-attach the pre-loaded submodules (exec might have cleared __dict__)
for _short in (
    "constants",
    "utils",
    "message_builder",
    "event_parser",
    "group_commands",
    "observability",
    "adapter",
):
    _full = f"{_PKG}.{_short}"
    if _full in sys.modules:
        setattr(_init_mod, _short, sys.modules[_full])
