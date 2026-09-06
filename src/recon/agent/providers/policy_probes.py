"""One probe per question the policy knows how to ask.

They run in order, strongest evidence first, and the first one to produce a
verdict wins. A probe that finds two explanations produces nothing: ambiguity
is handed on rather than resolved by picking a side.
"""

from __future__ import annotations

from itertools import combinations

from recon.agent import config, tools
from recon.agent.providers.policy_support import (
    FX_PROBE_PAISE,
    MAX_SPLIT_PARTS,
    Outcome,
    Probe,
    Session,
    cite,
    fee_band,
    link_verdict,
    plausible_sources,
    record_call,
    search_credits,
)
from recon.agent.schema import AgentVerdict, ProposedAction, ResidualReason
from recon.domain.break_types import BreakType
from recon.domain.models import SettlementRowType

# --- probes over cases that carry settlement rows ---------------------------


def probe_anchor_tie_out(session: Session) -> Outcome:
    """Records joined by a shared UTR that already balance as a group.

    Individually ambiguous, collectively certain: the group nets to zero but
    which row paid which credit is undecidable, so this never auto-applies.
    """
    if not session.anchored_txns or not session.rows:
        return None, ()
    args = {
        "amounts_paise": [t.amount_paise for t in session.anchored_txns],
        "target_paise": session.expected_paise,
    }
    result = tools.check_sum(session.ctx, **args)
    call = record_call("check_sum", args, result, f"residual {result['residual_paise']} paise")
    if not result["ties_out"]:
        return None, (call,)
    shared = {r.utr for r in session.rows if r.utr}
    return (
        link_verdict(
            session,
            txn_ids=frozenset(t.bank_txn_id for t in session.anchored_txns),
            break_type=BreakType.DUPLICATE_UTR if len(session.rows) > 1 else None,
            residual=0,
            reason=ResidualReason.NONE,
            confidence=config.CONFIDENCE_COLLECTIVE_TIE_OUT,
            rationale=(
                f"{len(session.rows)} rows and {len(session.anchored_txns)} credits share "
                f"UTR {sorted(shared)} and net to zero as a group; the pairing inside the "
                "group cannot be determined from the data"
            ),
            evidence=cite(
                *(r.settlement_row_id for r in session.rows),
                *(t.bank_txn_id for t in session.anchored_txns),
            ),
        ),
        (call,),
    )


def probe_chargeback_debit(session: Session) -> Outcome:
    """A negative settlement row answered by a debit of the same size."""
    if not any(r.row_type is SettlementRowType.CHARGEBACK for r in session.rows):
        return None, ()
    amount = -session.expected_paise
    date_from, date_to = session.window
    args = {
        "date_from": date_from,
        "date_to": date_to,
        "direction": "debit",
        "min_paise": amount,
        "max_paise": amount,
    }
    hits = tools.find_bank_txns(session.ctx, **args)
    call = record_call("find_bank_txns", args, hits, f"{len(hits)} matching debits")
    if len(hits) != 1:
        return None, (call,)
    return (
        link_verdict(
            session,
            txn_ids=frozenset({hits[0]["bank_txn_id"]}),
            break_type=BreakType.CHARGEBACK_DEBIT,
            residual=0,
            reason=ResidualReason.NONE,
            confidence=config.CONFIDENCE_EXACT_DEBIT,
            rationale=f"sole debit of {amount} paise in the window answers the chargeback",
            evidence=cite(hits[0]["bank_txn_id"]),
        ),
        (call,),
    )


def probe_exact_credit(session: Session) -> Outcome:
    """One credit equal to the group's net. Only reached when the group has parts."""
    expected = session.expected_paise
    if expected <= 0:
        return None, ()
    hits, call = search_credits(session, min_paise=expected, max_paise=expected)
    if len(hits) != 1:
        return None, (call,)
    return (
        link_verdict(
            session,
            txn_ids=frozenset({hits[0]["bank_txn_id"]}),
            break_type=BreakType.REFUND_NETTED if session.has_refund else None,
            residual=0,
            reason=ResidualReason.NONE,
            confidence=config.CONFIDENCE_EXACT_TIE_OUT,
            rationale=(
                f"{len(session.rows)} settlement rows net to {expected} paise, matched by "
                "the sole credit of that amount in the window"
            ),
            evidence=cite(hits[0]["bank_txn_id"]),
        ),
        (call,),
    )


