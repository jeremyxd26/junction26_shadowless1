"""Other people's money in a question (#350, #405; the principle decided in the review of #458).

A data rule claims only a confident match on the USER'S OWN money:

1. First person wins. A question whose subject or payer is the user ("did I", "cost me", "pay me",
   "from me", "our spending", Finnish "käytin", "minulle") is the user's own, whatever relative, shop or
   month it mentions as an object. It is declined only when it asks for another person's own money:
   a question clause with a person as the subject ("how much did she spend alone?") or a person who owns
   the money ("my husband's account").
2. A spending, income or what-if question with a third-person subject or owner is never claimed by a data
   rule. A clear person (a relation or role word in any case form, a personal pronoun, a title, a
   capitalised or non-Latin name) is declined as other-person data. A crowd ("everyone", "the average
   person", "muut", "kaikki") is left to the peer rule when it compares with the user, else unclaimed. When
   it cannot tell (a lower-case unknown word that spends or earns: "what did jane spend"), the message is
   unclaimed: the model planner or the clarifying question, never the user's own numbers.
3. Known non-persons: months, weekdays, holidays, the category and basket labels, the payee aliases and a
   curated list of shops, banks, utilities and services. Context beats the list: the owner of a bill, an
   invoice, a payment, a fee, a price or a subscription (Finnish lasku, maksu, hinta) is a company.

`classify(question, peer_question)` returns DECLINE, UNCLAIMED or None (no other person: the rules go on).
"""

from __future__ import annotations

import re
import unicodedata

from core.agent.guard import fold
from core.tools import config

DECLINE, UNCLAIMED = "decline", "unclaimed"


def _plain(text: str) -> str:
    """Accents off, case kept ("Äiti" -> "Aiti"), so a name keeps its capital."""
    return "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch))


# ---- the words ------------------------------------------------------------------------------------------
PERSON_EN = {
    "wife", "wives", "husband", "husbands", "spouse", "spouses", "partner", "partners", "girlfriend", "girlfriends",
    "boyfriend", "boyfriends", "fiance", "fiancee", "friend", "friends", "colleague", "colleagues", "coworker",
    "coworkers", "co-worker", "boss", "manager", "ex", "landlord", "landlady", "tenant", "roommate", "flatmate",
    "classmate", "teacher", "doctor", "dentist", "lawyer", "neighbour", "neighbours", "neighbor", "neighbors",
    "sister", "sisters", "brother", "brothers", "sibling", "siblings", "mother", "mom", "mum", "father", "dad",
    "parent", "parents", "son", "sons", "daughter", "daughters", "kid", "kids", "child", "children", "baby",
    "grandma", "grandpa", "grandmother", "grandfather", "grandparents", "aunt", "uncle", "cousin", "cousins",
    "niece", "nephew", "stepdad", "stepmom", "stepfather", "stepmother", "stepson", "stepdaughter", "family",
    "sister-in-law", "brother-in-law", "mother-in-law", "father-in-law",
}
# Finnish relation and role words in the forms that name the spender or the owner: nominative, "my X" (px),
# genitive, plural; folded (no accents). The allative "vaimolleni" (for my wife) and "X kanssa" are not here.
PERSON_FI = {
    "vaimo", "vaimoni", "vaimon", "vaimot", "vaimollani", "puoliso", "puolisoni", "puolison", "kumppani",
    "kumppanini", "kumppanin", "tyttoystava", "tyttoystavani", "tyttoystavan", "poikaystava", "poikaystavani",
    "poikaystavan", "ystava", "ystavani", "ystavan", "ystavat", "kaveri", "kaverini", "kaverin", "kaverit",
    "tyokaveri", "tyokaverini", "tyokaverin", "kollega", "kollegani", "kollegan", "pomo", "pomoni", "pomon",
    "esimies", "esimieheni", "esimiehen", "vuokranantaja", "vuokranantajani", "vuokranantajan", "exa", "exani",
    "exan", "sisko", "siskoni", "siskon", "sisar", "sisareni", "sisaren", "veli", "veljeni", "veljen", "aiti",
    "aitini", "aidin", "isa", "isani", "isan", "poika", "poikani", "pojan", "tytar", "tyttareni", "tyttaren",
    "lapsi", "lapseni", "lapsen", "lapset", "lasteni", "lasten", "naapuri", "naapurini", "naapurin", "mies",
    "mieheni", "miehen", "miehet", "vanhemmat", "vanhempani", "vanhempien", "mummo", "mummoni", "ukki", "ukkini",
    "isoaiti", "isoisa", "tati", "seta", "eno", "serkku", "serkkuni", "perhe", "perheeni",
}
PRONOUN = {"she", "he", "they", "her", "his", "their", "him", "them", "han", "hanen", "heidan"}
TITLE = {"mr", "mrs", "ms", "miss", "dr", "rouva", "herra", "neiti", "tohtori"}
CROWD = {"everyone", "everybody", "others", "people", "person", "average", "most", "muut", "muiden", "kaikki",
         "ihmiset", "keskiverto", "suomalaiset"}
