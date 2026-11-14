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
    "niece", "nephew", "stepdad", "stepmom", "stepfather", "stepmother", "stepson", "stepdaughter",
    "sister-in-law", "brother-in-law", "mother-in-law", "father-in-law", "owner", "owners", "ceo", "founder",
    "director", "employee", "employees", "staff", "cashier", "waiter", "waitress", "worker", "workers", "seller",
    "woman", "women", "man", "men", "guy", "girl", "boy", "lady", "gentleman", "somebody", "someone",
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
    "lapsi", "lapseni", "lapsen", "lapset", "lasteni", "lasten", "lapsella", "lapsellani", "lapselle", "lapselleni", "naapuri", "naapurini", "naapurin", "mies",
    "mieheni", "miehen", "miehet", "vanhemmat", "vanhempani", "vanhempien", "mummo", "mummoni", "ukki", "ukkini",
    "isoaiti", "isoisa", "tati", "seta", "eno", "serkku", "serkkuni", "omistaja", "omistajan", "omistajat",
    "toimitusjohtaja", "toimitusjohtajan", "johtaja", "johtajan", "tyontekija", "tyontekijan", "tyontekijat",
    "myyja", "myyjan", "tarjoilija", "nainen", "naisen", "henkilo", "henkilon", "joku",
}
# The partitive forms (#638), which name the person of a comparison: "Kulutanko miestäni enemmän?" is "Do I spend more
# than my husband?". Only the comparison rule reads them: "muut, joilla on lapsia" stays a peer question.
PERSON_FI_PARTITIVE = {
    "miesta", "miestani", "vaimoa", "vaimoani", "puolisoa", "puolisoani", "kumppania", "kumppaniani", "lasta",
    "lastani", "lapsia", "lapsiani", "aitia", "aitiani", "isaa", "isaani", "ystavaa", "ystavaani", "ystavia",
    "ystaviani", "naapuria", "naapuriani", "siskoa", "siskoani", "veljea", "veljeani", "poikaa", "poikaani", "tytarta",
    "tytartani", "vanhempia", "vanhempiani", "kaveria", "kaveriani", "tyokaveria", "tyokaveriani", "kollegaa",
    "kollegaani", "pomoa", "pomoani", "tyttoystavaa", "tyttoystavaani", "poikaystavaa", "poikaystavaani",
}
# The user's own household: "our household", "our family", "perheemme" (review of #458).
HOUSEHOLD = {"household", "family", "home", "perhe", "perheeni", "perheemme", "perheen", "kotitalous", "talouteni",
             "taloutemme",
             "kotitalouteni", "kotitaloutemme", "kotitalouden"}
PRONOUN = {"she", "he", "they", "her", "his", "their", "him", "them", "han", "hanen", "heidan"}
TITLE = {"mr", "mrs", "ms", "miss", "dr", "rouva", "herra", "neiti", "tohtori"}
CROWD = {"everyone", "everybody", "others", "people", "person", "average", "most", "muut", "muiden", "kaikki",
         "ihmiset", "keskiverto", "suomalaiset"}
FIRST = {"i", "me", "we", "us", "myself", "ourselves", "mina", "minun", "minulle", "minulta", "minua", "minulla",
         "meidan", "meille", "meilta", "meita", "meilla", "voin", "voinko", "voisin", "voisinko", "haluan",
         "haluaisin", "saanko", "olen", "olenko", "olisin", "tarvitsen", "tarvitsisin", "pystyn", "pystyisin",
         "vahentaisin", "kayttaisin", "kuluttaisin", "saastaisin", "leikkaisin", "ostaisin", "maksaisin",
         "lopettaisin", "jattaisin", "siirtaisin"}
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
# Plain spending nouns, Finnish stems with case endings and English words: never a person ("Paljonko kulutti
# Ruoka", "Vaatteet", "Vakuutus"). A shop's name is in STEMS.
THING_NOUN_STEMS = ("ruoka", "ruoa", "ruoan", "ruokaa", "juoma", "vaatte", "vaate", "vakuutu", "puhelin", "apteek",
                    "laakar", "parturi", "kampaaj", "vuokra", "sahko", "netti", "liikenne", "bensa", "polttoaine",
                    "kuntosali", "lahja", "harrastu", "matka", "ravintol", "kahvil", "lasku", "kirja", "lelu", "elokuv",
                    "taksi", "juna", "bussi", "asunto", "terveys", "kauneus", "lemmikki", "hoito", "laakk", "ostoks",
                    "kulutu", "meno", "tulo", "palkka", "saasto")
THING_NOUNS_EN = {"food", "drink", "drinks", "clothes", "insurance", "phone", "pharmacy", "doctor", "hairdresser",
                  "barber", "electricity", "internet", "gym", "gifts", "hobbies", "cafe", "books", "toys", "movies",
                  "train", "bus", "car", "health", "beauty", "pets", "groceries", "shopping", "spending"}


