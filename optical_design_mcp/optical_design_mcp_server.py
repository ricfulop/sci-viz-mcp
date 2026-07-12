#!/usr/bin/env python3
"""Persistent sequential optical-design MCP server backed by Optiland 0.6.0.

The server keeps a stable, explicit-unit JSON prescription as its source of
truth and reconstructs Optiland objects for tracing, analysis, optimization,
tolerancing, rendering, and native Optiland export.  It remains startable when
the optional Optiland dependency is absent; health/reference/model editing still
work and analysis tools return a structured ENGINE_UNAVAILABLE error.
"""

from __future__ import annotations

import contextlib
import csv
import hashlib
import importlib.metadata
import importlib.resources
import io
import json
import math
import os
import re
import shutil
import sys
import traceback
from pathlib import Path
from typing import Any

_THIS_DIR = Path(__file__).resolve().parent
_ROOT = _THIS_DIR.parent
sys.path.insert(0, str(_ROOT))

from mcp_runtime import configure_matplotlib_for_mcp, configure_stdio_logging, resolve_tool_name

configure_stdio_logging()
configure_matplotlib_for_mcp(_ROOT / ".matplotlib_cache")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from attribution import ATTRIBUTION_TEXT, add_figure_attribution
from styles import apply_aps_style

try:
    from preview.notify import notify_preview
except Exception:  # pragma: no cover - optional dashboard
    def notify_preview(*args, **kwargs):
        return None


OPTILAND_IMPORT_ERROR: Exception | None = None
try:
    with contextlib.redirect_stdout(io.StringIO()):
        import optiland.backend as optiland_backend
        from optiland import optic as optiland_optic
        from optiland.analysis import SpotDiagram
        from optiland.materials import Material
        from optiland.mtf import FFTMTF, GeometricMTF
        from optiland.optimization import OptimizationProblem, OptimizerGeneric
        from optiland.tolerancing import DistributionSampler, Tolerancing
        from optiland.tolerancing.monte_carlo import MonteCarlo
except Exception as exc:  # pragma: no cover - exercised in dependency-free installs
    OPTILAND_IMPORT_ERROR = exc
    optiland_backend = None
    optiland_optic = None
    SpotDiagram = None
    Material = None
    FFTMTF = None
    GeometricMTF = None
    OptimizationProblem = None
    OptimizerGeneric = None
    DistributionSampler = None
    Tolerancing = None
    MonteCarlo = None


SERVER_VERSION = "1.0.0"
MODEL_SCHEMA = "sciviz.optical_design/v1"
OUTPUT_DIR = Path(
    os.environ.get(
        "OPTICAL_DESIGN_OUTPUT_DIR",
        str(_ROOT / "output" / "optical_design"),
    )
).expanduser()
MODELS_DIR = OUTPUT_DIR / "models"
ARTIFACTS_DIR = OUTPUT_DIR / "artifacts"
RENDERS_DIR = OUTPUT_DIR / "renders"

_models: dict[str, dict[str, Any]] = {}
_SURFACE_TYPES = {"standard", "plane", "even_asphere", "odd_asphere", "paraxial"}
_VARIABLE_TYPES = {
    "radius",
    "conic",
    "thickness",
    "tilt",
    "decenter",
    "index",
    "asphere_coeff",
    "reciprocal_radius",
    "norm_radius",
}
_OPERAND_TYPES = {
    "f1",
    "f2",
    "F1",
    "F2",
    "EPD",
    "EPL",
    "XPD",
    "XPL",
    "magnification",
    "total_track",
    "real_x_intercept",
    "real_y_intercept",
    "real_z_intercept",
    "real_x_intercept_lcs",
    "real_y_intercept_lcs",
    "real_z_intercept_lcs",
    "real_L",
    "real_M",
    "real_N",
    "rms_spot_size",
    "OPD_difference",
    "edge_thickness",
    "AOI",
}


class ToolError(Exception):
    def __init__(self, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


@contextlib.contextmanager
def _quiet_optiland():
    """Capture upstream stdout so it cannot corrupt stdio JSON-RPC."""

    capture = io.StringIO()
    with contextlib.redirect_stdout(capture):
        yield


def _require_optiland() -> None:
    if OPTILAND_IMPORT_ERROR is not None:
        raise ToolError(
            "ENGINE_UNAVAILABLE",
            "Optiland is not installed or failed to import.",
            {
                "dependency": "optiland==0.6.0",
                "install": "./install.sh --with-design",
                "import_error": f"{type(OPTILAND_IMPORT_ERROR).__name__}: {OPTILAND_IMPORT_ERROR}",
            },
        )


def _package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "not-installed"


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "model"


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, np.ndarray):
        return _jsonable(value.tolist())
    if isinstance(value, np.generic):
        return _jsonable(value.item())
    if isinstance(value, complex):
        return {"real": float(value.real), "imag": float(value.imag)}
    if isinstance(value, float):
        if math.isnan(value):
            return None
        if math.isinf(value):
            return "infinity" if value > 0 else "-infinity"
    return value