FIRST = {"i", "me", "we", "us", "myself", "ourselves", "mina", "minun", "minulle", "minulta", "minua", "minulla",
         "meidan", "meille", "meilta", "meita", "meilla", "voin", "voinko", "voisin", "voisinko", "haluan",
         "haluaisin", "saanko", "olen", "olenko", "olisin", "tarvitsen", "tarvitsisin", "pystyn", "pystyisin"}
DETERMINER = {"my", "our", "the", "his", "her", "their", "your", "a", "an", "minun", "meidan", "and", "or", "ja",
              "tai"}
# Known non-persons. English words match exactly (with "'s"); shop, bank and Finnish stems also take a
# Finnish case ending ("Prisman", "Nordean", "Lidlin", "Kesäkuun"), so "Augustin" is no "August".
CALENDAR_EN = {"january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
               "november", "december", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
               "christmas", "easter", "midsummer", "weekend"}
CALENDAR_FI = ("tammikuu", "helmikuu", "maaliskuu", "huhtikuu", "toukokuu", "kesakuu", "heinakuu", "elokuu",
               "syyskuu", "lokakuu", "marraskuu", "joulukuu", "maanantai", "tiistai", "keskiviikko", "torstai",
               "perjantai", "lauantai", "sunnuntai", "viikonlopu", "joulu", "paasiai", "juhannu", "vappu", "uusivuo")
THINGS_EN = {"today", "yesterday", "month", "week", "year", "day", "last", "this", "next", "rent", "food", "travel",
             "groceries", "bills", "salary", "income", "spending", "shopping", "restaurants", "fuel", "taxi",
             "transport", "insurance", "electricity", "water", "phone", "internet", "gym", "pharmacy", "total",
             "budget", "sentti", "finland", "money", "usual", "average", "normal", "typical"}
STEMS = ("s-market", "s-mark", "prisma", "alepa", "sale", "lidl", "k-market", "k-citymarket", "k-supermarket",
         "k-ruoka", "kesko", "tokmanni", "verkkokauppa", "gigantti", "power", "ikea", "clas", "stockmann", "sokos",
         "hesburger", "mcdonald's", "wolt", "foodora", "uber", "bolt", "vr", "hsl", "finnair", "posti", "s-pank",
         "s-ryhm", "s-group", "s-bonus", "nordea", "osuuspank", "op", "danske", "aktia", "handelsbank", "revolut",
         "klarna", "paypal", "mobilepay", "kela", "verottaja", "vero", "fortum", "helen", "vattenfall", "elisa",
         "telia", "dna", "netflix", "spotify", "hbo", "disney", "apple", "google", "amazon", "steam", "youtube",
         "suomi", "suome", "kuukau", "kuu", "viiko", "vuode", "vuosi", "paiva", "tama", "viime", "edellis")
_ENDING = r"(?:n|in|an|en|un|yn|on|ssa|sta|lla|lta|lle|ksi|a|ta|na|t|ja|ihin|iin|seen|lle|kin)?"
_LABELS = {fold(lab) for table in (config.CATEGORY_LABELS, config.BASKET_LABELS, config.MCC_GROUP_LABELS)
           for pair in table.values() for lab in pair}
_PAYEES = {fold(p) for names in config.PAYEE_ALIASES.values() for name in names for p in name.split()}

MONEY_EN_STRONG = (r"spending|spend|purchases?|transactions?|money|salary|salaries|income|budget|accounts?|balance|"
                   r"expenses?|savings|earnings|wages?|pension|debts?|loans?|net worth|finances")
