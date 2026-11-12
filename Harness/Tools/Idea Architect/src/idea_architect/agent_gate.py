"""Hard kill switch for all Idea Architect agent planning and task execution.

Keep disabled until the next architecture phase explicitly re-enables agents.
Read-only project inspection and visualization remain available.
"""
AGENTS_ENABLED = False


def require_agents_enabled() -> None:
    if not AGENTS_ENABLED:
        raise RuntimeError(
            "ICARUS agents are quarantined: planning and task execution are disabled "
            "until the next approved architecture phase."
        )
