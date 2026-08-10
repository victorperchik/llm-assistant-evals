"""Markdown report.

Two audiences, one file. The client reads the first table and stops. I read
the failure list and fix things. Nothing in here needs a dashboard.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from .rubric import QUESTIONS

if TYPE_CHECKING:  # pragma: no cover
    from .runner import RunResult
    from .schema import Case


def write_report(path: Path, cases: list["Case"], results: list["RunResult"], scorer_name: str) -> None:
    lines: list[str] = []
    a = lines.append

    a("# Assistant eval report")
    a("")
    a(f"Cases: **{len(cases)}** · runs compared: **{len(results)}** · rubric scorer: `{scorer_name}`")
    if scorer_name == "heuristic":
        a("")
        a(
            "> The heuristic scorer is a smoke alarm, not a judge. Its percentage is "
            "only meaningful as a delta between runs on the same case set."
        )
    a("")

    a("## Summary")
    a("")
    a("| run | cases clean | blockers | warnings | rubric |")
    a("|---|---|---|---|---|")
    for r in results:
        a(
            f"| {r.name} | {r.cases_passed}/{r.cases_total} | {len(r.blockers)} | "
            f"{len(r.warnings)} | {r.rubric_pct:.0f}% |"
        )
    a("")

    if len(results) >= 2:
        first, last = results[0], results[-1]
        d_clean = last.cases_passed - first.cases_passed
        d_block = len(last.blockers) - len(first.blockers)
        d_rub = last.rubric_pct - first.rubric_pct
        a(
            f"**Delta {first.name} to {last.name}:** clean cases {d_clean:+d}, "
            f"blockers {d_block:+d}, rubric {d_rub:+.0f} points."
        )
        a("")

        fixed, broken = _diff(first, last)
        if fixed:
            a(f"Fixed: {', '.join(sorted(fixed))}")
        if broken:
            a(f"**Regressed: {', '.join(sorted(broken))}**")
        if fixed or broken:
            a("")

    a("## Rubric by axis")
    a("")
    a("| axis | question | " + " | ".join(r.name for r in results) + " |")
    a("|---|---|" + "---|" * len(results))
    for axis, question in QUESTIONS.items():
        cells = []
        for r in results:
            vals = [s.scores.get(axis, 0) for s in r.rubric]
            cells.append(f"{(sum(vals) / len(vals)):.2f}" if vals else "n/a")
        a(f"| `{axis}` | {question} | " + " | ".join(cells) + " |")
    a("")

    a("## Failures")
    a("")
    any_failure = False
    for r in results:
        bad = r.blockers + r.warnings
        if not bad:
            continue
        any_failure = True
        a(f"### {r.name}")
        a("")
        for o in bad:
            mark = "blocker" if o.severity == "blocker" else "warn"
            a(f"- **{o.case_id}** ({mark}, `{o.kind}`): {o.detail}")
            if o.note:
                a(f"  - why this check exists: {o.note}")
        a("")
    if not any_failure:
        a("None. Either the assistant is in good shape or the golden set is too easy.")
        a("")

    missing = {r.name: r.missing for r in results if r.missing}
    if missing:
        a("## Missing responses")
        a("")
        for name, ids in missing.items():
            a(f"- {name}: {', '.join(ids)}")
        a("")

    path.write_text("\n".join(lines), encoding="utf-8")


def _diff(first: "RunResult", last: "RunResult") -> tuple[set[str], set[str]]:
    f_bad = {o.case_id for o in first.blockers}
    l_bad = {o.case_id for o in last.blockers}
    return f_bad - l_bad, l_bad - f_bad
