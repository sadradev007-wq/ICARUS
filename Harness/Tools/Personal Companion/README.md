# ICARUS Personal Companion foundation

This package is the first executable component of the new local-first Personal Companion.

## Action journal

`icarus_personal_companion.action_journal.ActionJournal` writes one immutable JSON file for each meaningful action under:

`Local LLM/Train Data/events/YYYY/MM/A-<event-id>.json`

The writer uses atomic file creation, restrictive permissions, directory descriptors, and no-follow checks. It records bounded, credential-redacted summaries; it never records raw prompts, file contents, tool arguments, environment variables, or hidden chain-of-thought. Capture can be disabled by passing `enabled=False`.

## Development

Use Python 3.10+ and the standard library:

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
```

The four-provider configuration, permission policy, event schema, and integration decisions are documented in this directory. Chat, memory CRUD, calendar UI, and provider network adapters are intentionally separate follow-up increments.