def _unique_split(hits: list[dict], target: int) -> tuple[dict, ...] | None:
    """The one combination of credits that sums to target, if exactly one exists."""
    found = None
    for size in range(2, min(MAX_SPLIT_PARTS, len(hits)) + 1):
        for subset in combinations(hits, size):
            if sum(h["amount_paise"] for h in subset) != target:
                continue
            if found is not None:
                return None
            found = subset
    return found


def probe_split_credits(session: Session) -> Outcome:
    """One settlement paid out in tranches."""
    expected = session.expected_paise
    if expected <= 0:
        return None, ()
    hits, call = search_credits(session, min_paise=1, max_paise=expected - 1)
    subset = _unique_split(hits, expected)
    if subset is None:
        return None, (call,)
    ids = [h["bank_txn_id"] for h in subset]
    return (
        link_verdict(
            session,
            txn_ids=frozenset(ids),
            break_type=BreakType.PARTIAL_SETTLEMENT,
            residual=0,
            reason=ResidualReason.NONE,
            confidence=config.CONFIDENCE_UNIQUE_SPLIT,
            rationale=(
                f"{len(ids)} credits are the only combination in the window summing to "
                f"{expected} paise"
            ),
            evidence=cite(*ids),
        ),
        (call,),
    )


def probe_fee_variance(session: Session) -> Outcome:
    """A single payment settled at some rate other than the one on file.

    Proposed, never applied: the gate refuses any rate the system does not
    already hold, so an unfamiliar rate becomes a question for a human rather
    than a silent repricing of the merchant.
    """
    payments = [r for r in session.rows if r.row_type is SettlementRowType.PAYMENT]
    if len(payments) != 1 or len(session.rows) != 1:
        return None, ()
    gross = payments[0].gross_paise
    low, high = fee_band(gross)
    hits, call = search_credits(session, min_paise=low, max_paise=high)

    calls = (call,)
    explained = []
    for hit in hits:
        args = {"gross_paise": gross, "observed_net_paise": hit["amount_paise"]}
        implied = tools.implied_fee_bps(session.ctx, **args)
        calls += (record_call("implied_fee_bps", args, implied, str(implied)),)
        if implied.get("exact"):
            explained.append((hit, implied["fee_bps"]))

    if len(explained) != 1:
        return None, calls
    hit, bps = explained[0]
    residual = session.expected_paise - hit["amount_paise"]
    on_file = bps in session.ctx.knowledge.fee_bps_on_file
    return (
        link_verdict(
            session,
            txn_ids=frozenset({hit["bank_txn_id"]}),
            break_type=BreakType.NON_STANDARD_FEE,
            residual=residual,
            reason=ResidualReason.FEE_RATE_VARIANCE,
            confidence=(
                config.CONFIDENCE_KNOWN_FEE_RATE
                if on_file
                else config.CONFIDENCE_UNKNOWN_FEE_RATE
            ),
            rationale=(
                f"credit of {hit['amount_paise']} paise is exactly gross {gross} less a "
                f"{bps} bps fee and GST; that rate is "
                f"{'on file' if on_file else 'not on file'}"
            ),
            evidence=cite(hit["bank_txn_id"]),
        ),
        calls,
    )


def probe_small_tolerance(session: Session) -> Outcome:
    """A credit short by a handful of paise: rounding, not a deduction."""
    expected = session.expected_paise
    if expected <= 0:
        return None, ()
    hits, call = search_credits(
        session, min_paise=expected - FX_PROBE_PAISE, max_paise=expected + FX_PROBE_PAISE
    )
    if len(hits) != 1:
        return None, (call,)
    residual = expected - hits[0]["amount_paise"]
    return (
        link_verdict(
            session,
            txn_ids=frozenset({hits[0]["bank_txn_id"]}),
            break_type=BreakType.FX_ROUNDING,
            residual=residual,
            reason=ResidualReason.FX_ROUNDING,
            confidence=config.CONFIDENCE_KNOWN_TOLERANCE,
            rationale=(
                f"sole credit within {FX_PROBE_PAISE} paise of the expected "
                f"{expected}; off by {residual}"
            ),
            evidence=cite(hits[0]["bank_txn_id"]),
        ),
        (call,),
    )


