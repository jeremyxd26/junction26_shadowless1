"""A deterministic keyword model: the scripted model the service runs with until the Gemini adapter.

It is also the planner fallback of agent-core.md section 11 ("a keyword router maps the question to
the closest canonical intent, runs its tools and answers with a template"). It implements the same
two calls as any model and sees only what a model sees (model.py): the question, the tool
declarations and model views. It never sees the customer id.

The planner is table-driven and sized to what get_spending can answer. A question it cannot map
gets a clarifying question, never a guess: no tool argument is filled in with a value the user did not
give (R1, design section 7.4; issue #142). The composer is the template draft (template.py).
"""

from __future__ import annotations

import calendar
import json
import re
from datetime import date

from core.agent import template
from core.agent.guard import fold, fold_pattern
from core.agent.model import ComposeInput, ComposeResult, FunctionCall, PlanInput, PlanResult
from core.tools import config

# A spouse or partner named in the question: another person, whose data the coach never shows (#216).
# Spending on or for them ("a gift for my wife") is the user's own spending.
RELATION = (r"(?<!on my )(?<!for my )(?<!to my )(?<!with my )"
            r"\b(wife|wives|husbands?|spouses?|(girl|boy)friends?|vaimo\w*|puoliso\w*|kumppani\w*|"
            r"tyttöystäv\w*|poikaystäv\w*|mies(tä)?|mieh\w+)\b|(?<!on )(?<!for )(?<!to )(?<!with )\b(my|our) partners?\b")

