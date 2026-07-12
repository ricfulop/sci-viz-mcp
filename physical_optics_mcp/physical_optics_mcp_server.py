#!/usr/bin/env python3
"""Deterministic scalar, Gaussian-beamlet, and polarization optics MCP server.

Scalar propagation is performed with the repository-pinned Prysm revision.
Gaussian-beamlet ABCD propagation and Fresnel/Jones calculations use the
repository-pinned Poke revision.  Zemax and CODE V adapters are detected and
reported, but are never required for the native tools in this server.
"""

from __future__ import annotations

import contextlib
import csv
import hashlib
import importlib.metadata
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
from poke import beamlets as poke_beamlets
from poke import polarization as poke_polarization
from poke.poke_core import Rayfront
from prysm import otf as prysm_otf
from prysm import polynomials as prysm_polynomials
from prysm.propagation import Wavefront

from attribution import ATTRIBUTION_TEXT, add_figure_attribution
from styles import OKABE_ITO, apply_aps_style, aps_double

try:
    from preview.notify import notify_preview
except Exception:  # pragma: no cover - optional dashboard
    def notify_preview(*args, **kwargs):
        return None


SERVER_VERSION = "1.0.0"
MODEL_SCHEMA = "sciviz.physical_optics/v1"
OUTPUT_DIR = Path(
    os.environ.get(
        "PHYSICAL_OPTICS_OUTPUT_DIR",
        str(_ROOT / "output" / "physical_optics"),
    )
).expanduser()
MODELS_DIR = OUTPUT_DIR / "models"
ARTIFACTS_DIR = OUTPUT_DIR / "artifacts"
RENDERS_DIR = OUTPUT_DIR / "renders"

_models: dict[str, dict[str, Any]] = {}


