#!/usr/bin/env python3
"""Synchronize or inspect the exact LEAP 71 revisions in stack.lock.json."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from picogk_mcp.stack_manager import StackManager


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--modules",
        default="",
        help="Comma-separated module subset (default: all).",
    )
    parser.add_argument(
        "--include-unlicensed",
        action="store_true",
        help="Allow the simulation example, whose repository has no declared license.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace cached repositories that are not at the locked commit.",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Only report cache status; do not fetch.",
    )
    args = parser.parse_args()

    manager = StackManager()
    modules = (
        [item.strip() for item in args.modules.split(",") if item.strip()]
        or None
    )
    result = (
        manager.status(modules)
        if args.status
        else manager.sync(
            modules,
            include_unlicensed=args.include_unlicensed,
            force=args.force,
        )
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
