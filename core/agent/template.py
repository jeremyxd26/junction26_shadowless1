"""Fixed texts and the deterministic template answer (agent-core.md sections 6.3, 7.4, 7.6 and 11).

- Refusal templates per kind, the no-data sentence, the default clarifying question, follow-up
  questions and the lesson catalogue, in English and Finnish. They are drafts for human review
  before the demo (agent-core.md section 7.7); none of them contains a digit.
- template_draft builds an AnswerDraft from the tools' model views only: it cites every number as a
  {{nK}} token and writes no digit itself, so it passes the validator. It is the composer of the
  rule model and the fallback after a failed composer (R12).
"""

from __future__ import annotations

import re
from typing import Any

from core import answer_text
from core.tools import config as tools_config
from core.agent import answer_sentences
from core.agent.guard import fold, fold_pattern

REFUSAL: dict[str, dict[str, Any]] = {
    "investment_advice": {
        "label": ("Investment advice is outside what I can help with", "Sijoitusneuvonta ei kuulu siihen, missä voin auttaa"),
        "text": ("I can't give investment advice, such as which shares or funds to buy. I can show how much you could "
                 "set aside each month, so you know what you have to work with. For investing, an S-Pankki adviser can help.",
                 "En voi antaa sijoitusneuvontaa, esimerkiksi siitä, mitä osakkeita tai rahastoja kannattaa ostaa. Voin "
                 "näyttää, paljonko voisit säästää kuukaudessa. Sijoittamisessa auttaa S-Pankin neuvoja."),
    },
    "credit_decision": {
        "label": ("Loan decisions are made by the bank's loan process", "Lainapäätökset tehdään pankin lainaprosessissa"),
        "text": ("I can't predict whether a loan or mortgage would be approved, and I don't rate creditworthiness. "
                 "The bank's loan process gives that answer. I can show what you could save each month.",
                 "En voi ennustaa, myönnetäänkö laina tai asuntolaina, enkä arvioi luottokelpoisuutta. Vastauksen antaa "
                 "pankin lainaprosessi. Voin näyttää, paljonko voisit säästää kuukaudessa."),
    },
    "other_person_data": {
        "label": ("I can only look at your own money", "Voin katsoa vain omia raha-asioitasi"),
        "text": ("I can only look at your own transactions, never anyone else's. Ask me about your own spending instead.",
                 "Voin katsoa vain omia tapahtumiasi, en koskaan muiden. Kysy minulta omasta kulutuksestasi."),
    },
    "out_of_scope": {
        "label": ("This is outside what I can help with", "Tämä ei kuulu siihen, missä voin auttaa"),
        # The warmer generic decline (#287, the product owner's text); the four brief questions follow as chips.
        "text": ("That's outside my lane — I'm your money coach. I can help with things like:",
                 "Tämä menee ohi osaamiseni — olen rahavalmentajasi. Voin auttaa esimerkiksi näissä:"),
    },
    "unsafe": {
        "label": ("I can't help with that request", "En voi auttaa tässä pyynnössä"),
        "text": ("I can't help with that. I only read and explain your own spending, and I never move money or show raw records.",
                 "En voi auttaa siinä. Luen ja selitän vain omaa kulutustasi, enkä koskaan siirrä rahaa tai näytä raakatietoja."),
    },
}

BRIEF_QUESTIONS = (
    ("Where did my money go?", "Mihin rahani menivät?"),
    ("What kind of spender am I?", "Millainen kuluttaja olen?"),
    ("What can I safely spend this week?", "Paljonko minulla on turvallisesti käytettävissä tällä viikolla?"),
    ("How could I save more?", "Miten voisin säästää enemmän?"),
)

