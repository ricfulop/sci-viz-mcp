#!/usr/bin/env python3
"""
comsol_mcp_server.py
MCP server for headless COMSOL Multiphysics control via the mph Java bridge.

Ported into sci-viz-mcp from the Flash-Physics-Twin project's comsol_mcp
(the comprehensive execution server). Compared to the original, this copy:
  - resolves the runs directory from COMSOL_MCP_RUNS_DIR (env) instead of a
    hardcoded repo-relative path
  - exposes the coupled EM+thermal+Flash and AC/DC coil export methods as
    MCP tools (they existed in comsol_api.py but were never registered)
  - stamps rendered PNGs with the Sci-Viz attribution footer

Implements the MCP JSON-RPC 2.0 protocol over stdio.
"""

import json
import os
import sys
import traceback
from pathlib import Path

_THIS_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(_THIS_DIR))
sys.path.insert(0, str(_THIS_DIR.parent))

from mcp_runtime import configure_stdio_logging, resolve_tool_name
from attribution import ATTRIBUTION_TEXT, stamp_image_file

configure_stdio_logging()

from comsol_api import ComsolBackend, validate_mph_file
from io_utils import ensure_run_dirs, load_yaml_params

# Runs directory: configurable so this server works for any project.
# Default keeps runs inside the sci-viz-mcp output folder.
RUNS_DIR = Path(os.environ.get(
    "COMSOL_MCP_RUNS_DIR",
    str(_THIS_DIR.parent / "output" / "comsol_runs"),
))

_backend = ComsolBackend()

# ── MCP JSON-RPC helpers ─────────────────────────────────────────────────────

def send_response(req_id, result=None, error=None):
    response = {"jsonrpc": "2.0", "id": req_id}
    if error is not None:
        response["error"] = error
    else:
        response["result"] = result if result is not None else {}
    sys.stdout.write(json.dumps(response) + "\n")
    sys.stdout.flush()


def send_error(req_id, code, message, data=None):
    error = {"code": code, "message": message}
    if data:
        error["data"] = data
    send_response(req_id, error=error)


def run_path(run_id: str) -> Path:
    return RUNS_DIR / run_id


# ── Tool handlers ────────────────────────────────────────────────────────────

def handle_open_or_create_model(args):
    rp = run_path(args["run_id"])
    ensure_run_dirs(rp)
    model_file = _backend.open_or_create(
        rp,
        template_path=args.get("template_path"),
        model_path=args.get("model_path"),
    )
    return {"status": "ok", "model_file": str(model_file)}


def handle_apply_inputs(args):
    rp = run_path(args["run_id"])
    inputs_dir = Path(args.get("inputs_dir") or (rp / "inputs"))
    params = load_yaml_params(inputs_dir)
    strict = bool(args.get("strict", True))
    _backend.apply_parameters(rp, params, strict=strict)
    return {"status": "ok", "applied": list(params.keys())}


def handle_build_geometry(args):
    _backend.build_geometry(run_path(args["run_id"]))
    return {"status": "ok"}


def handle_mesh(args):
    _backend.mesh(run_path(args["run_id"]), mesh_id=args.get("mesh_id"))
    return {"status": "ok"}


def handle_run_pipeline(args):
    pipeline = args.get("pipeline") or ["A", "B", "C", "D"]
    _backend.run_pipeline(run_path(args["run_id"]), pipeline)
    return {"status": "ok", "pipeline": pipeline}


def handle_run_study(args):
    _backend.run_study(run_path(args["run_id"]), args["study_id"])
    return {"status": "ok", "study_id": args["study_id"]}


def handle_export_fields(args):
    rp = run_path(args["run_id"])
    out = _backend.export_fields(
        rp,
        fmt=args.get("format") or "h5",
        fields=args.get("fields"),
        bias_voltage=float(args.get("bias_voltage", 0.0)),
        flash_enabled=bool(args.get("flash_enabled", True)),
        flash_params=args.get("flash_params"),
        synthetic_mode=args.get("synthetic_mode", "pipeline"),
    )
    return {"status": "ok", "outputs": out}


def handle_export_kpis(args):
    out = _backend.export_kpis(run_path(args["run_id"]))
    return {"status": "ok", "kpis_path": out}


def handle_export_em_coil_fields(args):
    rp = run_path(args["run_id"])
    out = _backend.export_em_coil_fields(
        rp,
        fmt=args.get("format") or "h5",
        coil_params=args.get("coil_params"),
    )
    return {"status": "ok", "outputs": out}


def handle_export_em_coil_kpis(args):
    out = _backend.export_em_coil_kpis(run_path(args["run_id"]))
    return {"status": "ok", "kpis_path": out}


def handle_export_coupled_fields(args):
    rp = run_path(args["run_id"])
    out = _backend.export_coupled_fields(
        rp,
        fmt=args.get("format") or "h5",
        em_mode=args.get("em_mode", "surrogate"),
        bias_voltage=float(args.get("bias_voltage", 0.0)),
        flash_enabled=bool(args.get("flash_enabled", True)),
        flash_params=args.get("flash_params"),
        em_params=args.get("em_params"),
        thermal_params=args.get("thermal_params"),
        synthetic_mode=args.get("synthetic_mode", "pipeline"),
    )
    return {"status": "ok", "outputs": out}


