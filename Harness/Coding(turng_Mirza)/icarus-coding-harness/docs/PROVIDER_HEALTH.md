# Four-route provider health

The Coding Harness can inspect the Personal Companion provider configuration without enabling any agent runtime. Inference remains disabled unless the operator supplies the explicit opt-in flag described below.

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

The default aggregate report is icarus.provider-health.v1 and is described by schemas/provider-health.v1.schema.json. A route can be ok, warning, error, or skipped. A missing advertised model is a warning because some OpenAI-compatible servers expose incomplete model lists. Configuration-level failures return an empty routes object; after a valid configuration is loaded, all four route entries are present, including disabled routes marked skipped.

## Explicit local inference probe

The operator may explicitly request a bounded inference smoke test:

    icarus-harness doctor --providers-config "Harness/Tools/Personal Companion/config/providers.local.json" --probe-local-inference

This switches the report to icarus.provider-health.v2:

- Only enabled routes with kind local are eligible.
- The configured model must first appear in GET /models.
- The endpoint hostname must be localhost or a loopback IP, including when HTTPS is used.
- Exactly one POST /chat/completions is sent per eligible route.
- The request contains one fixed, non-sensitive user message, no tools, temperature 0, max_tokens 16, and stream false.
- Redirects are not followed; response bodies are capped at 1 MiB.
- API routes, disabled routes, and local routes whose model is not listed are marked skipped.
- The response text is not copied into the report or any data store.

This option verifies that a compatible endpoint returned a non-empty assistant message. It does not exercise tool calling, Task Companion, the Coding Harness agent loop, or real task execution.

## Explicit limitations

The diagnostic does not change provider configuration, instantiate AgentRuntime, write Task Companion feedback, or create Local LLM task records. The Coding Harness agent kill switch remains closed. The opt-in probe is a transport smoke test only; a full approved runtime integration test remains a separate architecture step.
