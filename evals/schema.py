"""Data model for the eval suite.

A Case is one thing an assistant must get right. It carries the user turn,
whatever context the assistant is supposed to have, and a list of
expectations that can be checked mechanically.

Expectations are deliberately boring. Anything an LLM has to judge belongs in
the rubric (see rubric.py), not here. Mixing the two is how eval suites start
lying to you.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator


@dataclass(frozen=True)
class Expectation:
    """One mechanical assertion about a response.

    kind         name of a check registered in checks.CHECKS
    value        argument for that check (string, list, int, ...)
    severity     "blocker" fails the case outright; "warn" is recorded only
    note         why this expectation exists, for the report
    """

    kind: str
    value: Any = None
    severity: str = "blocker"
    note: str = ""

    def __post_init__(self) -> None:
        if self.severity not in ("blocker", "warn"):
            raise ValueError(f"unknown severity: {self.severity}")


@dataclass(frozen=True)
class Case:
    id: str
    user_turn: str
    expectations: list[Expectation]
    context: str = ""
    tags: list[str] = field(default_factory=list)
    language: str = "en"

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> "Case":
        return Case(
            id=raw["id"],
            user_turn=raw["user_turn"],
            context=raw.get("context", ""),
            tags=list(raw.get("tags", [])),
            language=raw.get("language", "en"),
            expectations=[
                Expectation(
                    kind=e["kind"],
                    value=e.get("value"),
                    severity=e.get("severity", "blocker"),
                    note=e.get("note", ""),
                )
                for e in raw.get("expectations", [])
            ],
        )


@dataclass(frozen=True)
class Response:
    """One assistant answer to one case, produced by some version of the system."""

    case_id: str
    text: str
    run: str


def load_cases(path: str | Path) -> list[Case]:
    return [Case.from_dict(row) for row in _read_jsonl(path)]


def load_responses(path: str | Path, run: str) -> dict[str, Response]:
    out: dict[str, Response] = {}
    for row in _read_jsonl(path):
        out[row["case_id"]] = Response(case_id=row["case_id"], text=row["text"], run=run)
    return out


def _read_jsonl(path: str | Path) -> Iterator[dict[str, Any]]:
    with open(path, encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, 1):
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no} is not valid JSON") from exc