# (kind, pattern) in order: the first match declines the question. No data tool runs (R6, R10).
DECLINE_RULES = [
    ("unsafe", r"ignore (all |the )?(previous|prior|above) instructions|system override|admin mode|developer mode|"
               r"\btransfer\b|\bsiirrä\b|raw (transaction|row|record)s?|merchant ids?|raakatiedot"),
    ("other_person_data", r"\bCUST\d+|\bcustomer\b|neighbou?r|naapuri|my (friend|colleague|partner)'?s?\b|"
                          r"someone else|other (people|customers)|muiden|toisen|" + RELATION),
    ("credit_decision", r"mortgage|credit ?score|creditworth|approve (my |a )?loan|loan (be )?approved|"
                        r"asuntolaina|luottokelpo|myöntääkö|lainapäätös"),
    ("investment_advice", r"\b(should|which|what|best)\b.*\b(stocks?|shares?|funds?|etfs?|crypto|bitcoin)\b|"
                          r"\binvest(ing)? (in|into)\b|\bput (my|the) (money|savings) into\b|"
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
    (r"this month|so far|tässä kuussa|tämän kuun|tämä kuu\b|tämä kuukausi|tähän mennessä", "this_month"),
    (r"this week|tällä viikolla", "this_week"),
    (r"last week|viime viikolla", "last_week"),
    (r"this year|year to date|tänä vuonna", "year_to_date"),
]
COMPARE = r"\bcompare|\bthan\b|\bvs\.?\b|versus|verrattuna|vertautuu|enemmän kuin|vähemmän kuin"
TOTAL = r"in total|so far in total|\bever\b|since (my|the) data|yhteensä|kaikkiaan"


def _month_range(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def _months_mentioned(q: str, as_of: date) -> list[tuple[int, int]]:
    """(year, month) of every month named in the question, in order."""
    out = []
    for m in re.finditer(MONTH_RX + r"\w*(?:\s+(\d{4}))?", fold(q)):
        month = MONTHS[m.group(1)]
        year = int(m.group(2)) if m.group(2) else (as_of.year if month <= as_of.month else as_of.year - 1)
        out.append((year, month))
    return out


def plan_spending(question: str, as_of: date) -> dict | None:
    """get_spending arguments for a spending question, or None if no period can be found."""
    q = fold(question)
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


# "fewer" and "N % less" (#346): "what if I took 10% fewer taxis?", "what if I used taxis 10% less?".
WHAT_IF = (r"\bsave\b|\bcut\b|\breduce|spen[dt]\w*\s+(?:\S+\s+){0,2}less\b|spent half|half as much|less on|"
           r"\bfewer\b|(?:%|\bpercent|\bper cent)\s+less\b|"
           r"säästä\w*|säästöön|vähentä\w*|vähemmän|puolet")
PERCENT = r"(?<![\d.,])(\d+(?:[.,]\d+)?)\s?(?:%|percent\b|per cent\b|prosent\w*)"
HALF = r"\bhalf\b|\bpuolet\b|\bpuoleen\b|puolitta\w*"
# A health selection is never a what-if (R9): the health MCCs of core/tools/config.py and plain words.
HEALTH = (r"\bhealth(care)?\b|terveys\w*|terveyden\w*|pharmac\w*|apteek\w*|\bdoctors?\b|lääkär\w*|dentist\w*|"
          r"hammaslääk\w*|\b(?:" + "|".join(config.MCC_GROUPS["health"]) + r")\b")
# A selection the rules do not map (an MCC, a merchant): never replaced by a category of their own.
SELECTION_CODE = r"\bmcc\b|\bmerchants?\b|\bcode\b|kauppia\w*|koodi\w*"
# Everyday words for a what-if on merchant category codes (#346), resolved without the model. Each code is
# one that the four personas spend on in the what-if window (1 Apr - 30 Sep 2026, checked on the dataset;
# PR #346 lists who): taxi 4121, public transport 4111, fuel 5541/5542 and parking 7523 (the MCC groups of
# core/tools/config.py), fast food and takeaway 5814, bars 5813, cinemas 7832. Cafés, streaming and gyms
# have no code of their own in the data, so those words stay unmapped and the user is asked back.
WHAT_IF_MCC_WORDS = [(fold_pattern(rx), codes) for rx, codes in [
    (r"tax(i|is)\b|taksi\w*|takse\w*", config.MCC_GROUPS["taxi"]),
    (r"public transport|joukkoliiken\w*|\bbus(es)?\b|bussi\w*|busse\w*|\btrams?\b|ratikka\w*|raitiovaun\w*",
     config.MCC_GROUPS["public_transport"]),
    (r"\bfuel|petrol|gasoline|polttoaine\w*|bensa\w*|bensii\w*|tankkau\w*", config.MCC_GROUPS["fuel"]),
    (r"parking|pysäköin\w*|parkki\w*", config.MCC_GROUPS["parking"]),
    (r"take-?aways?|fast food|noutoruo\w*|pikaruo\w*", ("5814",)),
    (r"\bbars?\b|\bpubs?\b|baari\w*|baare\w*", ("5813",)),
    (r"cinemas?|\bmovies\b|elokuv\w*|leffa\w*|leffoi\w*", ("7832",)),
]]


def plan_what_if(question: str) -> tuple[str, dict | None]:
    """What the rules do with a what-if question. They never fill in a value the user did not give
    (R1, design section 7.4; issue #142). The question is read folded (without diacritics):
    - ("health", None): a health selection (R9): the refusal alone, no other scenario;
    - ("save_more", None): "How could I save more?" with no category and no cut: the design's tools
      for it (section 7.5) that need no number from the user, and the answer offers a what-if;
    - ("unmapped", None): not exactly one selection the rules know (a what-if category, or an everyday
      word of WHAT_IF_MCC_WORDS), or a code or merchant the user typed: not recognised, so the next
      planner, or a clarifying question, takes it;
    - ("amount", None): one selection but no cut, or a cut outside 1..100 % or not whole: ask how much;
    - ("run", args): run_what_if with that selection and the user's own cut ("half" is 50 %)."""
    q = fold(question)
    if re.search(HEALTH, q):
        return "health", None
    categories = {c for rx, c in CATEGORY_WORDS if re.search(rx, q)} & config.WHAT_IF_CATEGORIES
    codes = {c for rx, c in WHAT_IF_MCC_WORDS if re.search(rx, q)}
    pct = re.search(PERCENT, q)
    half = re.search(HALF, q)
    if not categories and not codes and not pct and not half and re.search(template.SAVE_MORE, q):
        return "save_more", None
    if (len(categories) + len(codes) != 1 or re.search(SELECTION_CODE, q)
            or (not codes and any(re.search(rx, q) for rx, _ in MCC_GROUP_WORDS))):
        return "unmapped", None
    if pct:
        value = float(pct.group(1).replace(",", "."))
        if value != int(value) or not 1 <= value <= 100:
            return "amount", None
        cut = int(value)
    elif half:
        cut = 50
    else:
        return "amount", None
    selection = ({"kind": "mcc", "value": ",".join(sorted(codes.pop()))} if codes
                 else {"kind": "category", "value": categories.pop()})
    return "run", {"selection": selection, "cut_pct": cut}


# The S-Bonus question (#216): "S-Bonus", "S-Group"/"S-ryhmä", or a bonus in a grocery context; an
# employer's bonus is not it. The share of groceries comes only from the user: "half" and "all" as words
# they typed, a whole percentage from 1 to 100 as typed. A share they stated that cannot be read or is
# outside that range is asked back, as the what-if does; no stated share means the tool's default (R1).
BONUS = (r"(?<!['’])\bs[- ]?bonu\w*|\bs-?ryhm\w*|\bs[- ]group\b|\bs-?etukortti\w*|"
         r"\bbonu\w*\b.*\b(grocer\w*|ruoka\w*|ostok\w*|kauppa\w*)|\b(grocer\w*|ruoka\w*|ostok\w*)\b.*\bbonu\w*|"
         r"\bbonusta\b(?!.*\b(työ\w*|palk\w*|esimie\w*)).*\b(saisin|saan|kertyy|kertyisi)\b")
SHARE_WORDS = [(r"\bhalf\b|\bpuolet\b|\bpuolella\b|\bpuolesta\b|puoleen", 50),
               (r"\ball\b|\bkaikki\w*", 100)]
# A share stated in a form the rules cannot read: a fraction or a number written as a word.
SHARE_UNREADABLE = (r"\b(a |one )?(third|quarter|fifth|tenth)s?\b|\b\w+sosa\w*|\b\d+\s?/\s?\d+\b|"
                    r"\b(ten|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred)\b|"
                    r"\b(kymmenen|kaksikymmentä|kolmekymmentä|neljäkymmentä|viisikymmentä|sata)\b")
BONUS_SHARE_ASK = ("Which share of your groceries should I count? Tell me as a whole percentage, or say half or all.",
                   "Minkä osuuden ruokaostoksistasi lasken? Kerro se kokonaisena prosenttina tai sano puolet tai kaikki.")


def plan_bonus(question: str) -> dict | None:
    """get_bonus_estimate arguments: the share the user typed, or none (the tool's default); None when
    the user stated a share that cannot be read or lies outside 1 to 100 (ask back)."""
    q = fold(question)
    m = re.search(PERCENT, q)
    if m:
        signed = re.search(r"[-\u2212\u2013]\s?$", q[:m.start()])
        value = float(m.group(1).replace(",", "."))
        if signed or value != int(value) or not 1 <= value <= 100:
            return None
        return {"share_pct": int(value)}
    if re.search(r"%|\bpercent\w*|\bprosent\w*", q) or re.search(fold_pattern(SHARE_UNREADABLE), q):
        return None
    for rx, share in SHARE_WORDS:
        if re.search(rx, q):
            return {"share_pct": share}
    return {}


# The peer comparison (#216): how I compare with people like me. It needs a peer word and the user
# themselves ("I", "my", a Finnish -ni form); it never falls into the month-over-month rule. What OTHER
# people spend, or their transactions, stays a refusal (another person's data), as does a named person.
PEERS = (r"people like me|people my age|others? (of )?my age|other people|others like me|\bmy peers\b|\bpeers?\b|"
         r"than others|than other people|compared? (with|to) (others|other people|people like me)|"
         r"kaltais\w*|ikäis\w*|ikätoveri\w*|muihin|muiden kanssa|verrattuna muihin|kuin muut\b|kuin muilla")
SELF = r"\b(i|me|my|mine|minä|minun|minulla|minua|olenko|kulutanko|kulutan|käytänkö)\b|\w{3,}ni\b"
OTHERS_DATA = (r"other people'?s|others'|\b(their|muiden) (transactions?|rows?|records?|tapahtum\w*|ostok\w*)|"
               r"what do (other people|others) (spend|buy)|mitä muut (kuluttavat|ostavat|käyttävät)")
SPECIFIC_PERSON = (r"\bCUST\d+|neighbou?r|naapuri|my (friend|colleague|partner)|someone else|\bcustomer\b|toisen|"
                   + RELATION)


# The partner's questions and their tools (team-lead mapping). The first match wins; a question about
# a specific period or category falls through to get_spending.
BRIEF = [
    ("where_money_went", r"where did (all )?my money go|where does my money go|mihin rahani (meni|menivät|menee)",
     # The metric's window (metrics.md section 1): month averages of the last 6 complete months.
     lambda q, as_of: [("get_basket_breakdown", {"period": {"preset": "last_6_months"}})]),
    ("safe_to_spend", r"safe(ly)? to spend|safely spend|spend safely|can i (safely )?spend this week|turvallisesti|"
                      r"voin käyttää tällä viikolla",
     lambda q, as_of: [("get_safe_to_spend", {})]),
    ("spender_type", r"what kind of spender|what type of spender|millainen kuluttaja",
     lambda q, as_of: [("get_spender_profile", {}), ("get_peer_benchmark", {"metric": "spend_total"})]),
    # Bills, payday and income: the template's own matchers, so the answer cites what was asked.
    ("recurring_bills", template.BILL_WORDS + "|" + template.INCOME_WORDS,
     lambda q, as_of: [("get_recurring_bills", {})]),
    ("bonus", BONUS, lambda q, as_of: [("get_bonus_estimate", plan_bonus(q))]),
    ("peers", PEERS, lambda q, as_of: [("get_peer_benchmark", {"metric": "spend_total"})]),
    ("what_if", WHAT_IF, None),  # plan_what_if, in RuleModel._calls
]
# "How could I save more?": where the money goes (the baskets) and the bills, the tools of design
# section 7.5 that need no number from the user. A safe-to-save figure joins once a tool exposes it.
SAVE_MORE_CALLS = [("get_safe_to_save", {}), ("get_basket_breakdown", {"period": {"preset": "last_6_months"}})]
# The what-if questions back never suggest an amount (review of PR #126): the user says how much.
WHAT_IF_AMOUNT = ("By how much would you like to cut it? Tell me as a percentage.",
                  "Kuinka paljon haluaisit vähentää? Kerro se prosentteina.")
# The selection asked back names only spending all four personas have (#346: restaurants, groceries,
# taxis, fuel and parking, checked on the dataset), so every example leads to a real what-if.
WHAT_IF_WHICH = ("Which spending would you like to cut, and by how much? For example restaurants, groceries, "
                 "taxis, fuel or parking.",
                 "Mitä kulutusta haluaisit vähentää ja kuinka paljon? Esimerkiksi ravintolat, ruokaostokset, "
                 "taksit, polttoaine tai pysäköinti.")
WHAT_IF_WHICH_OPTIONS = (("What if I cut restaurants?", "What if I cut groceries?", "What if I took fewer taxis?"),
                         ("Entä jos vähentäisin ravintoloita?", "Entä jos vähentäisin ruokaostoksia?",
                          "Entä jos käyttäisin taksia vähemmän?"))
# A money question the rules cannot map: it asks about the period only when it is about spending.
MONEY_WORDS = r"\bspen[dt]\w*|\bcost\w*|\bpaid\b|\bbought\b|kulut\w*|kaytin|kaytan|maksoin|ostin"
NOT_YET = ("I can't answer that one yet. I can tell you about your spending by category or period.",
           "En osaa vielä vastata tähän. Voin kertoa kulutuksestasi luokittain tai jaksoittain.")
NOT_YET_OPTIONS = (("How much did I spend last month?", "How much did I spend on restaurants last month?"),
                   ("Paljonko käytin viime kuussa?", "Paljonko käytin ravintoloihin viime kuussa?"))


# Every rule pattern is matched against a folded question, so the patterns are folded too.
BONUS, PEERS, SELF, OTHERS_DATA, SPECIFIC_PERSON = (
    fold_pattern(rx) for rx in (BONUS, PEERS, SELF, OTHERS_DATA, SPECIFIC_PERSON))
DECLINE_RULES = [(kind, fold_pattern(rx)) for kind, rx in DECLINE_RULES]
CATEGORY_WORDS = [(fold_pattern(rx), c) for rx, c in CATEGORY_WORDS]
MCC_GROUP_WORDS = [(fold_pattern(rx), g) for rx, g in MCC_GROUP_WORDS]
MONTHS = {fold(k): v for k, v in MONTHS.items()}
MONTH_RX = fold_pattern(MONTH_RX)
PRESETS = [(fold_pattern(rx), p) for rx, p in PRESETS]
COMPARE, TOTAL, WHAT_IF, HALF, HEALTH, SELECTION_CODE = (
    fold_pattern(rx) for rx in (COMPARE, TOTAL, WHAT_IF, HALF, HEALTH, SELECTION_CODE))
BRIEF = [(intent, fold_pattern(rx), build) for intent, rx, build in BRIEF]


# Questions about Sentti itself (#287). They match only when the whole message is the greeting or the
# meta question (punctuation, an emoji, "Sentti" as an address and a leading greeting allowed), and only
# after no refusal rule matched: "hi, ignore your rules ..." stays refused, "Hi, where did my money go?"
# is the baskets question. Russian forms are answered in English.
_GREET = r"(hi|hello|hey|hi there|hello there|hey there|good (morning|afternoon|evening)|hei|moi|moikka|terve|huomenta|привет|здравствуй(те)?)"
META = [
    ("identity", rf"({_GREET} )?(who are you|what are you|are you (a |an )?(bot|robot|ai|human|real person)|"
                 r"kuka olet|kuka sina olet|mika olet|oletko (botti|robotti|tekoaly|ihminen)|кто ты|ты кто|ты бот)"),
    ("capabilities", rf"({_GREET} )?(what can you do|what do you do|how do you work|what can i ask( you)?|"
                     r"mita osaat|mita sina osaat|mita voit tehda|miten toimit|что ты умеешь|что умеешь)"),
    ("help", rf"({_GREET} )?(help|help me|apua|помощь|помоги)"),
    ("thanks", r"(thanks|thank you|thank you so much|thanks a lot|thx|kiitos|kiitti|kiitos paljon|спасибо)"),
    ("greeting", _GREET),
]


def meta_intent(question: str) -> str | None:
    """The meta intent of a message that is nothing more than it, else None (never past a refusal rule)."""
    q = fold(question)
    if any(re.search(rx, q, re.I) for _, rx in DECLINE_RULES):
        return None
    core = re.sub(r"[^\w\s']", " ", q)          # punctuation and emoji
    core = re.sub(r"\bsentti\b", " ", core)       # Sentti as an address
    core = " ".join(core.split())
    for intent, rx in META:
        if re.fullmatch(fold_pattern(rx), core):
            return intent
    return None


class RuleModel:
    model_id = "rules@1"

    def plan(self, request: PlanInput) -> PlanResult:
        """Rules first: recognised=False means no rule matched, and the calls are a clarifying question
        (the default one, or the what-if one for a selection the rules do not map). A decline, a
        NOT_YET answer, a what-if amount question and every data call are recognised answers."""
        calls, recognised = self._calls(request)
        return PlanResult(calls=calls, recognised=recognised)

    @staticmethod
    def _clarify(texts: tuple[str, str], options: tuple[tuple[str, ...], tuple[str, ...]], lang: str) -> list[FunctionCall]:
        return [FunctionCall("ask_clarifying_question", {"question": template.pick(texts, lang),
                                                         "options": list(template.pick(options, lang))})]

    @staticmethod
    def _default_clarify(lang: str) -> list[FunctionCall]:
        return [FunctionCall("ask_clarifying_question", {
            "question": template.pick(template.CLARIFY["question"], lang),
            "options": list(template.pick(template.CLARIFY["options"], lang))})]

    def _calls(self, request: PlanInput) -> tuple[list[FunctionCall], bool]:
        if request.responses:  # round 2: the data is in; write the answer
            return [FunctionCall("finish")], True
        q = fold(request.question)  # "kayttaa" and "käyttää" match the same rules
        # A comparison with people like me is the peer benchmark (aggregates), not another person's data;
        # a named or specific person still is (#216).
        peer_question = (bool(re.search(PEERS, q)) and bool(re.search(SELF, q))
                         and not re.search(SPECIFIC_PERSON, q, re.I) and not re.search(OTHERS_DATA, q))
        for kind, rx in DECLINE_RULES:
            if kind == "other_person_data" and peer_question:
                continue
            if re.search(rx, q, re.I):
                return [FunctionCall("decline", {"kind": kind})], True
        tools = {t["name"] for t in request.tools}
        lang = request.language
        as_of = date.fromisoformat(request.as_of)
        spending = plan_spending(request.question, as_of) if "get_spending" in tools else None
        for intent, rx, build in BRIEF:
            if not re.search(rx, q, re.I):
                continue
            # A what-if or bills question that names a period is still a what-if or bills question;
            # a plain spending question with a period goes to get_spending below.
            if intent == "what_if" and spending is not None and not re.search(PERCENT + "|" + HALF, q):
                break
            if intent == "what_if" and re.search(r"\bsave (more )?time\b", q):
                continue  # saving time is no money question
            if intent == "recurring_bills" and re.search(template.SAVE_MORE, q):
                continue  # "save more of my income" is the save-more question, not the income
            if intent == "peers" and not peer_question:
                continue  # what others spend, a named person, or no "I": not the peer benchmark
            if intent == "bonus" and plan_bonus(q) is None:
                return self._clarify(BONUS_SHARE_ASK, ((), ()), lang), True
            if intent == "what_if":
                kind, what_if = plan_what_if(q)
                if kind == "health":
                    return [FunctionCall("decline", {"kind": "out_of_scope"})], True
                if kind == "unmapped":
                    return self._clarify(WHAT_IF_WHICH, WHAT_IF_WHICH_OPTIONS, lang), False
                if kind == "amount":
                    return self._clarify(WHAT_IF_AMOUNT, ((), ()), lang), True
                planned = SAVE_MORE_CALLS if kind == "save_more" else [("run_what_if", what_if)]
            else:
                planned = build(q, as_of)
            calls = [FunctionCall(name, args) for name, args in planned if name in tools]
            if calls:
                return calls + [FunctionCall("finish")], True
            return self._clarify(NOT_YET, NOT_YET_OPTIONS, lang), True
        if "get_spending" in tools:
            args = plan_spending(request.question, date.fromisoformat(request.as_of))
            if args is not None:
                return [FunctionCall("get_spending", args), FunctionCall("finish")], True
        if re.search(MONEY_WORDS, q) or any(re.search(rx, q) for rx, _ in CATEGORY_WORDS + MCC_GROUP_WORDS):
            return self._default_clarify(request.language), False      # a spending question without a period
        return self._clarify(template.CLARIFY_GENERAL["question"], template.CLARIFY_GENERAL["options"], lang), False

    def compose(self, request: ComposeInput) -> ComposeResult:
        return ComposeResult(text=json.dumps(
            template.template_draft(request.data, request.errors, request.language, None, request.question),
            ensure_ascii=False))
