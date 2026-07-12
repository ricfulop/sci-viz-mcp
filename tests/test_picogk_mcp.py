#!/usr/bin/env python3
"""Protocol, failure-isolation, full-stack compile, and native PicoGK tests."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from picogk_mcp import PicoGKBackend, PicoGKBackendError, StackError, StackManager

TEST_ROOT = REPO / "output" / "test_picogk_mcp"
CACHE_ROOT = Path(
    os.environ.get(
        "PICOGK_TEST_CACHE_DIR",
        str(REPO / "output" / "picogk-stack-cache"),
    )
)
MODELS = REPO / "tests" / "picogk_models"
SERVER = REPO / "picogk_mcp" / "picogk_mcp_server.py"


def _backend(name: str) -> PicoGKBackend:
    root = TEST_ROOT / name
    shutil.rmtree(root, ignore_errors=True)
    return PicoGKBackend(
        root,
        stack_manager=StackManager(cache_root=CACHE_ROOT),
    )


def _native_backend(name: str) -> PicoGKBackend:
    backend = _backend(name)
    health = backend.health()
    if not health["dotnet_version"] or not health["native_runtime_supported"]:
        raise unittest.SkipTest(
            f"Native PicoGK unavailable: {health['rid']} / {health['dotnet_error']}"
        )
    return backend


def _assert_raises(exception_type, function, *args, **kwargs):
    try:
        function(*args, **kwargs)
    except exception_type:
        return
    raise AssertionError(f"Expected {exception_type.__name__}.")


def test_stack_lock_and_license_gate():
    manager = StackManager(cache_root=TEST_ROOT / "empty-cache")
    assert manager.resolve_modules(["lattice_library"]) == [
        "shape_kernel",
        "lattice_library",
    ]
    assert len(manager.catalog()["modules"]) == 7
    assert manager.package["version"] == "2.2.0"
    _assert_raises(
        StackError,
        manager.sync,
        ["simulation_example"],
        include_unlicensed=False,
    )


def test_project_generation_and_path_validation():
    backend = _backend("generation")
    project = backend.create_project(name="Generated Project", modules=[])
    assert project["project_id"].startswith("generated-project-")
    job = backend._create_job(
        project["project_id"],
        voxel_size_mm=0.5,
        viewer_mode="headless",
        timeout_s=30,
        build_only=True,
    )
    csproj = (job.job_dir / "SciVizPicoGKJob.csproj").read_text()
    assert 'PackageReference Include="PicoGK" Version="2.2.0"' in csproj
    assert "RunnerHost.cs" in csproj
    _assert_raises(
        PicoGKBackendError,
        backend.artifact,
        job.job_id,
        "../outside.stl",
    )


def test_mcp_protocol_and_health():
    env = {
        **os.environ,
        "PYTHONPATH": str(REPO),
        "PICOGK_MCP_OUTPUT_DIR": str(TEST_ROOT / "protocol"),
        "PICOGK_MCP_CACHE_DIR": str(CACHE_ROOT),
        "PICOGK_MCP_AUTO_PREVIEW": "0",
    }
    proc = subprocess.Popen(
        [sys.executable, str(SERVER)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(REPO),
        env=env,
    )
    commands = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "picogk_health", "arguments": {}},
        },
    ]
    try:
        responses = []
        for command in commands:
            assert proc.stdin is not None
            proc.stdin.write(json.dumps(command) + "\n")
            proc.stdin.flush()
            assert proc.stdout is not None
            responses.append(json.loads(proc.stdout.readline()))
        assert responses[0]["result"]["serverInfo"]["name"] == "picogk_mcp"
        tools = responses[1]["result"]["tools"]
        assert len(tools) == 17
        assert {tool["name"] for tool in tools} >= {
            "picogk_run_csharp",
            "picogk_cancel_job",
            "picogk_preview_artifact",
        }
        health = json.loads(
            responses[2]["result"]["content"][0]["text"]
        )
        assert health["picogk_version"] == "2.2.0"
        assert health["trusted_code_execution"] is True
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def test_native_core_roundtrip():
    backend = _native_backend("native-core")
    source = (MODELS / "core_roundtrip.cs").read_text()
    project = backend.create_project(
        name="core-roundtrip",
        modules=[],
        source=source,
    )
    result = backend.run_project(
        project["project_id"],
        voxel_size_mm=0.8,
        viewer_mode="headless",
        timeout_s=180,
        wait=True,
    )
    assert result["status"] == "succeeded", backend.job_logs(result["job_id"])
    artifacts = {item["relative_path"]: item for item in result["artifacts"]}
    assert artifacts["core_roundtrip.stl"]["bytes"] > 1000
    assert artifacts["core_fields.vdb"]["bytes"] > 1000
    validation = json.loads(
        Path(artifacts["validation.json"]["path"]).read_text()
    )
    assert validation["fields"] == 3
    assert abs(validation["scalar"] - 42.0) < 1e-6
    assert validation["vector"] == [1, 2, 3]


def test_native_shape_and_lattice():
    backend = _native_backend("native-shape-lattice")
    status = backend.stack.status(["lattice_library"])
    if not status["ready"]:
        raise unittest.SkipTest("Locked ShapeKernel/LatticeLibrary cache not synchronized.")
    project = backend.create_project(
        name="shape-lattice",
        modules=["lattice_library"],
        source=(MODELS / "shape_lattice.cs").read_text(),
    )
    result = backend.run_project(
        project["project_id"],
        voxel_size_mm=1.0,
        viewer_mode="headless",
        timeout_s=240,
        wait=True,
    )
    assert result["status"] == "succeeded", backend.job_logs(result["job_id"])
    assert result["artifacts"][0]["bytes"] > 1000


def test_full_stack_modules_compile():
    if os.environ.get("PICOGK_FULL_STACK_TESTS") != "1":
        raise unittest.SkipTest("Set PICOGK_FULL_STACK_TESTS=1 for all source modules.")
    backend = _native_backend("full-stack")
    modules = list(backend.stack.modules)
    if not backend.stack.status(modules)["ready"]:
        raise unittest.SkipTest("Full locked LEAP 71 stack is not synchronized.")

    failures = {}
    for module in modules:
        project = backend.create_project(
            name=f"compile-{module}",
            modules=[module],
        )
        result = backend.build_project(
            project["project_id"],
            timeout_s=600,
            wait=True,
        )
        if result["status"] != "succeeded":
            failures[module] = backend.job_logs(result["job_id"])
    assert not failures, json.dumps(failures, indent=2)

    representative_models = {
        "quasi_crystals": ("quasi_crystal.cs", 1.0),
        "rover_wheel": ("rover_tread.cs", 1.5),
        "helix_heatx": ("helix_component.cs", 1.0),
        "simulation_example": ("simulation_fields.cs", 1.0),
    }
    runtime_failures = {}
    for module, (model_name, voxel_size) in representative_models.items():
        project = backend.create_project(
            name=f"run-{module}",
            modules=[module],
            source=(MODELS / model_name).read_text(),
        )
        result = backend.run_project(
            project["project_id"],
            voxel_size_mm=voxel_size,
            viewer_mode="headless",
            timeout_s=600,
            wait=True,
        )
        if result["status"] != "succeeded" or not result["artifacts"]:
            runtime_failures[module] = backend.job_logs(result["job_id"])
    assert not runtime_failures, json.dumps(runtime_failures, indent=2)


def test_failure_isolation_and_cancellation():
    backend = _native_backend("failure-isolation")
    bad_project = backend.create_project(
        name="bad-source",
        source="public static class Broken { this is not C sharp; }",
    )
    failed = backend.build_project(
        bad_project["project_id"],
        timeout_s=120,
        wait=True,
    )
    assert failed["status"] == "failed"

    sleep_source = """using SciViz.PicoGK.Runner;