def _thing_noun(token: str) -> bool:
    t = re.sub(r"['’]s?$", "", fold(token).strip(".'’"))
    return t in THING_NOUNS_EN or any(t.startswith(s) for s in THING_NOUN_STEMS)


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
_NOT_SHOPS = ("suomi", "suome", "kuukau", "kuu", "viiko", "vuode", "vuosi", "paiva", "tama", "viime", "edellis")
_ENDING = r"(?:n|in|an|en|un|yn|on|ssa|sta|lla|lta|lle|ksi|a|ta|na|t|ja|ihin|iin|seen|lle|kin)?"
_LABELS = {fold(lab) for table in (config.CATEGORY_LABELS, config.BASKET_LABELS, config.MCC_GROUP_LABELS)
           for pair in table.values() for lab in pair}
_LABELS |= {w for lab in list(_LABELS) for w in lab.replace("&", " ").split() if len(w) > 2}
# Capitalised only because a sentence starts with them, or the coach's "you": never a name.
NOT_A_NAME = {"that", "this", "these", "those", "it", "there", "here", "what", "who", "how", "which",
              "when", "where", "why", "the", "a", "an", "and", "but", "or", "so", "then", "your", "my",
              "our", "you", "u", "any", "some", "every", "each", "all", "no", "not", "also", "just",
              "voit", "voisit", "haluat", "olet", "saat", "sina", "sa", "te", "teidan", "se", "tama",
              "tuo", "ne", "nama", "arki", "arjen", "iban", "eur", "mcc", "sepa", "pin", "atm", "vat",
              "alv", "taxis", "cafes", "bars", "flights", "hotels", "subscriptions", "parking"}
_PAYEES = {fold(p) for names in config.PAYEE_ALIASES.values() for name in names for p in name.split()}

MONEY_EN_STRONG = (r"spending|spend|purchases?|transactions?|money|salary|salaries|income|budget|accounts?|balance|"
                   r"expenses?|savings|earnings|wages?|pension|debts?|loans?|net worth|finances")
MONEY_EN_WEAK = r"groceries|food|shopping|clothes|rent|card"
COMPANY_CONTEXT = r"bills?|invoices?|payments?|fees?|prices?|subscriptions?|charges?|plan"
VERB_PERSON = r"spend|spent|spends|earn|earned|earns|save|saved|saves|buy|bought|buys|shop|shops|shopped"
VERB_ANY = (VERB_PERSON + r"|pay|paid|pays|make|made|makes|owe|owes|get|got|gets|cost|costs|cut|cuts|have|has|"
            r"own|owns|compare|compares|give|gave|gives|send|sent|sends|lend|lent|lends|transfer|transferred|"
            r"transfers|return|returned|returns|gift|gifted|gifts|receive|received|receives")
VERB_PAST = r"spent|spends|earned|earns|paid|pays|bought|buys|saved|saves|owes|makes|made|cut|cuts"
FI_VERB = (r"kaytti|kayttaa|kayttavat|kayttivat|kulutti|kuluttaa|kuluttavat|kuluttivat|maksoi|maksaa|maksavat|"
           r"maksoivat|ostivat|tienasivat|ansaitsivat|saastivat|"   # the 3rd person plural past (#517)
           r"sai|saa|saavat|saivat|antoi|antaa|antoivat|lahetti|lahettivat|lainasi|lainasivat|siirsi|siirsivat|"
           r"palautti|palauttivat|lahjoitti|lahjoittivat|"
           r"osti|ostaa|ostavat|tienaa|tienasi|tienaavat|ansaitsi|ansaitsee|saasti|saastaa|"
           r"on (?:tienannut|kayttanyt|kuluttanut|maksanut|saastanyt|ostanut|ansainnut)")
FI_QUESTION_VERB = r"kuluttaako|kayttaako|maksaako|tienaako|ostaako|saastaako|ansaitseeko|antaako|tarjoaako|saako"
FI_WHAT_IF_VERB = r"vahentaisi|leikkaisi|kayttaisi|kuluttaisi|saastaisi"
FI_MONEY = r"kulutu\w*|palk(?!kapaiv)\w*|tulo\w*|tili\b|tilin\b|tilil\w*|saldo\w*|meno\w*|ostok\w*|tilitapahtum\w*|raho\w*"
FI_COMPANY = r"\w*(?:lasku|maksu|hinta|hinna)\w*"

