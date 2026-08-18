"""Run a golden set against one or two recorded runs and write a report.

Usage:

    python -m evals.runner --cases data/golden_set.example.jsonl \
        --run baseline=data/runs/baseline.jsonl \
        --run v2=data/runs/v2.jsonl \
        --out reports/example_report.md

Exit code is 1 if the last run has any blocker failure, so this can gate CI.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

from .checks import CHECKS
from .report import write_report
from .rubric import HeuristicScorer, RubricScore, Scorer
from .schema import Case, Response, load_cases, load_responses


@dataclass
class CheckOutcome:
    case_id: str
    kind: str
    passed: bool
    severity: str
    detail: str
    note: str


@dataclass
class RunResult:
    name: str
    outcomes: list[CheckOutcome]
    rubric: list[RubricScore]
    missing: list[str]

    @property
    def blockers(self) -> list[CheckOutcome]:
        return [o for o in self.outcomes if not o.passed and o.severity == "blocker"]

    @property
    def warnings(self) -> list[CheckOutcome]:
        return [o for o in self.outcomes if not o.passed and o.severity == "warn"]

    @property
    def cases_passed(self) -> int:
        failed = {o.case_id for o in self.blockers}
        seen = {o.case_id for o in self.outcomes}
        return len(seen - failed)

    @property
    def cases_total(self) -> int:
        return len({o.case_id for o in self.outcomes})

    @property
    def rubric_pct(self) -> float:
        if not self.rubric:
            return 0.0
        got = sum(r.total for r in self.rubric)
        top = sum(r.max_total for r in self.rubric)
        return 100.0 * got / top if top else 0.0


def evaluate(cases: list[Case], responses: dict[str, Response], name: str, scorer: Scorer) -> RunResult:
    outcomes: list[CheckOutcome] = []
    rubric: list[RubricScore] = []
    missing: list[str] = []

    for case in cases:
        resp = responses.get(case.id)
        if resp is None:
            missing.append(case.id)
            continue
        for exp in case.expectations:
            fn = CHECKS.get(exp.kind)
            if fn is None:
                raise KeyError(f"unknown check '{exp.kind}' in case {case.id}")
            passed, detail = fn(resp.text, exp.value)
            outcomes.append(
                CheckOutcome(
                    case_id=case.id,
                    kind=exp.kind,
                    passed=passed,
                    severity=exp.severity,
                    detail=detail,
                    note=exp.note,
                )
            )
        rubric.append(scorer.score(case.id, case.user_turn, resp.text))

    return RunResult(name=name, outcomes=outcomes, rubric=rubric, missing=missing)


def _push_to_langfuse(
    cases: list[Case],
    recorded: dict[str, dict[str, Response]],
    results: list[RunResult],
    dataset_name: str | None,
) -> None:
    """Best-effort mirror of this run into Langfuse.

    Deliberately noisy on failure and harmless otherwise. The suite's job is to
    fail the build on a regression; it is not allowed to fail the build because
    a dashboard was unreachable.
    """
    from . import langfuse_sink as sink

    name = dataset_name or sink.DEFAULT_DATASET
    try:
        sink.sync_dataset(cases, name)
        suffix = sink.ci_run_suffix()
        for result in results:
            run_name = sink.push_run(recorded[result.name], result, name, suffix)
            print(f"langfuse: pushed run '{run_name}' to dataset '{name}'")
    except sink.LangfuseUnavailable as exc:
        print(f"langfuse: skipped ({exc})", file=sys.stderr)
    except Exception as exc:  # noqa: BLE001 - see docstring
        print(f"langfuse: push failed ({type(exc).__name__}: {exc})", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run the assistant eval suite.")
    ap.add_argument("--cases", required=True)
    ap.add_argument(
        "--run",
        action="append",
        required=True,
        metavar="NAME=PATH",
        help="a recorded run; repeat to compare versions",
    )
    ap.add_argument("--out", default="reports/report.md")
    ap.add_argument("--scorer", choices=("heuristic", "claude"), default="heuristic")
    ap.add_argument(
        "--langfuse",
        action="store_true",
        help="also send each run to Langfuse as a dataset run (opt-in, never gates the exit code)",
    )
    ap.add_argument("--langfuse-dataset", default=None, metavar="NAME")
    args = ap.parse_args(argv)

    cases = load_cases(args.cases)

    if args.scorer == "claude":
        from .rubric import AnthropicScorer

        scorer: Scorer = AnthropicScorer()
    else:
        scorer = HeuristicScorer()

    results: list[RunResult] = []
    recorded: dict[str, dict[str, Response]] = {}
    for spec in args.run:
        if "=" not in spec:
            ap.error(f"--run expects NAME=PATH, got {spec!r}")
        name, path = spec.split("=", 1)
        responses = load_responses(path, name)
        recorded[name] = responses
        results.append(evaluate(cases, responses, name, scorer))

    if args.langfuse:
        _push_to_langfuse(cases, recorded, results, args.langfuse_dataset)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    write_report(out, cases, results, scorer_name=scorer.name)

    for r in results:
        print(
            f"{r.name}: {r.cases_passed}/{r.cases_total} cases clean, "
            f"{len(r.blockers)} blocker(s), {len(r.warnings)} warning(s), "
            f"rubric {r.rubric_pct:.0f}%"
        )
    print(f"report written to {out}")

    return 1 if results and results[-1].blockers else 0


if __name__ == "__main__":
    sys.exit(main())
