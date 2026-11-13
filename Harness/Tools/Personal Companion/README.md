# ICARUS Personal Companion foundation

This package provides the local-first Personal Companion UI and its approval-first AI planning API.

## Taxonomy

data/taxonomy.fa.json contains exactly 50 main domains and 20 subtopics per domain (1,000 subtopics total). The taxonomy is versioned and validated by schemas/taxonomy.v1.schema.json.

## AI planning API

Run from this directory:

```bash
python -m icarus_personal_companion.server
```

The local server binds to 127.0.0.1:4173 by default and serves both the UI and API. It provides:

- GET /api/taxonomy — taxonomy data.
- POST /api/ai/classify — propose a category/subcategory for a user item.
- POST /api/ai/calendar — propose a schedule for supplied tasks and explicit free-time windows.
- POST /api/audit/approval — record approval or rejection for a server-issued `proposal_id`; IDs expire after 15 minutes and can be decided only once.

The four model routes are configured through config/providers.local.json (copy from config/providers.example.json). Create the local file with `cp config/providers.example.json config/providers.local.json`; it is ignored by Git. API keys are environment variables only. The local routes use OpenAI-compatible endpoints; Ollama's OpenAI-compatible API is the default local endpoint.

## Safety and data boundaries

AI endpoints produce proposals only. Every proposal receives an opaque `proposal_id`; its approval or rejection must present the matching server-issued ID, action, route, and model. The ID expires after 15 minutes and is consumed by the first decision. Proposal and decision action-journal records share that ID. Category assignments and calendar events are not applied until the user explicitly approves them. Calendar proposals are checked server-side to ensure every event is within a supplied availability window, has an offset-aware ISO-8601 time, references an input task, and does not overlap another proposed event.

AI proposals and user approvals are recorded by ActionJournal as privacy-bounded JSON under Local LLM/Train Data/events/YYYY/MM/. The journal stores bounded summaries and metadata, not raw prompts, tool arguments, file contents, or secrets. Approved task/event data currently lives in browser localStorage; persistent TaskStore, Vikunja, CalDAV and Google Calendar integration remain future work.

The legacy Idea Architect and Coding Harness agent runtimes remain quarantined. These endpoints do not enable legacy agents or tool execution.

## Development

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
```

UI checks (from ui/):

```bash
corepack pnpm test
corepack pnpm check
```