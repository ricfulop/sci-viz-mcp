"""Project, build, and isolated job lifecycle for PicoGK MCP."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import signal
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape as xml_escape

from .stack_manager import StackError, StackManager

try:
    from preview.notify import notify_preview
except Exception:  # preview dashboard is optional
    def notify_preview(*args, **kwargs):
        return None

THIS_DIR = Path(__file__).resolve().parent
REPO_ROOT = THIS_DIR.parent
RUNNER_HOST = THIS_DIR / "runner" / "RunnerHost.cs"
DEFAULT_OUTPUT_ROOT = Path(
    os.environ.get(
        "PICOGK_MCP_OUTPUT_DIR",
        str(REPO_ROOT / "output" / "picogk"),
    )
).expanduser()

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,95}$")
_VALID_VIEWER_MODES = {"headless", "viewer_autoclose", "viewer_interactive"}
_PREVIEWABLE_SUFFIXES = {".png", ".jpg", ".jpeg", ".pdf", ".svg"}
_MAX_SOURCE_BYTES = 2 * 1024 * 1024
_MAX_LOG_CHARS = 200_000


class PicoGKBackendError(RuntimeError):
    """Actionable backend failure surfaced through MCP."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return (slug or "model")[:48]


def _validate_id(value: str, kind: str) -> str:
    if not _ID_RE.fullmatch(value):
        raise PicoGKBackendError(
            f"Invalid {kind} {value!r}; use lowercase letters, numbers, and hyphens."
        )
    return value


@dataclass
class JobRecord:
    job_id: str
    project_id: str
    job_dir: Path
    modules: list[str]
    voxel_size_mm: float
    viewer_mode: str
    timeout_s: int
    build_only: bool
    build_hash: str
    status: str = "queued"
    created_at: str = field(default_factory=_utc_now)
    started_at: str | None = None
    ended_at: str | None = None
    pid: int | None = None
    exit_code: int | None = None
    error: str | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event)
    process: subprocess.Popen | None = None


