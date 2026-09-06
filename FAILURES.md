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

---

## 4. The editable install stopped resolving, and entry 3's fix turned out to be conditional

**Symptom.** Two days after entry 3, `python -m recon.cli run` failed with
`ModuleNotFoundError: No module named 'recon'` again — but only from some
working directories, and only sometimes. `sys.path` showed `site-packages` on
it and the `.pth` file pointing at `src/` sitting in that directory, unread.

**Diagnosis.** Every time a new subpackage was added (`recon.agent`,
`recon.review`, `recon.knowledge`), setuptools' strict editable finder had to
be regenerated, so a stale install silently stopped seeing half the codebase.
Switching to `editable_mode=compat` produced a plain path `.pth` that this
interpreter did not process at all. Either way the import path depended on
install state I could not see from the error message.

**Recovery.** Stopped depending on it. The package is a `src/` layout with no
runtime dependencies, so `PYTHONPATH=src python -m recon.cli` needs no install
step at all, and that is what the `Makefile` and CI both use. `pip install -e
.` still works and is still documented — it is now one supported path rather
than the only one.

**Kept.** Entry 3 concluded "a green test suite does not prove the package is
installable". That was right, and incomplete: an install that worked once does
not prove it still works. The zero-install path is the one a reviewer will
actually hit, so that is the one CI exercises.

---

## 5. The fee-rate tool "explained" a flat bank charge, exactly

**Symptom.** Before trusting `implied_fee_bps`, I probed it with a case it was
never meant to explain: a settlement short by a flat ₹11.80 remittance charge.
It answered `{"exact": True, "fee_bps": 210}` — a clean, whole basis-point rate
that reproduces the observed payout to the paise.

**Diagnosis.** Not a bug in the tool. On a gross of ₹10,000, a flat ₹11.80
deduction is arithmetically indistinguishable from a 210 bps merchant discount
rate. Any inverse-fee calculation will find *some* rate for *any* shortfall.
Had the agent been allowed to treat "an exact rate exists" as an explanation,
it would have confidently repriced the merchant on the strength of a
coincidence, and it would have done it at high confidence because the
arithmetic really does tie out.

**Recovery.** Split "the arithmetic fits" from "we accept this explanation".
The gate now auto-applies a fee-rate variance only when the re-derived rate is
one the system already holds on file, and the agent starts with a single rate.
An unfamiliar rate is a proposal for a human, never a posting. The 275 bps rate
in the dataset is learned only after several people confirm it independently —
and 210 bps never accumulates support, because the residual is constant rather
than proportional, so the flat-charge promoter picks it up instead.

**Kept.** A model that can compute is not a model that can justify. The check
that matters is not "does this number work out" but "is this a kind of
explanation we have agreed to accept".

---

## 6. `recon review` crashed when nothing was attached to stdin

**Symptom.** A CLI test of the interactive review loop failed with
`OSError: pytest: reading from stdin while output is captured`.

**Diagnosis.** The loop caught `EOFError` and `KeyboardInterrupt` around
`input()`, which covers a reviewer pressing Ctrl-D or Ctrl-C. It did not cover
there being no terminal at all — a cron job, a CI step, a piped invocation —
where the read raises `OSError`. The failure mode in production would have been
worse than the test: an operator running the queue non-interactively would lose
every decision made before the crash, because the log is only written at the
end.

**Recovery.** Treat a missing terminal the same as a reviewer walking away:
stop the loop and persist what was already decided. Found because the surface
was tested at all, which is the argument for testing the boring commands.

**Kept.** Exception handlers written around the interactive case tend to miss
the non-interactive one, and the non-interactive one is where data gets lost
quietly.

---

## 7. One wrong posting, found only by running the invariant at a larger size

**Symptom.** Everything passed at the documented configuration — 500 cases,
seed 7, zero incorrect postings, four days running. Then I wrote the CI script
that asserts the invariant across several sizes and seeds, and 750 cases at
seed 23 produced exactly one wrong posting.

**Diagnosis.** A `bank_charge_netted` credit — one short by a flat ₹11.80 — was
auto-flagged as an *unidentified receipt* at 0.90 confidence. Two things had to
line up. The settlement row's own case found two candidate credits in its
window instead of one, so it abstained and left the credit unclaimed. The
credit then came up as its own case, and the probe that decides "nothing
explains this money" searched only for a settlement row whose net **exactly**
equalled the credit.

