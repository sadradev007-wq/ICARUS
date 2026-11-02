from .workspace import Workspace

class ProjectMemory:
    def __init__(self, workspace: Workspace):
        self.workspace = workspace
        self.path = ".icarus/memory.md"
        target = workspace.resolve(self.path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_text("# Project memory\n\nStore durable, user-approved project facts here. Never store secrets.\n", encoding="utf-8")

    def read(self, limit: int = 12000) -> str:
        return self.workspace.read_text(self.path, limit)

    def append(self, note: str) -> None:
        target = self.workspace.resolve(self.path)
        with target.open("a", encoding="utf-8") as stream:
            stream.write("\n- " + note.replace("\n", " ").strip() + "\n")