FI_VERB_PERSON = re.compile(r"kaytti|kayttaa|kayttavat|kayttivat|kulutti|kuluttaa|kuluttavat|kuluttivat|osti|ostaa|"
                            r"sai|saa|saavat|saivat|ostivat|tienasivat|ansaitsivat|saastivat|"
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
    "subject_base": re.compile(rf"{_NP1} (?P<verb>spend|spends|earn|earns|buy|buys|save|saves|shop|shops)\b", re.I),
    "group_of": re.compile(rf"\b(?:one|some|any|both|all|each|most|none|two|three|several) of "
                           rf"(?P<np>(?:my|our|the|his|her|their) {_TOKEN})(?: (?P<verb>{VERB_ANY}))?", re.I),
    "aux_subject_of": re.compile(rf"\b(?:{_AUX}) (?P<np>(?:(?:the|a|an|my|our) )?{_TOKEN}) of (?:(?:the|a|an) )?"
                                 rf"{_TOKEN}(?: {_TOKEN})? (?P<verb>{VERB_ANY})\b", re.I),
    "is_spending": re.compile(rf"\b(?:is|are|was|were) {_NP1} (?P<verb>spending|earning|saving)\b", re.I),
    "fi_subject": re.compile(rf"(?<=\w )(?P<np>{_TOKEN}(?: (?:ja|tai) {_TOKEN})?) (?P<verb>{FI_VERB})\b", re.I),
    "fi_question": re.compile(rf"\b(?P<verb>{FI_QUESTION_VERB}) (?P<np>{_TOKEN})\b", re.I),
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
    "fi_verb_first": re.compile(rf"\b(?P<verb>{FI_VERB}) (?P<np>{_TOKEN})\b", re.I),
    "fi_experiencer": re.compile(rf"(?<=\w )(?P<np>{_TOKEN}(?:lla|llani|lle|lleni)) (?P<verb>kului|kuluu|meni|menee|jai|jaa|"
                                 rf"kertyi|kertyy|tuli|tulee)\b", re.I),
    "fi_per": re.compile(rf"(?<=\w )(?P<np>{_TOKEN}) kohden\b", re.I),
    "spender": re.compile(rf"\b(?:what (?:kind|type|sort) of (?:spender|saver|consumer) (?:is|was|are) {_NP1}|"
                          rf"is (?P<np3>{_TOKEN}) an? (?:big |small |good |bad )?(?:spender|saver)|"
                          rf"millainen (?:kuluttaja|saastaja) (?P<np2>{_TOKEN}) on\b)", re.I),
    # #638, read per clause: a person who may spend or save ("Paljonko vaimoni voi käyttää turvallisesti?"), who can
    # afford something ("Onko vaimollani varaa …?"), who owns the coach's Finnish term ("mieheni turvallisesti
    # käytettävä summa", "mieheni budjetti", as "my husband's safe to spend"), a comparison in the partitive or with
    # "verrattuna" ("Kulutanko miestäni enemmän?", "vaimooni verrattuna"), and the one a thing cost ("What did my wife's
    # gym cost her?", review of #635; "Paljonko kuntosali maksoi vaimolleni?")
    "fi_modal_subject": re.compile(rf"(?<=\w )(?P<np>{_TOKEN}) (?:voi|voisi|pystyy|pystyisi|uskaltaa) (?:\w+ )?"
                                   rf"(?:kayttaa|kuluttaa|saastaa|tuhlata|ostaa|laittaa)\b", re.I),
    "fi_afford": re.compile(rf"\bonko (?P<np>{_TOKEN}) varaa\b", re.I),
    "fi_term_owner": re.compile(rf"(?P<np>{_TOKEN}) (?:turvallisesti (?:kaytettav|saastettav)\w*|turvalli\w* kayttovar\w*|"
                                rf"budjet\w*)", re.I),
    "fi_compare_partitive": re.compile(rf"(?<=\w )(?P<np>{_TOKEN}) (?P<cmp>enemman|vahemman|useammin|harvemmin|"
                                       rf"suuremm\w*|pienemm\w*|verrattuna)\b|\bverrattuna (?P<np2>{_TOKEN})", re.I),
    "cost_to": re.compile(rf"\b(?:cost|costs|charge|charged|charges) (?!(?:in|on|at|per|for|to|with|from|by|of|last|this|"
                          rf"next|each|every|so|now|then|about|around|altogether|overall)\b)"
                          rf"(?P<np>(?:(?:my|our|the|his|her|their) )?{_TOKEN}"
                          rf"(?: (?:and|or) (?:(?:my|our|the|his|her|their) )?{_TOKEN})?)", re.I),
    # a person's thing as the subject of a cost question: "How much did my husband's phone plan cost?" (#639, review of
    # #647); the user's own spending on it keeps its outcome ("How much did I spend on my husband's birthday?")
    "owner_cost": re.compile(rf"\b(?:did|does|do|is|was|has|will|would) (?:my|our) (?P<np>{_TOKEN})['’]s? "
                             rf"(?:{_TOKEN} ){{0,3}}(?:cost|costs|come to|run)\b(?!\s+(?:me|us)\b)", re.I),
    # the Finnish twin: "Paljonko mieheni liittymä maksoi?", "Mitä vaimoni vakuutus maksaa?" (review of #679); the
    # user's own cost of it ("… maksoi minulle") keeps its outcome
    "fi_owner_cost": re.compile(rf"\b(?:paljonko|mita|kuinka paljon) (?P<np>{_TOKEN}) (?:{_TOKEN} ){{1,2}}?"
                                rf"(?:maksoi|maksaa|maksoivat|maksavat|kustansi|kustantaa)\b(?! (?:minulle|meille)\b)",
                                re.I),
    "fi_cost_to": re.compile(rf"\b(?:maksoi|maksoivat|maksavat|kustansi)(?: {_TOKEN}){{0,2}}? "
                             rf"(?P<np>{_TOKEN}(?:lle|lleni|llemme))\b", re.I),
    # a lone name at the start with a time: "Jane in June, how much?"
    "lead_name": re.compile(rf"^(?P<np>{_TOKEN}) (?:in|during) (?:{_CALENDAR_RX})\b|"
                           rf"^(?P<np2>{_TOKEN}) (?:last|this) (?:week|month|year)\b", re.I),
}
STRONG_OWNER_NOUN = re.compile(rf"^(?:{MONEY_EN_STRONG}|{FI_MONEY})$", re.I)
# A bonus, interest or points question is about a company, whatever its name ("Does Ruohonjuuri pay S-Bonus?").
COMPANY_TALK = re.compile(r"\b(?:s-?bonus\w*|bonus\w*|interest|points?|cashback|rewards?|korko\w*|pistei\w*)\b", re.I)
PAY_TO_ME = re.compile(r"pay|paid|pays|give|gave|gives|send|sent|sends|transfer|transferred|transfers|lend|lent|lends|"
                       r"refund|refunded|owe|owes|return|returned|returns|gift|gifted|gifts|maksoi|maksaa|maksoivat|maksavat|antavat|lahettavat|"
                       r"antoi|antaa|antoivat|lahetti|lahettivat|siirsi|siirsivat|lainasi|lainasivat|palautti|"
                       r"palauttivat|lahjoitti|lahjoittivat", re.I)
