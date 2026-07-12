#!/usr/bin/env bash
# One-shot setup for sci-viz-mcp.
#
#   ./install.sh                         # python venv + deps + node builds
#   ./install.sh --minimal               # python only
#   ./install.sh --with-picogk           # also install local .NET 9 + build runner
#   ./install.sh --with-picogk --sync-picogk
#   ./install.sh --with-astro             # Astropy + POPPY + AOtools
#   ./install.sh --with-design            # Optiland
#
# Afterwards run:  .venv/bin/python scripts/generate_mcp_config.py
# and paste the output into ~/.cursor/mcp.json (or your MCP client's config).

set -euo pipefail
cd "$(dirname "$0")"

MINIMAL=0
WITH_PICOGK=0
SYNC_PICOGK=0
INCLUDE_UNLICENSED=0
WITH_ASTRO=0
WITH_DESIGN=0

for arg in "$@"; do
  case "$arg" in
    --minimal) MINIMAL=1 ;;
    --with-picogk) WITH_PICOGK=1 ;;
    --sync-picogk) WITH_PICOGK=1; SYNC_PICOGK=1 ;;
    --include-unlicensed-picogk) INCLUDE_UNLICENSED=1 ;;
    --with-astro) WITH_ASTRO=1 ;;
    --with-design) WITH_DESIGN=1 ;;
    *)
      echo "ERROR: unknown option $arg"
      exit 2
      ;;
  esac
done

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
if [[ $WITH_ASTRO -eq 1 ]]; then
  echo "==> Installing astronomy and adaptive-optics extras"
  .venv/bin/pip install --quiet -r requirements-astro.txt
fi
if [[ $WITH_DESIGN -eq 1 ]]; then
  echo "==> Installing optical-design extras"
  .venv/bin/pip install --quiet -r requirements-design.txt
fi

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

# ── .NET 9 + PicoGK (optional) ───────────────────────────────────────────────
if [[ $WITH_PICOGK -eq 1 ]]; then
  DOTNET_BIN="$(command -v dotnet || true)"
  if [[ -z "$DOTNET_BIN" && -x .dotnet/dotnet ]]; then
    DOTNET_BIN="$PWD/.dotnet/dotnet"
  fi
  if [[ -z "$DOTNET_BIN" ]]; then
    if ! command -v curl >/dev/null; then
      echo "ERROR: curl is required to install the local .NET 9 SDK."
      exit 1
    fi
    echo "==> Installing local .NET 9 SDK"
    mkdir -p output/installers .dotnet
    curl -fsSL https://dot.net/v1/dotnet-install.sh \
      -o output/installers/dotnet-install.sh
    bash output/installers/dotnet-install.sh \
      --channel 9.0 --install-dir "$PWD/.dotnet" --no-path
    DOTNET_BIN="$PWD/.dotnet/dotnet"
  fi

  DOTNET_MAJOR="$("$DOTNET_BIN" --version | cut -d. -f1)"
  if [[ "$DOTNET_MAJOR" -lt 9 ]]; then
    echo "ERROR: PicoGK 2.2 requires .NET 9; found $("$DOTNET_BIN" --version)."
    exit 1
  fi

  echo "==> Building PicoGK runner"
  mkdir -p .nuget/packages output/dotnet-home
  DOTNET_CLI_HOME="$PWD/output/dotnet-home" \
  DOTNET_CLI_TELEMETRY_OPTOUT=1 \
  NUGET_PACKAGES="$PWD/.nuget/packages" \
  "$DOTNET_BIN" build picogk_mcp/runner/SciViz.PicoGK.Runner.csproj \
    --configuration Release --nologo --verbosity minimal

  if [[ $SYNC_PICOGK -eq 1 ]]; then
    echo "==> Synchronizing locked LEAP 71 source stack"
    SYNC_ARGS=()
    if [[ $INCLUDE_UNLICENSED -eq 1 ]]; then
      SYNC_ARGS+=(--include-unlicensed)
    fi
    .venv/bin/python scripts/sync_picogk_stack.py "${SYNC_ARGS[@]}"
  fi
fi

# ── Smoke checks ─────────────────────────────────────────────────────────────
echo "==> Smoke checks"
.venv/bin/python - <<'PY'
import importlib
for mod in ["ase", "pymatgen", "matplotlib", "numpy", "h5py", "prysm", "poke"]:
    importlib.import_module(mod)
    print(f"  ok  {mod}")
for opt in ["ovito", "mph", "yaml", "aiohttp"]:
    try:
        importlib.import_module(opt)
        print(f"  ok  {opt}")
    except ImportError:
        print(f"  --  {opt} (optional, not installed)")
PY

if [[ $WITH_ASTRO -eq 1 ]]; then
  .venv/bin/python - <<'PY'
import importlib
for mod in ["aotools", "astropy", "hcipy", "poppy"]:
    importlib.import_module(mod)
    print(f"  ok  {mod}")
PY
fi

if [[ $WITH_DESIGN -eq 1 ]]; then
  .venv/bin/python - <<'PY'
import optiland
print("  ok  optiland")
PY
fi

if [[ $WITH_PICOGK -eq 1 ]]; then
  PICOGK_MCP_DOTNET="$DOTNET_BIN" .venv/bin/python - <<'PY'
from picogk_mcp import PicoGKBackend
health = PicoGKBackend().health()
assert health["dotnet_version"], health
assert health["native_runtime_supported"], health
print(f"  ok  PicoGK {health['picogk_version']} via .NET {health['dotnet_version']}")
PY
fi

echo
echo "==> Done. Next steps:"
echo "  1. .venv/bin/python scripts/generate_mcp_config.py"
echo "  2. Paste the output into ~/.cursor/mcp.json and restart your MCP client."
echo "  3. Optional commercial integrations:"
echo "       - COMSOL:     comsol_mcp needs a licensed COMSOL install (see comsol_mcp/README_SCIVIZ.md)"
echo "       - PixInsight: run pjsr/pixinsight-mcp-watcher.js inside PixInsight (see pixinsight_mcp/README_SCIVIZ.md)"
echo "       - Blender:    ./install_blender_foundation_mcp.sh && ./install_sciviz_addon.sh"
echo "       - FreeCAD:    ./install_freecad_mcp.sh  (then Start RPC Server in FreeCAD)"
echo "  4. Optional PicoGK full stack:"
echo "       ./install.sh --with-picogk --sync-picogk"
