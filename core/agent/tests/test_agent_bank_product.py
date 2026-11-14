"""#417: no answer puts an amount into the bank's screen or product in one sentence ("put €360 into monthly
saving" next to a button that leads to investment funds reads like personal investment advice).

- The rule itself (validator.amount_with_bank_product, words shared with the eval in core/answer_text.py). It
  fires on DESTINATION or ACTION uses only (decided in the review of #475): a plain statement of a
  figure passes. The lists below are the reviewer's drafts of that review, verbatim, plus earlier ones.
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


REJECTED = [
    # the review of #475, rejected on b6a8ff5 and still rejected
    "Put {{n1}} into monthly saving in S-mobiili.",
    "Open monthly saving and set {{n1}} a month.",
    "Siirrä {{n1}} kuukausisäästöön.",
    "Start saving {{n1}} a month in S-mobiili",
    "Aloita säästäminen {{n1}} kuukaudessa S-mobiilissa.",
    "Invest {{n1}} a month in funds.",
    "Put {{n1}} in an index fund.",
    "Put {{n1}} into a mutual fund.",
    "Put {{n1}} in the fund.",
    "Buy fund units for {{n1}}.",
    "You could put {{n1}} into monthly savings.",
    "Sijoita {{n1}} rahastoon.",
    "Sijoitusrahastoon voisit laittaa {{n1}}.",
    "Laita {{n1}} kuukausisäästöön S-mobiilissa.",
    "Laita {{n1}} säästöön S-mobiilissa.",
    "Move your Bonus to fund: {{n1}}.",
    "Go to s-mobiili and save {{n1}}.",
    "An investment fund with {{n1}} a month would grow.",          # a named investment product beside an amount
    "Save {{n1}} a month into your fund.",
    "Transfer {{n1}} to your monthly saving.",
    "Kuukausisäästämiseen sopii {{n1}}.",                          # the illative is a destination by itself
    # the review of #475, missed on b6a8ff5
    "You could move {{n1}} to a fund.",
    "Send {{n1}} to your fund every month.",
    "Open the monthly-saving screen and add {{n1}}.",
    # earlier ones
    "Put {{n1}} into monthly saving.",
    "You could move {{n1}} to monthly saving in S-mobiili.",
    "Set aside {{n2}} with S-mobiili each month.",
    "{{n1}} could go into an index fund.",
    "Bonus to fund turns {{n2}} into fund units.",
    "Save {{n1}}; open monthly saving.",                              # a semicolon does not end the sentence
    "Put {{n1}} into monthly savings.",
    "Laita {{n1}} kuukausisäästämiseen.",
    "Laita {{n1}} kuukausisäästöön.",
    "Voisit siirtää {{n2}} S-mobiilissa kuukausisäästämiseen.",
    "Sijoita {{n1}} osakerahastoon.",
    "Bonus rahastoon kerryttää {{n2}}.",
]
PASSED = [
    # the review of #475
    "I am Sentti, an AI money coach inside S-mobiili.",
    "I can't help with a loan decision; please contact S-Pankki.",
    "You could set aside about {{n1}} a month.",
    "You can spend about {{n2}} this week, after setting aside about {{n1}} a month.",
    "To keep setting aside {{n1}} a month, about {{n2}} a week is safe to spend, below your usual {{n2}} a week.",
    "These changes could add about {{n1}} a month. That is on top of the about {{n2}} a month you set aside first.",
    "Your S-Bonus would be about {{n1}} a month.",
    "At S Group stores your S-Bonus could be about {{n1}} a month.",
    "Your fund fee of {{n1}} is due before payday.",
    "A buffer in an emergency fund of {{n1}} would cover a month.",
    "Your refund of {{n1}} arrived on 3 September.",
    "Your monthly savings goal is {{n1}} a month.",
    "A monthly saving of {{n1}} is typical for you.",
    "Voisit säästää noin {{n1}} kuukaudessa.",
    "Voit käyttää tällä viikolla noin {{n2}}, kun ensin laitat sivuun noin {{n1}}.",
    "S-Bonuksesi olisi noin {{n1}} kuukaudessa.",
    "Puskurirahastoon riittäisi {{n1}}.",
    "Kuukausisäästösi on noin {{n1}}.",
    "S-mobiilissa näkyy {{n4}} tapahtumaa.",                          # a count is not an amount
    "S-mobiilissa {{n3}} kuluistasi on ruokaa.",                       # a share is not an amount
    "You could set aside about {{n1}} a month. The card's button opens monthly saving in S-mobiili.",
    "The cost of the fund-raiser was {{n1}}.",
    # plain statements, rejected on b6a8ff5 and passed since the decision in the review of #475
    "Your monthly saving is {{n1}}.",
    "In S-mobiili your balance is {{n2}}.",
    "Kuukausisäästäminen {{n1}} kuukaudessa kerryttää vuodessa {{n2}}.",
    # outside the rule by design: no bank screen or product is named
    "Invest {{n1}} a month.",
    "Move {{n1}} to a savings account.",
    "Siirrä {{n1}} säästötilille.",
    # earlier ones
    template.INTRO[0], template.INTRO[1],
    "You could set aside about {{n1}}.\nSee monthly saving in S-mobiili.",              # a line break ends it too
    "That is a monthly saving of {{n1}}.",
    "An emergency fund of {{n2}} covers a surprise.",
    "{{n2}} would be enough to fund the trip.",
    "You could save {{n2}} to fund the trip.",                       # "to fund" as a verb
    "{{n3}} of your spending went through S-mobiili.",
    "Kuukausisäästösi voisi olla {{n1}}.",
    "Puskurirahasto {{n2}} auttaa yllätyksissä.",
]


# The confirmation of #475: the reviewer's q5.py and q6.py drafts, verbatim ({{n3}} there is {{n2}} here).
REJECTED += [
    '{{n1}} could go into your fund.',
    '{{n1}} a month would grow in a fund.',
    'Consider monthly saving of {{n1}} in S-mobiili.',
    'With monthly saving in S-mobiili you would set aside {{n1}}.',
    'Avaa kuukausisäästäminen ja valitse {{n1}}.',
    'Rahastoon voisi mennä {{n1}}.',
    '{{n1}} kannattaa laittaa rahastoon.',
    'You could start monthly saving with {{n1}}.',
    'Start monthly saving with {{n1}} a month.',
    'Set up monthly saving for {{n1}} a month.',
    'You could add {{n1}} to monthly saving.',
    '{{n1}} could be moved to your fund.',
    '{{n1}} was put into the fund.',
    'Why not open a fund and invest {{n1}}?',
    'Voisit aloittaa kuukausisäästämisen {{n1}} summalla.',
    'Aloita kuukausisäästäminen {{n1}} kuukaudessa.',
    'Sijoita {{n1}} osakerahastoon.',
    'Voit siirtää {{n1}} kuukausisäästöön.',
    'Lisää {{n1}} kuukausisäästöön S-mobiilissa.',
    'Avaa S-mobiili ja laita {{n1}} sivuun.',
    'You could invest {{n1}} in an index fund.',
    'An index fund of {{n1}} a month suits you.',
    'Buy fund units for {{n1}}.',
    'Send {{n1}} to your monthly saving.',
    'Pay {{n1}} into your fund.',
    'You can put {{n1}} aside in S-mobiili.',
    'Go to S-mobiili and save {{n1}} a month.',
    'Save {{n1}} a month with monthly saving.',
    'Tee kuukausisäästö: {{n1}} kuukaudessa kuukausisäästämiseen.',
    'Talleta {{n1}} rahastoon.',
    'Keep {{n1}} in a fund.',
    'Park {{n1}} in a fund.',
    'Contribute {{n1}} to a fund.',
    'Allocate {{n1}} to monthly saving.',
    'Direct {{n1}} to a fund.',
    '{{n1}} into monthly saving.',
    'A fund with {{n1}} a month.',
    'Stash {{n1}} in S-mobiili.',
    'You can leave {{n1}} in a fund.',
    'Pay {{n1}} into monthly saving.',
    'Fund your future with {{n1}} a month.',
    'Kannattaisi sijoittaa {{n1}} rahastoon.',
    'Maksa {{n1}} kuukausisäästöön.',
    'Kuukausisäästäminen kannattaa aloittaa {{n1}} summalla.',
    'Voit käyttää {{n1}} rahastosäästämiseen.',
    'Pidä {{n1}} rahastossa.',
]
PASSED += [
    'Monthly saving in S-mobiili is a tool for this. You could set aside {{n1}} a month.',
    'You could set aside {{n1}} a month. The button opens monthly saving in S-mobiili.',
    'You could set aside {{n1}} a month. Open monthly saving in S-mobiili to see more.',
    'Save {{n1}} a month.',
    'You could save about {{n1}} a month.',
    'Your monthly saving is {{n1}}.',
    'Monthly saving in S-mobiili is not needed to reach {{n1}} a month.',
    'A typical month leaves {{n1}}, so a fund is not needed.',
    'A fund is not something I can advise on.',
    'Your fund fee is {{n1}} a month.',
    'Your emergency fund holds {{n2}}.',
    'Your S-Bonus would be about {{n1}} a month.',
    'Voisit säästää noin {{n1}} kuukaudessa.',
    'Voisit laittaa sivuun noin {{n1}} kuukaudessa.',
    'Voit käyttää tällä viikolla noin {{n2}}, kun ensin laitat sivuun noin {{n1}}.',
    'Voisit säästää {{n1}}. Kuukausisäästäminen avautuu painikkeesta S-mobiilissa.',
    'Kuukausisäästäminen S-mobiilissa on tapa säästää. Voisit säästää noin {{n1}}.',
    'Säästötavoitteesi on {{n1}} kuukaudessa.',
    'Lisäksi voisit säästää {{n1}} kuukaudessa.',
    'Lisää kuluja {{n2}} tässä kuussa kuin tavallisesti.',
    'Laita sivuun {{n1}} kuukaudessa.',
    'Rahasto-osuuksia ei voi arvioida, mutta {{n1}} jää kuukaudessa.',
    'Puskurirahastoon riittäisi {{n1}}.',
    'Set up a standing order of {{n1}} a month.',
    'Transfer {{n1}} to your savings account.',
    'Move {{n1}} to your savings account.',
    'Invest {{n1}} a month.',
    'Siirrä {{n1}} säästötilille.',
    'To fund the trip you would need {{n1}} a month.',
    'S-mobiili shows {{n4}} transactions this month.',
    'Add the bill of {{n2}} to your payments.',
    'Open the card to see {{n2}} of detail.',
    'Add {{n2}} to your payments in S-mobiili.',
]


# #499, verbatim ({{n3}} there is the plain euro amount {{n2}} here): the bill passes, the inessive and
# verb-less monthly-saving advice are rejected.
REJECTED += [
    "Maksa {{n1}} kuukausisäästöön S-mobiilissa.",
    "Maksa {{n1}} rahastoon kuukausittain.",
    "Pidä {{n1}} kuukausisäästössä.",
    "Kuukausisäästössä {{n1}} kuukaudessa riittäisi.",
    "Kuukausisäästäminen S-mobiilissa: {{n1}} kuukaudessa riittää.",
    "Monthly saving in S-mobiili: {{n1}} a month would do.",
    "In monthly saving, {{n1}} a month is enough.",
]
PASSED += [
    "Maksa {{n2}} S-mobiilissa ennen eräpäivää.",
    "Maksa lasku S-mobiilissa; summa on {{n2}}.",
    "Monthly saving of {{n1}} is typical for you.",
    "Your monthly saving is {{n1}}.",
]


@pytest.mark.parametrize("text", REJECTED)
def test_an_amount_put_into_the_bank_screen_or_product_is_rejected(text):
    assert amount_with_bank_product(text, NUMBERS)


@pytest.mark.parametrize("text", PASSED)
def test_no_false_rejection(text):
    assert amount_with_bank_product(text, NUMBERS) is None


@pytest.mark.parametrize("text", REJECTED + PASSED)
def test_the_eval_rule_on_the_rendered_text_agrees(text):
    """The eval checks the rendered text with the same words: the same verdict for every draft."""
    rendered = render_known(text)
    assert bool(amount_beside_bank_product(rendered)) == bool(amount_with_bank_product(text, NUMBERS)), rendered


def render_known(text: str) -> str:
    for nid, n in NUMBERS.items():
        text = text.replace("{{" + nid + "}}", n.display)
    return text


def test_the_rendered_text_rule_of_the_eval_agrees():
    assert amount_beside_bank_product("Put €360.00 a month into monthly saving.")
    assert amount_beside_bank_product("Laita 360,00\u00a0€ / kk kuukausisäästämiseen.")
    assert amount_beside_bank_product("You could set aside about €360.00 a month. See monthly saving in S-mobiili.") is None
    assert amount_beside_bank_product(template.INTRO[0]) is None


# ---- runtime: model drafts only ---------------------------------------------------------------------------

SPEND = [FunctionCall("fake_spending", {"category": "Restaurants"}), FunctionCall("finish")]
# {{n1}} is cited once: a token cited twice is its own rejection (#437)
JOINED = {"language": "en", "text": "Put the {{n1}} you spent on restaurants in August 2026 into monthly saving "
                                    "in S-mobiili instead.", "cited": ["n1"], "lesson_key": None}
APART = {"language": "en", "text": "In August 2026 you spent {{n1}} on restaurants, over {{n2}} visits.",
         "cited": ["n1", "n2"], "lesson_key": None}


def test_a_model_draft_that_joins_them_is_retried_with_the_reason(make_pipeline):
    model = ScriptedModel(plans=[SPEND], drafts=[JOINED, APART])
    pipe = make_pipeline(model, data=FakeData())
    done = dict(run(pipe))["done"]
    assert done["outcome"] == "answered" and "S-mobiili" not in done["text_rendered"]
    assert done["text_rendered"] == "In August 2026 you spent €147.64 on restaurants, over 10 visits."
    reason = model.compose_inputs[1].validation_errors
    assert len(reason) == 1 and ("Put the €147.64 you spent on restaurants in August 2026 into monthly saving in "
                                 "S-mobiili instead.") in reason[0]
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
