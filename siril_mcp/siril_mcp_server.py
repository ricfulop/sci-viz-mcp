#!/usr/bin/env python3
"""
siril_mcp_server.py
MCP server wrapping Siril (https://siril.org) for AI-driven astrophotography
processing — the free/GPL counterpart to pixinsight_mcp, with the same
workflow shape: open → analyze → gradient removal → color calibration →
stretch → denoise → export.

Unlike PixInsight, Siril ships first-class headless automation: this server
drives `siril-cli -s <script.ssf>` directly, so no GUI or watcher process is
needed. Each tool call generates a Siril script, runs it, and tracks the
resulting file in a session so calls chain naturally.

Siril also covers what the PixInsight bridge does not: full preprocessing
(calibrate / register / stack) of raw light frames.

Implements MCP JSON-RPC 2.0 over stdio (protocolVersion 2024-11-05).
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

_THIS_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(_THIS_DIR))
sys.path.insert(0, str(_THIS_DIR.parent))
from mcp_runtime import resolve_tool_name
from attribution import ATTRIBUTION_TEXT, stamp_image_file

try:
    from preview.notify import notify_preview
except Exception:  # preview dashboard is optional
    def notify_preview(*args, **kwargs):
        pass

OUTPUT_DIR = Path(os.environ.get(
    "SIRIL_MCP_OUTPUT_DIR",
    str(_THIS_DIR.parent / "output" / "siril"),
))

SIRIL_REQUIRES = "1.2.0"   # minimum Siril version stated in generated scripts
SCRIPT_TIMEOUT_S = int(os.environ.get("SIRIL_MCP_TIMEOUT_S", "900"))

RASTER_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff"}


# ── Siril binary discovery ───────────────────────────────────────────────────

_CANDIDATES = [
    os.environ.get("SIRIL_CLI", ""),
    "/Applications/Siril.app/Contents/MacOS/siril-cli",
    shutil.which("siril-cli") or "",
    "/usr/local/bin/siril-cli",
    "/opt/homebrew/bin/siril-cli",
    "/usr/bin/siril-cli",
    "C:/Program Files/Siril/bin/siril-cli.exe",
]


def find_siril_cli() -> str:
    for c in _CANDIDATES:
        if c and Path(c).exists():
            return c
    raise RuntimeError(
        "siril-cli not found. Install Siril (https://siril.org) or set the "
        "SIRIL_CLI environment variable to the binary path. On macOS the "
        "binary lives at /Applications/Siril.app/Contents/MacOS/siril-cli."
    )


def siril_version() -> str:
    out = subprocess.run([find_siril_cli(), "--version"], capture_output=True,
                         text=True, timeout=30)
    m = re.search(r"siril\s+([\d.]+)", out.stdout + out.stderr)
    return m.group(1) if m else (out.stdout or out.stderr).strip()


# ── Script execution ─────────────────────────────────────────────────────────

def run_siril_script(commands: list, workdir: Path, timeout_s: int = SCRIPT_TIMEOUT_S) -> dict:
    """Write commands to a .ssf script and execute it headlessly."""
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    script = f"requires {SIRIL_REQUIRES}\n" + "\n".join(commands) + "\n"
    with tempfile.NamedTemporaryFile(
        "w", suffix=".ssf", dir=str(workdir), delete=False
    ) as f:
        f.write(script)
        script_path = f.name
    try:
        proc = subprocess.run(
            [find_siril_cli(), "-d", str(workdir), "-s", script_path],
            capture_output=True, text=True, timeout=timeout_s,
        )
    finally:
        try:
            os.unlink(script_path)
        except OSError:
            pass

    log = (proc.stdout or "") + (proc.stderr or "")
    # Siril prefixes log lines with "log: "; errors are usually flagged
    lines = [ln for ln in log.splitlines() if ln.strip()]
    errors = [ln for ln in lines
              if re.search(r"error|could not|cannot|failed|not supported",
                           ln, re.IGNORECASE)
              and "0 errors" not in ln.lower()]
    return {
        "returncode": proc.returncode,
        "ok": proc.returncode == 0,
        "script": script,
        "log_tail": lines[-40:],
        "errors": errors,
    }


def _q(path) -> str:
    """Quote a path for a Siril script line."""
    return f'"{path}"'


# ── Session store ────────────────────────────────────────────────────────────
# session_id -> {"dir": Path, "current": Path, "history": [str]}

_sessions: dict = {}
_counter = 0


def _new_session_id(name: str) -> str:
    global _counter
    _counter += 1
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "img").lower()).strip("-") or "img"
    return f"{slug}-{_counter}"


def _get(session_id: str) -> dict:
    if session_id not in _sessions:
        raise ValueError(
            f"Unknown session_id '{session_id}'. "
            f"Active: {list(_sessions.keys()) or 'none'}. Use siril_open_image first."
        )
    return _sessions[session_id]


def _apply(session_id: str, op_name: str, op_commands: list,
           timeout_s: int = SCRIPT_TIMEOUT_S) -> dict:
    """load current image → run op commands → save as new working file."""
    s = _get(session_id)
    out_file = s["dir"] / f"{s['current'].stem}_{op_name}.fit"
    # avoid collisions on repeated ops
    n = 1
    while out_file.exists():
        n += 1
        out_file = s["dir"] / f"{s['current'].stem}_{op_name}{n}.fit"
    cmds = [f"load {_q(s['current'])}"] + op_commands + [f"save {_q(out_file.with_suffix(''))}"]
    res = run_siril_script(cmds, s["dir"], timeout_s=timeout_s)
    if res["ok"] and out_file.exists():
        s["current"] = out_file
        s["history"].append(op_name)
    return {
        "ok": res["ok"] and out_file.exists(),
        "current_file": str(s["current"]),
        "history": s["history"],
        "log_tail": res["log_tail"],
        "errors": res["errors"],
    }


# ── Tool handlers: setup & session ───────────────────────────────────────────

def handle_check(args):
    cli = find_siril_cli()
    return {
        "siril_cli": cli,
        "version": siril_version(),
        "hint": "Siril is free software (GPLv3) — no commercial license needed.",
    }


def handle_open_image(args):
    src = Path(args["path"]).expanduser().resolve()
    if not src.exists():
        raise ValueError(f"Image not found: {src}")
    name = args.get("name", src.stem)
    session_id = _new_session_id(name)
    workdir = OUTPUT_DIR / session_id
    workdir.mkdir(parents=True, exist_ok=True)

    # Normalize input to FITS in the session dir so every later op is uniform.
    work_fit = workdir / f"{src.stem}_work.fit"
    if src.suffix.lower() in (".fit", ".fits", ".fts"):
        shutil.copy2(src, work_fit)
        res = {"ok": True, "log_tail": [], "errors": []}
    else:
        res = run_siril_script(
            [f"load {_q(src)}", f"save {_q(work_fit.with_suffix(''))}"], workdir)
        if not res["ok"] or not work_fit.exists():
            raise RuntimeError(
                f"Siril could not load {src}. Log: {res['log_tail'][-8:]}")

    _sessions[session_id] = {"dir": workdir, "current": work_fit,
                             "history": ["open"], "source": str(src)}
    return {
        "session_id": session_id,
        "current_file": str(work_fit),
        "source": str(src),
        "attribution": ATTRIBUTION_TEXT,
        "hint": "Chain siril_remove_gradient, siril_color_calibrate, "
                "siril_stretch, siril_denoise, then siril_save_image.",
    }


def handle_list_sessions(args):
    return {"sessions": [
        {"session_id": sid, "current_file": str(s["current"]),
         "history": s["history"], "source": s.get("source")}
        for sid, s in _sessions.items()
    ]}


def handle_get_statistics(args):
    s = _get(args["session_id"])
    res = run_siril_script([f"load {_q(s['current'])}", "stat"], s["dir"])
    stats_lines = [ln for ln in res["log_tail"]
                   if re.search(r"mean|median|sigma|min|max|bgnoise|layer", ln,
                                re.IGNORECASE)]
    return {"ok": res["ok"], "statistics": stats_lines, "log_tail": res["log_tail"]}


# ── Tool handlers: processing (PixInsight-workflow mirror) ───────────────────

def handle_remove_gradient(args):
    method = args.get("method", "rbf")
    if method == "rbf":
        smooth = args.get("smooth", 0.5)
        samples = args.get("samples", 20)
        cmd = f"subsky -rbf -samples={samples} -smooth={smooth}"
    else:
        degree = int(args.get("degree", 2))
        if not 1 <= degree <= 4:
            raise ValueError("Polynomial degree must be 1-4.")
        cmd = f"subsky {degree}"
    return _apply(args["session_id"], "bkg", [cmd])


def handle_color_calibrate(args):
    method = args.get("method", "pcc")
    if method == "spcc":
        # Spectrophotometric CC: needs astrometric solution + net access
        cmds = ["platesolve", "spcc"]
    elif method == "pcc":
        cmds = ["platesolve", "pcc"]
    else:
        raise ValueError("method must be 'spcc' or 'pcc'")
    return _apply(args["session_id"], method, cmds)


def handle_remove_green(args):
    # type 0 = average neutral protection (default), 1 = maximum neutral
    protection = int(args.get("protection", 0))
    return _apply(args["session_id"], "scnr", [f"rmgreen {protection}"])


def handle_stretch(args):
    method = args.get("method", "autostretch")
    if method == "autostretch":
        linked = "-linked " if args.get("linked", False) else ""
        if "shadows_clip" in args or "target_bg" in args:
            shadows = args.get("shadows_clip", -2.8)
            target_bg = args.get("target_bg", 0.25)
            cmd = f"autostretch {linked}{shadows} {target_bg}"
        else:
            cmd = f"autostretch {linked}".strip()
    elif method == "asinh":
        stretch = args.get("stretch_factor", 50)
        cmd = f"asinh {stretch}"
    elif method == "ght":
        # generalized hyperbolic: sensible mild default
        d = args.get("D", 1.0)
        b = args.get("B", 5.0)
        cmd = f"autoght -D={d} -b={b}"
    else:
        raise ValueError("method must be autostretch | asinh | ght")
    return _apply(args["session_id"], "stretch", [cmd])


def handle_denoise(args):
    modulation = args.get("modulation", 1.0)
    cmd = "denoise" if modulation >= 1.0 else f"denoise -mod={modulation}"
    return _apply(args["session_id"], "denoise", [cmd], timeout_s=1800)


def handle_deconvolve(args):
    method = args.get("method", "rl")
    iters = int(args.get("iterations", 10))
    if method == "rl":
        cmds = ["makepsf stars", f"rl -iters={iters}"]
    elif method == "wiener":
        cmds = ["makepsf stars", "wiener"]
    else:
        raise ValueError("method must be 'rl' or 'wiener'")
    return _apply(args["session_id"], "deconv", cmds, timeout_s=1800)


def handle_crop(args):
    x, y = int(args["x"]), int(args["y"])
    w, h = int(args["width"]), int(args["height"])
    return _apply(args["session_id"], "crop", [f"crop {x} {y} {w} {h}"])


def handle_run_commands(args):
    """Power tool: run arbitrary Siril commands on the session image."""
    cmds = args["commands"]
    if isinstance(cmds, str):
        cmds = [cmds]
    return _apply(args["session_id"], args.get("op_name", "custom"), cmds)


# ── Tool handlers: preprocessing / stacking ──────────────────────────────────

_FRAME_EXTS = {".fit", ".fits", ".fts", ".fz", ".cr2", ".cr3", ".nef", ".arw",
               ".dng", ".raf", ".orf", ".tif", ".tiff"}


def _fits_naxis(path: Path):
    """Read NAXIS from a FITS primary header without astropy."""
    try:
        with open(path, "rb") as f:
            hdr = f.read(2880).decode("ascii", errors="replace")
        m = re.search(r"NAXIS\s*=\s*(\d+)", hdr)
        return int(m.group(1)) if m else None
    except OSError:
        return None


def _stage_frames(src_dir: Path, dest_dir: Path) -> int:
    """Symlink usable light frames into a clean dir, skipping junk.

    Smart telescopes (Dwarf, Seestar) mix rejected frames ('failed_*'),
    in-camera stacks ('stacked*', 3-channel FITS), thumbnails, and JSON
    into the capture folder; Siril's 'convert' chokes on inconsistent
    frames, so we stage a clean set of raw 2-D frames only.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    n = 0
    for f in sorted(src_dir.iterdir()):
        if not f.is_file() or f.suffix.lower() not in _FRAME_EXTS:
            continue
        name = f.name.lower()
        if name.startswith(("failed_", "stacked")) or "_thn" in name:
            continue
        if f.suffix.lower() in (".fit", ".fits", ".fts") and _fits_naxis(f) != 2:
            continue  # in-camera stack / RGB composite, not a raw light frame
        link = dest_dir / f"frame_{n:04d}{f.suffix.lower()}"
        try:
            link.symlink_to(f)
        except OSError:
            shutil.copy2(f, link)
        n += 1
    return n