MONTHLY_AVERAGE = ("monthly average", "kuukausikeskiarvo")
# "How could I save more?" without a category or a cut: the answer shows the basket shares and the bills
# due, and ends by offering a what-if on the largest everyday category. The offer names no amount: the
# coach never suggests a cut (issue #142, R1); the user says by how much.
SAVE_MORE = (r"save more(?! time)|saving more(?! time)|help me save|help me to save|säästää enemmän|"
             r"säästäisin enemmän|säästämään enemmän|säästöä enemmän|säästän enemmän|"
             # the everyday ways of asking it (#340); the rules read the same words (rules.plan_what_if)
             r"\bhow (can|could|do|should|would) i save\b(?! time)|\bsave money\b|"
             r"\b(help me|tips to|ways to|how (can|could|do) i) (spend less|cut back)\b|"
             r"\bways to save\b|\bsaving tips\b|\btips to save\b|\bwhere (can|could|should) i (save|cut)\b|"
             r"\b(how much|amount) (could|can|would) i save\b|\bput (more |some )?(money )?aside\b|"
             r"\bmiten (voisin|voin|saisin) säästä\w*|\bmissä (voisin|voin) säästä\w*|\bsäästöön\b")
# One sentence each, so the save-more answer stays within two sentences (#342, Renat's length rule).
WHAT_IF_OFFER = ("Tell me how much you would cut {category} by, and I'll show what you'd save.",
                 "Kerro, kuinka paljon vähentäisit luokassa {category}, niin näytän säästön.")
WHAT_IF_OFFER_ANY = ("Name a category and how much you would cut it by, and I'll show what you'd save.",
                     "Kerro luokka ja kuinka paljon vähentäisit, niin näytän säästön.")
# The peer benchmark's reasons for showing nothing (#216): the reason only, never a number.
PEER_REASON = {
    "group_too_small": ("There are too few people like you in the data to compare with.",
                        "Aineistossa on liian vähän kaltaisiasi vertailuun."),
    "not_comparable": ("Your spending cannot be compared with people like you for this period.",
                       "Kulutustasi ei voi verrata kaltaisiisi tällä jaksolla."),
}
NO_DATA = ("There are no transactions for that period in your data.",
           "Tältä jaksolta ei ole tapahtumia aineistossasi.")
TOOL_FAILED = ("Some of the data could not be computed right now.",
               "Osaa tiedoista ei voitu laskea juuri nyt.")
NOTHING = ("I could not find data for that question.", "En löytänyt tietoja tähän kysymykseen.")
CLARIFY_GENERAL = {
    "question": ("What would you like to know about your money?", "Mitä haluaisit tietää raha-asioistasi?"),
    "options": (("Where did my money go?", "What can I safely spend this week?", "How could I save more?"),
                ("Mihin rahani menivät?", "Paljonko minulla on turvallisesti käytettävissä tällä viikolla?",
                 "Miten voisin säästää enemmän?")),
}
CLARIFY = {
    "question": ("Which period do you mean?", "Mitä ajanjaksoa tarkoitat?"),
    "options": (("This month", "Last month", "The last three months"),
                ("Tämä kuukausi", "Viime kuukausi", "Viimeiset kolme kuukautta")),
}
STATUS_UNDERSTANDING = ("Reading your question", "Luen kysymystäsi")
STATUS_WRITING = ("Writing the answer", "Kirjoitan vastausta")