MONEY_EN_WEAK = r"groceries|food|shopping|clothes|rent|card"
COMPANY_CONTEXT = r"bills?|invoices?|payments?|fees?|prices?|subscriptions?|charges?|plan"
VERB_PERSON = r"spend|spent|spends|earn|earned|earns|save|saved|saves|buy|bought|buys|shop|shops|shopped"
VERB_ANY = (VERB_PERSON + r"|pay|paid|pays|make|made|makes|owe|owes|get|got|gets|cost|costs|cut|cuts|have|has|"
            r"own|owns|compare|compares")
VERB_PAST = r"spent|spends|earned|earns|paid|pays|bought|buys|saved|saves|owes|makes|made|cut|cuts"
FI_VERB = (r"kaytti|kayttaa|kayttavat|kayttivat|kulutti|kuluttaa|kuluttavat|kuluttivat|maksoi|maksaa|maksavat|"
           r"osti|ostaa|ostavat|tienaa|tienasi|tienaavat|ansaitsi|ansaitsee|saasti|saastaa|"
           r"on (?:tienannut|kayttanyt|kuluttanut|maksanut|saastanyt|ostanut|ansainnut)")
FI_QUESTION_VERB = r"kuluttaako|kayttaako|maksaako|tienaako|ostaako|saastaako|ansaitseeko"
FI_WHAT_IF_VERB = r"vahentaisi|leikkaisi|kayttaisi|kuluttaisi|saastaisi"
FI_MONEY = r"kulutu\w*|palk(?!kapaiv)\w*|tulo\w*|tili\b|tilin\b|tilil\w*|saldo\w*|meno\w*|ostok\w*|tilitapahtum\w*|raho\w*"
FI_COMPANY = r"\w*(?:lasku|maksu|hinta|hinna)\w*"

FI_VERB_PERSON = re.compile(r"kaytti|kayttaa|kayttavat|kayttivat|kulutti|kuluttaa|kuluttavat|kuluttivat|osti|ostaa|"
                            r"ostavat|tienaa|tienasi|tienaavat|ansaitsi|ansaitsee|saasti|saastaa|"
                            r"on (?:tienannut|kayttanyt|kuluttanut|saastanyt|ostanut|ansainnut)", re.I)
_CALENDAR_RX = "|".join(sorted(CALENDAR_EN))
_TOKEN = r"(?:[^\W\d_]+(?:[-'’][^\W\d_]+)*\.?)"
_NP = rf"(?P<np>(?:{_TOKEN} ){{0,2}}{_TOKEN}(?: (?:and|or|ja|tai) (?:(?:my|her|his|their) )?{_TOKEN})?)"
_NP1 = rf"(?<![\w'’-])(?P<np>(?:(?:my|our|the|his|her|their) )?{_TOKEN}(?: {_TOKEN})?)"
_AUX = r"did|does|do|has|have|had|will|would|could|can|should|is|was"
_NP2 = (rf"(?<![\w'’-])(?P<np>(?:(?:my|our|the|his|her|their) )?{_TOKEN}(?: {_TOKEN})?"
        rf"(?: (?:and|or|ja|tai) (?:(?:my|her|his|their) )?{_TOKEN})?)")
_PREP = r"(?!(?:on|for|at|in|to|with|from|by|of)\b)"
_QUESTION = r"how much|how many|what|paljonko|kuinka paljon|mita|mihin"