def handle_preprocess_stack(args):
    """Full OSC preprocessing: convert, calibrate, register, stack lights."""
    lights = Path(args["lights_dir"]).expanduser().resolve()
    if not lights.is_dir():
        raise ValueError(f"lights_dir not found: {lights}")
    darks = args.get("darks_dir")
    flats = args.get("flats_dir")
    biases = args.get("biases_dir")
    name = args.get("name", "stack")
    workdir = OUTPUT_DIR / f"{name}_{int(time.time())}"
    process = workdir / "process"
    process.mkdir(parents=True, exist_ok=True)
    if " " in str(workdir):
        raise ValueError(
            f"Siril scripts cannot handle spaces in paths; move the repo or set "
            f"SIRIL_MCP_OUTPUT_DIR to a space-free path (got: {workdir})")

    # Stage all frame sets into the (space-free) workdir. Siril's cd/-out=
    # do not un-quote paths, and smart-telescope folders mix junk with lights.
    n_lights = _stage_frames(lights, workdir / "lights")
    if n_lights < 2:
        raise ValueError(
            f"Found only {n_lights} usable frames in {lights} "
            f"(supported: {sorted(_FRAME_EXTS)}; 'failed_*'/'stacked*' skipped).")
    for label, src in (("darks", darks), ("flats", flats), ("biases", biases)):
        if src:
            n = _stage_frames(Path(src).expanduser().resolve(), workdir / label)
            if n < 1:
                raise ValueError(f"No usable frames in {label} dir: {src}")

    mono = bool(args.get("mono", False))
    # All paths below are relative to workdir (siril-cli -d workdir)
    cmds = []

    if biases:
        cmds += ["cd biases",
                 "convert bias -out=../process",
                 "cd ../process",
                 "stack bias rej 3 3 -nonorm -out=bias_stacked",
                 "cd .."]
    if flats:
        cmds += ["cd flats",
                 "convert flat -out=../process",
                 "cd ../process"]
        if biases:
            cmds += ["calibrate flat -bias=bias_stacked",
                     "stack pp_flat rej 3 3 -norm=mul -out=flat_stacked"]
        else:
            cmds += ["stack flat rej 3 3 -norm=mul -out=flat_stacked"]
        cmds += ["cd .."]
    if darks:
        cmds += ["cd darks",
                 "convert dark -out=../process",
                 "cd ../process",
                 "stack dark rej 3 3 -nonorm -out=dark_stacked",
                 "cd .."]

    cal_parts = []
    if darks:
        cal_parts.append("-dark=dark_stacked")
    if flats:
        cal_parts.append("-flat=flat_stacked")

    if cal_parts:
        cmds += ["cd lights",
                 "convert light -out=../process",
                 "cd ../process"]
        debayer = "" if mono else " -cfa -equalize_cfa -debayer"
        cmds += [f"calibrate light {' '.join(cal_parts)}{debayer}",
                 "register pp_light",
                 "stack r_pp_light rej 3 3 -norm=addscale -output_norm "
                 f"-out={name}_result"]
    else:
        # No calibration frames: debayer OSC data at conversion time
        debayer = "" if mono else " -debayer"
        cmds += ["cd lights",
                 f"convert light{debayer} -out=../process",
                 "cd ../process",
                 "register light",
                 f"stack r_light rej 3 3 -norm=addscale -output_norm -out={name}_result"]

    res = run_siril_script(cmds, workdir, timeout_s=int(args.get("timeout_s", 3600)))
    result_file = process / f"{name}_result.fit"
    out = {
        "ok": res["ok"] and result_file.exists(),
        "result_file": str(result_file) if result_file.exists() else None,
        "workdir": str(workdir),
        "log_tail": res["log_tail"],
        "errors": res["errors"],
    }
    if result_file.exists():
        session_id = _new_session_id(name)
        sdir = OUTPUT_DIR / session_id
        sdir.mkdir(parents=True, exist_ok=True)
        work_fit = sdir / f"{name}_work.fit"
        shutil.copy2(result_file, work_fit)
        _sessions[session_id] = {"dir": sdir, "current": work_fit,
                                 "history": ["stack"], "source": str(lights)}
        out["session_id"] = session_id
        out["hint"] = ("Stacked image opened as a session — continue with "
                       "siril_remove_gradient → siril_color_calibrate → "
                       "siril_stretch → siril_save_image.")
    return out


