from __future__ import annotations
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from .workspace import Workspace, WorkspaceError

@dataclass(frozen=True)
class TestProfile:
    language: str
    command: tuple[str, ...]
    confidence: str
    reason: str
    test_files: tuple[str, ...]
    related_tests: tuple[str, ...]

class TestDiscovery:
    """Read-only project test discovery; it never executes discovered commands."""
    def __init__(self, workspace: Workspace):
        self.workspace = workspace

    def _changed_paths(self, supplied: Iterable[str] | None) -> list[str]:
        if supplied is not None:
            result = []
            for item in supplied:
                if not isinstance(item, str) or not item.strip():
                    continue
                result.append(self.workspace.resolve(item).relative_to(self.workspace.root).as_posix())
            return sorted(set(result))
        try:
            proc = subprocess.run(["git", "diff", "--name-only", "HEAD"], cwd=self.workspace.root,
                                  capture_output=True, text=True, timeout=10, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return []
        if proc.returncode != 0:
            return []
        result = []
        for item in proc.stdout.splitlines():
            if item.strip():
                try:
                    result.append(self.workspace.resolve(item).relative_to(self.workspace.root).as_posix())
                except WorkspaceError:
                    continue
        return sorted(set(result))

    @staticmethod
    def _related(changed: list[str], tests: list[str]) -> list[str]:
        selected = []
        for changed_path in changed:
            stem = Path(changed_path).stem.casefold()
            if stem in {"__init__", "index"}:
                continue
            for test in tests:
                test_stem = Path(test).stem.casefold().removesuffix(".test").removesuffix(".spec")
                if test_stem in {stem, f"test_{stem}", f"{stem}_test"} or stem in Path(test).parts:
                    selected.append(test)
        return sorted(set(selected))

    def discover(self, changed_paths: Iterable[str] | None = None) -> dict:
        files = self.workspace.list_files(limit=5000)
        file_set = set(files)
        changed = self._changed_paths(changed_paths)
        profiles: list[TestProfile] = []
        python_tests = [p for p in files if
            (Path(p).name.startswith("test_") and p.endswith(".py")) or p.endswith("_test.py")
            or (Path(p).parts[0] in {"tests", "test"} and p.endswith(".py"))]
        python_markers = {"pyproject.toml", "setup.py", "setup.cfg", "tox.ini", "pytest.ini"}
        if python_markers.intersection(file_set) or python_tests:
            config_text = ""
            if "pyproject.toml" in file_set:
                try:
                    config_text = self.workspace.read_text("pyproject.toml", max_chars=50000).casefold()
                except (OSError, WorkspaceError):
                    pass
            uses_pytest = "pytest.ini" in file_set or "conftest.py" in file_set or "[tool.pytest" in config_text or "pytest" in config_text
            command = ("pytest", "-q") if uses_pytest else (("python", "-m", "unittest", "discover", "-s", "tests", "-v") if any(p.startswith("tests/") for p in files) else (("python", "-m", "unittest", "discover", "-s", "test", "-v") if any(p.startswith("test/") for p in files) else ("python", "-m", "unittest", "discover", "-v")))
            related = self._related(changed, python_tests)
            profiles.append(TestProfile("python", command, "high" if python_tests else "medium",
                "Python project markers and test files detected." if python_tests else "Python project marker detected; no test files were found.",
                tuple(python_tests), tuple(related or (python_tests if not changed else ()))))

        package = None
        if "package.json" in file_set:
            try:
                package = json.loads(self.workspace.read_text("package.json", max_chars=100000))
            except (ValueError, OSError, WorkspaceError):
                package = None
        if isinstance(package, dict):
            scripts = package.get("scripts", {})
            js_tests = [p for p in files if any(token in Path(p).name.casefold() for token in (".test.", ".spec."))
                        or Path(p).name.casefold() in {"jest.config.js", "jest.config.ts", "vitest.config.js", "vitest.config.ts"}]
            if isinstance(scripts, dict) and isinstance(scripts.get("test"), str):
                related = self._related(changed, js_tests)
                profiles.append(TestProfile("javascript/typescript", ("npm", "test"), "high" if js_tests else "medium",
                    "package.json defines a test script.", tuple(js_tests),
                    tuple(related or (js_tests if not changed else ()))))

        if "Cargo.toml" in file_set:
            rust_tests = [p for p in files if p.endswith(".rs")]
            related = self._related(changed, rust_tests)
            profiles.append(TestProfile("rust", ("cargo", "test"), "high",
                "Cargo.toml detected; cargo test is the standard project test command.",
                tuple(rust_tests), tuple(related or (rust_tests if not changed else ()))))

        if "go.mod" in file_set:
            go_tests = [p for p in files if p.endswith("_test.go")]
            related = self._related(changed, go_tests)
            profiles.append(TestProfile("go", ("go", "test", "./..."), "high" if go_tests else "medium",
                "go.mod detected; Go test files use the _test.go suffix.", tuple(go_tests),
                tuple(related or (go_tests if not changed else ()))))

        if "pom.xml" in file_set:
            java_tests = [p for p in files if p.startswith("src/test/") and p.endswith(".java")]
            related = self._related(changed, java_tests)
            profiles.append(TestProfile("java/maven", ("mvn", "test"), "high" if java_tests else "medium",
                "Maven project marker detected.", tuple(java_tests),
                tuple(related or (java_tests if not changed else ()))))

        if any(p in file_set for p in ("build.gradle", "build.gradle.kts", "gradlew")):
            gradle_tests = [p for p in files if p.startswith("src/test/")]
            command = ("./gradlew", "test") if "gradlew" in file_set else ("gradle", "test")
            related = self._related(changed, gradle_tests)
            profiles.append(TestProfile("java/gradle", command, "high" if gradle_tests else "medium",
                "Gradle project marker detected.", tuple(gradle_tests),
                tuple(related or (gradle_tests if not changed else ()))))

        if any(p.endswith(".csproj") or p.endswith(".sln") for p in files):
            dotnet_tests = [p for p in files if p.endswith("Tests.cs") or p.endswith("Test.cs")]
            related = self._related(changed, dotnet_tests)
            profiles.append(TestProfile("dotnet", ("dotnet", "test"), "high" if dotnet_tests else "medium",
                ".NET project or solution detected.", tuple(dotnet_tests),
                tuple(related or (dotnet_tests if not changed else ()))))

        return {"workspace": str(self.workspace.root), "changed_paths": changed,
                "execution_performed": False, "profiles": [{"language": p.language, "command": list(p.command), "confidence": p.confidence, "reason": p.reason, "test_files": list(p.test_files), "related_tests": list(p.related_tests)} for p in profiles],
                "notes": ["Discovery is read-only; no test command was executed.",
                          "Run tests only through the approval-gated command tool.",
                          "Some suggested commands require an explicit policy allowlist entry."]}
