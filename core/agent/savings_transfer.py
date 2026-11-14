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

Only a message that is one question with nothing after it is claimed (`ONE_QUESTION`, Renat's decision on the review
of #670); any other message is left to the rules as they were before #658, so a request in it keeps their refusal.
"""

from __future__ import annotations

import re
from typing import Any

from core.agent.guard import fold_pattern

# "to savings", "into my savings account"; Finnish "säästöön", "säästöihin", "säästötilille"
_TO_SAVINGS = r"\b(to|into)\s+(my\s+|the\s+|our\s+)?savings?\b"
_FI_SAVINGS = r"\b(säästöön|säästöihin|säästötili\w*)\b"
MOVED = fold_pattern(
    r"\b(transfer\w*|put|puts|putting|mov(e|es|ed|ing)|sen(d|ds|t|ding)|go|goes|went|going|set(ting)?\s+aside)\b"
    r"[^.?!]{0,40}?" + _TO_SAVINGS + r"|\bsavings?\s+transfers?\b|"
    r"\b(siirs|siirr|siirt|laito|laita|laitet|pistin|pistä|panin|panen|men(ee|i|evät|ivät)\b)\w*[^.?!]{0,40}?"
    + _FI_SAVINGS + r"|\bsäästösiirto\w*")
# "How much did I save last month?", "Paljonko säästin viime kuussa?" (#668): what went to savings, never the spending
# total. Not a saving on something, by or from something, or for something ("How much did I save on groceries?").
SAVED = fold_pattern(
    r"\b(did|do|does|have|has)\s+(i|we)\s+(usually\s+|normally\s+|typically\s+|actually\s+|really\s+)?sav(e|ed)\b"
    r"(?!\s+(on|by|from|with|if|for|up)\b)|"
    r"\b(säästin|säästimme|säästän|säästämme|säästänyt|säästäneet)\b(?!\s+\w+(sta|stä|lla|llä)\b)")
# A question about the user's own money, past or usual ...
ASKS = fold_pattern(
    r"\b(how much|how often|what (was|were|is|are)|when (did|was)|did (i|we)|do (i|we)|have (i|we)|does|is there|"
    r"paljonko|kuinka paljon|kuinka usein|mikä (oli|on)|milloin|onko|siirsinkö|siirränkö|laitoinko|laitanko|"
    r"meneekö|menikö)\b|\?\s*$")
# ... never a request to move money ("Put 100 euros into savings?", "Can you move 50 euros to savings?"), advice, a
# plan, a hypothesis or a future amount ("How much should I transfer to savings?", "What if I put 100 euros into
# savings?"): the decline, savings plan and what-if rules answer those
# A move or change verb with an amount anywhere in the message ("… Also move 200 euros to savings now", "… can you
# increase it to 500 euros?"): a request, which keeps the decline rules' refusal (review of #670)
MOVE_WITH_AMOUNT = fold_pattern(
    r"\b(transfer|move|send|put|deposit|add|pay|increase|raise|lower|reduce|change|set|siirrä|siirtää|laita|laittaa|"
    r"pistä|pane|talleta|nosta|nostaa|muuta|maksa)\b[^.?!]{0,30}?"
    # "€200", "200 €", "200€", "200e", "200eur", "200 euros", "fifty euros" (a "€" is no word character, so no \b
    # after it, and none between the digit and the unit)
    r"(€\s?\d|\b\d[\d\s.,]*\s?(?:€|(?:euros?|eur|euroa?|e)\b)|\b(ten|twenty|fifty|hundred|thousand|kymmenen|"
    r"viisikymmentä|sata|tuhat)\s+(euros?|euroa?)\b)")
# One question with nothing after it, the whole message (Renat's decision on the review of #670): no second sentence
# (after ".", "?", "!", ";", ":" or a line break) and no further clause (after ",", a dash, "&", "+", "and", "then",
# "also", "plus", "ja", "sitten", "myös" or "sekä"); only a closing "please" or "thanks" may follow. "… and increase
# it", "…, increase it", "… - increase it", "…? Bump it up" and "…? And the month before?" are left to the rules as
# before #658.
_BREAK = r"[.?!;:,\n&+–—]|\s-|-\s|\b(and|then|also|plus|ja|sitten|myös|sekä)\b"
ONE_QUESTION = fold_pattern(r"\s*(?:(?!" + _BREAK + r").)+?(?:,?\s+(?:please|pls|thanks|thank you|kiitos))?\s*[.?!]*\s*")
# "Do I have a regular transfer to savings?" (#658) as the whole message, nothing before or after it but the bank the
# savings account is at or a closing "please". Only this message has its "transfer" exempted from the move-money
# refusal (rules._declines), and only when it is claimed: "… please increase it", "… increase it to 200" and
# "Increase it. Do I have …?" keep the refusal, as do a transfer to a person and a scheduled or future transfer.
HAVE_TRANSFER = fold_pattern(
    r"\s*(do|does|did)\s+(i|we)\s+have\s+(a|any)\s+(regular\s+|monthly\s+|recurring\s+|standing\s+)?transfers?\s+"
    r"(to|into)\s+(my\s+|the\s+|our\s+)?savings?(\s+accounts?)?"
    r"(\s+(at|in|with)\s+(another|a\s+different|an\s+other|my\s+other|other)\s+banks?)?"
    r"(\s*,?\s*(please|pls))?\s*[.?!]*\s*")
# "How much should I transfer to savings (each month)?" (#668) as the whole message, nothing before or after it but a
# month or a closing "please": how much to set aside, the savings plan's question. As with HAVE_TRANSFER, only this
# message has its "transfer" exempted from the move-money refusal (rules._declines), and only when it is claimed
# (`set_aside`); "… or invest in stocks?", "… at another bank?", "… next month?" and any later clause keep the refusal.
SET_ASIDE_TRANSFER = fold_pattern(
    r"\s*how\s+much\s+(should|can|could|shall)\s+(i|we)\s+transfer\s+(to|into)\s+(my\s+|the\s+|our\s+)?savings?"
    r"(\s+accounts?)?(\s+(each|every|per|a)\s+month|\s+monthly)?(\s*,?\s*(please|pls))?\s*[.?!]*\s*")
# A request to move money as the message's first word or after "can you", "voitko" (#668: never how much to set aside)
REQUEST = fold_pattern(
    r"^\W*(please\s+|pls\s+)?(transfer|put|move|send|set|pay|make|start|stop|cancel|siirrä|siirtäkää|laita|pistä|"
    r"pane|tee|aloita|lopeta)\b|\b(can|could|would|will)\s+you\b|\bvoi(tko|sitko|tteko)\b")
NOT_OWN = REQUEST + "|" + fold_pattern(
    r"\b(should|could|can|would|might|will|shall|must|ought|may)\s+(i|we)\b|\b(have|need|want|ought)\s+to\b|"
    r"\bwhat if\b|\bif (i|we)\b|\bnext (month|year|week)\b|\b(tomorrow|tonight|huomenna)\b|"
    r"\b(pitäisi|pitäis|kannattaa|kannattaisi|voin|voit|voimme|voisin|voisimme|voinko|voiko|voisiko|pitääkö|"
    r"tarvitsee|täytyy|jos)\b|"
    r"\bensi (kuussa|vuonna|viikolla)\b|"
    # fees, costs, interest or tax on savings are another question (review of #670)
    r"\b(fees?|charges?|costs?|interest|tax(es)?|kulut|kuluja|palkkio\w*|korko\w*|korot)\b") + "|" + MOVE_WITH_AMOUNT
# "How much did I save?" is what went to savings only without a discount, a deadline ahead, a why or a comparison
# (#668): "I used a promo code, how much did I save?", "paljonko olen säästänyt jouluun mennessä?", "why did I save
# less last month?" are other questions. Read only when SAVED, not MOVED, makes the question one about savings.
SAVED_OTHER = fold_pattern(
    r"\b(promo(tion)?s?|discounts?|coupons?|vouchers?|offers?|deals?|cashback|rebates?|alennu\w*|tarjou\w*|"
    r"kuponki\w*|kupongi\w*)\b|"
    r"\bby\s+(christmas|the end|end of|new year|easter|summer|midsummer|then)\b|\bmennessä\b|\bjouluun\b|"
    r"\b(why|how come|miksi)\b|\b(less|more|fewer|vähemmän|enemmän)\b")
# The past: a month, the last transfer, a past verb. Otherwise the question is about the usual transfer.
PAST = fold_pattern(
    r"\b(did|was|were|went|last|latest|previous|recent|ago|transferred|moved|sent|paid|this year|so far)\b|"
    r"\b(january|february|march|april|june|july|august|september|october|november|december)\b|\bin may\b|"
    r"\b(siirsin\w*|siirsimme|siirrettiin|siirtänyt|laitoin\w*|laitettiin|pistin|panin|meni|menivät|viime|"
    r"säästin|säästimme|säästänyt|säästäneet|saved|"
    r"viimeisin\w*|viimeksi|edellinen|edellisen|edellisellä|tänä vuonna)\b|"
    r"\b(tammi|helmi|maalis|huhti|touko|kesä|heinä|elo|syys|loka|marras|joulu)kuu\w*")
ONE_TRANSFER = fold_pattern(r"\b(last|latest|previous|recent)\s+(savings\s+)?transfer\b|"
                            r"\b(viimeisin|edellinen)\s+(säästö)?siirto\w*")
# One month named or meant ("last month", "in August", "viime kuussa", "elokuussa"): the month lead
MONTH = fold_pattern(
    r"\b(last|this|previous|past)\s+month\b|"
    r"\b(january|february|march|april|june|july|august|september|october|november|december)\b|\bin may\b|"
    r"\b(viime|edellisenä|edellisessä|tässä|tänä)\s+(kuussa|kuukautena|kuukaudessa)\b|"
    r"\b(tammi|helmi|maalis|huhti|touko|kesä|heinä|elo|syys|loka|marras|joulu)kuussa\b")
# A year, a total, "ever", a week or a year as the period (review of #670): the period lead, never the month's
PERIOD_TOTAL = fold_pattern(
    r"\b(19|20)\d\d\b|\b(in total|altogether|ever|so far|this year|last year|a year|per year|each year|every year|"
    r"yearly|annually|a week|per week|each week|every week|weekly)\b|"
    r"\b(yhteensä|koskaan|tähän mennessä|tänä vuonna|viime vuonna|vuodessa|vuosittain|viikossa|viikoittain)\b")

LEAD = {
    "month": ("I can't single out a past month's transfers to savings on their own.",
              "En pysty erottelemaan yksittäisen kuukauden säästösiirtoja erikseen."),
    "transfer": ("I can't single out one transfer to savings on its own.",
                 "En pysty erottelemaan yksittäistä säästösiirtoa erikseen."),
    "total": ("I can't add up your past transfers to savings for a period.",
              "En pysty laskemaan aiempia säästösiirtojasi yhteen tietyltä ajalta."),
}


def lead_key(q: str, kind: str) -> str | None:
    """Which lead the answer opens with: one transfer, one month, a period's total; None for the usual transfer."""
    if re.search(ONE_TRANSFER, q):
        return "transfer"
    if re.search(PERIOD_TOTAL, q):
        return "total"
    if kind == "past":
        return "month" if re.search(MONTH, q) else "total"
    return None


# "How much should I transfer to savings?", "Paljonko voin siirtää säästöön kuukaudessa?" (#668): how much to set
# aside is the savings plan's question (the rule `save_more`), never a refusal and never what already goes to savings
HOW_MUCH = fold_pattern(r"\b(how much|paljonko|kuinka paljon)\b")
SET_ASIDE_MODAL = fold_pattern(r"\b(should|can|could|shall)\s+(i|we)\b|"
                               r"\b(pitäisi|pitäis|kannattaa|kannattaisi|voin|voisin|voimme|voisimme)\b")
HYPOTHESIS = fold_pattern(r"\bwhat if\b|\bif (i|we)\b|\bjos\b|\bentä jos\b")


def asks(q: str) -> str | None:
    """"past" or "usual" when the folded message is one question about the user's own transfers to savings (or how
    much they saved, #668), else None."""
    saved = re.search(SAVED, q) and not re.search(SAVED_OTHER, q)
    if not re.fullmatch(ONE_QUESTION, q) or not ((re.search(MOVED, q) or saved) and re.search(ASKS, q)) \
            or re.search(NOT_OWN, q):
        return None
    return "past" if re.search(PAST, q) else "usual"


def have_transfer(q: str) -> bool:
    """The whole folded message asks whether the user has a regular transfer to savings, and the rules claim it: its
    "transfer" is no request to move money (rules._declines)."""
    return bool(re.fullmatch(HAVE_TRANSFER, q)) and asks(q) is not None


def set_aside(q: str) -> bool:
    """The folded message is one question how much the user should or can move to savings (#668), with no amount and
    no request."""
    return bool(re.fullmatch(ONE_QUESTION, q) and re.search(MOVED, q) and re.search(HOW_MUCH, q)
                and re.search(SET_ASIDE_MODAL, q) and not re.search(HYPOTHESIS, q) and not re.search(REQUEST, q)
                and not re.search(MOVE_WITH_AMOUNT, q))


def set_aside_transfer(q: str) -> bool:
    """The whole folded message asks how much the user should transfer to savings, and the rules claim it: its
    "transfer" is no request to move money (rules._declines)."""
    return bool(re.fullmatch(SET_ASIDE_TRANSFER, q)) and set_aside(q)


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
    key = lead_key(q, kind)
    if key is not None:
        return f"{LEAD[key][pick]} {body}", cited
    return body, cited