# Lessons: short, reviewed texts the composer may pick by key; the model never writes them.
LESSONS: dict[str, dict[str, tuple[str, str]]] = {
    "one_off_vs_habit": {"title": ("One-offs and habits", "Kertaostokset ja tavat"),
                         "text": ("A one-off cost shows up once. A habit repeats every month, so a small change there adds up over a year.",
                                  "Kertaostos näkyy kerran. Tapa toistuu joka kuukausi, joten pieni muutos siinä kertyy vuodessa.")},
    "fixed_vs_flexible": {"title": ("Fixed and flexible costs", "Kiinteät ja joustavat menot"),
                          "text": ("Fixed costs like rent change slowly. Flexible costs like eating out are where quick changes are possible.",
                                   "Kiinteät menot, kuten vuokra, muuttuvat hitaasti. Joustavissa menoissa, kuten ulkona syömisessä, muutos on nopeampi.")},
    "safety_buffer": {"title": ("A safety buffer", "Puskuri"),
                      "text": ("Keeping a small amount untouched on the account protects you from surprises before payday.",
                               "Pieni koskematon summa tilillä suojaa yllätyksiltä ennen palkkapäivää.")},
    "small_amounts_add_up": {"title": ("Small amounts add up", "Pienet summat kertyvät"),
                             "text": ("Small, frequent purchases are easy to miss, but together they can be a large part of a month.",
                                      "Pienet, toistuvat ostokset jäävät helposti huomaamatta, mutta yhdessä ne voivat olla iso osa kuukautta.")},
    "price_level": {"title": ("Price levels", "Hintataso"),
                    "text": ("The same basket can cost a different amount in different stores.",
                             "Sama ostoskori voi maksaa eri kaupoissa eri verran.")},
    "estimate_not_promise": {"title": ("An estimate, not a promise", "Arvio, ei lupaus"),
                             "text": ("This is based on your past months; the coming months can differ.",
                                      "Tämä perustuu menneisiin kuukausiisi; tulevat kuukaudet voivat poiketa."),},
    "peer_context": {"title": ("Compared with others", "Vertailu muihin"),
                     "text": ("A comparison with people like you is context, not a target.",
                              "Vertailu kaltaisiisi ihmisiin on taustatietoa, ei tavoite.")},
}

MAX_TEMPLATE_NUMBERS = 8


def pick(pair: tuple[str, str], language: str) -> str:
    return pair[1] if language == "fi" else pair[0]


def refusal(kind: str, language: str) -> tuple[str, dict[str, str]]:
    entry = REFUSAL[kind]
    return pick(entry["text"], language), {"kind": kind, "label": pick(entry["label"], language)}


# Sentti introduces itself (#287): greeting, identity, capabilities and help get the introduction, thanks
# gets one short sentence; both are followed by the four brief questions as chips (done.follow_ups).
# The product owner's texts, word for word; no digits and no number words.
INTRO = ("Hi, I'm Sentti — an AI money coach inside S-mobiili. I look at your own transactions and explain where "
         "your money goes, what's safe to spend this week and how you could save more. Every number comes from your "
         "transactions — tap it to see them. Sometimes I'll ask you a question too.",
         "Hei, olen Sentti — tekoälyvalmentaja S-mobiilissa. Katson omia tilitapahtumiasi ja kerron, mihin rahasi "
         "menevät, paljonko voit turvallisesti käyttää tällä viikolla ja miten voisit säästää enemmän. Jokainen luku "
         "tulee tilitapahtumistasi — napauta sitä, niin näet ne. Kysyn myös joskus sinulta jotain.")
THANKS = ("You're welcome — ask me anything about your money.", "Ole hyvä — kysy minulta mitä tahansa raha-asioistasi.")


def meta_text(intent: str, language: str) -> str:
    return pick(THANKS if intent == "thanks" else INTRO, language)


def brief_questions(language: str) -> list[str]:
    """All four brief questions, the chips of an introduction and of the generic decline (#287)."""
    return [pick(q, language) for q in BRIEF_QUESTIONS]


def follow_ups(question: str, language: str, refused: bool = False) -> list[str]:
    """The partner's four questions minus the one just asked (agent-core.md section 7.6)."""
    asked = question.strip().lower()
    out = [pick(q, language) for q in BRIEF_QUESTIONS if pick(q, language).lower() != asked]
    return out[:2] if refused else out[:3]


def lesson(key: str | None, language: str) -> dict[str, str] | None:
    if key is None or key not in LESSONS:
        return None
    entry = LESSONS[key]
    return {"key": key, "title": pick(entry["title"], language), "text": pick(entry["text"], language)}


def _numbers_in(view: Any, label: str = "") -> list[tuple[str, str]]:
    """(label, id) of every number in a model view, the shallow ones first (a total and each group's
    amount before nested details such as a basket's categories), in view order within a depth.
    Groups use the group's label."""
    found: list[tuple[int, int, str, str]] = []

    def walk(node: Any, depth: int, current: str) -> None:
        if isinstance(node, dict):
            if {"id", "value", "unit"} <= node.keys() and isinstance(node.get("id"), str):
                found.append((depth, len(found), node.get("label") or current, node["id"]))
                return
            group_label = node.get("label") if isinstance(node.get("label"), str) else current
            for key, value in node.items():
                if key not in ("notes", "period", "tool"):
                    walk(value, depth + 1, group_label)
        elif isinstance(node, list):
            for item in node:
                walk(item, depth + 1, current)

    walk(view, 0, label)
    return [(lab, number_id) for _, _, lab, number_id in sorted(found)]


