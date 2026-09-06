"""Token and money accounting for the model path.

An agent that resolves exceptions but costs more than the analyst it replaces
is not a product. Cost is measured per case and per thousand ledger lines, so
the comparison against a human queue is direct.
"""

from __future__ import annotations

from dataclasses import dataclass

# USD per million tokens, list price at time of writing. Overridable per run
# so the numbers in a report can be reproduced against a specific price sheet.
PRICING_USD_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-opus-5": (15.00, 75.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-haiku-4-5-20251001": (1.00, 5.00),
}

MILLION = 1_000_000


@dataclass(frozen=True, slots=True)
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0

    def __add__(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cached_input_tokens=self.cached_input_tokens + other.cached_input_tokens,
        )

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens + self.cached_input_tokens


@dataclass(frozen=True, slots=True)
class CostReport:
    model: str
    usage: TokenUsage
    cases_resolved: int
    ledger_lines: int
    wall_ms: int

    @property
    def usd(self) -> float:
        return usd_cost(self.model, self.usage)

    @property
    def usd_per_case(self) -> float:
        return self.usd / self.cases_resolved if self.cases_resolved else 0.0

    @property
    def usd_per_thousand_lines(self) -> float:
        if not self.ledger_lines:
            return 0.0
        return self.usd * 1_000 / self.ledger_lines

    @property
    def ms_per_case(self) -> float:
        return self.wall_ms / self.cases_resolved if self.cases_resolved else 0.0


def usd_cost(model: str, usage: TokenUsage) -> float:
    """Price a run. An unknown model prices at zero rather than guessing."""
    rates = PRICING_USD_PER_MTOK.get(model)
    if rates is None:
        return 0.0
    input_rate, output_rate = rates
    # Cache reads are billed at a tenth of the input rate.
    return (
        usage.input_tokens * input_rate
        + usage.cached_input_tokens * input_rate * 0.1
        + usage.output_tokens * output_rate
    ) / MILLION