class PicoGKBackend:
    """Trusted-local raw C# execution with per-job process isolation."""

    def __init__(
        self,
        output_root: str | Path = DEFAULT_OUTPUT_ROOT,
        *,
        stack_manager: StackManager | None = None,
    ) -> None:
        self.output_root = Path(output_root).expanduser().resolve()
        self.projects_dir = self.output_root / "projects"
        self.jobs_dir = self.output_root / "jobs"
        self.build_cache_dir = self.output_root / "build_cache"
        self.dotnet_cli_home = self.output_root / "dotnet_home"
        self.nuget_packages = Path(
            os.environ.get(
                "NUGET_PACKAGES",
                str(REPO_ROOT / ".nuget" / "packages"),
            )
        ).expanduser()
        self.stack = stack_manager or StackManager()
        self._jobs: dict[str, JobRecord] = {}
        self._jobs_lock = threading.RLock()
        self._build_locks: dict[str, threading.Lock] = {}

    # ------------------------------------------------------------------
    # Environment and project lifecycle

    @staticmethod
    def detect_rid() -> str:
        machine = platform.machine().lower()
        if sys_platform := platform.system().lower():
            if sys_platform == "darwin" and machine in {"arm64", "aarch64"}:
                return "osx-arm64"
            if sys_platform == "windows" and machine in {
                "amd64",
                "x86_64",
            }:
                return "win-x64"
            return f"{sys_platform}-{machine or 'unknown'}"
        return f"unknown-{machine or 'unknown'}"

    @staticmethod
    def find_dotnet() -> str | None:
        configured = os.environ.get("PICOGK_MCP_DOTNET")
        if configured:
            path = Path(configured).expanduser()
            return str(path.resolve()) if path.is_file() else None
        found = shutil.which("dotnet")
        if found:
            return found
        candidates = [
            REPO_ROOT / ".dotnet" / "dotnet",
            Path.home() / ".dotnet" / "dotnet",
            Path("/usr/local/share/dotnet/dotnet"),
            Path("/opt/homebrew/bin/dotnet"),
            Path(r"C:\Program Files\dotnet\dotnet.exe"),
        ]
        for candidate in candidates:
            if candidate.is_file():
                return str(candidate)
        return None

    def health(self) -> dict:
        dotnet = self.find_dotnet()
        dotnet_version = None
        dotnet_error = None
        if dotnet:
            try:
                proc = subprocess.run(
                    [dotnet, "--version"],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                if proc.returncode == 0:
                    dotnet_version = proc.stdout.strip()
                else:
                    dotnet_error = (proc.stderr or proc.stdout).strip()
            except Exception as exc:  # health must degrade, not crash
                dotnet_error = str(exc)

        rid = self.detect_rid()
        supported = rid in self.stack.package["supported_rids"]
        return {
            "status": "ok" if dotnet and dotnet_version else "degraded",
            "dotnet": dotnet,
            "dotnet_version": dotnet_version,
            "dotnet_error": dotnet_error,
            "required_target": self.stack.lock["dotnet_target"],
            "rid": rid,
            "native_runtime_supported": supported,
            "supported_rids": self.stack.package["supported_rids"],
            "picogk_version": self.stack.package["version"],
            "output_root": str(self.output_root),
            "trusted_code_execution": True,
            "stack": self.stack.status(),
        }

    def _validate_source(self, source: str) -> None:
        if not isinstance(source, str) or not source.strip():
            raise PicoGKBackendError("C# source must be a non-empty string.")
        if len(source.encode("utf-8")) > _MAX_SOURCE_BYTES:
            raise PicoGKBackendError(
                f"C# source exceeds {_MAX_SOURCE_BYTES} bytes."
            )

    def create_project(
        self,
        *,
        name: str,
        modules: list[str] | None = None,
        source: str | None = None,
    ) -> dict:
        selected = self.stack.resolve_modules(modules or [])
        if source is None:
            source = self.default_source()
        self._validate_source(source)

        project_id = f"{_slug(name)}-{uuid.uuid4().hex[:8]}"
        project_dir = self.projects_dir / project_id
        project_dir.mkdir(parents=True, exist_ok=False)
        (project_dir / "Model.cs").write_text(source, encoding="utf-8")
        manifest = {
            "project_id": project_id,
            "name": name,
            "modules": selected,
            "created_at": _utc_now(),
            "updated_at": _utc_now(),
            "source_file": "Model.cs",
        }
        _atomic_json(project_dir / "project.json", manifest)
        return self.get_project(project_id, include_source=False)

    def _project_dir(self, project_id: str) -> Path:
        _validate_id(project_id, "project_id")
        return self.projects_dir / project_id

    def _load_project(self, project_id: str) -> tuple[Path, dict]:
        project_dir = self._project_dir(project_id)
        manifest_path = project_dir / "project.json"
        if not manifest_path.is_file():
            raise PicoGKBackendError(f"Unknown PicoGK project: {project_id}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        return project_dir, manifest

    def get_project(self, project_id: str, *, include_source: bool = True) -> dict:
        project_dir, manifest = self._load_project(project_id)
        source_path = project_dir / manifest["source_file"]
        result = {
            **manifest,
            "project_dir": str(project_dir),
            "source_path": str(source_path),
            "source_sha256": _sha256_file(source_path),
        }
        if include_source:
            result["source"] = source_path.read_text(encoding="utf-8")
        return result

    def list_projects(self) -> dict:
        projects = []
        if self.projects_dir.is_dir():
            for manifest_path in sorted(self.projects_dir.glob("*/project.json")):
                try:
                    manifest = json.loads(
                        manifest_path.read_text(encoding="utf-8")
                    )
                    projects.append(
                        {
                            **manifest,
                            "project_dir": str(manifest_path.parent),
                        }
                    )
                except (OSError, json.JSONDecodeError):
                    continue
        return {"projects": projects}

    def write_source(
        self,
        project_id: str,
        source: str,
        *,
        modules: list[str] | None = None,
    ) -> dict:
        self._validate_source(source)
        project_dir, manifest = self._load_project(project_id)
        if modules is not None:
            manifest["modules"] = self.stack.resolve_modules(modules)
        source_path = project_dir / manifest["source_file"]
        temporary = source_path.with_suffix(".cs.tmp")
        temporary.write_text(source, encoding="utf-8")
        os.replace(temporary, source_path)
        manifest["updated_at"] = _utc_now()
        _atomic_json(project_dir / "project.json", manifest)
        return self.get_project(project_id, include_source=False)

    @staticmethod
    def default_source() -> str:
        return """using System.Numerics;
using PicoGK;
using SciViz.PicoGK.Runner;

namespace SciViz.PicoGK.Job;

public static class UserModel
{
    [PicoGKTask]
    public static void Task(JobContext context)
    {
        Voxels sphere = Voxels.voxSphere(
            Library.oLibrary(),
            Vector3.Zero,
            10f
        );
        Mesh mesh = sphere.mshAsMesh();
        string output = context.OutputPath("model.stl");
        mesh.SaveToStlFile(output);
        context.RegisterArtifact(
            output,
            "triangle_mesh",
            new { units = "mm" }
        );
    }
}
"""

    def _dotnet_env(self) -> dict[str, str]:
        self.dotnet_cli_home.mkdir(parents=True, exist_ok=True)
        self.nuget_packages.mkdir(parents=True, exist_ok=True)
        return {
            **os.environ,
            "DOTNET_CLI_HOME": str(self.dotnet_cli_home),
            "DOTNET_CLI_TELEMETRY_OPTOUT": "1",
            "DOTNET_NOLOGO": "1",
            "NUGET_PACKAGES": str(self.nuget_packages),
        }

    def _runner_env(self) -> dict[str, str]:
        """Minimal runtime environment; do not leak API keys into raw C#."""
        self.dotnet_cli_home.mkdir(parents=True, exist_ok=True)
        self.nuget_packages.mkdir(parents=True, exist_ok=True)
        allowed = {
            "HOME",
            "LANG",
            "LC_ALL",
            "PATH",
            "SystemRoot",
            "TEMP",
            "TMP",
            "TMPDIR",
            "USER",
            "WINDIR",
        }
        env = {key: value for key, value in os.environ.items() if key in allowed}
        env.update(
            {
                "DOTNET_CLI_HOME": str(self.dotnet_cli_home),
                "DOTNET_CLI_TELEMETRY_OPTOUT": "1",
                "DOTNET_NOLOGO": "1",
                "NUGET_PACKAGES": str(self.nuget_packages),
            }
        )
        dotnet = self.find_dotnet()
        if dotnet:
            env["DOTNET_ROOT"] = str(Path(dotnet).resolve().parent)
        return env

    # ------------------------------------------------------------------
    # Job generation and execution

    def _build_hash(self, source: str, modules: list[str]) -> str:
        payload = {
            "source": source,
            "modules": modules,
            "stack_lock": self.stack.lock_hash,
            "picogk_version": self.stack.package["version"],
            "runner_host": _sha256_file(RUNNER_HOST),
            "target": self.stack.lock["dotnet_target"],
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode("utf-8")
        ).hexdigest()

    def _write_csproj(
        self,
        path: Path,
        *,
        model_path: Path,
        modules: list[str],
    ) -> None:
        sources = self.stack.source_files(modules) if modules else []
        compile_items = [
            (
                RUNNER_HOST,
                "RunnerHost.cs",
            ),
            (
                model_path,
                "Model.cs",
            ),
        ]
        for source in sources:
            module = next(
                name
                for name in modules
                if source.is_relative_to(self.stack.repo_dir(name))
            )
            relative = source.relative_to(self.stack.repo_dir(module))
            compile_items.append(
                (source, f"upstream/{module}/{relative.as_posix()}")
            )

        compile_xml = "\n".join(
            "    <Compile Include=\"{}\" Link=\"{}\" />".format(
                xml_escape(str(source), {'"': "&quot;"}),
                xml_escape(link, {'"': "&quot;"}),
            )
            for source, link in compile_items
        )
        package = self.stack.package
        content = f"""<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <OutputType>Exe</OutputType>
    <TargetFramework>{xml_escape(self.stack.lock["dotnet_target"])}</TargetFramework>
    <AssemblyName>SciVizPicoGKJob</AssemblyName>
    <RootNamespace>SciViz.PicoGK.Job</RootNamespace>
    <ImplicitUsings>enable</ImplicitUsings>
    <Nullable>enable</Nullable>
    <EnableDefaultCompileItems>false</EnableDefaultCompileItems>
    <RestorePackagesWithLockFile>true</RestorePackagesWithLockFile>
    <Deterministic>true</Deterministic>
  </PropertyGroup>
  <ItemGroup>
    <PackageReference Include="{xml_escape(package["package"])}" Version="{xml_escape(package["version"])}" />
  </ItemGroup>
  <ItemGroup>
{compile_xml}
  </ItemGroup>
</Project>
"""
        path.write_text(content, encoding="utf-8")

    def _create_job(
        self,
        project_id: str,
        *,
        voxel_size_mm: float,
        viewer_mode: str,
        timeout_s: int,
        build_only: bool,
    ) -> JobRecord:
        if (
            not isinstance(voxel_size_mm, (int, float))
            or not 0 < float(voxel_size_mm) <= 1000
        ):
            raise PicoGKBackendError(
                "voxel_size_mm must be greater than 0 and at most 1000."
            )
        if viewer_mode not in _VALID_VIEWER_MODES:
            raise PicoGKBackendError(
                f"viewer_mode must be one of {sorted(_VALID_VIEWER_MODES)}."
            )
        if not 1 <= int(timeout_s) <= 86_400:
            raise PicoGKBackendError("timeout_s must be between 1 and 86400.")

        project_dir, manifest = self._load_project(project_id)
        modules = self.stack.resolve_modules(manifest.get("modules", []))
        if modules:
            missing = [
                item["module"]
                for item in self.stack.status(modules)["modules"]
                if not item["ready"]
            ]
            if missing:
                raise PicoGKBackendError(
                    f"Source modules are not synchronized: {missing}. "
                    "Call picogk_sync_stack first."
                )

        source = (project_dir / manifest["source_file"]).read_text(encoding="utf-8")
        build_hash = self._build_hash(source, modules)
        job_id = f"job-{uuid.uuid4().hex[:12]}"
        job_dir = self.jobs_dir / job_id
        (job_dir / "src").mkdir(parents=True, exist_ok=False)
        (job_dir / "artifacts").mkdir()
        (job_dir / "logs").mkdir()
        model_path = job_dir / "src" / "Model.cs"
        model_path.write_text(source, encoding="utf-8")
        self._write_csproj(
            job_dir / "SciVizPicoGKJob.csproj",
            model_path=model_path,
            modules=modules,
        )

        record = JobRecord(
            job_id=job_id,
            project_id=project_id,
            job_dir=job_dir,
            modules=modules,
            voxel_size_mm=float(voxel_size_mm),
            viewer_mode=viewer_mode,
            timeout_s=int(timeout_s),
            build_only=build_only,
            build_hash=build_hash,
        )
        with self._jobs_lock:
            self._jobs[job_id] = record
        self._write_job_manifest(record)
        return record

    def build_project(
        self,
        project_id: str,
        *,
        timeout_s: int = 600,
        wait: bool = False,
    ) -> dict:
        record = self._create_job(
            project_id,
            voxel_size_mm=0.5,
            viewer_mode="headless",
            timeout_s=timeout_s,
            build_only=True,
        )
        self._start_job(record)
        return self.wait_job(record.job_id, timeout_s + 30) if wait else self.job_status(record.job_id)

    def run_project(
        self,
        project_id: str,
        *,
        voxel_size_mm: float = 0.5,
        viewer_mode: str = "viewer_autoclose",
        timeout_s: int = 3600,
        wait: bool = False,
    ) -> dict:
        rid = self.detect_rid()
        if (
            rid not in self.stack.package["supported_rids"]
            and os.environ.get("PICOGK_MCP_ALLOW_UNSUPPORTED_RID") != "1"
        ):
            raise PicoGKBackendError(
                f"PicoGK {self.stack.package['version']} has no native runtime for "
                f"{rid}. Supported: {self.stack.package['supported_rids']}."
            )
        record = self._create_job(
            project_id,
            voxel_size_mm=voxel_size_mm,
            viewer_mode=viewer_mode,
            timeout_s=timeout_s,
            build_only=False,
        )
        self._start_job(record)
        return self.wait_job(record.job_id, timeout_s + 600) if wait else self.job_status(record.job_id)

    def run_csharp(
        self,
        *,
        source: str,
        name: str = "one-shot-model",
        modules: list[str] | None = None,
        voxel_size_mm: float = 0.5,
        viewer_mode: str = "viewer_autoclose",
        timeout_s: int = 3600,
        wait: bool = False,
    ) -> dict:
        project = self.create_project(
            name=name,
            modules=modules,
            source=source,
        )
        result = self.run_project(
            project["project_id"],
            voxel_size_mm=voxel_size_mm,
            viewer_mode=viewer_mode,
            timeout_s=timeout_s,
            wait=wait,
        )
        result["project_id"] = project["project_id"]
        return result

    def _start_job(self, record: JobRecord) -> None:
        thread = threading.Thread(
            target=self._execute_job,
            args=(record,),
            name=f"picogk-{record.job_id}",
            daemon=True,
        )
        thread.start()

    def _execute_job(self, record: JobRecord) -> None:
        record.started_at = _utc_now()
        try:
            dotnet = self.find_dotnet()
            if not dotnet:
                raise PicoGKBackendError(
                    "dotnet was not found. Install .NET 9 or set PICOGK_MCP_DOTNET."
                )
            record.status = "building"
            self._write_job_manifest(record)
            self._ensure_build(record, dotnet)
            if record.cancel_event.is_set():
                record.status = "cancelled"
                return
            if record.build_only:
                record.status = "succeeded"
                record.exit_code = 0
                return

            record.status = "running"
            self._write_job_manifest(record)
            result_path = record.job_dir / "runner_result.json"
            log_path = record.job_dir / "logs" / "picogk.log"
            env = {
                **self._runner_env(),
                "PICOGK_JOB_ID": record.job_id,
                "PICOGK_JOB_OUTPUT_DIR": str(record.job_dir / "artifacts"),
                "PICOGK_RUNNER_RESULT": str(result_path),
                "PICOGK_LOG_FILE": str(log_path),
                "PICOGK_VIEWER_MODE": record.viewer_mode,
                "PICOGK_VOXEL_SIZE_MM": format(record.voxel_size_mm, ".9g"),
            }
            exit_code, outcome = self._run_process(
                record,
                [dotnet, str(record.job_dir / "bin" / "SciVizPicoGKJob.dll")],
                cwd=record.job_dir,
                env=env,
                stdout_path=record.job_dir / "logs" / "runner.stdout.log",
                stderr_path=record.job_dir / "logs" / "runner.stderr.log",
                timeout_s=record.timeout_s,
            )
            record.exit_code = exit_code
            if outcome == "cancelled":
                record.status = "cancelled"
            elif outcome == "timed_out":
                record.status = "timed_out"
                record.error = f"Execution exceeded {record.timeout_s} seconds."
            elif exit_code == 0:
                record.status = "succeeded"
            else:
                record.status = "failed"
                record.error = self._runner_error(record)
        except Exception as exc:
            record.status = (
                "cancelled" if record.cancel_event.is_set() else "failed"
            )
            record.error = str(exc)
        finally:
            record.ended_at = _utc_now()
            record.process = None
            record.pid = None
            self._write_job_manifest(record)
            if (
                record.status == "succeeded"
                and os.environ.get("PICOGK_MCP_AUTO_PREVIEW", "1") != "0"
            ):
                self._notify_artifacts(record)

    def _ensure_build(self, record: JobRecord, dotnet: str) -> None:
        cache_dir = self.build_cache_dir / record.build_hash[:24]
        ready = cache_dir / ".ready"
        lock = self._build_locks.setdefault(record.build_hash, threading.Lock())
        with lock:
            if ready.is_file():
                shutil.copytree(
                    cache_dir / "bin",
                    record.job_dir / "bin",
                    dirs_exist_ok=True,
                )
                (record.job_dir / "logs" / "build.stdout.log").write_text(
                    f"Reused build cache {cache_dir}\n",
                    encoding="utf-8",
                )
                (record.job_dir / "logs" / "build.stderr.log").write_text(
                    "", encoding="utf-8"
                )
                return

            exit_code, outcome = self._run_process(
                record,
                [
                    dotnet,
                    "build",
                    str(record.job_dir / "SciVizPicoGKJob.csproj"),
                    "--configuration",
                    "Release",
                    "--nologo",
                    "--verbosity",
                    "minimal",
                    "--output",
                    str(record.job_dir / "bin"),
                ],
                cwd=record.job_dir,
                env=self._dotnet_env(),
                stdout_path=record.job_dir / "logs" / "build.stdout.log",
                stderr_path=record.job_dir / "logs" / "build.stderr.log",
                timeout_s=min(record.timeout_s, 1800),
            )
            record.exit_code = exit_code
            if outcome == "cancelled":
                raise PicoGKBackendError("Build cancelled.")
            if outcome == "timed_out":
                raise PicoGKBackendError("PicoGK project build timed out.")
            if exit_code != 0:
                raise PicoGKBackendError(self._build_error(record))

            staging = cache_dir.with_name(
                f".{cache_dir.name}.tmp-{uuid.uuid4().hex}"
            )
            if staging.exists():
                shutil.rmtree(staging)
            (staging / "bin").mkdir(parents=True)
            shutil.copytree(
                record.job_dir / "bin",
                staging / "bin",
                dirs_exist_ok=True,
            )
            (staging / ".ready").write_text(record.build_hash + "\n")
            cache_dir.parent.mkdir(parents=True, exist_ok=True)
            if cache_dir.exists():
                shutil.rmtree(cache_dir)
            os.replace(staging, cache_dir)

    def _run_process(
        self,
        record: JobRecord,
        command: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
        stdout_path: Path,
        stderr_path: Path,
        timeout_s: int,
    ) -> tuple[int, str]:
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        popen_kwargs: dict[str, Any] = {}
        if os.name == "nt":
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen_kwargs["start_new_session"] = True

        with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            process = subprocess.Popen(
                command,
                cwd=str(cwd),
                env=env,
                stdout=stdout,
                stderr=stderr,
                stdin=subprocess.DEVNULL,
                **popen_kwargs,
            )
            record.process = process
            record.pid = process.pid
            deadline = time.monotonic() + timeout_s
            while True:
                if record.cancel_event.is_set():
                    self._terminate_process(process)
                    return process.wait(), "cancelled"
                return_code = process.poll()
                if return_code is not None:
                    return return_code, "completed"
                if time.monotonic() >= deadline:
                    self._terminate_process(process)
                    return process.wait(), "timed_out"
                time.sleep(0.2)

    @staticmethod
    def _terminate_process(process: subprocess.Popen) -> None:
        if process.poll() is not None:
            return
        try:
            if os.name == "nt":
                process.terminate()
            else:
                os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=5)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            try:
                if os.name == "nt":
                    process.kill()
                else:
                    os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def _build_error(self, record: JobRecord) -> str:
        return "PicoGK build failed:\n" + self._read_log(
            record.job_dir / "logs" / "build.stderr.log",
            fallback=record.job_dir / "logs" / "build.stdout.log",
            limit=12_000,
        )

    def _runner_error(self, record: JobRecord) -> str:
        result_path = record.job_dir / "runner_result.json"
        if result_path.is_file():
            try:
                result = json.loads(result_path.read_text(encoding="utf-8"))
                if result.get("error"):
                    return str(result["error"])
            except (OSError, json.JSONDecodeError):
                pass
        return "PicoGK execution failed:\n" + self._read_log(
            record.job_dir / "logs" / "runner.stderr.log",
            limit=12_000,
        )

    # ------------------------------------------------------------------
    # Job queries, cancellation, logs, and artifacts

    def _get_job(self, job_id: str) -> JobRecord:
        _validate_id(job_id, "job_id")
        with self._jobs_lock:
            record = self._jobs.get(job_id)
        if record:
            return record

        manifest_path = self.jobs_dir / job_id / "job.json"
        if not manifest_path.is_file():
            raise PicoGKBackendError(f"Unknown PicoGK job: {job_id}")
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        record = JobRecord(
            job_id=job_id,
            project_id=data["project_id"],
            job_dir=manifest_path.parent,
            modules=data["modules"],
            voxel_size_mm=data["voxel_size_mm"],
            viewer_mode=data["viewer_mode"],
            timeout_s=data["timeout_s"],
            build_only=data["build_only"],
            build_hash=data["build_hash"],
            status=data["status"],
            created_at=data["created_at"],
            started_at=data.get("started_at"),
            ended_at=data.get("ended_at"),
            exit_code=data.get("exit_code"),
            error=data.get("error"),
        )
        return record

    def job_status(self, job_id: str) -> dict:
        record = self._get_job(job_id)
        result = self._record_dict(record)
        result["artifacts"] = self.list_artifacts(job_id)["artifacts"]
        return result

    def list_jobs(self, limit: int = 100) -> dict:
        jobs = []
        if self.jobs_dir.is_dir():
            manifests = sorted(
                self.jobs_dir.glob("*/job.json"),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
            for path in manifests[: max(1, min(int(limit), 1000))]:
                try:
                    jobs.append(json.loads(path.read_text(encoding="utf-8")))
                except (OSError, json.JSONDecodeError):
                    continue
        return {"jobs": jobs}

    def wait_job(self, job_id: str, timeout_s: int = 4200) -> dict:
        deadline = time.monotonic() + timeout_s
        terminal = {"succeeded", "failed", "cancelled", "timed_out"}
        while time.monotonic() < deadline:
            status = self.job_status(job_id)
            if status["status"] in terminal:
                return status
            time.sleep(0.2)
        raise PicoGKBackendError(
            f"Timed out waiting for {job_id}; the job continues in the background."
        )

    def cancel_job(self, job_id: str) -> dict:
        record = self._get_job(job_id)
        if record.status in {"succeeded", "failed", "cancelled", "timed_out"}:
            return self.job_status(job_id)
        record.cancel_event.set()
        if record.process is not None:
            self._terminate_process(record.process)
        return self.job_status(job_id)

    @staticmethod
    def _read_log(
        path: Path,
        *,
        fallback: Path | None = None,
        limit: int = _MAX_LOG_CHARS,
    ) -> str:
        for selected in (path, fallback):
            if selected is None or not selected.is_file():
                continue
            with selected.open("rb") as stream:
                size = selected.stat().st_size
                stream.seek(max(0, size - limit * 4))
                text = stream.read().decode("utf-8", errors="replace")
            if text:
                return text[-limit:]
        return ""

    def job_logs(self, job_id: str, max_chars: int = 50_000) -> dict:
        record = self._get_job(job_id)
        limit = max(1, min(int(max_chars), _MAX_LOG_CHARS))
        logs = {}
        for path in sorted((record.job_dir / "logs").glob("*")):
            if path.is_file():
                logs[path.name] = self._read_log(path, limit=limit)
        return {"job_id": job_id, "logs": logs}

    def _registered_artifacts(self, record: JobRecord) -> dict[str, dict]:
        path = record.job_dir / "artifacts" / "artifacts.jsonl"
        registered = {}
        if not path.is_file():
            return registered
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                item = json.loads(line)
                registered[str(Path(item["path"]).resolve())] = item
            except (KeyError, TypeError, json.JSONDecodeError):
                continue
        return registered

    def list_artifacts(self, job_id: str) -> dict:
        record = self._get_job(job_id)
        root = record.job_dir / "artifacts"
        registered = self._registered_artifacts(record)
        artifacts = []
        if root.is_dir():
            for path in sorted(root.rglob("*")):
                if not path.is_file() or path.name == "artifacts.jsonl":
                    continue
                registration = registered.get(str(path.resolve()), {})
                suffix = path.suffix.lower()
                inferred_kind = {
                    ".stl": "triangle_mesh",
                    ".obj": "triangle_mesh",
                    ".vdb": "voxel_field",
                    ".png": "image",
                    ".jpg": "image",
                    ".jpeg": "image",
                    ".pdf": "document",
                    ".svg": "image",
                }.get(suffix, "file")
                inferred_metadata = (
                    {"units": "mm"}
                    if suffix in {".stl", ".obj", ".vdb"}
                    else None
                )
                artifacts.append(
                    {
                        "path": str(path.resolve()),
                        "relative_path": path.relative_to(root).as_posix(),
                        "kind": registration.get("kind", inferred_kind),
                        "metadata": registration.get(
                            "metadata", inferred_metadata
                        ),
                        "bytes": path.stat().st_size,
                        "sha256": _sha256_file(path),
                        "previewable": suffix in _PREVIEWABLE_SUFFIXES,
                    }
                )
        return {"job_id": job_id, "artifacts": artifacts}

    def _notify_artifacts(self, record: JobRecord) -> None:
        for artifact in self.list_artifacts(record.job_id)["artifacts"]:
            if not artifact["previewable"]:
                continue
            notify_preview(
                artifact["path"],
                "picogk_run",
                params={
                    "job_id": record.job_id,
                    "project_id": record.project_id,
                    "voxel_size_mm": record.voxel_size_mm,
                    "viewer_mode": record.viewer_mode,
                    "modules": record.modules,
                    "stack_lock_hash": self.stack.lock_hash,
                },
                server_name="picogk_mcp",
            )

    def artifact(
        self,
        job_id: str,
        relative_path: str,
    ) -> dict:
        if Path(relative_path).is_absolute():
            raise PicoGKBackendError("relative_path must not be absolute.")
        record = self._get_job(job_id)
        root = (record.job_dir / "artifacts").resolve()
        path = (root / relative_path).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise PicoGKBackendError(
                f"Artifact not found under {job_id}: {relative_path}"
            )
        return next(
            item
            for item in self.list_artifacts(job_id)["artifacts"]
            if item["path"] == str(path)
        )

    def _record_dict(self, record: JobRecord) -> dict:
        return {
            "job_id": record.job_id,
            "project_id": record.project_id,
            "status": record.status,
            "build_only": record.build_only,
            "modules": record.modules,
            "voxel_size_mm": record.voxel_size_mm,
            "viewer_mode": record.viewer_mode,
            "timeout_s": record.timeout_s,
            "build_hash": record.build_hash,
            "stack_lock_hash": self.stack.lock_hash,
            "picogk_version": self.stack.package["version"],
            "rid": self.detect_rid(),
            "job_dir": str(record.job_dir),
            "created_at": record.created_at,
            "started_at": record.started_at,
            "ended_at": record.ended_at,
            "pid": record.pid,
            "exit_code": record.exit_code,
            "error": record.error,
        }

    def _write_job_manifest(self, record: JobRecord) -> None:
        manifest = self._record_dict(record)
        if record.ended_at:
            manifest["artifacts"] = self.list_artifacts(record.job_id)[
                "artifacts"
            ]
            source = record.job_dir / "src" / "Model.cs"
            manifest["source_sha256"] = (
                _sha256_file(source) if source.is_file() else None
            )
        _atomic_json(record.job_dir / "job.json", manifest)