TAKEAWAY_SIZE = 4  # the main number and at most three supporting ones (issue #112); the rest stay in the cards
NEXT_PAYDAY = ("Next payday", "Seuraava palkkapäivä")
BILL_TYPICAL = r"regular|monthly|usual|every month|säännölli|kuukausi|tavallis"
# A bills question is a bills question even when it names payday ("Which bills are due before payday?",
# "Mitä laskuja on tulossa ennen palkkapäivää?"); only a question without bills is about income.
BILL_WORDS = r"\bbills?\b|lasku\w*"   # also inside a compound: "kuukausilaskuni"
# Income and payday words: the rule that sends the question to the bills tool (rules.py) and the
# takeaway below read them from here, so a question routed for its income gets the income (#216).
INCOME_WORDS = (r"\b(pay ?day|salary|income|take-? ?home pay|net pay|earn(s|ed|ings)?|palkka\w*|tulo|tulot|tuloni|"
                r"tuloja|tienaa?\w*|ansaitse\w*)\b")

# Matched against the folded question (no diacritics), so folded here too.
SAVE_MORE, BILL_TYPICAL, BILL_WORDS, INCOME_WORDS = (fold_pattern(rx) for rx in (SAVE_MORE, BILL_TYPICAL, BILL_WORDS, INCOME_WORDS))


def asks_income(q: str) -> bool:
    """A folded question about income or payday and not about the bills ("Which bills are due before
    payday?" is a bills question)."""
    return bool(re.search(INCOME_WORDS, q)) and not re.search(BILL_WORDS, q)


def _num(node: Any, label: str | None = None) -> tuple[str, str] | None:
    if isinstance(node, dict) and {"id", "value", "unit"} <= node.keys() and isinstance(node.get("id"), str):
        return (label or node.get("label") or "", node["id"])
    return None


