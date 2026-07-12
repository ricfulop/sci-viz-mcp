"""Unit and stdio end-to-end tests for optical_design_mcp."""

from __future__ import annotations

import importlib.util
import json
import math
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "optical_design_mcp" / "optical_design_mcp_server.py"


def load_server(tmp_path: Path):
    os.environ["OPTICAL_DESIGN_OUTPUT_DIR"] = str(tmp_path / "design-output")
    os.environ["MPLBACKEND"] = "Agg"
    spec = importlib.util.spec_from_file_location(
        f"optical_design_test_{tmp_path.name}",
        SERVER,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    module.notify_preview = lambda *args, **kwargs: None
    return module


def new_singlet(module, model_id: str = "singlet") -> str:
    return module.handle_new_model(
        {
            "name": model_id,
            "model_id": model_id,
            "preset": "biconvex_singlet",
        }
    )["model_id"]


def rms_operand():
    return {
        "type": "rms_spot_size",
        "target": 0.0,
        "input_data": {
            "surface_number": -1,
            "Hx": 0.0,
            "Hy": 0.0,
            "num_rays": 3,
            "wavelength_nm": 550.0,
            "distribution": "uniform",
        },
    }


def tolerance_args(model_id: str):
    return {
        "model_id": model_id,
        "seed": 12345,
        "iterations": 8,
        "perturbations": [
            {
                "type": "radius",
                "surface_number": 1,
                "distribution": "normal",
                "mean": 50.0,
                "sigma": 0.1,
            }
        ],
        "operands": [
            {
                "type": "rms_spot_size",
                "input_data": {
                    "surface_number": -1,
                    "Hx": 0.0,
                    "Hy": 0.0,
                    "num_rays": 3,
                    "wavelength_nm": 550.0,
                    "distribution": "uniform",
                },
            }
        ],
    }


def test_health_and_dependency_degradation(tmp_path):
    module = load_server(tmp_path)
    health = module.handle_health({})
    assert health["ok"]
    assert health["engine"]["version"] == "0.6.0"
    assert health["engine"]["available"]
    assert len(module.TOOLS) >= 18

    previous = module.OPTILAND_IMPORT_ERROR
    module.OPTILAND_IMPORT_ERROR = ImportError("simulated missing optional package")
    degraded = module.handle_health({})
    assert not degraded["engine"]["available"]
    with pytest.raises(module.ToolError) as error:
        module.handle_trace({"model_id": "missing"})
    # Model lookup precedes engine lookup for unknown IDs; verify the engine
    # error directly through the stable guard.
    with pytest.raises(module.ToolError) as engine_error:
        module._require_optiland()
    assert engine_error.value.code == "ENGINE_UNAVAILABLE"
    module.OPTILAND_IMPORT_ERROR = previous


def test_model_surface_editing_and_roundtrip(tmp_path):
    module = load_server(tmp_path)
    model_id = module.handle_new_model(
        {"name": "editable", "model_id": "editable", "preset": "empty"}
    )["model_id"]
    first = module.handle_add_surface(
        {
            "model_id": model_id,
            "surface": {
                "radius_mm": 40.0,
                "thickness_mm": 4.0,
                "material": "N-BK7",
                "is_stop": True,
                "comment": "front",
            },
        }
    )
    assert first["index"] == 1
    second = module.handle_add_surface(
        {
            "model_id": model_id,
            "surface": {
                "radius_mm": -40.0,
                "thickness_mm": 35.0,
                "material": "air",
                "comment": "rear",
            },
        }
    )
    assert second["index"] == 2
    updated = module.handle_update_surface(
        {
            "model_id": model_id,
            "index": 2,
            "patch": {"radius_mm": -45.0, "conic": -0.1},
        }
    )
    assert updated["surface"]["radius_mm"] == -45.0
    module.handle_set_aperture_stop(
        {
            "model_id": model_id,
            "aperture_type": "EPD",
            "value": 8.0,
            "stop_index": 1,
        }
    )
    module.handle_set_fields(
        {
            "model_id": model_id,
            "field_type": "angle",
            "fields": [{"x_deg": 0, "y_deg": 0}, {"x_deg": 0, "y_deg": 2}],
        }
    )
    module.handle_set_wavelengths(
        {
            "model_id": model_id,
            "wavelengths": [{"value_nm": 486.1}, {"value_nm": 587.6}],
            "primary_index": 1,
        }
    )
    saved = module.handle_save_model({"model_id": model_id})
    module._models.clear()
    loaded = module.handle_load_model(
        {"file_path": saved["path"], "model_id": "loaded-editable"}
    )
    model = module.handle_get_model({"model_id": loaded["model_id"]})["model"]
    assert model["units"]["length"] == "mm"
    assert model["units"]["wavelength"] == "nm"
    assert model["surfaces"][2]["conic"] == -0.1
    assert model["fields"]["items"][1]["y_deg"] == 2
    assert model["wavelengths"][1]["is_primary"]

    removed = module.handle_remove_surface(
        {"model_id": "loaded-editable", "index": 2}
    )
    assert removed["surface_count"] == 3


def test_biconvex_singlet_paraxial_focal_length_matches_lensmaker(tmp_path):
    module = load_server(tmp_path)
    model_id = new_singlet(module)
    model = module.handle_get_model({"model_id": model_id})["model"]
    system = module._build_optic(model)

    wavelength_um = 0.55
    glass_index = float(
        np.asarray(system.surfaces[1].material_post.n(wavelength_um)).ravel()[0]
    )
    r1_mm, r2_mm, thickness_mm = 50.0, -50.0, 5.0
    lensmaker_power = (glass_index - 1) * (
        1 / r1_mm
        - 1 / r2_mm
        + (glass_index - 1) * thickness_mm / (glass_index * r1_mm * r2_mm)
    )
    expected_efl_mm = 1 / lensmaker_power
    optiland_efl_mm = float(np.asarray(system.paraxial.f2()))
    assert optiland_efl_mm == pytest.approx(expected_efl_mm, rel=2e-3)
    assert float(np.asarray(system.paraxial.FNO())) == pytest.approx(
        optiland_efl_mm / 10.0,
        rel=1e-9,
    )


def test_trace_spot_and_mtf_known_invariants(tmp_path):
    module = load_server(tmp_path)
    model_id = new_singlet(module)
    trace = module.handle_trace(
        {
            "model_id": model_id,
            "Hx": 0.0,
            "Hy": 0.0,
            "wavelength_nm": 550.0,
            "num_rays": 5,
            "distribution": "uniform",
        }
    )
    assert trace["valid_ray_count"] > 5
    assert trace["centroid_mm"]["x"] == pytest.approx(0.0, abs=1e-12)
    assert trace["centroid_mm"]["y"] == pytest.approx(0.0, abs=1e-12)
    assert trace["length_unit"] == "mm"

    spot = module.handle_spot(
        {"model_id": model_id, "num_rings": 3, "distribution": "hexapolar"}
    )
    assert spot["rms_spot_radius_mm"][0][0] > 0
    assert Path(spot["artifact_path"]).exists()

    mtf = module.handle_mtf(
        {
            "model_id": model_id,
            "method": "geometric",
            "num_rays": 5,
            "num_points": 32,
        }
    )
    assert mtf["fields"][0]["dc_mtf"]["tangential"] == pytest.approx(
        1.0, abs=1e-12
    )
    assert mtf["fields"][0]["dc_mtf"]["sagittal"] == pytest.approx(
        1.0, abs=1e-12
    )
    fft_mtf = module.handle_mtf(
        {
            "model_id": model_id,
            "method": "fft",
            "num_rays": 16,
            "num_points": 32,
        }
    )
    assert fft_mtf["engine"] == "optiland.mtf.ScalarFFTMTF"
    assert fft_mtf["fields"][0]["dc_mtf"]["tangential"] == pytest.approx(
        1.0, abs=1e-12
    )


def test_seeded_tolerance_regenerates_identical_results(tmp_path):
    module = load_server(tmp_path)
    model_id = new_singlet(module)
    args = tolerance_args(model_id)
    first = module.handle_tolerance(args)
    second = module.handle_tolerance(args)
    assert first["artifact_path"] == second["artifact_path"]
    assert first["file_sha256"] == second["file_sha256"]
    assert first["summary"] == second["summary"]
    assert first["results_reset_to_nominal"]

    model = module.handle_get_model({"model_id": model_id})["model"]
    assert model["surfaces"][1]["radius_mm"] == 50.0


def test_optimization_improves_merit_and_persists_prescription(tmp_path):
    module = load_server(tmp_path)
    model_id = new_singlet(module)
    result = module.handle_optimize(
        {
            "model_id": model_id,
            "variables": [
                {
                    "type": "radius",
                    "surface_number": 2,
                    "min": -100.0,
                    "max": -20.0,
                }
            ],
            "operands": [rms_operand()],
            "method": "L-BFGS-B",
            "max_iterations": 10,
            "tolerance": 1e-6,
        }
    )
    assert result["final_merit"] < result["initial_merit"] * 1e-3
    assert result["model_persisted"]
    optimized_radius = module.handle_get_model({"model_id": model_id})["model"][
        "surfaces"
    ][2]["radius_mm"]
    assert optimized_radius != -50.0
    assert -100 <= optimized_radius <= -20


def test_material_catalog_render_and_exports(tmp_path):
    module = load_server(tmp_path)
    model_id = new_singlet(module)
    catalog = module.handle_materials({"query": "N-BK7", "limit": 5})
    assert catalog["count"] > 0
    assert any(
        "bk7" in " ".join(str(value) for value in item.values()).lower()
        for item in catalog["materials"]
    )

    render_args = {
        "model_id": model_id,
        "kind": "layout",
        "num_rays": 3,
        "dpi": 100,
    }
    first = module.handle_render(render_args)
    second = module.handle_render(render_args)
    assert first["image_path"] == second["image_path"]
    assert Path(first["image_path"]).stat().st_size > 1000

    for export_type in ("model_json", "optiland_json", "prescription_csv"):
        exported = module.handle_export(
            {"model_id": model_id, "export_type": export_type}
        )
        assert Path(exported["path"]).exists()
        assert len(exported["file_sha256"]) == 64


def test_stdio_end_to_end(tmp_path):
    env = {
        **os.environ,
        "OPTICAL_DESIGN_OUTPUT_DIR": str(tmp_path / "e2e-output"),
        "MPLBACKEND": "Agg",
    }
    proc = subprocess.Popen(
        [sys.executable, str(SERVER)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    assert proc.stdin is not None
    assert proc.stdout is not None
    request_id = 0

    def rpc(method, params=None):
        nonlocal request_id
        request_id += 1
        proc.stdin.write(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": method,
                    "params": params or {},
                }
            )
            + "\n"
        )
        proc.stdin.flush()
        response = json.loads(proc.stdout.readline())
        assert "error" not in response, response
        return response["result"]

    def call(name, arguments=None):
        result = rpc(
            "tools/call",
            {"name": name, "arguments": arguments or {}},
        )
        return json.loads(result["content"][0]["text"])

    assert rpc("initialize")["serverInfo"]["name"] == "optical_design_mcp"
    assert len(rpc("tools/list")["tools"]) >= 18
    created = call(
        "optical_design_new_model",
        {"name": "e2e", "model_id": "e2e", "preset": "biconvex_singlet"},
    )
    traced = call(
        "optical_design_trace",
        {"model_id": created["model_id"], "num_rays": 5},
    )
    assert traced["valid_ray_count"] > 0
    assert Path(traced["artifact_path"]).exists()
    proc.stdin.close()
    proc.wait(timeout=20)
    assert proc.returncode == 0
