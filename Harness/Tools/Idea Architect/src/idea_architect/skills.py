"""Skill discovery and human-reviewed activation registry.

A repository is never imported or executed merely because it was discovered. Approval binds
a reviewed repository record to an already trusted host handler ID.
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .execution import HandlerRegistry


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
        if not query.strip():
            raise ValueError("query cannot be empty")
        params = urllib.parse.urlencode({
            "q": query, "sort": "stars", "order": "desc",
            "per_page": max(1, min(limit, 30))
        })
        request = urllib.request.Request(
            "https://api.github.com/search/repositories?" + params,
            headers={"Accept": "application/vnd.github+json",
                     "User-Agent": "ICARUS-Idea-Architect"}
        )
        if self.token:
            request.add_header("Authorization", "Bearer " + self.token)
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
        now = datetime.now(timezone.utc).isoformat()
        return [SkillCandidate(
            name=item["name"], repository=item["full_name"], url=item["html_url"],
            description=item.get("description") or "",
            stars=int(item.get("stargazers_count", 0)), discovered_at=now
        ) for item in data.get("items", [])]


class SkillRegistry:
    """Quarantine registry; activation only maps reviewed skills to trusted host handlers."""
    def __init__(self, root: Path):
        self.root = Path(root)
        self.quarantine = self.root / "quarantine"
        self.registry_file = self.root / "registry.json"
        self.quarantine.mkdir(parents=True, exist_ok=True)
        if not self.registry_file.exists():
            self._save([])

    def _load(self) -> list[dict[str, Any]]:
        data = json.loads(self.registry_file.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError("Skill registry must be a JSON array")
        return data

    def _save(self, items: list[dict[str, Any]]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        temp = self.registry_file.with_suffix(".tmp")
        temp.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp.replace(self.registry_file)

    @staticmethod
    def _folder_name(repository: str) -> str:
        return repository.replace("/", "__").replace("..", "_")

    def add_candidate(self, candidate: SkillCandidate) -> Path:
        if not candidate.repository or "/" not in candidate.repository:
            raise ValueError("repository must be in owner/name form")
        items = self._load()
        if any(x.get("repository") == candidate.repository for x in items):
            raise ValueError("This skill repository is already registered")
        record = asdict(candidate)
        items.append(record)
        self._save(items)
        folder = self.quarantine / self._folder_name(candidate.repository)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "CANDIDATE.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return folder

    def approve_candidate(
        self, repository: str, *, handler_id: str, approved_by: str,
        review_digest: str
    ) -> dict[str, Any]:
        """Approve metadata only; handler must separately exist in the host allow-list."""
        if not approved_by.strip() or not review_digest.strip() or not handler_id.strip():
            raise ValueError("approved_by, review_digest and handler_id are required")
        items = self._load()
        matches = [x for x in items if x.get("repository") == repository]
        if len(matches) != 1:
            raise KeyError(f"Unknown or duplicate skill repository: {repository}")
        record = matches[0]
        if record.get("status") != "quarantined":
            raise ValueError(f"Skill cannot be approved from status {record.get('status')}")
        record.update({
            "status": "approved", "handler_id": handler_id,
            "approved_by": approved_by, "approved_at": datetime.now(timezone.utc).isoformat(),
            "review_digest": review_digest
        })
        self._save(items)
        folder = self.quarantine / self._folder_name(repository)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "CANDIDATE.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return record

    def bind_approved(self, handlers: HandlerRegistry) -> list[str]:
        """Bind approved records only when their handler IDs are already allow-listed."""
        bound: list[str] = []
        for record in self._load():
            if record.get("status") != "approved":
                continue
            handler_id = record.get("handler_id")
            if not isinstance(handler_id, str) or not handler_id:
                continue
            handlers.get(handler_id)
            bound.append(record["repository"])
        return bound

    def list_candidates(self) -> list[dict[str, Any]]:
        return self._load()
