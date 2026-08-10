"""The judged half of the suite.

Five questions, taken verbatim from the check-in I run with every client at
day 3 and week 2 after handover. They were a conversation before they were a
rubric; turning them into a 0-2 scale is what made two deliveries comparable.

Scoring is pluggable on purpose. The offline scorer keeps the suite runnable
in CI with no key and no spend; the model scorer is for the real run. Both
return the same shape, so a report never has to know which one produced it.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Protocol

QUESTIONS = {
    "usage": "Would this answer make the user come back tomorrow, or quietly stop opening the chat?",
    "usefulness": "Does it close the task, or does it hand the work back to the user?",
    "voice": "Does it sound like the person's own assistant, or like a generic bot?",
    "failure": "Is anything here generic, evasive, or irritating?",
    "recommend": "Would the user show this answer to someone else?",
}

SCALE = {0: "fails", 1: "passable", 2: "good"}


@dataclass(frozen=True)
class RubricScore:
    case_id: str
    scores: dict[str, int]
    comment: str = ""

    @property
    def total(self) -> int:
        return sum(self.scores.values())

    @property
    def max_total(self) -> int:
        return 2 * len(self.scores)


class Scorer(Protocol):
    name: str

    def score(self, case_id: str, user_turn: str, response: str) -> RubricScore: ...


class HeuristicScorer:
    """Offline scorer. Not a judge, a smoke alarm.

    It penalises the three things that showed up most often in bad answers:
    hedging, handing the task back, and generic filler. It is good enough to
    catch a regression in CI and nowhere near good enough to rank two decent
    answers. Do not report its numbers as quality.
    """

    name = "heuristic"

    _HEDGE = re.compile(
        r"\b(it depends|there are many|generally speaking|as an ai|i cannot|various factors)\b",
        re.IGNORECASE,
    )
    _HANDBACK = re.compile(
        r"\b(you (?:could|should|might want to) (?:try|consider|look into)|"
        r"consider (?:consulting|researching)|do your own research)\b",
        re.IGNORECASE,
    )
    _FILLER = re.compile(
        r"\b(great question|i'd be happy to|certainly|absolutely|let's dive in|in today's world)\b",
        re.IGNORECASE,
    )

    def score(self, case_id: str, user_turn: str, response: str) -> RubricScore:
        hedges = len(self._HEDGE.findall(response))
        handbacks = len(self._HANDBACK.findall(response))
        fillers = len(self._FILLER.findall(response))
        concrete = len(re.findall(r"\d", response))

        usefulness = 2 if handbacks == 0 else (1 if handbacks == 1 else 0)
        voice = 2 if fillers == 0 else (1 if fillers == 1 else 0)
        failure = 2 if hedges == 0 else (1 if hedges == 1 else 0)
        usage = 2 if (handbacks == 0 and fillers == 0) else 1
        # An answer worth showing to someone else has none of the three tells.
        # Concreteness (a number, a name, a next step) is a bonus, never a
        # requirement: the first version demanded a digit and punished good
        # short answers that happened not to contain one.
        problems = hedges + handbacks + fillers
        recommend = 2 if problems == 0 else (1 if problems == 1 else 0)
        if problems == 0 and concrete == 0 and len(response) < 40:
            recommend = 1  # too thin to forward

        notes = []
        if hedges:
            notes.append(f"{hedges} hedge(s)")
        if handbacks:
            notes.append(f"{handbacks} hand-back(s)")
        if fillers:
            notes.append(f"{fillers} filler phrase(s)")

        return RubricScore(
            case_id=case_id,
            scores={
                "usage": usage,
                "usefulness": usefulness,
                "voice": voice,
                "failure": failure,
                "recommend": recommend,
            },
            comment="; ".join(notes),
        )


class AnthropicScorer:
    """Model-graded scoring for the real run.

    Kept deliberately thin. The prompt asks for the five numbers and nothing
    else, because a judge that is allowed to write prose will write prose
    instead of scoring.
    """

    name = "claude"

    def __init__(self, model: str = "claude-sonnet-4-5", api_key: str | None = None):
        self.model = model
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set")

    def _prompt(self, user_turn: str, response: str) -> str:
        lines = "\n".join(f"{k}: {v}" for k, v in QUESTIONS.items())
        return (
            "Score the assistant response on five axes, 0 to 2 each.\n"
            "0 fails, 1 passable, 2 good.\n\n"
            f"{lines}\n\n"
            f"USER TURN:\n{user_turn}\n\nASSISTANT RESPONSE:\n{response}\n\n"
            "Reply with one JSON object and nothing else: "
            '{"usage":int,"usefulness":int,"voice":int,"failure":int,'
            '"recommend":int,"comment":"under 15 words"}'
        )

    def score(self, case_id: str, user_turn: str, response: str) -> RubricScore:
        import json
        import urllib.request

        body = json.dumps(
            {
                "model": self.model,
                "max_tokens": 300,
                "messages": [{"role": "user", "content": self._prompt(user_turn, response)}],
            }
        ).encode()
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=body,
            headers={
                "content-type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            },
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read())
        text = payload["content"][0]["text"]
        data = json.loads(re.search(r"\{.*\}", text, re.S).group(0))
        comment = str(data.pop("comment", ""))
        return RubricScore(
            case_id=case_id,
            scores={k: int(v) for k, v in data.items() if k in QUESTIONS},
            comment=comment,
        )
