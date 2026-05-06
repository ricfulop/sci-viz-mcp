#!/usr/bin/env bash
# Install the official Blender Foundation MCP server.
#
# Source repo: https://projects.blender.org/lab/blender_mcp
# This script clones the repo (or updates an existing clone), creates a
# dedicated venv, and installs the `blender-mcp` package in editable mode.
# It then prints the snippet to drop into ~/.cursor/mcp.json so Cursor
# launches this server instead of the community PyPI `uvx blender-mcp`.
#
# Usage:
#   ./install_blender_foundation_mcp.sh                 # default location
#   ./install_blender_foundation_mcp.sh --dest <dir>    # custom location
#   ./install_blender_foundation_mcp.sh --update        # git pull + reinstall
#
# Prerequisites:
#   - Python 3.10+
#   - Git
#   - The Foundation MCP add-on installed inside Blender 5.1+ (drag-and-drop
#     install from https://www.blender.org/lab/mcp-server/).

set -euo pipefail

DEST="${HOME}/voltivity/blender_mcp_foundation"
ACTION="install"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --dest) DEST="$2"; shift 2 ;;
        --update) ACTION="update"; shift ;;
        -h|--help)
            sed -n '2,16p' "$0"; exit 0 ;;
        *) echo "unknown arg: $1"; exit 1 ;;
    esac
done

REPO_URL="https://projects.blender.org/lab/blender_mcp"

if [[ ! -d "$DEST/.git" ]]; then
    echo "▸ cloning $REPO_URL → $DEST"
    git clone "$REPO_URL" "$DEST"
elif [[ "$ACTION" == "update" ]]; then
    echo "▸ updating $DEST"
    git -C "$DEST" pull --ff-only
fi

if [[ ! -d "$DEST/.venv" ]]; then
    echo "▸ creating venv at $DEST/.venv"
    python3 -m venv "$DEST/.venv"
fi

echo "▸ upgrading pip and installing blender-mcp"
"$DEST/.venv/bin/pip" install --upgrade pip >/dev/null
"$DEST/.venv/bin/pip" install --quiet -e "$DEST/mcp"

ENTRY="$DEST/.venv/bin/blender-mcp"
if [[ ! -x "$ENTRY" ]]; then
    echo "error: $ENTRY missing after install" >&2
    exit 1
fi

cat <<EOF

✓ Foundation MCP server installed.

  Entry point:   $ENTRY
  Help:          $ENTRY --help

Next steps:

  1. Add or replace the "blender" entry in ~/.cursor/mcp.json:

       "blender": {
         "command": "$ENTRY",
         "args": ["--transport", "stdio"]
       }

  2. Make sure the Foundation MCP add-on is enabled inside Blender
     (View3D > N > BlenderMCP > Connect, status pill should read "Connected").

  3. Reload MCP servers in Cursor (Cmd+Shift+P → "Reload MCP Servers")
     or quit and reopen Cursor.
EOF
