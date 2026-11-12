# ICARUS Personal Companion UI

A responsive Persian RTL GUI prototype for the Personal Companion.

## Views

- Chat-first home with suggested actions and today's focus.
- Tasks list and task creation modal.
- Weekly calendar projection.
- User-visible, editable-memory concept.
- Folder-oriented workspace library.
- Four independent LLM provider cards.
- JSON action journal / activity feed.
- Privacy, permissions, and quarantine settings.

## Run locally

No runtime dependencies are required. From this directory:

```bash
python3 -m http.server 4173
```

Then open `http://127.0.0.1:4173`.

Use pnpm for project scripts:

```bash
pnpm test
pnpm check
```

## Prototype boundary

This is a frontend prototype, not yet connected to the Python TaskStore, chat service, memory store, Vikunja, calendar backend, or LLM provider adapters. New tasks are stored only in browser localStorage and are explicitly labeled as local prototype drafts. Chat replies are illustrative placeholders. No AI tools or legacy agents execute from this UI.

The GUI is intentionally chat-first, with a stable left-to-right application shell in desktop layout, RTL Persian content, compact global navigation, visible quarantine status, and a responsive bottom navigation on mobile. The full backend integration is a separate implementation step.
