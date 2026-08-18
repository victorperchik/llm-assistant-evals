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


def test_scores_are_carried_not_recomputed(monkeypatch):
    """Every score pushed must already exist in the offline RunResult."""
    sent: list[tuple[str, float]] = []

    class StubItem:
        def __init__(self, case_id: str) -> None:
            self.id = case_id
            self.input = self.expected_output = None
            self.metadata = {"case_id": case_id}

    class StubDataset:
        def __init__(self, items): self.items = items

        def run_experiment(self, *, name, task, evaluators=(), description=None, **_):
            for item in self.items:
                task(item=item)
                for evaluator in evaluators:
                    for ev in evaluator(input=None, output=None, expected_output=None, metadata=item.metadata):
                        sent.append((ev.name, ev.value))
            return types.SimpleNamespace(format=lambda: "")

    class StubClient:
        def __init__(self): self.items = []

        def create_dataset(self, **kw): pass

        def create_dataset_item(self, **kw): self.items.append(StubItem(kw["id"]))

        def get_dataset(self, name, **kw): return StubDataset(self.items)

        def flush(self): pass

    stub = StubClient()
    monkeypatch.setattr(sink, "_client", lambda: stub)

    cases = load_cases(CASES)
    sink.sync_dataset(cases, "test-set")
    assert len(stub.items) == len(cases)

    responses = load_responses(BASELINE, "baseline")
    result = evaluate(cases, responses, "baseline", HeuristicScorer())
    sink.push_run(responses, result, "test-set")

    clean = [value for name, value in sent if name == "case_clean"]
    assert len(clean) == result.cases_total
    assert sum(clean) == result.cases_passed

    blockers = [value for name, value in sent if name == "blockers"]
    assert sum(blockers) == len(result.blockers)