# A: a bonus, interest or points question makes a name a company only when it pays, gives or offers
PAYS_OUT = re.compile(r"pay|pays|paid|give|gives|gave|offer|offers|offered|maksaa|maksaako|maksoi|antaa|antaako|"
                      r"tarjoaa|tarjoaako", re.I)
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


_MONEY_VERB = (r"spend|spent|spends|spending|pay|paid|pays|paying|earn|earned|earns|buy|bought|save|saved|saves|"
               r"saving|get|got|gets|receive|received|give|gave|owe|lend|lent|use|used|have|had|make|made|cut|"
               r"reduce|afford|transfer|transferred|shop|shopped|lose|lost|need|put|invest|withdraw")
_TO_ME_VERB = (r"cost|costs|pay|paid|pays|give|gave|gives|owe|owes|earn|earned|earns|save|saved|saves|charge|"
               r"charged|charges|send|sent|lend|lent|refund|refunded|transfer|transferred")
# "did I spend", "I paid", "we bought"; "cost me", "pay me back", "from me". A perception or cognition verb in front
# ("I know my wife spent", "I heard Jane spent") is no first person: the money clause is someone else's.
_FILLER = (r"do|did|does|have|had|has|will|would|can|could|should|also|just|really|actually|usually|probably|"
           r"always|never|still|ever|not|already|even|only|all|both|each|recently|mostly|often")
FIRST_SUBJECT = re.compile(rf"\b(?:i|we)\b(?: (?:{_FILLER}))* (?:{_MONEY_VERB})\b", re.I)
FIRST_OBJECT = re.compile(rf"\b(?:{_TO_ME_VERB})(?: \w+){{0,2}}? (?:me|us)\b|\bfrom (?:me|us)\b", re.I)
FI_FIRST = re.compile(r"\b(?:minulle|minulta|meille|meilta|vahentaisin|kayttaisin|kuluttaisin|saastaisin|leikkaisin|"
                      r"ostaisin|maksaisin|lopettaisin|jattaisin|siirtaisin)\b|"
                      r"\b(?:voin|voinko|voisin|voisinko|haluan|haluaisin|pystyn|pystyisin|saanko|tarvitsen)"
                      r"(?: \w+)? (?:saastaa|kayttaa|kuluttaa|maksaa|ostaa|saada|leikata|vahentaa|laittaa|sijoittaa)\b",
                      re.I)


APPOSITION = re.compile(rf"\b(?:I|[Ww]e), [A-Z]\w+, (?:\w+ )?(?:{_MONEY_VERB})\b")


def _first_person(plain: str, question: str = "") -> bool:
    if APPOSITION.search(question):
        return True
    low = NOT_FIRST.sub(" ", plain.lower())
    return bool(FIRST_SUBJECT.search(low) or FIRST_OBJECT.search(low) or FIRST_MONEY.search(low)
                or FI_FIRST.search(low))


def _calendar(token: str) -> bool:
    t = re.sub(r"['’]s?$", "", fold(token).strip(".'’"))
    return t in CALENDAR_EN or any(re.fullmatch(re.escape(s) + r"\w{0,4}", t) for s in CALENDAR_FI)


def _shop(token: str) -> bool:
    """A shop, bank, utility or service of the known list (with a Finnish case ending), or a payee alias."""
    t = re.sub(r"['’]s?$", "", fold(token).strip(".'’"))
    return t in _PAYEES or any(re.fullmatch(re.escape(s) + _ENDING, t) for s in STEMS if s not in _NOT_SHOPS)


# A company as the owner of spending, income or salary is not the user's (#486): "Prisma's spending",
# "Lidl's income", "Netflix's salary", "Lidlin tulot". "Lidlin ostokset / kulutus" stays the user's purchases at Lidl.
COMPANY_MONEY_EN = re.compile(r"spending|income|salary|salaries|earnings|wages?|revenue|profits?|money|budget|"
                              r"finances|net worth", re.I)
