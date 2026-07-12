"""
Shared helpers for stdio MCP servers in sci-viz-mcp.

Keeps JSON-RPC on stdout clean (no matplotlib/logging noise) and provides
small validation utilities reused across servers.
"""

from __future__ import annotations

import logging
import os
import sys
import warnings
from pathlib import Path


def configure_stdio_logging(level: int = logging.INFO) -> None:
    """Send all logging to stderr so stdout stays JSON-RPC only."""
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(
            level=level,
            stream=sys.stderr,
            format="%(name)s %(levelname)s: %(message)s",
        )
    else:
        for handler in root.handlers:
            # Embedding hosts such as pytest own capture streams whose lifetime
            # is shorter than the process. Rebinding those handlers makes them
            # point at closed files after a capture phase. Only redirect a
            # conventional handler that is explicitly writing to stdout.
            if (
                hasattr(handler, "setStream")
                and getattr(handler, "stream", None) in {sys.stdout, sys.__stdout__}
            ):
                handler.setStream(sys.stderr)


def configure_matplotlib_for_mcp(cache_dir: Path | None = None) -> None:
    """
    Prepare matplotlib for MCP use: writable cache dir, warnings on stderr.

    Call before importing matplotlib in MCP server entrypoints.
    """
    if cache_dir is None:
        cache_dir = Path(__file__).resolve().parent / ".matplotlib_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(cache_dir))

    warnings.filterwarnings("ignore", category=UserWarning, module="matplotlib")

    def _showwarning(message, category, filename, lineno, file=None, line=None):
        sys.stderr.write(warnings.formatwarning(message, category, filename, lineno, line))

    warnings.showwarning = _showwarning


def is_text_mph_placeholder(path: Path) -> bool:
    """
    Return True if path looks like a repo text spec, not a COMSOL binary .mph.

    Real COMSOL models are binary (often ZIP-based) and are not ASCII comments.
    """
    if not path.exists():
        return False
    if path.stat().st_size < 8192:
        head = path.read_bytes()[:256]
        if head.startswith(b"#") or head.startswith(b"PLACEHOLDER"):
            return True
        # Tiny files without null bytes are almost never real models
        if b"\x00" not in head and path.stat().st_size < 4096:
            try:
                head.decode("utf-8")
                return True
            except UnicodeDecodeError:
                pass
    return False


def cursor_safe_tool_name(name: str) -> str:
    """Cursor MCP allows only [A-Za-z0-9_]; map namespace.action → namespace_action."""
    return name.replace(".", "_")


def resolve_tool_name(name: str, tools: dict) -> str:
    """Resolve legacy dotted tool names to underscore registry keys."""
    if name in tools:
        return name
    underscored = cursor_safe_tool_name(name)
    if underscored in tools:
        return underscored
    return name


def validate_comsol_mph(path: Path) -> None:
    """Raise ValueError with an actionable message if path is not a real .mph."""
    if not path.exists():
        raise ValueError(f"COMSOL model not found: {path}")
    if is_text_mph_placeholder(path):
        raise ValueError(
            f"{path} is a text placeholder/spec, not a COMSOL Multiphysics .mph file. "
            "Open COMSOL Desktop, build or open the model, save as .mph, then pass "
            "model_path=<absolute path to that file> to comsol_open_or_create_model."
        )
