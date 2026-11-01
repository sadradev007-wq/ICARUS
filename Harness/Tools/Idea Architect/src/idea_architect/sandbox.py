"""Linux bubblewrap command sandbox; fails closed when isolation is unavailable.

Only an absolute executable and fixed arguments supplied by trusted host configuration are
accepted. Task text is passed as JSON on stdin and is never interpreted as a shell command.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .execution import ExecutionError, HandlerResult


@dataclass(frozen=True)
class SandboxPolicy:
    timeout_seconds: int = 30
    max_input_bytes: int = 1024 * 1024
    max_output_bytes: int = 1024 * 1024
    cpu_seconds: int = 20
    memory_bytes: int = 512 * 1024 * 1024
    max_file_bytes: int = 16 * 1024 * 1024
    max_processes: int = 16


class BubblewrapCommandHandler:
    """Run a fixed trusted executable in a network-isolated bubblewrap namespace."""
    def __init__(
        self, *, executable: str, fixed_args: tuple[str, ...] = (),
        policy: SandboxPolicy | None = None, bubblewrap: str = "bwrap"
    ) -> None:
        executable_path = Path(executable)
        if not executable_path.is_absolute() or not executable_path.is_file():
            raise ValueError("executable must be an existing absolute file path")
        executable_path = executable_path.resolve()
        if not any(executable_path.is_relative_to(Path(root)) for root in ("/usr", "/bin")):
            raise ValueError("executable must reside under /usr or /bin, visible in the sandbox")
        if any("\x00" in arg for arg in fixed_args):
            raise ValueError("arguments cannot contain NUL bytes")
        self.executable = str(executable_path)
        self.fixed_args = tuple(fixed_args)
        self.policy = policy or SandboxPolicy()
        self.bubblewrap = shutil.which(bubblewrap)
        if self.policy.timeout_seconds < 1 or min(
            self.policy.max_input_bytes, self.policy.max_output_bytes,
            self.policy.cpu_seconds, self.policy.memory_bytes,
            self.policy.max_file_bytes, self.policy.max_processes
        ) < 1:
            raise ValueError("sandbox limits must be positive")

    def __call__(self, task: dict[str, Any], project_dir: Path) -> HandlerResult:
        if os.name != "posix" or resource is None:
            raise ExecutionError("This sandbox requires Linux/POSIX resource limits")
        if not self.bubblewrap:
            raise ExecutionError("bubblewrap is unavailable; refusing unsandboxed execution")
        payload = json.dumps(task, ensure_ascii=False).encode("utf-8")
        if len(payload) > self.policy.max_input_bytes:
            raise ExecutionError("Task input exceeds sandbox input limit")
        project_dir = Path(project_dir).resolve()
        project_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="icarus-skill-", dir=project_dir) as tmp:
            workspace = Path(tmp).resolve()
            command = [self.bubblewrap, "--unshare-all", "--die-with-parent"]
            for system_path in ("/usr", "/bin", "/lib", "/lib64", "/etc"):
                if Path(system_path).exists():
                    command.extend(["--ro-bind", system_path, system_path])
            command.extend([
                "--proc", "/proc", "--dev", "/dev",
                "--tmpfs", "/tmp",
                "--bind", str(workspace), "/workspace",
                "--chdir", "/workspace",
                "--", self.executable, *self.fixed_args
            ])
            env = {"PATH": "/usr/bin:/bin", "HOME": "/workspace",
                   "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}
            def apply_resource_limits() -> None:
                resource.setrlimit(resource.RLIMIT_CPU, (self.policy.cpu_seconds, self.policy.cpu_seconds))
                resource.setrlimit(resource.RLIMIT_AS, (self.policy.memory_bytes, self.policy.memory_bytes))
                resource.setrlimit(resource.RLIMIT_FSIZE, (self.policy.max_file_bytes, self.policy.max_file_bytes))
                resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
                if hasattr(resource, "RLIMIT_NPROC"):
                    resource.setrlimit(resource.RLIMIT_NPROC, (self.policy.max_processes, self.policy.max_processes))

            with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
                try:
                    proc = subprocess.Popen(
                        command, stdin=subprocess.PIPE, stdout=stdout_file,
                        stderr=stderr_file, cwd=str(workspace), env=env,
                        close_fds=True, start_new_session=True,
                        preexec_fn=apply_resource_limits
                    )
                    try:
                        proc.communicate(input=payload, timeout=self.policy.timeout_seconds)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.communicate()
                        raise ExecutionError("Sandbox command timed out")
                except OSError as exc:
                    raise ExecutionError(f"Could not start bubblewrap sandbox: {exc}") from exc
                stdout_file.seek(0)
                stdout = stdout_file.read(self.policy.max_output_bytes + 1)
                stderr_file.seek(0)
                stderr = stderr_file.read(min(self.policy.max_output_bytes, 8192) + 1)
            if len(stdout) > self.policy.max_output_bytes:
                raise ExecutionError("Sandbox stdout exceeded output limit")
            if len(stderr) > min(self.policy.max_output_bytes, 8192):
                stderr = stderr[:8192]
            if proc.returncode != 0:
                raise ExecutionError(
                    f"Sandbox command exited {proc.returncode}: "
                    + stderr.decode("utf-8", errors="replace")
                )
            try:
                result = json.loads(stdout.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ExecutionError("Sandbox must return one UTF-8 JSON object on stdout") from exc
            if not isinstance(result, dict):
                raise ExecutionError("Sandbox output must be a JSON object")
            return HandlerResult(outputs=result, summary="Executed in bubblewrap namespace")