def handle_export_coupled_kpis(args):
    out = _backend.export_coupled_kpis(
        run_path(args["run_id"]),
        em_mode=args.get("em_mode", "surrogate"),
        thermal_params=args.get("thermal_params"),
        powder_region=args.get("powder_region"),
    )
    return {"status": "ok", "kpis_path": out}


def handle_render_png(args):
    out = _backend.render_png(run_path(args["run_id"]), plot_id=args["plot_id"])
    try:
        if Path(out).stat().st_size > 0:
            stamp_image_file(out)
    except Exception:
        pass
    return {"status": "ok", "png_path": out, "attribution": ATTRIBUTION_TEXT}


def handle_close_model(args):
    _backend.close(run_path(args["run_id"]))
    return {"status": "ok"}


def handle_health(args):
    """Check COMSOL/mph readiness without opening a model."""
    start_client = bool(args.get("start_client", False))
    template_default = os.environ.get("COMSOL_MCP_DEFAULT_TEMPLATE", "")
    template_path = Path(template_default) if template_default else None
    mph_ok = False
    mph_error = None
    comsol_version = None
    try:
        import mph  # noqa: F401
        mph_ok = True
    except ImportError as e:
        mph_error = f"mph not installed: {e}"

    comsol_running = False
    if mph_ok and start_client:
        try:
            client = _backend.client
            comsol_running = True
            comsol_version = str(client)
        except Exception as e:
            mph_error = str(e)

    template_status = "not_configured"
    template_note = None
    if template_path is not None:
        template_status = "missing"
        if template_path.exists():
            try:
                validate_mph_file(template_path)
                template_status = "valid_binary"
            except Exception as e:
                template_status = "placeholder_or_invalid"
                template_note = str(e)

    return {
        "status": "ok" if comsol_running else "degraded",
        "mph_installed": mph_ok,
        "comsol_client": comsol_running,
        "comsol_version": comsol_version,
        "mph_error": mph_error,
        "default_template": str(template_path) if template_path else None,
        "default_template_status": template_status,
        "default_template_note": template_note,
        "runs_dir": str(RUNS_DIR),
        "loaded_models": list(_backend._models.keys()),
    }


_RUN_ID_PROP = {"run_id": {"type": "string", "description": "Run identifier"}}

