# Five-minute walkthrough

The script for the pitch video. Timings are the target, not the ceremony.

---

## 0:00 — The problem, in one number (30s)

> Razorpay's own brief for this track says verification capacity is the
> bottleneck — reconciliation is still done by hand. So I built the thing that
> does it. But the interesting constraint isn't volume, it's asymmetry.
>
> A missed match costs an analyst a few minutes. A **wrong** match posts a
> journal entry that somebody unwinds three weeks later, in a close.
>
> That asymmetry decides the whole architecture.

## 0:30 — What most people would build, and why it's wrong (45s)

> The obvious build is "throw the settlement file at an LLM and ask it to
> reconcile". That spends money to become less reliable.
>
> 86% of these lines match on rules a model has no business touching — a
> matching reference, an exact amount inside the settlement window, a payout
> batch the processor already grouped for you. Deterministic, auditable, free.
>
> The cost lives entirely in the tail. So that's where the model goes.

**Show:** `make run` — first block on screen.

```
  rules auto-matched         430 / 500   (86.0%)
  incorrect postings           0
```

## 1:15 — The agent, and what it is not allowed to do (90s)

> The agent gets nine read-only tools, and three properties are enforced in
> code rather than requested in the prompt: it cannot write, every search is
> bounded to 25 rows, and it can only see records the matcher left open — so it
> physically cannot claim money that is already reconciled.
>
> It never does arithmetic. It calls `check_sum` and uses what comes back.
>
> And then nothing it says is trusted. The verdict is a proposal. Before it
> reaches the ledger, I recompute the residual from the ledger myself, check
> every cited id is a real open record, and refuse any explanation that isn't
> one we've already agreed to accept.

**Show:** the gate table in the README, then:

```
  agent worked                70 cases   (70 resolved correctly)
    auto-applied              25   precision 100.0%
    sent to review            40
    escalated                  5
  straight-through           455 / 500   (91.0%)
```

> Note what did *not* happen: nothing was auto-applied wrongly. The five
> escalations are cases the policy could not name, and it says so rather than
> inventing something.

## 2:45 — The part I'd want to be asked about (60s)

> Here's a failure I built the safety rail around.
>
> One break in the data is a flat ₹11.80 bank remittance charge. I have a tool
> that inverts the fee schedule — given a gross and a payout, what rate explains
> it? I fed it the flat-charge case before trusting it, and it came back
> `exact: True, fee_bps: 210`. A clean, whole basis-point rate, tying out to the
> paise.
>
> It was a coincidence. On a ₹10,000 gross, a flat ₹11.80 is arithmetically
> indistinguishable from a 210 bps rate. If "an exact rate exists" counted as an
> explanation, the system would have confidently repriced the merchant — at high
> confidence, because the maths genuinely works.
>
> So the gate doesn't ask "does this tie out". It asks "is this a kind of
> explanation we've agreed to accept". A fee rate auto-applies only if it's
> already on file.

## 3:45 — The loop that makes it compound (75s)

> Which raises the obvious question: then how does a new rate ever get accepted?

**Switch to the browser — `make serve`.** This is the beat to do live, not on
slides.

> Through review. Every blocked case is here, with the proposal, the money that
> doesn't tie out, and why the gate refused it. I confirm the ones I agree with.

*Click Confirm down the list. The counter moves. Then hit **Promote**.*

> Three independent confirmations of the same pattern, inside hard-coded
> bounds, and it becomes a deterministic rule.

*The banner appears and the numbers move on screen:*

```
  straight through     91%  ->  97%      (+6.0 pts)
  cases needing a person  45  ->  15     (30 fewer)
  rules on file            0  ->   3
  incorrect postings       0      0
```

> Three rules, and the third is the one I'd point at. Nobody told this system
> that flat charges exist. It noticed the *same* shortfall — ₹11.80 — recurring
> across settlements of completely different sizes. A percentage fee can't do
> that. It inferred a constant deduction from the data alone.
>
> And those rules now run in the *matcher*, not the agent. So that break stops
> costing a model call at all. The system gets cheaper the more it's used.

**If the room is quiet, one more click:** press **Change** on a decision.

> The decision log is append-only, so revising is a new line and the latest word
> counts. I got that wrong the first time — the log was being read as a tally,
> so double-clicking one case counted as two independent confirmations. Which
> would mean three double-clicks could teach it a merchant fee rate. It's
> FAILURES.md entry 9, and I only found it by clicking the thing.

## 5:00 — What's left, and why that's correct (15s)

> Fifteen cases survive, and they're exactly the two kinds that should.
>
> Five are undecidable: two settlements sharing one bank reference for the same
> amount. The group ties out; which row paid which credit doesn't follow from
> anything in the file. That's not a modelling gap, it's missing information.
>
> The other ten are real cash differences — payouts that never arrived, credits
> nothing explains. The agent finds them and names them. It deliberately does
> **not** close them. The system clears matching problems on its own; it never
> clears a money problem. That line is enforced in the gate, not in a comment.

---

## If asked: "what broke?"

Point at [FAILURES.md](FAILURES.md). The two worth telling:

**The metric accused correct code.** The eval harness reported ten wrong
matches. The matcher was right; my *answer key* was wrong. I nearly "fixed" a
matcher that had no bug. Then the deeper problem surfaced: the scenario wasn't
even a break — two rows with the same reference but different amounts are still
separable. I changed the generator so the case is genuinely undecidable.

**The obvious fix was backwards.** Batch payout recall was 20%. The rule
searched combinations of unmatched rows for a subset summing to the credit, with
the pool capped for cost. Obvious fix: raise the cap. That would have been
wrong — in a bigger pool coincidental sums become *likely*, converting safe
abstentions into confident false matches. The real fix was to search less: real
settlement reports publish a batch id, so I grouped on it. Recall went to 100%,
zero false matches, and it got faster.

## If asked: "did you actually use an LLM?"

Yes — and the repo is honest about what is measured. The `AnthropicResolver`
runs the same queue through Claude with the same nine tools and the same
verification and gate. `--resolver anthropic` switches to it.

The numbers quoted are from the deterministic policy, which is the **control**,
not a mock: the best "just write more rules" answer, written by someone who
knows the dataset. That's deliberate. Any claim of the form "the model adds X"
is worthless without a serious non-model baseline, and shipping the baseline
means the repo runs on a clean checkout with no key.
