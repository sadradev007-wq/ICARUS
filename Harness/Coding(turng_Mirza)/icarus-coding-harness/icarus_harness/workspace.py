from pathlib import Path

class WorkspaceError(ValueError):
    pass

class Workspace:
    def __init__(self, root: Path):
        self.root = root.expanduser().resolve()
        if not self.root.exists() or not self.root.is_dir():
            raise WorkspaceError(f"Workspace is not a directory: {self.root}")

    def resolve(self, relative: str) -> Path:
        candidate = (self.root / relative).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise WorkspaceError("Path escapes the selected workspace") from exc
        return candidate

    def list_files(self, relative: str = ".", limit: int = 200) -> list[str]:
        base = self.resolve(relative)
        if not base.is_dir():
            raise WorkspaceError("Requested path is not a directory")
        ignored = {".git", ".venv", "venv", "node_modules", "__pycache__", ".icarus"}
        found = []
        for path in sorted(base.rglob("*")):
            if any(part in ignored for part in path.parts):
                continue
            if path.is_file():
                found.append(path.relative_to(self.root).as_posix())
                if len(found) >= limit:
                    break
        return found

    def read_text(self, relative: str, max_chars: int = 20000) -> str:
        path = self.resolve(relative)
        if not path.is_file():
            raise WorkspaceError("File does not exist")
        return path.read_text(encoding="utf-8", errors="replace")[:max_chars]

    def write_text(self, relative: str, content: str) -> str:
        path = self.resolve(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path.relative_to(self.root).as_posix()

    def search(self, query: str, limit: int = 30) -> list[str]:
        matches = []
        for name in self.list_files(limit=1000):
            try:
                lines = self.resolve(name).read_text(encoding="utf-8", errors="replace").splitlines()
                for number, line in enumerate(lines, 1):
                    if query.casefold() in line.casefold():
                        matches.append(f"{name}:{number}: {line[:240]}")
                        if len(matches) >= limit:
                            return matches
            except OSError:
                continue
        return matches
