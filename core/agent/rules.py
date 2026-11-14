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
from dataclasses import dataclass
from datetime import date

from core.agent import template
from core.agent.guard import flags, fold, fold_pattern
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
          **{m.lower(): i for i, m in enumerate(calendar.month_abbr) if m}, "sept": 9,
          **{stem: i + 1 for i, stem in enumerate(("tammi", "helmi", "maalis", "huhti", "touko", "kesä", "heinä",
                                                    "elo", "syys", "loka", "marras", "joulu"))}}
# A month is a whole word (#298): "Marja", "summarize", "decide", "doctor", "Juno" and "Augustin" name no
# month. Group 1 is an English name or abbreviation, group 2 a Finnish stem with "kuu" and its ending.
MONTH_RX = (r"(?:\b(january|february|march|april|may|june|july|august|september|october|november|december|"
            r"jan|feb|mar|apr|jun|jul|aug|sept|sep|oct|nov|dec)\b\.?|"
            r"\b(tammi|helmi|maalis|huhti|touko|kesä|heinä|elo|syys|loka|marras|joulu)kuu\w*)")
# "may" is also a verb ("how much may I spend?"): it is the month only after a preposition or a day, before
# a year or a day, or capitalised inside a sentence.
MAY_MONTH = (r"\b(in|of|for|during|since|from|until|till|to|through|and|or|vs|versus|than|between|last|this|next|"
             r"early|late|mid|before|after|\d{1,2}(st|nd|rd|th)?)\s+may\b|\bmay\s+(\d|and\b|or\b|vs\b|versus\b)")

PRESETS = [
    (r"last (3|three) months|past (3|three) months|viimeisen (3|kolmen) kuukauden|viimeiset (3|kolme) kuukautta", "last_3_months"),
    (RECENTLY := r"\blately\b|\brecently\b|\bthese days\b|\bof late\b|viime aikoina|viime kuukausina|viime aikoj\w*",
     "last_3_months"),
    (r"last (6|six) months|past (6|six) months|viimeisen (6|kuuden) kuukauden", "last_6_months"),
    (r"last (12|twelve) months|past year|viimeisen (12|vuoden)", "last_12_months"),
    (r"last month|previous month|viime kuussa|viime kuun\b|viime kuukausi\b|edellisen kuun|edellinen kuukausi", "last_month"),
    (r"this month|so far|tässä kuussa|tämän kuun|tämä kuu\b|tämä kuukausi|tähän mennessä", "this_month"),
    (r"this week|tällä viikolla", "this_week"),
    (r"last week|viime viikolla", "last_week"),
    (r"this year|year to date|tänä vuonna", "year_to_date"),
]
COMPARE = r"\bcompare|\bthan\b|\bvs\.?\b|versus|verrattuna|vertautuu|\bvertaa\w*|enemmän kuin|vähemmän kuin"
TOTAL = r"in total|so far in total|\bever\b|since (my|the) data|yhteensä|kaikkiaan"
ALL_TIME = r"so far in total|\bever\b|since (my|the) data"


