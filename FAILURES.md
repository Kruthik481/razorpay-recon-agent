# What broke, and how I recovered

A running log kept while building, not reconstructed afterwards. Each entry
records the symptom, the diagnosis, and — where they differ — why the obvious
fix was the wrong one.

---

## 1. The evaluation harness flagged 10 wrong matches that were actually right

**Symptom.** First full run of the eval harness: `incorrect_matches = 10`,
precision 97.7%. Since "never post a wrong linkage" is the safety property the
whole design rests on, this looked like the matcher confidently guessing.

**Diagnosis.** All 10 traced to the `duplicate_utr` scenario. The matcher was
behaving correctly: stage 1 abstained on the reused reference, then stage 2
separated the two rows by amount and produced the *right* pairing. The bug was
in my answer key. I had recorded the case as a single ground-truth link
covering both rows and both credits, so the exact-signature comparison scored
two correct proposals as one wrong one.

**Recovery.** The deeper problem was that the scenario wasn't a break at all.
Two rows sharing a UTR but carrying different amounts are still separable, so a
rules engine *should* resolve them. I changed the generator to emit identical
amounts as well as identical references, which is the version that is genuinely
undecidable without more evidence. Both stages now abstain and the case lands
in the exception queue where it belongs.

**Kept.** When a metric accuses the code, check the metric first. I nearly
"fixed" a matcher that was already right, which would have made it worse.

---

## 2. Blind subset-sum for batch payouts: 20% recall, and unsafe at scale

**Symptom.** `aggregated_payout` recall was 0.2 — only 4 of 20 batch payouts
matched.

**Diagnosis.** The rule searched every combination of unmatched settlement rows
within a date window for a subset summing to the credit. I had capped the
candidate pool at 12 rows to bound the search, but the generated period carries
a median of 20 settlement rows per settlement date, so the rule hit its guard
and abstained almost every time.

**The fix I didn't ship.** Raising the cap. At 30 rows, C(30,5) is 142,506
subsets per credit, and the cost is the smaller problem: in a large pool,
coincidental subsets that sum to the right total become *likely*. That converts
a safe abstention into a confident false match, which is the one failure mode
this system exists to avoid. More search would have bought recall by spending
precision.

**Recovery.** Modelled the source properly instead. Real PSP settlement reports
publish a settlement/payout ID that already groups the rows in a batch, so I
added `settlement_id` to the settlement row and grouped on it. The subset
search survives only as a fallback *inside* one batch, where the pool is small
by construction and the combinatorics are bounded. Recall went to 100% with
zero false matches, and the rule got faster.

**Kept.** When a matching rule underperforms, ask what identifying information
the source already provides before reaching for a bigger search. The
combinatorial version looked more sophisticated and was strictly worse.

---

## 3. Package imported fine under pytest but not from a plain interpreter

**Symptom.** `ModuleNotFoundError: No module named 'recon'` running a
throwaway diagnostic script, while the full test suite passed.

**Diagnosis.** `pythonpath = ["src"]` in `pyproject.toml` is honoured by
pytest, not by the interpreter, so the `src/` layout resolved only under test.

**Recovery.** Added a `[build-system]` and setuptools package discovery over
`src/`, so `pip install -e .` gives a reviewer cloning the repo a working
import path from the documented setup steps alone. Verified by importing the
package from a plain interpreter, not just under pytest.

**Kept.** A green test suite does not prove the package is installable. Those
are separate claims and the README depends on the second one.
