#!/usr/bin/env bash
# One-shot setup for sci-viz-mcp.
#
#   ./install.sh            # python venv + deps + node builds
#   ./install.sh --minimal  # python only (skip ray_optics / pixinsight node builds)
#
# Afterwards run:  .venv/bin/python scripts/generate_mcp_config.py
# and paste the output into ~/.cursor/mcp.json (or your MCP client's config).

set -euo pipefail
cd "$(dirname "$0")"

MINIMAL=0
[[ "${1:-}" == "--minimal" ]] && MINIMAL=1

echo "==> sci-viz-mcp setup in $(pwd)"

# ── Python ───────────────────────────────────────────────────────────────────
if ! command -v python3 >/dev/null; then
  echo "ERROR: python3 not found (need >= 3.10)"; exit 1
fi

if [[ ! -d .venv ]]; then
  echo "==> Creating .venv"
  python3 -m venv .venv
fi
echo "==> Installing Python dependencies"
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -r requirements.txt

# ── Node (ray_optics_mcp + pixinsight_mcp) ───────────────────────────────────
if [[ $MINIMAL -eq 0 ]]; then
  if command -v npm >/dev/null; then
    echo "==> Building ray_optics_mcp vendor (node-canvas)"
    (cd ray_optics_mcp/vendor && npm install --no-audit --no-fund)
    echo "==> Building pixinsight_mcp"
    (cd pixinsight_mcp && npm install --no-audit --no-fund && npm run build)
  else
    echo "WARNING: npm not found — skipping ray_optics_mcp and pixinsight_mcp."
    echo "         Install Node.js >= 18 and re-run, or use --minimal."
  fi
fi

# ── Smoke checks ─────────────────────────────────────────────────────────────
echo "==> Smoke checks"
.venv/bin/python - <<'PY'
import importlib
for mod in ["ase", "pymatgen", "matplotlib", "numpy", "h5py"]:
    importlib.import_module(mod)
    print(f"  ok  {mod}")
for opt in ["ovito", "mph", "yaml", "aiohttp"]:
    try:
        importlib.import_module(opt)
        print(f"  ok  {opt}")
    except ImportError:
        print(f"  --  {opt} (optional, not installed)")
PY

echo
echo "==> Done. Next steps:"
echo "  1. .venv/bin/python scripts/generate_mcp_config.py"
echo "  2. Paste the output into ~/.cursor/mcp.json and restart your MCP client."
echo "  3. Optional commercial integrations:"
echo "       - COMSOL:     comsol_mcp needs a licensed COMSOL install (see comsol_mcp/README_SCIVIZ.md)"
echo "       - PixInsight: run pjsr/pixinsight-mcp-watcher.js inside PixInsight (see pixinsight_mcp/README_SCIVIZ.md)"
echo "       - Blender:    ./install_blender_foundation_mcp.sh && ./install_sciviz_addon.sh"