def _canonical_json(value: Any) -> str:
    return json.dumps(
        _jsonable(value),
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _digest(*values: Any, length: int = 16) -> str:
    h = hashlib.sha256()
    for value in values:
        h.update(_canonical_json(value).encode())
        h.update(b"\0")
    return h.hexdigest()[:length]


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(_jsonable(value), indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _array_sha256(*arrays: np.ndarray) -> str:
    h = hashlib.sha256()
    for array in arrays:
        contiguous = np.ascontiguousarray(array)
        h.update(str(contiguous.dtype).encode())
        h.update(str(contiguous.shape).encode())
        h.update(contiguous.tobytes())
    return h.hexdigest()


def _number(
    value: Any,
    name: str,
    *,
    positive: bool = False,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ToolError("VALIDATION_ERROR", f"{name} must be a number.", {"field": name})
    value = float(value)
    if not math.isfinite(value):
        raise ToolError("VALIDATION_ERROR", f"{name} must be finite.", {"field": name})
    if positive and value <= 0:
        raise ToolError("VALIDATION_ERROR", f"{name} must be > 0.", {"field": name})
    if minimum is not None and value < minimum:
        raise ToolError("VALIDATION_ERROR", f"{name} must be >= {minimum}.")
    if maximum is not None and value > maximum:
        raise ToolError("VALIDATION_ERROR", f"{name} must be <= {maximum}.")
    return value


def _integer(
    value: Any,
    name: str,
    *,
    minimum: int = 0,
    maximum: int | None = None,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ToolError("VALIDATION_ERROR", f"{name} must be an integer.")
    if value < minimum or (maximum is not None and value > maximum):
        raise ToolError(
            "VALIDATION_ERROR",
            f"{name} must be in [{minimum}, {maximum or 'unbounded'}].",
        )
    return value


def _surface(
    role: str,
    *,
    radius_mm: float | None = None,
    thickness_mm: float | None = 0.0,
    material: str = "air",
    is_stop: bool = False,
    comment: str = "",
    surface_type: str = "standard",
    conic: float = 0.0,
    parameters: dict | None = None,
) -> dict[str, Any]:
    return {
        "role": role,
        "surface_type": surface_type,
        "radius_mm": radius_mm,
        "thickness_mm": thickness_mm,
        "material": material,
        "is_stop": is_stop,
        "comment": comment,
        "conic": conic,
        "parameters": parameters or {},
    }


def _default_model(name: str, preset: str = "empty") -> dict[str, Any]:
    model = {
        "schema": MODEL_SCHEMA,
        "name": name,
        "units": {
            "length": "mm",
            "angle": "deg",
            "wavelength": "nm",
            "spatial_frequency": "cycles/mm",
        },
        "aperture": {"type": "EPD", "value_mm": 10.0},
        "fields": {
            "type": "angle",
            "items": [{"x_deg": 0.0, "y_deg": 0.0, "weight": 1.0}],
        },
        "wavelengths": [{"value_nm": 550.0, "weight": 1.0, "is_primary": True}],
        "surfaces": [
            _surface("object", thickness_mm=None, comment="Object"),
            _surface("image", thickness_mm=0.0, comment="Image"),
        ],
        "metadata": {},
    }
    if preset == "biconvex_singlet":
        model["aperture"] = {"type": "EPD", "value_mm": 10.0}
        model["surfaces"] = [
            _surface("object", thickness_mm=None, comment="Object"),
            _surface(
                "surface",
                radius_mm=50.0,
                thickness_mm=5.0,
                material="N-BK7",
                is_stop=True,
                comment="Singlet front",
            ),
            _surface(
                "surface",
                radius_mm=-50.0,
                thickness_mm=45.0,
                material="air",
                comment="Singlet rear",
            ),
            _surface("image", thickness_mm=0.0, comment="Image"),
        ]
    elif preset != "empty":
        raise ToolError(
            "VALIDATION_ERROR",
            f"Unknown preset '{preset}'.",
            {"supported": ["empty", "biconvex_singlet"]},
        )
    return model


def _validate_model(model: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(model, dict) or model.get("schema") != MODEL_SCHEMA:
        raise ToolError(
            "INVALID_MODEL",
            f"Model must use schema '{MODEL_SCHEMA}'.",
            {"received": model.get("schema") if isinstance(model, dict) else None},
        )
    aperture = model.get("aperture", {})
    if aperture.get("type") not in {"EPD", "imageFNO", "objectNA"}:
        raise ToolError("INVALID_MODEL", "Unsupported aperture type.")
    value_key = {
        "EPD": "value_mm",
        "imageFNO": "value",
        "objectNA": "value",
    }[aperture["type"]]
    _number(aperture.get(value_key), f"aperture.{value_key}", positive=True)
    fields = model.get("fields", {})
    if fields.get("type") not in {
        "angle",
        "object_height",
        "paraxial_image_height",
        "real_image_height",
    }:
        raise ToolError("INVALID_MODEL", "Unsupported field type.")
    if not fields.get("items"):
        raise ToolError("INVALID_MODEL", "At least one field is required.")
    for idx, field in enumerate(fields["items"]):
        _number(field.get("x", field.get("x_deg", 0.0)), f"fields.items[{idx}].x")
        _number(field.get("y", field.get("y_deg", 0.0)), f"fields.items[{idx}].y")
        _number(field.get("weight", 1.0), f"fields.items[{idx}].weight", minimum=0)
    wavelengths = model.get("wavelengths", [])
    if not wavelengths:
        raise ToolError("INVALID_MODEL", "At least one wavelength is required.")
    primary_count = 0
    for idx, wave in enumerate(wavelengths):
        _number(wave.get("value_nm"), f"wavelengths[{idx}].value_nm", positive=True)
        _number(wave.get("weight", 1.0), f"wavelengths[{idx}].weight", minimum=0)
        primary_count += bool(wave.get("is_primary"))
    if primary_count != 1:
        raise ToolError("INVALID_MODEL", "Exactly one wavelength must be primary.")
    surfaces = model.get("surfaces", [])
    if len(surfaces) < 2:
        raise ToolError("INVALID_MODEL", "Object and image surfaces are required.")
    if surfaces[0].get("role") != "object" or surfaces[-1].get("role") != "image":
        raise ToolError("INVALID_MODEL", "First surface must be object and last image.")
    stop_count = 0
    for idx, surface in enumerate(surfaces):
        if surface.get("surface_type", "standard") not in _SURFACE_TYPES:
            raise ToolError(
                "INVALID_MODEL",
                f"Unsupported surface_type at surfaces[{idx}].",
                {"supported": sorted(_SURFACE_TYPES)},
            )
        if surface.get("radius_mm") is not None:
            radius = _number(surface["radius_mm"], f"surfaces[{idx}].radius_mm")
            if radius == 0:
                raise ToolError("INVALID_MODEL", "Surface radius cannot be zero.")
        if surface.get("thickness_mm") is not None:
            _number(surface["thickness_mm"], f"surfaces[{idx}].thickness_mm")
        if not isinstance(surface.get("material", "air"), str):
            raise ToolError("INVALID_MODEL", "Surface material must be a string.")
        if not isinstance(surface.get("parameters", {}), dict):
            raise ToolError("INVALID_MODEL", "Surface parameters must be an object.")
        stop_count += bool(surface.get("is_stop"))
    if stop_count > 1:
        raise ToolError("INVALID_MODEL", "Only one aperture-stop surface is allowed.")
    return model


def _model_path(model_id: str) -> Path:
    return MODELS_DIR / f"{_slug(model_id)}.json"


def _persist(model_id: str) -> str:
    model = _validate_model(_models[model_id])
    path = _model_path(model_id)
    _atomic_json(path, model)
    return str(path)


def _get(model_id: str) -> dict[str, Any]:
    if model_id in _models:
        return _models[model_id]
    path = _model_path(model_id)
    if path.exists():
        model = _validate_model(json.loads(path.read_text()))
        _models[model_id] = model
        return model
    raise ToolError("MODEL_NOT_FOUND", f"Unknown model_id '{model_id}'.")


def _summary(model_id: str, model: dict[str, Any]) -> dict[str, Any]:
    return {
        "model_id": model_id,
        "name": model["name"],
        "path": str(_model_path(model_id)),
        "surface_count": len(model["surfaces"]),
        "field_count": len(model["fields"]["items"]),
        "wavelength_count": len(model["wavelengths"]),
        "stop_index": next(
            (idx for idx, surf in enumerate(model["surfaces"]) if surf.get("is_stop")),
            None,
        ),
        "model_digest": _digest(model, length=32),
    }


def _artifact_path(model_id: str, kind: str, suffix: str, args: dict) -> Path:
    path = (
        ARTIFACTS_DIR
        / _slug(model_id)
        / f"{kind}-{_digest(_get(model_id), kind, args)}.{suffix}"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _render_path(model_id: str, kind: str, args: dict) -> Path:
    path = (
        RENDERS_DIR
        / _slug(model_id)
        / f"{kind}-{_digest(_get(model_id), kind, args)}.png"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _surface_kwargs(surface: dict[str, Any]) -> dict[str, Any]:
    kwargs = dict(surface.get("parameters", {}))
    kwargs["thickness"] = (
        np.inf if surface.get("thickness_mm") is None else surface["thickness_mm"]
    )
    kwargs["radius"] = (
        np.inf if surface.get("radius_mm") is None else surface["radius_mm"]
    )
    kwargs["conic"] = surface.get("conic", 0.0)
    return kwargs


def _build_optic(model: dict[str, Any]):
    _require_optiland()
    _validate_model(model)
    with _quiet_optiland():
        system = optiland_optic.Optic(name=model["name"])
        for index, surface in enumerate(model["surfaces"]):
            system.surfaces.add(
                index=index,
                surface_type=surface.get("surface_type", "standard"),
                comment=surface.get("comment", ""),
                is_stop=bool(surface.get("is_stop", False)),
                material=surface.get("material", "air"),
                **_surface_kwargs(surface),
            )
        aperture = model["aperture"]
        aperture_value = aperture.get("value_mm", aperture.get("value"))
        system.set_aperture(aperture["type"], aperture_value)
        system.fields.set_type(model["fields"]["type"])
        for field in model["fields"]["items"]:
            system.fields.add(
                y=field.get("y", field.get("y_deg", 0.0)),
                x=field.get("x", field.get("x_deg", 0.0)),
                vx=field.get("vx", 0.0),
                vy=field.get("vy", 0.0),
                weight=field.get("weight", 1.0),
            )
        for wavelength in model["wavelengths"]:
            system.wavelengths.add(
                value=wavelength["value_nm"],
                unit="nm",
                is_primary=bool(wavelength.get("is_primary")),
                weight=wavelength.get("weight", 1.0),
            )
    return system


def _primary_wavelength_nm(model: dict[str, Any]) -> float:
    return float(next(w["value_nm"] for w in model["wavelengths"] if w["is_primary"]))


def _normalize_input_data(data: dict[str, Any], system) -> dict[str, Any]:
    normalized = dict(data)
    normalized["optic"] = system
    if "wavelength_nm" in normalized:
        normalized["wavelength"] = float(normalized.pop("wavelength_nm")) / 1000.0
    if normalized.get("wavelength") == "primary":
        normalized["wavelength"] = float(system.primary_wavelength)
    return normalized


def _variable_unit(variable_type: str) -> str:
    if variable_type in {"radius", "reciprocal_radius", "thickness", "decenter"}:
        return "mm"
    if variable_type == "tilt":
        return "rad"
    return "dimensionless"


def _operand_unit(operand_type: str) -> str:
    if operand_type in {
        "f1",
        "f2",
        "F1",
        "F2",
        "EPD",
        "EPL",
        "XPD",
        "XPL",
        "total_track",
        "real_x_intercept",
        "real_y_intercept",
        "real_z_intercept",
        "real_x_intercept_lcs",
        "real_y_intercept_lcs",
        "real_z_intercept_lcs",
        "rms_spot_size",
        "OPD_difference",
        "edge_thickness",
    }:
        return "mm"
    if operand_type == "AOI":
        return "deg"
    return "dimensionless"


def _update_model_from_variables(
    model: dict[str, Any],
    system,
    variable_specs: list[dict[str, Any]],
) -> None:
    for spec in variable_specs:
        surface_number = int(spec.get("surface_number", -1))
        if surface_number < 0:
            surface_number += len(model["surfaces"])
        kind = spec["type"]
        surface = system.surfaces[surface_number]
        if kind in {"radius", "reciprocal_radius"}:
            radius = float(np.asarray(surface.geometry.radius))
            model["surfaces"][surface_number]["radius_mm"] = None if math.isinf(radius) else radius
        elif kind == "conic":
            model["surfaces"][surface_number]["conic"] = float(
                np.asarray(surface.geometry.k)
            )
        elif kind == "thickness":
            model["surfaces"][surface_number]["thickness_mm"] = float(
                np.asarray(surface.thickness)
            )


def handle_health(args: dict) -> dict:
    del args
    available = OPTILAND_IMPORT_ERROR is None
    return {
        "ok": True,
        "server": "optical_design_mcp",
        "version": SERVER_VERSION,
        "model_schema": MODEL_SCHEMA,
        "engine": {
            "name": "Optiland",
            "required_for_analysis": True,
            "available": available,
            "version": _package_version("optiland"),
            "pinned_version": "0.6.0",
            "import_error": (
                None
                if available
                else f"{type(OPTILAND_IMPORT_ERROR).__name__}: {OPTILAND_IMPORT_ERROR}"
            ),
        },
        "capabilities": {
            "model_editing_without_engine": True,
            "sequential_ray_trace": available,
            "spot_diagram": available,
            "geometric_and_fft_mtf": available,
            "deterministic_optimization": available,
            "seeded_monte_carlo_tolerancing": available,
            "glass_catalog": available,
            "rendering": available,
        },
        "output_dir": str(OUTPUT_DIR),
        "install": "./install.sh --with-design",
    }


_REFERENCE = {
    "units": (
        "Prescription radii, thicknesses, apertures, ray intercepts, and spot "
        "metrics are mm. Fields of type angle are deg; object/image-height fields "
        "are mm. Wavelengths are stored as nm and converted to Optiland micrometers. "
        "MTF frequencies are cycles/mm. Hx, Hy, Px, and Py are normalized coordinates."
    ),
    "surfaces": (
        "The first surface is role=object and the last role=image. Interior surfaces "
        "support standard, plane, even_asphere, odd_asphere, and paraxial geometry. "
        "radius_mm=null means planar; object thickness_mm=null means infinity. "
        "material is the medium after each surface (for example N-BK7, then air)."
    ),
    "optimization": (
        "Optimization wraps Optiland OptimizationProblem and OptimizerGeneric. "
        "Variables use explicit type/surface_number/bounds. Operand input_data uses "
        "wavelength_nm (converted to um) and normalized ray coordinates. Methods are "
        "deterministic SciPy minimizers; stochastic global optimizers are intentionally "
        "not exposed."
    ),
    "tolerancing": (
        "Monte Carlo tolerancing uses Optiland Tolerancing, DistributionSampler, "
        "and MonteCarlo. Every perturbation receives seed+index, results are reset "
        "to nominal after evaluation, and repeated calls with the same model and "
        "arguments regenerate identical numeric results."
    ),
    "limitations": (
        "Optiland is an optional dependency pinned at 0.6.0. Engine-backed tools "
        "return ENGINE_UNAVAILABLE when it is absent. The server exposes Optiland's "
        "sequential model and catalog; it does not require or claim Zemax/CODE V "
        "compatibility. Surface updates cover common scalar prescription parameters; "
        "advanced freeforms can be passed through parameters but are not all editable "
        "through dedicated patch fields."
    ),
}


def handle_reference(args: dict) -> dict:
    topic = args.get("topic", "units")
    if topic not in _REFERENCE:
        raise ToolError(
            "REFERENCE_NOT_FOUND",
            f"Unknown topic '{topic}'.",
            {"topics": sorted(_REFERENCE)},
        )
    return {"topic": topic, "content": _REFERENCE[topic]}


def handle_new_model(args: dict) -> dict:
    name = str(args.get("name", "sequential-optical-model"))
    preset = args.get("preset", "empty")
    model = _default_model(name, preset)
    if args.get("metadata") is not None:
        if not isinstance(args["metadata"], dict):
            raise ToolError("VALIDATION_ERROR", "metadata must be an object.")
        model["metadata"] = args["metadata"]
    model_id = _slug(str(args.get("model_id") or name))
    if model_id in _models or _model_path(model_id).exists():
        model_id = f"{model_id}-{_digest(model, len(_models), length=8)}"
    _models[model_id] = model
    path = _persist(model_id)
    return {**_summary(model_id, model), "path": path, "preset": preset}


def handle_load_model(args: dict) -> dict:
    if bool(args.get("file_path")) == bool(args.get("model_json")):
        raise ToolError(
            "VALIDATION_ERROR",
            "Provide exactly one of file_path or model_json.",
        )
    if args.get("file_path"):
        path = Path(args["file_path"]).expanduser().resolve()
        if not path.exists():
            raise ToolError("FILE_NOT_FOUND", f"Model file not found: {path}")
        model = json.loads(path.read_text())
        fallback_id = path.stem
    else:
        model = args["model_json"]
        if isinstance(model, str):
            model = json.loads(model)
        fallback_id = model.get("name", "loaded-model")
    model = _validate_model(model)
    model_id = _slug(str(args.get("model_id") or fallback_id))
    _models[model_id] = model
    path = _persist(model_id)
    return {**_summary(model_id, model), "path": path}


def handle_save_model(args: dict) -> dict:
    model_id = args["model_id"]
    model = _get(model_id)
    if args.get("file_path"):
        path = Path(args["file_path"]).expanduser().resolve()
        if path.suffix.lower() != ".json":
            raise ToolError("VALIDATION_ERROR", "file_path must end in .json.")
        _atomic_json(path, model)
    else:
        path = Path(_persist(model_id))
    return {
        "model_id": model_id,
        "path": str(path),
        "model_digest": _digest(model, length=32),
        "file_sha256": _file_sha256(path),
    }


def handle_list_models(args: dict) -> dict:
    del args
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    records: dict[str, dict] = {}
    for path in sorted(MODELS_DIR.glob("*.json")):
        try:
            model = _validate_model(json.loads(path.read_text()))
            records[path.stem] = _summary(path.stem, model)
        except Exception as exc:
            records[path.stem] = {
                "model_id": path.stem,
                "path": str(path),
                "error": str(exc),
            }
    for model_id, model in _models.items():
        records[model_id] = _summary(model_id, model)
    return {"models": list(records.values()), "count": len(records)}


def handle_get_model(args: dict) -> dict:
    model = _get(args["model_id"])
    return {
        "model_id": args["model_id"],
        "model": model,
        "model_digest": _digest(model, length=32),
    }


def _normalize_surface_spec(spec: dict[str, Any], role: str = "surface") -> dict:
    surface_type = spec.get("surface_type", "standard")
    if surface_type not in _SURFACE_TYPES:
        raise ToolError(
            "VALIDATION_ERROR",
            f"Unsupported surface_type '{surface_type}'.",
            {"supported": sorted(_SURFACE_TYPES)},
        )
    radius = spec.get("radius_mm")
    if radius is not None:
        radius = _number(radius, "radius_mm")
        if radius == 0:
            raise ToolError("VALIDATION_ERROR", "radius_mm cannot be zero.")
    thickness = spec.get("thickness_mm", 0.0)
    if thickness is not None:
        thickness = _number(thickness, "thickness_mm")
    return _surface(
        role,
        radius_mm=radius,
        thickness_mm=thickness,
        material=str(spec.get("material", "air")),
        is_stop=bool(spec.get("is_stop", False)),
        comment=str(spec.get("comment", "")),
        surface_type=surface_type,
        conic=_number(spec.get("conic", 0.0), "conic"),
        parameters=dict(spec.get("parameters", {})),
    )


def handle_add_surface(args: dict) -> dict:
    model_id = args["model_id"]
    model = _get(model_id)
    index = args.get("index", len(model["surfaces"]) - 1)
    index = _integer(index, "index", minimum=1, maximum=len(model["surfaces"]) - 1)
    surface = _normalize_surface_spec(args["surface"])
    if surface["is_stop"]:
        for existing in model["surfaces"]:
            existing["is_stop"] = False
    model["surfaces"].insert(index, surface)
    _validate_model(model)
    _persist(model_id)
    return {
        "model_id": model_id,
        "index": index,
        "surface": surface,
        "surface_count": len(model["surfaces"]),
    }


def handle_update_surface(args: dict) -> dict:
    model_id = args["model_id"]
    model = _get(model_id)
    index = _integer(
        args["index"],
        "index",
        minimum=0,
        maximum=len(model["surfaces"]) - 1,
    )
    patch = args["patch"]
    if not isinstance(patch, dict):
        raise ToolError("VALIDATION_ERROR", "patch must be an object.")
    current = dict(model["surfaces"][index])
    if index in {0, len(model["surfaces"]) - 1} and "role" in patch:
        raise ToolError("VALIDATION_ERROR", "Object/image roles cannot be changed.")
    current.update(patch)
    current["role"] = model["surfaces"][index]["role"]
    normalized = _normalize_surface_spec(current, role=current["role"])
    if normalized["is_stop"]:
        for existing in model["surfaces"]:
            existing["is_stop"] = False
    model["surfaces"][index] = normalized
    _validate_model(model)
    _persist(model_id)
    return {"model_id": model_id, "index": index, "surface": normalized}


def handle_remove_surface(args: dict) -> dict:
    model_id = args["model_id"]
    model = _get(model_id)
    index = _integer(
        args["index"],
        "index",
        minimum=1,
        maximum=len(model["surfaces"]) - 2,
    )
    removed = model["surfaces"].pop(index)
    _validate_model(model)
    _persist(model_id)
    return {
        "model_id": model_id,
        "removed_index": index,
        "removed_surface": removed,
        "surface_count": len(model["surfaces"]),
    }


def handle_set_aperture_stop(args: dict) -> dict:
    model_id = args["model_id"]
    model = _get(model_id)
    aperture_type = args.get("aperture_type", "EPD")
    if aperture_type not in {"EPD", "imageFNO", "objectNA"}:
        raise ToolError("VALIDATION_ERROR", "Invalid aperture_type.")
    value = _number(args["value"], "value", positive=True)
    model["aperture"] = (
        {"type": aperture_type, "value_mm": value}
        if aperture_type == "EPD"
        else {"type": aperture_type, "value": value}
    )
    if "stop_index" in args:
        stop_index = _integer(
            args["stop_index"],
            "stop_index",
            minimum=1,
            maximum=len(model["surfaces"]) - 2,
        )
        for idx, surface in enumerate(model["surfaces"]):
            surface["is_stop"] = idx == stop_index
    _validate_model(model)
    _persist(model_id)
    return {
        "model_id": model_id,
        "aperture": model["aperture"],
        "stop_index": next(
            (idx for idx, surface in enumerate(model["surfaces"]) if surface["is_stop"]),
            None,
        ),
    }


def handle_set_fields(args: dict) -> dict:
    model_id = args["model_id"]
    model = _get(model_id)
    field_type = args["field_type"]
    if field_type not in {
        "angle",
        "object_height",
        "paraxial_image_height",
        "real_image_height",
    }:
        raise ToolError("VALIDATION_ERROR", "Invalid field_type.")
    items = args["fields"]
    if not isinstance(items, list) or not items:
        raise ToolError("VALIDATION_ERROR", "fields must be a non-empty array.")
    normalized = []
    for idx, field in enumerate(items):
        x = _number(
            field.get("x", field.get("x_deg", 0.0)),
            f"fields[{idx}].x",
        )
        y = _number(
            field.get("y", field.get("y_deg", 0.0)),
            f"fields[{idx}].y",
        )
        entry = {
            "x_deg" if field_type == "angle" else "x": x,
            "y_deg" if field_type == "angle" else "y": y,
            "vx": _number(field.get("vx", 0.0), f"fields[{idx}].vx"),
            "vy": _number(field.get("vy", 0.0), f"fields[{idx}].vy"),
            "weight": _number(
                field.get("weight", 1.0), f"fields[{idx}].weight", minimum=0
            ),
        }
        normalized.append(entry)
    model["fields"] = {"type": field_type, "items": normalized}
    _validate_model(model)
    _persist(model_id)
    return {
        "model_id": model_id,
        "field_type": field_type,
        "field_unit": "deg" if field_type == "angle" else "mm",
        "fields": normalized,
    }


def handle_set_wavelengths(args: dict) -> dict:
    model_id = args["model_id"]
    model = _get(model_id)
    values = args["wavelengths"]
    if not isinstance(values, list) or not values:
        raise ToolError("VALIDATION_ERROR", "wavelengths must be a non-empty array.")
    primary_index = _integer(
        args.get("primary_index", 0),
        "primary_index",
        minimum=0,
        maximum=len(values) - 1,
    )
    model["wavelengths"] = [
        {
            "value_nm": _number(
                wave["value_nm"], f"wavelengths[{idx}].value_nm", positive=True
            ),
            "weight": _number(
                wave.get("weight", 1.0), f"wavelengths[{idx}].weight", minimum=0
            ),
            "is_primary": idx == primary_index,
        }
        for idx, wave in enumerate(values)
    ]
    _validate_model(model)
    _persist(model_id)
    return {
        "model_id": model_id,
        "wavelengths": model["wavelengths"],
        "unit": "nm",
    }


def handle_materials(args: dict) -> dict:
    _require_optiland()
    query = str(args.get("query", "")).lower()
    limit = _integer(args.get("limit", 25), "limit", minimum=1, maximum=200)
    try:
        catalog = importlib.resources.files("optiland.database").joinpath("catalog_nk.csv")
        with catalog.open("r", encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
    except Exception as exc:
        raise ToolError(
            "CATALOG_ERROR",
            "Unable to read the Optiland glass catalog.",
            {"error": str(exc)},
        ) from exc
    if query:
        rows = [
            row
            for row in rows
            if query
            in " ".join(
                [
                    row.get("name", ""),
                    row.get("category_name", ""),
                    row.get("reference", ""),
                    row.get("filename_no_ext", ""),
                ]
            ).lower()
        ]
    results = []
    for row in rows[:limit]:
        results.append(
            {
                "name": row.get("name"),
                "category": row.get("category_name"),
                "reference": row.get("reference"),
                "min_wavelength_um": _jsonable(
                    float(row["min_wavelength"]) if row.get("min_wavelength") else None
                ),
                "max_wavelength_um": _jsonable(
                    float(row["max_wavelength"]) if row.get("max_wavelength") else None
                ),
            }
        )
    validation = None
    if args.get("validate_name"):
        with _quiet_optiland():
            material = Material(
                args["validate_name"],
                reference=args.get("reference"),
                robust_search=False,
            )
            validation = {
                "requested": args["validate_name"],
                "resolved_name": material.name,
                "metadata": _jsonable(material.material_data),
            }
    return {
        "query": query,
        "count": len(results),
        "materials": results,
        "validation": validation,
        "catalog": "Optiland refractiveindex.info package data",
    }


def handle_trace(args: dict) -> dict:
    model_id = args["model_id"]
    model = _get(model_id)
    system = _build_optic(model)
    wavelength_nm = _number(
        args.get("wavelength_nm", _primary_wavelength_nm(model)),
        "wavelength_nm",
        positive=True,
    )
    hx = _number(args.get("Hx", 0.0), "Hx")
    hy = _number(args.get("Hy", 0.0), "Hy")
    num_rays = _integer(args.get("num_rays", 32), "num_rays", minimum=1, maximum=1024)
    distribution = args.get("distribution", "uniform")
    with _quiet_optiland():
        rays = system.trace(
            Hx=hx,
            Hy=hy,
            wavelength=wavelength_nm / 1000.0,
            num_rays=num_rays,
            distribution=distribution,
        )
    x, y, z = map(lambda value: np.asarray(value, dtype=float), (rays.x, rays.y, rays.z))
    L, M, N = map(lambda value: np.asarray(value, dtype=float), (rays.L, rays.M, rays.N))
    intensity = np.asarray(rays.i, dtype=float)
    op_args = {
        "wavelength_nm": wavelength_nm,
        "Hx": hx,
        "Hy": hy,
        "num_rays": num_rays,
        "distribution": distribution,
    }
    path = _artifact_path(model_id, "trace", "npz", op_args)
    np.savez_compressed(
        path,
        x_mm=x,
        y_mm=y,
        z_mm=z,
        L=L,
        M=M,
        N=N,
        intensity=intensity,
        opd_mm=np.asarray(rays.opd),
        wavelength_nm=np.array(wavelength_nm),
    )
    valid = np.isfinite(x) & np.isfinite(y) & (intensity > 0)
    return {
        "model_id": model_id,
        "artifact_path": str(path),
        "numeric_sha256": _array_sha256(x, y, z, L, M, N, intensity),
        "engine": "optiland.Optic.trace",
        "length_unit": "mm",
        "direction_cosine_unit": "dimensionless",
        "wavelength_nm": wavelength_nm,
        "field_normalized": {"Hx": hx, "Hy": hy},
        "generated_ray_count": int(len(x)),
        "valid_ray_count": int(valid.sum()),
        "centroid_mm": {
            "x": float(np.nanmean(x[valid])) if np.any(valid) else None,
            "y": float(np.nanmean(y[valid])) if np.any(valid) else None,
        },
        "rms_radius_mm": (
            float(
                np.sqrt(
                    np.mean(
                        (x[valid] - np.mean(x[valid])) ** 2
                        + (y[valid] - np.mean(y[valid])) ** 2
                    )
                )
            )
            if np.any(valid)
            else None
        ),
    }


def _spot_analysis(
    model_id: str,
    num_rings: int,
    distribution: str,
    reference: str,
) -> tuple[Any, list[list[float]], Path]:
    model = _get(model_id)
    system = _build_optic(model)
    with _quiet_optiland():
        analysis = SpotDiagram(
            system,
            fields="all",
            wavelengths="all",
            num_rings=num_rings,
            distribution=distribution,
            reference=reference,
        )
        rms = [[float(np.asarray(value)) for value in row] for row in analysis.rms_spot_radius()]
        geo = [
            [float(np.asarray(value)) for value in row]
            for row in analysis.geometric_spot_radius()
        ]
    arrays: dict[str, np.ndarray] = {}
    for field_index, field_data in enumerate(analysis.data):
        for wave_index, spot in enumerate(field_data):
            arrays[f"field_{field_index}_wave_{wave_index}_x_mm"] = np.asarray(spot.x)
            arrays[f"field_{field_index}_wave_{wave_index}_y_mm"] = np.asarray(spot.y)
            arrays[f"field_{field_index}_wave_{wave_index}_intensity"] = np.asarray(
                spot.intensity
            )
    op_args = {
        "num_rings": num_rings,
        "distribution": distribution,
        "reference": reference,
    }
    path = _artifact_path(model_id, "spot", "npz", op_args)
    np.savez_compressed(path, **arrays)
    analysis._sciviz_geometric_radius = geo
    return analysis, rms, path


def handle_spot(args: dict) -> dict:
    model_id = args["model_id"]
    num_rings = _integer(args.get("num_rings", 6), "num_rings", minimum=2, maximum=64)
    distribution = args.get("distribution", "hexapolar")
    reference = args.get("reference", "chief_ray")
    analysis, rms, path = _spot_analysis(
        model_id, num_rings, distribution, reference
    )
    return {
        "model_id": model_id,
        "artifact_path": str(path),
        "engine": "optiland.analysis.SpotDiagram",
        "length_unit": "mm",
        "fields": [
            {"index": idx, "coordinates": list(map(float, field.coord))}
            for idx, field in enumerate(analysis.fields)
        ],
        "wavelengths_nm": [float(wave.value) * 1000 for wave in analysis.wavelengths],
        "rms_spot_radius_mm": rms,
        "geometric_spot_radius_mm": analysis._sciviz_geometric_radius,
        "reference": reference,
    }


def _mtf_analysis(
    model_id: str,
    method: str,
    num_rays: int,
    num_points: int,
    max_frequency: float | str,
) -> tuple[Any, Path]:
    model = _get(model_id)
    system = _build_optic(model)
    with _quiet_optiland():
        if method == "geometric":
            analysis = GeometricMTF(
                system,
                fields="all",
                wavelength="primary",
                num_rays=num_rays,
                num_points=num_points,
                max_freq=max_frequency,
            )
        elif method == "fft":
            analysis = FFTMTF(
                system,
                fields="all",
                wavelength="primary",
                num_rays=num_rays,
                max_freq=max_frequency,
            )
        else:
            raise ToolError(
                "VALIDATION_ERROR",
                f"Unknown MTF method '{method}'.",
                {"supported": ["geometric", "fft"]},
            )
    arrays: dict[str, np.ndarray] = {}
    if method == "geometric":
        arrays["frequency_cycles_per_mm"] = np.asarray(analysis.freq)
        for idx, values in enumerate(analysis.mtf):
            arrays[f"field_{idx}_tangential"] = np.asarray(values[0])
            arrays[f"field_{idx}_sagittal"] = np.asarray(values[1])
    else:
        for idx, values in enumerate(analysis.mtf):
            arrays[f"field_{idx}_frequency_tangential_cycles_per_mm"] = np.asarray(
                analysis.freq_tang[idx]
            )
            arrays[f"field_{idx}_frequency_sagittal_cycles_per_mm"] = np.asarray(
                analysis.freq_sag[idx]
            )
            arrays[f"field_{idx}_tangential"] = np.asarray(values[0])
            arrays[f"field_{idx}_sagittal"] = np.asarray(values[1])
    op_args = {
        "method": method,
        "num_rays": num_rays,
        "num_points": num_points,
        "max_frequency_cycles_per_mm": max_frequency,
    }
    path = _artifact_path(model_id, f"mtf-{method}", "npz", op_args)
    np.savez_compressed(path, **arrays)
    return analysis, path


def handle_mtf(args: dict) -> dict:
    model_id = args["model_id"]
    method = args.get("method", "geometric")
    num_rays = _integer(args.get("num_rays", 32), "num_rays", minimum=4, maximum=512)
    num_points = _integer(args.get("num_points", 128), "num_points", minimum=16, maximum=2048)
    max_frequency = args.get("max_frequency_cycles_per_mm", "cutoff")
    if max_frequency != "cutoff":
        max_frequency = _number(max_frequency, "max_frequency_cycles_per_mm", positive=True)
    analysis, path = _mtf_analysis(
        model_id, method, num_rays, num_points, max_frequency
    )
    fields = []
    for idx, values in enumerate(analysis.mtf):
        if method == "geometric":
            ft = fs = np.asarray(analysis.freq)
        else:
            ft = np.asarray(analysis.freq_tang[idx])
            fs = np.asarray(analysis.freq_sag[idx])
        tang = np.asarray(values[0])
        sag = np.asarray(values[1])
        fields.append(
            {
                "field_index": idx,
                "field_coordinates": list(map(float, analysis.resolved_fields[idx]))
                if hasattr(analysis, "resolved_fields")
                else list(map(float, analysis.fields[idx].coord)),
                "dc_mtf": {"tangential": float(tang[0]), "sagittal": float(sag[0])},
                "tangential_sample_count": int(len(ft)),
                "sagittal_sample_count": int(len(fs)),
            }
        )
    return {
        "model_id": model_id,
        "artifact_path": str(path),
        "engine": f"optiland.mtf.{type(analysis).__name__}",
        "method": method,
        "frequency_unit": "cycles/mm",
        "wavelength_nm": _primary_wavelength_nm(_get(model_id)),
        "fields": fields,
    }


def handle_optimize(args: dict) -> dict:
    model_id = args["model_id"]
    model = _get(model_id)
    system = _build_optic(model)
    variables = args.get("variables", [])
    operands = args.get("operands", [])
    if not variables or not operands:
        raise ToolError("VALIDATION_ERROR", "variables and operands must be non-empty.")
    with _quiet_optiland():
        problem = OptimizationProblem(batching=False)
        for idx, variable in enumerate(variables):
            kind = variable.get("type")
            if kind not in _VARIABLE_TYPES:
                raise ToolError(
                    "VALIDATION_ERROR",
                    f"Unsupported variable type '{kind}' at variables[{idx}].",
                    {"supported": sorted(_VARIABLE_TYPES)},
                )
            kwargs = {
                key: value
                for key, value in variable.items()
                if key not in {"type", "min", "max"}
            }
            problem.add_variable(
                system,
                kind,
                min_val=variable.get("min"),
                max_val=variable.get("max"),
                **kwargs,
            )
        for idx, operand in enumerate(operands):
            kind = operand.get("type")
            if kind not in _OPERAND_TYPES:
                raise ToolError(
                    "VALIDATION_ERROR",
                    f"Unsupported operand type '{kind}' at operands[{idx}].",
                    {"supported": sorted(_OPERAND_TYPES)},
                )
            input_data = _normalize_input_data(operand.get("input_data", {}), system)
            problem.add_operand(
                operand_type=kind,
                target=operand.get("target"),
                min_val=operand.get("min"),
                max_val=operand.get("max"),
                weight=operand.get("weight", 1.0),
                input_data=input_data,
            )
        initial_merit = float(np.asarray(problem.sum_squared()))
        optimizer = OptimizerGeneric(problem)
        result = optimizer.optimize(
            method=args.get("method"),
            maxiter=_integer(args.get("max_iterations", 100), "max_iterations", minimum=1, maximum=10000),
            disp=False,
            tol=_number(args.get("tolerance", 1e-6), "tolerance", positive=True),
        )
        final_merit = float(np.asarray(problem.sum_squared()))
    _update_model_from_variables(model, system, variables)
    _validate_model(model)
    _persist(model_id)
    result_data = {
        "success": bool(result.success),
        "status": int(result.status),
        "message": str(result.message),
        "iterations": int(getattr(result, "nit", 0)),
        "function_evaluations": int(getattr(result, "nfev", 0)),
        "initial_merit": initial_merit,
        "final_merit": final_merit,
        "optimized_scaled_variables": [float(value) for value in np.asarray(result.x)],
        "variable_units": [_variable_unit(item["type"]) for item in variables],
        "operand_units": [_operand_unit(item["type"]) for item in operands],
    }
    path = _artifact_path(
        model_id,
        "optimization",
        "json",
        {
            "variables": variables,
            "operands": operands,
            "method": args.get("method"),
            "max_iterations": args.get("max_iterations", 100),
            "tolerance": args.get("tolerance", 1e-6),
        },
    )
    _atomic_json(path, result_data)
    return {
        "model_id": model_id,
        "artifact_path": str(path),
        "engine": "optiland.optimization.OptimizerGeneric",
        "model_persisted": True,
        **result_data,
    }


def handle_tolerance(args: dict) -> dict:
    model_id = args["model_id"]
    model = _get(model_id)
    system = _build_optic(model)
    seed = _integer(args.get("seed", 20260711), "seed", minimum=0, maximum=2**32 - 1)
    iterations = _integer(
        args.get("iterations", 100), "iterations", minimum=1, maximum=10000
    )
    perturbations = args.get("perturbations", [])
    operands = args.get("operands", [])
    if not perturbations or not operands:
        raise ToolError("VALIDATION_ERROR", "perturbations and operands must be non-empty.")
    with _quiet_optiland():
        tolerancing = Tolerancing(system)
        for idx, perturbation in enumerate(perturbations):
            kind = perturbation.get("type")
            if kind not in _VARIABLE_TYPES:
                raise ToolError(
                    "VALIDATION_ERROR",
                    f"Unsupported perturbation type '{kind}'.",
                )
            distribution = perturbation.get("distribution", "normal")
            if distribution == "normal":
                params = {
                    "loc": _number(perturbation.get("mean", 0.0), f"perturbations[{idx}].mean"),
                    "scale": _number(
                        perturbation.get("sigma"),
                        f"perturbations[{idx}].sigma",
                        positive=True,
                    ),
                }
            elif distribution == "uniform":
                low = _number(perturbation.get("low"), f"perturbations[{idx}].low")
                high = _number(perturbation.get("high"), f"perturbations[{idx}].high")
                if high <= low:
                    raise ToolError("VALIDATION_ERROR", "Uniform high must exceed low.")
                params = {"low": low, "high": high}
            else:
                raise ToolError(
                    "VALIDATION_ERROR",
                    "distribution must be normal or uniform.",
                )
            sampler = DistributionSampler(distribution, seed=seed + idx, **params)
            variable_kwargs = {
                key: value
                for key, value in perturbation.items()
                if key
                not in {
                    "type",
                    "distribution",
                    "mean",
                    "sigma",
                    "low",
                    "high",
                }
            }
            tolerancing.add_perturbation(kind, sampler, **variable_kwargs)
        for idx, operand in enumerate(operands):
            kind = operand.get("type")
            if kind not in _OPERAND_TYPES:
                raise ToolError("VALIDATION_ERROR", f"Unsupported operand '{kind}'.")
            tolerancing.add_operand(
                kind,
                input_data=_normalize_input_data(operand.get("input_data", {}), system),
                target=operand.get("target"),
                weight=operand.get("weight", 1.0),
                min_val=operand.get("min"),
                max_val=operand.get("max"),
            )
        analysis = MonteCarlo(tolerancing)
        analysis.run(iterations)
        results = analysis._results.copy()
        tolerancing.reset()
    op_args = {
        "seed": seed,
        "iterations": iterations,
        "perturbations": perturbations,
        "operands": operands,
    }
    path = _artifact_path(model_id, "tolerance", "csv", op_args)
    results.to_csv(path, index=False, float_format="%.17g")
    summary = {}
    for column in results.columns:
        values = np.asarray(results[column], dtype=float)
        summary[column] = {
            "mean": float(np.mean(values)),
            "std": float(np.std(values, ddof=0)),
            "min": float(np.min(values)),
            "p05": float(np.quantile(values, 0.05)),
            "p50": float(np.quantile(values, 0.50)),
            "p95": float(np.quantile(values, 0.95)),
            "max": float(np.max(values)),
        }
    return {
        "model_id": model_id,
        "artifact_path": str(path),
        "file_sha256": _file_sha256(path),
        "engine": "optiland.tolerancing.MonteCarlo",
        "seed": seed,
        "iterations": iterations,
        "results_reset_to_nominal": True,
        "perturbation_units": [
            _variable_unit(item["type"]) for item in perturbations
        ],
        "operand_units": [_operand_unit(item["type"]) for item in operands],
        "summary": summary,
    }


def handle_render(args: dict) -> dict:
    model_id = args["model_id"]
    model = _get(model_id)
    system = _build_optic(model)
    kind = args.get("kind", "layout")
    render_args = dict(args)
    render_args.pop("model_id", None)
    if args.get("output_file"):
        path = Path(args["output_file"]).expanduser().resolve()
        if path.suffix.lower() != ".png":
            raise ToolError("VALIDATION_ERROR", "output_file must end in .png.")
        path.parent.mkdir(parents=True, exist_ok=True)
    else:
        path = _render_path(model_id, kind, render_args)
    apply_aps_style()
    with _quiet_optiland():
        if kind == "layout":
            fig, _ = system.draw(
                fields="all",
                wavelengths="primary",
                num_rays=_integer(args.get("num_rays", 5), "num_rays", minimum=1, maximum=100),
                title=None,
            )
        elif kind == "spot":
            analysis, _, _ = _spot_analysis(
                model_id,
                _integer(args.get("num_rings", 6), "num_rings", minimum=2, maximum=64),
                args.get("distribution", "hexapolar"),
                args.get("reference", "chief_ray"),
            )
            fig, _ = analysis.view(add_airy_disk=bool(args.get("add_airy_disk", True)))
        elif kind == "mtf":
            analysis, _ = _mtf_analysis(
                model_id,
                args.get("method", "geometric"),
                _integer(args.get("num_rays", 32), "num_rays", minimum=4, maximum=512),
                _integer(args.get("num_points", 128), "num_points", minimum=16, maximum=2048),
                args.get("max_frequency_cycles_per_mm", "cutoff"),
            )
            fig, _ = analysis.view(add_reference=True)
        else:
            raise ToolError(
                "VALIDATION_ERROR",
                f"Unknown render kind '{kind}'.",
                {"supported": ["layout", "spot", "mtf"]},
            )
    add_figure_attribution(fig)
    fig.savefig(
        path,
        dpi=_integer(args.get("dpi", 300), "dpi", minimum=72, maximum=1200),
        bbox_inches="tight",
    )
    plt.close(fig)
    notify_preview(
        str(path),
        "optical_design_render",
        render_args,
        server_name="optical_design_mcp",
    )
    return {
        "model_id": model_id,
        "kind": kind,
        "image_path": str(path),
        "file_sha256": _file_sha256(path),
        "attribution": ATTRIBUTION_TEXT,
    }


def handle_export(args: dict) -> dict:
    model_id = args["model_id"]
    model = _get(model_id)
    export_type = args.get("export_type", "model_json")
    if export_type == "model_json":
        path = (
            Path(args["output_file"]).expanduser().resolve()
            if args.get("output_file")
            else _artifact_path(model_id, "prescription", "json", {})
        )
        _atomic_json(path, model)
    elif export_type == "optiland_json":
        system = _build_optic(model)
        with _quiet_optiland():
            data = system.to_dict()
        path = (
            Path(args["output_file"]).expanduser().resolve()
            if args.get("output_file")
            else _artifact_path(model_id, "optiland-native", "json", {})
        )
        _atomic_json(path, data)
    elif export_type == "prescription_csv":
        path = (
            Path(args["output_file"]).expanduser().resolve()
            if args.get("output_file")
            else _artifact_path(model_id, "prescription", "csv", {})
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(
                [
                    "index",
                    "role",
                    "surface_type",
                    "radius_mm",
                    "thickness_mm",
                    "material_after",
                    "conic",
                    "is_stop",
                    "comment",
                ]
            )
            for idx, surface in enumerate(model["surfaces"]):
                writer.writerow(
                    [
                        idx,
                        surface["role"],
                        surface["surface_type"],
                        "infinity" if surface["radius_mm"] is None else surface["radius_mm"],
                        "infinity"
                        if surface["thickness_mm"] is None
                        else surface["thickness_mm"],
                        surface["material"],
                        surface["conic"],
                        surface["is_stop"],
                        surface["comment"],
                    ]
                )
    elif export_type == "result_copy":
        source = Path(args.get("source_artifact", "")).expanduser().resolve()
        if not source.exists() or source.suffix.lower() not in {
            ".json",
            ".csv",
            ".npz",
            ".png",
        }:
            raise ToolError(
                "VALIDATION_ERROR",
                "source_artifact must be an existing JSON, CSV, NPZ, or PNG.",
            )
        if args.get("output_file"):
            path = Path(args["output_file"]).expanduser().resolve()
        else:
            path = _artifact_path(
                model_id,
                f"result-{source.stem}",
                source.suffix.lstrip("."),
                {"source_sha256": _file_sha256(source)},
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, path)
    else:
        raise ToolError(
            "VALIDATION_ERROR",
            f"Unknown export_type '{export_type}'.",
            {
                "supported": [
                    "model_json",
                    "optiland_json",
                    "prescription_csv",
                    "result_copy",
                ]
            },
        )
    return {
        "model_id": model_id,
        "export_type": export_type,
        "path": str(path),
        "file_sha256": _file_sha256(path),
    }


_MODEL_ID = {"type": "string", "description": "Persistent sequential optical model ID"}
_SURFACE_OBJECT = {
    "type": "object",
    "properties": {
        "surface_type": {
            "type": "string",
            "enum": sorted(_SURFACE_TYPES),
            "default": "standard",
        },
        "radius_mm": {
            "type": ["number", "null"],
            "description": "Radius in mm; null is planar",
        },
        "thickness_mm": {
            "type": ["number", "null"],
            "description": "Distance to next surface in mm; null is infinity",
        },
        "material": {
            "type": "string",
            "default": "air",
            "description": "Optiland material after the surface, e.g. N-BK7",
        },
        "is_stop": {"type": "boolean", "default": False},
        "comment": {"type": "string"},
        "conic": {"type": "number", "default": 0},
        "parameters": {
            "type": "object",
            "description": "Optiland geometry-specific parameters in mm/radians as documented",
        },
    },
    "additionalProperties": False,
}
_OPERAND_SCHEMA = {
    "type": "object",
    "properties": {
        "type": {"type": "string", "enum": sorted(_OPERAND_TYPES)},
        "target": {"type": "number"},
        "min": {"type": "number"},
        "max": {"type": "number"},
        "weight": {"type": "number", "minimum": 0, "default": 1},
        "input_data": {
            "type": "object",
            "description": (
                "Optiland operand inputs. Use wavelength_nm for physical wavelength; "
                "Hx/Hy/Px/Py are normalized; surface_number is zero-based."
            ),
        },
    },
    "required": ["type", "input_data"],
    "additionalProperties": False,
}


TOOLS = {
    "optical_design_health": {
        "handler": handle_health,
        "description": "Report optional Optiland 0.6.0 availability and server capabilities.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    "optical_design_reference": {
        "handler": handle_reference,
        "description": "Return unit, surface, optimization, tolerancing, or limitation reference.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "enum": ["units", "surfaces", "optimization", "tolerancing", "limitations"],
                    "default": "units",
                }
            },
            "additionalProperties": False,
        },
    },
    "optical_design_new_model": {
        "handler": handle_new_model,
        "description": "Create and persist an empty or biconvex-singlet sequential prescription.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "model_id": {"type": "string"},
                "preset": {
                    "type": "string",
                    "enum": ["empty", "biconvex_singlet"],
                    "default": "empty",
                },
                "metadata": {"type": "object"},
            },
            "additionalProperties": False,
        },
    },
    "optical_design_load_model": {
        "handler": handle_load_model,
        "description": "Load and validate a server-native sequential prescription JSON.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string"},
                "model_json": {"oneOf": [{"type": "object"}, {"type": "string"}]},
                "model_id": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
    "optical_design_save_model": {
        "handler": handle_save_model,
        "description": "Save a sequential prescription to managed storage or an explicit JSON file.",
        "inputSchema": {
            "type": "object",
            "properties": {"model_id": _MODEL_ID, "file_path": {"type": "string"}},
            "required": ["model_id"],
            "additionalProperties": False,
        },
    },
    "optical_design_list_models": {
        "handler": handle_list_models,
        "description": "List in-memory and persisted sequential optical models.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    "optical_design_get_model": {
        "handler": handle_get_model,
        "description": "Return the complete explicit-unit sequential prescription.",
        "inputSchema": {
            "type": "object",
            "properties": {"model_id": _MODEL_ID},
            "required": ["model_id"],
            "additionalProperties": False,
        },
    },
    "optical_design_add_surface": {
        "handler": handle_add_surface,
        "description": "Insert a refractive/reflective prescription surface before the image plane.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "model_id": _MODEL_ID,
                "index": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Insertion index; defaults immediately before image",
                },
                "surface": _SURFACE_OBJECT,
            },
            "required": ["model_id", "surface"],
            "additionalProperties": False,
        },
    },
    "optical_design_update_surface": {
        "handler": handle_update_surface,
        "description": "Patch radius, thickness, material, stop, conic, type, or geometry parameters.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "model_id": _MODEL_ID,
                "index": {"type": "integer", "minimum": 0},
                "patch": _SURFACE_OBJECT,
            },
            "required": ["model_id", "index", "patch"],
            "additionalProperties": False,
        },
    },
    "optical_design_remove_surface": {
        "handler": handle_remove_surface,
        "description": "Remove an interior prescription surface; object/image planes are protected.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "model_id": _MODEL_ID,
                "index": {"type": "integer", "minimum": 1},
            },
            "required": ["model_id", "index"],
            "additionalProperties": False,
        },
    },
    "optical_design_set_aperture_stop": {
        "handler": handle_set_aperture_stop,
        "description": "Set EPD in mm, image F-number, or object NA and optionally the stop index.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "model_id": _MODEL_ID,
                "aperture_type": {
                    "type": "string",
                    "enum": ["EPD", "imageFNO", "objectNA"],
                    "default": "EPD",
                },
                "value": {"type": "number", "exclusiveMinimum": 0},
                "stop_index": {"type": "integer", "minimum": 1},
            },
            "required": ["model_id", "value"],
            "additionalProperties": False,
        },
    },
    "optical_design_set_fields": {
        "handler": handle_set_fields,
        "description": "Replace angular fields in deg or object/image-height fields in mm.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "model_id": _MODEL_ID,
                "field_type": {
                    "type": "string",
                    "enum": [
                        "angle",
                        "object_height",
                        "paraxial_image_height",
                        "real_image_height",
                    ],
                },
                "fields": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "properties": {
                            "x_deg": {"type": "number"},
                            "y_deg": {"type": "number"},
                            "x": {"type": "number"},
                            "y": {"type": "number"},
                            "vx": {"type": "number", "default": 0},
                            "vy": {"type": "number", "default": 0},
                            "weight": {"type": "number", "minimum": 0, "default": 1},
                        },
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["model_id", "field_type", "fields"],
            "additionalProperties": False,
        },
    },
    "optical_design_set_wavelengths": {
        "handler": handle_set_wavelengths,
        "description": "Replace weighted wavelengths in nm and select the primary index.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "model_id": _MODEL_ID,
                "wavelengths": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "properties": {
                            "value_nm": {"type": "number", "exclusiveMinimum": 0},
                            "weight": {"type": "number", "minimum": 0, "default": 1},
                        },
                        "required": ["value_nm"],
                        "additionalProperties": False,
                    },
                },
                "primary_index": {"type": "integer", "minimum": 0, "default": 0},
            },
            "required": ["model_id", "wavelengths"],
            "additionalProperties": False,
        },
    },
    "optical_design_materials": {
        "handler": handle_materials,
        "description": "Search or exactly validate materials in Optiland's refractiveindex.info catalog.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 25},
                "validate_name": {"type": "string"},
                "reference": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
    "optical_design_trace": {
        "handler": handle_trace,
        "description": "Trace a deterministic Optiland ray distribution and export final rays to NPZ.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "model_id": _MODEL_ID,
                "Hx": {"type": "number", "default": 0, "description": "Normalized x field"},
                "Hy": {"type": "number", "default": 0, "description": "Normalized y field"},
                "wavelength_nm": {"type": "number", "exclusiveMinimum": 0},
                "num_rays": {"type": "integer", "minimum": 1, "maximum": 1024, "default": 32},
                "distribution": {
                    "type": "string",
                    "enum": ["uniform", "hexapolar", "random", "ring"],
                    "default": "uniform",
                },
            },
            "required": ["model_id"],
            "additionalProperties": False,
        },
    },
    "optical_design_spot": {
        "handler": handle_spot,
        "description": "Calculate Optiland spot diagrams with RMS/geometric radii in mm and NPZ rays.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "model_id": _MODEL_ID,
                "num_rings": {"type": "integer", "minimum": 2, "maximum": 64, "default": 6},
                "distribution": {
                    "type": "string",
                    "enum": ["hexapolar", "uniform", "random", "ring"],
                    "default": "hexapolar",
                },
                "reference": {
                    "type": "string",
                    "enum": ["chief_ray", "centroid"],
                    "default": "chief_ray",
                },
            },
            "required": ["model_id"],
            "additionalProperties": False,
        },
    },
    "optical_design_mtf": {
        "handler": handle_mtf,
        "description": "Calculate Optiland geometric or FFT MTF and export all field curves to NPZ.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "model_id": _MODEL_ID,
                "method": {
                    "type": "string",
                    "enum": ["geometric", "fft"],
                    "default": "geometric",
                },
                "num_rays": {"type": "integer", "minimum": 4, "maximum": 512, "default": 32},
                "num_points": {"type": "integer", "minimum": 16, "maximum": 2048, "default": 128},
                "max_frequency_cycles_per_mm": {
                    "type": "number",
                    "exclusiveMinimum": 0,
                    "description": "Omit to use diffraction cutoff",
                },
            },
            "required": ["model_id"],
            "additionalProperties": False,
        },
    },
    "optical_design_optimize": {
        "handler": handle_optimize,
        "description": "Run deterministic Optiland/SciPy prescription optimization and persist optimized values.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "model_id": _MODEL_ID,
                "variables": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string", "enum": sorted(_VARIABLE_TYPES)},
                            "surface_number": {"type": "integer"},
                            "min": {"type": "number"},
                            "max": {"type": "number"},
                            "coeff_number": {"type": "integer"},
                            "axis": {"type": "string"},
                            "wavelength": {"type": "number"},
                        },
                        "required": ["type", "surface_number"],
                        "additionalProperties": False,
                    },
                },
                "operands": {"type": "array", "minItems": 1, "items": _OPERAND_SCHEMA},
                "method": {
                    "type": "string",
                    "enum": ["Nelder-Mead", "Powell", "L-BFGS-B", "SLSQP", "BFGS"],
                },
                "max_iterations": {"type": "integer", "minimum": 1, "maximum": 10000, "default": 100},
                "tolerance": {"type": "number", "exclusiveMinimum": 0, "default": 1e-6},
            },
            "required": ["model_id", "variables", "operands"],
            "additionalProperties": False,
        },
    },
    "optical_design_tolerance": {
        "handler": handle_tolerance,
        "description": "Run seeded Optiland Monte Carlo tolerancing and export deterministic CSV results.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "model_id": _MODEL_ID,
                "seed": {"type": "integer", "minimum": 0, "maximum": 4294967295, "default": 20260711},
                "iterations": {"type": "integer", "minimum": 1, "maximum": 10000, "default": 100},
                "perturbations": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string", "enum": sorted(_VARIABLE_TYPES)},
                            "surface_number": {"type": "integer"},
                            "distribution": {
                                "type": "string",
                                "enum": ["normal", "uniform"],
                                "default": "normal",
                            },
                            "mean": {
                                "type": "number",
                                "description": (
                                    "Absolute sampled-variable mean: mm for radius/"
                                    "thickness/decenter, rad for tilt, otherwise dimensionless"
                                ),
                            },
                            "sigma": {
                                "type": "number",
                                "exclusiveMinimum": 0,
                                "description": "Standard deviation in the same unit as mean",
                            },
                            "low": {
                                "type": "number",
                                "description": "Uniform lower bound in variable-native units",
                            },
                            "high": {
                                "type": "number",
                                "description": "Uniform upper bound in variable-native units",
                            },
                            "coeff_number": {"type": "integer"},
                            "axis": {"type": "string"},
                            "wavelength": {"type": "number"},
                        },
                        "required": ["type", "surface_number", "distribution"],
                        "additionalProperties": False,
                    },
                },
                "operands": {"type": "array", "minItems": 1, "items": _OPERAND_SCHEMA},
            },
            "required": ["model_id", "perturbations", "operands"],
            "additionalProperties": False,
        },
    },
    "optical_design_render": {
        "handler": handle_render,
        "description": "Render an attributed Optiland layout, spot diagram, or MTF figure.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "model_id": _MODEL_ID,
                "kind": {"type": "string", "enum": ["layout", "spot", "mtf"], "default": "layout"},
                "output_file": {"type": "string"},
                "dpi": {"type": "integer", "minimum": 72, "maximum": 1200, "default": 300},
                "num_rays": {"type": "integer", "minimum": 1, "maximum": 512},
                "num_rings": {"type": "integer", "minimum": 2, "maximum": 64},
                "num_points": {"type": "integer", "minimum": 16, "maximum": 2048},
                "distribution": {"type": "string"},
                "reference": {"type": "string"},
                "add_airy_disk": {"type": "boolean", "default": True},
                "method": {"type": "string", "enum": ["geometric", "fft"]},
                "max_frequency_cycles_per_mm": {"type": "number", "exclusiveMinimum": 0},
            },
            "required": ["model_id", "kind"],
            "additionalProperties": False,
        },
    },
    "optical_design_export": {
        "handler": handle_export,
        "description": "Export server JSON, native Optiland JSON, prescription CSV, or copy a result artifact.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "model_id": _MODEL_ID,
                "export_type": {
                    "type": "string",
                    "enum": ["model_json", "optiland_json", "prescription_csv", "result_copy"],
                    "default": "model_json",
                },
                "source_artifact": {"type": "string"},
                "output_file": {"type": "string"},
            },
            "required": ["model_id"],
            "additionalProperties": False,
        },
    },
}


