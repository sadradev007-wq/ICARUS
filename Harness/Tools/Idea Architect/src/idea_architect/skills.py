"""Skill discovery and quarantine registry.

Discovery is optional and network-dependent. Skill installation never executes third-party
code: candidates are recorded for human review and sandbox testing first.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class SkillCandidate:
    name: str
    repository: str
    url: str
    description: str
    stars: int
    discovered_at: str
    status: str = "quarantined"


class GitHubSkillDiscovery:
    def __init__(self, token: str | None = None, timeout: int = 10):
        self.token, self.timeout = token, timeout

    def search(self, query: str, limit: int = 10) -> list[SkillCandidate]:
        params = urllib.parse.urlencode({"q": query, "sort": "stars", "order": "desc", "per_page": min(limit, 30)})
        request = urllib.request.Request(
            "https://api.github.com/search/repositories?" + params,
            headers={"Accept": "application/vnd.github+json", "User-Agent": "ICARUS-Idea-Architect"}
        )
        if self.token:
            request.add_header("Authorization", "Bearer " + self.token)
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
        now = datetime.now(timezone.utc).isoformat()
        return [SkillCandidate(
            name=item["name"], repository=item["full_name"], url=item["html_url"],
            description=item.get("description") or "", stars=int(item.get("stargazers_count", 0)),
            discovered_at=now
        ) for item in data.get("items", [])]


class SkillRegistry:
    def __init__(self, root: Path):
        self.root = root
        self.quarantine = root / "quarantine"
        self.registry_file = root / "registry.json"
        self.quarantine.mkdir(parents=True, exist_ok=True)
        if not self.registry_file.exists():
            self._save([])

    def _load(self) -> list[dict[str, Any]]:
        return json.loads(self.registry_file.read_text(encoding="utf-8"))

    def _save(self, items: list[dict[str, Any]]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        temp = self.registry_file.with_suffix(".tmp")
        temp.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp.replace(self.registry_file)

    def add_candidate(self, candidate: SkillCandidate) -> Path:
        items = self._load()
        if any(x["repository"] == candidate.repository for x in items):
            raise ValueError("This skill repository is already registered")
        items.append(asdict(candidate))
        self._save(items)
        folder = self.quarantine / candidate.repository.replace("/", "__")
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "CANDIDATE.json").write_text(
            json.dumps(asdict(candidate), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return folder

    def list_candidates(self) -> list[dict[str, Any]]:
        return self._load()