public static class SleepingModel
{
    [PicoGKTask]
    public static void Task(JobContext context)
    {
        Thread.Sleep(TimeSpan.FromSeconds(30));
    }
}
"""
    sleeping = backend.create_project(name="sleeping", source=sleep_source)
    running = backend.run_project(
        sleeping["project_id"],
        viewer_mode="headless",
        timeout_s=120,
        wait=False,
    )
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        status = backend.job_status(running["job_id"])
        if status["status"] == "running":
            break
        if status["status"] in {"failed", "timed_out"}:
            raise AssertionError(backend.job_logs(running["job_id"]))
        time.sleep(0.2)
    cancelled = backend.cancel_job(running["job_id"])
    deadline = time.monotonic() + 10
    while cancelled["status"] not in {"cancelled", "failed"} and time.monotonic() < deadline:
        time.sleep(0.2)
        cancelled = backend.job_status(running["job_id"])
    assert cancelled["status"] == "cancelled"

    good = backend.create_project(name="after-failure")
    succeeded = backend.run_project(
        good["project_id"],
        viewer_mode="headless",
        timeout_s=120,
        wait=True,
    )
    assert succeeded["status"] == "succeeded", backend.job_logs(succeeded["job_id"])


def main() -> int:
    TEST_ROOT.mkdir(parents=True, exist_ok=True)
    tests = [
        test_stack_lock_and_license_gate,
        test_project_generation_and_path_validation,
        test_mcp_protocol_and_health,
        test_native_core_roundtrip,
        test_native_shape_and_lattice,
        test_full_stack_modules_compile,
        test_failure_isolation_and_cancellation,
    ]
    failures = 0
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
        except unittest.SkipTest as exc:
            print(f"SKIP {test.__name__}: {exc}")
        except Exception as exc:
            failures += 1
            print(f"FAIL {test.__name__}: {exc}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
