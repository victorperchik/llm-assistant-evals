"""Optional Langfuse sink.

The harness exists to run in CI with no key and no spend, and that does not
change here. This module is opt-in, imported lazily, and every failure inside
it is swallowed: an observability backend that can fail a deploy is a worse
problem than the one it was installed to solve.

What it adds is the one thing a markdown report cannot give you: history.
The report tells you baseline was 1/8 and v2 is 8/8. Langfuse tells you which
of the last forty runs was the one that broke `no_invented_date`, and on which
commit.

Mapping:

    golden set          -> dataset
    one case            -> dataset item (item id is the case id, so re-running
                           updates in place instead of duplicating)
    one --run           -> dataset run (experiment)
    checks and rubric   -> scores on that run's items

Usage:

    pip install langfuse
    export LANGFUSE_PUBLIC_KEY=pk-lf-...
    export LANGFUSE_SECRET_KEY=sk-lf-...
    export LANGFUSE_BASE_URL=https://cloud.langfuse.com  # eu default; us. and jp. exist

    python -m evals.runner ... --langfuse
"""

from __future__ import annotations

import os
from collections import defaultdict
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from .runner import RunResult
    from .schema import Case, Response

DEFAULT_DATASET = "assistant-golden-set"


class LangfuseUnavailable(RuntimeError):
    """Raised only inside this module. Callers downgrade it to a warning."""


def _client() -> Any:
    if not (os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY")):
        raise LangfuseUnavailable(
            "LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY are not set; skipping Langfuse"
        )
    try:
        from langfuse import get_client
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise LangfuseUnavailable("the langfuse package is not installed (pip install langfuse)") from exc
    return get_client()


def _evaluation(name: str, value: float, comment: str = "") -> Any:
    from langfuse import Evaluation

    return Evaluation(name=name, value=value, comment=comment) if comment else Evaluation(name=name, value=value)


def sync_dataset(cases: list["Case"], dataset_name: str = DEFAULT_DATASET) -> None:
    """Upsert the golden set as a Langfuse dataset.

    Item ids are case ids on purpose. The golden set is edited far more often
    than it is replaced, and a dataset that grows a duplicate every time a case
    is reworded stops being comparable within a week.
    """
    lf = _client()
    lf.create_dataset(
        name=dataset_name,
        description="Golden set for personal assistant deliveries: mechanical checks first, rubric second.",
        metadata={"source": "llm-assistant-evals"},
    )
    for case in cases:
        lf.create_dataset_item(
            dataset_name=dataset_name,
            id=case.id,
            input={"user_turn": case.user_turn, "context": case.context},
            expected_output={
                "expectations": [
                    {"kind": e.kind, "value": e.value, "severity": e.severity, "note": e.note}
                    for e in case.expectations
                ]
            },
            metadata={"case_id": case.id, "tags": case.tags, "language": case.language},
        )
    lf.flush()


def push_run(
    responses: dict[str, "Response"],
    result: "RunResult",
    dataset_name: str = DEFAULT_DATASET,
    run_suffix: str = "",
) -> str:
    """Send one evaluated run to Langfuse as a dataset run. Returns the run name.

    Nothing is recomputed here. The checks and the rubric have already run
    offline; this only carries their numbers across. Scoring twice, once for
    the report and once for the dashboard, is how the two start disagreeing.
    """
    lf = _client()

    by_case: dict[str, list] = defaultdict(list)
    for outcome in result.outcomes:
        by_case[outcome.case_id].append(outcome)
    rubric_by_case = {r.case_id: r for r in result.rubric}

    def task(*, item: Any, **_: Any) -> str:
        case_id = _case_id(item)
        response = responses.get(case_id)
        return response.text if response else ""

    def grade(*, metadata: dict | None = None, **_: Any) -> list:
        case_id = (metadata or {}).get("case_id", "")
        outcomes = by_case.get(case_id, [])
        blockers = [o for o in outcomes if not o.passed and o.severity == "blocker"]
        warnings = [o for o in outcomes if not o.passed and o.severity == "warn"]

        evaluations = [
            _evaluation(
                "case_clean",
                0.0 if blockers else 1.0,
                comment="; ".join(f"{o.kind}: {o.detail}" for o in blockers)[:400],
            ),
            _evaluation("blockers", float(len(blockers))),
            _evaluation("warnings", float(len(warnings))),
        ]

        rubric = rubric_by_case.get(case_id)
        if rubric:
            for axis, value in rubric.scores.items():
                evaluations.append(_evaluation(f"rubric.{axis}", float(value)))
            if rubric.max_total:
                evaluations.append(
                    _evaluation(
                        "rubric_pct",
                        100.0 * rubric.total / rubric.max_total,
                        comment=rubric.comment,
                    )
                )
        return evaluations

    def summarise(**_: Any) -> list:
        """Run-level totals, so nobody has to average the item scores back up.

        Without these the only aggregate lives in the description string, and
        anything reading the run over the API — a dashboard, an agent — has to
        re-derive it from the per-item scores and hope it derives it the same
        way the report did.
        """
        return [
            _evaluation("run.cases_clean_pct", 100.0 * result.cases_passed / (result.cases_total or 1)),
            _evaluation("run.blockers_total", float(len(result.blockers))),
            _evaluation("run.warnings_total", float(len(result.warnings))),
            _evaluation("run.rubric_pct", result.rubric_pct),
        ]

    run_name = f"{result.name}{run_suffix}"
    dataset = lf.get_dataset(dataset_name)
    dataset.run_experiment(
        name=run_name,
        description=(
            f"{result.cases_passed}/{result.cases_total} cases clean, "
            f"{len(result.blockers)} blocker(s), rubric {result.rubric_pct:.1f}%"
        ),
        task=task,
        evaluators=[grade],
        run_evaluators=[summarise],
    )
    lf.flush()
    return run_name


def _case_id(item: Any) -> str:
    """Dataset items carry the case id twice; take whichever the SDK exposes."""
    for candidate in (getattr(item, "id", None), (getattr(item, "metadata", None) or {}).get("case_id")):
        if candidate:
            return str(candidate)
    return ""


def ci_run_suffix() -> str:
    """A short, stable marker so two runs of the same name stay distinguishable.

    GitHub gives us a commit and a run number for free. Locally there is
    nothing worth inventing, so the run keeps its bare name and overwrites
    itself, which is what you want while you are iterating.
    """
    sha = os.environ.get("GITHUB_SHA", "")[:7]
    number = os.environ.get("GITHUB_RUN_NUMBER", "")
    if sha and number:
        return f"-ci{number}-{sha}"
    if sha:
        return f"-{sha}"
    return ""