PATTERNS = {
    # subject: "did Jane spend", "how much Jane spent", "what if Marja cut", "Paljonko Marja käytti"
    "aux_subject": re.compile(rf"\b(?:{_AUX}) {_NP2} (?P<verb>{VERB_ANY})\b", re.I),
    "subject": re.compile(rf"{_NP1} (?P<verb>{VERB_PAST})\b", re.I),
    "what_if": re.compile(rf"\bwhat if {_NP1} (?P<verb>{VERB_ANY}|reduced|reduces|stopped)\b", re.I),
    "is_spending": re.compile(rf"\b(?:is|are|was|were) {_NP1} (?P<verb>spending|earning|saving)\b", re.I),
    "fi_subject": re.compile(rf"(?<=\w )(?P<np>{_TOKEN}(?: (?:ja|tai) {_TOKEN})?) (?P<verb>{FI_VERB})\b", re.I),
    "fi_question": re.compile(rf"\b(?:{FI_QUESTION_VERB}) (?P<np>{_TOKEN})\b", re.I),
    "fi_onko": re.compile(rf"\bonko (?P<np>{_TOKEN}) (?P<verb>kuluttanut|kayttanyt|tienannut|saastanyt|ostanut|"
                          rf"ansainnut)\b", re.I),
    "fi_lead": re.compile(rf"^(?P<np>{_TOKEN}) (?P<verb>{FI_VERB_PERSON.pattern})\b"),
    "fi_what_if": re.compile(rf"\bmita jos (?P<np>{_TOKEN}) (?:{FI_WHAT_IF_VERB})\b", re.I),
    # owner: "Jane's June spending", "my husband's account", "spending of Jane", "Marjan kulutus"
    "owner": re.compile(rf"{_NP1}['’]s? (?:(?:{_TOKEN}) )?(?P<noun>{MONEY_EN_STRONG}|{MONEY_EN_WEAK}|{COMPANY_CONTEXT})\b",
                        re.I),
    "owner_direct": re.compile(rf"{_NP1}['’]s? (?P<noun>{MONEY_EN_STRONG}|{MONEY_EN_WEAK})\b", re.I),
    "owner_of": re.compile(rf"\b(?:{MONEY_EN_STRONG}) (?:of|from|by) {_NP1}", re.I),
    "owner_pronoun": re.compile(rf"\b(?P<np>his|her|their|hanen|heidan) (?P<noun>{MONEY_EN_STRONG}|{FI_MONEY})", re.I),
    "fi_owner": re.compile(rf"(?P<np>{_TOKEN}) (?P<noun>{FI_MONEY}|{FI_COMPANY})", re.I),
    # comparison with someone: "more than my wife", "kuin Marja"
    "compare": re.compile(rf"\b(?:than|compared (?:to|with)|versus|vs\.?|kuin|verrattuna) {_PREP}{_NP1}", re.I),
    "compare_to": re.compile(rf"\bcompare\b.* (?:to|with) {_PREP}{_NP1}", re.I),
    "me_or": re.compile(rf"\b(?:me|i) or {_NP1}", re.I),
    "or_me": re.compile(rf"{_NP1} or (?:me|i)\b", re.I),
    "about": re.compile(rf"^(?:and )?(?:what|how) about {_NP1}", re.I),
    "and_name": re.compile(rf"^and {_NP1}$", re.I),
    "fi_has": re.compile(rf"(?<=\w )(?P<np>{_TOKEN}(?:lla|llani)) on\b", re.I),
    "spender": re.compile(rf"\b(?:what (?:kind|type|sort) of (?:spender|saver|consumer) (?:is|was|are) {_NP1}|"
                          rf"is (?P<np3>{_TOKEN}) an? (?:big |small |good |bad )?(?:spender|saver)|"
                          rf"millainen (?:kuluttaja|saastaja) (?P<np2>{_TOKEN}) on\b)", re.I),
    # a lone name at the start with a time: "Jane in June, how much?"
    "lead_name": re.compile(rf"^(?P<np>{_TOKEN}) (?:in|during) (?:{_CALENDAR_RX})\b|"
                           rf"^(?P<np2>{_TOKEN}) (?:last|this) (?:week|month|year)\b", re.I),
}
STRONG_OWNER_NOUN = re.compile(rf"^(?:{MONEY_EN_STRONG}|{FI_MONEY})$", re.I)
COMPANY_NOUN = re.compile(rf"^(?:{COMPANY_CONTEXT}|{FI_COMPANY})$", re.I)
NOT_FIRST = re.compile(r"\b(show|tell|give|let|help|send) me\b|\bnayta minulle\b|\bkerro minulle\b|"
                       r"\b(than|kuin) (me|i|us|we|mina|me)\b|\blike (me|us)\b|\bkaltaisi\w*", re.I)
FIRST_MONEY = re.compile(rf"\b(?:my|our) (?:{MONEY_EN_STRONG}|{MONEY_EN_WEAK}|{COMPANY_CONTEXT}|bonus|bonuses)\b|"
                         r"\b(?:kulutu|kulutukse|palkka|palka|tulo|tuloja|tili|saldo|meno|menoja|ostokse|lasku|"
                         r"laskuja|raha|rahoja)(?:ni|mme)\b|"
                         r"\b(?:kaytin|kaytan|kulutin|kulutan|maksoin|maksan|ostin|ostan|sain|saan|tienasin|tienaan|"
                         r"saastin|saastan|kustansin|lainasin|lahjoitin|annoin|kaytimme|kulutimme|maksoimme|ostimme|"
                         r"saimme|kaytamme|kulutamme)\b", re.I)
