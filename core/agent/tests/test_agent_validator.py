"""The output validator and the registry rules. No database."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from conftest import AUG, FakeArgs, fake_spending
from pydantic import BaseModel, ConfigDict

from core.agent.registry import CallRejected, Registry, RegistryError, ToolSpec, property_names
from core.agent.toolset import KNOWN_TOOLS, default_registry
from core.agent.validator import Allowed, validate
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
