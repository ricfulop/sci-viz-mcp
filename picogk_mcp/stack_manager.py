"""Pinned source-cache management for the public LEAP 71 modeling stack."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import uuid
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Iterable

THIS_DIR = Path(__file__).resolve().parent
DEFAULT_LOCK_PATH = THIS_DIR / "stack.lock.json"
DEFAULT_CACHE_ROOT = Path(
    os.environ.get(
        "PICOGK_MCP_CACHE_DIR",
        str(Path.home() / ".cache" / "sci-viz-mcp" / "picogk"),
    )
).expanduser()

_MODULE_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


class StackError(RuntimeError):
    """Raised when the locked source stack cannot be resolved safely."""


class StackManager:
    """Read, validate, synchronize, and query the locked LEAP 71 stack."""

    def __init__(
        self,
        lock_path: str | Path = DEFAULT_LOCK_PATH,
        cache_root: str | Path = DEFAULT_CACHE_ROOT,
    ) -> None:
        self.lock_path = Path(lock_path).expanduser().resolve()
        self.cache_root = Path(cache_root).expanduser().resolve()
        self.lock = json.loads(self.lock_path.read_text(encoding="utf-8"))
        self._validate_lock()
        canonical = json.dumps(
            self.lock, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        self.lock_hash = hashlib.sha256(canonical).hexdigest()
        self.stack_dir = self.cache_root / self.lock_hash[:16]
        self.sources_dir = self.stack_dir / "sources"

    @property
    def modules(self) -> dict[str, dict]:
        return self.lock["modules"]

    @property
    def package(self) -> dict:
        return self.lock["packages"]["picogk"]

    def _validate_lock(self) -> None:
        if self.lock.get("schema_version") != 1:
            raise StackError("Unsupported PicoGK stack lock schema.")
        if self.lock.get("dotnet_target") != "net9.0":
            raise StackError("PicoGK 2.2 jobs must target net9.0.")

        package = self.lock.get("packages", {}).get("picogk")
        if not isinstance(package, dict):
            raise StackError("Lock file is missing packages.picogk.")
        if not _COMMIT_RE.fullmatch(str(package.get("commit", ""))):
            raise StackError("PicoGK package commit must be a full SHA-1.")
        if not package.get("version"):
            raise StackError("PicoGK package version is required.")

        modules = self.lock.get("modules")
        if not isinstance(modules, dict) or not modules:
            raise StackError("Lock file must define at least one source module.")
        for name, module in modules.items():
            if not _MODULE_RE.fullmatch(name):
                raise StackError(f"Invalid module name in lock: {name!r}")
            if not str(module.get("repository", "")).startswith(
                "https://github.com/leap71/"
            ):
                raise StackError(f"{name}: repository must be under leap71.")
            if not _COMMIT_RE.fullmatch(str(module.get("commit", ""))):
                raise StackError(f"{name}: commit must be a full SHA-1.")
            includes = module.get("include")
            if not isinstance(includes, list) or not includes:
                raise StackError(f"{name}: at least one include glob is required.")
            for dep in module.get("dependencies", []):
                if dep not in modules:
                    raise StackError(f"{name}: unknown dependency {dep!r}.")

    def resolve_modules(self, requested: Iterable[str] | None) -> list[str]:
        """Return requested modules plus transitive dependencies in build order."""
        names = list(requested or [])
        if not names:
            return []
        unknown = sorted(set(names) - set(self.modules))
        if unknown:
            raise StackError(
                f"Unknown PicoGK modules: {unknown}. Available: {sorted(self.modules)}"
            )

        ordered: list[str] = []
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(name: str) -> None:
            if name in visited:
                return
            if name in visiting:
                raise StackError(f"Dependency cycle involving {name!r}.")
            visiting.add(name)
            for dep in self.modules[name].get("dependencies", []):
                visit(dep)
            visiting.remove(name)
            visited.add(name)
            ordered.append(name)

        for name in names:
            visit(name)
        return ordered

    def repo_dir(self, module_name: str) -> Path:
        if module_name not in self.modules:
            raise StackError(f"Unknown PicoGK module: {module_name}")
        return self.sources_dir / module_name

    def _git(self) -> str:
        configured = os.environ.get("PICOGK_MCP_GIT")
        if configured:
            path = Path(configured).expanduser()
            if path.is_file():
                return str(path)
            raise StackError(f"PICOGK_MCP_GIT does not exist: {path}")
        found = shutil.which("git")
        if found:
            return found
        raise StackError("git was not found. Install Git or set PICOGK_MCP_GIT.")

    def _run_git(
        self,
        args: list[str],
        *,
        cwd: Path | None = None,
        timeout_s: int = 300,
    ) -> subprocess.CompletedProcess[str]:
        proc = subprocess.run(
            [self._git(), *args],
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env={
                **os.environ,
                "GIT_TERMINAL_PROMPT": "0",
                "GIT_CONFIG_NOSYSTEM": "1",
            },
        )
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout).strip()[-4000:]
            raise StackError(f"git {' '.join(args[:2])} failed: {detail}")
        return proc

    def _checked_out_commit(self, module_name: str) -> str | None:
        target = self.repo_dir(module_name)
        if not (target / ".git").is_dir():
            return None
        try:
            return self._run_git(
                ["rev-parse", "HEAD"], cwd=target, timeout_s=30
            ).stdout.strip()
        except (StackError, subprocess.TimeoutExpired):
            return None

    def verify_module(self, module_name: str) -> dict:
        module = self.modules[module_name]
        actual = self._checked_out_commit(module_name)
        expected = module["commit"]
        return {
            "module": module_name,
            "ready": actual == expected,
            "expected_commit": expected,
            "actual_commit": actual,
            "path": str(self.repo_dir(module_name)),
            "license": module["license"],
            "redistributable": bool(module.get("redistributable", False)),
        }

    @contextmanager
    def _sync_lock(self, timeout_s: int = 60):
        self.cache_root.mkdir(parents=True, exist_ok=True)
        lock_file = self.cache_root / f".{self.lock_hash[:16]}.sync.lock"
        deadline = time.monotonic() + timeout_s
        fd: int | None = None
        while fd is None:
            try:
                fd = os.open(
                    lock_file,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o600,
                )
                os.write(fd, f"{os.getpid()}\n".encode("ascii"))
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise StackError(
                        f"Timed out waiting for stack sync lock: {lock_file}"
                    )
                time.sleep(0.2)
        try:
            yield
        finally:
            if fd is not None:
                os.close(fd)
            try:
                lock_file.unlink()
            except FileNotFoundError:
                pass

    def _sync_one(self, module_name: str, *, force: bool = False) -> dict:
        module = self.modules[module_name]
        current = self.verify_module(module_name)
        if current["ready"] and not force:
            current["action"] = "cached"
            return current

        target = self.repo_dir(module_name)
        if target.exists():
            if not force:
                raise StackError(
                    f"{module_name} cache exists at the wrong revision. "
                    "Retry with force=true to replace it."
                )
            shutil.rmtree(target)

        target.parent.mkdir(parents=True, exist_ok=True)
        staging = target.with_name(f".{target.name}.tmp-{uuid.uuid4().hex}")
        try:
            staging.mkdir(parents=False)
            self._run_git(["init", "--quiet"], cwd=staging)
            self._run_git(
                ["remote", "add", "origin", module["repository"]], cwd=staging
            )
            self._run_git(
                ["fetch", "--depth", "1", "origin", module["commit"]],
                cwd=staging,
            )
            self._run_git(["checkout", "--detach", "FETCH_HEAD"], cwd=staging)
            actual = self._run_git(
                ["rev-parse", "HEAD"], cwd=staging, timeout_s=30
            ).stdout.strip()
            if actual != module["commit"]:
                raise StackError(
                    f"{module_name}: expected {module['commit']}, got {actual}."
                )
            os.replace(staging, target)
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)

        result = self.verify_module(module_name)
        result["action"] = "fetched"
        return result

    def sync(
        self,
        requested: Iterable[str] | None = None,
        *,
        include_unlicensed: bool = False,
        force: bool = False,
    ) -> dict:
        """Synchronize exact locked commits into the local source cache."""
        modules = self.resolve_modules(
            requested if requested is not None else self.modules.keys()
        )
        restricted = [
            name
            for name in modules
            if self.modules[name].get("license") == "NOASSERTION"
        ]
        if restricted and not include_unlicensed:
            raise StackError(
                "These public repositories do not declare a reusable license: "
                f"{restricted}. Pass include_unlicensed=true only if you have "
                "confirmed your right to use them locally."
            )

        with self._sync_lock():
            results = [
                self._sync_one(name, force=force)
                for name in modules
            ]
        return {
            "lock_hash": self.lock_hash,
            "stack_dir": str(self.stack_dir),
            "modules": results,
        }

    def status(self, requested: Iterable[str] | None = None) -> dict:
        modules = self.resolve_modules(
            requested if requested is not None else self.modules.keys()
        )
        statuses = [self.verify_module(name) for name in modules]
        return {
            "lock_hash": self.lock_hash,
            "lock_path": str(self.lock_path),
            "cache_root": str(self.cache_root),
            "stack_dir": str(self.stack_dir),
            "ready": all(item["ready"] for item in statuses),
            "package": self.package,
            "modules": statuses,
        }

    def source_files(self, requested: Iterable[str]) -> list[Path]:
        """Return deterministic, de-duplicated C# sources for selected modules."""
        files: dict[str, Path] = {}
        for name in self.resolve_modules(requested):
            status = self.verify_module(name)
            if not status["ready"]:
                raise StackError(
                    f"{name} is not synchronized. Run picogk_sync_stack first."
                )
            module = self.modules[name]
            root = self.repo_dir(name)
            resolved_root = root.resolve()
            excluded = module.get("exclude", [])
            for pattern in module["include"]:
                for candidate in root.glob(pattern):
                    if not candidate.is_file() or candidate.suffix.lower() != ".cs":
                        continue
                    resolved_candidate = candidate.resolve()
                    if not resolved_candidate.is_relative_to(resolved_root):
                        raise StackError(
                            f"{name}: source symlink escapes the locked repository: "
                            f"{candidate}"
                        )
                    relative = candidate.relative_to(root).as_posix()
                    if any(
                        PurePosixPath(relative).match(item)
                        for item in excluded
                    ):
                        continue
                    files[f"{name}/{relative}"] = resolved_candidate
        return [files[key] for key in sorted(files)]

    def catalog(self) -> dict:
        return {
            "lock_hash": self.lock_hash,
            "dotnet_target": self.lock["dotnet_target"],
            "package": self.package,
            "modules": {
                name: {
                    "description": module["description"],
                    "dependencies": module.get("dependencies", []),
                    "license": module["license"],
                    "redistributable": module.get("redistributable", False),
                    "commit": module["commit"],
                    "repository": module["repository"],
                    "compatibility": module.get("compatibility"),
                }
                for name, module in self.modules.items()
            },
        }

