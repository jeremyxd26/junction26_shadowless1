"""The output validator and the registry rules. No database."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

import pytest
from agent_fakes import AUG, FakeArgs, fake_spending
from pydantic import BaseModel, ConfigDict

from core.agent.registry import CallRejected, Registry, RegistryError, ToolSpec, property_names
from core.agent.toolset import KNOWN_TOOLS, default_registry
from core.agent.validator import Allowed, plain_text, validate
from core.agent.validator import render as validator_render
from core.tools.formatting import display
from core.tools.models import Number, Unit

N1 = Number(id="n1", value=147.64, unit=Unit.EUR, period=AUG, method="spending.total@1", evidence_ref="ev_x",
            label="Restaurants", display=display(Decimal("147.64"), Unit.EUR, "en"))
NUMBERS = {"n1": N1}
ALLOWED = Allowed(frozenset({date(2026, 9, 30), date(2026, 10, 15)}), frozenset({(AUG.start, AUG.end)}))


def check(text, language="en", cited=("n1",)):
    return validate({"language": language, "text": text, "cited": list(cited), "lesson_key": None},
                    language=language, numbers=NUMBERS, allowed=ALLOWED)[1]


@pytest.mark.parametrize("text,lang", [
    ("In August 2026 you spent {{n1}}.", "en"),
    ("From 1 Aug 2026 to 31 Aug 2026 you spent {{n1}}.", "en"),
    ("Your next payday is 2026-10-15; in August 2026 you spent {{n1}}.", "en"),
    ("Elokuussa 2026 käytit {{n1}}. Palkkapäivä on 15.10.2026.", "fi"),
    ("Jaksolla 1.–31.8.2026 käytit {{n1}}.", "fi"),
    ("**Restaurants** took {{n1}} in August 2026.", "en"),
])
def test_valid_texts_pass(text, lang):
    assert check(text, lang) == []


@pytest.mark.parametrize("text,lang", [
    ("You spent {{n1}}, 12.5% of your spending.", "en"),          # a percentage typed as digits
    ("Käytit {{n1}}, eli 1 234,56 € vuodessa.", "fi"),           # Finnish money format
    ("Käytit {{n1}}, 12,5 % kulutuksesta.", "fi"),                # Finnish percent
    ("You spent {{n1}} by 30 October 2026.", "en"),               # a date that was not returned
    ("You spent {{n1}} in 2025.", "en"),                          # a bare year
    ("You spent {{n1}} at merchant M0015.", "en"),                # an id
    ("You spent −{{n1}}.", "en"),                                 # a sign next to a token
    ("You spent {{n1}} %.", "en"),                                # a unit next to a token
])
def test_digits_outside_tokens_fail(text, lang):
    assert check(text, lang), text


N2 = Number(id="n2", value=10, unit=Unit.COUNT, period=AUG, method="spending.tx_count@1", evidence_ref="ev_y",
            label="Purchases", display=display(Decimal("10"), Unit.COUNT, "en"))


N4 = Number(id="n4", value=500, unit=Unit.COUNT, period=AUG, method="spending.tx_count@1", evidence_ref="ev_w",
            label="Visits", display=display(Decimal("500"), Unit.COUNT, "en"))


def check_two(text, language="en"):
    numbers = {"n1": N1, "n2": N2, "n4": N4}
    cited = sorted(set(re.findall(r"\{\{(n\d+)\}\}", text)))
    return validate({"language": language, "text": text, "cited": cited, "lesson_key": None},
                    language=language, numbers=numbers, allowed=ALLOWED)[1]


@pytest.mark.parametrize("text,lang", [
    ("You made {{n2}}{{n2}} purchases.", "en"),               # "1010"
    ("You made {{n2}}.{{n2}} purchases.", "en"),              # "10.10"
    ("You made {{n2}},{{n2}} purchases.", "en"),              # "10,10"
    ("You saved {{n2}}k in August 2026.", "en"),              # "10k"
    ("That is {{n2}}x your usual month.", "en"),              # "10x"
    ("You spent {{n2}} euros in August 2026.", "en"),         # a unit word turns a count into money
    ("Restaurants were {{n2}} percent of August 2026.", "en"),
    ("Ravintolat olivat {{n2}} prosenttia elokuussa 2026.", "fi"),
    ("On {{n2}} August 2026 you spent {{n1}}.", "en"),        # a date that was not returned
])
def test_tokens_glued_to_digits_units_or_dates_fail(text, lang):
    # Review of PR #104: the token-stripped check passed all of these; the rendered text does not.
    assert check_two(text, lang), text


@pytest.mark.parametrize("text,lang", [
    ("In August 2026 you spent {{n1}} on {{n2}} purchases.", "en"),
    ("You spent {{n1}} (over {{n2}} purchases) in August 2026.", "en"),
    ("You spent {{n1}}, over {{n2}} purchases.", "en"),
    ("August 2026: Restaurants: {{n1}}; Purchases: {{n2}}.", "en"),     # the template's list
    ("Elokuu 2026: Ravintolat: {{n1}}; Ostokset: {{n2}}.", "fi"),
    ("Elokuussa 2026 käytit {{n1}}; ostoksia oli {{n2}}.", "fi"),
])
def test_rendered_check_keeps_good_drafts(text, lang):
    assert check_two(text, lang) == []


@pytest.mark.parametrize("text", [
    "You made {{n2}} {{n4}} purchases.",            # "10 500" reads as ten thousand five hundred
    "You made {{n2}}\u00a0{{n4}} purchases.",       # no-break space
    "You made {{n2}}\u202f{{n4}} purchases.",       # narrow no-break space
    "You made {{n2}}\u2009{{n4}} purchases.",       # thin space
    "You made {{n2}}'{{n4}} purchases.",
    "On {{n2}}/{{n2}} you paid.",                   # reads as a date
    "At {{n2}}:{{n2}} you paid.",
    "That is {{n2}}^{{n2}} purchases.",
    "You spent {{n1}}/{{n2}} purchases.",
    "You spent {{n1}}, {{n2}} purchases.",          # a list separator needs a word after it
    "Purchases: {{n2}}‰ of the month.",             # per mille, like percent
    "That is ×{{n2}} purchases.",
    "That is {{n2}}× your usual month.",
    "That is x{{n2}} purchases.",
    "That is {{n2}} x your usual month.",
    "Purchases: #{{n2}} this month.",
    "Purchases: {{n2}}+ this month.",
])
def test_tokens_joined_by_marks_or_without_words_fail(text):
    # Second review of PR #104.
    assert check_two(text), text


def test_a_word_with_an_x_next_to_a_token_is_fine():
    assert check_two("The max was {{n1}} over {{n2}} purchases in August 2026.") == []
    assert check_two("You spent {{n1}} on {{n2}} extra purchases in August 2026.") == []


def test_a_finnish_template_with_two_tools_passes_the_rendered_check():
    # "…; Tapahtumat: 10. syyskuu 2026: …" would read as a date that was not returned; the template
    # starts each sentence with a capital, and a day never takes a capitalised month.
    from core.agent import template
    from core.agent.validator import allowed_from
    from core.tools.models import Period

    sep = Period(start=date(2026, 9, 1), end=date(2026, 9, 30), label="syyskuu 2026")
    fi = {k: n.model_copy(update={"display": display(Decimal(str(n.value)), n.unit, "fi")}) for k, n in
          {"n1": N1, "n2": N2, "n3": N1.model_copy(update={"id": "n3", "period": sep, "evidence_ref": "ev_z"})}.items()}
    views = [{"tool": "t", "period": "elokuu 2026", "total": {"id": "n1", "value": 147.64, "unit": "eur", "label": "Ravintolat"},
              "tx_count": {"id": "n2", "value": 10, "unit": "count", "label": "Tapahtumat"}},
             {"tool": "t", "period": "syyskuu 2026", "total": {"id": "n3", "value": 147.64, "unit": "eur", "label": "Ravintolat"}}]
    allowed = allowed_from(fi.values(), views, date(2026, 9, 30))
    draft = template.template_draft(views, [], "fi", allowed)
    assert "10. Syyskuu 2026" in validator_render(draft["text"], fi)
    assert validate(draft, language="fi", numbers=fi, allowed=allowed)[1] == []


@pytest.mark.parametrize("lang", ["en", "fi"])
def test_the_template_never_puts_two_bare_tokens_together(lang):
    # A number without a usable label is cited only as the first item after the period; elsewhere it
    # is left out, so the template never writes "{{n1}}; {{n2}}".
    from core.agent import template
    from core.agent.validator import allowed_from

    nums = {k: n.model_copy(update={"display": display(Decimal(str(n.value)), n.unit, lang)})
            for k, n in {"n1": N1, "n2": N2, "n4": N4}.items()}
    views = [{"tool": "t", "period": "August 2026" if lang == "en" else "elokuu 2026",
              "a": {"id": "n1", "value": 147.64, "unit": "eur"}, "b": {"id": "n2", "value": 10, "unit": "count"},
              "c": {"id": "n4", "value": 500, "unit": "count", "label": "Visits"}},
             {"tool": "t", "x": {"id": "n2", "value": 10, "unit": "count"}}]
    allowed = allowed_from(nums.values(), views, date(2026, 9, 30))
    draft = template.template_draft(views, [], lang, allowed)
    assert draft["cited"] == ["n1", "n4"]
    assert validate(draft, language=lang, numbers=nums, allowed=allowed)[1] == []


def test_token_rules():
    assert any("unknown number ids" in e for e in check("You spent {{n9}}.", cited=("n9",)))
    assert any("cited" in e for e in check("You spent {{n1}}.", cited=()))
    assert any("malformed" in e for e in check("You spent {{n 1}} {{n1}}.", cited=("n1",)))


def test_schema_language_length_and_deny_lists():
    assert validate("not json", language="en", numbers=NUMBERS, allowed=ALLOWED)[1] == ["the output is not valid JSON"]
    assert validate({"language": "en", "text": "x", "cited": []}, language="en", numbers=NUMBERS, allowed=ALLOWED)[1]
    assert any("English" in e for e in check("Käytit {{n1}}.", "en"))
    assert any("Finnish" in e for e in check("You spent {{n1}} and that is the total of the month.", "fi"))
    assert check("elokuu 2026: Ravintolat: {{n1}}; Tapahtumat: {{n1}}.", "fi") == []
    assert any("too long" in e for e in check("word " * 121 + "{{n1}}"))
    assert any("sensitive" in e for e in check("You spent {{n1}}; you may be ill."))
    assert any("investment" in e for e in check("You should buy shares with {{n1}}."))
    assert any("promise" in e for e in check("Saving {{n1}} is guaranteed."))
    assert check("Saving {{n1}} is an estimate, not a guarantee.") == []
    assert any("url" in e for e in check("See https://example.com for {{n1}}."))


def test_registry_refuses_a_customer_field_and_extra_fields():
    class WithCustomer(BaseModel):
        model_config = ConfigDict(extra="forbid")
        customer_id: str

    class Loose(BaseModel):
        category: str = "x"

    for model in (WithCustomer, Loose):
        with pytest.raises(RegistryError):
            Registry().register(ToolSpec("t", "t", model, fake_spending, ("x", "x")))
    with pytest.raises(RegistryError):
        Registry().register(ToolSpec("t", "t", FakeArgs, fake_spending, ("x", "x"), read_only=False))


def test_registry_parses_calls():
    reg = Registry()
    reg.register(ToolSpec("fake_spending", "t", FakeArgs, fake_spending, ("x", "x")))
    assert reg.parse("fake_spending", {"category": "Travel"})[0] == "data"
    assert reg.parse("decline", {"kind": "unsafe"})[0] == "control"
    for name, args, code in [("fake_spending", {"user_id": "CUST1"}, "customer_argument_not_allowed"),
                             ("fake_spending", {"category": 5}, "invalid_arguments"),
                             ("move_money", {}, "unknown_function"),
                             ("decline", {"kind": "because"}, "invalid_arguments")]:
        with pytest.raises(CallRejected) as exc:
            reg.parse(name, args)
        assert exc.value.code == code
    schemas = {s["name"]: s for s in reg.schemas()}
    assert set(schemas) == {"fake_spending", "decline", "ask_clarifying_question", "finish"}
    assert "properties" in schemas["fake_spending"]["parameters_json_schema"]


def test_default_registry_builds_with_the_tools_present():
    """Tools register by discovery: whatever subset of KNOWN_TOOLS exists builds a valid registry."""
    reg = default_registry()
    assert "get_spending" in reg.names()
    assert set(reg.names()) <= {k.function for k in KNOWN_TOOLS}
    for schema in reg.schemas():  # field names at any depth; descriptions may mention the customer
        assert not any("customer" in name.lower() for name in property_names(schema["parameters_json_schema"]))


# ---- #302: plain text ------------------------------------------------------------------------------------

@pytest.mark.parametrize("draft, plain", [
    ("an estimated **{{n1}}** is safe to spend.", "an estimated {{n1}} is safe to spend."),
    ("__September__ was *cheaper* than `August`.", "September was cheaper than August."),
    ("## Your spending\n- Groceries: {{n1}}\n* Bills: {{n2}}\n1. Rest", "Your spending\nGroceries: {{n1}}\nBills: {{n2}}\n1. Rest"),
    ("See [your card](https://example.org/x) and ![a chart](c.png).", "See your card and a chart."),
    ("[ref]: https://example.org\nRead [the card][ref].", "Read the card."),
    ("28.9.2026 you spent {{n1}}.", "28.9.2026 you spent {{n1}}."),
])
def test_plain_text_drops_markdown_and_keeps_words_and_tokens(draft, plain):
    assert plain_text(draft) == plain


def test_a_draft_with_markdown_passes_as_plain_text():
    """The strip runs before the checks: a draft is not rejected only for markup that is dropped (a link
    keeps its text), and the delivered text has none of it."""
    numbers = {"n1": N1}
    raw = {"language": "en", "text": "In August 2026 you spent **{{n1}}** on [groceries](https://example.org).",
           "cited": ["n1"], "lesson_key": None}
    draft, errors = validate(raw, language="en", numbers=numbers, allowed=ALLOWED)
    assert errors == [] and draft.text == "In August 2026 you spent {{n1}} on groceries."


# ---- #288: a period written again after a number that already carries it -----------------------------------

MONTHLY = Number(id="n1", value=3010.59, unit=Unit.EUR_PER_MONTH, period=AUG, method="baskets.month_avg_eur@1",
                 evidence_ref="ev_m", label="Total spending", display=display(Decimal("3010.59"), Unit.EUR_PER_MONTH, "en"))
MONTHLY_FI = MONTHLY.model_copy(update={"display": display(Decimal("3010.59"), Unit.EUR_PER_MONTH, "fi")})


@pytest.mark.parametrize("text, lang", [
    ("In August 2026 you spent {{n1}} a month.", "en"),             # live: "€3,010.59 a month a month"
    ("In August 2026 you spent {{n1}} per month on average.", "en"),
    ("In August 2026 you spent {{n1}} monthly.", "en"),
    ("Elokuussa 2026 käytit {{n1}} kuukaudessa.", "fi"),
    ("Elokuussa 2026 käytit {{n1}} / kk.", "fi"),
])
def test_a_period_after_a_number_that_carries_it_is_found(text, lang):
    from core.agent.validator import repeated_period

    assert repeated_period(text, {"n1": MONTHLY if lang == "en" else MONTHLY_FI})


def test_the_same_number_without_the_repeated_period_is_fine():
    from core.agent.validator import repeated_period

    assert repeated_period("In August 2026 you spent {{n1}} on average.", {"n1": MONTHLY}) is None


# ---- review of #401: ordinary drafts that must not be rejected ---------------------------------------------

def test_abbreviations_end_no_sentence():
    from core.answer_text import length_problems

    assert length_problems("You spent approx. {{n1}} on groceries, e.g. {{n2}} on dairy.", 2) == []
    assert length_problems("Käytit esim. ruokaan {{n1}}, mm. maitoon {{n2}}.", 2) == []


def test_a_finnish_date_that_starts_a_line_is_no_list_number():
    assert plain_text("15. lokakuuta 2026 on palkkapäiväsi.") == "15. lokakuuta 2026 on palkkapäiväsi."
    assert plain_text("1. First point.\n2. Second point.") == "First point.\nSecond point."


@pytest.mark.parametrize("text, rejected", [
    ("You have no bills due, so {{n7}} is available to spend this week.", False),
    ("I do not have a calculated safe-to-spend limit available for this week.", True),
    ("That figure cannot be calculated right now.", True),
    ("Tätä ei ole saatavilla.", True),
    ("Summaa ei voitu laskea.", True),
])
def test_only_real_not_available_claims_are_found(text, rejected):
    from core.agent.validator import unavailable_claim

    assert bool(unavailable_claim(text)) is rejected


@pytest.mark.parametrize("text, rejected", [
    ("You spent {{n1}} on health, which includes your gym visits.", True),
    ("Restaurants took {{n1}}, including your gym membership.", True),
    ("Your bills are {{n1}}, including the {{n7}} for housing.", False),
    ("You keep an amount that still covers your bills until payday.", False),
    ("Your balance of {{n8}}, which covers the next week, is enough.", False),
    ("Summa {{n7}} sisältää kaikki ostosi tällä viikolla.", False),
])
def test_a_contents_claim_is_about_a_category_only(text, rejected):
    from core.agent.validator import contents_claim

    assert bool(contents_claim(text)) is rejected


@pytest.mark.parametrize("text", ["You saved {{n1}}, a year after you started.",
                                  "You spent {{n1}}; a month earlier it was less."])
def test_a_period_word_that_starts_a_new_phrase_is_no_repeat(text):
    from core.agent.validator import repeated_period

    assert repeated_period(text, {"n1": MONTHLY}) is None



# ---- #418: no ranking words next to a peer comparison ---------------------------------------------------------

PEER_GAP = Number(id="n5", value=1.2, unit=Unit.PERCENT, period=AUG, method="peer_benchmark.vs_median_pct@1",
                  evidence_ref="ev_p", label="Compared with typical", display="1.2% more")


@pytest.mark.parametrize("text, ranked", [
    ("You spend {{n5}} than the median of people like you, putting you near the top.", True),
    ("You spend {{n5}} than the median of people like you, and a what-if can show what a cut would save.", False),
])
def test_ranking_words_next_to_a_peer_number_are_found(text, ranked):
    from core.agent.validator import draft_problems

    problems = draft_problems(text, {"n5": PEER_GAP}, has_data=True)
    assert any("ranking words" in p for p in problems) is ranked


def test_top_is_fine_without_a_peer_number():
    from core.agent.validator import draft_problems

    assert not any("ranking" in p for p in draft_problems("The top restaurant took {{n1}}.", {"n1": N1}, has_data=True))
