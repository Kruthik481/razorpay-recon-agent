"""What the reconciliation system knows about how money is deducted.

This is the only mutable-in-spirit part of the system, and even here every
change produces a new object. It starts almost empty: one fee rate on file and
no tolerances. Day 3 grows it from human-confirmed exceptions, and the matcher
and the agent both read from it, so learning one fact makes both cheaper.
"""

from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True, slots=True)
class LearnedFact:
    """A single promoted fact, with the evidence that justified promoting it."""

    kind: str
    value: int
    support: int
    source_case_refs: tuple[str, ...]
    note: str


@dataclass(frozen=True, slots=True)
class Knowledge:
    """Rates and tolerances the system is willing to apply without asking."""

    fee_bps_on_file: tuple[int, ...] = (200,)
    fx_tolerance_paise: int = 0
    flat_bank_charges_paise: tuple[int, ...] = ()
    facts: tuple[LearnedFact, ...] = ()

    def with_fee_rate(self, bps: int, fact: LearnedFact) -> Knowledge:
        if bps in self.fee_bps_on_file:
            return self
        return replace(
            self,
            fee_bps_on_file=tuple(sorted({*self.fee_bps_on_file, bps})),
            facts=(*self.facts, fact),
        )

    def with_fx_tolerance(self, paise: int, fact: LearnedFact) -> Knowledge:
        if paise <= self.fx_tolerance_paise:
            return self
        return replace(self, fx_tolerance_paise=paise, facts=(*self.facts, fact))

    def with_flat_charge(self, paise: int, fact: LearnedFact) -> Knowledge:
        if paise in self.flat_bank_charges_paise:
            return self
        return replace(
            self,
            flat_bank_charges_paise=tuple(sorted({*self.flat_bank_charges_paise, paise})),
            facts=(*self.facts, fact),
        )


BASELINE = Knowledge()
