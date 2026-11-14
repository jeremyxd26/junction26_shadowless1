"""The effect text of an answer (#382) without a database: built from the real difference, including
no difference at all and a negative result."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from core.tools.formatting import display
from core.tools.label_answer import effect_text
from core.tools.models import Number, Period, Unit

WEEK = Period(start=date(2026, 10, 1), end=date(2026, 10, 7), label="Next 7 days")


def n(value: float) -> Number:
    return Number(value=value, unit=Unit.EUR, period=WEEK, method="safe_to_spend.safe_to_spend_7d_eur@1",
                  evidence_ref="ev_000000000000", label="x", display=display(Decimal(str(value)), Unit.EUR, "en"))


def side(sts: float, save: float = 364.31, reserve: float = 167.74, balance: float = 5000.0,
         budget: float | None = None) -> dict:
    return {"safe_to_spend": ("Safe to spend", n(sts)), "safe_to_save": ("Typically left", n(save)),
            "irregular_reserve": ("Reserve", n(reserve)), "balance_limit": ("Balance", n(balance)),
            "budget_limit": ("Budget", n(sts if budget is None else budget))}


def token(key: str, side_: str) -> str:
    return "{{" + f"{key}.{side_}" + "}}"


def text(before, after, basket, state="answered", language="en") -> str:
    return effect_text(before, after, basket, state, "{{amount}}", token, language)


def test_safe_to_spend_moved_says_from_what_to_what_and_why():
    t = text(side(221.58), side(180.26, reserve=256.3), "unexpected_necessities")
    assert t == ("Left to spend this week goes from {{safe_to_spend.before}} to {{safe_to_spend.after}}: "
                 "{{amount}} now counts as an unexpected necessity, so the reserve grows.")


def test_the_reserve_is_named_only_when_it_grew():
    t = text(side(221.58), side(180.26), "unexpected_necessities")
    assert t.endswith("{{amount}} now counts as an unexpected necessity.") and "reserve" not in t


def test_zero_difference_says_why_by_the_binding_limit():
    budget_bound = text(side(221.58, balance=5000.0, budget=221.58), side(221.58, balance=5000.0, budget=221.58),
                        "everyday_spending")
    assert budget_bound == ("{{amount}} now counts as everyday spending. This does not change what is left to spend "
                            "this week: your monthly budget, not this purchase, sets the limit.")
    balance_bound = text(side(40.0, balance=40.0, budget=300.0), side(40.0, balance=40.0, budget=300.0),
                         "everyday_spending", language="fi")
    assert balance_bound.endswith("saldosi asettaa rajan, ja tämä ostos näkyy siinä jo.")


def test_safe_to_save_moving_alone_is_said_without_adding_the_two():
    t = text(side(221.58, save=364.31), side(221.58, save=184.61), "unexpected_necessities")
    assert t.endswith("Left to spend this week stays the same, but what you can typically put aside goes from "
                      "{{safe_to_save.before}} to {{safe_to_save.after}}.")


def test_a_negative_result_keeps_its_sign_and_the_undo_reads_back():
    down = text(side(30.0, balance=30.0, budget=300.0), side(-15.0, balance=-15.0, budget=300.0, reserve=200.0),
                "unexpected_necessities")
    assert "goes from {{safe_to_spend.before}} to {{safe_to_spend.after}}" in down
    assert n(-15.0).display == "-€15.00"                          # the token's display carries the minus
    undo = text(side(-15.0, balance=-15.0, budget=300.0), side(30.0, balance=30.0, budget=300.0), None, "pending")
    assert undo.endswith("{{amount}} is waiting for your answer again.")
    closed = text(side(30.0), side(30.0), None, "closed", language="fi")
    assert closed.startswith("{{amount}} on taas siinä ryhmässä, johon säännöt sen sijoittavat.")


def test_two_sentences_and_three_numbers_at_most():
    import re
    for before, after, basket in [(side(221.58), side(180.26, reserve=256.3), "unexpected_necessities"),
                                  (side(221.58, save=364.31), side(221.58, save=184.61), "unexpected_necessities"),
                                  (side(221.58), side(221.58), "everyday_spending")]:
        for lang in ("en", "fi"):
            t = text(before, after, basket, language=lang)
            assert len(re.findall(r"[.?](?=\s|$)", t)) <= 2 and len(re.findall(r"\{\{[^}]+\}\}", t)) <= 3
