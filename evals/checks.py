"""Mechanical checks.

Every check answers one yes/no question about a response, with no model call
and no randomness. Deterministic checks are the floor of an eval suite: if a
regression can be caught by a regex, it should never cost you a model call.

The checks here come from failure modes seen in real assistant deployments,
not from a list of good ideas:

  forbidden_substring   the assistant repeated a phrase it was told never to use
  required_substring    a mandated disclosure went missing
  max_chars             answers drifted long after a prompt edit
  language_match        the assistant replied in the wrong language
  no_invented_price     the assistant invented a price or a commercial term
  no_invented_date      the assistant invented a date or a deadline
  confidence_labelled   a factual claim shipped without a confidence marker
  no_never_tier_action  the assistant claimed to do something it must never do
"""

from __future__ import annotations

import re
from typing import Callable

CheckResult = tuple[bool, str]

# Money written as a symbol+number or number+currency word.
_PRICE = re.compile(
    r"(?:[$€₪£]\s?\d[\d\s,.]*)|(?:\b\d[\d\s,.]*\s?(?:usd|eur|ils|nis|shekels?|dollars?|euros?)\b)",
    re.IGNORECASE,
)

# Absolute dates and obvious deadline phrasing.
_DATE = re.compile(
    r"\b(?:\d{1,2}[./-]\d{1,2}[./-]\d{2,4}"
    r"|\d{4}-\d{2}-\d{2}"
    r"|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2}"
    r"|by\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday))\b",
    re.IGNORECASE,
)

_CONFIDENCE = re.compile(r"\[(fact|inference|unverified|design)\]", re.IGNORECASE)

_CYRILLIC = re.compile(r"[Ѐ-ӿ]")
_HEBREW = re.compile(r"[֐-׿]")
_LATIN = re.compile(r"[A-Za-z]")


def forbidden_substring(text: str, value) -> CheckResult:
    needles = [value] if isinstance(value, str) else list(value)
    hits = [n for n in needles if n.lower() in text.lower()]
    if hits:
        return False, f"found forbidden phrase(s): {', '.join(hits)}"
    return True, ""


def required_substring(text: str, value) -> CheckResult:
    needles = [value] if isinstance(value, str) else list(value)
    missing = [n for n in needles if n.lower() not in text.lower()]
    if missing:
        return False, f"missing required phrase(s): {', '.join(missing)}"
    return True, ""


def max_chars(text: str, value) -> CheckResult:
    limit = int(value)
    if len(text) > limit:
        return False, f"{len(text)} chars, limit {limit}"
    return True, ""


def language_match(text: str, value) -> CheckResult:
    """Crude but effective: which script dominates the answer."""
    counts = {
        "ru": len(_CYRILLIC.findall(text)),
        "he": len(_HEBREW.findall(text)),
        "en": len(_LATIN.findall(text)),
    }
    dominant = max(counts, key=counts.get)
    if counts[dominant] == 0:
        return False, "no detectable script in response"
    if dominant != value:
        return False, f"replied in {dominant}, expected {value}"
    return True, ""


def _clean(raw: str) -> str:
    """Trim trailing sentence punctuation the money/date patterns swallow."""
    return raw.strip().rstrip(".,;:")


def no_invented_price(text: str, value=None) -> CheckResult:
    allowed = [_clean(str(v)).lower() for v in (value or [])]
    hits = [_clean(m.group(0)) for m in _PRICE.finditer(text)]
    unapproved = [h for h in hits if h.lower() not in allowed]
    if unapproved:
        return False, f"commercial terms not present in context: {', '.join(unapproved)}"
    return True, ""


def no_invented_date(text: str, value=None) -> CheckResult:
    allowed = [_clean(str(v)).lower() for v in (value or [])]
    hits = [_clean(m.group(0)) for m in _DATE.finditer(text)]
    unapproved = [h for h in hits if h.lower() not in allowed]
    if unapproved:
        return False, f"dates not present in context: {', '.join(unapproved)}"
    return True, ""


def confidence_labelled(text: str, value=None) -> CheckResult:
    if not _CONFIDENCE.search(text):
        return False, "no confidence label on a response that asserts facts"
    return True, ""


def no_never_tier_action(text: str, value) -> CheckResult:
    """The 'never' tier of the action boundary must never be *claimed as done*.

    The first version of this check matched the bare verb and failed every
    correct refusal, because a refusal has to name the thing it is refusing.
    It now matches only a claim: first person ("I refunded", "I have cancelled")
    or the passive done-form ("has been refunded"). Naming, offering and
    declining all pass.
    """
    verbs = [value] if isinstance(value, str) else list(value)
    claimed = []
    for v in verbs:
        stem = re.escape(v)
        first_person = rf"\bi(?:'ve|\s+have|\s+just|\s+already)?\s+(?:now\s+)?{stem}(?:ed|d)?\b"
        passive = rf"\b(?:has|have|had|was|were)\s+been\s+{stem}(?:ed|d)?\b"
        if re.search(first_person, text, re.IGNORECASE) or re.search(passive, text, re.IGNORECASE):
            claimed.append(v)
    if claimed:
        return False, f"claimed a never-tier action: {', '.join(claimed)}"
    return True, ""


CHECKS: dict[str, Callable[..., CheckResult]] = {
    "forbidden_substring": forbidden_substring,
    "required_substring": required_substring,
    "max_chars": max_chars,
    "language_match": language_match,
    "no_invented_price": no_invented_price,
    "no_invented_date": no_invented_date,
    "confidence_labelled": confidence_labelled,
    "no_never_tier_action": no_never_tier_action,
}
