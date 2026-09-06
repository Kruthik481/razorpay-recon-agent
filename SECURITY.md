# Security

## Reporting

Open a private security advisory on the repository, or email
kruthikrocky@gmail.com. Please do not open a public issue for a vulnerability.

## What this project handles

All shipped data is synthetic, generated locally by `recon.generator`. The
repository contains no real merchant, bank or customer data, and no credentials.

If you point it at real data, everything below applies to you.

## Secrets

`ANTHROPIC_API_KEY` is read from the environment by the `anthropic` SDK. It is
never read from a file, never logged, and never included in a verdict, a
decision log, a dashboard or a report. `.env` is gitignored.

No other secret is used anywhere in the codebase.

## Trust boundaries

| input | treated as | control |
| ----- | ---------- | ------- |
| model output | untrusted | every record id checked against open records; every amount recomputed from the ledger |
| `state/knowledge.json` | untrusted | schema-versioned, type-checked on load, rejected loudly if malformed |
| `state/decisions.jsonl` | untrusted | every line parsed strictly; a malformed line fails the load rather than being skipped |
| CSV exports | output only | never read back by the system |

The agent's tools are read-only by construction. There is no code path from a
model response to a mutation of the ledger — a verdict is data that the
verifier and the gate consume, and the gate is the only thing that decides a
disposition.

## Prompt injection

Record descriptions from a bank statement reach the model as data inside a tool
result. If a hostile description tried to instruct the model, the blast radius
is bounded by design rather than by the prompt:

- tools cannot write anything;
- searches are scoped to records the matcher left open, so no already-reconciled
  money is reachable;
- any record id the model returns is checked against that same open set;
- the residual is recomputed from the ledger, so a claimed amount cannot lie;
- the materiality limit caps any automatic posting at ₹500, and applies to
  flags as well as links — the agent closes matching problems on its own, and
  never closes a cash difference.

The worst outcome of a successful injection is a wrong proposal that fails
verification and goes to a human.

## Learned rules

The promotion path is the one place the system changes its own behaviour. It is
constrained deliberately:

- a minimum of three independent human confirmations;
- values re-derived from the ledger, never taken from the decision's label;
- hard ceilings on every learnable value;
- every promoted fact records the case references behind it, in plain JSON, so
  it can be audited and reverted.

Promotion re-derives values from the ledger, so a decision cannot teach the
system a rate the amounts do not support. It does trust that the lines in
`decisions.jsonl` represent real human decisions. Anyone who can write to that
file before `recon promote` runs can, with at least `MIN_SUPPORT` fabricated
confirmations pointing at real rows, get a rate promoted — bounded by the
plausible-rate band and the exact-reproduction requirement, but still a
promotion nobody made. In a real deployment the decision log needs the same
access controls as any other approval record; treat write access to it as
equivalent to approval authority.
