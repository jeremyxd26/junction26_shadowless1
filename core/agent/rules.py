"""A deterministic keyword model: the scripted model the service runs with until the Gemini adapter.

It is also the planner fallback of agent-core.md section 11 ("a keyword router maps the question to
the closest canonical intent, runs its tools and answers with a template"). It implements the same
two calls as any model and sees only what a model sees (model.py): the question, the tool
declarations and model views. It never sees the customer id.

The planner is table-driven and sized to what get_spending can answer. A question it cannot map
gets a clarifying question, never a guess. The composer is the template draft (template.py).
"""

from __future__ import annotations

import calendar
import json
import re
from datetime import date

from core.agent import template
from core.agent.model import ComposeInput, ComposeResult, FunctionCall, PlanInput, PlanResult
from core.tools import config

# (kind, pattern) in order: the first match declines the question. No data tool runs (R6, R10).
DECLINE_RULES = [
    ("unsafe", r"ignore (all |the )?(previous|prior|above) instructions|system override|admin mode|developer mode|"
               r"\btransfer\b|\bsiirrä\b|raw (transaction|row|record)s?|merchant ids?|raakatiedot"),
    ("other_person_data", r"\bCUST\d+|\bcustomer\b|neighbou?r|naapuri|my (friend|colleague|partner)'?s?\b|"
                          r"someone else|other (people|customers)|muiden|toisen"),
    ("credit_decision", r"mortgage|credit ?score|creditworth|approve (my |a )?loan|loan (be )?approved|"
                        r"asuntolaina|luottokelpo|myöntääkö|lainapäätös"),
    ("investment_advice", r"\b(should|which|what|best)\b.*\b(stocks?|shares?|funds?|etfs?|crypto|bitcoin)\b|"
                          r"\binvest (in|into)\b|\bput (my|the) (money|savings) into\b|"
                          r"kannattaako.*(sijoit|osak|rahasto)|mihin (minun )?(pitäisi|kannattaa) sijoittaa"),
    ("unsafe", r"\bam i (ill|sick|pregnant)\b|what illness|diagnos|olenko (sairas|raskaana)"),
    ("out_of_scope", r"just (estimate|guess)|any number|python|javascript|\bcode\b|\bvote\b|äänestää|election|vaali|"
                     r"medicine|headache|lääke|päänsärky|weather|sää\b|recipe"),
]

CATEGORY_WORDS = [
    (r"groceries|grocery|food shopping|ruoka(an|ostok\w*)?\b|ruokaostoks", "Groceries"),
    (r"restaurants?|dining out|eating out|eat out|ravintol\w*|ulkona syö\w*", "Restaurants"),
    (r"entertainment|viihtee\w*|viihde", "Entertainment"),
    (r"investments?|invested|\binvest\b|sijoit\w*", "Invest Deposit"),
    (r"housing|\brent\b|asumi\w*|vuokra\w*", "Housing"),
    (r"utilit\w*|electricity|sähkö\w*", "Utilities"),
    (r"\btravel\w*|matkailu\w*|matkoihin", "Travel"),
    (r"lifestyle|clothes|vaatte\w*", "Lifestyle"),
    (r"home (and|&) tech|electronics|kodin ja tekniikan", "Home & Tech"),
]
MCC_GROUP_WORDS = [
    (r"tax(i|is)\b|taksi\w*", "taxi"),
    (r"public transport|joukkoliiken\w*|bus(es)?\b|tram", "public_transport"),
    (r"\bfuel|petrol|gasoline|polttoaine\w*|bensa\w*", "fuel"),
    (r"parking|pysäköin\w*", "parking"),
]
MONTHS = {**{m.lower(): i for i, m in enumerate(calendar.month_name) if m},
          **{m.lower(): i for i, m in enumerate(calendar.month_abbr) if m},
          **{stem: i + 1 for i, stem in enumerate(("tammi", "helmi", "maalis", "huhti", "touko", "kesä", "heinä",
                                                    "elo", "syys", "loka", "marras", "joulu"))}}
MONTH_RX = (r"(january|february|march|april|may|june|july|august|september|october|november|december|"
            r"jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec|"
            r"(?:tammi|helmi|maalis|huhti|touko|kesä|heinä|elo|syys|loka|marras|joulu)(?=kuu))")

