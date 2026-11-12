# ICARUS Personal Companion UI

A Persian RTL interface for the local-first Personal Companion.

## Views

- دستیار: chat-first workspace (free chat still needs its separate adapter).
- کارها: task list grouped by the 50-domain taxonomy.
- تقویم: AI-assisted scheduling proposals and locally stored, user-approved events.
- Memory, library, four provider routes, activity, and settings.

## Run the integrated local app

From Harness/Tools/Personal Companion (the package root), run:

```bash
python -m icarus_personal_companion.server
```

Then open http://127.0.0.1:4173. The Python server serves the UI and its local API together; python -m http.server is not sufficient for AI features.

Run UI checks from ui/:

```bash
corepack pnpm test
corepack pnpm check
```

## AI configuration

The taxonomy classifier defaults to system1_local; calendar planning defaults to system2_local. The server reads config/providers.local.json when present, otherwise config/providers.example.json. Copy the example file to providers.local.json and adjust model URLs/names and enabled flags. API keys must be supplied only through environment variables named by api_key_env; never commit keys.

Four routes are supported: system1_local, system1_api, system2_local, and system2_api. The example enables the two local routes. API routes are disabled until explicitly enabled and configured.

## Approval and persistence boundaries

- AI classification only proposes a category/subcategory; a user click is required before the task is saved.
- Calendar planning requires explicit availability windows and timezone. The server rejects events outside those windows and overlapping proposals.
- AI calendar proposals are not saved until the user explicitly approves them. Approved tasks/events currently persist in browser localStorage; Vikunja, CalDAV, and Google Calendar sync are not connected yet.
- AI proposal and approval metadata is written to privacy-bounded JSON action events under Local LLM/Train Data/events/. Raw prompts, tool arguments, file contents, and secrets are not journaled.
- The legacy Idea Architect and Coding Harness agents remain quarantined. These bounded planning endpoints do not unlock their tool execution.
- The free-form chat still uses a placeholder response and is not connected to the model API.