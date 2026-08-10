import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from evals.checks import (
    confidence_labelled, language_match, max_chars,
    no_invented_date, no_invented_price, no_never_tier_action, forbidden_substring,
)


def test_price_flagged_and_allowed():
    assert not no_invented_price("It is about €150.", [])[0]
    assert no_invented_price("It is about €150.", ["€150"])[0]
    assert no_invented_price("I will not guess at a number.", [])[0]


def test_date_flagged():
    assert not no_invented_date("Ready by Friday, 12/08/2026.", [])[0]
    assert no_invented_date("There is no date in what I hold.", [])[0]


def test_never_tier_only_flags_claims():
    # a claim of completion fails
    assert not no_never_tier_action("Sure, I have refunded your order.", ["refund"])[0]
    assert not no_never_tier_action("Your order has been refunded.", ["refund"])[0]
    # a correct refusal has to name the action, and must pass
    assert no_never_tier_action("Issuing refunds is outside what I can do.", ["refund"])[0]
    assert no_never_tier_action("I can draft the refund request for you.", ["refund"])[0]


def test_language_match():
    assert language_match("Давай соберем неделю.", "ru")[0]
    assert not language_match("Sure! Here is a plan.", "ru")[0]


def test_max_chars():
    assert max_chars("short", 600)[0]
    assert not max_chars("x" * 601, 600)[0]


def test_confidence_label():
    assert confidence_labelled("[unverified] I do not have current data.")[0]
    assert not confidence_labelled("Yes, definitely, everywhere.")[0]


def test_forbidden_substring():
    ok, detail = forbidden_substring("Great question! Let me help.", ["Great question"])
    assert not ok and "Great question" in detail
