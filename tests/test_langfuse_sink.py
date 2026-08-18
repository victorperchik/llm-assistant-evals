"""The sink's contract is that it cannot hurt anything.

These tests assert the three ways it is allowed to behave when the outside
world is missing or broken: refuse politely without keys, carry the already
computed scores across without recomputing them, and never change the runner's
exit code. Nothing here talks to a network.
"""

from __future__ import annotations

import types

import pytest

from evals import langfuse_sink as sink
from evals.rubric import HeuristicScorer
from evals.runner import evaluate, main
from evals.schema import load_cases, load_responses

CASES = "data/golden_set.example.jsonl"
BASELINE = "data/runs/baseline.jsonl"
V2 = "data/runs/v2.jsonl"


def test_no_keys_is_a_polite_refusal(monkeypatch):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    with pytest.raises(sink.LangfuseUnavailable):
        sink._client()


def test_langfuse_flag_never_changes_the_exit_code(tmp_path, monkeypatch):
    """Without keys the flag is a no-op, and the build verdict is untouched."""
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    args = [
        "--cases", CASES,
        "--run", f"baseline={BASELINE}",
        "--run", f"v2={V2}",
        "--out", str(tmp_path / "report.md"),
    ]
    assert main(args) == main(args + ["--langfuse"]) == 0


def test_a_broken_backend_is_swallowed(tmp_path, monkeypatch):
    def explode() -> None:
        raise ConnectionError("host unreachable")

    monkeypatch.setattr(sink, "_client", explode)
    assert main([
        "--cases", CASES,
        "--run", f"v2={V2}",
        "--out", str(tmp_path / "report.md"),
        "--langfuse",
    ]) == 0


class _Recorder:
    """A stand-in for the SDK that runs the callbacks instead of swallowing them.

    The first version of this stub took **kwargs and therefore accepted
    run_evaluators without ever calling them, which meant a green suite said
    nothing about the run-level scores. A fake that silently absorbs the thing
    under test is worse than no fake: it reports confidence it does not have.
    """

    def __init__(self) -> None:
        self.items: list = []
        self.item_scores: list[tuple[str, float]] = []
        self.run_scores: dict[str, float] = {}
        self.run_evaluators_seen = 0

    # --- client half -----------------------------------------------------
    def create_dataset(self, **kw) -> None: ...

    def create_dataset_item(self, **kw) -> None:
        self.items.append(
            types.SimpleNamespace(
                id=kw["id"], input=None, expected_output=None, metadata={"case_id": kw["id"]}
            )
        )

    def get_dataset(self, name, **kw): return self

    def flush(self) -> None: ...

    # --- dataset half ----------------------------------------------------
    def run_experiment(self, *, name, task, evaluators=(), run_evaluators=(), description=None, **_):
        results = []
        for item in self.items:
            output = task(item=item)
            results.append(types.SimpleNamespace(item=item, output=output))
            for evaluator in evaluators:
                for ev in evaluator(input=None, output=output, expected_output=None, metadata=item.metadata):
                    self.item_scores.append((ev.name, ev.value))
        self.run_evaluators_seen = len(run_evaluators)
        for evaluator in run_evaluators:
            for ev in evaluator(item_results=results):
                self.run_scores[ev.name] = ev.value
        return types.SimpleNamespace(format=lambda: "")


def _push(monkeypatch, run: str, path: str) -> tuple[_Recorder, object]:
    stub = _Recorder()
    monkeypatch.setattr(sink, "_client", lambda: stub)
    cases = load_cases(CASES)
    sink.sync_dataset(cases, "test-set")
    responses = load_responses(path, run)
    result = evaluate(cases, responses, run, HeuristicScorer())
    sink.push_run(responses, result, "test-set")
    return stub, result


def test_scores_are_carried_not_recomputed(monkeypatch):
    """Every score pushed must already exist in the offline RunResult."""
    stub, result = _push(monkeypatch, "baseline", BASELINE)
    assert len(stub.items) == result.cases_total

    clean = [value for name, value in stub.item_scores if name == "case_clean"]
    assert len(clean) == result.cases_total
    assert sum(clean) == result.cases_passed

    blockers = [value for name, value in stub.item_scores if name == "blockers"]
    assert sum(blockers) == len(result.blockers)


@pytest.mark.parametrize("run,path", [("baseline", BASELINE), ("v2", V2)])
def test_run_level_aggregates_match_the_offline_result(monkeypatch, run, path):
    """The run carries its own totals, and they agree with the report.

    Asserted on both runs on purpose: baseline is the failing case and v2 the
    clean one, and an aggregate that is only ever checked against zeros hides
    a whole class of arithmetic mistake.
    """
    stub, result = _push(monkeypatch, run, path)

    assert stub.run_evaluators_seen == 1, "run_evaluators never reached the SDK"
    assert set(stub.run_scores) == {
        "run.cases_clean_pct",
        "run.blockers_total",
        "run.warnings_total",
        "run.rubric_pct",
    }
    assert stub.run_scores["run.cases_clean_pct"] == pytest.approx(
        100.0 * result.cases_passed / result.cases_total
    )
    assert stub.run_scores["run.blockers_total"] == len(result.blockers)
    assert stub.run_scores["run.warnings_total"] == len(result.warnings)
    assert stub.run_scores["run.rubric_pct"] == pytest.approx(result.rubric_pct)
