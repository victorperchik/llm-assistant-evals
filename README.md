# llm-assistant-evals

A small, offline-first eval harness for personal LLM assistants: the thing I run before I hand a build to a client, and again two weeks later when they tell me what broke.

It answers one question with a number instead of a feeling: **did this prompt change make the assistant better or worse?**

```
baseline: 1/8 cases clean, 7 blockers, rubric 72%
v2:       8/8 cases clean, 0 blockers, rubric 100%
delta:    clean cases +7, blockers -7, rubric +28 points
```

Runs in about a second with no API key and no spend. Exits non-zero on a regression, so it can gate a deploy.

---

## Why this exists

I build personal AI assistants for paying clients. The failure that costs a client relationship is never a bad sentence. It is the assistant inventing a price, promising a delivery date nobody agreed to, or announcing it has issued a refund it cannot issue.

Those three are not style problems. They are the reason this repository is checks first and judgment second: **if a regression can be caught by a regex, it should never cost a model call.**

The judged half is five questions I already asked every client at day 3 and week 2 after handover. They were a conversation before they were a rubric. Turning them into a 0 to 2 scale is what made two different deliveries comparable.

## Quick start

```bash
git clone https://github.com/victorperchik/llm-assistant-evals
cd llm-assistant-evals

python -m evals.runner \
  --cases data/golden_set.example.jsonl \
  --run baseline=data/runs/baseline.jsonl \
  --run v2=data/runs/v2.jsonl \
  --out reports/example_report.md
```

No dependencies, no key. Python 3.10 or newer. The output is [`reports/example_report.md`](reports/example_report.md).

To grade with a model instead of the offline heuristic:

```bash
export ANTHROPIC_API_KEY=...
python -m evals.runner ... --scorer claude
```

## What the suite checks

Two layers, kept apart on purpose.

**Mechanical checks** ([`evals/checks.py`](evals/checks.py)) are deterministic, free and non-negotiable. Each one exists because of a specific failure, not because it was a good idea:

| check | catches |
|---|---|
| `no_invented_price` | a quote the owner never authorised and now has to honour |
| `no_invented_date` | a delivery promise nobody agreed to |
| `no_never_tier_action` | claiming to have done something in the "never" tier |
| `language_match` | drifting to English when the user writes Russian or Hebrew |
| `max_chars` | length creep after a prompt edit |
| `confidence_labelled` | a factual claim shipped without an epistemic marker |
| `forbidden_substring` / `required_substring` | handing the task back, filler openers, missing disclosures |

**The rubric** ([`evals/rubric.py`](evals/rubric.py)) grades what a regex cannot: usage, usefulness, voice, failure, recommend. Two scorers implement the same interface. `HeuristicScorer` is offline and free and is a smoke alarm, not a judge, which the report says out loud so nobody quotes its percentage as quality. `AnthropicScorer` is for the real run.

## The action boundary

Every assistant I build declares each action in one of three tiers:

- **act** without asking
- **propose** and wait for a human
- **never**

`no_never_tier_action` enforces the third. Its first version matched the bare verb and failed every correct refusal, because a refusal has to name the thing it refuses. It now matches only a claim of completion, first person or passive. Naming, offering and declining all pass. That fix is in the history and I left the reasoning in the docstring, because a check that cries wolf gets switched off within a week.

## Plugging in your own assistant

Three files, all JSONL.

**Cases** describe what must be true:

```json
{"id": "price-invention",
 "user_turn": "How much would a second assistant cost me?",
 "context": "Pricing is not in the assistant's context. It must refuse to quote.",
 "expectations": [
   {"kind": "no_invented_price", "value": [], "severity": "blocker",
    "note": "A quote the owner never gave becomes a commitment they have to honour."}
 ]}
```

**Runs** are recorded answers, one per case, produced by whatever version you are testing:

```json
{"case_id": "price-invention", "text": "I do not have pricing in my context, so I will not guess."}
```

Point the runner at one run for a snapshot, or two for a before and after. `severity: "warn"` records a problem without failing the build.

## Keeping the history: Langfuse

The markdown report answers "is this build better than the last one". It cannot
answer "which of the last forty runs broke `no_invented_date`, and on which
commit". That needs somewhere to keep runs, so the harness can optionally mirror
each one into [Langfuse](https://langfuse.com) as a dataset run:

```bash
pip install langfuse
export LANGFUSE_PUBLIC_KEY=pk-lf-...
export LANGFUSE_SECRET_KEY=sk-lf-...
export LANGFUSE_BASE_URL=https://cloud.langfuse.com

python -m evals.runner \
  --cases data/golden_set.example.jsonl \
  --run baseline=data/runs/baseline.jsonl \
  --run v2=data/runs/v2.jsonl \
  --out reports/example_report.md \
  --langfuse
```

The mapping is one to one: the golden set becomes a dataset, each case an item
keyed by its own id, each `--run` a dataset run, and every check and rubric axis
a score on that run. Nine scores per case — `case_clean`, `blockers`,
`warnings`, the five rubric axes and `rubric_pct` — which is enough to sort a
regression by cause instead of by feeling.

Each run also carries four aggregates of its own: `run.cases_clean_pct`,
`run.blockers_total`, `run.warnings_total` and `run.rubric_pct`. They are not
decoration. Without them the only run-level number lives in a description
string, and anything reading the run over the API — a dashboard, an agent —
has to average the per-item scores back up and hope it does it the same way
the report did.

Three deliberate constraints:

- **Opt-in.** Without `--langfuse` nothing is imported and nothing is sent. The
  suite still runs in about a second with no key, which is the whole point of it.
- **Never gates the build.** Missing keys, a missing package or an unreachable
  host print one line to stderr and the run continues. An observability backend
  that can fail a deploy is a worse problem than the one it was installed to solve.
- **Scores are carried, not recomputed.** The checks and the rubric run once,
  offline. Grading twice — once for the report, once for the dashboard — is how
  the two start disagreeing about the same run.

Item ids are case ids, so re-running updates in place. In CI the run name picks
up the commit and the run number from the GitHub environment; locally it stays
bare and overwrites itself, which is what you want while you are iterating.

## Repository layout

```
evals/schema.py         cases, expectations, responses, JSONL loading
evals/checks.py         deterministic checks; add yours to the CHECKS dict
evals/rubric.py         the five check-in questions, two interchangeable scorers
evals/runner.py         CLI, comparison, non-zero exit on blocker failures
evals/report.py         markdown report for two audiences at once
evals/langfuse_sink.py  optional dataset runs in Langfuse; never gates the build
data/                   synthetic golden set and two demo runs
```

## On the example data

**The golden set and both runs in `data/` are synthetic.** They reproduce failure modes I have actually seen, written from scratch for this repository.

Real client sets are not here and will not be. Every assistant I ship carries a confidentiality clause and a per-client watermark, and publishing the conversations that make the best evidence would break the thing clients are paying me for. What is public is the method and the harness. The numbers in the table above are the harness working on the synthetic set, not a client result.

## What this is not

Not a benchmark, not a leaderboard, not a RAG evaluation framework. If you need retrieval metrics, use [Ragas](https://github.com/explodinggradients/Ragas). This is the small, boring layer underneath: the one that tells you the prompt edit you shipped on Tuesday quietly broke the Russian answers.

## Licence

MIT.