# ── Tool handlers: export ────────────────────────────────────────────────────

def handle_save_image(args):
    s = _get(args["session_id"])
    fmt = args.get("format", "png").lower().lstrip(".")
    out_path = args.get("output_file")
    if out_path:
        out_path = Path(out_path).expanduser().resolve()
    else:
        out_path = s["dir"] / f"{s['current'].stem}.{fmt}"
    stem = out_path.with_suffix("")

    if fmt in ("fit", "fits"):
        cmd = f"save {_q(stem)}"
        out_path = stem.with_suffix(".fit")
    elif fmt in ("tif", "tiff"):
        cmd = f"savetif {_q(stem)}"
        out_path = stem.with_suffix(".tif")
    elif fmt in ("jpg", "jpeg"):
        cmd = f"savejpg {_q(stem)} {int(args.get('quality', 95))}"
        out_path = stem.with_suffix(".jpg")
    elif fmt == "png":
        cmd = f"savepng {_q(stem)}"
        out_path = stem.with_suffix(".png")
    else:
        raise ValueError("format must be fit | tif | jpg | png")

    res = run_siril_script([f"load {_q(s['current'])}", cmd], s["dir"])
    ok = res["ok"] and out_path.exists()
    if ok and out_path.suffix.lower() in RASTER_EXTS:
        try:
            stamp_image_file(str(out_path))
        except Exception:
            pass
        notify_preview(str(out_path), "siril_save_image",
                       {"session_id": args["session_id"]},
                       server_name="siril_mcp")
    return {
        "ok": ok,
        "output_file": str(out_path) if ok else None,
        "log_tail": res["log_tail"],
        "errors": res["errors"],
        "attribution": ATTRIBUTION_TEXT,
    }


