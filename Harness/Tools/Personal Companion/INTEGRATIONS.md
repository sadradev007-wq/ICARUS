# Personal Companion integrations

## Vikunja

Repository: https://github.com/go-vikunja/vikunja  
License: GNU AGPL-3.0-only.

Use Vikunja as a separate self-hosted service and connect through its documented REST API and CalDAV interface. Do not vendor its server source into ICARUS in this integration. Keep the existing local TaskStore usable offline and define an adapter boundary so users can select local-only or Vikunja-backed storage.

Initial mapping:
- ICARUS task title/description/priority/status -> Vikunja task fields.
- `due_at` -> `due_date`; optional start/end timestamps map to `start_date`/`end_date`.
- reminders and recurring schedules use native backend capabilities where available.
- project/folder IDs are mapped explicitly; never silently merge unrelated projects.
- sync must be idempotent, record remote IDs, detect conflicts, and require user choice when both sides changed.
- credentials come from an OS secret store or environment variable, never checked-in config or action JSON.

Vikunja's REST API provides the backend surface; CalDAV can expose calendar data to compatible calendar clients. A polished Google Calendar-like ICARUS month/week/day interface remains a separate UI implementation and must be validated against the chosen Vikunja release.

## abe-winter/vik

Repository: https://github.com/abe-winter/vik  
Description: Vikunja CLI client intended for agents.

The repository metadata currently reports no license and its root does not contain a LICENSE file. Therefore ICARUS must not copy, vendor, or redistribute its source without permission or a clear license. The public API notes are useful for understanding endpoint shapes, but the ICARUS adapter should independently implement only the documented HTTP contract. Recheck license and maintenance status before reconsidering code reuse.

## Attribution and dependency policy

Keep third-party projects as external services or declared dependencies where legally permitted. Do not copy source into ICARUS merely because it is public on GitHub. Record project name, source URL, version/commit, license, and local modifications for every adopted dependency.
