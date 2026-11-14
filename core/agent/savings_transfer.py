"""Questions about the user's own transfers to savings (#658).

"How much did I transfer to savings last month?", "How much do I usually transfer to savings each month?", "What was
my last transfer to savings?", "Paljonko siirsin säästöön viime kuussa?", "Paljonko siirrän säästöön kuukaudessa?".

The rules claim them for the savings plan tool, whose view carries what already goes to savings (#560): the regular
transfer's typical month and its share of the income, or `saving_seen` False when no regular transfer shows. The
template writes the answer from that view (`sentence`), in any model state.

No tool returns the amount of one past month or of one transfer, so a question about the past gets one plain sentence
saying so, then what is known: the regular transfer (its typical month, never presented as one month's amount) or
the zero state. A request to move money is no question about transfers: the decline rules refuse it before this.
Matched on the folded question (guard.fold: lower case, no diacritics).
"""

from __future__ import annotations

import re
from typing import Any

from core.agent.guard import fold_pattern

# "to savings", "into my savings account"; Finnish "säästöön", "säästöihin", "säästötilille"
_TO_SAVINGS = r"\b(to|into)\s+(my\s+|the\s+|our\s+)?savings?\b"
_FI_SAVINGS = r"\b(säästöön|säästöihin|säästötili\w*)\b"
MOVED = fold_pattern(
    r"\b(transfer\w*|put|puts|putting|mov(e|es|ed|ing)|sen(d|ds|t|ding)|go|goes|went|going|set(ting)?\s+aside|"
    r"pa(y|ys|id))\b[^.?!]{0,40}?" + _TO_SAVINGS + r"|\bsavings?\s+transfers?\b|"
    r"\b(siirs|siirr|siirt|laito|laita|laitet|pistin|pistä|panin|panen|men(ee|i|evät|ivät)\b)\w*[^.?!]{0,40}?"
    + _FI_SAVINGS + r"|\bsäästösiirto\w*")
# A question about the user's own money, past or usual ...
ASKS = fold_pattern(
    r"\b(how much|how often|what (was|were|is|are)|when (did|was)|did (i|we)|do (i|we)|have (i|we)|does|is there|"
    r"paljonko|kuinka paljon|kuinka usein|mikä (oli|on)|milloin|onko|siirsinkö|siirränkö|laitoinko|laitanko|"
    r"meneekö|menikö)\b|\?\s*$")
# ... never a request to move money ("Put 100 euros into savings?", "Can you move 50 euros to savings?"), advice, a
# plan, a hypothesis or a future amount ("How much should I transfer to savings?", "What if I put 100 euros into
# savings?"): the decline, savings plan and what-if rules answer those
NOT_OWN = fold_pattern(
    r"^\W*(please\s+|pls\s+)?(transfer|put|move|send|set|pay|make|start|stop|cancel|siirrä|siirtäkää|laita|pistä|"
    r"pane|tee|aloita|lopeta)\b|\b(can|could|would|will)\s+you\b|\bvoi(tko|sitko|tteko)\b|"
    r"\b(should|could|can|would|might|will|shall|must|ought|may)\s+(i|we)\b|\b(have|need|want|ought)\s+to\b|"
    r"\bwhat if\b|\bif (i|we)\b|\bnext (month|year|week)\b|"
    r"\b(pitäisi|pitäis|kannattaa|kannattaisi|voisin|voinko|voiko|voisiko|pitääkö|tarvitsee|täytyy|jos)\b|"
    r"\bensi (kuussa|vuonna|viikolla)\b")
# The past: a month, the last transfer, a past verb. Otherwise the question is about the usual transfer.
PAST = fold_pattern(
    r"\b(did|was|were|went|last|latest|previous|recent|ago|transferred|moved|sent|paid|this year|so far)\b|"
    r"\b(january|february|march|april|june|july|august|september|october|november|december)\b|\bin may\b|"
    r"\b(siirsin\w*|siirsimme|siirrettiin|siirtänyt|laitoin\w*|laitettiin|pistin|panin|meni|menivät|viime|"
    r"viimeisin\w*|viimeksi|edellinen|edellisen|edellisellä|tänä vuonna)\b|"
    r"\b(tammi|helmi|maalis|huhti|touko|kesä|heinä|elo|syys|loka|marras|joulu)kuu\w*")
ONE_TRANSFER = fold_pattern(r"\b(last|latest|previous|recent)\s+(savings\s+)?transfer\b|"
                            r"\b(viimeisin|edellinen)\s+(säästö)?siirto\w*")

LEAD = {
    "month": ("I can't single out a past month's transfers to savings on their own.",
              "En pysty erottelemaan yksittäisen kuukauden säästösiirtoja erikseen."),
    "transfer": ("I can't single out one transfer to savings on its own.",
                 "En pysty erottelemaan yksittäistä säästösiirtoa erikseen."),
}


def asks(q: str) -> str | None:
    """"past" or "usual" when the folded question asks about the user's own transfers to savings, else None."""
    if not (re.search(MOVED, q) and re.search(ASKS, q)) or re.search(NOT_OWN, q):
        return None
    return "past" if re.search(PAST, q) else "usual"


def sentence(view: dict[str, Any], language: str, q: str, already: dict[str, tuple[str, str]]) -> \
        tuple[str, list[str]] | None:
    """The answer from the savings plan view and the ids it cites: for the past, the lead that one month or one
    transfer cannot be singled out; then the regular transfer (#560's sentence, `already`) or the zero state. None
    when the view is not the savings plan's or what goes to savings could not be read."""
    kind = asks(q)
    if kind is None or view.get("tool") != "get_savings_plan":
        return None
    pick = 1 if language == "fi" else 0

    def num(node: Any) -> dict[str, Any] | None:
        return node if isinstance(node, dict) and isinstance(node.get("id"), str) else None

    saving, share = num(view.get("already_saving")), num(view.get("already_share"))
    tok = lambda n: "{{" + n["id"] + "}}"  # noqa: E731
    if view.get("saving_seen") is True and saving:
        body, cited = ((already["already"][pick].format(amount=tok(saving), share=tok(share)), [saving["id"], share["id"]])
                       if share else (already["already_no_share"][pick].format(amount=tok(saving)), [saving["id"]]))
    elif view.get("saving_seen") is False:
        body, cited = already["no_transfer"][pick], []
    else:
        return None
    if kind == "past":
        lead = LEAD["transfer" if re.search(ONE_TRANSFER, q) else "month"][pick]
        return f"{lead} {body}", cited
    return body, cited
