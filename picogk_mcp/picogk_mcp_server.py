#!/usr/bin/env python3
"""MCP server for trusted-local PicoGK and LEAP 71 C# modeling jobs."""

from __future__ import annotations

import json
import logging
import sys
import traceback
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
REPO_ROOT = THIS_DIR.parent
sys.path.insert(0, str(REPO_ROOT))

from mcp_runtime import configure_stdio_logging, resolve_tool_name
from picogk_mcp.picogk_backend import PicoGKBackend, PicoGKBackendError
from picogk_mcp.stack_manager import StackError

try:
    from preview.notify import notify_preview
except Exception:  # preview is optional
    def notify_preview(*args, **kwargs):
        return None


configure_stdio_logging()
LOGGER = logging.getLogger("picogk_mcp")
BACKEND = PicoGKBackend()


def handle_health(args):
    return BACKEND.health()


def handle_stack_info(args):
    if args.get("include_status", True):
        return {
            "catalog": BACKEND.stack.catalog(),
            "status": BACKEND.stack.status(args.get("modules")),
        }
    return {"catalog": BACKEND.stack.catalog()}


def handle_sync_stack(args):
    return BACKEND.stack.sync(
        args.get("modules"),
        include_unlicensed=bool(args.get("include_unlicensed", False)),
        force=bool(args.get("force", False)),
    )


def handle_create_project(args):
    return BACKEND.create_project(
        name=args["name"],
        modules=args.get("modules"),
        source=args.get("source"),
    )


def handle_list_projects(args):
    return BACKEND.list_projects()


def handle_get_project(args):
    return BACKEND.get_project(
        args["project_id"],
        include_source=bool(args.get("include_source", True)),
    )


def handle_write_source(args):
    return BACKEND.write_source(
        args["project_id"],
        args["source"],
        modules=args.get("modules"),
    )


def handle_build(args):
    return BACKEND.build_project(
        args["project_id"],
        timeout_s=int(args.get("timeout_s", 600)),
        wait=bool(args.get("wait", False)),
    )


def handle_run(args):
    return BACKEND.run_project(
        args["project_id"],
        voxel_size_mm=float(args.get("voxel_size_mm", 0.5)),
        viewer_mode=args.get("viewer_mode", "viewer_autoclose"),
        timeout_s=int(args.get("timeout_s", 3600)),
        wait=bool(args.get("wait", False)),
    )


def handle_run_csharp(args):
    return BACKEND.run_csharp(
        source=args["source"],
        name=args.get("name", "one-shot-model"),
        modules=args.get("modules"),
        voxel_size_mm=float(args.get("voxel_size_mm", 0.5)),
        viewer_mode=args.get("viewer_mode", "viewer_autoclose"),
        timeout_s=int(args.get("timeout_s", 3600)),
        wait=bool(args.get("wait", False)),
    )


def handle_job_status(args):
    return BACKEND.job_status(args["job_id"])


def handle_list_jobs(args):
    return BACKEND.list_jobs(int(args.get("limit", 100)))


def handle_cancel_job(args):
    return BACKEND.cancel_job(args["job_id"])


def handle_job_logs(args):
    return BACKEND.job_logs(
        args["job_id"],
        max_chars=int(args.get("max_chars", 50_000)),
    )


def handle_list_artifacts(args):
    return BACKEND.list_artifacts(args["job_id"])


def handle_preview_artifact(args):
    artifact = BACKEND.artifact(
        args["job_id"],
        args["relative_path"],
    )
    if not artifact["previewable"]:
        return {
            "notified": False,
            "artifact": artifact,
            "hint": (
                "The browser dashboard previews images/PDF/SVG. Use the returned "
                "STL/OBJ path with Blender or OVITO for a 3D render."
            ),
        }
    notify_preview(
        artifact["path"],
        "picogk_preview_artifact",
        params={
            "job_id": args["job_id"],
            "relative_path": args["relative_path"],
        },
        server_name="picogk_mcp",
    )
    return {"notified": True, "artifact": artifact}


def handle_reference(args):
    topic = args.get("topic", "task_contract")
    if topic == "task_contract":
        return {
            "contract": (
                "Submit one static method marked [PicoGKTask]. It may accept no "
                "parameters or one JobContext. JobContext.OutputPath confines "
                "artifacts to the job directory and RegisterArtifact records "
                "kind/metadata. The submitted C# otherwise has full .NET and "
                "selected LEAP 71 API access."
            ),
            "template": BACKEND.default_source(),
        }
    if topic == "modules":
        return BACKEND.stack.catalog()
    if topic == "runtime":
        return {
            "target": BACKEND.stack.lock["dotnet_target"],
            "picogk_version": BACKEND.stack.package["version"],
            "supported_rids": BACKEND.stack.package["supported_rids"],
            "viewer_modes": {
                "headless": (
                    "Geometry and field operations without a Viewer. Code that "
                    "calls Library.oViewer() will fail."
                ),
                "viewer_autoclose": (
                    "Uses Library.Go and closes after the task and pending viewer "
                    "actions finish."
                ),
                "viewer_interactive": (
                    "Uses Library.Go and remains active until the viewer closes; "
                    "run asynchronously."
                ),
            },
            "units": "PicoGK world coordinates and voxel size are millimetres.",
        }
    if topic == "security":
        return {
            "trusted_local_only": True,
            "warning": (
                "run_csharp compiles and executes arbitrary C# with the MCP server "
                "user's filesystem and network permissions. Process isolation, "
                "timeouts, and job output conventions are not an OS sandbox."
            ),
        }
    raise ValueError(
        "topic must be task_contract, modules, runtime, or security."
    )


