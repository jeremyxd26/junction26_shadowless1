"""#417: no answer names an amount and the bank's screen or product in one sentence ("put €360 into monthly
saving" next to a button that leads to investment funds reads like personal investment advice).

- The rule itself (validator.amount_with_bank_product, words shared with the eval in core/answer_text.py),
  with the false rejections it must avoid: the introduction, a decline that names S-Pankki, an amount
  with "saving" in the general sense, "monthly savings", "refund", "an emergency fund".
- At runtime it rejects MODEL drafts only: the retry gets the reason, then the template writes.
- Templates are never replaced for it, so they are held to it here: every recorded tool result through the
  template in English and in Finnish, and the introduction, the thanks and every decline. The two tools
  whose cards carry the `open_host_screen` action are covered with their own fixtures in
  core/tools/tests/test_host_screen_labels_pure.py.
No database, no network."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from agent_fakes import AUG, FakeData, audit_records, run

from core.agent import template
from core.agent.model import FunctionCall, ScriptedModel
from core.agent.validator import allowed_from, amount_with_bank_product
from core.answer_text import amount_beside_bank_product
from core.tools.formatting import display
from core.tools.models import Number, Unit

RECORDINGS = sorted((Path(__file__).parent / "recordings").glob("*.json"))


def num(nid: str, value: str, unit: Unit, language: str = "en") -> Number:
    return Number(id=nid, value=float(value), unit=unit, period=AUG, method="spending.total@1",
                  evidence_ref=f"ev_{nid:0>12}", label="Amount", display=display(Decimal(value), unit, language))


NUMBERS = {"n1": num("n1", "360.00", Unit.EUR_PER_MONTH), "n2": num("n2", "184.61", Unit.EUR),
           "n3": num("n3", "12.5", Unit.PERCENT), "n4": num("n4", "10", Unit.COUNT)}


@pytest.mark.parametrize("text", [
    "Put {{n1}} into monthly saving.",
    "You could move {{n1}} to monthly saving in S-mobiili.",
    "Set aside {{n2}} with S-mobiili each month.",
    "{{n1}} could go into an index fund.",
    "Bonus to fund turns {{n2}} into fund units.",
    "Save {{n1}}; open monthly saving.",                              # a semicolon does not end the sentence
    "Laita {{n1}} kuukausisäästämiseen.",
    "Voisit siirtää {{n2}} S-mobiilissa kuukausisäästämiseen.",
    "Sijoita {{n1}} osakerahastoon.",
    "Bonus rahastoon kerryttää {{n2}}.",
])
def test_an_amount_with_the_bank_screen_or_product_in_one_sentence_is_rejected(text):
    assert amount_with_bank_product(text, NUMBERS)


@pytest.mark.parametrize("text", [
    template.INTRO[0], template.INTRO[1],                             # "an AI money coach inside S-mobiili"
    "I can't help with that here. S-Pankki's customer service can.",  # a decline naming the bank, no amount
    "You could set aside about {{n1}} a month.",                      # an amount and saving in the general sense
    "You could set aside about {{n1}}. The button opens monthly saving in S-mobiili.",   # two sentences
    "You could set aside about {{n1}}.\nSee monthly saving in S-mobiili.",              # a line break ends it too
    "Your monthly savings goal of {{n1}} stays the same.",           # "monthly savings", the general sense
    "That is a monthly saving of {{n1}}.",
    "Your refund of {{n2}} arrived in August 2026.",
    "An emergency fund of {{n2}} covers a surprise.",
    "{{n2}} would be enough to fund the trip.",
    "{{n3}} of your spending went through S-mobiili.",               # a share is not an amount
    "{{n4}} purchases were made in S-mobiili.",                       # a count is not an amount
    "Voisit säästää noin {{n1}} kuukaudessa.",
    "Kuukausisäästösi voisi olla {{n1}}.",                            # kuukausisäästö: the general word
    "Puskurirahasto {{n2}} auttaa yllätyksissä.",                      # a buffer fund is not the bank's fund
])
def test_no_false_rejection(text):
    assert amount_with_bank_product(text, NUMBERS) is None


def test_the_rendered_text_rule_of_the_eval_agrees():
    assert amount_beside_bank_product("Put €360.00 a month into monthly saving.")
    assert amount_beside_bank_product("Laita 360,00\u00a0€ / kk kuukausisäästämiseen.")
    assert amount_beside_bank_product("You could set aside about €360.00 a month. See monthly saving in S-mobiili.") is None
    assert amount_beside_bank_product(template.INTRO[0]) is None


# ---- runtime: model drafts only ---------------------------------------------------------------------------

SPEND = [FunctionCall("fake_spending", {"category": "Restaurants"}), FunctionCall("finish")]
JOINED = {"language": "en", "text": "You spent {{n1}} on restaurants in August 2026. Put {{n1}} into monthly "
                                    "saving in S-mobiili instead.", "cited": ["n1"], "lesson_key": None}
APART = {"language": "en", "text": "In August 2026 you spent {{n1}} on restaurants, over {{n2}} visits.",
         "cited": ["n1", "n2"], "lesson_key": None}


def test_a_model_draft_that_joins_them_is_retried_with_the_reason(make_pipeline):
    model = ScriptedModel(plans=[SPEND], drafts=[JOINED, APART])
    pipe = make_pipeline(model, data=FakeData())
    done = dict(run(pipe))["done"]
    assert done["outcome"] == "answered" and "S-mobiili" not in done["text_rendered"]
    assert done["text_rendered"] == "In August 2026 you spent €147.64 on restaurants, over 10 visits."
    reason = model.compose_inputs[1].validation_errors
    assert len(reason) == 1 and "Put €147.64 into monthly saving in S-mobiili instead." in reason[0]
    attempts = audit_records(pipe)[-1]["composer_attempts"]
    assert attempts[0]["validation"] != "ok" and attempts[1]["validation"] == "ok"


def test_twice_joined_the_template_answers(make_pipeline):
    model = ScriptedModel(plans=[SPEND], drafts=[JOINED, JOINED])
    done = dict(run(make_pipeline(model, data=FakeData())))["done"]
    assert done["outcome"] == "answered" and "llm_unavailable" in done["warnings"]
    assert amount_beside_bank_product(done["text_rendered"]) is None


# ---- templates: never replaced at runtime, so held to the rule here --------------------------------------

def _template_text(views, numbers, language, as_of, question):
    allowed = allowed_from(numbers.values(), views, as_of)
    draft = template.template_draft(views, [], language, allowed, question)
    return draft["text"] if isinstance(draft, dict) else draft


@pytest.mark.parametrize("language", ["en", "fi"])
@pytest.mark.parametrize("path", RECORDINGS, ids=lambda p: p.stem)
def test_the_template_for_each_recorded_tool_result_keeps_amount_and_bank_apart(path, language):
    fixture = json.loads(path.read_text(encoding="utf-8"))
    if not fixture.get("tools"):
        pytest.skip("no tool result in this recording")
    numbers = {n["id"]: Number.model_validate(n) for t in fixture["tools"] for n in t["numbers"]}
    views = [t["model_view"] for t in fixture["tools"]]
    text = _template_text(views, numbers, language, date.fromisoformat(fixture["as_of"]), fixture["question"])
    assert amount_with_bank_product(text, numbers) is None, text


@pytest.mark.parametrize("language", ["en", "fi"])
def test_the_introduction_thanks_and_every_decline_pass(language):
    texts = [template.meta_text("introduce", language), template.meta_text("thanks", language)]
    texts += [template.refusal(kind, language)[0] for kind in template.REFUSAL]
    for text in texts:
        assert amount_with_bank_product(text, {}) is None, text
        assert amount_beside_bank_product(text) is None, text
