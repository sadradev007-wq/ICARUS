"""Hard kill switch for the Coding Harness agent runtime.

This is intentionally code-controlled (not environment/config overridable) so a
workspace setting cannot accidentally reactivate an agent during quarantine.
"""
AGENTS_ENABLED = False


def require_agent_runtime_enabled() -> None:
    if not AGENTS_ENABLED:
        raise RuntimeError(
            "ICARUS Coding Harness agent is quarantined: model calls and tool execution "
            "are disabled until the next approved architecture phase."
        )
