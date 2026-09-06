# Reconciliation exception agent

**Deterministic rules clear the mechanical breaks. A model is spent only on the
ambiguous tail. Every exception a human confirms becomes a new rule, so the same
break never costs twice.**

Built for the [Razorpay AI Buildathon](https://razorpay.com/buildathon/), AI
Finance Controller track. Runs end to end with no API key and no network.

```bash
git clone https://github.com/Kruthik481/razorpay-recon-agent
cd razorpay-recon-agent
make run
```

---

## The result

Measured on a generated 28-day settlement period: 500 cases, 550 settlement
rows, 510 bank transactions, ₹6,795,911 of gross value. Every number below is
scored against an answer key that the matcher and the agent never see.

|                          | rules only | + exception agent | + one review cycle |
| ------------------------ | ---------: | ----------------: | -----------------: |
| straight through         |      86.0% |         **91.0%** |          **97.0%** |
| cases reaching a human   |         70 |                45 |             **15** |
| **incorrect postings**   |      **0** |             **0** |              **0** |
| auto-apply precision     |     100.0% |            100.0% |             100.0% |

The fifteen that survive are exactly the two kinds that should:

- **5 undecidable.** Two settlements sharing one bank reference for the same
  amount. The group ties out; which row paid which credit does not follow from
  anything in the file. No model fixes that — it is missing information.
- **10 real cash differences.** Five payouts that never arrived and five
  credits nothing explains. The agent finds them, names them and hands them
  over. It does not close them: the system clears *matching* problems on its
  own and never clears a *money* problem. See [FAILURES.md](FAILURES.md) entry
  8 for the review that caught this being wrong.

Reproduce with `make run`. Open `make dashboard` for the same thing as HTML.

---

## Why this problem

Razorpay's own framing of the AI Finance Controller track: *verification
capacity is the bottleneck; reconciliation, settlement and forecasting are
still done by hand.* That is a precision problem, not a volume problem.

The economics are lopsided in a way that decides the architecture:

- **A missed match costs minutes.** An analyst looks at it and moves on.
- **A wrong match costs weeks.** It posts a journal entry, flows into a close,
  and someone has to unwind it downstream.

So the system is built to abstain. Every rule and every model verdict proposes a
link only when the evidence identifies exactly one counterparty. Two plausible
explanations means no answer, every time.

---

## How it works

```
   merchant ledger        PSP settlement report        bank statement
          |                        |                         |
          +------------------------+-------------------------+
                                   |
                      ┌────────────▼────────────┐
                      │  1. deterministic rules │   86% of cases
                      │  exact UTR              │   0 model calls
                      │  amount + date window   │   0 wrong postings
                      │  declared batch payout  │
                      │  learned rules  ◄───────┼──────────────┐
                      └────────────┬────────────┘              │
                                   │ exception queue           │
                      ┌────────────▼────────────┐              │
                      │  2. exception agent     │   tools, not │
                      │  9 read-only tools      │   free text  │
                      │  cites record ids       │              │
                      │  declares residual      │              │
                      └────────────┬────────────┘              │
                                   │ verdict                   │
                      ┌────────────▼────────────┐              │
                      │  3. verify + gate       │   recomputes │
                      │  residual recomputed    │   every      │
                      │  citations checked      │   number     │
                      │  materiality limit      │              │
                      └──┬──────────────────┬───┘              │
                  auto-apply           needs a human           │
                         │                  │                  │
                         ▼       ┌──────────▼──────────┐       │
                    posted       │  4. review queue    │       │
                                 │  confirmed →────────┼───────┘
                                 │  promotion          │  new rule
                                 └─────────────────────┘
```

### 1. Rules first

Most reconciliation lines match on rules a model has no business touching — 86%
of cases here.
Three stages run strongest-evidence-first, each seeing only what the previous
one left: a UTR unique on both sides, an exact net amount inside the settlement
window, and a payout batch grouped by the `settlement_id` the PSP already
publishes.

Spending an LLM call on those is spending money to become less reliable.

### 2. The agent works only what is left

The exception queue is clustered on keys a real report actually publishes —
shared payment id, order id, or UTR. Everything else the agent has to find
itself, through nine read-only tools:

`get_settlement_row` · `get_bank_txn` · `get_order` · `find_bank_txns` ·
`find_settlement_rows` · `fee_schedule` · `expected_net` · `implied_fee_bps` ·
`check_sum`

Three properties are enforced in code rather than asked for in the prompt:

- **Read-only.** No tool mutates the ledger.
- **Bounded.** Every search takes a date range and an amount range and returns
  at most 25 rows, so prompt size and cost cannot run away.
- **Scoped.** Searches see only records the matcher left open, so money that is
  already reconciled cannot be claimed twice.

The model never does arithmetic: it calls `check_sum` and uses what comes back.

### 3. Nothing the model says is trusted

A verdict is a proposal. Before it can reach the ledger:

| check | what it catches |
| ----- | --------------- |
| every cited id must be an open record | a hallucinated or already-reconciled reference |
| the residual is **recomputed** from the ledger | a misstated or wishful shortfall |
| the action must match the record shape | "these are unrelated" citing a link |
| the residual reason must be one we accept | an unexplained deduction dressed up as a fee |
| residual ≤ ₹500 materiality limit, flags included | a large write-off at high confidence, and any material cash difference being closed quietly |

A fee-rate variance auto-applies only when the re-derived rate is one the system
already holds. See [FAILURES.md](FAILURES.md) entry 5 for why "the arithmetic
works out" is not the same as "this is explained".

### 4. Confirmed exceptions become rules

Every case the gate refuses goes to a queue with the proposal, the money that
does not tie out, and the reason it was blocked. Confirmations are mined for
patterns, and a pattern with at least three independent confirmations — inside
hard-coded bounds — becomes a deterministic rule.

On the sample period the system taught itself three facts:

| learned | value | from | effect |
| ------- | ----: | ---: | ------ |
| a second merchant discount rate | 275 bps | 15 confirmations | 15 cases stop reaching the queue |
| a rounding tolerance | 7 paise | 10 confirmations | 10 cases stop reaching the queue |
| a flat bank charge | ₹11.80 | 5 confirmations | 5 cases stop reaching the queue |

Thirty cases stop reaching the human queue, and the matcher clears them for
free from then on — 86.0% to 92.0% on rules alone.

The third one is the interesting one. Nobody described a flat charge to the
system. It noticed the *same* shortfall recurring across settlements of totally
different sizes — a proportional fee cannot do that — and inferred a constant
deduction from the data alone.

Learned facts live in a plain JSON file (`state/knowledge.json`) with the case
references behind each one. A rule nobody can read, audit or revert is a
liability, not a feature.

---

## Break taxonomy

The generator produces fourteen kinds of break, split by whether a rules engine
can resolve them *in principle*.

**Rules resolve these — 86% of cases, no model call:**

| break | what it looks like |
| ----- | ------------------ |
| `clean` | UTR on both sides, amounts agree |
| `fee_netting` | credit is net of MDR + GST, so it never equals the order gross |
| `settlement_lag` | credit lands T+3, crossing the reporting boundary |
| `missing_utr` | PSP report omits the reference |
| `aggregated_payout` | several rows paid as one consolidated credit |

**These need judgement — the agent's queue:**

| break | what it looks like | outcome |
| ----- | ------------------ | ------- |
| `refund_netted` | a refund deducted from the same day's payout | auto-applied, ties out exactly |
| `partial_settlement` | one settlement arriving as two credits | auto-applied, unique split |
| `chargeback_debit` | a debit with no order behind it | auto-applied |
| `missing_in_bank` | settled per the PSP, money never arrived | found, named, **never closed** |
| `unknown_credit` | money in, nothing explains it | found, named, **never closed** |
| `non_standard_fee` | a renegotiated rate the config does not know | review → **learned** |
| `fx_rounding` | short by a few paise | review → **learned** |
| `bank_charge_netted` | short by a flat remittance charge | escalated → **learned** |
| `duplicate_utr` | two settlements, one reference, same amount | stays with a human, correctly |

---

## Why synthetic data

Real settlement files are confidential, and without an answer key you can report
"we matched 94%" but not "we were right 94% of the time". Those are different
claims and only the second one is worth anything when a wrong link posts a
journal entry.

Every generated case carries a ground-truth link, so precision and recall are
measurable per break type. The generator is deterministic — exact break counts
by largest-remainder allocation, not sampling — so a metric change always
reflects a code change.

All money is integer paise. Floats never touch an amount anywhere in the system.

---

## Running it

```bash
make run          # the whole loop, before and after learning
make dashboard    # the same thing as a self-contained HTML file
make queue        # what still needs a person, and why
make review       # decide on the queue yourself
make promote      # turn your confirmations into rules
make test         # 176 tests
make check        # lint, format check, tests with coverage
make export       # write the period out as CSV
```

Nothing above needs an API key, a network connection, or an install step.

### Using a live model

The deterministic policy in `src/recon/agent/providers/` is the **control**,
not a mock: it is the best "just write more rules" answer, written
by someone who knows the dataset. It exists so that every claim about what a
model adds is measured against a serious baseline, and so the repo runs on a
clean checkout.

To run the same queue through Claude:

```bash
pip install -e ".[llm]"
export ANTHROPIC_API_KEY=...
python -m recon.cli run --resolver anthropic --model claude-sonnet-5
```

Both resolvers implement the same interface, get the same tools, and are scored
by the same harness, so the comparison is direct. Token and rupee cost per
thousand ledger lines is reported in the same table.

> The measured figures in this README are from the deterministic policy. Model
> figures depend on your key and model choice and are printed by the command
> above; they are not quoted here because I have not run them.

---

## Layout

```
src/recon/
  domain/       frozen records, break taxonomy, integer-paise money
  generator/    one pure builder per break type, plus the answer key
  matching/     the deterministic stages, and rules learned from review
  agent/        tools, prompts, providers, verification, confidence gate
  review/       decision log, review queue, promotion
  knowledge/    the facts the system is allowed to learn, and their store
  evaluation/   scoring against ground truth; terminal reports
  dashboard/    self-contained HTML report
  commands/     one module per command group
tests/          176 tests, 93% branch coverage
```

## Design notes

- **Immutable throughout.** Frozen slotted dataclasses; every stage returns new
  tuples. Nothing is mutated in place, including the knowledge base.
- **Integer paise only.** `apply_bps` rounds half-up with integer math so the
  generator and the matcher agree to the paise.
- **Confidence is a property of the evidence, not of the model.** A unique UTR
  match is 1.00 because the evidence is unique, not because anything feels sure.
- **Abstention is a first-class answer.** Every rule and every probe returns
  nothing when two explanations fit.

## What broke

[FAILURES.md](FAILURES.md) — six entries, written as they happened, including
two where the obvious fix was the wrong one and one where a metric accused
correct code.

## Further reading

- [ARCHITECTURE.md](ARCHITECTURE.md) — data flow, module boundaries, extension points
- [DEMO.md](DEMO.md) — the five-minute walkthrough
- [CONTRIBUTING.md](CONTRIBUTING.md) — adding a break type, a rule, or a provider

## License

MIT — see [LICENSE](LICENSE).
