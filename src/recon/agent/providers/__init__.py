"""Model providers. Every provider returns the same AgentVerdict shape.

`policy` needs nothing at all. `anthropic` needs the SDK and an API key, and
is only constructed when it is actually selected.
"""

from __future__ import annotations

from recon.agent.provider import ExceptionResolver
from recon.agent.providers.deterministic import DeterministicPolicy

RESOLVER_NAMES = ("policy", "anthropic")


def build_resolver(name: str, model: str | None = None) -> ExceptionResolver:
    """Construct a resolver by name, deferring every optional import."""
    if name == "policy":
        return DeterministicPolicy()
    if name == "anthropic":
        from recon.agent.providers.anthropic_resolver import (
            DEFAULT_MODEL,
            AnthropicResolver,
        )

        return AnthropicResolver(model=model or DEFAULT_MODEL)
    raise ValueError(f"unknown resolver {name!r}; choose from {RESOLVER_NAMES}")