COMPANY_MONEY_FI = re.compile(r"palk\w*|tulo\w*|liikevaihto\w*|voito\w*|voitto\w*", re.I)
GET_VERBS = re.compile(r"get|got|gets|receive|received|receives|pay|paid|pays|maksoi|maksoivat|maksaa|maksavat", re.I)   # a pronoun that gets or pays is a person
# "I, my wife and our kids spent": a comma list that starts with the user is the user's household (#486)
JOINT_LIST = re.compile(r"\b(?:i|me|we)(?:, (?:my|our|the) \w+)+,? (?:and|&) (?:my|our|the) \w+(?: \w+)? "
                        r"(?:spend|spent|paid|bought|earned|saved|pay|buy)\b", re.I)


def _known(token: str) -> bool:
    t = re.sub(r"['’]s?$", "", fold(token).strip(".'’"))
    return (t in _LABELS or t in _PAYEES or t in THINGS_EN or _calendar(token)
            or any(re.fullmatch(re.escape(s) + _ENDING, t) for s in STEMS))


def _case_stem(word: str) -> str:
    """A folded word without its "-lla(ni)" or "-lle(ni)" ending. A stem whose genitive is a person word reads as that
    genitive (#638): "miehelläni" is "miehen", "äidilleni" is "äidin", like "vaimollani" and "isälläni"."""
    stem = re.sub(r"(?<=\w\w\w)(?:ll(?:a|ani)|lle(?:ni)?)$", "", word)
    return stem + "n" if stem != word and stem + "n" in PERSON_FI else stem


def kind_of(np: str) -> str:
    """person, crowd, unknown or thing, for the words of a subject or owner (case and accents as typed)."""
    tokens = [t for t in re.findall(_TOKEN, np)]
    words = [re.sub(r"['’]s?$", "", fold(t).strip(".")) for t in tokens]
    words = [w if w in PERSON_FI else _case_stem(w) for w in words]
    content = [(t, w) for t, w in zip(tokens, words) if w not in DETERMINER]
    if content and (all(w in FIRST for _, w in content) or content[-1][1] in FIRST):
        return "first"                               # "I", "help me (save)": the user
    if {"store", "stores", "shop", "shops", "bank", "banks", "company", "companies", "business", "businesses",
            "brand", "brands", "merchant", "merchants", "chain", "chains"} & set(words):
        return "thing"                               # "our partner stores": companies
    if any(w in HOUSEHOLD for _, w in content) and not {"the", "his", "her", "their"} & set(words) and not any(
            t[:1].isupper() and not _known(t) and w not in HOUSEHOLD for t, w in content):
        return "first"                               # "our household", "perheemme": the user's own
    content = [(t, w) for t, w in content if w not in HOUSEHOLD]   # "the Virtanen family": the Virtanens
    if not content:
        return "thing"
    if any(w in FIRST for _, w in content) and {"and", "ja", "&"} & set(words):
        return "first"                               # "my wife and I", "me and my husband": the user's own
    content = [(t, w) for t, w in content if w not in FIRST]
    if not content:
        return "thing"
    if any(w in PERSON_EN or w in PERSON_FI or w in PRONOUN or w in TITLE or w.startswith("ex-")
           or any(part in PERSON_EN for part in w.split("-")) for _, w in content):
        return "person"
    if any(w in CROWD for _, w in content):
        return "crowd"
    if any(_known(t) for t, _ in content):
        return "thing"
    if any(_thing_noun(t) for t, _ in content):
        return "noun"                                # "Ruoka", "Vaatteet", "Vakuutus": a spending noun
    content = [(t, w) for t, w in content if w not in NOT_A_NAME]
    if not content:
        return "thing"
    if any(re.search(r"[^\x00-\x7f]", t) and not re.search(r"[a-zA-Z]", _plain(t)) for t, _ in content):
        return "name"                                # a non-Latin name ("Олег")
    if any(t[:1].isupper() for t, _ in content):
        return "name"                                # a capitalised word that is no known thing: a name
    return "unknown"


# Words that open a subject phrase but are not its head ("how much Jane spent", "what Mark spent").
FI_STOP = {"miten", "kuinka", "paljonko", "milloin", "mihin", "mista", "missa", "mika", "mita", "ennen",
           "on", "kun", "niin", "jos", "nyt", "sen", "taman", "tan", "sinun", "kaiken", "koko", "jokaisen", "oman",
           "minun", "meidan", "kuin"}
TO_ME_SKIP = re.compile(r"cost|costs|earn|earned|earns|save|saved|saves|charge|charged|charges|get|got|"
                        r"gets|receive|received|receives|maksoi|maksaa|kulutti|kaytti|osti", re.I)
FI_COST = re.compile(r"maksoi|maksaa", re.I)
FI_MODAL = (r"voin|voit|voi|voimme|voitte|voivat|voisin|voisit|voisi|haluan|haluat|haluaa|pitaa|pitaisi|"
            r"saan|saat|kannattaa|kannattaisi|pystyn|pystyt|pystyy|aion|aiot|aikoo|taytyy|tarvitsee")