# ── Tool handlers: knowledge ─────────────────────────────────────────────────

_WORKFLOW = """Recommended Siril processing order (mirrors the PixInsight workflow):

0. siril_preprocess_stack — if starting from raw light frames
   (calibrate with darks/flats/biases, debayer, register, stack).
1. siril_open_image — load the stacked linear image.
2. siril_get_statistics — inspect background level and noise.
3. siril_remove_gradient — background extraction while LINEAR
   (method 'rbf' recommended; 'poly' degree 1-4 for simple gradients).
4. siril_color_calibrate — while LINEAR. 'spcc' (spectrophotometric,
   needs internet for Gaia catalog) or 'pcc' (photometric).
   Both plate-solve first; FITS needs approximate WCS or target coords.
5. siril_deconvolve — optional, while LINEAR (PSF from stars, then
   Richardson-Lucy). Equivalent of BlurXTerminator's sharpening step.
6. siril_stretch — go non-linear. 'autostretch' (like PI's STF+HT),
   'asinh' for star-color preservation, or 'ght'.
7. siril_remove_green — SCNR green-cast removal after stretch.
8. siril_denoise — Siril's NL-Bayes denoise (NoiseXTerminator analog).
9. siril_save_image — export png/jpg/tif (attribution auto-stamped)
   or fit for further work.

Differences from PixInsight: no LRGB combination or narrowband blending
tools here yet (Siril supports them via 'rgbcomp' and pixel math — use
siril_run_commands). Star removal requires StarNet installed in Siril
(command 'starnet' via siril_run_commands)."""