def takeaway(view: dict[str, Any], question: str = "", language: str = "en") -> tuple[list[tuple[str, str]], list[str]]:
    """The numbers one tool's answer cites, main number first, at most TAKEAWAY_SIZE, in the order of
    agent-core.md section 6.2; and extra sentences without numbers (a date). A tool not listed here
    gets its shallowest numbers."""
    tool = view.get("tool")
    q = fold(question)
    picks: list[tuple[str, str] | None] = []
    extra: list[str] = []
    if tool == "get_spending":
        comparison = view.get("comparison") or {}
        picks.append(_num(view.get("total")))
        if comparison:
            picks += [_num(comparison.get("baseline")), _num(comparison.get("change")), _num(comparison.get("change_pct"))]
        else:
            picks.append(_num(view.get("tx_count")))
            picks += [_num(g.get("amount"), g.get("label")) for g in view.get("groups") or []]
    elif tool == "get_basket_breakdown":
        if not re.search(SAVE_MORE, q):  # "save more": the three shares, the rest stays in the card
            picks.append(_num(view.get("total")))
        picks += [_num(b.get("share"), b.get("label")) for b in view.get("baskets") or []]
    elif tool == "get_safe_to_save":
        # The monthly figure is the main number (#216); "save more" cites it alone next to the basket
        # shares. When it is 0, the tool's reason says why (a text without digits), never a negative.
        picks.append(_num(view.get("monthly")))
        if not re.search(SAVE_MORE, q):
            picks.append(_num(view.get("stock")))
        reason = view.get("reason") or {}
        if (view.get("monthly") or {}).get("value") == 0 and isinstance(reason.get("text"), str):
            extra.append(reason["text"])
    elif tool == "get_bonus_estimate":
        # The estimate and its assumptions sentence; the user's share stays out of the text (#216).
        if view.get("status") == "not_offered":
            if isinstance(view.get("reason"), str):
                extra.append(view["reason"])
        else:
            # The share is cited too: the user's own number when they gave one ("Share at S-Group
            # stores"), else the assumed default ("Assumed share ..."), so a "half" answer never reads
            # like one for all groceries (review of #246).
            picks += [_num(view.get(k)) for k in ("total_month", "share", "total_year", "grocery_month")]
            assumptions = [a for a in view.get("assumptions") or [] if isinstance(a, str)]
            if assumptions:
                extra.append(assumptions[-1])  # "...a what-if, not a fact about where you shop."
    elif tool == "get_peer_benchmark":
        # The position, the difference from the median with the tool's own display (it carries its
        # direction word), the median and the group size; nothing but the reason when not shown (#216).
        if view.get("shown") is False:
            if view.get("reason") in PEER_REASON:
                extra.append(pick(PEER_REASON[view["reason"]], language))
        else:
            picks += [_num(view.get("percentile")), _num(view.get("vs_median")), _num(view.get("peer_median")),
                      _num((view.get("peer_group") or {}).get("size"))]
    elif tool == "get_safe_to_spend":
        picks += [_num(view.get(k)) for k in ("safe_to_spend", "balance_limit", "budget_limit")]
    elif tool == "run_what_if":
        # The cut is the user's own number and stays out of the text.
        picks += [_num(view.get(k)) for k in ("saving_per_month", "baseline_per_month", "saving_per_year")]
    elif tool == "get_recurring_bills":
        if re.search(SAVE_MORE, q):  # "save more": the bills due before payday, one number
            picks.append(_num(view.get("upcoming_total")))
        elif asks_income(q):
            picks += [_num(i.get("typical_month"), i.get("label")) for i in view.get("income") or []]
            if isinstance(view.get("next_payday"), str):
                extra.append(f"{pick(NEXT_PAYDAY, language)}: {_date(view['next_payday'], language)}.")
        elif re.search(BILL_TYPICAL, q):
            picks += [_num(b.get("typical_month"), b.get("label")) for b in view.get("bills") or []]
        else:
            picks.append(_num(view.get("upcoming_total")))
            picks += [_num(b.get("due_until_payday"), b.get("label")) for b in view.get("bills") or []]
    else:
        picks = list(_numbers_in(view))
    out = [p for p in picks if p is not None][:TAKEAWAY_SIZE]
    return out, extra


# Safe to spend as one takeaway sentence with its reason (coordinator, after #246): the amount, and which
# limit binds. The three numbers are the ones the takeaway always cited.
SAFE_SENTENCE = {
    "budget": ("Safe to spend in the coming week: {safe}, because your monthly budget is the limit ({budget}); "
               "your balance would allow more ({balance}).",
               "Turvallisesti käytettävissä tulevalla viikolla: {safe}, koska kuukausibudjettisi on raja ({budget}); "
               "saldosi sallisi enemmän ({balance})."),
    "balance": ("Safe to spend in the coming week: {safe}, because your balance is the limit ({balance}); "
                "your monthly budget would allow more ({budget}).",
                "Turvallisesti käytettävissä tulevalla viikolla: {safe}, koska saldosi on raja ({balance}); "
                "kuukausibudjettisi sallisi enemmän ({budget})."),
    "equal": ("Safe to spend in the coming week: {safe}; your balance and your monthly budget set the same limit "
              "({balance}).",
              "Turvallisesti käytettävissä tulevalla viikolla: {safe}; saldosi ja kuukausibudjettisi asettavat saman "
              "rajan ({balance})."),
}


