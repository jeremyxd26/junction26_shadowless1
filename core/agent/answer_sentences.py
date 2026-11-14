"""Rule answers as short human sentences (#342): one takeaway first, then at most one more sentence.

template_draft (template.py) asks `for_view` for each tool's model view. It returns the sentences and
the number ids they cite, or None for a tool written elsewhere: the safe-to-spend sentence, the spender
profile, the peer benchmark and the S-Bonus estimate keep their own texts (PR #296), and an unknown
tool keeps the old "label: number" form.

Rules for every text here (coordinator, #342):
- at most two short sentences and about 35 words, in plain words, English and Finnish, the takeaway
  first, and at most three numbers; the rest stay on the card (Renat's length rule);
- a change is said in words ("less than in August"), never two lines with the same label;
- no repeated label, no "label: number; label: number" list;
- no judgement words, no advice beyond the existing what-if offer, no exclamation marks;
- numbers only as {{nK}} tokens of the view's own numbers, never a digit or a number word of our own,
  never a unit word next to a token (its display carries the unit), and always a word between two
  tokens. Dates appear only as the tools' own period labels and dates.
The Finnish sentences are written as Finnish, with a native check listed in the PR; a label is never
inflected, so a category stands after "luokassa" and a month label is turned into its inessive only for
the "<month>kuu <year>" form ("elokuussa 2026").
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Callable

from core.tools import config

Sentences = tuple[list[str], list[str]]
Ok = Callable[[str], bool]
# A tool's notes that these sentences already say ("You have no transactions ..."): left out after them.
SAID_BY_SENTENCE = frozenset(config.TEXT["note_empty"])


def pick(pair: tuple[str, str], language: str) -> str:
    return pair[1] if language == "fi" else pair[0]


def _tok(node: Any) -> str | None:
    if isinstance(node, dict) and isinstance(node.get("id"), str) and {"value", "unit"} <= node.keys():
        return "{{" + node["id"] + "}}"
    return None


def _ids(*tokens: str | None) -> list[str]:
    return [t[2:-2] for t in tokens if t]


def _value(node: Any) -> float | None:
    v = node.get("value") if isinstance(node, dict) else None
    return v if isinstance(v, (int, float)) else None


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]


# ---- period phrases ----------------------------------------------------------------------------------

_EN_MONTH = re.compile(r"^[A-Z][a-z]+ \d{4}$")
_FI_MONTH = re.compile(r"^(\w+kuu) (\d{4})$", re.I)


def in_period(label: str, language: str) -> str:
    """"in August 2026" / "elokuussa 2026"; a range: "during 1 Apr – 30 Sep 2026" / "jaksolla 1.4.–30.9.2026"."""
    if language == "fi":
        m = _FI_MONTH.match(label)
        return f"{m.group(1).lower()}ssa {m.group(2)}" if m else f"jaksolla {label}"
    return f"in {label}" if _EN_MONTH.match(label) else f"during {label}"


# ---- what a spending number is about --------------------------------------------------------------------

_KNOWN_LABELS = {lab for table in (config.CATEGORY_LABELS, config.BASKET_LABELS, config.MCC_GROUP_LABELS)
                 for pair in table.values() for lab in pair}


def _subject(label: str, language: str) -> str | None:
    """None for plain spending or income; else how the sentence names it ("restaurants", "luokassa Ravintolat")."""
    if label in (pick(config.TEXT["spending"], language), pick(config.TEXT["income"], language)):
        return None
    if language == "fi":
        return f"luokassa {label}"
    return label.lower() if label in _KNOWN_LABELS else label


SPENT = {
    # (no subject, with a subject): {total} and the subject phrase
    "plain": (("You spent {total} {period}.", "You spent {total} on {what} {period}."),
              ("{Period} käytit {total}.", "{Period} käytit {total} {what}.")),
    "count": (("You spent {total} {period}, across {count} transactions.",
               "You spent {total} on {what} {period}, across {count} transactions."),
              ("{Period} käytit {total} ja tapahtumien määrä oli {count}.",
               "{Period} käytit {total} {what} ja tapahtumien määrä oli {count}.")),
    "count_one": (("You spent {total} {period}, in {count} transaction.",
                   "You spent {total} on {what} {period}, in {count} transaction."),
                  ("{Period} käytit {total} ja tapahtumien määrä oli {count}.",
                   "{Period} käytit {total} {what} ja tapahtumien määrä oli {count}.")),
    "income": (("Your income {period} was {total}.", "Your income {period} was {total}, from {what}."),
               ("{Period} tuloja tuli {total}.", "{Period} tuloja tuli {total} {what}.")),
    "income_count": (("Your income {period} was {total}, across {count} payments.",
                      "Your income {period} was {total} from {what}, across {count} payments."),
                     ("{Period} tuloja tuli {total} ja maksujen määrä oli {count}.",
                      "{Period} tuloja tuli {total} {what} ja maksujen määrä oli {count}.")),
    "income_count_one": (("Your income {period} was {total}, in {count} payment.",
                          "Your income {period} was {total} from {what}, in {count} payment."),
                         ("{Period} tuloja tuli {total} ja maksujen määrä oli {count}.",
                          "{Period} tuloja tuli {total} {what} ja maksujen määrä oli {count}.")),
    # Nothing in the period: the count and the total are still stated (the eval and the card show them).
    "none": (("There were {count} transactions {period}, so you spent {total}.",
              "There were {count} transactions for {what} {period}, so you spent {total}."),
             ("{Period} oli {count} tapahtumaa, joten käytit {total}.",
              "{Period} {what} oli {count} tapahtumaa, joten käytit {total}.")),
}
COMPARED = {   # appended to the first sentence: ", down from €4,175.17 in August 2026 (-29.8%)."
    "more": (", up from {baseline} {period} ({pct}).", ", enemmän kuin {period} ({baseline}, muutos {pct})."),
    "less": (", down from {baseline} {period} ({pct}).", ", vähemmän kuin {period} ({baseline}, muutos {pct})."),
    "more_no_pct": (", up from {baseline} {period}.", ", enemmän kuin {period} ({baseline})."),
    "less_no_pct": (", down from {baseline} {period}.", ", vähemmän kuin {period} ({baseline})."),
    "same": (", the same as {period} ({baseline}).", ", saman verran kuin {period} ({baseline})."),
}
LARGEST_GROUPS = ("The largest parts were {items}.", "Suurimmat osat olivat {items}.")
TIME_GROUPS = ("By period: {items}.", "Jaksoittain: {items}.")


def _join(items: list[str], language: str) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + (" ja " if language == "fi" else " and ") + items[-1]


def spending(view: dict[str, Any], language: str, ok: Ok) -> Sentences | None:
    total, count = _tok(view.get("total")), _tok(view.get("tx_count"))
    period = view.get("period")
    if not total or not isinstance(period, str) or not ok(period):
        return None
    label = (view.get("total") or {}).get("label") or ""
    what = _subject(label, language)
    lang = 1 if language == "fi" else 0
    phrase = in_period(period, language)
    fmt = {"total": total, "count": count, "what": what or "", "period": phrase, "Period": _cap(phrase)}
    income = view.get("direction") == "in"
    comparison = view.get("comparison") or {}

    if _value(view.get("tx_count")) == 0 and _value(view.get("total")) == 0:
        return [SPENT["none"][lang][1 if what else 0].format(**fmt)], _ids(count, total)

    if comparison:
        baseline, change, pct = (_tok(comparison.get(k)) for k in ("baseline", "change", "change_pct"))
        b_label = (comparison.get("baseline") or {}).get("label") or ""
        if not baseline or not change or not ok(b_label):
            return None
        first = SPENT["income" if income else "plain"][lang][1 if what else 0].format(**fmt)
        delta = _value(comparison.get("change")) or 0
        direction = "more" if delta > 0 else "less" if delta < 0 else "same"
        key = direction if direction == "same" or pct else f"{direction}_no_pct"
        first = first[:-1] + pick(COMPARED[key], language).format(period=in_period(b_label, language),
                                                                  baseline=baseline, pct=pct)
        return [first], _ids(total, baseline, pct if direction != "same" else None)

    groups = [(g.get("label"), _tok(g.get("amount")), g.get("key")) for g in view.get("groups") or []]
    groups = [(lab, t, k) for lab, t, k in groups if isinstance(lab, str) and t and ok(lab)][:2]
    if groups:
        first = SPENT["income" if income else "plain"][lang][1 if what else 0].format(**fmt)
        time_like = all(isinstance(k, str) and re.match(r"^\d{4}-\d{2}", k) for _, _, k in groups)
        if time_like:
            items = [f"{t} {in_period(lab, language)}" for lab, t, _ in groups]   # "€3,500.00 in July 2026"
            second = pick(TIME_GROUPS, language).format(items=_join(items, language))
        else:
            names = [(lab.lower() if lab in _KNOWN_LABELS else lab) for lab, _, _ in groups]   # a known label
            items = [f"{n} ({t})" for n, (_, t, _) in zip(names, groups)]
            second = pick(LARGEST_GROUPS, language).format(items=_join(items, language))
        return [first, second], _ids(total, *(t for _, t, _ in groups))

    key = ("income_count" if income else "count") if count else ("income" if income else "plain")
    if count and _value(view.get("tx_count")) == 1:
        key += "_one"
    return [SPENT[key][lang][1 if what else 0].format(**fmt)], _ids(total, count)


# ---- baskets --------------------------------------------------------------------------------------------

BASKET_PHRASES = {
    # (English name, Finnish illative)
    "regular_essentials": ("regular essentials", "säännöllisiin välttämättömiin menoihin"),
    "unexpected_necessities": ("unexpected necessities", "odottamattomiin välttämättömiin menoihin"),
    "everyday_spending": ("everyday spending", "arjen kulutukseen"),
    "unclassified": ("purchases waiting for your answer", "vastaustasi odottaviin ostoksiin"),
}
BASKET_LEAD = {
    "most": ("Most of your spending, {share}, went to {basket}.",
             "Suurin osa kulutuksestasi, {share}, meni {basket}."),
    "largest": ("The largest share of your spending, {share}, went to {basket}.",
                "Suurin osuus kulutuksestasi, {share}, meni {basket}."),
}
BASKET_REST = ("{Basket} took {share} and {basket2} {share2}.", "{Basket} meni {share} ja {basket2} {share2}.")
BASKET_REST_ONE = ("{Basket} took {share}.", "{Basket} meni {share}.")


def baskets(view: dict[str, Any], language: str, ok: Ok, save_more: bool) -> Sentences | None:
    """The three shares in two sentences; the monthly total stays on the card. In the save-more answer
    the baskets stay on their card: the text is the safe-to-save figure and the what-if offer."""
    if save_more:
        return [], []
    rows = [(b.get("key"), _tok(b.get("share")), _value(b.get("share"))) for b in view.get("baskets") or []]
    rows = [(k, t, v) for k, t, v in rows if k in BASKET_PHRASES and t and v is not None]
    if not rows:
        return None
    rows.sort(key=lambda r: -r[2])
    lang = 1 if language == "fi" else 0
    name = lambda key: BASKET_PHRASES[key][lang]  # noqa: E731
    (k1, t1, v1), rest = rows[0], rows[1:3]
    sentences = [pick(BASKET_LEAD["most" if v1 > 50 else "largest"], language).format(share=t1, basket=name(k1))]
    cited = [t1]
    if len(rest) == 2:
        (k2, t2, _), (k3, t3, _) = rest
        sentences.append(pick(BASKET_REST, language).format(Basket=_cap(name(k2)), share=t2, basket2=name(k3),
                                                            share2=t3))
        cited += [t2, t3]
    elif rest:
        sentences.append(pick(BASKET_REST_ONE, language).format(Basket=_cap(name(rest[0][0])), share=rest[0][1]))
        cited.append(rest[0][1])
    return sentences, _ids(*cited)


# ---- bills, income and payday ---------------------------------------------------------------------------

BILLS_DUE = {
    "items": ("Bills of {total} are due before your payday, including {items}.",
              "Ennen palkkapäivää erääntyy laskuja {total}, joista {items}."),
    "total": ("Bills of {total} are due before your payday.", "Ennen palkkapäivää erääntyy laskuja {total}."),
}
BILL_ITEM = ("{amount} for {bill}", "{bill} {amount}")
BILLS_TYPICAL = ("Your regular bills are {items}.", "Säännölliset laskusi ovat {items}.")
BILL_TYPICAL_ITEM = ("{bill} at {amount}", "{bill}, tavallisesti {amount}")
# One sentence: the first income row and, when known, the next payday (review of #365).
SALARY = ("Your salary is usually {amount}", "Palkkasi on tavallisesti {amount}")
OTHER_INCOME = ("Your usual {income} is {amount}", "Tavallinen tulosi ({income}) on {amount}")
AND_PAYDAY = (", and your next payday is {date}.", ", ja seuraava palkkapäiväsi on {date}.")
NEXT_PAYDAY = ("Your next payday is {date}.", "Seuraava palkkapäiväsi on {date}.")


def _date(iso: str, language: str) -> str | None:
    try:
        d = date.fromisoformat(iso)
    except (TypeError, ValueError):
        return None
    return f"{d.day}.{d.month}.{d.year}" if language == "fi" else f"{d.day} {d.strftime('%B')} {d.year}"


def _bill_name(label: str, language: str) -> str:
    return label[:1].lower() + label[1:]


def bills(view: dict[str, Any], language: str, ok: Ok, mode: str) -> Sentences | None:
    """mode: "due" (bills before payday), "typical" (the regular bills), "income" (salary and payday),
    "save_more" (only the bills due before payday)."""
    if mode == "income":
        when = _date(view.get("next_payday"), language) if isinstance(view.get("next_payday"), str) else None
        first = None
        for item in view.get("income") or []:      # the first row that can be named; the rest stay on the card
            amount = _tok(item.get("typical_month"))
            if not amount:
                continue
            if item.get("key") == "salary":
                first = (pick(SALARY, language).format(amount=amount), amount)
            elif isinstance(item.get("label"), str) and ok(item["label"]):
                name = item["label"][:1].lower() + item["label"][1:]
                first = (pick(OTHER_INCOME, language).format(income=name, amount=amount), amount)
            if first:
                break
        if first:
            end = pick(AND_PAYDAY, language).format(date=when) if when else "."
            return [first[0] + end], _ids(first[1])
        return ([pick(NEXT_PAYDAY, language).format(date=when)], []) if when else None

    if mode == "typical":
        items, cited = [], []
        for b in (view.get("bills") or [])[:3]:
            amount = _tok(b.get("typical_month"))
            if amount and isinstance(b.get("label"), str) and ok(b["label"]):
                items.append(pick(BILL_TYPICAL_ITEM, language).format(bill=_bill_name(b["label"], language),
                                                                     amount=amount))
                cited.append(amount)
        return ([pick(BILLS_TYPICAL, language).format(items=_join(items, language))], _ids(*cited)) if items else None

    total = _tok(view.get("upcoming_total"))
    if not total:
        return None
    if mode == "save_more":
        return [pick(BILLS_DUE["total"], language).format(total=total)], _ids(total)
    items, cited = [], [total]
    for b in (view.get("bills") or [])[:2]:
        amount = _tok(b.get("due_until_payday"))
        if amount and _value(b.get("due_until_payday")) and isinstance(b.get("label"), str) and ok(b["label"]):
            items.append(pick(BILL_ITEM, language).format(bill=_bill_name(b["label"], language), amount=amount))
            cited.append(amount)
    if items:
        return [pick(BILLS_DUE["items"], language).format(total=total, items=_join(items, language))], _ids(*cited)
    return [pick(BILLS_DUE["total"], language).format(total=total)], _ids(total)


# ---- what-if and safe to save -----------------------------------------------------------------------------

WHAT_IF = ("That cut would save you {month}, or {year}.", "Tämä leikkaus säästäisi sinulle {month} eli {year}.")
WHAT_IF_MONTH = ("That cut would save you {month}.", "Tämä leikkaus säästäisi sinulle {month}.")
WHAT_IF_BASE = {
    "named": ("Right now you spend {baseline} on {what}.", "Nyt käytät {baseline} {what}."),
    "plain": ("Right now that spending comes to {baseline}.", "Nyt tämä kulutus on {baseline}."),
}


def _what_if_subject(selection: Any, language: str) -> str | None:
    if not isinstance(selection, dict):
        return None
    kind, value = selection.get("kind"), selection.get("value")
    table = {"category": config.CATEGORY_LABELS, "basket": config.BASKET_LABELS,
             "mcc_group": config.MCC_GROUP_LABELS}.get(kind)
    if not table or value not in table:
        return None
    label = pick(table[value], language)
    return f"luokassa {label}" if language == "fi" else label.lower()


def what_if(view: dict[str, Any], language: str, ok: Ok) -> Sentences | None:
    if view.get("status") == "not_offered":
        caveats = [c for c in view.get("caveats") or [] if isinstance(c, str) and not re.search(r"\d", c)]
        return ([caveats[-1]], []) if caveats else None
    month, year, base = (_tok(view.get(k)) for k in ("saving_per_month", "saving_per_year", "baseline_per_month"))
    if not month:
        return None
    sentences = [pick(WHAT_IF if year else WHAT_IF_MONTH, language).format(month=month, year=year)]
    cited = [month, year]
    caveats = [c for c in view.get("caveats") or [] if isinstance(c, str) and not re.search(r"\d", c)]
    if view.get("status") == "estimate_with_caveat" and len(caveats) > 1:
        sentences.append(caveats[1])     # the caveat matters more than the current amount
    elif base:
        what = _what_if_subject(view.get("selection"), language)
        sentences.append(pick(WHAT_IF_BASE["named" if what else "plain"], language).format(baseline=base,
                                                                                          what=what or ""))
        cited.append(base)
    return sentences, _ids(*cited)


SAFE_TO_SAVE = ("You can typically put aside {monthly}.", "Voit tavallisesti säästää {monthly}.")
STOCK = ("Beyond what you need until payday, your account has {stock}.",
         "Tililläsi on {stock} enemmän kuin tarvitset palkkapäivään asti.")


def safe_to_save(view: dict[str, Any], language: str, save_more: bool) -> Sentences | None:
    monthly, stock = _tok(view.get("monthly")), _tok(view.get("stock"))
    if not monthly:
        return None
    reason = (view.get("reason") or {}).get("text")
    if _value(view.get("monthly")) == 0 and isinstance(reason, str) and not re.search(r"\d", reason):
        if save_more:                      # the reason, then the what-if offer: two sentences
            return [reason], []
        return [pick(SAFE_TO_SAVE, language).format(monthly=monthly), reason], _ids(monthly)
    sentences, cited = [pick(SAFE_TO_SAVE, language).format(monthly=monthly)], [monthly]
    if stock and not save_more:
        sentences.append(pick(STOCK, language).format(stock=stock))
        cited.append(stock)
    return sentences, _ids(*cited)


# ---- dispatch ---------------------------------------------------------------------------------------------

def for_view(view: dict[str, Any], language: str, ok: Ok, *, save_more: bool, asks_income: bool,
             bill_typical: bool) -> Sentences | None:
    """The sentences for one tool's view, or None when this module does not write that tool's answer."""
    tool = view.get("tool")
    if tool == "get_spending":
        return spending(view, language, ok)
    if tool == "get_basket_breakdown":
        return baskets(view, language, ok, save_more)
    if tool == "get_recurring_bills":
        mode = "save_more" if save_more else "income" if asks_income else "typical" if bill_typical else "due"
        return bills(view, language, ok, mode)
    if tool == "run_what_if":
        return what_if(view, language, ok)
    if tool == "get_safe_to_save":
        return safe_to_save(view, language, save_more)
    return None
