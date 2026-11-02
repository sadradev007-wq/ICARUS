from dataclasses import dataclass

@dataclass
class RunResult:
    status: str
    summary: str
    steps: int
    transcript: list[dict[str, str]]