def _send_response(req_id: Any, result: Any = None, error: dict | None = None) -> None:
    response = {"jsonrpc": "2.0", "id": req_id}
    if error is not None:
        response["error"] = error
    else:
        response["result"] = result if result is not None else {}
    sys.stdout.write(json.dumps(_jsonable(response), separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _initialize() -> dict:
    return {
        "protocolVersion": "2024-11-05",
        "capabilities": {"tools": {}},
        "serverInfo": {"name": "optical_design_mcp", "version": SERVER_VERSION},
    }


def _tools_list() -> dict:
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


def _tools_call(params: dict) -> dict:
    name = resolve_tool_name(params.get("name"), TOOLS)
    if name not in TOOLS:
        raise ToolError("TOOL_NOT_FOUND", f"Unknown tool '{name}'.")
    arguments = params.get("arguments") or {}
    if not isinstance(arguments, dict):
        raise ToolError("VALIDATION_ERROR", "Tool arguments must be an object.")
    result = TOOLS[name]["handler"](arguments)
    return {"content": [{"type": "text", "text": json.dumps(_jsonable(result))}]}


def main() -> None:
    for line in sys.stdin:
        if not line.strip():
            continue
        req: dict[str, Any] = {}
        try:
            req = json.loads(line)
            req_id = req.get("id")
            method = req.get("method")
            if method == "initialize":
                _send_response(req_id, _initialize())
            elif method == "notifications/initialized":
                continue
            elif method == "tools/list":
                _send_response(req_id, _tools_list())
            elif method == "tools/call":
                _send_response(req_id, _tools_call(req.get("params") or {}))
            else:
                _send_response(
                    req_id,
                    error={"code": -32601, "message": f"Method not found: {method}"},
                )
        except json.JSONDecodeError as exc:
            _send_response(None, error={"code": -32700, "message": f"Parse error: {exc}"})
        except ToolError as exc:
            _send_response(
                req.get("id"),
                error={
                    "code": -32010,
                    "message": str(exc),
                    "data": {"error_code": exc.code, **exc.details},
                },
            )
        except Exception as exc:  # pragma: no cover - protocol safety net
            data = {"error_code": "INTERNAL_ERROR", "type": type(exc).__name__}
            if os.environ.get("SCIVIZ_MCP_DEBUG") == "1":
                data["traceback"] = traceback.format_exc()
            _send_response(
                req.get("id"),
                error={"code": -32000, "message": str(exc), "data": data},
            )


if __name__ == "__main__":
    main()
