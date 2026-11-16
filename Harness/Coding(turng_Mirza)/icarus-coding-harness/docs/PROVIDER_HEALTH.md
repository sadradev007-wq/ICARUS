# Four-route provider health

The Coding Harness can inspect the Personal Companion provider configuration without enabling any agent runtime.

## Command

Run from the repository root after installing the Coding Harness package:

    icarus-harness doctor --providers-config "Harness/Tools/Personal Companion/config/providers.local.json"

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