def handle_workflow(args):
    return {"workflow": _WORKFLOW}


# ── Tool registry ────────────────────────────────────────────────────────────

TOOLS = {
    "siril_check": {
        "handler": handle_check,
        "description": "Verify Siril installation: locate siril-cli and report its version. Siril is free software (GPLv3) — no license required.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    "siril_open_image": {
        "handler": handle_open_image,
        "description": "Open an image (FITS, TIFF, PNG, JPG, RAW...) into a new Siril processing session. Returns a session_id used by all processing tools. The image is converted to a working FITS copy; the original is never modified.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute path to the image"},
                "name": {"type": "string", "description": "Optional session name"},
            },
            "required": ["path"],
        },
    },
    "siril_list_sessions": {
        "handler": handle_list_sessions,
        "description": "List active Siril processing sessions with their history and current working file.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    "siril_get_statistics": {
        "handler": handle_get_statistics,
        "description": "Image statistics (mean, median, sigma, background noise) per channel for the session's current image.",
        "inputSchema": {
            "type": "object",
            "properties": {"session_id": {"type": "string"}},
            "required": ["session_id"],
        },
    },
    "siril_remove_gradient": {
        "handler": handle_remove_gradient,
        "description": "Background gradient removal (Siril 'subsky'). Do this while the image is LINEAR. method 'rbf' (default, handles complex gradients) or 'poly' with degree 1-4.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "method": {"type": "string", "enum": ["rbf", "poly"], "default": "rbf"},
                "degree": {"type": "integer", "minimum": 1, "maximum": 4,
                           "description": "Polynomial degree (poly method)"},
                "samples": {"type": "integer", "default": 20},
                "smooth": {"type": "number", "default": 0.5},
            },
            "required": ["session_id"],
        },
    },
    "siril_color_calibrate": {
        "handler": handle_color_calibrate,
        "description": "Color calibration while LINEAR. Plate-solves then runs 'spcc' (spectrophotometric, Gaia catalog, needs internet) or 'pcc' (photometric). Image needs enough stars and approximate coordinates in the FITS header.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "method": {"type": "string", "enum": ["spcc", "pcc"], "default": "pcc"},
            },
            "required": ["session_id"],
        },
    },
    "siril_remove_green": {
        "handler": handle_remove_green,
        "description": "Remove green cast (Siril 'rmgreen', SCNR-equivalent). Apply after stretching.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "protection": {"type": "integer", "enum": [0, 1], "default": 0,
                               "description": "0 = average neutral, 1 = maximum neutral"},
            },
            "required": ["session_id"],
        },
    },
    "siril_stretch": {
        "handler": handle_stretch,
        "description": "Histogram stretch: linear → non-linear. Methods: 'autostretch' (like PixInsight STF+HistogramTransformation), 'asinh' (preserves star color), 'ght' (generalized hyperbolic).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "method": {"type": "string",
                           "enum": ["autostretch", "asinh", "ght"],
                           "default": "autostretch"},
                "shadows_clip": {"type": "number", "default": -2.8},
                "target_bg": {"type": "number", "default": 0.25},
                "linked": {"type": "boolean", "default": False},
                "stretch_factor": {"type": "number", "default": 50,
                                   "description": "asinh stretch factor"},
            },
            "required": ["session_id"],
        },
    },
    "siril_denoise": {
        "handler": handle_denoise,
        "description": "Denoise using Siril's NL-Bayes algorithm (NoiseXTerminator analog). modulation < 1.0 blends with the original.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "modulation": {"type": "number", "default": 1.0},
            },
            "required": ["session_id"],
        },
    },
    "siril_deconvolve": {
        "handler": handle_deconvolve,
        "description": "Deconvolution while LINEAR (BlurXTerminator analog): builds a PSF from detected stars then applies Richardson-Lucy ('rl') or Wiener filtering.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "method": {"type": "string", "enum": ["rl", "wiener"], "default": "rl"},
                "iterations": {"type": "integer", "default": 10},
            },
            "required": ["session_id"],
        },
    },
    "siril_crop": {
        "handler": handle_crop,
        "description": "Crop the session image to a rectangle (x, y = top-left corner in pixels).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "x": {"type": "integer"}, "y": {"type": "integer"},
                "width": {"type": "integer"}, "height": {"type": "integer"},
            },
            "required": ["session_id", "x", "y", "width", "height"],
        },
    },
    "siril_run_commands": {
        "handler": handle_run_commands,
        "description": "Power tool: run arbitrary Siril script commands on the session image (load and save are added automatically). Full command reference: https://siril.readthedocs.io/en/stable/Commands.html. Examples: 'starnet' (star removal, needs StarNet installed), 'rgbcomp', 'fmul 1.5', 'resample 0.5'.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "commands": {"type": "array", "items": {"type": "string"}},
                "op_name": {"type": "string", "default": "custom"},
            },
            "required": ["session_id", "commands"],
        },
    },
    "siril_preprocess_stack": {
        "handler": handle_preprocess_stack,
        "description": "Full preprocessing of raw frames (what PixInsight's WBPP does): convert, optionally calibrate with darks/flats/biases, debayer (OSC), register, and sigma-clip stack. Returns the stacked file and opens it as a new session ready for processing.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "lights_dir": {"type": "string"},
                "darks_dir": {"type": "string"},
                "flats_dir": {"type": "string"},
                "biases_dir": {"type": "string"},
                "name": {"type": "string", "default": "stack"},
                "mono": {"type": "boolean", "default": False,
                         "description": "Set true for mono camera (skips debayer)"},
                "timeout_s": {"type": "integer", "default": 3600},
            },
            "required": ["lights_dir"],
        },
    },
    "siril_save_image": {
        "handler": handle_save_image,
        "description": "Export the session's current image as png, jpg, tif, or fit. Raster exports carry the Sci-Viz attribution stamp.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "format": {"type": "string", "enum": ["png", "jpg", "tif", "fit"],
                           "default": "png"},
                "output_file": {"type": "string"},
                "quality": {"type": "integer", "default": 95},
            },
            "required": ["session_id"],
        },
    },
    "siril_workflow": {
        "handler": handle_workflow,
        "description": "Return the recommended end-to-end Siril processing workflow (stacking through export), mapped to the equivalent PixInsight steps.",
        "inputSchema": {"type": "object", "properties": {}},
    },
}


# ── MCP protocol ─────────────────────────────────────────────────────────────

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


def handle_initialize(params):
    return {
        "protocolVersion": "2024-11-05",
        "capabilities": {"tools": {}},
        "serverInfo": {"name": "siril_mcp", "version": "0.1.0"},
    }


def handle_tools_list():
    return {"tools": [
        {"name": name, "description": t["description"], "inputSchema": t["inputSchema"]}
        for name, t in TOOLS.items()
    ]}


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
            else:
                send_error(req_id, -32601, f"Method not found: {method}")

        except json.JSONDecodeError as e:
            send_error(None, -32700, f"Parse error: {e}")
        except Exception as e:
            rid = req.get("id") if "req" in dir() else None
            send_error(rid, -32000, str(e), {"traceback": traceback.format_exc()})


if __name__ == "__main__":
    main()
