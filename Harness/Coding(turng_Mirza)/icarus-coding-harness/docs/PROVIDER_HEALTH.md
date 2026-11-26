# Four-route provider health

The Coding Harness can inspect the Personal Companion provider configuration without enabling any agent runtime. Inference is disabled by default and requires the explicit opt-in flag below.

## Command

Run from the repository root after installing the Coding Harness package:

    icarus-harness doctor --providers-config "Harness/Tools/Personal Companion/config/providers.local.json" \
      --output ~/.local/share/icarus/provider-health.json

The local configuration is created by copying providers.example.json and remains ignored by Git. API keys must be supplied through the environment variables named by each API route's api_key_env field.

## Checks

- The configuration must use icarus.llm-providers.v1 and declare all four route names.
- Every route's enabled flag, kind, model, base URL, timeout, and optional credential-variable name are checked before network access.
- Routing selectors must refer to one of the four routes.
- Safety metadata must preserve the code-owned invariants: legacy agents disabled, tool execution policy-gated, provider configuration unable to grant permissions, AI planning requiring user approval, and calendar planning requiring explicit availability. chat_only_initially remains descriptive rollout metadata, not an authorization switch.
- Disabled routes are reported as skipped and are not contacted.
- Enabled API routes require a non-empty environment credential. Local routes use their configured key-variable name or the existing ICARUS_API_KEY/local fallback.
- Each enabled route is checked with the existing bounded GET /models transport. Redirects are not followed; non-loopback HTTP is rejected; endpoint paths and credential values are not returned.

The aggregate report is icarus.provider-health.v1 and is described by schemas/provider-health.v1.schema.json. A route can be ok, warning, error, or skipped. A missing advertised model is a warning because some OpenAI-compatible servers expose incomplete model lists. Configuration-level failures return an empty routes object; after a valid configuration is loaded, all four route entries are present, including disabled routes marked skipped.

## Explicit limitations

This is a read-only connectivity and model-list diagnostic. It does not send Chat Completions requests, prove inference compatibility, change provider configuration, instantiate AgentRuntime, write Task Companion feedback, or create Local LLM task records. The Coding Harness agent kill switch remains closed. A separately approved smoke test against an installed local model server is still required before claiming real inference works.

## Saved report handoff

Use `--output PATH` to save the JSON report without shell redirection. The
parent directory must already exist. The file is written atomically with
mode `0600` on POSIX systems; a failed write leaves the previous report
unchanged. A diagnostic result whose status is `error` is still a valid
report and is saved before the CLI exits with code 2.

Task Companion reads the saved file only. Its projection v2 reports
`fresh`, `stale`, or `unknown` based on the file modification time, with
a 24-hour freshness window. Projection v1 remains available unchanged.


## Explicit local inference probe

The operator may explicitly request a bounded inference smoke test:

    icarus-harness doctor --providers-config "Harness/Tools/Personal Companion/config/providers.local.json" \
      --probe-local-inference --output ~/.local/share/icarus/provider-health.json

This switches the saved report to `icarus.provider-health.v2`:

- Only enabled routes with `kind: local` are eligible for inference.
- The configured model must first appear in the bounded `GET /models` response.
- The Chat Completions host must be `localhost` or a loopback IP, including when HTTPS is used.
- Exactly one `POST /chat/completions` is sent per eligible route.
- The request contains one fixed, non-sensitive user message, no tools, temperature 0, max_tokens 16, and stream false.
- Redirects are not followed; response bodies are capped at 1 MiB.
- API routes, disabled routes, and local routes whose model is not listed are marked skipped.
- The assistant response text is not copied into the report or any data store.

The Task Companion reader accepts the v2 report and projects only the probe status. It does not expose the model response, model name, endpoint, credentials, or diagnostic messages. Its projection v2 also reports report-file freshness. The probe remains a diagnostic, not a Coding Harness task run.

This option verifies only that a compatible endpoint returned a non-empty assistant message. It does not exercise tool calling, Task Companion execution, the Coding Harness agent loop, or real task execution. The AgentRuntime kill switch remains closed.