MODULES_SCHEMA = {
    "type": "array",
    "items": {"type": "string"},
    "description": "LEAP 71 modules; dependencies are added automatically.",
}

TOOLS = {
    "picogk_health": {
        "handler": handle_health,
        "description": (
            "Check .NET 9, native RID support, PicoGK version, output paths, "
            "and locked LEAP 71 source-cache status. Never launches PicoGK."
        ),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    "picogk_stack_info": {
        "handler": handle_stack_info,
        "description": (
            "List the pinned PicoGK/LEAP 71 module catalog, dependencies, "
            "licenses, commits, and local cache readiness."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "modules": MODULES_SCHEMA,
                "include_status": {"type": "boolean", "default": True},
            },
            "additionalProperties": False,
        },
    },
    "picogk_sync_stack": {
        "handler": handle_sync_stack,
        "description": (
            "Fetch exact locked LEAP 71 source revisions into the local cache. "
            "The unlicensed simulation example requires explicit opt-in."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "modules": MODULES_SCHEMA,
                "include_unlicensed": {
                    "type": "boolean",
                    "default": False,
                    "description": "Allow repositories whose lock entry is NOASSERTION.",
                },
                "force": {"type": "boolean", "default": False},
            },
            "additionalProperties": False,
        },
    },
    "picogk_create_project": {
        "handler": handle_create_project,
        "description": (
            "Create a persistent raw-C# PicoGK project. Omit source to get a "
            "working sphere-to-STL template."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "modules": MODULES_SCHEMA,
                "source": {"type": "string"},
            },
            "required": ["name"],
            "additionalProperties": False,
        },
    },
    "picogk_list_projects": {
        "handler": handle_list_projects,
        "description": "List persistent PicoGK source projects.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    "picogk_get_project": {
        "handler": handle_get_project,
        "description": "Read a PicoGK project manifest and optionally its C# source.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "include_source": {"type": "boolean", "default": True},
            },
            "required": ["project_id"],
            "additionalProperties": False,
        },
    },
    "picogk_write_source": {
        "handler": handle_write_source,
        "description": (
            "Replace a project's trusted raw C# source and optionally change "
            "its selected LEAP 71 modules."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "source": {"type": "string"},
                "modules": MODULES_SCHEMA,
            },
            "required": ["project_id", "source"],
            "additionalProperties": False,
        },
    },
    "picogk_build": {
        "handler": handle_build,
        "description": (
            "Compile a PicoGK project in an isolated job without loading the "
            "native geometry runtime."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "timeout_s": {"type": "integer", "minimum": 1, "maximum": 86400},
                "wait": {"type": "boolean", "default": False},
            },
            "required": ["project_id"],
            "additionalProperties": False,
        },
    },
    "picogk_run": {
        "handler": handle_run,
        "description": (
            "Build and run a persistent PicoGK project in an isolated process. "
            "Submitted C# is trusted code, not sandboxed."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "voxel_size_mm": {"type": "number", "exclusiveMinimum": 0, "maximum": 1000},
                "viewer_mode": {
                    "type": "string",
                    "enum": ["headless", "viewer_autoclose", "viewer_interactive"],
                },
                "timeout_s": {"type": "integer", "minimum": 1, "maximum": 86400},
                "wait": {"type": "boolean", "default": False},
            },
            "required": ["project_id"],
            "additionalProperties": False,
        },
    },
    "picogk_run_csharp": {
        "handler": handle_run_csharp,
        "description": (
            "Create, build, and run one raw C# PicoGK task. TRUSTED LOCAL ONLY: "
            "the source executes with the user's filesystem/network permissions."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "source": {"type": "string"},
                "name": {"type": "string"},
                "modules": MODULES_SCHEMA,
                "voxel_size_mm": {"type": "number", "exclusiveMinimum": 0, "maximum": 1000},
                "viewer_mode": {
                    "type": "string",
                    "enum": ["headless", "viewer_autoclose", "viewer_interactive"],
                },
                "timeout_s": {"type": "integer", "minimum": 1, "maximum": 86400},
                "wait": {"type": "boolean", "default": False},
            },
            "required": ["source"],
            "additionalProperties": False,
        },
    },
    "picogk_job_status": {
        "handler": handle_job_status,
        "description": "Get build/run status, diagnostics, provenance, and artifacts for a job.",
        "inputSchema": {
            "type": "object",
            "properties": {"job_id": {"type": "string"}},
            "required": ["job_id"],
            "additionalProperties": False,
        },
    },
    "picogk_list_jobs": {
        "handler": handle_list_jobs,
        "description": "List recent PicoGK build and run jobs.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "minimum": 1, "maximum": 1000}
            },
            "additionalProperties": False,
        },
    },
    "picogk_cancel_job": {
        "handler": handle_cancel_job,
        "description": "Cancel a running PicoGK build or model process and its process group.",
        "inputSchema": {
            "type": "object",
            "properties": {"job_id": {"type": "string"}},
            "required": ["job_id"],
            "additionalProperties": False,
        },
    },
    "picogk_job_logs": {
        "handler": handle_job_logs,
        "description": "Read bounded build, runner, and PicoGK logs for a job.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string"},
                "max_chars": {"type": "integer", "minimum": 1, "maximum": 200000},
            },
            "required": ["job_id"],
            "additionalProperties": False,
        },
    },
    "picogk_list_artifacts": {
        "handler": handle_list_artifacts,
        "description": "List job artifacts with size, SHA-256, kind, metadata, and preview support.",
        "inputSchema": {
            "type": "object",
            "properties": {"job_id": {"type": "string"}},
            "required": ["job_id"],
            "additionalProperties": False,
        },
    },
    "picogk_preview_artifact": {
        "handler": handle_preview_artifact,
        "description": (
            "Send an image/PDF/SVG job artifact to the Sci-Viz live preview. "
            "For STL/OBJ/VDB, returns a Blender/OVITO handoff hint."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string"},
                "relative_path": {"type": "string"},
            },
            "required": ["job_id", "relative_path"],
            "additionalProperties": False,
        },
    },
    "picogk_reference": {
        "handler": handle_reference,
        "description": "Return the raw-task contract, module catalog, runtime modes, or security model.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "enum": ["task_contract", "modules", "runtime", "security"],
                }
            },
            "additionalProperties": False,
        },
    },
}


