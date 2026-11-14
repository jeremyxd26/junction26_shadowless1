"""Two lying answer sources for the eval runner: each wraps the reference source and adds an invented
number, so a run with either must fail every answer. They show the checks work (README, eval set).

    python core/eval/run.py --source liars:invented_text       # an invented amount in the text
    python core/eval/run.py --source liars:declared_invented   # ...also declared as a Number object
    python core/eval/run.py --source liars:borrowing           # a borrowing suggestion in the text (#437)
"""

from __future__ import annotations

from sources import ReferenceSource

from core import answer_text


def invented_text(doc, args):
    """An invented amount appended to the text (refusals get one too)."""
    ref = ReferenceSource(doc)

    def source(customer_id, question, language):
        ans = ref(customer_id, question, language)
        if ans.outcome == "refused":
            ans.text += " Sinulla on 5 000,00 € säästöissä." if language == "fi" else " You hold €5,000.00."
        else:
            ans.text += " Lisäksi 30 € jää yli." if language == "fi" else " You also have €30 left."
        return ans
    source.stats = ref.stats
    return source


def declared_invented(doc, args):
    """An invented amount that is also declared as a Number object with a formatter-correct display,
    so only the check that a tool of the answer returned it can catch it."""
    ref = ReferenceSource(doc)

    def source(customer_id, question, language):
        ans = ref(customer_id, question, language)
        display = answer_text.formatted(30.0, "eur", language)
        if ans.outcome == "refused":
            ans.text += f" {display}"
        else:
            ans.numbers = ans.numbers + [{"id": "n99", "value": 30.0, "unit": "eur", "display": display,
                                          "method": "spending.total@1", "period": None}]
            ans.text += f" Extra: {display}."
        return ans
    source.stats = ref.stats
    return source


def borrowing(doc, args):
    """A borrowing suggestion appended to every answer, so the borrowing rule must fail each one (#419, #437)."""
    ref = ReferenceSource(doc)

    def source(customer_id, question, language):
        ans = ref(customer_id, question, language)
        ans.text += " Voit ottaa lainaa siihen." if language == "fi" else " You could take out a small loan for it."
        return ans
    source.stats = ref.stats
    return source
