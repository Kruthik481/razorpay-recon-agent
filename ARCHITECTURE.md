# Architecture

## The shape of the problem

Reconciliation is a three-way join that does not join. The merchant's ledger
says what was ordered, the processor's settlement report says what was paid out
after fees, and the bank statement says what actually moved. They disagree for
about a dozen structural reasons, most of them mechanical and a few of them
genuinely ambiguous.

The design follows from one asymmetry: a missed match costs an analyst minutes,
a wrong match posts a journal entry that someone unwinds weeks later. Every
component is therefore built to abstain rather than guess, and the number the
system is optimised against is *incorrect postings*, held at zero, not accuracy.

## Data flow

```
generator ──> Dataset(orders, settlement_rows, bank_txns, ground_truth)
                 │                                            │
                 │  (the matcher and agent never see this) ───┘
                 ▼
             reconcile(rows, txns, rules)
                 │
                 ├─ MatchProposal ×N ──────────> evaluate() ──> EvaluationReport
                 │
                 └─ ReconOutcome.unmatched_*
                        │
                        ▼
                 build_exception_queue() ──> ExceptionCase ×N
                        │
                        ▼
                 resolver.resolve(case, ToolContext) ──> AgentVerdict
                        │
                        ▼
                 verify() ──> violations
                        │
                        ▼
                 gate() ──> GatedVerdict{auto_apply | needs_review | escalate}
                        │
                        ├─ auto_apply ──> counted as straight-through
                        │
                        └─ everything else ──> ReviewItem ──> ReviewDecision
                                                                  │
                                                                  ▼
                                                             promote()
                                                                  │
                                                                  ▼
                                                              Knowledge
                                                                  │
                                        learned_rules(knowledge) ─┘
```

The loop closes: `Knowledge` feeds back into `reconcile`, so the second pass
over the same period clears breaks the first pass had to escalate.

## Module boundaries

| package | owns | must not know about |
| ------- | ---- | ------------------- |
| `domain` | records, break taxonomy, integer-paise money | everything else |
| `generator` | synthetic periods and the answer key | matching, agent |
| `matching` | deterministic stages and learned rules | the answer key, the agent |
| `agent` | tools, prompts, providers, verification, gate | the answer key, review |
| `review` | decision log, queue, promotion | the answer key |
| `knowledge` | learnable facts and their JSON store | how facts get used |
| `evaluation` | scoring against ground truth | how anything was produced |
| `dashboard` | HTML rendering | any decision logic |

The one rule that matters: **`ground_truth` is read only by
`recon.evaluation`.** Nothing in `matching`, `agent` or `review` imports it. The
`Dataset` carries the answer key alongside the data because that is convenient
for the harness, and the boundary is enforced by keeping every consumer honest —
`reconcile_dataset` takes a `Dataset` and touches three of its four fields.

## Key types

```python
MatchProposal(settlement_row_ids, bank_txn_ids, stage, confidence, rationale)
ReconOutcome(matches, unmatched_settlement_row_ids, unmatched_bank_txn_ids)
ExceptionCase(case_ref, settlement_row_ids, bank_txn_ids, anchor_reason)
AgentVerdict(action, break_type, record ids, residual_paise, residual_reason,
             confidence, rationale, evidence)
GatedVerdict(verdict, disposition, violations, gate_reasons)
Knowledge(fee_bps_on_file, fx_tolerance_paise, flat_bank_charges_paise, facts)
```

Everything is a frozen slotted dataclass. Stages return new tuples; nothing is
mutated in place, including `Knowledge`, whose `with_*` methods return copies.

## Matching stages

Rules run strongest-evidence-first and each stage sees only what earlier stages
left behind. A stage never revisits a claimed record.

1. **`match_by_exact_utr`** — requires the reference to be unique on *both*
   sides and the credit to equal the row's net. A reused reference carries no
   identifying power, so it abstains.
2. **`match_by_amount_and_date_window`** — exact net amount inside
   `[settled_on, settled_on + 4d]`, only when exactly one candidate survives.
3. **`match_aggregated_payouts`** — groups by the `settlement_id` the PSP
   publishes, tries the whole batch, then falls back to a bounded subset search
   *inside* that batch. See FAILURES.md entry 2 for why grouping beat searching.
4. **learned rules** — parameterised by `Knowledge`; empty until review teaches
   the system something.

## The agent's contract

A resolver implements one method:

```python
def resolve(self, case: ExceptionCase, ctx: ToolContext) -> ResolverOutput
```

`ToolContext` carries the ledger index, the set of records still open, and the
current `Knowledge`. Two resolvers ship:

- **`DeterministicPolicy`** — ordered probes, no model, no network. This is the
  control against which any model claim is measured. Its parts are split across
  `providers/policy_support.py` (the shared machinery), `policy_probes.py` (one
  probe per question it knows how to ask) and `deterministic.py` (the class).
- **`AnthropicResolver`** — a tool-calling loop against the Messages API, with
  the SDK imported lazily and the client injectable so it is testable with no
  key and no package installed.

Adding a third is one class and one line in `providers/build_resolver`.

## Trust boundary

Everything downstream of `resolve` treats the verdict as untrusted input:

- `verify()` recomputes the residual from the ledger and rejects any citation
  that is not an open record.
- `gate()` re-derives the fee rate itself rather than believing the verdict's
  claim, and refuses any residual reason not already on file.
- The materiality limit blocks a large automatic write-off at any confidence,
  and applies to flags too: the system clears matching problems on its own and
  never clears a cash difference.

This is why a hallucinated id or a wishful shortfall costs a case rather than a
journal entry.

## Extension points

| to add | touch |
| ------ | ----- |
| a break type | `domain/break_types.py`, a builder in `generator/scenarios.py`, a weight in `generator/config.py` |
| a deterministic rule | `matching/rules.py`, register in `DEFAULT_RULES` |
| a learnable fact | `knowledge/model.py`, a promoter in `review/promotion.py`, a rule in `matching/learned.py` |
| an agent tool | `agent/tools.py` and its schema in `agent/toolspec.py` (a test asserts the two stay in sync) |
| a model provider | a class with `resolve`, plus `agent/providers/__init__.py` |

## What is deliberately not here

- **A database.** The whole period fits in memory and the point is the
  reasoning, not the storage layer.
- **A web server.** The dashboard is a file. It survives being emailed.
- **Streaming.** Reconciliation is a batch problem with a daily cadence.
- **A framework.** The runtime has no dependencies at all. The agent loop is
  about a hundred lines because that is all it needs to be.