def send_response(request_id, result=None, error=None):
    response = {"jsonrpc": "2.0", "id": request_id}
    if error is not None:
        response["error"] = error
    else:
        response["result"] = result if result is not None else {}
    sys.stdout.write(json.dumps(response) + "\n")
    sys.stdout.flush()


def send_error(request_id, code, message, data=None):
    error = {"code": code, "message": message}
    if data:
        error["data"] = data
    send_response(request_id, error=error)


def handle_initialize(params):
    return {
        "protocolVersion": "2024-11-05",
        "capabilities": {"tools": {}},
        "serverInfo": {"name": "picogk_mcp", "version": "0.1.0"},
    }


def handle_tools_list():
    return {
        "tools": [
            {
                "name": name,
                "description": tool["description"],
                "inputSchema": tool["inputSchema"],
            }
            for name, tool in TOOLS.items()
        ]
    }


def handle_tools_call(params):
    tool_name = resolve_tool_name(params.get("name"), TOOLS)
    arguments = params.get("arguments", {})
    if tool_name not in TOOLS:
        raise ValueError(f"Unknown tool: {tool_name}")
    result = TOOLS[tool_name]["handler"](arguments)
    return {
        "content": [{"type": "text", "text": json.dumps(result)}],
    }


def main():
    for line in sys.stdin:
        if not line.strip():
            continue
        request = None
        try:
            request = json.loads(line)
            request_id = request.get("id")
            method = request.get("method")
            params = request.get("params", {})
            if method == "initialize":
                send_response(request_id, handle_initialize(params))
            elif method == "notifications/initialized":
                continue
            elif method == "tools/list":
                send_response(request_id, handle_tools_list())
            elif method == "tools/call":
                send_response(request_id, handle_tools_call(params))
            else:
                send_error(request_id, -32601, f"Method not found: {method}")
        except json.JSONDecodeError as exc:
            send_error(None, -32700, f"Parse error: {exc}")
        except (PicoGKBackendError, StackError, ValueError, KeyError) as exc:
            request_id = request.get("id") if request else None
            send_error(
                request_id,
                -32000,
                str(exc),
                {"error_type": type(exc).__name__},
            )
        except Exception as exc:
            request_id = request.get("id") if request else None
            LOGGER.error("Unhandled PicoGK MCP error:\n%s", traceback.format_exc())
            send_error(
                request_id,
                -32603,
                f"Internal error: {exc}",
                {"error_type": type(exc).__name__},
            )


if __name__ == "__main__":
    main()