def safe_to_spend_sentence(view: dict[str, Any], language: str) -> tuple[str, list[str]] | None:
    """The safe-to-spend takeaway as one sentence, and the ids it cites; None when a number is missing."""
    if view.get("tool") != "get_safe_to_spend":
        return None
    nums = {k: view.get(k) for k in ("safe_to_spend", "balance_limit", "budget_limit")}
    if not all(isinstance(n, dict) and isinstance(n.get("id"), str) for n in nums.values()):
        return None
    if nums["balance_limit"].get("value") == nums["budget_limit"].get("value"):
        kind, ids = "equal", [nums["safe_to_spend"]["id"], nums["balance_limit"]["id"]]
    else:
        kind = "balance" if view.get("binding_limit") == "balance" else "budget"
        ids = [nums[k]["id"] for k in ("safe_to_spend", "balance_limit", "budget_limit")]
    tokens = {k.split("_")[0] if k != "safe_to_spend" else "safe": f"{{{{{n['id']}}}}}" for k, n in nums.items()}
    return pick(SAFE_SENTENCE[kind], language).format(**tokens), ids


def lead_sentences(view: dict[str, Any], language: str) -> list[str]:
    """Text that comes before a tool's numbers. None today: the spender profile names its type in its own
    sentence (answer_sentences.profile, #342), so the answer stays within two sentences."""
    return []


def save_more_plan(views: list[dict[str, Any]], question: str) -> bool:
    """The save-more plan ran: the baskets answered "How could I save more?", and no what-if did."""
    tools = {v.get("tool") for v in views}
    return bool(re.search(SAVE_MORE, fold(question))) and "get_basket_breakdown" in tools and "run_what_if" not in tools


def what_if_offer(views: list[dict[str, Any]], language: str) -> str:
    """The offered next question: a cut of the largest everyday category, with no amount (R1)."""
    largest = None
    for view in views:
        for basket in view.get("baskets") or [] if view.get("tool") == "get_basket_breakdown" else []:
            if basket.get("key") != "everyday_spending":
                continue
            for c in basket.get("categories") or []:
                if c.get("key") not in tools_config.WHAT_IF_CATEGORIES:  # only a cut the rules can plan
                    continue
                amount = (c.get("amount") or {}).get("value")
                if isinstance(amount, (int, float)) and c.get("label") and (largest is None or amount > largest[0]):
                    largest = (amount, c["label"])
    if largest is None or re.search(r"\d", largest[1]):
        return pick(WHAT_IF_OFFER_ANY, language)
    category = largest[1].lower() if language == "en" else largest[1]
    return pick(WHAT_IF_OFFER, language).format(category=category)


def _date(iso: str, language: str) -> str:
    y, m, d = iso.split("-")
    return iso if language == "en" else f"{int(d)}.{int(m)}.{y}"