TOOLS = {
    "comsol_health": {
        "handler": handle_health,
        "description": "Check mph install and default template; set start_client=true to launch COMSOL",
        "inputSchema": {
            "type": "object",
            "properties": {
                "start_client": {
                    "type": "boolean",
                    "description": "If true, start COMSOL via mph (slow; use for diagnostics)",
                },
            },
        },
    },
    "comsol_open_or_create_model": {
        "handler": handle_open_or_create_model,
        "description": "Open an existing COMSOL model or create from template",
        "inputSchema": {
            "type": "object",
            "properties": {
                **_RUN_ID_PROP,
                "template_path": {"type": "string", "description": "Path to .mph template"},
                "model_path": {"type": "string", "description": "Path to existing .mph model"},
            },
            "required": ["run_id"],
        },
    },
    "comsol_apply_inputs": {
        "handler": handle_apply_inputs,
        "description": "Apply input parameters from YAML files to the COMSOL model",
        "inputSchema": {
            "type": "object",
            "properties": {
                **_RUN_ID_PROP,
                "inputs_dir": {"type": "string"},
                "strict": {"type": "boolean", "default": True},
            },
            "required": ["run_id"],
        },
    },
    "comsol_build_geometry": {
        "handler": handle_build_geometry,
        "description": "Build the model geometry",
        "inputSchema": {
            "type": "object",
            "properties": {**_RUN_ID_PROP},
            "required": ["run_id"],
        },
    },
    "comsol_mesh": {
        "handler": handle_mesh,
        "description": "Generate mesh for the model",
        "inputSchema": {
            "type": "object",
            "properties": {**_RUN_ID_PROP, "mesh_id": {"type": "string"}},
            "required": ["run_id"],
        },
    },
    "comsol_run_pipeline": {
        "handler": handle_run_pipeline,
        "description": "Run the full A->B->C->D simulation pipeline",
        "inputSchema": {
            "type": "object",
            "properties": {
                **_RUN_ID_PROP,
                "pipeline": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["run_id"],
        },
    },
    "comsol_run_study": {
        "handler": handle_run_study,
        "description": "Run a specific study",
        "inputSchema": {
            "type": "object",
            "properties": {**_RUN_ID_PROP, "study_id": {"type": "string"}},
            "required": ["run_id", "study_id"],
        },
    },
    "comsol_export_fields": {
        "handler": handle_export_fields,
        "description": "Export field data to HDF5 (with Flash physics DeltaB/chi fields)",
        "inputSchema": {
            "type": "object",
            "properties": {
                **_RUN_ID_PROP,
                "format": {"type": "string", "default": "h5"},
                "fields": {"type": "array", "items": {"type": "string"}},
                "bias_voltage": {"type": "number", "description": "DC bias voltage (V)"},
                "flash_enabled": {"type": "boolean", "default": True},
                "flash_params": {"type": "object", "description": "Override Flash physics params (DeltaG0, r_act, B_s, ...)"},
                "synthetic_mode": {"type": "string", "enum": ["pipeline", "science"]},
            },
            "required": ["run_id"],
        },
    },
    "comsol_export_kpis": {
        "handler": handle_export_kpis,
        "description": "Export KPIs to JSON",
        "inputSchema": {
            "type": "object",
            "properties": {**_RUN_ID_PROP},
            "required": ["run_id"],
        },
    },
    "comsol_export_em_coil_fields": {
        "handler": handle_export_em_coil_fields,
        "description": "Export AC/DC coil EM fields (B_mag, E_mag, Q_RF) via finite-solenoid surrogate",
        "inputSchema": {
            "type": "object",
            "properties": {
                **_RUN_ID_PROP,
                "format": {"type": "string", "default": "h5"},
                "coil_params": {"type": "object", "description": "Override coil params (I_coil, f_RF, n_turns, coil_radius, sigma_eff, ...)"},
            },
            "required": ["run_id"],
        },
    },
    "comsol_export_em_coil_kpis": {
        "handler": handle_export_em_coil_kpis,
        "description": "Export KPIs for AC/DC coil EM simulation",
        "inputSchema": {
            "type": "object",
            "properties": {**_RUN_ID_PROP},
            "required": ["run_id"],
        },
    },
    "comsol_export_coupled_fields": {
        "handler": handle_export_coupled_fields,
        "description": "Export coupled EM + thermal + Flash fields (Q_RF heating, T_gas, DeltaB, chi, RF-assisted activation)",
        "inputSchema": {
            "type": "object",
            "properties": {
                **_RUN_ID_PROP,
                "format": {"type": "string", "default": "h5"},
                "em_mode": {"type": "string", "enum": ["surrogate", "comsol"]},
                "bias_voltage": {"type": "number"},
                "flash_enabled": {"type": "boolean", "default": True},
                "flash_params": {"type": "object"},
                "em_params": {"type": "object"},
                "thermal_params": {"type": "object"},
                "synthetic_mode": {"type": "string", "enum": ["pipeline", "science"]},
            },
            "required": ["run_id"],
        },
    },
    "comsol_export_coupled_kpis": {
        "handler": handle_export_coupled_kpis,
        "description": "Export KPIs for coupled EM+thermal+Flash run, incl. powder-region and energy-balance metrics",
        "inputSchema": {
            "type": "object",
            "properties": {
                **_RUN_ID_PROP,
                "em_mode": {"type": "string", "enum": ["surrogate", "comsol"]},
                "thermal_params": {"type": "object"},
                "powder_region": {"type": "object", "description": "r_min, r_max, z_start, z_end (m)"},
            },
            "required": ["run_id"],
        },
    },
    "comsol_render_png": {
        "handler": handle_render_png,
        "description": "Render a COMSOL plot group to PNG",
        "inputSchema": {
            "type": "object",
            "properties": {**_RUN_ID_PROP, "plot_id": {"type": "string"}},
            "required": ["run_id", "plot_id"],
        },
    },
    "comsol_close_model": {
        "handler": handle_close_model,
        "description": "Close the model and release resources",
        "inputSchema": {
            "type": "object",
            "properties": {**_RUN_ID_PROP},
            "required": ["run_id"],
        },
    },
}


# ── MCP protocol ─────────────────────────────────────────────────────────────

def handle_initialize(params):
    return {
        "protocolVersion": "2024-11-05",
        "capabilities": {"tools": {}},
        "serverInfo": {"name": "comsol_mcp", "version": "0.4.0"},
    }


def handle_tools_list():
    tools = []
    for name, tool in TOOLS.items():
        tools.append({
            "name": name,
            "description": tool["description"],
            "inputSchema": tool["inputSchema"],
        })
    return {"tools": tools}


def handle_tools_call(params):
    tool_name = resolve_tool_name(params.get("name"), TOOLS)
    arguments = params.get("arguments", {})
    if tool_name not in TOOLS:
        raise ValueError(f"Unknown tool: {tool_name}")
    result = TOOLS[tool_name]["handler"](arguments)
    return {"content": [{"type": "text", "text": json.dumps(result)}]}


def main():
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            req = json.loads(line)
            req_id = req.get("id")
            method = req.get("method")
            params = req.get("params", {})

            if method == "initialize":
                send_response(req_id, handle_initialize(params))
            elif method == "notifications/initialized":
                pass
            elif method == "tools/list":
                send_response(req_id, handle_tools_list())
            elif method == "tools/call":
                send_response(req_id, handle_tools_call(params))
            elif method == "ping":
                send_response(req_id, {})
            else:
                send_error(req_id, -32601, f"Method not found: {method}")

        except json.JSONDecodeError as e:
            send_error(None, -32700, f"Parse error: {e}")
        except Exception as e:
            rid = req.get("id") if "req" in dir() else None
            send_error(rid, -32000, str(e), {"traceback": traceback.format_exc()})


if __name__ == "__main__":
    main()
