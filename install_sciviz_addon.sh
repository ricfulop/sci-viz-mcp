#!/usr/bin/env bash
# Install the SciViz Blender add-on into the user extensions directory.
#
# Default mode is symlink so edits in this repo propagate immediately on
# Blender restart. Pass --copy for a one-shot copy install instead.
#
# Usage:
#   ./install_sciviz_addon.sh                # symlink into Blender 5.1
#   ./install_sciviz_addon.sh --copy          # copy
#   ./install_sciviz_addon.sh --version 5.1   # pick a specific Blender
#   ./install_sciviz_addon.sh --uninstall

set -euo pipefail

MODE="symlink"
BLENDER_VERSION=""
ACTION="install"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --copy) MODE="copy"; shift ;;
        --symlink) MODE="symlink"; shift ;;
        --version) BLENDER_VERSION="$2"; shift 2 ;;
        --uninstall) ACTION="uninstall"; shift ;;
        -h|--help)
            sed -n '2,12p' "$0"; exit 0 ;;
        *) echo "unknown arg: $1"; exit 1 ;;
    esac
done

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
SRC="$REPO_DIR/sciviz_blender_addon"

if [[ ! -d "$SRC" ]]; then
    echo "error: source directory not found: $SRC" >&2
    exit 1
fi

case "$(uname -s)" in
    Darwin) BASE="$HOME/Library/Application Support/Blender" ;;
    Linux)  BASE="$HOME/.config/blender" ;;
    *)      echo "error: unsupported OS $(uname -s)" >&2; exit 1 ;;
esac

if [[ -z "$BLENDER_VERSION" ]]; then
    BLENDER_VERSION="$(ls -1 "$BASE" 2>/dev/null \
        | grep -E '^[0-9]+\.[0-9]+$' \
        | sort -V \
        | tail -1)"
fi

if [[ -z "$BLENDER_VERSION" ]]; then
    echo "error: no Blender version directory found under $BASE" >&2
    echo "       launch Blender once, then re-run this script." >&2
    exit 1
fi

EXT_DIR="$BASE/$BLENDER_VERSION/extensions/user_default"
mkdir -p "$EXT_DIR"
DEST="$EXT_DIR/sciviz"

if [[ "$ACTION" == "uninstall" ]]; then
    if [[ -e "$DEST" || -L "$DEST" ]]; then
        rm -rf "$DEST"
        echo "uninstalled $DEST"
    else
        echo "nothing to remove at $DEST"
    fi
    exit 0
fi

if [[ -e "$DEST" || -L "$DEST" ]]; then
    rm -rf "$DEST"
fi

case "$MODE" in
    symlink)
        ln -s "$SRC" "$DEST"
        echo "symlinked: $DEST -> $SRC" ;;
    copy)
        cp -R "$SRC" "$DEST"
        echo "copied:    $SRC -> $DEST" ;;
esac

cat <<EOF

Next steps inside Blender $BLENDER_VERSION:
  1. Edit > Preferences > Get Extensions > Repositories: ensure "User Default" is enabled.
  2. Edit > Preferences > Add-ons: search "sciviz", check the box.
  3. View3D sidebar (N-key) > "SciViz" tab.

ASE / numpy must live in Blender's bundled Python:
  /Applications/Blender.app/Contents/Resources/$BLENDER_VERSION/python/bin/python3.* -m pip install ase numpy
EOF
