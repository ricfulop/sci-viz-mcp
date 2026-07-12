#!/usr/bin/env bash
# Install the FreeCADMCP addon (vendored from neka-nat/freecad-mcp) into
# FreeCAD's user Mod directory, and print the Cursor mcp.json snippet.
#
# Usage:
#   ./install_freecad_mcp.sh                  # symlink addon into FreeCAD Mod
#   ./install_freecad_mcp.sh --copy            # copy instead of symlink
#   ./install_freecad_mcp.sh --update-vendor   # refresh freecad_mcp/addon from GitHub
#   ./install_freecad_mcp.sh --update          # --update-vendor then reinstall
#
# Prerequisites:
#   - FreeCAD 1.0+ installed (macOS: brew install --cask freecad)
#   - uv / uvx on PATH for the Cursor MCP bridge (https://docs.astral.sh/uv/)

set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
ADDON_SRC="$ROOT/freecad_mcp/addon"
MODE="symlink"
DO_VENDOR=0
DO_INSTALL=1
UPSTREAM_URL="https://github.com/neka-nat/freecad-mcp.git"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --copy) MODE="copy"; shift ;;
    --symlink) MODE="symlink"; shift ;;
    --update-vendor) DO_VENDOR=1; DO_INSTALL=0; shift ;;
    --update) DO_VENDOR=1; DO_INSTALL=1; shift ;;
    -h|--help)
      sed -n '2,14p' "$0"; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

detect_mod_dir() {
  local support="${HOME}/Library/Application Support/FreeCAD"
  # Prefer versioned FreeCAD 1.1 / 1.0 paths (macOS app builds).
  for v in v1-1 v1-0; do
    if [[ -d "$support/$v" ]] || [[ -d /Applications/FreeCAD.app ]]; then
      echo "$support/$v/Mod"
      return
    fi
  done
  # Linux / fallback
  for d in \
      "${HOME}/.local/share/FreeCAD/v1-1/Mod" \
      "${HOME}/.local/share/FreeCAD/Mod" \
      "${HOME}/.FreeCAD/Mod"
  do
    if [[ -d "$(dirname "$d")" ]]; then
      echo "$d"
      return
    fi
  done
  # Default: FreeCAD 1.1 macOS layout (created on first install)
  echo "$support/v1-1/Mod"
}

if [[ $DO_VENDOR -eq 1 ]]; then
  echo "▸ refreshing vendored addon from $UPSTREAM_URL"
  TMP="$(mktemp -d)"
  git clone --depth 1 "$UPSTREAM_URL" "$TMP/freecad-mcp"
  COMMIT="$(git -C "$TMP/freecad-mcp" rev-parse HEAD)"
  rm -rf "$ADDON_SRC"
  mkdir -p "$(dirname "$ADDON_SRC")"
  cp -R "$TMP/freecad-mcp/addon/FreeCADMCP" "$ADDON_SRC"
  cp "$TMP/freecad-mcp/LICENSE" "$ROOT/freecad_mcp/LICENSE"
  rm -rf "$TMP"
  NOTICE="$ROOT/freecad_mcp/THIRD_PARTY_NOTICE.md"
  if [[ -f "$NOTICE" ]]; then
    # Rewrite the pinned-commit line in place.
    if grep -q 'Pinned commit:' "$NOTICE"; then
      sed -i.bak "s/Pinned commit: \`.*/Pinned commit: \`$COMMIT\`/" "$NOTICE"
      rm -f "${NOTICE}.bak"
    fi
  fi
  echo "✓ vendored addon at $ADDON_SRC (commit $COMMIT)"
fi

if [[ $DO_INSTALL -eq 0 ]]; then
  exit 0
fi

if [[ ! -f "$ADDON_SRC/Init.py" && ! -f "$ADDON_SRC/InitGui.py" ]]; then
  echo "error: addon source missing at $ADDON_SRC" >&2
  echo "       run: ./install_freecad_mcp.sh --update-vendor" >&2
  exit 1
fi

MOD_DIR="$(detect_mod_dir)"
DEST="$MOD_DIR/FreeCADMCP"
mkdir -p "$MOD_DIR"

if [[ -e "$DEST" || -L "$DEST" ]]; then
  echo "▸ removing existing $DEST"
  rm -rf "$DEST"
fi

if [[ "$MODE" == "symlink" ]]; then
  echo "▸ symlinking $ADDON_SRC → $DEST"
  ln -s "$ADDON_SRC" "$DEST"
else
  echo "▸ copying $ADDON_SRC → $DEST"
  cp -R "$ADDON_SRC" "$DEST"
fi

UVX="$(command -v uvx || true)"
if [[ -z "$UVX" ]]; then
  UVX="uvx"
  echo "WARNING: uvx not on PATH — install uv (https://docs.astral.sh/uv/) before using Cursor."
fi

cat <<EOF

✓ FreeCADMCP addon installed ($MODE).

  Addon:     $DEST
  FreeCAD:   restart FreeCAD, then Workbench → "MCP Addon" → Start RPC Server
             (or enable Auto-Start Server in the MCP menu)

  Cursor ~/.cursor/mcp.json entry:

    "freecad": {
      "command": "$UVX",
      "args": ["freecad-mcp"]
    }

  Or merge automatically:

    .venv/bin/python scripts/generate_mcp_config.py --servers freecad --write

  Then reload MCP servers in Cursor.
EOF
