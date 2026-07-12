"""Unit and stdio end-to-end tests for physical_optics_mcp."""

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
SERVER = ROOT / "physical_optics_mcp" / "physical_optics_mcp_server.py"


def load_server(tmp_path: Path):
    os.environ["PHYSICAL_OPTICS_OUTPUT_DIR"] = str(tmp_path / "physical-output")
    os.environ["MPLBACKEND"] = "Agg"
    spec = importlib.util.spec_from_file_location(
        f"physical_optics_test_{tmp_path.name}",
        SERVER,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    module.notify_preview = lambda *args, **kwargs: None
    return module


def new_circular_model(module, samples: int = 128) -> str:
    model_id = module.handle_new_model(
        {"name": "analytic-circular-pupil", "model_id": "analytic"}
    )["model_id"]
    module.handle_define_pupil(
        {
            "model_id": model_id,
            "shape": "circle",
            "diameter_mm": 10.0,
            "samples": samples,
            "obscuration_ratio": 0.0,
            "apodization": {"type": "uniform"},
        }
    )
    module.handle_define_wavelengths_fields(
        {
            "model_id": model_id,
            "wavelengths": [{"value_nm": 550.0, "weight": 1.0}],
            "fields": [{"x_deg": 0.0, "y_deg": 0.0, "weight": 1.0}],
        }
    )
    return model_id


def test_health_tools_and_persistent_model_roundtrip(tmp_path):
    module = load_server(tmp_path)
    health = module.handle_health({})
    assert health["ok"]
    assert health["engines"]["prysm"]["available"]
    assert health["engines"]["poke"]["available"]
    assert health["licensed_adapters"]["zemax_zos_api"]["optional"]
    assert len(module.TOOLS) >= 17

    model_id = new_circular_model(module, samples=64)
    saved = module.handle_save_model({"model_id": model_id})
    assert Path(saved["path"]).exists()
    first_digest = saved["model_digest"]

    module._models.clear()
    loaded = module.handle_load_model(
        {"file_path": saved["path"], "model_id": "reloaded"}
    )
    assert loaded["model_digest"] == first_digest
    model = module.handle_get_model({"model_id": "reloaded"})["model"]
    assert model["units"]["wavelength"] == "nm"
    assert model["units"]["pupil_length"] == "mm"
    assert module.handle_list_models({})["count"] >= 2


def test_clear_circular_pupil_matches_airy_energy_and_mtf(tmp_path):
    module = load_server(tmp_path)
    model_id = new_circular_model(module, samples=128)

    # f/10 at 550 nm: first Airy-zero radius = 1.22 lambda N = 6.71 um.
    airy_zero_um = 1.22 * 0.55 * 10.0
    ee = module.handle_encircled_energy(
        {
            "model_id": model_id,
            "effective_focal_length_mm": 100.0,
            "oversampling": 4.0,
            "radii_um": [airy_zero_um],
        }
    )
    measured = ee["samples"][0]["encircled_energy"]
    assert measured == pytest.approx(0.837785, abs=0.015)
    assert "pinned Prysm revision has no encircled-energy helper" in ee["integration"]

    # Incoherent circular-pupil cutoff = 1/(lambda_mm * f/#).
    cutoff = 1.0 / (0.00055 * 10.0)
    half_cutoff = cutoff / 2
    analytic_half = 2 / math.pi * (
        math.acos(0.5) - 0.5 * math.sqrt(1 - 0.5**2)
    )
    mtf = module.handle_mtf(
        {
            "model_id": model_id,
            "effective_focal_length_mm": 100.0,
            "oversampling": 4.0,
            "frequencies_cycles_per_mm": [0.0, half_cutoff, cutoff],
        }
    )
    assert mtf["sampled"][0]["tangential"] == pytest.approx(1.0, abs=1e-12)
    assert mtf["sampled"][1]["tangential"] == pytest.approx(
        analytic_half, abs=0.04
    )
    assert mtf["sampled"][2]["tangential"] < 0.04


def test_aberration_reduces_strehl_and_wavefront_reports_nm(tmp_path):
    module = load_server(tmp_path)
    model_id = new_circular_model(module, samples=96)
    ideal = module.handle_psf(
        {"model_id": model_id, "effective_focal_length_mm": 100.0}
    )
    assert ideal["strehl_ratio"] == pytest.approx(1.0, abs=1e-12)

    module.handle_set_aberrations(
        {
            "model_id": model_id,
            "terms": [{"n": 2, "m": 0, "coefficient_nm": 150.0}],
        }
    )
    wavefront = module.handle_wavefront({"model_id": model_id})
    aberrated = module.handle_psf(
        {"model_id": model_id, "effective_focal_length_mm": 100.0}
    )
    assert wavefront["metrics"]["rms_wavefront_error_nm"] > 100
    assert aberrated["strehl_ratio"] < 0.5


def test_deterministic_scalar_regeneration_and_numeric_export(tmp_path):
    module = load_server(tmp_path)
    model_id = new_circular_model(module, samples=64)
    focused = module.handle_propagate(
        {
            "model_id": model_id,
            "method": "focus",
            "effective_focal_length_mm": 100.0,
            "oversampling": 2.0,
        }
    )
    free_space = module.handle_propagate(
        {
            "model_id": model_id,
            "method": "angular_spectrum",
            "distance_mm": 10.0,
            "oversampling": 1.0,
        }
    )
    assert focused["sample_spacing_unit"] == "um"
    assert focused["engine"] == "prysm.Wavefront.focus"
    assert free_space["sample_spacing_unit"] == "mm"
    assert free_space["engine"] == "prysm.Wavefront.free_space"

    call = {
        "model_id": model_id,
        "effective_focal_length_mm": 100.0,
        "oversampling": 2.0,
    }
    first = module.handle_psf(call)
    second = module.handle_psf(call)
    assert first["artifact_path"] == second["artifact_path"]
    assert first["numeric_sha256"] == second["numeric_sha256"]

    exported = module.handle_export(
        {
            "model_id": model_id,
            "export_type": "numeric_json",
            "source_artifact": first["artifact_path"],
            "array_name": "psf",
        }
    )
    payload = json.loads(Path(exported["path"]).read_text())
    assert payload["shape"] == first["shape"]
    assert exported["numeric_sha256"] == first["numeric_sha256"]


def test_poke_gaussian_free_space_matches_analytic_radius(tmp_path):
    module = load_server(tmp_path)
    model_id = new_circular_model(module, samples=64)
    waist_mm = 0.1
    distance_mm = 100.0
    wavelength_mm = 550e-6
    rayleigh_mm = math.pi * waist_mm**2 / wavelength_mm
    expected_radius = waist_mm * math.sqrt(1 + (distance_mm / rayleigh_mm) ** 2)
    result = module.handle_gaussian_beamlets(
        {
            "model_id": model_id,
            "waist_mm": waist_mm,
            "nrays_across": 5,
            "grid_samples": 32,
            "elements": [{"type": "free_space", "distance_mm": distance_mm}],
        }
    )
    assert result["output_1e2_radius_mm"]["x"] == pytest.approx(
        expected_radius, rel=1e-12
    )
    assert result["output_1e2_radius_mm"]["y"] == pytest.approx(
        expected_radius, rel=1e-12
    )
    assert "poke.beamlets.prop_complex_curvature" in result["engine"]["propagation"]
    assert not result["licensed_adapter_used"]


def test_poke_normal_incidence_jones_fresnel_case(tmp_path):
    module = load_server(tmp_path)
    result = module.handle_polarization_jones(
        {
            "wavelength_nm": 550.0,
            "input_jones": [1.0, 0.0],
            "interfaces": [
                {
                    "n1": 1.0,
                    "n2": 1.5,
                    "incidence_angle_deg": 0.0,
                    "mode": "reflect",
                }
            ],
        }
    )
    matrix = result["system_jones_matrix"]
    assert matrix[0][0]["real"] == pytest.approx(-0.2, abs=1e-12)
    assert matrix[1][1]["real"] == pytest.approx(0.2, abs=1e-12)
    assert result["output_stokes"]["S0"] == pytest.approx(0.04, abs=1e-12)
    assert result["engine"].startswith("poke.polarization")


def test_render_is_stable_and_attributed(tmp_path):
    module = load_server(tmp_path)
    model_id = new_circular_model(module, samples=64)
    args = {
        "model_id": model_id,
        "kind": "mtf",
        "effective_focal_length_mm": 100.0,
        "width_px": 600,
    }
    first = module.handle_render(args)
    second = module.handle_render(args)
    assert first["image_path"] == second["image_path"]
    assert Path(first["image_path"]).stat().st_size > 1000
    assert first["attribution"] == module.ATTRIBUTION_TEXT


def test_stdio_end_to_end(tmp_path):
    env = {
        **os.environ,
        "PHYSICAL_OPTICS_OUTPUT_DIR": str(tmp_path / "e2e-output"),
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

    assert rpc("initialize")["serverInfo"]["name"] == "physical_optics_mcp"
    assert len(rpc("tools/list")["tools"]) >= 17
    created = call(
        "physical_optics_new_model",
        {"name": "e2e", "model_id": "e2e"},
    )
    wavefront = call(
        "physical_optics_wavefront",
        {"model_id": created["model_id"]},
    )
    assert Path(wavefront["artifact_path"]).exists()
    proc.stdin.close()
    proc.wait(timeout=15)
    assert proc.returncode == 0