def probe_missing_credit(session: Session) -> Outcome:
    """Settled per the processor, with a reference the bank never saw."""
    referenced = [r.utr for r in session.rows if r.utr]
    if not referenced:
        return None, ()
    seen = any(
        txn_id in session.ctx.visible_txn_ids or txn_id in session.ctx.index.txns_by_id
        for utr in referenced
        for txn_id in session.ctx.index.txns_by_utr.get(utr, ())
    )
    if seen:
        return None, ()
    return (
        AgentVerdict(
            case_ref=session.case.case_ref,
            action=ProposedAction.FLAG_MISSING_CREDIT,
            break_type=BreakType.MISSING_IN_BANK,
            settlement_row_ids=frozenset(r.settlement_row_id for r in session.rows),
            bank_txn_ids=frozenset(),
            residual_paise=session.expected_paise,
            residual_reason=ResidualReason.UNRECONCILED_FUNDS,
            confidence=config.CONFIDENCE_ORPHAN_FLAG,
            rationale=(
                f"UTR {referenced[0]} appears in the settlement report but nowhere in the "
                f"bank statement; {session.expected_paise} paise never arrived"
            ),
            evidence=cite(*(r.settlement_row_id for r in session.rows)),
        ),
        (),
    )


def probe_unexplained_candidate(session: Session) -> Outcome:
    """A credit that is clearly related but short by an amount we cannot name.

    Deliberately still a link proposal: naming the counterparty is useful even
    when the shortfall is not understood, and it stops the credit resurfacing
    later as an unidentified receipt. The low confidence sends it to a human.
    """
    expected = session.expected_paise
    if expected <= 0:
        return None, ()
    low, _ = fee_band(expected)
    hits, call = search_credits(session, min_paise=low, max_paise=expected)
    if len(hits) != 1:
        return None, (call,)
    residual = expected - hits[0]["amount_paise"]
    return (
        link_verdict(
            session,
            txn_ids=frozenset({hits[0]["bank_txn_id"]}),
            break_type=None,
            residual=residual,
            reason=ResidualReason.UNEXPLAINED,
            confidence=config.CONFIDENCE_UNEXPLAINED,
            rationale=(
                f"sole nearby credit is short by {residual} paise, which is neither a "
                "rounding difference nor any fee rate on file"
            ),
            evidence=cite(hits[0]["bank_txn_id"]),
        ),
        (call,),
    )


ROW_PROBES: tuple[Probe, ...] = (
    probe_anchor_tie_out,
    probe_chargeback_debit,
    probe_exact_credit,
    probe_split_credits,
    probe_fee_variance,
    probe_small_tolerance,
    probe_missing_credit,
    probe_unexplained_candidate,
)


# --- probes over cases that carry only bank transactions --------------------


def probe_unidentified_credit(session: Session) -> Outcome:
    """Money in the account that no open settlement row could have produced."""
    txn = session.anchored_txns[0]
    hits, call = plausible_sources(session)
    if hits:
        return None, (call,)
    return (
        AgentVerdict(
            case_ref=session.case.case_ref,
            action=ProposedAction.FLAG_UNIDENTIFIED_CREDIT,
            break_type=BreakType.UNKNOWN_CREDIT,
            settlement_row_ids=frozenset(),
            bank_txn_ids=frozenset(t.bank_txn_id for t in session.anchored_txns),
            residual_paise=-sum(t.amount_paise for t in session.anchored_txns),
            residual_reason=ResidualReason.UNRECONCILED_FUNDS,
            confidence=config.CONFIDENCE_ORPHAN_FLAG,
            rationale=(
                f"credit of {txn.amount_paise} paise on {txn.value_date} has no open "
                f"settlement row of that net anywhere in the window"
            ),
            evidence=cite(*(t.bank_txn_id for t in session.anchored_txns)),
        ),
        (call,),
    )


def probe_orphan_credit_candidate(session: Session) -> Outcome:
    """One open row could explain this credit, but not by an amount we can name.

    Proposed at low confidence so the pair reaches a person together, rather
    than the row and the credit surfacing separately as two half-mysteries.
    """
    txn = session.anchored_txns[0]
    hits, call = plausible_sources(session)
    if len(hits) != 1:
        return None, (call,)
    row = hits[0]
    return (
        AgentVerdict(
            case_ref=session.case.case_ref,
            action=ProposedAction.LINK,
            break_type=None,
            settlement_row_ids=frozenset({row["settlement_row_id"]}),
            bank_txn_ids=frozenset({txn.bank_txn_id}),
            residual_paise=row["net_paise"] - txn.amount_paise,
            residual_reason=ResidualReason.UNEXPLAINED,
            confidence=config.CONFIDENCE_UNEXPLAINED,
            rationale=(
                f"only {row['settlement_row_id']} could have produced this credit, but it "
                f"is short by {row['net_paise'] - txn.amount_paise} paise for no reason on file"
            ),
            evidence=cite(row["settlement_row_id"], txn.bank_txn_id),
        ),
        (call,),
    )


TXN_PROBES: tuple[Probe, ...] = (probe_unidentified_credit, probe_orphan_credit_candidate)