ADVERBS = {"safely", "really", "actually", "usually", "probably", "roughly", "approximately", "exactly", "only",
           "mostly", "nearly", "likely", "just", "even", "still", "also", "totally", "completely", "certainly",
           "definitely", "normally", "typically", "generally", "recently", "lately", "finally", "already", "often"}
_LEAD = {"how", "much", "many", "what", "which", "show", "tell", "can", "could", "check", "see", "so", "then",
         "and", "but", "also", "just", "paljonko",
         "kuinka", "paljon", "mita", "mihin", "nayta", "kerro"}
_BE = {"was", "were", "is", "are", "been", "be", "being", "olivat", "oli", "on", "ovat", "to", "would", "will",
       "can", "could", "should", "did", "does", "do", "may", "might", "must"}   # "safe to spend"


def _head(np: str) -> str | None:
    """The subject phrase without its opening question words; None for a passive ("much was spent")."""
    tokens = np.split()
    while tokens and fold(tokens[0]) in _LEAD:
        tokens = tokens[1:]
    if any(re.sub(r"['’](?:d|ll|re|ve)$", "", fold(tok)) in ("you", "u", "voit", "voisit", "sina", "sa") for tok in tokens):
        return None                                   # the coach's "you" ("what you'd save")
    if any(fold(tok) in FIRST for tok in tokens):
        return None                                   # the user in the subject: "i safly spend", "me and my wife"
    tokens = [tok for tok in tokens if tok.lower() not in ADVERBS and not re.fullmatch(r"\w{4,}sti", fold(tok))]
    owned = [i for i, tok in enumerate(tokens) if tok.endswith(("'s", "’s", "'", "’"))]
    if owned:
        tokens = tokens[owned[-1] + 1:]               # "Marja's husband" spends: the husband
    if not tokens or (fold(tokens[-1]) in _BE and not tokens[-1][:1].isupper()):
        return None
    return " ".join(tokens)


# The person the user gave, sent, lent, owed, paid or bought something for (#542): "How much did I give my husband?",
# "What did I buy my wife?", "How much did I pay Marja?", "Paljonko annoin miehelleni?", "Mitä ostin Marjalle?",
# "Paljonko käytin vaimooni?". It is the user's own money, but no category or filter maps the person.
GIVE_TO_EN = re.compile(r"\b(?:give|gave|given|send|sent|lend|lent|owe|owed|buy|bought|get|got|pay|paid)\s+"
                        r"((?:my|our|his|her|their)\s+[^\W\d_][\w'-]*|[A-Z][^\W\d_][\w'-]*)")
FI_TO_SUFFIX = re.compile(r"(?:lle|lleni|llesi|llemme|llenne|lleen)$")
# allative stems kind_of does not know from PERSON_FI ("miehelleni", "äidilleni", "veljelleni")
FI_TO_STEMS = {"miehe", "aidi", "velje", "poja", "tyttare", "lapse", "vanhemmi", "sisare", "esimiehe"}
FI_INTO_PERSON = {"vaimooni", "mieheeni", "lapsiini", "lapseeni", "aitiini", "isaani", "siskooni", "veljeeni",
                  "ystavaani", "puolisooni", "poikaani", "tyttareeni", "kumppaniini", "vanhempiini"}


_ASKING = re.compile(r"\b(?:how much|how many|what|which|paljonko|kuinka paljon|mita|mihin|kenelle)\b", re.I)


def to_person(question: str) -> bool:
    """The question names a person as the one the user's money went to (see GIVE_TO_EN), in the part that asks:
    "I bought my brother a gift, how much did I spend in August?" asks for August's spending."""
    parts = [p for p in re.split(r"[.?!,;]", _plain(question)) if _ASKING.search(fold(p))]
    plain = " ".join(parts) if parts else _plain(question)
    if any(kind_of(m.group(1)) in ("person", "name") for m in GIVE_TO_EN.finditer(plain)):
        return True
    for token in re.findall(r"[^\W\d_]+", plain):
        word = fold(token)
        if word in FI_INTO_PERSON:
            return True
        stem = FI_TO_SUFFIX.sub("", word)
        if stem != word and (stem in FI_TO_STEMS or kind_of(token) in ("person", "name")):
            return True
    return False


# The coach's own terms (#601): "safe to spend" and "safe to save" are money, like "budget", whoever owns them ("my
# wife's safe to spend" is her money), and never a name, however they are capitalised ("What Is Safe To Spend?").
PRODUCT_TERM = re.compile(r"\bsafe[ -]to[ -](?:spend|save)\b", re.I)


def _normalised(question: str) -> str:
    """The question as the people rules read it (#601): the coach's own terms read as the money word "budget", in any
    case ("What Is Safe To Spend?": its capitals mark no name; a real name keeps its capital and its reading)."""
    # "my wife safe to spend" is "my wife's budget": a person word right before the term owns it
    question = re.sub(r"\b(my|our|his|her|their)\s+([^\W\d_]+)\s+(?=safe[ -]to[ -](?:spend|save)\b)",
                      lambda m: f"{m.group(1)} {m.group(2)}'s " if fold(m.group(2)) in PERSON_EN else m.group(0),
                      question, flags=re.I)
    return PRODUCT_TERM.sub("budget", question)