That search can never find a row that paid out short. So any deduction the
system cannot name will eventually be reported as money arriving from nowhere,
and reported confidently, because as far as that probe can see the search came
back empty. It needed a denser period for two candidates to collide, which is
why 500 cases never showed it.

**Recovery.** Made the question harder to answer in the affirmative. "Nothing
explains this credit" now requires that no open settlement row could have
produced it *after any plausible deduction* — net at or above the credit, up to
5% plus the materiality limit. If exactly one row could have, the case becomes a
low-confidence link instead, so the row and the credit reach a person together
rather than as two separate half-mysteries. CI now runs the invariant at six
sizes up to 1,500 cases.

**Kept.** Two lessons, and the second is the one I would not have got any other
way. First: a negative claim needs a search wide enough to disprove it — an
exact-match query is not evidence of absence. Second: an invariant that only
runs on the configuration in the README is a description of that configuration,
not an invariant. Every safety property in this project now runs across sizes
and seeds, and the one that mattered was the one I nearly did not write.

---

## 8. The materiality limit had a hole in it, and the docs claimed it did not

**Symptom.** A security review of the gate found that
`ResidualReason.UNRECONCILED_FUNDS` returned from `_residual_blockers` before
the materiality check ran. So any verdict flagging a missing or unidentified
credit auto-applied at any amount, provided the model was confident. One of my
own tests asserted this as correct behaviour, posting ₹9,763 automatically
against a ₹500 limit.

**Diagnosis.** The reasoning was that a flag is not a posting — it raises an
exception rather than moving money — so the cap did not apply. That was wrong
for a reason I had not thought about: `build_review_queue` filters out
everything the gate auto-applied, so an auto-flagged case is never shown to
anyone. "Flagged" and "closed without review" were the same thing in this
implementation. A missing ₹9,763 payout would have been marked as handled and
disappeared.

Worse, `SECURITY.md` stated that the limit "caps any automatic posting at ₹500
of unexplained value". That sentence was not true of the code it described.

**Recovery.** The cap now applies to flags as well as links. The line it draws
turns out to be the right one to draw anyway, and it is a better description of
what the system is for: **it clears matching problems on its own, and never
clears a cash difference.** Every `missing_in_bank` and `unknown_credit` case
now reaches a person, which is what a controller would want in the first place.

It cost real numbers — straight-through fell from 93.0% to 91.0%, and to 97.0%
rather than 99.0% after learning. I would rather report 97% honestly than 99%
with a hole in the control, and the shape of what is left is a better answer
than the bigger number was: five cases nobody could decide, and ten where money
is genuinely wrong.

**Kept.** Two things. A control with an exemption is not a control until you
have checked what the exemption reaches — mine was defensible in isolation and
wrong in context, because of a filter three modules away. And documentation
that overstates a guarantee is worse than no documentation: I wrote that
sentence in `SECURITY.md` believing it, and believing it is what stopped me
re-reading the branch it described.

---

## 9. The append-only decision log was read as if it were a tally

**Symptom.** Found by using the review console rather than by a test. Clicking
Confirm on the same case twice showed "2 confirmed", and promotion counted it
as two independent confirmations towards the three it requires.

**Diagnosis.** `decisions.jsonl` is append-only by design, and its own module
docstring says so: "a change of mind is a new line, never an edit". Every
consumer then read the file as a flat list. So one case confirmed twice counted
twice, and — worse — a case confirmed and later *rejected* still contributed
its withdrawn confirmation to the count. `MIN_SUPPORT = 3` was supposed to mean
three independent cases; it actually meant three log lines.

That is the whole guard against promoting a rule on thin evidence. Three
double-clicks on one case would have taught the system a merchant fee rate.

**Recovery.** Added `latest()` to collapse the log to one standing decision per
case, and routed promotion and the console's counters through it. Last word
wins, which is what an append-only log with revisions has always meant here.
Then made the semantics visible instead of implicit: the console grew a
**Change** button, so a reviewer can revise a decision and see the count move.

**Kept.** An append-only log is a design decision that every reader has to
honour, and the honouring is the part that gets skipped. Writing "a change of
mind is a new line" in a docstring did not make anything collapse the log — it
just made me believe it did. Also: I found this by clicking the thing. Four
days of tests and eight reviews had not, because every one of them fed the log
in one clean pass, which is exactly what a person never does.