def template_draft(views: list[dict[str, Any]], errors: list[dict[str, Any]], language: str,
                   allowed: Any | None, question: str = "") -> dict[str, Any]:
    """An AnswerDraft built only from model views: '<period>. <label>: {{nK}}.' sentences.

    With `allowed` (validator.Allowed: the orchestrator knows the numbers' periods), any label or note
    whose digits are not returned dates is left out. Without it (a model sees only model views), the
    tools' period and number labels are kept and notes with digits are left out; the validator checks
    the result."""
    def ok(text: str, is_note: bool = False) -> bool:
        if allowed is None:
            # Without the answer's dates: a note with digits is left out; a label is kept only if all its
            # digits are inside date expressions ("August 2026" yes, "Next 7 days" no). The validator
            # then checks that those dates were returned.
            if is_note:
                return not re.search(r"\d", text)
            return not re.search(r"\d", answer_text.find_dates(text, blank_all=True)[1])
        return not answer_text.leftover_digits(text, dates=allowed.dates, periods=allowed.periods)

    sentences: list[str] = []
    cited: list[str] = []
    q = fold(question)
    # #342: human sentences for the tools answer_sentences writes; the others (profile, peer, S-Bonus,
    # safe to spend, an unknown tool) keep their own form below.
    owns = [answer_sentences.for_view(view, language, ok, save_more=bool(re.search(SAVE_MORE, q)),
                                      asks_income=asks_income(q), bill_typical=bool(re.search(BILL_TYPICAL, q)))
            for view in views]
    generic = views   # the views that get the sentence-per-tool form below
    if views and all(own is not None for own in owns):
        offer = what_if_offer(views, language) if save_more_plan(views, question) else None
        sentences, generic = own_answer([own[0] for own in owns], bool(errors), offer), []
    for view, own in zip(generic, owns):
        # One sentence per tool: "<period>: <label>: {{n1}}; <label>: {{n2}}." Items are joined with
        # semicolons, so a number is never followed by ". " and a label (a count then "10. heinäkuu 2026"
        # would read as a date). Signed values keep their sign in the token's display.
        items = []
        period = view.get("period")
        has_head = isinstance(period, str) and ok(period)
        chosen, extra = takeaway(view, question, language)
        sentences += [s for s in lead_sentences(view, language) if ok(s, is_note=True)]
        custom = safe_to_spend_sentence(view, language)
        if custom and not set(custom[1]) & set(cited) and len(cited) + len(custom[1]) <= MAX_TEMPLATE_NUMBERS:
            sentences.append(custom[0])
            cited += custom[1]
            chosen = []  # the sentence above cites them
        if own and not set(own[1]) & set(cited) and len(cited) + len(own[1]) <= MAX_TEMPLATE_NUMBERS:
            sentences += own[0]   # the tool's notes stay on its card (Renat's length rule)
            cited += own[1]
            continue
        for label, number_id in chosen:
            if number_id in cited or len(cited) >= MAX_TEMPLATE_NUMBERS:
                continue
            safe_label = label if label and ok(label) else ""
            if not safe_label and (items or not has_head):
                continue  # a bare token after another token would read as one number with it
            items.append(f"{safe_label}: {{{{{number_id}}}}}" if safe_label else f"{{{{{number_id}}}}}")
            cited.append(number_id)
        head = f"{period}: " if has_head and items else ""
        if head and view.get("monthly_average"):  # say that the amounts are averages, not one month
            head = f"{period}, {pick(MONTHLY_AVERAGE, language)}: "
        if items:
            # Each sentence starts with a capital: "…: 10. syyskuu 2026: …" would read as a date in the
            # rendered text, "…: 10. Syyskuu 2026: …" does not (a day takes a lower-case month).
            sentence = head + "; ".join(items) + "."
            sentences.append(sentence[:1].upper() + sentence[1:])
        sentences += extra  # built from the view's own ISO dates (next payday): returned dates
        for note in view.get("notes") or []:
            if isinstance(note, str) and ok(note, is_note=True):
                sentences.append(note)
    if generic and sentences and save_more_plan(views, question):
        sentences.append(what_if_offer(views, language))
    if errors:
        if not views and all(e.get("error") == "period_out_of_range" for e in errors):
            sentences.append(pick(NO_DATA, language))
        else:
            sentences.append(pick(TOOL_FAILED, language))
    if not sentences:
        sentences.append(pick(NOTHING, language))
    text = " ".join(sentences)
    if not generic:   # own_answer may leave a view out: cite exactly the tokens the text says, in order
        cited = list(dict.fromkeys(TOKEN.findall(text)))
    return {"language": language, "text": text, "cited": cited, "lesson_key": None}


TOKEN = re.compile(r"\{\{(n\d+)\}\}")
ANSWER_SENTENCES = 2   # Renat's length rule on #342: the whole answer
ANSWER_NUMBERS = 3


def own_answer(views: list[list[str]], errors: bool, offer: str | None) -> list[str]:
    """The answer when answer_sentences writes every view (#342, review of #365): the first view that says
    something is the takeaway and is always said whole; a later view is said only while the answer stays
    within two sentences and three numbers, otherwise it is left out whole and its card shows it. The
    save-more offer and the error sentence count as sentences."""
    room = ANSWER_SENTENCES - (1 if errors else 0)
    sentences: list[str] = []
    tokens: set[str] = set()
    for texts in views:
        more = tokens | set(TOKEN.findall(" ".join(texts)))
        if not sentences or (len(sentences) + len(texts) <= room and len(more) <= ANSWER_NUMBERS):
            sentences += texts
            tokens = more
    if offer and sentences and len(sentences) < room:
        sentences.append(offer)
    return sentences