def _month_range(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def _may_is_the_month(question: str) -> bool:
    if re.search(MAY_MONTH, fold(question)):
        return True
    # "May" capitalised after the first word of a sentence is the month ("How did May compare?").
    return any(question[:m.start()].strip() and question[:m.start()].rstrip()[-1] not in ".!?"
               for m in re.finditer(r"\bMay\b", question))


def _months_mentioned(question: str, as_of: date) -> list[tuple[int, int]]:
    """(year, month) of every month named in the question, in order."""
    out = []
    for m in re.finditer(MONTH_RX + r"(?:\s+(\d{4}))?", fold(question)):
        name = m.group(1) or m.group(2)
        if name == "may" and not _may_is_the_month(question):
            continue
        month = MONTHS[name]
        year = int(m.group(3)) if m.group(3) else (as_of.year if month <= as_of.month else as_of.year - 1)
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
    months = _months_mentioned(question, as_of)
    between = re.search(r"between (\d{1,2}) and (\d{1,2}) " + MONTH_RX + r"\s+(\d{4})", q)
    year_only = re.search(r"\b(?:in|vuonna|vuoden)\s+(\d{4})\b", q)
    presets = [p for rx, p in PRESETS if re.search(rx, q)]
    preset = presets[0] if presets else None
    if compare and {"this_month", "last_month"} <= set(presets):
        preset = "this_month"   # "compare this month with last month": this month, against the one before

    if between:
        month = MONTHS[between.group(3) or between.group(4)]
        year = int(between.group(5))
        args["period"] = {"preset": "custom", "start": date(year, month, int(between.group(1))).isoformat(),
                          "end": date(year, month, int(between.group(2))).isoformat()}
    elif re.search(ALL_TIME, q):
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
    elif re.search(TOTAL, q):   # "in total" with no period named: since the data starts
        args["period"] = {"preset": "custom", "start": config.DATA_START.isoformat(), "end": as_of.isoformat()}
    else:
        return None
    if compare or (preset == "last_3_months" and re.search(RECENTLY, q)):
        args["compare_to"] = "previous_period"   # "lately": against the three months before
    if "categories" in flt and set(flt["categories"]) == {"Invest Deposit"}:
        args["direction"] = "out"
    return args


WHAT_IF = (r"\bsave\b|\bcut\b|\breduce|spen[dt]\w*\s+(?:\S+\s+){0,2}less\b|spent half|half as much|less on|"
           r"säästä\w*|säästöön|vähentä\w*|vähemmän|puolet")
PERCENT = r"(?<![\d.,])(\d+(?:[.,]\d+)?)\s?(?:%|percent\b|per cent\b|prosent\w*)"
HALF = r"\bhalf\b|\bpuolet\b|\bpuoleen\b|puolitta\w*"
# A health selection is never a what-if (R9): the health MCCs of core/tools/config.py and plain words.
HEALTH = (r"\bhealth(care)?\b|tervey\w*|lääk(e|k)\w*|pharmac\w*|apteek\w*|\bdoctors?\b|lääkär\w*|dentist\w*|"
          r"hammaslääk\w*|\b(?:" + "|".join(config.MCC_GROUPS["health"]) + r")\b")
# A selection the rules do not map (an MCC, a merchant): never replaced by a category of their own.
SELECTION_CODE = r"\bmcc\b|\bmerchants?\b|\bcode\b|kauppia\w*|koodi\w*"


def plan_what_if(question: str) -> tuple[str, dict | None]:
    """What the rules do with a what-if question. They never fill in a value the user did not give
    (R1, design section 7.4; issue #142). The question is read folded (without diacritics):
    - ("health", None): a health selection (R9): the refusal alone, no other scenario;
    - ("save_more", None): "How could I save more?" with no category and no cut: the design's tools
      for it (section 7.5) that need no number from the user, and the answer offers a what-if;
    - ("unmapped", None): not exactly one what-if category the rules know, or an MCC, merchant or
      transport group: not recognised, so the next planner, or a clarifying question, takes it;
    - ("amount", None): one category but no cut, or a cut outside 1..100 % or not whole: ask how much;
    - ("run", args): run_what_if with that category and the user's own cut ("half" is 50 %)."""
    q = fold(question)
    if re.search(HEALTH, q):
        return "health", None
    categories = {c for rx, c in CATEGORY_WORDS if re.search(rx, q)} & config.WHAT_IF_CATEGORIES
    pct = re.search(PERCENT, q)
    half = re.search(HALF, q)
    if not categories and not pct and not half and re.search(template.SAVE_MORE, q):
        return "save_more", None
    if (len(categories) != 1 or re.search(SELECTION_CODE, q)
            or any(re.search(rx, q) for rx, _ in MCC_GROUP_WORDS)):
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
    return "run", {"selection": {"kind": "category", "value": categories.pop()}, "cut_pct": cut}


# The S-Bonus question (#216): "S-Bonus", "S-Group"/"S-ryhmä", or a bonus in a grocery context; an
# employer's bonus is not it. The share of groceries comes only from the user: "half" and "all" as words
# they typed, a whole percentage from 1 to 100 as typed. A share they stated that cannot be read or is
# outside that range is asked back, as the what-if does; no stated share means the tool's default (R1).
S_GROUP_CHAINS = r"s-?market\w*|prisma\w*|alepa\w*|\bsale\b|\babc\b|sokos\w*|herkku\w*"
BONUS = (r"(?<!['’])\bs[- ]?bonu\w*|\bs-?ryhm\w*|\bs[- ]group\b|\bs-?etukortti\w*|"
         r"\bbonu\w*\b.*\b(grocer\w*|ruoka\w*|ostok\w*|kauppa\w*)|\b(grocer\w*|ruoka\w*|ostok\w*)\b.*\bbonu\w*|"
         rf"\bbonu\w*\b.*\b({S_GROUP_CHAINS})|\b({S_GROUP_CHAINS}).*\bbonu\w*|"
         r"\bbonusta\b(?!.*\b(työ\w*|palk\w*|esimie\w*)).*\b(saisin|saan|kertyy|kertyisi|tienaisin|ansaitsisin)\b")
# A bonus word the S-Bonus rule does not claim ("How much could I earn in bonus?") competes with the
# income rule: an employer's bonus or the S-Bonus, the planner or a question back decides.
BONUS_WORD = r"\bbonu\w*"
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
# Small everyday purchases (#256): "Where do my small purchases go?", "How much do I spend on coffees and
# snacks?", "Mihin pienet ostokset menevät?". Plural forms only: "that small purchase" is one purchase, not
# the tool's question. Never the baskets question ("Where did my money go?").
SMALL_PURCHASES = (r"\bsmall (purchases|buys|expenses)\b|\blittle (purchases|buys|things)\b|"
                   r"\bcoffees? and snacks\b|\bsnacks and coffees?\b|"
                   r"\bpien(et|iä|ten|iin|issä|istä|illä|ille) "
                   r"(ostoks(et|ia|ien|iin|issa|ista|illa|ille|eni|iani|iini|issani|istani)|"
                   r"hankin(nat|toja|tojen|toihin|noissa|noista))\b|"
                   r"\bpikkuostoks(et|ia|ien|iin|issa|ista|illa|ille|eni|iani)\b|"
                   r"\bkahvi\w* ja (välipalo|naposte)\w*")
# The rule claims a small-purchases question only when nothing is left after removing the trigger, the
# default period ("the last 3 months") and these words: anything else (an amount, a period, a filter, a
# what-if) may change the question, so the next planner reads it (a rule claims only a confident full
# match; review of #390). Folded, like every rule pattern.
SMALL_FILLERS = frozenset({
    "where", "do", "does", "did", "my", "go", "goes", "went", "how", "much", "many", "show", "me", "count",
    "add", "adds", "added", "up", "to", "spend", "spent", "on", "i", "make", "made", "the", "in", "over",
    "during", "cost", "costs", "what", "are", "all",
    "mihin", "minun", "menevat", "menivat", "menee", "meni", "paljonko", "kuinka", "paljon", "montako",
    "nayta", "kaytan", "kaytin", "kulutan", "kulutin", "rahani", "rahat", "rahaa", "mita", "ovat", "aikana",
})
OTHERS_DATA = (r"other people'?s|others'|\b(their|muiden) (transactions?|rows?|records?|tapahtum\w*|ostok\w*)|"
               r"what do (other people|others) (spend|buy)|mitä muut (kuluttavat|ostavat|käyttävät)")
SPECIFIC_PERSON = (r"\bCUST\d+|neighbou?r|naapuri|my (friend|colleague|partner)|someone else|\bcustomer\b|toisen|"
                   + RELATION)


# "Will my money last until payday?" (#257). It needs the money or balance phrasing, so a bills
# question that only mentions payday still goes to the bills; Finnish with or without ä and ö. A
# question about the past ("since last payday", "what was my balance") is not a forecast.
PAYDAY = (r"(?:pay ?day|next salary|(?:my )?salary (?:arrives|comes|lands|is paid)|palkkap[äa]iv\w*|palkka\w*|"
          r"palkan tulo\w*)")
FORECAST_PAST = (r"\b(?:was|were|did|had|since|oli|olivat|oliko|olivatko)\b|"
                 r"\blast (?:month|week|year|payday)\b|\bviime\w*\b")
FORECAST = (r"^(?!.*(?:" + FORECAST_PAST + r")).*?(?:"
            r"\b(?:money|cash|balance|savings|it)\b.{0,20}\blast\s+(?:until|till|to|through|before)\b.{0,15}"
            + PAYDAY + "|"
            r"\benough (?:money|cash)\b.{0,25}" + PAYDAY + "|"
            r"\benough\b.{0,20}\blast\s+(?:until|till|to)\b.{0,15}" + PAYDAY + "|"
            r"\bbalance\b.{0,30}\b(?:before|until|till|by)\b.{0,10}" + PAYDAY + "|"
            r"what will my balance be|balance forecast|forecast (?:of )?my balance|how low will my balance|"
            r"\blowest (?:point|balance)\b.{0,30}\b(?:before|until|till)\b.{0,10}" + PAYDAY + "|"
            r"run out of money|make it (?:to|until|till) " + PAYDAY + "|"
            r"riitt(?:[äa]v[äa]tk[öo]|[äa][äa]k[öo])\b.{0,40}" + PAYDAY + "|"
            r"\bsaldo\w*\b.{0,30}\bennen\b.{0,10}" + PAYDAY + "|"
            r"\bsaldo\w*\b.{0,30}" + PAYDAY + r"\s+(?:asti|mennessä|mennessa)\b|"
            r"p[äa]rj[äa][äa]nk[öo]\b.{0,30}" + PAYDAY + "|"
            r"loppu(?:vatko|uko)\b.{0,20}\brah|\brah\w*\b.{0,20}loppu(?:vatko|uko))")

# The intents the rules know, each with its own full pattern (#316, #340). Which one claims a message is
# decided in claim() below.
# 1. "Where did my money go?": where the money goes, what it goes to most, a breakdown.
WHERE = (r"\bwhere('s| is| did| does| do| has| have| was)\b.*\bmoney\b.*\b(go|goes|went|gone|going|disappear\w*|vanish\w*)\b|"
         r"\b(spend|spending|spent) (the )?most\b|\bmost of my money\b|\bbiggest (expenses?|spending|costs?)\b|"
         r"\b(spending )?break ?down\b|\bwhat do i spend (my )?money on\b|"
         r"\bmihin\b.*\braha\w*\b.*\b(meni\w*|menee|menev\w*|mennyt|menneet|kulu\w*|katoa\w*|hävi\w*)|"
         r"\bmihin\b.*\beniten\b|\beniten rahaa\b")
# 2. "What kind of spender am I?": the user's type, style or habits.
SPENDER = (r"\bwhat (kind|type|sort) of (spender|saver|consumer)\b|\b\w+ of (spender|saver) am i\b|"
           r"\bspending (style|habits?|personality|profile|type|pattern)s?\b|\bdescribe (my )?spending\b|"
           r"\bam i an? (\w+ ){0,3}(spender|saver)\b|"
           r"\bmill?ai?nen (kuluttaja|rahankäyttäjä|säästäjä|tuhlaaja)\b|\bolenko (tuhlari|tuhlaaja|säästäjä|pihi|nuuka)\b|"
           r"\bkulutustottumu\w*|\brahankäyttäjä\w*")
# 3. "What can I safely spend this week?": what the user MAY spend: a limit, a budget, what is left, what
#    they can afford (#316). A question about what they DID spend (PAST) is the spending rule's.
SAFE = (r"safe(ly)? to spend|safely spend|spend safely|\bturvallisesti\b|"
        r"(?<!credit )\b(spending )?limit\b|\bbudget\w*|budjet\w*|"
        r"\bleft to spend\b|\b(have|got) (left )?to spend\b|\b(have|got) left (this|for the|for this) week\b|"
        r"\b(the )?most i (can|could) spend\b|"
        r"\b(can|could|may) i (\w+ly )?(spend|afford)\b|\bafford\b|"
        r"\bok(ay)? (if|to) (i )?spend\b|\ball right (if|to) (i )?spend\b|"
        r"\b(voin|voinko|saan|saanko|uskallanko) (turvallisesti )?(käyttää|kuluttaa|tuhlata)\b|"
        r"\bpaljon(ko)? (mä |minä )?voin\b(?!.*säästä)|"
        r"\bkäytettävissä\b|\bjäljellä\b.*\b(tällä viikolla|käyttää|kuluttaa|tuhlata)\b|"
        r"\b(tällä viikolla|käytettäväksi)\b.*\bjäljellä\b|\b(on|onko) (minulla |mulla )?varaa\b")
NOT_SAFE = (r"\b(cards?|credit|overdraft|withdraw\w*|raise|increase|loans?|borrow\w*|lainaa?\w*|luoto\w*|"
            r"kortin|korttiraja\w*|nostoraja\w*)\b|"
            # a future occasion or another horizon: the safe-to-spend figure is the next seven days
            r"\bnext (year|month|summer|winter|spring|autumn|christmas)\b|\bwedding\b|\bin the future\b|"
            r"\bnext week\w*|\bcoming week\b|\bensi viiko\w*|\bmonthly\b|\bkuukausibudjet\w*|\bkuukauden budjet\w*|"
            r"\bin a year\b|\bnext \d+ days\b|\bend of (the|this) month\b|\bkuun loppuun\b|\bvuoden päästä\b|"
            r"\bvuodessa\b|\bseuraava\w* \d+ päivä\w*|\bkuukauden loppuun\b|\btuleva\w* viiko\w*|"
            r"\bensi (vuonna|vuodeksi|kuussa|kesänä|talvena|jouluna)\b|\bhäi\w*|\bhäät\b|\btulevaisuude\w*")
# 3. A message about a total, or a spending question without "I" ("How much was spent?", "Paljonko meni
#    elokuussa?"), stands on its own in a conversation.
COMPLETE_WORDS = (r"\btotal\b|\boverall\b|\bspending\b|\b(was|were|been) spent\b|\byhteensä\b|\bkaikkiaan\b|\bkokonais\w*|"
                  r"\bmeni\b|\bmenivät\b|\bkului\w*")
# An attempt to set the rules aside ("ignore your rules, what's my budget?") is never claimed by a data
# rule; the input guard does not flag these forms yet (#205).
SET_ASIDE = (r"\b(ignore|forget|disregard|bypass) (all |any )?(your|the|my|these|those|previous|prior) "
             r"(rules|instructions|guidelines|limits)\b|"
             r"\b(pretend|imagine|act as if|suppose)\b.*\bno (rules|limits|restrictions|instructions|guidelines)\b|"
             r"\b(unohda|ohita)\b.*\b(säänn\w*|sääntö\w*|ohje\w*|rajoitu\w*)|"
             r"\b(esitä|kuvittele|oleta)\b.*\b(ei|ettei)\b.*\b(säänn\w*|sääntö\w*|ohje\w*|rajoitu\w*)")
# 4. What other people spend most on is no question about the user's own money.
WHERE_OTHERS = r"\bwho\b|\bpeople\b|\bothers?\b|\beveryone\b|\bmuut\b|\bmuiden\b|\bihmiset\b|\bkuka\b"
# Another person's profile ("what kind of spender is Marjatta?") is not the user's own (#298).
SPENDER_OTHER = (r"\bwhat (kind|type|sort) of (spender|saver|consumer) (is|are|was|were)\b|"
                 r"\bmill?ai?nen (kuluttaja|rahankäyttäjä|säästäjä|tuhlaaja) (?!(olen|olenko|oon|olisin|mä|minä|ma|mina)\b)\w+")
PAST = (r"\bdid (i|we)\b|\b(have|has) (i|we) (spent|paid|bought|used)\b|\bi('ve| have)? (spent|paid|bought)\b|"
        r"\bspent\b|\bwas i\b|\bkulutin\b|\bkäytin\b|\bkäytinkö\b|\bolen (käyttänyt|kuluttanut|maksanut)\b|"
        r"\bmaksoin\b|\bostin\b")
# The spending rule needs a period (plan_spending) and a word about spending: a money word, a category or
# group, "how much", a comparison of named months, or a total.
SPEND_SIGNAL = (r"\bhow much\b|\bpaljonko\b|\bkuinka paljon\b|\bexpens\w*|\bmenot\b|\bmenoni\b|\bbuy\b|\bostanut\b|"
                r"\btotal\b|\boverall\b")
# A message with its own subject and verb about the user's money is complete; anything else in a running
# conversation ("compared to August?", "and restaurants?") is a follow-up of the previous turn (#300).
SELF_SPEND = (r"\b(i|we)\b.*\b(spen[dt]\w*|paid|pay|bought|buy|earn\w*|save\w*|afford|cost\w*|get)\b|"
              r"\bmy (spending|money|expenses|budget|income|salary|bills)\b|"
              r"\bkulutin\b|\bkäytin\b|\bkäytinkö\b|\bkulutukse\w*|\bolen (käyttänyt|kuluttanut|maksanut)\b|"
              r"\bmaksoin\b|\bostin\b|\bvoinko\b|\btienaan\b|\bmenoni\b|\brahani\b")
INTENTS = [
    # Small everyday purchases (#256): only the plain question is claimed (small_purchases_whole); a cut or a
    # comparison of them goes to the what-if or peer rule (in _matched).
    ("small_purchases", SMALL_PURCHASES),
    ("where_money_went", WHERE),
    ("safe_to_spend", SAFE),
    ("spender_type", SPENDER),
    ("balance_forecast", FORECAST),   # "Will my money last until payday?" (#257)
    # Bills, payday and income: the template's own matchers, so the answer cites what was asked.
    ("recurring_bills", template.BILL_WORDS + "|" + template.INCOME_WORDS),
    ("bonus", BONUS),
    ("peers", PEERS),
    ("what_if", WHAT_IF),  # plan_what_if: a cut, or "how could I save more?"
]
# "How could I save more?": the savings plan (#369), which composes the what-if cuts, safe to save and the
# S-Bonus extra and needs no number from the user. Without that tool, the earlier answer: safe to save and
# where the money goes (the baskets).
SAVE_MORE_PLAN = [("get_savings_plan", {})]
SAVE_MORE_CALLS = [("get_safe_to_save", {}), ("get_basket_breakdown", {"period": {"preset": "last_6_months"}})]
# The what-if questions back never suggest an amount (review of PR #126): the user says how much.
WHAT_IF_AMOUNT = ("By how much would you like to cut it? Tell me as a percentage.",
                  "Kuinka paljon haluaisit vähentää? Kerro se prosentteina.")
WHAT_IF_WHICH = ("Which spending would you like to cut, and by how much?",
                 "Mitä kulutusta haluaisit vähentää ja kuinka paljon?")
WHAT_IF_WHICH_OPTIONS = (("What if I cut restaurants?", "What if I cut groceries?"),
                         ("Entä jos vähentäisin ravintoloita?", "Entä jos vähentäisin ruokaostoksia?"))
# A money question the rules cannot map: it asks about the period only when it is about spending.
MONEY_WORDS = r"\bspen[dt]\w*|\bcost\w*|\bpaid\b|\bbought\b|kulut\w*|kaytin|kaytan|maksoin|ostin"
NOT_YET = ("I can't answer that one yet. I can tell you about your spending by category or period.",
           "En osaa vielä vastata tähän. Voin kertoa kulutuksestasi luokittain tai jaksoittain.")
NOT_YET_OPTIONS = (("How much did I spend last month?", "How much did I spend on restaurants last month?"),
                   ("Paljonko käytin viime kuussa?", "Paljonko käytin ravintoloihin viime kuussa?"))


class OfferContact(list):
    """Calls whose answer offers the way to a human at the bank (#420): the NOT_YET answer. Set where that
    text is chosen; RuleModel.plan turns it into PlanResult.offer_contact."""


# Every rule pattern is matched against a folded question, so the patterns are folded too.
BONUS, PEERS, SELF, OTHERS_DATA, SPECIFIC_PERSON, BONUS_WORD, SMALL_PURCHASES = (
    fold_pattern(rx) for rx in (BONUS, PEERS, SELF, OTHERS_DATA, SPECIFIC_PERSON, BONUS_WORD, SMALL_PURCHASES))
WHERE, SPENDER, SAFE, NOT_SAFE, PAST, SPEND_SIGNAL, SELF_SPEND, COMPLETE_WORDS, SET_ASIDE, MAY_MONTH = (
    fold_pattern(rx) for rx in (WHERE, SPENDER, SAFE, NOT_SAFE, PAST, SPEND_SIGNAL, SELF_SPEND, COMPLETE_WORDS,
                                SET_ASIDE, MAY_MONTH))
# Savings and income are never compared with other people (#418): "do people like me save more than me?"
PEER_NOT_COMPARED = (r"\bsav(e|es|ed|ing|ings)\b|\bincome\b|\bsalary\b|\bearn\w*|\bsäästä\w*|\bsäästö\w*|"
                     r"\btulo\w*|\bpalk\w*|\btienaa?\w*|\bansai\w*")
# ... unless the comparison is of spending: "Do I spend more than people like me so I can save?"
PEER_SPEND_COMPARED = r"\b(spend|spending|spent|kulutan\w*|kulutukse\w*|käytän\w*)\b.{0,12}\b(more|less|enemmän|vähemmän)\b"
WHERE_OTHERS, SPENDER_OTHER, PEER_NOT_COMPARED, PEER_SPEND_COMPARED = (
    fold_pattern(rx) for rx in (WHERE_OTHERS, SPENDER_OTHER, PEER_NOT_COMPARED, PEER_SPEND_COMPARED))
DECLINE_RULES = [(kind, fold_pattern(rx)) for kind, rx in DECLINE_RULES]
CATEGORY_WORDS = [(fold_pattern(rx), c) for rx, c in CATEGORY_WORDS]
MCC_GROUP_WORDS = [(fold_pattern(rx), g) for rx, g in MCC_GROUP_WORDS]
MONTHS = {fold(k): v for k, v in MONTHS.items()}
MONTH_RX = fold_pattern(MONTH_RX)
PRESETS = [(fold_pattern(rx), p) for rx, p in PRESETS]
COMPARE, TOTAL, ALL_TIME, WHAT_IF, HALF, HEALTH, SELECTION_CODE, RECENTLY = (
    fold_pattern(rx) for rx in (COMPARE, TOTAL, ALL_TIME, WHAT_IF, HALF, HEALTH, SELECTION_CODE, RECENTLY))
INTENTS = [(intent, fold_pattern(rx)) for intent, rx in INTENTS]


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


def small_purchases_whole(q: str) -> bool:
    """A folded question is the plain small-purchases question and nothing more: after removing the trigger,
    the default period ("the last 3 months", which the tool uses anyway) and SMALL_FILLERS, no word is left.
    An amount, another period, a filter or a what-if in words or digits leaves a word, so it is not claimed."""
    default = next(rx for rx, p in PRESETS if p == config.SMALL_PURCHASE_DEFAULT_PERIOD)
    rest = re.sub(default, " ", re.sub(SMALL_PURCHASES, " ", q))
    return all(word in SMALL_FILLERS for word in re.findall(r"[\w']+", rest))


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


# ---- which rule claims a message (#281, #300, #316, #340, #357) ----------------------------------------
# A rule claims a message only when it is confident: its own pattern matches and no other rule's does,
# except for the priorities below. Two rules that compete, or a word another rule owns ("bonus" next to
# "earn"), are not claimed: the model's planner decides, and without the model the rules ask back with
# the candidates' own questions as options. A question in several clauses ("Where did my money go and
# what can I spend?") is claimed only when every clause is, and then every part is planned. In a running
# conversation a message that is not complete on its own is a follow-up of the previous turn (#300).

# (winner, loser): when both match one clause, the winner claims it; every other pair competes. Some
# priorities hold only on a condition, in _beats: safe to spend over spending only without a word about
# the past (PAST), over the bills rule only without a bills word; the breakdown over spending only
# without a category; save more over income only with the save-more words; a what-if over spending only
# with a cut the user stated.
PRECEDENCE = {
    # the small purchases come before spending and the breakdown (#390)
    ("small_purchases", "spending"), ("small_purchases", "where_money_went"), ("small_purchases", "safe_to_spend"),
    ("bonus", "recurring_bills"), ("bonus", "what_if"), ("bonus", "spending"), ("bonus", "peers"),
    ("safe_to_spend", "spending"), ("safe_to_spend", "recurring_bills"),
    ("balance_forecast", "recurring_bills"), ("balance_forecast", "spending"),   # payday words (#257)
    ("bonus", "where_money_went"), ("bonus", "safe_to_spend"),
    ("where_money_went", "spending"),
    ("spender_type", "peers"), ("spender_type", "spending"),
    ("recurring_bills", "spending"),
    ("peers", "spending"), ("peers", "what_if"),
}
MAX_DATA_CALLS = 6  # the pipeline's limit for one answer (orchestrator.MAX_DATA_CALLS)
# The questions offered when rules compete: each is claimed by its own rule.
CANDIDATE_QUESTIONS = {
    "where_money_went": template.BRIEF_QUESTIONS[0],
    "spender_type": template.BRIEF_QUESTIONS[1],
    "safe_to_spend": template.BRIEF_QUESTIONS[2],
    "what_if": template.BRIEF_QUESTIONS[3],
    "spending": ("How much did I spend this month?", "Paljonko käytin tässä kuussa?"),
    "recurring_bills": ("Which bills are coming up next?", "Mitkä laskut ovat tulossa seuraavaksi?"),
    "bonus": ("How much S-Bonus could I get?", "Paljonko S-Bonusta voisin saada?"),
    "small_purchases": ("Where do my small purchases go?", "Mihin pienet ostokset menevät?"),
    "balance_forecast": ("Will my money last until payday?", "Riittävätkö rahani palkkapäivään?"),
    "peers": ("How do I compare with people like me?", "Miten kulutukseni vertautuu kaltaisiini?"),
}
CLARIFY_WHICH = ("Which of these do you mean?", "Mitä näistä tarkoitat?")
# Where one question ends and the next starts: a question mark with more text after it, or "and", a comma
# or a semicolon before a question word.
_QUESTION_WORD = (r"(?:what|where|how|when|which|why|can|could|should|is|are|am|do|does|did|will|would|tell|show|"
                  r"mita|mihin|paljonko|kuinka|voinko|onko|miten|missa|mista|millainen|milloin|mika)\b")
CLAUSE_BREAK = rf"\?\s+(?=\S)|[,;]\s*(?={_QUESTION_WORD})|\s+(?:and|also|plus|ja|seka)\s+(?={_QUESTION_WORD})"
# A follow-up compared with a baseline the get_spending tool knows (CompareTo).
BASELINE_LAST_YEAR = (r"\blast year\b|\ba year (ago|before|earlier)\b|\bsame (month|period|time) last year\b|"
                      r"\bviime vuo\w*|\bvuotta (aiemmin|sitten)\b|\bedellisvuo\w*")
BASELINE_TYPICAL = r"\b(typical|usual|normal|average)\w*|\btavallis\w*|\bkeskimäär\w*|\bnormaali\w*"
LAST_MONTH_WORDS = r"\blast month\b|\bprevious month\b|\bviime kuu\w*|\bedelli\w* kuu\w*"
FOLLOW_TOOLS = ("get_spending", "get_basket_breakdown")
BASELINE_LAST_YEAR, BASELINE_TYPICAL, LAST_MONTH_WORDS = (
    fold_pattern(rx) for rx in (BASELINE_LAST_YEAR, BASELINE_TYPICAL, LAST_MONTH_WORDS))


@dataclass(frozen=True)
class Claim:
    """What the rules do with a message: rule is the rule that claims it, None when none does."""

    rule: str | None
    calls: tuple[FunctionCall, ...] = ()
    candidates: tuple[str, ...] = ()   # not claimed: the rules that competed for it
    reason: str = ""                   # not claimed: "competing", "period", "what_if_which", "follow_up", ""
    offer_contact: bool = False        # the NOT_YET answer: it offers the way to the bank (#420)


def _filter_of(q: str) -> dict:
    groups = [g for rx, g in MCC_GROUP_WORDS if re.search(rx, q)]
    categories = [c for rx, c in CATEGORY_WORDS if re.search(rx, q)]
    return {"mcc_groups": groups} if groups else {"categories": categories} if categories else {}


def _spending_words(q: str) -> bool:
    return bool(re.search(MONEY_WORDS, q) or re.search(SPEND_SIGNAL, q) or _filter_of(q))


def _matched(q: str, peer_question: bool, spending: dict | None) -> list[str]:
    """Every rule whose own pattern matches the clause."""
    found = []
    for intent, rx in INTENTS:
        if not re.search(rx, q):
            continue
        if intent == "what_if" and re.search(r"\bsave (more )?time\b", q):
            continue  # saving time is no money question
        if intent == "recurring_bills" and re.search(template.SAVE_MORE, q):
            continue  # "save more of my income" is the save-more question, not the income (#296)
        if intent == "peers" and re.search(PEER_NOT_COMPARED, q) and not re.search(PEER_SPEND_COMPARED, q):
            continue  # savings and income are not compared with others (#418)
        if intent == "peers" and not peer_question:
            continue  # what others spend, a named person, or no "I": not the peer benchmark
        if intent == "small_purchases" and (re.search(WHAT_IF, q) or peer_question):
            continue  # a cut or a comparison of the small purchases: the what-if or peer rule (#390)
        if intent == "safe_to_spend" and re.search(NOT_SAFE, q):
            continue  # a card or credit limit, a loan, a raise, another horizon
        if intent == "where_money_went" and re.search(WHERE_OTHERS, q):
            continue  # "who spent the most", "what do people spend the most on"
        if intent == "spender_type" and re.search(SPENDER_OTHER, q):
            continue  # another person's profile
        found.append(intent)
    if "recurring_bills" in found and "bonus" not in found and re.search(BONUS_WORD, q):
        found.append("bonus")  # "earn in bonus": an employer's bonus or the S-Bonus (#357)
    if spending is not None and (_spending_words(q) or re.search(TOTAL, q) or re.search(COMPARE, q)):
        found.append("spending")
    elif ("safe_to_spend" in found and (re.search(PAST, q) or _other_period(spending))) or \
            (_filter_of(q) and {"safe_to_spend", "where_money_went", "spender_type"} & set(found)):
        # "Did I go over my budget?": what one did or may spend. "How much can I spend on restaurants?",
        # "my spending habits for groceries": these rules take no category, so it would be dropped.
        found.append("spending")
    return found


def _other_period(spending: dict | None) -> bool:
    """The question names a period other than this week ("what was my budget last month?")."""
    return spending is not None and (spending.get("period") or {}).get("preset") != "this_week"


def _beats(a: str, b: str, q: str, spending: dict | None) -> bool:
    category = bool(_filter_of(q))
    if (a, b) == ("safe_to_spend", "spending"):
        return not re.search(PAST, q) and not category and not _other_period(spending)
    if (a, b) == ("spender_type", "spending"):
        return not re.search(PAST, q) and not category
    if (a, b) == ("safe_to_spend", "recurring_bills"):
        return not re.search(template.BILL_WORDS, q)
    if (a, b) == ("where_money_went", "spending"):
        return not category and not re.search(COMPARE, q)   # the breakdown compares nothing
    if (a, b) == ("spending", "where_money_went"):
        return category and spending is not None and not re.search(COMPARE, q)   # "break down my restaurant spending"
    if (a, b) == ("what_if", "safe_to_spend"):
        return bool(re.search(PERCENT + "|" + HALF, q))   # "cut my restaurant budget by 20%"
    if (a, b) == ("what_if", "recurring_bills"):
        return bool(re.search(template.SAVE_MORE, q))
    if {a, b} == {"what_if", "spending"}:
        return (a == "what_if") == bool(re.search(PERCENT + "|" + HALF, q))
    if (a, b) == ("bonus", "recurring_bills"):
        return bool(re.search(BONUS, q))  # a bare "bonus" next to "earn" competes
    return (a, b) in PRECEDENCE


def _resolve(found: list[str], q: str, spending: dict | None) -> tuple[str | None, tuple[str, ...]]:
    """The rule that claims a clause, or None and the rules that compete for it."""
    winners = [a for a in found if all(a == b or _beats(a, b, q, spending) for b in found)]
    if len(winners) == 1:
        return winners[0], ()
    return None, tuple(a for a in found if not any(b != a and _beats(b, a, q, spending) for b in found))


def _claimed(rule: str, planned: list[tuple[str, dict]], tools: set[str], lang: str) -> Claim:
    calls = tuple(FunctionCall(name, args) for name, args in planned if name in tools)
    if not calls:  # the rule's tool is not registered
        return Claim(rule, tuple(RuleModel._clarify(NOT_YET, NOT_YET_OPTIONS, lang)), offer_contact=True)
    return Claim(rule, calls + (FunctionCall("finish"),))


def _plan_intent(intent: str, question: str, q: str, as_of: date, tools: set[str], lang: str,
                 spending: dict | None) -> Claim:
    if intent == "spending":
        return _claimed(intent, [("get_spending", spending)], tools, lang)
    if intent == "where_money_went":
        # A period the user named ("this month", "last month") is the breakdown's period (#281); else the
        # metric's window (metrics.md section 1): month averages of the last 6 complete months.
        period = (plan_spending(question, as_of) or {}).get("period") or {"preset": "last_6_months"}
        return _claimed(intent, [("get_basket_breakdown", {"period": period})], tools, lang)
    if intent == "safe_to_spend":
        return _claimed(intent, [("get_safe_to_spend", {})], tools, lang)
    if intent == "small_purchases":
        return _claimed(intent, [("get_small_purchases", {})], tools, lang)
    if intent == "spender_type":
        return _claimed(intent, [("get_spender_profile", {}), ("get_peer_benchmark", {"metric": "spend_total"})],
                        tools, lang)
    if intent == "recurring_bills":
        return _claimed(intent, [("get_recurring_bills", {})], tools, lang)
    if intent == "balance_forecast":
        return _claimed(intent, [("get_balance_forecast", {})], tools, lang)
    if intent == "bonus":
        share = plan_bonus(q)
        if share is None:
            return Claim(intent, tuple(RuleModel._clarify(BONUS_SHARE_ASK, ((), ()), lang)))
        return _claimed(intent, [("get_bonus_estimate", share)], tools, lang)
    if intent == "peers":
        return _claimed(intent, [("get_peer_benchmark", {"metric": "spend_total"})], tools, lang)
    kind, what_if = plan_what_if(q)
    if kind == "health":
        return Claim(intent, (FunctionCall("decline", {"kind": "out_of_scope"}),))
    if kind == "unmapped":
        return Claim(None, reason="what_if_which")
    if kind == "amount":
        return Claim(intent, tuple(RuleModel._clarify(WHAT_IF_AMOUNT, ((), ()), lang)))
    if kind == "save_more":
        return _claimed("save_more", SAVE_MORE_PLAN if "get_savings_plan" in tools else SAVE_MORE_CALLS, tools, lang)
    return _claimed(intent, [("run_what_if", what_if)], tools, lang)


LONG_MESSAGE_CHARS = 200   # a message longer than this is never claimed by the spending rule (#399)


def long_message(question: str) -> bool:
    """A message longer than LONG_MESSAGE_CHARS, or with several question marks (#399)."""
    return len(question) > LONG_MESSAGE_CHARS or question.count("?") > 1


def _claim_clause(question: str, as_of: date, tools: set[str], lang: str, peer_question: bool,
                  long: bool = False) -> Claim:
    q = fold(question)
    # The spending rule never claims a long message or one with several questions (#399): a sum of the
    # categories it happens to mention is not its answer. The other rules, or the model, take it.
    spending = plan_spending(question, as_of) if "get_spending" in tools and not long else None
    found = [f for f in _matched(q, peer_question, spending) if not (long and f == "spending")]
    if "small_purchases" in found and not small_purchases_whole(q):
        # more than the plain small-purchases question (an amount, a period, a filter): the next planner reads
        # it, never answered for the defaults (#142, #390)
        return Claim(None, reason="period")
    if "what_if" in found and plan_what_if(q)[0] == "health" and \
            not ("spending" in found and not re.search(PERCENT + "|" + HALF, q)):
        return Claim("what_if", (FunctionCall("decline", {"kind": "out_of_scope"}),))
    if not found:
        return Claim(None, reason="period" if re.search(MONEY_WORDS, q) or _filter_of(q) else "")
    winner, competing = _resolve(found, q, spending)
    if winner is None:
        return Claim(None, candidates=competing, reason="competing")
    return _plan_intent(winner, question, q, as_of, tools, lang, spending)


def _topics(part: str, peer_question: bool) -> frozenset[str]:
    """The rules a clause is about, to tell two questions from one question in two clauses."""
    q = fold(part)
    found = {intent for intent, rx in INTENTS if re.search(rx, q) and (intent != "peers" or peer_question)}
    if re.search(MONEY_WORDS, q) or _filter_of(q):
        found.add("spending")
    return frozenset(found)


def _complete(question: str, q: str, as_of: date) -> bool:
    """A message that stands on its own: the user's own subject and verb, another rule's question, or a
    category with a period ("Restaurants in August")."""
    if re.search(SELF_SPEND, q) or re.search(COMPLETE_WORDS, q) or any(re.search(rx, q) for _, rx in INTENTS):
        return True
    args = plan_spending(question, as_of)
    return bool(args and args.get("filter")) and not re.search(COMPARE, q)


def _prev_month(ym: tuple[int, int]) -> tuple[int, int]:
    return (ym[0], ym[1] - 1) if ym[1] > 1 else (ym[0] - 1, 12)


def _single_month(period, as_of: date) -> tuple[int, int] | None:
    """The calendar month a period is, or None (several months, a week, a malformed period)."""
    if not isinstance(period, dict):
        return None
    if period.get("preset") == "this_month":
        return as_of.year, as_of.month
    if period.get("preset") == "last_month":
        return _prev_month((as_of.year, as_of.month))
    if period.get("preset") == "custom":
        try:
            start, end = date.fromisoformat(str(period["start"])), date.fromisoformat(str(period["end"]))
        except (KeyError, ValueError):
            return None
        if start.day == 1 and (start.year, start.month) == (end.year, end.month) \
                and end.day == calendar.monthrange(end.year, end.month)[1]:
            return start.year, start.month
    return None


def _baseline(question: str, q: str, period, as_of: date) -> str | None:
    """The compare_to of "compared to August?" for the previous turn's period, or None when the tool cannot
    compare with that baseline (it knows the previous period, the same period last year and the typical)."""
    if re.search(BASELINE_TYPICAL, q):
        return "typical"
    if re.search(BASELINE_LAST_YEAR, q):
        return "same_period_last_year"
    target = _single_month(period, as_of)
    named = [m for m in _months_mentioned(question, as_of) if m != target]
    if not named and re.search(LAST_MONTH_WORDS, q):
        named = [_prev_month((as_of.year, as_of.month))]
    if not named:
        return "previous_period"   # "compared with before?", "vs the previous month?"
    if target is None:
        return None
    if named[-1] == _prev_month(target):
        return "previous_period"
    if named[-1] == (target[0] - 1, target[1]):
        return "same_period_last_year"
    return None


def _follow_up(request: PlanInput, q: str, as_of: date, tools: set[str]) -> Claim:
    """A message that is not complete on its own, in a running conversation (#300). It keeps the previous
    turn's tool, period and filter and changes what it names: a baseline ("compared to August?"), a period
    ("and last month?") or a category ("what about groceries?"). It answers the rules' period question
    ("Last month" after "How much did I spend on groceries?"). Anything else is not claimed."""
    question = request.question
    not_claimed = Claim(None, reason="follow_up")
    prev = request.history[-1] if isinstance(request.history[-1], dict) else {}
    calls = [c for c in prev.get("calls") or [] if isinstance(c, dict)]
    stated = plan_spending(question, as_of)
    flt = _filter_of(q)
    compare = bool(re.search(COMPARE, q))
    if not calls:
        before = prev.get("question")
        if compare or stated is None or not isinstance(before, str) or "get_spending" not in tools:
            return not_claimed
        asked = claim(PlanInput(question=before, language=request.language, as_of=request.as_of, tools=request.tools))
        args = plan_spending(before + ". " + question, as_of) if asked.reason == "period" else None
        if not args:
            return not_claimed
        return Claim("follow_up", (FunctionCall("get_spending", args), FunctionCall("finish")))
    if len(calls) != 1 or calls[0].get("name") not in FOLLOW_TOOLS or "get_spending" not in tools:
        return not_claimed
    tool, args = calls[0]["name"], dict(calls[0].get("args") or {}) if isinstance(calls[0].get("args"), dict) else {}
    new = dict(args) if tool == "get_spending" else {"period": args.get("period")}
    if flt:
        new["filter"] = flt
        new.pop("direction", None)
        if flt.get("categories") == ["Invest Deposit"]:
            new["direction"] = "out"
    if compare:
        compare_to = _baseline(question, q, args.get("period"), as_of)
        if compare_to is None or new.get("period") is None:
            return not_claimed
        new["compare_to"] = compare_to
        return Claim("follow_up", (FunctionCall("get_spending", new), FunctionCall("finish")))
    period = (stated or {}).get("period")
    if not flt and period is None:
        return not_claimed           # "why?", "tell me more": the planner, or the general question back
    if tool == "get_basket_breakdown" and not flt:
        return Claim("follow_up", (FunctionCall("get_basket_breakdown", {**args, "period": period}),
                                   FunctionCall("finish")))
    if period is not None:
        new["period"] = period
    if new.get("period") is None:
        return not_claimed
    return Claim("follow_up", (FunctionCall("get_spending", new), FunctionCall("finish")))


def _data_calls(found: Claim) -> list[FunctionCall]:
    return [c for c in found.calls if c.name not in ("finish", "decline", "ask_clarifying_question")]


def claim(request: PlanInput) -> Claim:
    """The one place that decides which rule claims a message, or that none does (see above)."""
    question = request.question
    q = fold(question)  # "kayttaa" and "käyttää" match the same rules
    tools = {t["name"] for t in request.tools}
    lang = request.language
    as_of = date.fromisoformat(request.as_of)
    # A comparison with people like me is the peer benchmark (aggregates), not another person's data;
    # a named or specific person still is (#216).
    peer_question = (bool(re.search(PEERS, q)) and bool(re.search(SELF, q))
                     and not re.search(SPECIFIC_PERSON, q, re.I) and not re.search(OTHERS_DATA, q))
    for kind, rx in DECLINE_RULES:
        if kind == "other_person_data" and peer_question:
            continue
        if re.search(rx, q, re.I):
            return Claim("decline", (FunctionCall("decline", {"kind": kind}),))
    if flags(question) or re.search(SET_ASIDE, q):
        return Claim(None, reason="flagged")
    if request.history and not _complete(question, q, as_of):
        return _follow_up(request, q, as_of, tools)
    bare = re.sub(r"^(the|and|or|enta|ja) ", "", " ".join(re.sub(r"[^\w\s]", " ", q).split()))
    if "get_spending" in tools and any(re.fullmatch(rx, bare) for rx, _ in PRESETS):
        args = plan_spending(question, as_of)
        if args:
            return Claim("spending", (FunctionCall("get_spending", args), FunctionCall("finish")))
    long = long_message(question)
    clauses = [(part, _topics(part, peer_question)) for part in re.split(CLAUSE_BREAK, q) if part.strip()]
    clauses = [(part, topics) for part, topics in clauses if topics]
    if len(clauses) > 1 and all(not (a & b) for i, (_, a) in enumerate(clauses) for _, b in clauses[i + 1:]):
        parts = [_claim_clause(part, as_of, tools, lang, peer_question, long) for part, _ in clauses]
        declined = next((part for part in parts if part.calls and part.calls[0].name == "decline"), None)
        if declined is not None:
            return declined          # a refusal of one part is the answer to the whole message
        unique = {(c.name, json.dumps(c.args, sort_keys=True)): c for part in parts for c in _data_calls(part)}
        calls = list(unique.values())
        if all(part.rule and _data_calls(part) and len(_data_calls(part)) == len(part.calls) - 1 for part in parts) \
                and len(calls) <= MAX_DATA_CALLS:
            rules = list(dict.fromkeys(part.rule for part in parts))
            return Claim(rules[0] if len(rules) == 1 else "+".join(rules), tuple(calls) + (FunctionCall("finish"),))
        competing = [r for part in parts for r in (part.candidates or ((part.rule,) if part.rule else ()))]
        return Claim(None, candidates=tuple(dict.fromkeys(competing)), reason="competing")
    return _claim_clause(question, as_of, tools, lang, peer_question, long)


class RuleModel:
    model_id = "rules@1"

    def plan(self, request: PlanInput) -> PlanResult:
        """Rules first: recognised=False means no rule matched, and the calls are a clarifying question
        (the default one, or the what-if one for a selection the rules do not map). A decline, a
        NOT_YET answer, a what-if amount question and every data call are recognised answers."""
        calls, recognised = self._calls(request)
        return PlanResult(calls=list(calls), recognised=recognised, offer_contact=isinstance(calls, OfferContact))

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
        found = claim(request)
        if found.rule is not None:
            return (OfferContact(found.calls) if found.offer_contact else list(found.calls)), True
        lang = request.language
        if found.reason == "what_if_which":
            return self._clarify(WHAT_IF_WHICH, WHAT_IF_WHICH_OPTIONS, lang), False
        options = [template.pick(CANDIDATE_QUESTIONS[c], lang) for c in found.candidates if c in CANDIDATE_QUESTIONS]
        if len(options) > 1:   # rules compete: their own questions as the options
            return self._clarify((CLARIFY_WHICH[0], CLARIFY_WHICH[1]), (tuple(options[:3]), tuple(options[:3])), lang), False
        if found.reason == "period":
            return self._default_clarify(lang), False      # a spending question without a period
        return self._clarify(template.CLARIFY_GENERAL["question"], template.CLARIFY_GENERAL["options"], lang), False

    def compose(self, request: ComposeInput) -> ComposeResult:
        return ComposeResult(text=json.dumps(
            template.template_draft(request.data, request.errors, request.language, None, request.question),
            ensure_ascii=False))