_PLACE = re.compile(r"(?:ss|st|ll|lt)a$|lle$|ksi$")   # a local case: "Tukholmassa" is a place, no name


def _other_spender(clause: str, first: bool) -> list[str]:
    """The verdicts of the #638 rules on one clause (accents off, see PATTERNS). A Finnish allative after "maksoi" is the
    one charged or the one the user bought for ("Paljonko maksoi lahja vaimolleni?"): the message is unclaimed."""
    out: list[str] = []
    for name in ("fi_modal_subject", "fi_afford"):
        for m in PATTERNS[name].finditer(clause):
            np, kind = m.group("np"), kind_of(m.group("np"))
            if fold(np) in FI_STOP or (kind == "name" and _PLACE.search(fold(np))):
                continue                              # "Paljonko voi käyttää", "Paljonko Tukholmassa voi käyttää"
            if first and not re.search(rf"\b(?:{_QUESTION}|miksi|onko)\s*$", clause[:m.start()], re.I):
                continue                              # "Paljonko voin käyttää, jos vaimoni voi ostaa auton?"
            if kind in ("person", "name"):
                out.append(DECLINE)
    for m in PATTERNS["fi_term_owner"].finditer(clause):
        np, kind = m.group("np"), kind_of(m.group("np"))
        if kind == "person" or (kind == "name" and m.start() > 0 and re.search(r"(?<!ne)n$", fold(np))):
            out.append(DECLINE)                       # "mieheni / Marjan turvallisesti käytettävä summa"
    for m in PATTERNS["fi_compare_partitive"].finditer(clause):
        word = fold(m.group("np") or m.group("np2"))
        verrattuna = m.group("np2") is not None or fold(m.group("cmp")) == "verrattuna"
        if word in (FI_INTO_PERSON if verrattuna else PERSON_FI_PARTITIVE):
            out.append(DECLINE)                       # "Kulutanko miestäni enemmän?", "vaimooni verrattuna"
    for m in PATTERNS["cost_to"].finditer(clause):
        np, kind = m.group("np"), kind_of(m.group("np"))
        if fold(np).split()[0] in ("her", "him", "them") or kind == "person" or (
                kind == "name" and m.group(0)[:1].islower()):
            out.append(DECLINE)                       # "cost her" ("her" alone is no determiner); title case is no name
    for m in PATTERNS["owner_cost"].finditer(clause):
        if kind_of(m.group("np")) == "person":
            out.append(DECLINE)                       # "did my husband's phone plan cost?"
    for m in PATTERNS["fi_owner_cost"].finditer(clause):
        if kind_of(m.group("np")) == "person" and re.search(r"(?:ni|n)$", fold(m.group("np"))):
            out.append(DECLINE)                       # "Paljonko mieheni liittymä maksoi?" (a genitive owner)
    for m in PATTERNS["fi_cost_to"].finditer(clause):
        if kind_of(m.group("np")) in ("person", "name"):
            out.append(UNCLAIMED)
    if re.search(r"\b(?:maksoi|maksoivat|maksavat|kustansi)\b.*\b(?:hanelle|heille)\b", clause, re.I):
        out.append(UNCLAIMED)                         # "Mitä äitini vakuutus maksoi hänelle?"
    return out


