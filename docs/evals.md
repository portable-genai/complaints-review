# How the complaints review assistant is evaluated

Read this page if you decide what this service is allowed to say. The metrics, the bars and the
corpus below are generated from the artifacts that actually gate the build, so they cannot drift
from what runs: `make evals-doc-check` fails the build when this page and those artifacts
disagree.

## How to run it

```sh
make eval              # offline, no credentials
make evals-doc-check   # this page is still true
```

`make check` runs both on every change.

## What is measured, and against what bar

Every bar below lives in `eval/rubrics/*.yaml` next to the argument for it, and the
runner reads it from there. There is no dict of thresholds in the runner any more: a
metric scored with no reviewed bar fails the build, and so does a bar that names no
metric, which is the direction that rots quietly because it rots toward looking well
governed.

The third column is the denominator rule, and it applies only where a score is a
FRACTION over scored positives: such a threshold `t` tolerates a single miss only over
at least `1/(1-t)` of them. `all or nothing` marks a bar that already asks for no
headroom, so a bigger corpus would not change what it means. Each rubric declares which
it is rather than the rule being guessed from the number.

| Metric | Bar | Denominator | What it measures |
|---|---|---|---|
| `categorisation_accuracy` | 0.85 | a rate; needs 7 positives | Fraction of examples whose assigned ComplaintCategory equals the golden category. |
| `citation_accuracy` | 0.9 | a rate; needs 10 positives | Precision and recall of the review's citations against the knowledge base and the reviewer's must-cite list, averaged. |
| `groundedness` | 0.8 | a rate; needs 5 positives | Fraction of reviews whose categorisation and draft response are backed by a cited policy / regulatory source. A review that draws a conclusion with no citation scores 0. |
| `pii_safety` | 1 | all or nothing | No raw identifier survives into any audit record or review narrative, checked by the shared pack and by an independent planted literal. |

Scored over 10 golden complaints.

## What is exercised

- **10 golden complaints** in `eval/datasets/golden_complaints.jsonl`, each
  with the category a reviewer assigned and 13 must-cite source ids between
  them. The expectation is the dataset's, never a re-read of the pipeline's verdict.
- **4 of them plant a raw identifier**, across 4 markets
  (AU, HK, JP, SG), so a broken pattern row for one jurisdiction cannot hide
  behind another market's clean result. A corpus that plants nothing scores a vacuous
  1.0.

## How a metric is prevented from being decoration

This repository was, until recently, the only one in the second wave with **no falsification
proof at all**: four gated metrics that had never been shown able to fail, which is exactly what
a broken scorer also looks like. Four rules now stand between a green result and a meaningless
one, and all four run in the scored run itself rather than only in a test suite:

1. **Every metric's red case runs first.** Run in `tests/`, a proof says the metric could have
   gone red on some machine at some point; run as the first statement of the scored run, it says
   the metric about to score this corpus can go red, in this process, with these thresholds. Each
   degraded case mutates the OUTPUT the scorer reads, and the scorers are imported rather than
   re-implemented, so a scorer that stopped working breaks the build instead of passing a copy of
   itself.
2. **The bars are read from the rubrics, in both directions.** There is no `THRESHOLDS` dict any
   more, and two of the four metrics had no rubric at all. `assert_covers` fails the build when a
   metric has no reviewed bar AND when a bar names no metric.
3. **The corpus must be able to express its own bars.** `citation_accuracy` at 0.90 is measured
   over the citations the reviews actually carry, not over ten complaints, which would not have
   supported it.
4. **The leak scan reads what the service persisted**, two independent ways. Scoring only off the
   pack the redactor masks with is a closed loop: a narrowed row can neither mask nor detect, and
   scores a vacuous 1.0 with the raw identifier sitting in the audit trail.

## What is NOT measured here

Naming this is part of the page, because an unmeasured claim that goes unmentioned reads as a
measured one.

- **A real model's words.** Every metric scores a deterministic core against a deterministic fake
  LLM adapter, so `groundedness` is a measurement of the VALIDATOR rather than of a model's
  restraint.
- **The draft response's prose.** Whether the drafted reply reads as a fair, complete answer to
  the complainant is a judgement and nothing judges it. That is the largest remaining gap here.
- **Retrieval quality.** Deliberately not scored: the local knowledge base seeds two passages, so
  recall over it would be trivially 1.0 and would say nothing. A retrieval metric belongs here
  once the corpus is large enough for one to mean something.
- **Production traffic.** Everything here is a golden set. Nothing samples live requests.