class ToolError(Exception):
    """Error carrying a stable machine-readable code and details."""

    def __init__(self, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


def _package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def _slug(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return value or "model"


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
        ensure_ascii=True,
        allow_nan=False,
    )


def _digest(*values: Any, length: int = 16) -> str:
    h = hashlib.sha256()
    for value in values:
        h.update(_canonical_json(value).encode("utf-8"))
        h.update(b"\0")
    return h.hexdigest()[:length]


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(_jsonable(value), indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def _require_number(
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
        raise ToolError(
            "VALIDATION_ERROR",
            f"{name} must be >= {minimum}.",
            {"field": name, "minimum": minimum},
        )
    if maximum is not None and value > maximum:
        raise ToolError(
            "VALIDATION_ERROR",
            f"{name} must be <= {maximum}.",
            {"field": name, "maximum": maximum},
        )
    return value


def _require_int(
    value: Any,
    name: str,
    *,
    minimum: int = 1,
    maximum: int | None = None,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ToolError("VALIDATION_ERROR", f"{name} must be an integer.", {"field": name})
    if value < minimum or (maximum is not None and value > maximum):
        raise ToolError(
            "VALIDATION_ERROR",
            f"{name} must be in [{minimum}, {maximum or 'unbounded'}].",
            {"field": name, "minimum": minimum, "maximum": maximum},
        )
    return value


def _default_model(name: str) -> dict[str, Any]:
    return {
        "schema": MODEL_SCHEMA,
        "name": name,
        "units": {
            "pupil_length": "mm",
            "wavelength": "nm",
            "wavefront_error": "nm",
            "field_angle": "deg",
            "propagation_distance": "mm",
            "psf_coordinate": "um",
            "spatial_frequency": "cycles/mm",
        },
        "pupil": {
            "shape": "circle",
            "diameter_mm": 10.0,
            "samples": 256,
            "obscuration_ratio": 0.0,
            "apodization": {"type": "uniform"},
        },
        "wavelengths": [{"value_nm": 550.0, "weight": 1.0}],
        "fields": [{"x_deg": 0.0, "y_deg": 0.0, "weight": 1.0}],
        "aberrations": [],
        "metadata": {},
    }


def _validate_model(model: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(model, dict):
        raise ToolError("INVALID_MODEL", "Model JSON must be an object.")
    if model.get("schema") != MODEL_SCHEMA:
        raise ToolError(
            "INVALID_MODEL",
            f"Expected schema '{MODEL_SCHEMA}'.",
            {"received": model.get("schema")},
        )
    pupil = model.get("pupil", {})
    if pupil.get("shape") not in {"circle", "square"}:
        raise ToolError("INVALID_MODEL", "pupil.shape must be 'circle' or 'square'.")
    _require_number(pupil.get("diameter_mm"), "pupil.diameter_mm", positive=True)
    _require_int(pupil.get("samples"), "pupil.samples", minimum=32, maximum=2048)
    _require_number(
        pupil.get("obscuration_ratio", 0.0),
        "pupil.obscuration_ratio",
        minimum=0.0,
        maximum=0.95,
    )
    if not model.get("wavelengths"):
        raise ToolError("INVALID_MODEL", "At least one wavelength is required.")
    for idx, item in enumerate(model["wavelengths"]):
        _require_number(item.get("value_nm"), f"wavelengths[{idx}].value_nm", positive=True)
        _require_number(item.get("weight", 1.0), f"wavelengths[{idx}].weight", minimum=0.0)
    if not model.get("fields"):
        raise ToolError("INVALID_MODEL", "At least one field is required.")
    for idx, item in enumerate(model["fields"]):
        _require_number(item.get("x_deg", 0.0), f"fields[{idx}].x_deg")
        _require_number(item.get("y_deg", 0.0), f"fields[{idx}].y_deg")
        _require_number(item.get("weight", 1.0), f"fields[{idx}].weight", minimum=0.0)
    for idx, term in enumerate(model.get("aberrations", [])):
        n = _require_int(term.get("n"), f"aberrations[{idx}].n", minimum=0, maximum=50)
        m = term.get("m")
        if isinstance(m, bool) or not isinstance(m, int) or abs(m) > n or (n - abs(m)) % 2:
            raise ToolError(
                "INVALID_MODEL",
                f"aberrations[{idx}] has invalid Zernike (n,m)=({n},{m}).",
            )
        _require_number(
            term.get("coefficient_nm"),
            f"aberrations[{idx}].coefficient_nm",
        )
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
    raise ToolError(
        "MODEL_NOT_FOUND",
        f"Unknown model_id '{model_id}'.",
        {"model_id": model_id},
    )


def _artifact_path(model_id: str, kind: str, ext: str, args: dict) -> Path:
    model = _get(model_id)
    token = _digest(model, kind, args)
    path = ARTIFACTS_DIR / _slug(model_id) / f"{kind}-{token}.{ext}"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _render_path(model_id: str, kind: str, args: dict) -> Path:
    model = _get(model_id)
    token = _digest(model, kind, args)
    path = RENDERS_DIR / _slug(model_id) / f"{kind}-{token}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _model_summary(model_id: str, model: dict[str, Any]) -> dict[str, Any]:
    return {
        "model_id": model_id,
        "name": model["name"],
        "path": str(_model_path(model_id)),
        "pupil": model["pupil"],
        "wavelength_count": len(model["wavelengths"]),
        "field_count": len(model["fields"]),
        "aberration_count": len(model.get("aberrations", [])),
        "model_digest": _digest(model, length=32),
    }


def _select_wave_field(
    model: dict[str, Any], wavelength_index: int, field_index: int
) -> tuple[float, dict[str, Any]]:
    if not 0 <= wavelength_index < len(model["wavelengths"]):
        raise ToolError(
            "INDEX_ERROR",
            f"wavelength_index {wavelength_index} is out of range.",
        )
    if not 0 <= field_index < len(model["fields"]):
        raise ToolError("INDEX_ERROR", f"field_index {field_index} is out of range.")
    return float(model["wavelengths"][wavelength_index]["value_nm"]), model["fields"][field_index]


def _make_wavefront(
    model: dict[str, Any],
    wavelength_index: int = 0,
    field_index: int = 0,
    *,
    include_aberrations: bool = True,
) -> tuple[Wavefront, dict[str, np.ndarray | float]]:
    wavelength_nm, field = _select_wave_field(model, wavelength_index, field_index)
    pupil = model["pupil"]
    samples = int(pupil["samples"])
    diameter_mm = float(pupil["diameter_mm"])
    dx_mm = diameter_mm / samples
    coords = (np.arange(samples) - samples / 2 + 0.5) * dx_mm
    x_mm, y_mm = np.meshgrid(coords, coords)
    radius_mm = diameter_mm / 2
    rho = np.hypot(x_mm, y_mm) / radius_mm
    theta = np.arctan2(y_mm, x_mm)
    if pupil["shape"] == "circle":
        amplitude = (rho <= 1).astype(float)
        obscuration = float(pupil.get("obscuration_ratio", 0.0))
        if obscuration:
            amplitude *= rho >= obscuration
    else:
        amplitude = np.ones_like(rho)
    apodization = pupil.get("apodization", {"type": "uniform"})
    apod_type = apodization.get("type", "uniform")
    if apod_type == "gaussian":
        edge_amplitude = _require_number(
            apodization.get("edge_amplitude", 0.1),
            "pupil.apodization.edge_amplitude",
            positive=True,
            maximum=1.0,
        )
        amplitude *= np.exp(math.log(edge_amplitude) * rho**2)
    elif apod_type != "uniform":
        raise ToolError(
            "UNSUPPORTED_APODIZATION",
            f"Unsupported apodization '{apod_type}'.",
            {"supported": ["uniform", "gaussian"]},
        )

    phase_nm = np.zeros_like(rho)
    if include_aberrations:
        for term in model.get("aberrations", []):
            z = prysm_polynomials.zernike_nm(
                int(term["n"]),
                int(term["m"]),
                rho,
                theta,
                norm=True,
            )
            phase_nm += float(term["coefficient_nm"]) * np.asarray(z)

    # A field angle is represented as the corresponding pupil-plane OPD tilt.
    phase_nm += (
        x_mm * math.tan(math.radians(float(field.get("x_deg", 0.0))))
        + y_mm * math.tan(math.radians(float(field.get("y_deg", 0.0))))
    ) * 1e6
    phase_nm *= amplitude != 0
    wf = Wavefront.from_amp_and_phase(
        amplitude=amplitude,
        phase=phase_nm,
        wavelength=wavelength_nm / 1000.0,
        dx=dx_mm,
    )
    return wf, {
        "x_mm": x_mm,
        "y_mm": y_mm,
        "rho": rho,
        "amplitude": amplitude,
        "phase_nm": phase_nm,
        "wavelength_nm": wavelength_nm,
        "dx_mm": dx_mm,
    }


def _wavefront_metrics(amplitude: np.ndarray, phase_nm: np.ndarray) -> dict[str, float]:
    mask = amplitude > 0
    if not np.any(mask):
        raise ToolError("EMPTY_PUPIL", "Pupil transmission is zero everywhere.")
    phase = phase_nm[mask]
    phase_centered = phase - np.mean(phase)
    return {
        "transmitting_samples": int(mask.sum()),
        "transmission_fraction": float(mask.mean()),
        "piston_nm": float(np.mean(phase)),
        "rms_wavefront_error_nm": float(np.sqrt(np.mean(phase_centered**2))),
        "peak_to_valley_nm": float(np.max(phase) - np.min(phase)),
    }


def _complex_to_pairs(values: np.ndarray) -> list[dict[str, float]]:
    values = np.asarray(values).ravel()
    return [{"real": float(v.real), "imag": float(v.imag)} for v in values]


def _complex_value(value: Any, field_name: str) -> complex:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return complex(float(value), 0.0)
    if isinstance(value, dict) and set(value).issubset({"real", "imag"}):
        return complex(float(value.get("real", 0.0)), float(value.get("imag", 0.0)))
    raise ToolError(
        "VALIDATION_ERROR",
        f"{field_name} must be a number or {{real, imag}}.",
        {"field": field_name},
    )


def _save_npz(path: Path, **arrays: Any) -> str:
    np.savez_compressed(path, **arrays)
    return str(path)


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _array_sha256(*arrays: np.ndarray) -> str:
    h = hashlib.sha256()
    for arr in arrays:
        contiguous = np.ascontiguousarray(arr)
        h.update(str(contiguous.dtype).encode())
        h.update(str(contiguous.shape).encode())
        h.update(contiguous.tobytes())
    return h.hexdigest()


def handle_health(args: dict) -> dict:
    del args
    zemax_python = False
    zemax_reason = "Zemax OpticStudio with ZOS-API is not detected."
    codev_python = False
    codev_reason = "CODE V with its Python/COM automation interface is not detected."
    if sys.platform == "win32":
        try:
            import win32com.client  # type: ignore  # noqa: F401

            zemax_python = True
            codev_python = True
            zemax_reason = (
                "COM bindings are present; a licensed running OpticStudio installation "
                "is still required and is not exercised by native tools."
            )
            codev_reason = (
                "COM bindings are present; a licensed CODE V installation is still "
                "required and is not exercised by native tools."
            )
        except Exception:
            pass
    return {
        "ok": True,
        "server": "physical_optics_mcp",
        "version": SERVER_VERSION,
        "model_schema": MODEL_SCHEMA,
        "engines": {
            "prysm": {
                "available": True,
                "version": _package_version("prysm"),
                "capabilities": [
                    "scalar wavefronts",
                    "FFT focus",
                    "angular-spectrum propagation",
                    "PSF",
                    "OTF/MTF",
                ],
            },
            "poke": {
                "available": True,
                "version": _package_version("poke"),
                "capabilities": [
                    "Gaussian beamlet initialization",
                    "ABCD complex-curvature propagation",
                    "Fresnel/Jones polarization",
                ],
            },
        },
        "licensed_adapters": {
            "zemax_zos_api": {
                "available": zemax_python,
                "optional": True,
                "reason": zemax_reason,
            },
            "code_v": {
                "available": codev_python,
                "optional": True,
                "reason": codev_reason,
            },
        },
        "output_dir": str(OUTPUT_DIR),
        "determinism": {
            "artifact_names": "SHA-256 of model and normalized operation inputs",
            "stochastic_operations": "none",
        },
    }


_REFERENCE = {
    "units": (
        "Pupil dimensions, effective focal lengths, and propagation distances are mm. "
        "Wavelengths and wavefront coefficients are nm. PSF coordinates are um. "
        "MTF frequencies are cycles/mm. Gaussian-beamlet internal calculations are SI."
    ),
    "aberrations": (
        "Aberrations are normalized Prysm Zernike terms specified by radial order n, "
        "azimuthal order m, and coefficient_nm. Valid terms require |m|<=n and "
        "(n-|m|) even. Coefficients multiply Prysm's orthonormal basis."
    ),
    "methods": (
        "Scalar focus and free-space propagation use Prysm Wavefront.focus and "
        "Wavefront.free_space. MTF uses prysm.otf.mtf_from_psf. The pinned Prysm "
        "revision has no encircled-energy helper, so energy is integrated directly "
        "from the Prysm-generated, normalized PSF. Gaussian beamlets use Poke "
        "Rayfront initialization and prop_complex_curvature with explicit ABCD "
        "elements. Jones calculations use Poke Fresnel coefficients and Mueller "
        "conversion."
    ),
    "limitations": (
        "The native Jones tool is a sequence of planar Fresnel interfaces with "
        "optional Jones-basis rotations; arbitrary 3D coated-surface PRT requires "
        "ray data from Poke's optional Zemax or CODE V adapters. Those commercial "
        "applications are never required and health reports them unavailable unless "
        "their Windows COM bindings are detected. Gaussian beamlet decomposition in "
        "Poke is upstream-labeled experimental; this server exposes a deterministic "
        "first-order ABCD subset rather than pretending to provide a licensed "
        "sequential ray-trace backend."
    ),
}


def handle_reference(args: dict) -> dict:
    topic = args.get("topic", "methods")
    if topic not in _REFERENCE:
        raise ToolError(
            "REFERENCE_NOT_FOUND",
            f"Unknown reference topic '{topic}'.",
            {"topics": sorted(_REFERENCE)},
        )
    return {"topic": topic, "content": _REFERENCE[topic]}


def handle_new_model(args: dict) -> dict:
    name = str(args.get("name", "physical-optics-model"))
    model = _default_model(name)
    if args.get("metadata") is not None:
        if not isinstance(args["metadata"], dict):
            raise ToolError("VALIDATION_ERROR", "metadata must be an object.")
        model["metadata"] = args["metadata"]
    requested = args.get("model_id")
    model_id = _slug(str(requested or name))
    if model_id in _models or _model_path(model_id).exists():
        model_id = f"{model_id}-{_digest(name, model, len(_models), length=8)}"
    _models[model_id] = model
    path = _persist(model_id)
    return {**_model_summary(model_id, model), "path": path}


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
        fallback_id = str(model.get("name", "loaded-model"))
    model = _validate_model(model)
    model_id = _slug(str(args.get("model_id") or fallback_id))
    _models[model_id] = model
    path = _persist(model_id)
    return {**_model_summary(model_id, model), "path": path}


def handle_save_model(args: dict) -> dict:
    model_id = args["model_id"]
    model = _get(model_id)
    if args.get("file_path"):
        path = Path(args["file_path"]).expanduser().resolve()
        if path.suffix.lower() != ".json":
            raise ToolError("VALIDATION_ERROR", "Model file_path must end in .json.")
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
            records[path.stem] = _model_summary(path.stem, model)
        except Exception as exc:
            records[path.stem] = {
                "model_id": path.stem,
                "path": str(path),
                "error": str(exc),
            }
    for model_id, model in _models.items():
        records[model_id] = _model_summary(model_id, model)
    return {"models": list(records.values()), "count": len(records)}


def handle_get_model(args: dict) -> dict:
    model = _get(args["model_id"])
    return {
        "model_id": args["model_id"],
        "model": model,
        "model_digest": _digest(model, length=32),
    }


def handle_define_pupil(args: dict) -> dict:
    model_id = args["model_id"]
    model = _get(model_id)
    shape = args.get("shape", "circle")
    if shape not in {"circle", "square"}:
        raise ToolError("VALIDATION_ERROR", "shape must be 'circle' or 'square'.")
    apodization = args.get("apodization", {"type": "uniform"})
    if not isinstance(apodization, dict):
        raise ToolError("VALIDATION_ERROR", "apodization must be an object.")
    model["pupil"] = {
        "shape": shape,
        "diameter_mm": _require_number(
            args["diameter_mm"], "diameter_mm", positive=True
        ),
        "samples": _require_int(
            args.get("samples", 256), "samples", minimum=32, maximum=2048
        ),
        "obscuration_ratio": _require_number(
            args.get("obscuration_ratio", 0.0),
            "obscuration_ratio",
            minimum=0.0,
            maximum=0.95,
        ),
        "apodization": apodization,
    }
    _validate_model(model)
    _persist(model_id)
    return {"model_id": model_id, "pupil": model["pupil"]}


def handle_define_wavelengths_fields(args: dict) -> dict:
    model_id = args["model_id"]
    model = _get(model_id)
    if "wavelengths" in args:
        wavelengths = args["wavelengths"]
        if not isinstance(wavelengths, list) or not wavelengths:
            raise ToolError("VALIDATION_ERROR", "wavelengths must be a non-empty array.")
        model["wavelengths"] = [
            {
                "value_nm": _require_number(
                    item["value_nm"], f"wavelengths[{idx}].value_nm", positive=True
                ),
                "weight": _require_number(
                    item.get("weight", 1.0),
                    f"wavelengths[{idx}].weight",
                    minimum=0.0,
                ),
            }
            for idx, item in enumerate(wavelengths)
        ]
    if "fields" in args:
        fields = args["fields"]
        if not isinstance(fields, list) or not fields:
            raise ToolError("VALIDATION_ERROR", "fields must be a non-empty array.")
        model["fields"] = [
            {
                "x_deg": _require_number(
                    item.get("x_deg", 0.0), f"fields[{idx}].x_deg"
                ),
                "y_deg": _require_number(
                    item.get("y_deg", 0.0), f"fields[{idx}].y_deg"
                ),
                "weight": _require_number(
                    item.get("weight", 1.0), f"fields[{idx}].weight", minimum=0.0
                ),
            }
            for idx, item in enumerate(fields)
        ]
    _validate_model(model)
    _persist(model_id)
    return {
        "model_id": model_id,
        "wavelengths": model["wavelengths"],
        "fields": model["fields"],
    }


def handle_set_aberrations(args: dict) -> dict:
    model_id = args["model_id"]
    model = _get(model_id)
    terms = args.get("terms", [])
    if not isinstance(terms, list):
        raise ToolError("VALIDATION_ERROR", "terms must be an array.")
    normalized = []
    for idx, term in enumerate(terms):
        n = _require_int(term.get("n"), f"terms[{idx}].n", minimum=0, maximum=50)
        m = term.get("m")
        if isinstance(m, bool) or not isinstance(m, int) or abs(m) > n or (n - abs(m)) % 2:
            raise ToolError(
                "VALIDATION_ERROR",
                f"Invalid Zernike (n,m)=({n},{m}) at terms[{idx}].",
            )
        normalized.append(
            {
                "n": n,
                "m": m,
                "coefficient_nm": _require_number(
                    term.get("coefficient_nm"), f"terms[{idx}].coefficient_nm"
                ),
            }
        )
    model["aberrations"] = normalized
    _persist(model_id)
    return {"model_id": model_id, "aberrations": normalized}


def handle_wavefront(args: dict) -> dict:
    model_id = args["model_id"]
    model = _get(model_id)
    wavelength_index = int(args.get("wavelength_index", 0))
    field_index = int(args.get("field_index", 0))
    wf, data = _make_wavefront(model, wavelength_index, field_index)
    op_args = {"wavelength_index": wavelength_index, "field_index": field_index}
    path = _artifact_path(model_id, "wavefront", "npz", op_args)
    _save_npz(
        path,
        field=wf.data,
        amplitude=data["amplitude"],
        phase_nm=data["phase_nm"],
        x_mm=data["x_mm"],
        y_mm=data["y_mm"],
        wavelength_nm=np.array(data["wavelength_nm"]),
        dx_mm=np.array(data["dx_mm"]),
    )
    metrics = _wavefront_metrics(data["amplitude"], data["phase_nm"])
    return {
        "model_id": model_id,
        "artifact_path": str(path),
        "numeric_sha256": _array_sha256(wf.data, data["phase_nm"]),
        "shape": list(wf.data.shape),
        "wavelength_nm": data["wavelength_nm"],
        "sample_spacing_mm": data["dx_mm"],
        "metrics": metrics,
        "engine": "prysm.Wavefront.from_amp_and_phase",
    }


def handle_propagate(args: dict) -> dict:
    model_id = args["model_id"]
    model = _get(model_id)
    wavelength_index = int(args.get("wavelength_index", 0))
    field_index = int(args.get("field_index", 0))
    method = args.get("method", "focus")
    wf, source = _make_wavefront(model, wavelength_index, field_index)
    if method == "focus":
        efl_mm = _require_number(args.get("effective_focal_length_mm"), "effective_focal_length_mm", positive=True)
        q = _require_number(args.get("oversampling", 2.0), "oversampling", minimum=1.0, maximum=8.0)
        result = wf.focus(efl=efl_mm, Q=q)
        coordinate_unit = "um"
        operation = {"effective_focal_length_mm": efl_mm, "oversampling": q}
        engine = "prysm.Wavefront.focus"
    elif method == "angular_spectrum":
        distance_mm = _require_number(args.get("distance_mm"), "distance_mm")
        q = _require_number(args.get("oversampling", 1.0), "oversampling", minimum=1.0, maximum=4.0)
        result = wf.free_space(dz=distance_mm, Q=q)
        coordinate_unit = "mm"
        operation = {"distance_mm": distance_mm, "oversampling": q}
        engine = "prysm.Wavefront.free_space"
    else:
        raise ToolError(
            "UNSUPPORTED_METHOD",
            f"Unknown propagation method '{method}'.",
            {"supported": ["focus", "angular_spectrum"]},
        )
    intensity = np.asarray(result.intensity.data)
    op_args = {
        "method": method,
        "wavelength_index": wavelength_index,
        "field_index": field_index,
        **operation,
    }
    path = _artifact_path(model_id, f"propagation-{method}", "npz", op_args)
    _save_npz(
        path,
        field=result.data,
        intensity=intensity,
        sample_spacing=np.array(result.dx),
        wavelength_nm=np.array(source["wavelength_nm"]),
        coordinate_unit=np.array(coordinate_unit),
    )
    return {
        "model_id": model_id,
        "method": method,
        "engine": engine,
        "artifact_path": str(path),
        "numeric_sha256": _array_sha256(result.data, intensity),
        "shape": list(result.data.shape),
        "sample_spacing": float(result.dx),
        "sample_spacing_unit": coordinate_unit,
        "peak_intensity": float(np.max(intensity)),
        "total_sampled_intensity": float(np.sum(intensity)),
        **operation,
    }


def _calculate_psf(
    model_id: str,
    effective_focal_length_mm: float,
    wavelength_index: int,
    field_index: int,
    oversampling: float,
) -> tuple[np.ndarray, float, dict, Path]:
    model = _get(model_id)
    wf, source = _make_wavefront(model, wavelength_index, field_index)
    focused = wf.focus(efl=effective_focal_length_mm, Q=oversampling)
    raw = np.asarray(focused.intensity.data, dtype=float)
    total = float(raw.sum())
    if not math.isfinite(total) or total <= 0:
        raise ToolError("NUMERICAL_ERROR", "PSF has non-positive total intensity.")
    psf = raw / total
    ideal_wf, _ = _make_wavefront(
        model,
        wavelength_index,
        field_index,
        include_aberrations=False,
    )
    ideal_raw = np.asarray(
        ideal_wf.focus(efl=effective_focal_length_mm, Q=oversampling).intensity.data,
        dtype=float,
    )
    ideal_psf = ideal_raw / ideal_raw.sum()
    args = {
        "effective_focal_length_mm": effective_focal_length_mm,
        "wavelength_index": wavelength_index,
        "field_index": field_index,
        "oversampling": oversampling,
    }
    path = _artifact_path(model_id, "psf", "npz", args)
    coords_um = (
        np.arange(psf.shape[0]) - psf.shape[0] / 2 + 0.5
    ) * float(focused.dx)
    _save_npz(
        path,
        psf=psf,
        ideal_psf=ideal_psf,
        coords_um=coords_um,
        sample_spacing_um=np.array(focused.dx),
        wavelength_nm=np.array(source["wavelength_nm"]),
        effective_focal_length_mm=np.array(effective_focal_length_mm),
    )
    meta = {
        "wavelength_nm": float(source["wavelength_nm"]),
        "sample_spacing_um": float(focused.dx),
        "strehl_ratio": float(psf.max() / ideal_psf.max()),
        "peak_normalized_intensity": float(psf.max()),
        "normalization": "sum(psf)=1",
    }
    return psf, float(focused.dx), meta, path


def handle_psf(args: dict) -> dict:
    model_id = args["model_id"]
    efl = _require_number(
        args.get("effective_focal_length_mm"),
        "effective_focal_length_mm",
        positive=True,
    )
    wavelength_index = int(args.get("wavelength_index", 0))
    field_index = int(args.get("field_index", 0))
    oversampling = _require_number(
        args.get("oversampling", 2.0),
        "oversampling",
        minimum=1.0,
        maximum=8.0,
    )
    psf, dx_um, meta, path = _calculate_psf(
        model_id, efl, wavelength_index, field_index, oversampling
    )
    return {
        "model_id": model_id,
        "artifact_path": str(path),
        "numeric_sha256": _array_sha256(psf),
        "shape": list(psf.shape),
        "coordinate_unit": "um",
        "engine": "prysm.Wavefront.focus",
        **meta,
    }


def _calculate_mtf(
    model_id: str,
    effective_focal_length_mm: float,
    wavelength_index: int,
    field_index: int,
    oversampling: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict, Path]:
    psf, dx_um, psf_meta, _ = _calculate_psf(
        model_id, effective_focal_length_mm, wavelength_index, field_index, oversampling
    )
    mtf_data = prysm_otf.mtf_from_psf(psf, dx=dx_um)
    mtf2d = np.asarray(mtf_data.data)
    center = mtf2d.shape[0] // 2
    frequency = np.arange(mtf2d.shape[0] - center) * float(mtf_data.dx)
    tangential = mtf2d[center:, center]
    sagittal = mtf2d[center, center:]
    args = {
        "effective_focal_length_mm": effective_focal_length_mm,
        "wavelength_index": wavelength_index,
        "field_index": field_index,
        "oversampling": oversampling,
    }
    path = _artifact_path(model_id, "mtf", "csv", args)
    with path.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["frequency_cycles_per_mm", "tangential", "sagittal"])
        writer.writerows(zip(frequency, tangential, sagittal, strict=False))
    return frequency, tangential, sagittal, psf_meta, path


def handle_mtf(args: dict) -> dict:
    model_id = args["model_id"]
    efl = _require_number(
        args.get("effective_focal_length_mm"),
        "effective_focal_length_mm",
        positive=True,
    )
    wavelength_index = int(args.get("wavelength_index", 0))
    field_index = int(args.get("field_index", 0))
    oversampling = _require_number(
        args.get("oversampling", 2.0), "oversampling", minimum=1.0, maximum=8.0
    )
    frequency, tangential, sagittal, psf_meta, path = _calculate_mtf(
        model_id, efl, wavelength_index, field_index, oversampling
    )
    requested = args.get("frequencies_cycles_per_mm")
    sampled = None
    if requested is not None:
        sampled = [
            {
                "frequency_cycles_per_mm": float(freq),
                "tangential": float(np.interp(freq, frequency, tangential)),
                "sagittal": float(np.interp(freq, frequency, sagittal)),
            }
            for freq in requested
        ]
    return {
        "model_id": model_id,
        "artifact_path": str(path),
        "numeric_sha256": _array_sha256(frequency, tangential, sagittal),
        "frequency_unit": "cycles/mm",
        "sample_count": int(len(frequency)),
        "sampled": sampled,
        "dc_mtf": {
            "tangential": float(tangential[0]),
            "sagittal": float(sagittal[0]),
        },
        "engine": "prysm.otf.mtf_from_psf",
        "psf": psf_meta,
    }


def _calculate_encircled_energy(
    model_id: str,
    effective_focal_length_mm: float,
    wavelength_index: int,
    field_index: int,
    oversampling: float,
    radii_um: list[float] | None,
) -> tuple[np.ndarray, np.ndarray, dict, Path]:
    psf, dx_um, psf_meta, _ = _calculate_psf(
        model_id, effective_focal_length_mm, wavelength_index, field_index, oversampling
    )
    n = psf.shape[0]
    coords = (np.arange(n) - n / 2 + 0.5) * dx_um
    x, y = np.meshgrid(coords, coords)
    radius = np.hypot(x, y).ravel()
    order = np.argsort(radius, kind="mergesort")
    radius_sorted = radius[order]
    energy_sorted = np.cumsum(psf.ravel()[order])
    energy_sorted /= energy_sorted[-1]
    if radii_um is None:
        radii = np.linspace(0, float(radius_sorted[-1]), 256)
    else:
        radii = np.asarray(
            [
                _require_number(value, f"radii_um[{idx}]", minimum=0.0)
                for idx, value in enumerate(radii_um)
            ],
            dtype=float,
        )
    energy = np.interp(radii, radius_sorted, energy_sorted, left=0.0, right=1.0)
    quantiles = {}
    for fraction in (0.5, 0.8, 0.8377850436212378, 0.9):
        quantiles[f"radius_at_{fraction:.6f}_energy_um"] = float(
            np.interp(fraction, energy_sorted, radius_sorted)
        )
    args = {
        "effective_focal_length_mm": effective_focal_length_mm,
        "wavelength_index": wavelength_index,
        "field_index": field_index,
        "oversampling": oversampling,
        "radii_um": None if radii_um is None else list(radii_um),
    }
    path = _artifact_path(model_id, "encircled-energy", "csv", args)
    with path.open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["radius_um", "encircled_energy_fraction"])
        writer.writerows(zip(radii, energy, strict=False))
    meta = {
        **psf_meta,
        **quantiles,
        "integration": (
            "Deterministic radial cumulative sum of the normalized Prysm PSF; "
            "the pinned Prysm revision has no encircled-energy helper."
        ),
    }
    return radii, energy, meta, path


def handle_encircled_energy(args: dict) -> dict:
    model_id = args["model_id"]
    efl = _require_number(
        args.get("effective_focal_length_mm"),
        "effective_focal_length_mm",
        positive=True,
    )
    wavelength_index = int(args.get("wavelength_index", 0))
    field_index = int(args.get("field_index", 0))
    oversampling = _require_number(
        args.get("oversampling", 2.0), "oversampling", minimum=1.0, maximum=8.0
    )
    radii, energy, meta, path = _calculate_encircled_energy(
        model_id,
        efl,
        wavelength_index,
        field_index,
        oversampling,
        args.get("radii_um"),
    )
    return {
        "model_id": model_id,
        "artifact_path": str(path),
        "numeric_sha256": _array_sha256(radii, energy),
        "radius_unit": "um",
        "energy_unit": "fraction",
        "samples": [
            {"radius_um": float(r), "encircled_energy": float(e)}
            for r, e in zip(radii, energy, strict=False)
        ],
        **meta,
    }


def _abcd_element(kind: str, value_m: float) -> tuple[np.ndarray, ...]:
    identity = np.eye(2)
    zero = np.zeros((2, 2))
    if kind == "free_space":
        return identity, value_m * identity, zero, identity
    if kind == "thin_lens":
        return identity, zero, -identity / value_m, identity
    raise ToolError(
        "UNSUPPORTED_ELEMENT",
        f"Unsupported beamlet element '{kind}'.",
        {"supported": ["free_space", "thin_lens"]},
    )


def handle_gaussian_beamlets(args: dict) -> dict:
    model_id = args["model_id"]
    model = _get(model_id)
    wavelength_index = int(args.get("wavelength_index", 0))
    wavelength_nm, field = _select_wave_field(model, wavelength_index, 0)
    wavelength_m = wavelength_nm * 1e-9
    pupil_radius_m = _require_number(
        args.get("pupil_radius_mm", model["pupil"]["diameter_mm"] / 2),
        "pupil_radius_mm",
        positive=True,
    ) * 1e-3
    waist_m = _require_number(args.get("waist_mm"), "waist_mm", positive=True) * 1e-3
    nrays = _require_int(args.get("nrays_across", 9), "nrays_across", minimum=3, maximum=41)
    max_fov_deg = _require_number(
        args.get("max_fov_deg", 1.0), "max_fov_deg", positive=True
    )
    fov_deg = args.get(
        "field_deg",
        [float(field.get("x_deg", 0.0)), float(field.get("y_deg", 0.0))],
    )
    if len(fov_deg) != 2:
        raise ToolError("VALIDATION_ERROR", "field_deg must contain [x_deg, y_deg].")
    elements = args.get("elements", [{"type": "free_space", "distance_mm": 100.0}])
    if not isinstance(elements, list) or not elements:
        raise ToolError("VALIDATION_ERROR", "elements must be a non-empty array.")

    # Poke currently prints constructor diagnostics to stdout; capture them so
    # they cannot corrupt MCP JSON-RPC.
    with contextlib.redirect_stdout(io.StringIO()):
        rayfront = Rayfront(
            nrays,
            wavelength_m,
            pupil_radius_m,
            max_fov_deg,
            fov=list(fov_deg),
            circle=True,
        )
        rayfront.as_gaussianbeamlets(waist_m)

    centers = np.asarray(rayfront.base_rays[:2]).T * pupil_radius_m
    slopes = np.tile(
        np.tan(np.radians(np.asarray(fov_deg, dtype=float))),
        (centers.shape[0], 1),
    )
    z_rayleigh = math.pi * waist_m**2 / wavelength_m
    qinv = np.eye(2, dtype=complex) / (1j * z_rayleigh)
    total_abcd = np.eye(4)
    normalized_elements = []
    for idx, element in enumerate(elements):
        kind = element.get("type")
        if kind == "free_space":
            value_m = _require_number(
                element.get("distance_mm"),
                f"elements[{idx}].distance_mm",
            ) * 1e-3
            normalized_elements.append({"type": kind, "distance_mm": value_m * 1e3})
        elif kind == "thin_lens":
            value_m = _require_number(
                element.get("focal_length_mm"),
                f"elements[{idx}].focal_length_mm",
            ) * 1e-3
            if value_m == 0:
                raise ToolError("VALIDATION_ERROR", "Thin-lens focal length cannot be zero.")
            normalized_elements.append({"type": kind, "focal_length_mm": value_m * 1e3})
        else:
            raise ToolError("UNSUPPORTED_ELEMENT", f"Unsupported element '{kind}'.")
        A, B, C, D = _abcd_element(kind, value_m)
        qinv = poke_beamlets.prop_complex_curvature(qinv, A, B, C, D)
        matrix = np.block([[A, B], [C, D]])
        total_abcd = matrix @ total_abcd
        state = np.column_stack((centers[:, 0], centers[:, 1], slopes[:, 0], slopes[:, 1]))
        state = (matrix @ state.T).T
        centers = state[:, :2]
        slopes = state[:, 2:]

    q = np.linalg.inv(np.asarray(qinv))
    widths_m = np.sqrt(
        wavelength_m * np.abs(np.diag(q)) ** 2 / (math.pi * np.imag(np.diag(q)))
    )
    curvature_m = []
    for value in np.real(np.diag(qinv)):
        curvature_m.append(float("inf") if abs(value) < 1e-15 else float(1 / value))

    grid_samples = _require_int(
        args.get("grid_samples", 128), "grid_samples", minimum=32, maximum=512
    )
    extent_mm = _require_number(
        args.get("detector_extent_mm", max(6 * float(np.max(widths_m)) * 1e3, 1.0)),
        "detector_extent_mm",
        positive=True,
    )
    coord_m = np.linspace(-extent_mm / 2, extent_mm / 2, grid_samples) * 1e-3
    x_m, y_m = np.meshgrid(coord_m, coord_m)
    field_out = np.zeros_like(x_m, dtype=complex)
    k = 2 * math.pi / wavelength_m
    qx_inv, qy_inv = qinv[0, 0], qinv[1, 1]
    for center in centers:
        dx = x_m - center[0]
        dy = y_m - center[1]
        field_out += np.exp(-1j * k * (qx_inv * dx**2 + qy_inv * dy**2) / 2)
    field_out /= max(len(centers), 1)
    intensity = np.abs(field_out) ** 2
    args_norm = {
        "wavelength_index": wavelength_index,
        "waist_mm": waist_m * 1e3,
        "pupil_radius_mm": pupil_radius_m * 1e3,
        "nrays_across": nrays,
        "field_deg": list(map(float, fov_deg)),
        "elements": normalized_elements,
        "grid_samples": grid_samples,
        "detector_extent_mm": extent_mm,
    }
    path = _artifact_path(model_id, "gaussian-beamlets", "npz", args_norm)
    _save_npz(
        path,
        field=field_out,
        intensity=intensity,
        coords_mm=coord_m * 1e3,
        beamlet_centers_mm=centers * 1e3,
        beamlet_slopes_rad=slopes,
        q_inverse_per_m=qinv,
        total_abcd=total_abcd,
    )
    return {
        "model_id": model_id,
        "artifact_path": str(path),
        "numeric_sha256": _array_sha256(field_out, centers, qinv),
        "engine": {
            "initialization": "poke.poke_core.Rayfront.as_gaussianbeamlets",
            "propagation": "poke.beamlets.prop_complex_curvature",
        },
        "wavelength_nm": wavelength_nm,
        "beamlet_count": int(len(centers)),
        "initial_waist_mm": waist_m * 1e3,
        "rayleigh_range_mm": z_rayleigh * 1e3,
        "output_1e2_radius_mm": {
            "x": float(widths_m[0] * 1e3),
            "y": float(widths_m[1] * 1e3),
        },
        "output_curvature_radius_mm": [
            "infinity" if math.isinf(v) else v * 1e3 for v in curvature_m
        ],
        "output_centroid_mm": {
            "x": float(np.mean(centers[:, 0]) * 1e3),
            "y": float(np.mean(centers[:, 1]) * 1e3),
        },
        "elements": normalized_elements,
        "licensed_adapter_used": False,
        "limitation": (
            "Deterministic first-order ABCD subset. Arbitrary sequential systems "
            "require optional licensed Zemax/CODE V ray data."
        ),
    }


def _rotation_jones(angle_deg: float) -> np.ndarray:
    angle = math.radians(angle_deg)
    c, s = math.cos(angle), math.sin(angle)
    return np.array([[c, s], [-s, c]], dtype=complex)


def handle_polarization_jones(args: dict) -> dict:
    interfaces = args.get("interfaces")
    if not isinstance(interfaces, list) or not interfaces:
        raise ToolError("VALIDATION_ERROR", "interfaces must be a non-empty array.")
    wavelength_nm = _require_number(
        args.get("wavelength_nm", 550.0), "wavelength_nm", positive=True
    )
    total = np.eye(2, dtype=complex)
    details = []
    for idx, interface in enumerate(interfaces):
        n1 = _complex_value(interface.get("n1"), f"interfaces[{idx}].n1")
        n2 = _complex_value(interface.get("n2"), f"interfaces[{idx}].n2")
        angle_deg = _require_number(
            interface.get("incidence_angle_deg", 0.0),
            f"interfaces[{idx}].incidence_angle_deg",
            minimum=0.0,
            maximum=89.999,
        )
        mode = interface.get("mode", "transmit")
        if mode not in {"reflect", "transmit"}:
            raise ToolError(
                "VALIDATION_ERROR",
                f"interfaces[{idx}].mode must be reflect or transmit.",
            )
        rs, rp = poke_polarization.fresnel_coefficients(
            np.asarray([math.radians(angle_deg)]),
            n1,
            n2,
            mode=mode,
        )
        coeff_s = complex(np.asarray(rs).ravel()[0])
        coeff_p = complex(np.asarray(rp).ravel()[0])
        rotation_deg = _require_number(
            interface.get("basis_rotation_deg", 0.0),
            f"interfaces[{idx}].basis_rotation_deg",
        )
        rotation = _rotation_jones(rotation_deg)
        local = np.diag([coeff_s, coeff_p])
        matrix = rotation.T @ local @ rotation
        total = matrix @ total
        details.append(
            {
                "index": idx,
                "mode": mode,
                "incidence_angle_deg": angle_deg,
                "basis_rotation_deg": rotation_deg,
                "fresnel_s": _jsonable(coeff_s),
                "fresnel_p": _jsonable(coeff_p),
                "jones_matrix": _jsonable(matrix),
            }
        )
    vector_spec = args.get(
        "input_jones",
        [{"real": 1.0, "imag": 0.0}, {"real": 0.0, "imag": 0.0}],
    )
    if not isinstance(vector_spec, list) or len(vector_spec) != 2:
        raise ToolError("VALIDATION_ERROR", "input_jones must contain two complex values.")
    input_vector = np.array(
        [_complex_value(v, f"input_jones[{idx}]") for idx, v in enumerate(vector_spec)]
    )
    output_vector = total @ input_vector
    ex, ey = output_vector
    stokes = np.array(
        [
            abs(ex) ** 2 + abs(ey) ** 2,
            abs(ex) ** 2 - abs(ey) ** 2,
            2 * np.real(ex * np.conj(ey)),
            -2 * np.imag(ex * np.conj(ey)),
        ],
        dtype=float,
    )
    mueller = poke_polarization.jones_to_mueller(total)
    return {
        "wavelength_nm": wavelength_nm,
        "interface_count": len(interfaces),
        "input_jones": _jsonable(input_vector),
        "output_jones": _jsonable(output_vector),
        "system_jones_matrix": _jsonable(total),
        "system_mueller_matrix": _jsonable(mueller),
        "output_stokes": {
            "S0": float(stokes[0]),
            "S1": float(stokes[1]),
            "S2": float(stokes[2]),
            "S3": float(stokes[3]),
        },
        "interfaces": details,
        "engine": "poke.polarization.fresnel_coefficients + jones_to_mueller",
        "licensed_adapter_used": False,
        "limitation": (
            "Planar-interface Jones sequence. Arbitrary 3D polarization ray tracing "
            "requires optional licensed Zemax/CODE V ray data."
        ),
    }


def handle_render(args: dict) -> dict:
    model_id = args["model_id"]
    model = _get(model_id)
    kind = args.get("kind", "wavefront")
    width_px = _require_int(args.get("width_px", 1400), "width_px", minimum=400, maximum=5000)
    dpi = 200
    apply_aps_style()
    render_args = dict(args)
    render_args.pop("model_id", None)
    if args.get("output_file"):
        path = Path(args["output_file"]).expanduser().resolve()
        if path.suffix.lower() != ".png":
            raise ToolError("VALIDATION_ERROR", "output_file must end in .png.")
        path.parent.mkdir(parents=True, exist_ok=True)
    else:
        path = _render_path(model_id, kind, render_args)

    if kind in {"pupil", "wavefront"}:
        _, data = _make_wavefront(
            model,
            int(args.get("wavelength_index", 0)),
            int(args.get("field_index", 0)),
        )
        image = data["amplitude"] if kind == "pupil" else data["phase_nm"]
        label = "Amplitude" if kind == "pupil" else "Wavefront error (nm)"
        fig, ax = plt.subplots(figsize=aps_double())
        extent = [
            float(np.min(data["x_mm"])),
            float(np.max(data["x_mm"])),
            float(np.min(data["y_mm"])),
            float(np.max(data["y_mm"])),
        ]
        im = ax.imshow(
            image,
            origin="lower",
            extent=extent,
            cmap="gray" if kind == "pupil" else "RdBu_r",
        )
        ax.set(xlabel="Pupil x (mm)", ylabel="Pupil y (mm)")
        fig.colorbar(im, ax=ax, label=label)
    elif kind == "psf":
        efl = _require_number(
            args.get("effective_focal_length_mm"),
            "effective_focal_length_mm",
            positive=True,
        )
        psf, dx_um, _, _ = _calculate_psf(
            model_id,
            efl,
            int(args.get("wavelength_index", 0)),
            int(args.get("field_index", 0)),
            float(args.get("oversampling", 2.0)),
        )
        coords = (np.arange(psf.shape[0]) - psf.shape[0] / 2 + 0.5) * dx_um
        fig, ax = plt.subplots(figsize=aps_double())
        im = ax.imshow(
            np.log10(np.maximum(psf, psf.max() * 1e-8)),
            origin="lower",
            extent=[coords[0], coords[-1], coords[0], coords[-1]],
            cmap="magma",
        )
        ax.set(xlabel="Image x (µm)", ylabel="Image y (µm)")
        fig.colorbar(im, ax=ax, label="log₁₀ normalized intensity")
    elif kind == "mtf":
        efl = _require_number(
            args.get("effective_focal_length_mm"),
            "effective_focal_length_mm",
            positive=True,
        )
        freq, tang, sag, _, _ = _calculate_mtf(
            model_id,
            efl,
            int(args.get("wavelength_index", 0)),
            int(args.get("field_index", 0)),
            float(args.get("oversampling", 2.0)),
        )
        fig, ax = plt.subplots(figsize=aps_double())
        ax.plot(freq, tang, color=OKABE_ITO["blue"], label="Tangential")
        ax.plot(freq, sag, "--", color=OKABE_ITO["vermillion"], label="Sagittal")
        ax.set(
            xlabel="Spatial frequency (cycles/mm)",
            ylabel="MTF",
            xlim=(0, float(args.get("max_frequency_cycles_per_mm", freq[-1]))),
            ylim=(0, 1.02),
        )
        ax.legend()
    elif kind == "encircled_energy":
        efl = _require_number(
            args.get("effective_focal_length_mm"),
            "effective_focal_length_mm",
            positive=True,
        )
        radii, energy, _, _ = _calculate_encircled_energy(
            model_id,
            efl,
            int(args.get("wavelength_index", 0)),
            int(args.get("field_index", 0)),
            float(args.get("oversampling", 2.0)),
            None,
        )
        fig, ax = plt.subplots(figsize=aps_double())
        ax.plot(radii, energy, color=OKABE_ITO["blue"])
        ax.axhline(0.8, color="0.5", linestyle=":")
        ax.set(xlabel="Radius (µm)", ylabel="Encircled energy", ylim=(0, 1.02))
    elif kind == "gaussian_beamlets":
        beamlet_result = handle_gaussian_beamlets(args)
        with np.load(beamlet_result["artifact_path"]) as archive:
            intensity = archive["intensity"]
            coords = archive["coords_mm"]
        fig, ax = plt.subplots(figsize=aps_double())
        im = ax.imshow(
            intensity,
            origin="lower",
            extent=[coords[0], coords[-1], coords[0], coords[-1]],
            cmap="magma",
        )
        ax.set(xlabel="Detector x (mm)", ylabel="Detector y (mm)")
        fig.colorbar(im, ax=ax, label="Relative intensity")
    else:
        raise ToolError(
            "UNSUPPORTED_RENDER",
            f"Unknown render kind '{kind}'.",
            {
                "supported": [
                    "pupil",
                    "wavefront",
                    "psf",
                    "mtf",
                    "encircled_energy",
                    "gaussian_beamlets",
                ]
            },
        )
    add_figure_attribution(fig)
    fig.set_size_inches(width_px / dpi, fig.get_size_inches()[1])
    fig.savefig(path, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    notify_preview(
        str(path),
        "physical_optics_render",
        render_args,
        server_name="physical_optics_mcp",
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
        if args.get("output_file"):
            path = Path(args["output_file"]).expanduser().resolve()
        else:
            path = _artifact_path(model_id, "model-export", "json", {})
        if path.suffix.lower() != ".json":
            raise ToolError("VALIDATION_ERROR", "model_json output must end in .json.")
        _atomic_json(path, model)
        return {
            "model_id": model_id,
            "export_type": export_type,
            "path": str(path),
            "file_sha256": _file_sha256(path),
        }
    source = args.get("source_artifact")
    if not source:
        raise ToolError(
            "VALIDATION_ERROR",
            "source_artifact is required for numeric_json or numeric_csv export.",
        )
    source_path = Path(source).expanduser().resolve()
    if not source_path.exists() or source_path.suffix.lower() != ".npz":
        raise ToolError("VALIDATION_ERROR", "source_artifact must be an existing .npz file.")
    array_name = args.get("array_name")
    with np.load(source_path) as archive:
        if array_name is None:
            array_name = archive.files[0]
        if array_name not in archive:
            raise ToolError(
                "ARRAY_NOT_FOUND",
                f"Array '{array_name}' is not in {source_path.name}.",
                {"arrays": archive.files},
            )
        array = np.asarray(archive[array_name])
    if export_type == "numeric_json":
        path = (
            Path(args["output_file"]).expanduser().resolve()
            if args.get("output_file")
            else _artifact_path(
                model_id,
                f"{source_path.stem}-{array_name}",
                "json",
                {"numeric_sha256": _array_sha256(array)},
            )
        )
        _atomic_json(
            path,
            {
                "source_artifact": str(source_path),
                "array_name": array_name,
                "shape": list(array.shape),
                "dtype": str(array.dtype),
                "data": _jsonable(array),
            },
        )
    elif export_type == "numeric_csv":
        if np.iscomplexobj(array):
            raise ToolError(
                "UNSUPPORTED_EXPORT",
                "numeric_csv does not accept complex arrays; use numeric_json.",
            )
        if array.ndim > 2:
            raise ToolError(
                "UNSUPPORTED_EXPORT",
                "numeric_csv supports only one- or two-dimensional arrays.",
            )
        path = (
            Path(args["output_file"]).expanduser().resolve()
            if args.get("output_file")
            else _artifact_path(
                model_id,
                f"{source_path.stem}-{array_name}",
                "csv",
                {"numeric_sha256": _array_sha256(array)},
            )
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savetxt(path, np.atleast_2d(array), delimiter=",")
    else:
        raise ToolError(
            "UNSUPPORTED_EXPORT",
            f"Unknown export_type '{export_type}'.",
            {"supported": ["model_json", "numeric_json", "numeric_csv"]},
        )
    return {
        "model_id": model_id,
        "export_type": export_type,
        "source_artifact": str(source_path),
        "array_name": array_name,
        "path": str(path),
        "numeric_sha256": _array_sha256(array),
        "file_sha256": _file_sha256(path),
    }


_MODEL_ID = {"type": "string", "description": "Persistent physical-optics model ID"}
_WAVELENGTH_INDEX = {
    "type": "integer",
    "minimum": 0,
    "default": 0,
    "description": "Zero-based index into model wavelengths (values stored in nm)",
}
_FIELD_INDEX = {
    "type": "integer",
    "minimum": 0,
    "default": 0,
    "description": "Zero-based index into model fields (angles stored in deg)",
}
_FOCAL_PROPERTIES = {
    "model_id": _MODEL_ID,
    "effective_focal_length_mm": {
        "type": "number",
        "exclusiveMinimum": 0,
        "description": "Effective focal length in mm",
    },
    "wavelength_index": _WAVELENGTH_INDEX,
    "field_index": _FIELD_INDEX,
    "oversampling": {
        "type": "number",
        "minimum": 1,
        "maximum": 8,
        "default": 2,
        "description": "Prysm FFT padding/oversampling factor",
    },
}


TOOLS = {
    "physical_optics_health": {
        "handler": handle_health,
        "description": "Report Prysm/Poke versions, deterministic outputs, and optional licensed-adapter availability.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    "physical_optics_reference": {
        "handler": handle_reference,
        "description": "Return unit, aberration, method, or limitation reference text.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "enum": ["units", "aberrations", "methods", "limitations"],
                    "default": "methods",
                }
            },
            "additionalProperties": False,
        },
    },
    "physical_optics_new_model": {
        "handler": handle_new_model,
        "description": "Create and persist a deterministic physical-optics JSON model.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "model_id": {"type": "string"},
                "metadata": {"type": "object"},
            },
            "additionalProperties": False,
        },
    },
    "physical_optics_load_model": {
        "handler": handle_load_model,
        "description": "Load and validate a physical-optics model from JSON file or inline JSON.",
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
    "physical_optics_save_model": {
        "handler": handle_save_model,
        "description": "Save a physical-optics model to managed storage or an explicit JSON path.",
        "inputSchema": {
            "type": "object",
            "properties": {"model_id": _MODEL_ID, "file_path": {"type": "string"}},
            "required": ["model_id"],
            "additionalProperties": False,
        },
    },
    "physical_optics_list_models": {
        "handler": handle_list_models,
        "description": "List in-memory and persisted physical-optics models.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    "physical_optics_get_model": {
        "handler": handle_get_model,
        "description": "Return a complete physical-optics JSON model and deterministic digest.",
        "inputSchema": {
            "type": "object",
            "properties": {"model_id": _MODEL_ID},
            "required": ["model_id"],
            "additionalProperties": False,
        },
    },
    "physical_optics_define_pupil": {
        "handler": handle_define_pupil,
        "description": "Define a unit-safe sampled pupil with optional obscuration and apodization.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "model_id": _MODEL_ID,
                "shape": {"type": "string", "enum": ["circle", "square"], "default": "circle"},
                "diameter_mm": {
                    "type": "number",
                    "exclusiveMinimum": 0,
                    "description": "Full pupil diameter/width in mm",
                },
                "samples": {"type": "integer", "minimum": 32, "maximum": 2048, "default": 256},
                "obscuration_ratio": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 0.95,
                    "default": 0,
                    "description": "Inner-to-outer pupil radius ratio",
                },
                "apodization": {
                    "type": "object",
                    "description": "{type:'uniform'} or {type:'gaussian', edge_amplitude:0..1}",
                },
            },
            "required": ["model_id", "diameter_mm"],
            "additionalProperties": False,
        },
    },
    "physical_optics_define_wavelengths_fields": {
        "handler": handle_define_wavelengths_fields,
        "description": "Replace wavelengths in nm and/or angular fields in degrees.",
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
                "fields": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "properties": {
                            "x_deg": {"type": "number", "default": 0},
                            "y_deg": {"type": "number", "default": 0},
                            "weight": {"type": "number", "minimum": 0, "default": 1},
                        },
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["model_id"],
            "additionalProperties": False,
        },
    },
    "physical_optics_set_aberrations": {
        "handler": handle_set_aberrations,
        "description": "Replace normalized Prysm Zernike wavefront coefficients in nm.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "model_id": _MODEL_ID,
                "terms": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "n": {"type": "integer", "minimum": 0, "maximum": 50},
                            "m": {"type": "integer"},
                            "coefficient_nm": {"type": "number"},
                        },
                        "required": ["n", "m", "coefficient_nm"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["model_id", "terms"],
            "additionalProperties": False,
        },
    },
    "physical_optics_wavefront": {
        "handler": handle_wavefront,
        "description": "Build the Prysm pupil wavefront, report WFE metrics, and export NPZ arrays.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "model_id": _MODEL_ID,
                "wavelength_index": _WAVELENGTH_INDEX,
                "field_index": _FIELD_INDEX,
            },
            "required": ["model_id"],
            "additionalProperties": False,
        },
    },
    "physical_optics_propagate": {
        "handler": handle_propagate,
        "description": "Propagate with Prysm FFT focus or angular-spectrum free space and export NPZ.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "model_id": _MODEL_ID,
                "method": {
                    "type": "string",
                    "enum": ["focus", "angular_spectrum"],
                    "default": "focus",
                },
                "effective_focal_length_mm": {"type": "number", "exclusiveMinimum": 0},
                "distance_mm": {"type": "number"},
                "oversampling": {"type": "number", "minimum": 1, "maximum": 8},
                "wavelength_index": _WAVELENGTH_INDEX,
                "field_index": _FIELD_INDEX,
            },
            "required": ["model_id", "method"],
            "additionalProperties": False,
        },
    },
    "physical_optics_psf": {
        "handler": handle_psf,
        "description": "Calculate a normalized scalar PSF and Strehl ratio with Prysm.",
        "inputSchema": {
            "type": "object",
            "properties": _FOCAL_PROPERTIES,
            "required": ["model_id", "effective_focal_length_mm"],
            "additionalProperties": False,
        },
    },
    "physical_optics_mtf": {
        "handler": handle_mtf,
        "description": "Calculate sagittal/tangential MTF from the Prysm PSF and export CSV.",
        "inputSchema": {
            "type": "object",
            "properties": {
                **_FOCAL_PROPERTIES,
                "frequencies_cycles_per_mm": {
                    "type": "array",
                    "items": {"type": "number", "minimum": 0},
                },
            },
            "required": ["model_id", "effective_focal_length_mm"],
            "additionalProperties": False,
        },
    },
    "physical_optics_encircled_energy": {
        "handler": handle_encircled_energy,
        "description": "Integrate encircled energy from the normalized Prysm PSF and export CSV.",
        "inputSchema": {
            "type": "object",
            "properties": {
                **_FOCAL_PROPERTIES,
                "radii_um": {
                    "type": "array",
                    "items": {"type": "number", "minimum": 0},
                    "description": "Optional radii in micrometers; default is 256-point curve",
                },
            },
            "required": ["model_id", "effective_focal_length_mm"],
            "additionalProperties": False,
        },
    },
    "physical_optics_gaussian_beamlets": {
        "handler": handle_gaussian_beamlets,
        "description": "Trace deterministic first-order Gaussian beamlets using Poke Rayfront and ABCD complex curvature.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "model_id": _MODEL_ID,
                "wavelength_index": _WAVELENGTH_INDEX,
                "waist_mm": {"type": "number", "exclusiveMinimum": 0},
                "pupil_radius_mm": {"type": "number", "exclusiveMinimum": 0},
                "nrays_across": {"type": "integer", "minimum": 3, "maximum": 41, "default": 9},
                "max_fov_deg": {"type": "number", "exclusiveMinimum": 0, "default": 1},
                "field_deg": {
                    "type": "array",
                    "minItems": 2,
                    "maxItems": 2,
                    "items": {"type": "number"},
                },
                "elements": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string", "enum": ["free_space", "thin_lens"]},
                            "distance_mm": {"type": "number"},
                            "focal_length_mm": {"type": "number"},
                        },
                        "required": ["type"],
                        "additionalProperties": False,
                    },
                },
                "grid_samples": {"type": "integer", "minimum": 32, "maximum": 512, "default": 128},
                "detector_extent_mm": {"type": "number", "exclusiveMinimum": 0},
            },
            "required": ["model_id", "waist_mm"],
            "additionalProperties": False,
        },
    },
    "physical_optics_polarization_jones": {
        "handler": handle_polarization_jones,
        "description": "Trace a planar-interface Fresnel/Jones sequence with Poke and return Jones, Mueller, and Stokes data.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "wavelength_nm": {"type": "number", "exclusiveMinimum": 0, "default": 550},
                "input_jones": {
                    "type": "array",
                    "minItems": 2,
                    "maxItems": 2,
                    "description": "Two complex values, each number or {real,imag}",
                },
                "interfaces": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "properties": {
                            "n1": {"description": "Incident refractive index: number or {real,imag}"},
                            "n2": {"description": "Exit refractive index: number or {real,imag}"},
                            "incidence_angle_deg": {
                                "type": "number",
                                "minimum": 0,
                                "exclusiveMaximum": 90,
                                "default": 0,
                            },
                            "mode": {
                                "type": "string",
                                "enum": ["reflect", "transmit"],
                                "default": "transmit",
                            },
                            "basis_rotation_deg": {"type": "number", "default": 0},
                        },
                        "required": ["n1", "n2"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["interfaces"],
            "additionalProperties": False,
        },
    },
    "physical_optics_render": {
        "handler": handle_render,
        "description": "Render pupil, WFE, PSF, MTF, encircled energy, or Gaussian beamlets to attributed PNG.",
        "inputSchema": {
            "type": "object",
            "properties": {
                **_FOCAL_PROPERTIES,
                "kind": {
                    "type": "string",
                    "enum": [
                        "pupil",
                        "wavefront",
                        "psf",
                        "mtf",
                        "encircled_energy",
                        "gaussian_beamlets",
                    ],
                },
                "width_px": {"type": "integer", "minimum": 400, "maximum": 5000, "default": 1400},
                "output_file": {"type": "string"},
                "max_frequency_cycles_per_mm": {"type": "number", "exclusiveMinimum": 0},
                "waist_mm": {"type": "number", "exclusiveMinimum": 0},
                "pupil_radius_mm": {"type": "number", "exclusiveMinimum": 0},
                "nrays_across": {"type": "integer", "minimum": 3, "maximum": 41},
                "max_fov_deg": {"type": "number", "exclusiveMinimum": 0},
                "field_deg": {"type": "array", "items": {"type": "number"}},
                "elements": {"type": "array", "items": {"type": "object"}},
                "grid_samples": {"type": "integer", "minimum": 32, "maximum": 512},
                "detector_extent_mm": {"type": "number", "exclusiveMinimum": 0},
            },
            "required": ["model_id", "kind"],
            "additionalProperties": False,
        },
    },
    "physical_optics_export": {
        "handler": handle_export,
        "description": "Export persistent model JSON or an NPZ numeric array to deterministic JSON/CSV.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "model_id": _MODEL_ID,
                "export_type": {
                    "type": "string",
                    "enum": ["model_json", "numeric_json", "numeric_csv"],
                    "default": "model_json",
                },
                "source_artifact": {"type": "string"},
                "array_name": {"type": "string"},
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
        "serverInfo": {"name": "physical_optics_mcp", "version": SERVER_VERSION},
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