# "pay me back", "get for Christmas from me": the user is the payer or the payee ("more than me" is not)
ME_AFTER_VERB = re.compile(r"^(?: (?!than\b|kuin\b)\w+){0,3} (?:me|us|minulle|meille)\b", re.I)


def _first_person(plain: str) -> bool:
    low = NOT_FIRST.sub(" ", plain.lower())
    return bool(set(re.findall(r"[a-z']+", low)) & FIRST or FIRST_MONEY.search(low))


def _calendar(token: str) -> bool:
    t = re.sub(r"['’]s?$", "", fold(token).strip(".'’"))
    return t in CALENDAR_EN or any(re.fullmatch(re.escape(s) + r"\w{0,4}", t) for s in CALENDAR_FI)


def _known(token: str) -> bool:
    t = re.sub(r"['’]s?$", "", fold(token).strip(".'’"))
    return (t in _LABELS or t in _PAYEES or t in THINGS_EN or _calendar(token)
            or any(re.fullmatch(re.escape(s) + _ENDING, t) for s in STEMS))


def kind_of(np: str) -> str:
    """person, crowd, unknown or thing, for the words of a subject or owner (case and accents as typed)."""
    tokens = [t for t in re.findall(_TOKEN, np)]
    words = [re.sub(r"['’]s?$", "", fold(t).strip(".")) for t in tokens]
    words = [w if w in PERSON_FI else re.sub(r"(?<=\w\w\w)ll(?:a|ani)$", "", w) for w in words]
    content = [(t, w) for t, w in zip(tokens, words) if w not in DETERMINER]
    if content and all(w in FIRST for _, w in content):
        return "first"
    if any(w in FIRST for _, w in content) and {"and", "ja", "&"} & set(words):
        return "first"                               # "my wife and I", "me and my husband": the user's own
    content = [(t, w) for t, w in content if w not in FIRST]
    if not content:
        return "thing"
    if any(w in PERSON_EN or w in PERSON_FI or w in PRONOUN or w in TITLE for _, w in content):
        return "person"
    if any(w in CROWD for _, w in content):
        return "crowd"
    if any(_known(t) for t, _ in content):
        return "thing"
    if any(re.search(r"[^\x00-\x7f]", t) and not re.search(r"[a-zA-Z]", _plain(t)) for t, _ in content):
        return "person"                              # a non-Latin name ("Олег")
    if any(t[:1].isupper() for t, _ in content):
        return "person"                              # a capitalised word that is no known thing: a name
    return "unknown"


# Words that open a subject phrase but are not its head ("how much Jane spent", "what Mark spent").
FI_STOP = {"miten", "kuinka", "paljonko", "milloin", "mihin", "mista", "missa", "mika", "mita", "ennen",
           "on", "kun", "niin", "jos", "nyt", "sen", "taman", "tan", "sinun", "kaiken", "koko", "jokaisen", "oman",
           "minun", "meidan", "kuin"}
_LEAD = {"how", "much", "many", "what", "which", "show", "tell", "can", "could", "you", "check", "see", "paljonko",
         "kuinka", "paljon", "mita", "mihin", "nayta", "kerro"}
_BE = {"was", "were", "is", "are", "been", "be", "being", "olivat", "oli", "on", "ovat"}


def _head(np: str) -> str | None:
    """The subject phrase without its opening question words; None for a passive ("much was spent")."""
    tokens = np.split()
    while tokens and fold(tokens[0]) in _LEAD:
        tokens = tokens[1:]
    tokens = [tok for tok in tokens if not tok.lower().endswith("ly") and tok.lower() not in ("you", "u")]
    owned = [i for i, tok in enumerate(tokens) if tok.endswith(("'s", "’s", "'", "’"))]
    if owned:
        tokens = tokens[owned[-1] + 1:]               # "Marja's husband" spends: the husband
    if not tokens or fold(tokens[-1]) in _BE:
        return None
    return " ".join(tokens)


