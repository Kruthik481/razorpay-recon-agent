# Runtime state

Two files live here once the loop has been run. Both are gitignored: they are
outputs of a particular reconciliation period, not source.

| file | written by | read by |
| ---- | ---------- | ------- |
| `decisions.jsonl` | `recon review` | `recon promote` |
| `knowledge.json` | `recon promote` | the matcher, the agent, the gate |

`decisions.jsonl` is append-only: a change of mind is a new line, never an edit.
`knowledge.json` is the audit surface — every learned fact carries the case
references that justified it, so it can be read, diffed and reverted by hand.

`decisions.sample.jsonl` is checked in. It is the output of the scripted
reviewer in `recon.review.simulate` on the documented configuration (500 cases,
seed 7), so the promotion step can be reproduced without anyone sitting through
the queue. It stands in for a person; it has never seen the answer key.

```bash
cp state/decisions.sample.jsonl state/decisions.jsonl
make promote
```
