# Contributing

The runtime has no dependencies. Everything below works from a clean checkout.

```bash
git clone https://github.com/Kruthik481/razorpay-recon-agent
cd razorpay-recon-agent
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
make check          # lint, format check, tests, coverage
```

If you would rather not install anything, every command works with
`PYTHONPATH=src python -m recon.cli ...`, which is what the `Makefile` and CI
use.

## The rules that are not negotiable

1. **Incorrect postings stay at zero.** `make run` prints the number. A change
   that raises it is not a trade-off, it is a regression, however much recall it
   buys.
2. **Money is integer paise.** No floats touch an amount, anywhere. Use
   `recon.domain.money`.
3. **Abstain on ambiguity.** A rule or probe that finds two valid explanations
   returns nothing. Never pick the first candidate.
4. **Nothing but `recon.evaluation` reads `ground_truth`.** If a matcher or an
   agent needs the answer key, the benchmark is meaningless.
5. **Records are immutable.** Frozen slotted dataclasses, new tuples out. This
   includes `Knowledge`.

## Adding a break type

1. Add the member to `BreakType` in `domain/break_types.py`, and to
   `DETERMINISTICALLY_MATCHABLE` only if a rule can resolve it with certainty.
2. Write a pure builder in `generator/scenarios.py` — same context in, same
   records out — and register it in `SCENARIO_BUILDERS`.
3. Give it a weight in `BREAK_MIX`.
4. Run `make run`. A new judgement break should show up in the exception queue,
   not silently get matched.

## Adding an agent tool

Tools live in `agent/tools.py` and take a `ToolContext` first. They must be
read-only, bounded, and scoped to open records. Add the JSON schema to
`agent/toolspec.py` — a test asserts the registry and the schemas stay in sync.

## Adding a learnable fact

Three places, in this order:

1. `knowledge/model.py` — the field and a `with_*` method that returns a copy.
2. `review/promotion.py` — a promoter that re-derives the value **from the
   ledger** rather than trusting the decision's label, requires at least
   `MIN_SUPPORT` independent confirmations, and enforces a hard bound.
3. `matching/learned.py` — the rule that uses it, registered in
   `LEARNED_RULE_FACTORIES`.

A fact that can be learned without a bound is a way to launder a guess into
policy. Do not add one.

## Tests

`make test`. Arrange-Act-Assert, and name the behaviour rather than the
function:

```python
def test_a_reused_reference_is_never_used_to_match(): ...
```

Coverage is enforced at 80% and currently sits at 93%. New logic needs tests;
new *safety* logic needs a test that proves the unsafe thing does not happen.

## Style

`ruff check` and `ruff format` are the arbiters — `make check` runs both.
Beyond that: files under 400 lines, functions under 50, no nesting past four
levels, and comments that explain *why*, not *what*. Both limits are checked by
`scripts/check_size_limits.py`, which CI runs.