def classify(question: str, peer_question: bool = False) -> str | None:
    question = _normalised(question)
    plain = re.sub(r"[?!,;:]", " ", _plain(question))
    plain = " ".join(plain.split())
    if JOINT_LIST.search(_plain(question)):
        return None                                   # "I, my wife and our kids spent": the user's household
    first = _first_person(plain, _plain(question))
    verdicts: list[str] = []

    def judge(np: str | None, *, unclaim: bool, spends: bool = False, subject: bool = False,
              person_verb: bool = False, verb: str = "") -> None:
        """A person declines; a crowd or (with `unclaim`) an unknown word leaves the message unclaimed. With
        `spends` (the subject of spend, earn, save or buy), a capitalised calendar word is a name ("What did
        June spend?") and any other known thing leaves the message unclaimed."""
        if not np:
            return
        kind = kind_of(np)
        if kind == "name":
            if COMPANY_TALK.search(plain) and (not verb or PAYS_OUT.fullmatch(verb)):
                return                                # "Does Zalando pay bonus?": a company; "did Jane get" is not
            kind = "person"
        if kind == "person" and subject and not person_verb and not GET_VERBS.fullmatch(verb) and not re.search(
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
    company_owned = {m.group("np") for m in PATTERNS["owner"].finditer(plain) if COMPANY_NOUN.match(m.group("noun"))
                     and any(_shop(tok) or _known(tok) for tok in m.group("np").split())}
    for m in list(PATTERNS["owner_direct"].finditer(plain)) + list(PATTERNS["owner"].finditer(plain)):
        noun = m.group("noun")
        if COMPANY_NOUN.match(noun) or m.group("np") in company_owned:
            continue                                  # "Helen's bill", "Nordea's account fee": a company
        if COMPANY_MONEY_EN.fullmatch(noun) and any(_shop(tok) for tok in m.group("np").split()):
            verdicts.append(UNCLAIMED)                # "Prisma's spending", "Lidl's income": not the user's
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
    for name in ("compare", "compare_to", "me_or", "or_me", "about", "and_name", "fi_has", "fi_experiencer", "fi_per"):
        for m in PATTERNS[name].finditer(plain):
            # an experiencer ("Marjalle kertyi bonusta") gets, never pays: a name stays a person
            judge(m.group("np"), unclaim=False, verb=m.groupdict().get("verb") or "")       # "more than usual" is no one; "than my wife" is
    for m in PATTERNS["fi_owner"].finditer(plain):
        if fold(m.group("np")) in FI_STOP:
            continue                                  # "Miten kulutukseni", "on palkka": no owner
        if COMPANY_NOUN.match(m.group("noun")) or not re.search(r"(?:n|ni)$", fold(m.group("np"))):
            continue                                  # a bill's or a fee's owner is a company; not a genitive
        if COMPANY_MONEY_FI.fullmatch(m.group("noun")) and _shop(m.group("np")):
            verdicts.append(UNCLAIMED)                # "Lidlin tulot", "Prisman palkka": not the user's
            continue
        judge(m.group("np"), unclaim=not first)
    for clause in re.split(r"[.?!;]", _plain(question)):
        verdicts += _other_spender(" ".join(re.sub(r"[,:]", " ", clause).split()), first)

    # Subjects: only when the user is not the subject, or a question clause asks about someone else.
    for name in ("aux_subject", "aux_subject_of", "subject", "subject_base", "what_if", "is_spending", "group_of",
                 "fi_subject",
                 "fi_verb_first",
                 "fi_question", "fi_what_if", "fi_onko", "fi_lead"):
        for m in PATTERNS[name].finditer(plain):
            if ME_AFTER_VERB.match(plain[m.end():]) and (PAY_TO_ME.fullmatch(m.groupdict().get("verb") or "")
                                                          or TO_ME_SKIP.fullmatch(m.groupdict().get("verb") or "")):
                verb = m.groupdict().get("verb") or ""
                payer = kind_of(_head(m.group("np")) or "")
                if PAY_TO_ME.fullmatch(verb) and (payer == "person" or (payer == "name" and not COMPANY_TALK.search(plain))):
                    verdicts.append(UNCLAIMED)        # money paid TO the user by a person: not get_spending
                continue                              # "did Prisma pay me bonus": the user's own
            if re.search(r"\b(?:i|me|we|us|mina|me) (?:and|ja) $", plain[:m.start()], re.I):
                continue                              # "me and my wife spend": the user's own
            if name == "fi_verb_first" and re.search(rf"\b(?:{FI_MODAL})\s*$", plain[:m.start()], re.I):
                continue                              # "Voit käyttää": an infinitive after a modal, no subject
            if name == "fi_verb_first" and not re.search(r"\b(?:paljonko|paljon|mita|mihin|montako|euroa)\s*$",
                                                         plain[:m.start()], re.I):
                continue                              # "Paljonko perhe käytti ruokaan": the subject is before
            if name == "fi_verb_first" and FI_COST.fullmatch(m.group("verb")):
                # "Paljonko maksoi X?": X may be a thing that cost. A name with an object is the payer
                # ("maksoi Marja vuokraa"); without one it is unclear; a known shop is the user's bill.
                payer = kind_of(m.group("np"))
                after = plain[m.end():].split()
                has_object = bool(after) and not (_known(after[0]) or fold(after[0]) in ("viime", "tana", "tassa",
                                                                                         "yhteensa", "kuussa"))
                if payer == "person" or (payer == "name" and has_object):
                    verdicts.append(DECLINE)
                elif payer == "name" or (payer == "noun" and m.group("np")[:1].isupper()):
                    verdicts.append(UNCLAIMED)
                continue
            if name == "group_of" and first:
                continue                              # "I spent on one of my friends"
            if first and name in ("aux_subject", "aux_subject_of", "subject", "subject_base", "fi_subject",
                                  "fi_verb_first"):
                before = plain[:m.start()].lower().strip()
                np_lead = m.group("np").split()[0].lower()
                if not (re.search(rf"\b(?:{_QUESTION})$", before) or fold(np_lead) in _LEAD):
                    continue                          # "My wife paid for dinner, how much did I spend?"
            verb = m.groupdict().get("verb") or ""
            person_verb = (bool(re.fullmatch(VERB_PERSON, verb, re.I)) if not name.startswith("fi")
                           else bool(FI_VERB_PERSON.fullmatch(verb)) if verb else True)
            # a word after a Finnish verb may be a time ("kulutti kesäkuussa"): the calendar-name rule is English
            judge(_head(m.group("np")), unclaim=person_verb and not first,
                  spends=person_verb and not first and name != "fi_verb_first",
                  subject=True, person_verb=person_verb, verb=verb)
    if not first:
        m = PATTERNS["lead_name"].match(plain)
        if m and kind_of(m.group("np") or m.group("np2")) in ("person", "name"):
            verdicts.append(UNCLAIMED)                # "Jane in June, how much?": not the user's numbers
    if DECLINE in verdicts:
        return DECLINE
    return UNCLAIMED if UNCLAIMED in verdicts else None