def classify(question: str, peer_question: bool = False) -> str | None:
    plain = re.sub(r"[?!,;:]", " ", _plain(question))
    plain = " ".join(plain.split())
    first = _first_person(plain)
    verdicts: list[str] = []

    def judge(np: str | None, *, unclaim: bool, spends: bool = False, subject: bool = False,
              person_verb: bool = False) -> None:
        """A person declines; a crowd or (with `unclaim`) an unknown word leaves the message unclaimed. With
        `spends` (the subject of spend, earn, save or buy), a capitalised calendar word is a name ("What did
        June spend?") and any other known thing leaves the message unclaimed."""
        if not np:
            return
        kind = kind_of(np)
        if kind == "person" and subject and not person_verb and not re.search(
                r"[A-Z]", np) and {fold(w) for w in np.split()} <= PRONOUN | DETERMINER:
            return                                    # "how do they compare": a pronoun spends, earns or owns
        if kind == "thing" and spends:
            names = [tok for tok in np.split() if tok[:1].isupper() and _calendar(tok)]
            verdicts.append(DECLINE if names else UNCLAIMED)
        elif kind == "person":
            verdicts.append(DECLINE)
        elif kind == "crowd" and not peer_question and unclaim:
            verdicts.append(UNCLAIMED)
        elif kind == "unknown" and unclaim:
            verdicts.append(UNCLAIMED)

    # Owners: another person's money, whoever asks ("my husband's account", "Marjan palkka"). A bill's,
    # a fee's or a payment's owner is a company. With the user as the speaker, an unknown owner is the user's.
    for m in list(PATTERNS["owner_direct"].finditer(plain)) + list(PATTERNS["owner"].finditer(plain)):
        noun = m.group("noun")
        if COMPANY_NOUN.match(noun):
            continue
        strong = bool(STRONG_OWNER_NOUN.match(noun))
        if not strong and first:
            continue                                  # "I spent on my daughter's clothes": the user's own
        judge(m.group("np"), unclaim=strong and not first)
    for m in PATTERNS["owner_of"].finditer(plain):
        judge(m.group("np"), unclaim=not first)
    for m in PATTERNS["owner_pronoun"].finditer(plain):
        judge(m.group("np"), unclaim=not first)
    for m in PATTERNS["spender"].finditer(plain):
        judge(m.group("np") or m.group("np2") or m.group("np3"), unclaim=True)
    for name in ("compare", "compare_to", "me_or", "or_me", "about", "and_name", "fi_has"):
        for m in PATTERNS[name].finditer(plain):
            judge(m.group("np"), unclaim=False)       # "more than usual" is no one; "than my wife" is
    for m in PATTERNS["fi_owner"].finditer(plain):
        if fold(m.group("np")) in FI_STOP:
            continue                                  # "Miten kulutukseni", "on palkka": no owner
        if COMPANY_NOUN.match(m.group("noun")) or not re.search(r"(?:n|ni)$", fold(m.group("np"))):
            continue                                  # a bill's or a fee's owner is a company; not a genitive
        judge(m.group("np"), unclaim=not first)

    # Subjects: only when the user is not the subject, or a question clause asks about someone else.
    for name in ("aux_subject", "subject", "what_if", "is_spending", "fi_subject", "fi_question", "fi_what_if", "fi_onko",
                 "fi_lead"):
        for m in PATTERNS[name].finditer(plain):
            if ME_AFTER_VERB.match(plain[m.end():]):
                continue                              # "did my brother pay me back": the user's own income
            if first and name in ("aux_subject", "subject", "fi_subject"):
                before = plain[:m.start()].lower().strip()
                np_lead = m.group("np").split()[0].lower()
                if not (re.search(rf"\b(?:{_QUESTION})$", before) or fold(np_lead) in _LEAD):
                    continue                          # "My wife paid for dinner, how much did I spend?"
            verb = m.groupdict().get("verb") or ""
            person_verb = (bool(re.fullmatch(VERB_PERSON, verb, re.I)) if not name.startswith("fi")
                           else bool(FI_VERB_PERSON.fullmatch(verb)) if verb else True)
            judge(_head(m.group("np")), unclaim=person_verb and not first, spends=person_verb and not first,
                  subject=True, person_verb=person_verb)
    if not first:
        m = PATTERNS["lead_name"].match(plain)
        if m and kind_of(m.group("np") or m.group("np2")) == "person":
            verdicts.append(UNCLAIMED)                # "Jane in June, how much?": not the user's numbers
    if DECLINE in verdicts:
        return DECLINE
    return UNCLAIMED if UNCLAIMED in verdicts else None
