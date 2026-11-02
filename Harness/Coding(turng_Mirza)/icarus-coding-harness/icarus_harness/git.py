import subprocess
from pathlib import Path

def _git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=30)
    return (result.stdout if result.returncode == 0 else result.stderr or result.stdout).strip()

def status(root: Path) -> str:
    return _git(root, "status", "--short", "--branch")

def diff(root: Path) -> str:
    return _git(root, "diff", "--")
