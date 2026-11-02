from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Ecosystem:
    language: str
    manager: str
    manifests: tuple[str, ...]
    lockfiles: tuple[str, ...]
    install_command: tuple[str, ...]
    test_command: tuple[str, ...]


# Ecosystem metadata only; third-party packages are not vendored into ICARUS.
ECOSYSTEMS: tuple[Ecosystem, ...] = (
    Ecosystem("javascript/typescript", "pnpm", ("package.json",), ("pnpm-lock.yaml",), ("pnpm", "install", "--frozen-lockfile"), ("pnpm", "test")),
    Ecosystem("python", "uv", ("pyproject.toml", "requirements.txt", "setup.py", "setup.cfg"), ("uv.lock",), ("uv", "sync", "--frozen"), ("uv", "run", "pytest", "-q")),
    Ecosystem("rust", "cargo", ("Cargo.toml",), ("Cargo.lock",), ("cargo", "fetch", "--locked"), ("cargo", "test")),
    Ecosystem("go", "go modules", ("go.mod",), ("go.sum",), ("go", "mod", "download"), ("go", "test", "./...")),
    Ecosystem("java", "maven", ("pom.xml",), ("pom.xml",), ("mvn", "-B", "dependency:go-offline"), ("mvn", "test")),
    Ecosystem("java/kotlin/scala", "gradle", ("build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts"), ("gradle.lockfile",), ("gradle", "dependencies"), ("gradle", "test")),
    Ecosystem("dotnet", "NuGet/dotnet", (".csproj", ".fsproj", ".vbproj", ".sln"), ("packages.lock.json",), ("dotnet", "restore", "--locked-mode"), ("dotnet", "test")),
    Ecosystem("php", "Composer", ("composer.json",), ("composer.lock",), ("composer", "install", "--no-interaction", "--prefer-dist"), ("composer", "test")),
    Ecosystem("ruby", "Bundler", ("Gemfile",), ("Gemfile.lock",), ("bundle", "install", "--frozen"), ("bundle", "exec", "rake", "test")),
    Ecosystem("dart/flutter", "Pub", ("pubspec.yaml",), ("pubspec.lock",), ("dart", "pub", "get"), ("dart", "test")),
    Ecosystem("swift", "Swift Package Manager", ("Package.swift",), ("Package.resolved",), ("swift", "package", "resolve"), ("swift", "test")),
    Ecosystem("c/c++", "CMake", ("CMakeLists.txt",), ("CMakeCache.txt",), ("cmake", "-S", ".", "-B", "build"), ("ctest", "--test-dir", "build")),
    Ecosystem("c/c++", "Conan", ("conanfile.py", "conanfile.txt"), ("conan.lock",), ("conan", "install", "."), ("ctest", "--test-dir", "build")),
    Ecosystem("elixir", "Mix", ("mix.exs",), ("mix.lock",), ("mix", "deps.get"), ("mix", "test")),
    Ecosystem("haskell", "Cabal", ("*.cabal", "cabal.project"), ("cabal.project.freeze",), ("cabal", "update"), ("cabal", "test")),
    Ecosystem("haskell", "Stack", ("stack.yaml",), ("stack.yaml.lock",), ("stack", "setup"), ("stack", "test")),
    Ecosystem("r", "renv", ("renv.lock", "DESCRIPTION"), ("renv.lock",), ("Rscript", "-e", "renv::restore()"), ("Rscript", "-e", "devtools::test()")),
)


def _matches(path: str, marker: str) -> bool:
    if marker.startswith("*."):
        return path.endswith(marker[1:])
    return path == marker or path.endswith("/" + marker)


def discover_ecosystems(files: list[str]) -> list[dict]:
    found: list[dict] = []
    for item in ECOSYSTEMS:
        manifests = [p for p in files if any(_matches(p, m) for m in item.manifests)]
        if not manifests:
            continue
        locks = [p for p in files if any(_matches(p, m) for m in item.lockfiles)]
        record = asdict(item)
        record["install_command"] = list(item.install_command)
        record["test_command"] = list(item.test_command)
        record["manifests"] = manifests
        record["lockfiles"] = locks
        found.append(record)
    return found
