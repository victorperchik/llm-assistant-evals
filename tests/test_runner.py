import sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evals.runner import evaluate
from evals.rubric import HeuristicScorer
from evals.schema import load_cases, load_responses


def test_v2_beats_baseline_and_report_writes(tmp_path):
    cases = load_cases(ROOT / "data/golden_set.example.jsonl")
    base = evaluate(cases, load_responses(ROOT / "data/runs/baseline.jsonl", "baseline"),
                    "baseline", HeuristicScorer())
    v2 = evaluate(cases, load_responses(ROOT / "data/runs/v2.jsonl", "v2"),
                  "v2", HeuristicScorer())

    assert len(base.blockers) > 0, "the baseline is supposed to be bad"
    assert len(v2.blockers) == 0, "v2 should be clean"
    assert v2.rubric_pct > base.rubric_pct
    assert v2.cases_total == len(cases)


def test_missing_response_is_reported():
    cases = load_cases(ROOT / "data/golden_set.example.jsonl")
    partial = load_responses(ROOT / "data/runs/v2.jsonl", "v2")
    partial.pop("handback")
    res = evaluate(cases, partial, "partial", HeuristicScorer())
    assert res.missing == ["handback"]
