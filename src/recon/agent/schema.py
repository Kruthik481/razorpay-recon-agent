"""The contract between the model and the ledger.

Everything the agent is allowed to assert lives in this module. A verdict is
a *proposal*: it carries the records it claims belong together, the money it
could not explain, and the evidence it used. Nothing here is trusted — the
verifier in `recon.agent.verify` recomputes every number before the gate in
`recon.agent.gate` decides what may be applied automatically.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from recon.domain.break_types import BreakType


class ProposedAction(StrEnum):
    """What the agent wants done with the records it examined."""

    LINK = "link"
    FLAG_MISSING_CREDIT = "flag_missing_credit"
    FLAG_UNIDENTIFIED_CREDIT = "flag_unidentified_credit"
    NO_ACTION = "no_action"


class ResidualReason(StrEnum):
    """Why a proposed link does not tie out to zero.

    An unexplained residual can never be auto-applied, however confident the
    model claims to be: unexplained money is the definition of a break.
    """

    NONE = "none"
    FEE_RATE_VARIANCE = "fee_rate_variance"
    FX_ROUNDING = "fx_rounding"
    FLAT_BANK_CHARGE = "flat_bank_charge"
    UNRECONCILED_FUNDS = "unreconciled_funds"
    UNEXPLAINED = "unexplained"


class Disposition(StrEnum):
    """What the confidence gate decided to do with a verdict."""

    AUTO_APPLY = "auto_apply"
    NEEDS_REVIEW = "needs_review"
    ESCALATE = "escalate"


@dataclass(frozen=True, slots=True)
class Evidence:
    """One citation. `ref` must name a real record or a real tool call."""

    kind: str
    ref: str
    detail: str


@dataclass(frozen=True, slots=True)
class AgentVerdict:
    """The agent's answer for one exception case."""

    case_ref: str
    action: ProposedAction
    break_type: BreakType | None
    settlement_row_ids: frozenset[str]
    bank_txn_ids: frozenset[str]
    residual_paise: int
    residual_reason: ResidualReason
    confidence: float
    rationale: str
    evidence: tuple[Evidence, ...] = ()

    @property
    def touches_records(self) -> bool:
        return bool(self.settlement_row_ids or self.bank_txn_ids)


@dataclass(frozen=True, slots=True)
class GatedVerdict:
    """A verdict plus the outcome of verification and gating."""

    verdict: AgentVerdict
    disposition: Disposition
    violations: tuple[str, ...]
    gate_reasons: tuple[str, ...]

    @property
    def is_auto_applied(self) -> bool:
        return self.disposition is Disposition.AUTO_APPLY


def abstention(case_ref: str, reason: str) -> AgentVerdict:
    """The safe answer when nothing can be asserted."""
    return AgentVerdict(
        case_ref=case_ref,
        action=ProposedAction.NO_ACTION,
        break_type=None,
        settlement_row_ids=frozenset(),
        bank_txn_ids=frozenset(),
        residual_paise=0,
        residual_reason=ResidualReason.UNEXPLAINED,
        confidence=0.0,
        rationale=reason,
    )


def break_type_from_name(name: str | None) -> BreakType | None:
    """Parse a model-supplied break type, tolerating anything unrecognised."""
    if not name:
        return None
    try:
        return BreakType(name.strip().lower())
    except ValueError:
        return None
