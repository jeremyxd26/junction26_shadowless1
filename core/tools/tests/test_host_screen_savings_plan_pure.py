"""#417 (decision 4) for the savings plan of #369: its card's `open_host_screen` action uses the one
`monthly_saving` label, and its template answer never names an amount and the bank's screen or product in one
sentence, in English and Finnish, with levers and with none. The plan's own fakes (test_tools_savings_plan_pure);
no database."""

from __future__ import annotations

import pytest
from test_host_screen_labels_pure import host_label_entries
from test_tools_savings_plan_pure import AS_OF, SANNA, fake, plan, what_if  # noqa: F401  (fake is a fixture)

from core.agent import template
from core.agent.validator import allowed_from, amount_with_bank_product, render
from core.answer_text import amount_beside_bank_product


@pytest.mark.parametrize("levers", [True, False])
@pytest.mark.parametrize("language, question", [("en", "How could I save more?"), ("fi", "Miten voisin säästää enemmän?")])
def test_the_plan_keeps_the_amount_apart_from_the_bank(fake, levers, language, question):   # noqa: F811
    if not levers:
        fake.what_ifs = {c: what_if("20.00", "2.00", ref=f"ev_{c[:3]}") for c in SANNA}
    result, ctx = plan(language)
    numbers = ctx.numbers.all()
    allowed = allowed_from(numbers.values(), [result.model_view], AS_OF)
    draft = template.template_draft([result.model_view], [], language, allowed, question)
    text = draft["text"] if isinstance(draft, dict) else draft
    assert amount_with_bank_product(text, numbers) is None, text
    assert amount_beside_bank_product(render(text, numbers)) is None, text
    if levers:
        labels = {t: v for t, _, v in host_label_entries()}
        host = [a for a in result.card.actions if a.type == "open_host_screen"]
        assert [(a.target, a.label) for a in host] == [
            ("monthly_saving", labels["monthly_saving"][0 if language == "en" else 1])]
