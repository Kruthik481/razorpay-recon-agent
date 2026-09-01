# Reconciliation Exception Agent

**Razorpay AI Buildathon 2026 — AI Finance Controller track**

Multi-source reconciliation across a merchant ledger, a PSP settlement report,
and a bank statement. A deterministic rules engine clears the mechanical
majority; an LLM agent is spent only on the ambiguous remainder, and every
proposal it makes is evidence-backed, confidence-scored, and reviewable.

---

## The thesis

Reconciliation is not hard because matching is hard. It is hard because a small
tail of breaks — undeclared fee changes, split payouts, netted refunds,
chargebacks, timing gaps — needs judgement, and that tail is what consumes the
finance team's week.

So the design question is not "can an LLM reconcile a ledger". It is **where an
LLM is worth its cost and its risk**. Measured on 500 generated cases:

| | |
|---|---|
| **Auto-matched by rules, no model call** | **87.0%** |
| **Precision of those matches** | **100.0%** |
| **Incorrect matches** | **0** |
| Left for the agent | 150 records |

Sending all 550 settlement rows to a model would be roughly 8× the token spend
to do worse on the 87% that deterministic rules already close at perfect
precision — and it would introduce a chance of error where currently there is
none. The rules engine is not a fallback for the AI. It is what makes the AI
affordable and safe to use on the part that actually needs it.

The single most important number above is **incorrect matches: 0**. A missed
match costs an analyst a few minutes. A confidently *wrong* match posts a bad
journal entry that can take weeks to unwind. This harness reports the two
separately and never blends them into one accuracy figure.

---

## Status

**Day 1 complete** — generator, deterministic matcher, evaluation harness.
Day 2 adds the LLM exception agent that works the 150-record queue.

- [x] Synthetic three-source dataset with a per-case answer key
- [x] Staged deterministic matcher (UTR → amount+window → batch payout)
- [x] Evaluation harness with per-break-type recall and queue composition
- [ ] LLM exception agent: tool use, cited evidence, confidence gating
- [ ] Human review queue, with rejections promoted back into rules
- [ ] Cost and latency accounting per 1,000 lines

---

## Quickstart

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e . && pip install -r requirements.txt

python -m recon.cli evaluate --cases 500 --seed 7   # the table above
python -m recon.cli export --out data/              # CSVs of all three sources
pytest -q                                           # 34 tests
```

## Architecture

```
                 orders.csv     settlement_rows.csv     bank_txns.csv
                 (ledger)       (PSP report)            (bank)
                      \               |                    /
                       \              |                   /
                        +-------------+------------------+
                                      |
                        +-------------v------------------+
                        |   STAGE 1  exact UTR           |  conf 1.00
                        |   unique reference both sides, |
                        |   amount agrees net of fees    |
                        +-------------+------------------+
                                      | residual
                        +-------------v------------------+
                        |   STAGE 2  amount + window     |  conf 0.90
                        |   sole credit for that net     |
                        |   within the settlement window |
                        +-------------+------------------+
                                      | residual
                        +-------------v------------------+
                        |   STAGE 3  batch payout        |  conf 0.85
                        |   group by settlement_id,      |
                        |   whole batch or unique subset |
                        +-------------+------------------+
                                      | residual
                        +-------------v------------------+
                        |   EXCEPTION QUEUE  (150)       |
                        |   the only place a model call  |
                        |   is justified     -> Day 2    |
                        +--------------------------------+
```

Each stage sees only what earlier stages left behind, and nothing is ever
re-matched. **Every rule abstains rather than guessing**: if the evidence does
not identify exactly one counterparty, the record goes to the queue. That is
the only safe default when the output posts a journal entry.

## Break taxonomy

Resolved by rules — mechanical, no judgement required:

| Break | Why a naive match fails |
|---|---|
| `clean` | — |
| `fee_netting` | Credit is net of MDR + GST, never equals order gross |
| `settlement_lag` | Credit lands T+3, crossing the reporting window |
| `missing_utr` | PSP report omits the reference entirely |
| `aggregated_payout` | Several rows paid out as one consolidated credit |

Routed to the agent — genuinely ambiguous:

| Break | Why judgement is required |
|---|---|
| `non_standard_fee` | Renegotiated rate the recon config still has as 2% |
| `partial_settlement` | One row arrives as two credits on different days |
| `refund_netted` | Refund silently deducted from an unrelated payout |
| `fx_rounding` | Off by a few paise from cross-currency rounding |
| `duplicate_utr` | Same reference *and* amount — undecidable alone |
| `chargeback_debit` | Debit with no corresponding order |
| `missing_in_bank` | Settled per the PSP, money never arrived |
| `unknown_credit` | Money arrived with nothing to explain it |

## Why synthetic data

Real settlement data is not available to a hackathon entrant, and scraping
together a public dataset would leave no way to tell a correct match from a
confident wrong one. Generating the data means **every case carries a
ground-truth answer key**, so the harness can report precision and per-break
recall instead of screenshots.

The generator is seeded and allocates break counts by largest remainder rather
than sampling, so the mix is identical across runs. Any metric change reflects
a code change, never a reshuffle. The break mix (58% clean, tapering to 1% for
the rare tail) is weighted to look like production, where the tail is small and
expensive.

The matcher never sees `Dataset.ground_truth`. Only the evaluation harness does.

## Design notes

**Integer paise everywhere.** No float touches an amount. Fee and tax are
derived with half-up integer rounding so the generator and matcher agree
exactly rather than approximately.

**Immutable records.** Every model is a frozen dataclass; each stage returns
new tuples rather than mutating a working set. A record cannot be silently
claimed twice, and the test suite asserts that matched and unmatched partition
the input exactly.

**Confidence is per rule, not per model.** A UTR match is 1.00 because the
evidence is exact. Amount-plus-window is 0.90 because coincidence is possible.
These are properties of the evidence, and they set the bar the Day 2 agent has
to clear before anything auto-posts.

## What broke

Three substantial things, including an evaluation harness that accused a
correct matcher and a batch-matching rule whose obvious fix would have traded
precision for recall. Written up in [FAILURES.md](./FAILURES.md).

## Layout

```
src/recon/
  domain/      frozen records, break taxonomy, integer money
  generator/   one builder per break type, deterministic assembly
  matching/    staged rules + engine
  evaluation/  scoring against the answer key, terminal report
tests/         34 tests
```