PRESETS = [
    (r"last (3|three) months|past (3|three) months|viimeisen (3|kolmen) kuukauden|viimeiset (3|kolme) kuukautta", "last_3_months"),
    (r"last (6|six) months|past (6|six) months|viimeisen (6|kuuden) kuukauden", "last_6_months"),
    (r"last (12|twelve) months|past year|viimeisen (12|vuoden)", "last_12_months"),
    (r"last month|previous month|viime kuussa|viime kuun|edellisen kuun", "last_month"),
    (r"this month|so far|tässä kuussa|tämän kuun|tähän mennessä", "this_month"),
    (r"this week|tällä viikolla", "this_week"),
    (r"last week|viime viikolla", "last_week"),
    (r"this year|year to date|tänä vuonna", "year_to_date"),
]
COMPARE = r"\bcompare|\bthan\b|\bvs\.?\b|versus|verrattuna|enemmän kuin|vähemmän kuin"
TOTAL = r"in total|so far in total|\bever\b|since (my|the) data|yhteensä|kaikkiaan"


def _month_range(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def _months_mentioned(q: str, as_of: date) -> list[tuple[int, int]]:
    """(year, month) of every month named in the question, in order."""
    out = []
    for m in re.finditer(MONTH_RX + r"\w*(?:\s+(\d{4}))?", q):
        month = MONTHS[m.group(1)]
        year = int(m.group(2)) if m.group(2) else (as_of.year if month <= as_of.month else as_of.year - 1)
        out.append((year, month))
    return out


def plan_spending(question: str, as_of: date) -> dict | None:
    """get_spending arguments for a spending question, or None if no period can be found."""
    q = question.lower()
    args: dict = {}
    categories = [c for rx, c in CATEGORY_WORDS if re.search(rx, q)]
    groups = [g for rx, g in MCC_GROUP_WORDS if re.search(rx, q)]
    flt = {}
    if groups:
        flt["mcc_groups"] = groups
    elif categories:
        flt["categories"] = categories
    if flt:
        args["filter"] = flt

    compare = bool(re.search(COMPARE, q))
    months = _months_mentioned(q, as_of)
    between = re.search(r"between (\d{1,2}) and (\d{1,2}) " + MONTH_RX + r"\w*\s+(\d{4})", q)
    year_only = re.search(r"\b(?:in|vuonna|vuoden)\s+(\d{4})\b", q)
    preset = next((p for rx, p in PRESETS if re.search(rx, q)), None)

    if between:
        month = MONTHS[between.group(3)]
        year = int(between.group(4))
        args["period"] = {"preset": "custom", "start": date(year, month, int(between.group(1))).isoformat(),
                          "end": date(year, month, int(between.group(2))).isoformat()}
    elif re.search(TOTAL, q):
        args["period"] = {"preset": "custom", "start": config.DATA_START.isoformat(), "end": as_of.isoformat()}
    elif preset:
        args["period"] = {"preset": preset}
    elif months:
        # With a comparison, the later month is the period and the earlier one its baseline.
        year, month = max(months) if compare else months[0]
        start, end = _month_range(year, month)
        this_month, last_month = (as_of.year, as_of.month), (as_of.year if as_of.month > 1 else as_of.year - 1,
                                                            as_of.month - 1 if as_of.month > 1 else 12)
        if (year, month) == this_month:
            args["period"] = {"preset": "this_month"}
        elif (year, month) == last_month:
            args["period"] = {"preset": "last_month"}
        else:
            args["period"] = {"preset": "custom", "start": start.isoformat(), "end": end.isoformat()}
    elif year_only:
        year = int(year_only.group(1))
        args["period"] = {"preset": "custom", "start": f"{year}-01-01", "end": f"{year}-12-31"}
    else:
        return None
    if compare:
        args["compare_to"] = "previous_period"
    if "categories" in flt and set(flt["categories"]) == {"Invest Deposit"}:
        args["direction"] = "out"
    return args


WHAT_IF = (r"\bsave\b|\bcut\b|\breduce|spend(ing)? less|spent half|half as much|less on|"
           r"säästä\w*|vähentä\w*|vähemmän|puolet")
PERCENT = r"(\d{1,3})\s?(?:%|percent|prosent\w*)"


def plan_what_if(question: str) -> dict:
    """run_what_if arguments: the category named in the question (dining out by default) and the cut
    the user gave (20% by default, half = 50%)."""
    q = question.lower()
    category = next((c for rx, c in CATEGORY_WORDS if re.search(rx, q) and c != "Invest Deposit"), "Restaurants")
    m = re.search(PERCENT, q)
    cut = int(m.group(1)) if m else 50 if re.search(r"half|puolet|puoleen", q) else 20
    return {"selection": {"kind": "category", "value": category}, "cut_pct": max(1, min(cut, 100))}


# The partner's questions and their tools (team-lead mapping). The first match wins; a question about
# a specific period or category falls through to get_spending.
BRIEF = [
    ("where_money_went", r"where did (all )?my money go|where does my money go|mihin rahani (meni|menivät|menee)",
     # The metric's window (metrics.md section 1): month averages of the last 6 complete months.
     lambda q, as_of: [("get_basket_breakdown", {"period": {"preset": "last_6_months"}})]),
    ("safe_to_spend", r"safe(ly)? to spend|safely spend|can i (safely )?spend this week|turvallisesti käyt\w*|"
                      r"voin käyttää tällä viikolla",
     lambda q, as_of: [("get_safe_to_spend", {})]),
    ("spender_type", r"what kind of spender|what type of spender|millainen kuluttaja",
     lambda q, as_of: [("get_spender_profile", {}), ("get_peer_benchmark", {"metric": "spend_total"})]),
    ("recurring_bills", r"\bbills?\b|payday|pay ?day|palkkapäivä|laskut|laskuni",
     lambda q, as_of: [("get_recurring_bills", {})]),
    ("what_if", WHAT_IF, lambda q, as_of: [("run_what_if", plan_what_if(q))]),
]
NOT_YET = ("I can't answer that one yet. I can tell you about your spending by category or period.",
           "En osaa vielä vastata tähän. Voin kertoa kulutuksestasi luokittain tai jaksoittain.")
NOT_YET_OPTIONS = (("How much did I spend last month?", "How much did I spend on restaurants last month?"),
                   ("Paljonko käytin viime kuussa?", "Paljonko käytin ravintoloihin viime kuussa?"))


class RuleModel:
    model_id = "rules@1"

    def plan(self, request: PlanInput) -> PlanResult:
        """Rules first: recognised=False means no rule matched, and the calls are the default clarifying
        question. A decline, a NOT_YET answer and every data call are recognised answers."""
        calls = self._calls(request)
        return PlanResult(calls=calls, recognised=calls != self._default_clarify(request.language))

    @staticmethod
    def _default_clarify(lang: str) -> list[FunctionCall]:
        return [FunctionCall("ask_clarifying_question", {
            "question": template.pick(template.CLARIFY["question"], lang),
            "options": list(template.pick(template.CLARIFY["options"], lang))})]

    def _calls(self, request: PlanInput) -> list[FunctionCall]:
        if request.responses:  # round 2: the data is in; write the answer
            return [FunctionCall("finish")]
        q = request.question.lower()
        for kind, rx in DECLINE_RULES:
            if re.search(rx, q, re.I):
                return [FunctionCall("decline", {"kind": kind})]
        tools = {t["name"] for t in request.tools}
        lang = request.language
        as_of = date.fromisoformat(request.as_of)
        spending = plan_spending(request.question, as_of) if "get_spending" in tools else None
        for intent, rx, build in BRIEF:
            if not re.search(rx, q, re.I):
                continue
            # A what-if or bills question that names a period is still a what-if or bills question;
            # a plain spending question with a period goes to get_spending below.
            if intent == "what_if" and spending is not None and not re.search(PERCENT + r"|half|puolet", q):
                break
            calls = [FunctionCall(name, args) for name, args in build(q, as_of) if name in tools]
            if calls:
                return calls + [FunctionCall("finish")]
            return [FunctionCall("ask_clarifying_question", {
                "question": template.pick(NOT_YET, lang), "options": list(template.pick(NOT_YET_OPTIONS, lang))})]
        if "get_spending" in tools:
            args = plan_spending(request.question, date.fromisoformat(request.as_of))
            if args is not None:
                return [FunctionCall("get_spending", args), FunctionCall("finish")]
        return self._default_clarify(request.language)

    def compose(self, request: ComposeInput) -> ComposeResult:
        return ComposeResult(text=json.dumps(
            template.template_draft(request.data, request.errors, request.language, None, request.question),
            ensure_ascii=False))
