"""Output checks of a talk-mode answer (#873), ported from #618's general-answer checks (head bdd564d1).

The patterns below are #618's, unchanged: numbers of any kind in words, products, banks and brands, health, other
people's money, links, borrowing in any form, judging, statements about the user's own money, names, and the
language check. A talk-mode draft may cite one number of the conversation by its token; the tokens are taken out
before these checks run (talk_mode.draft_problems), so only the text around them is read here.
"""

from __future__ import annotations

import re
import unicodedata

from core.answer_text import SENTENCE_BREAK

# A general money answer (#572) has no tool data, so it states no number of any kind: no digit (the validator's
# R1 check), and none of these either. "one" and "yksi" stay ("one way is to…"); every larger count, a share, a
# percentage and a Roman numeral is a figure the answer has no source for ("three months of costs", "VI months",
# "half your income", "kolme kuukautta").
_GENERAL_NUMBER_WORD = re.compile(
    r"\b(?:two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen"
    r"|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundreds?|thousands?|millions?"
    r"|billions?|dozens?|half|halves|quarters?|thirds?|fourths?|fifths?|tenths?|percent\w*|per\s+cent|percentage"
    # ordinals and multiples (review of #618): "a sixth", "the twelfth", "twice", "double", "tenfold"; never the idioms
    # "think twice" and "double-check"
    r"|sixths?|sevenths?|eighths?|ninths?|elevenths?|twelfths?|(?:thir|four|fif|six|seven|eigh|nine)teenths?"
    r"|twentieths?|thirtieths?|fortieths?|fiftieths?|hundredths?|thousandths?|(?<!think )twice|thrice"
    r"|double(?!-?check)\w*|triple\w*|quadruple\w*|(?:two|three|four|five|six|ten|hundred|thousand)fold"
    r"|kaksi|kahde\w*|kolme\w*|kolmen|neljä\w*|neljän|viisi|viide\w*|kuusi|kuude\w*|seitsemä\w*|kahdeksa\w*"
    r"|yhdeksä\w*|\w*kymmen\w*|\w+toista|sata\w*|sadan|tuha\w*|miljoon\w*|miljardi\w*|puolet|puolikas\w*|puoli"
    r"|neljännes\w*|kolmannes\w*|prosent\w*|tusina\w*|pari"
    # multiples and colloquial counts (review of #618, pass 3): "doubling", "treble", "tuplasti", "kaks", "viis"
    r"|doubl(?:ing|ed|es)|trebl\w*|tupla\w*|kaks|viis|tenner|fiver|nil"
    # "a couple of months", "a pair of", "puolen vuoden", "puoleen tuloista", "kolmas osa" (closing review of #618)
    r"|(?:a\s+)?couple\s+of|couple\s+(?:is|are|will|would|of|weeks?|months?|days?|years?)|a\s+pair\s+of|pairs\s+of"
    r"|puolen|puoleen|(?:kolmas|neljäs|viides|kymmenes)\s+osa\w*"
    # compounds ("kaksisataa", "viisituhatta"), shares ("kolmasosa") and multiples ("kaksinkertainen") (review of #618)
    r"|(?:kaksi|kolme|neljä|viisi|kuusi|seitsemän|kahdeksan|yhdeksän)(?:sata|tuhat)\w*"
    r"|(?:kolmas|neljäs|viides|kuudes|seitsemäs|kahdeksas|yhdeksäs|kymmenes|sadas)osa\w*"
    r"|(?:kaksin|kolmin|nelin|viisin|kuusin|kymmenen|sata|tuhat)kertai\w*)\b", re.I)
# A number word joined to the next word ("twentyfive", "threemonth", "fiftyfifty"): the long English number words with
# no word boundary after them (closing review of #618); the short ones (two, six, ten) keep it ("often", "tenant")
_NUMBER_PREFIX = re.compile(r"\b(?:three|four|five|seven|eight|nine|eleven|twelve|twenty|thirty|forty|fifty|sixty"
                            r"|seventy|eighty|ninety|hundred|thousand|million|billion|dozen)[a-z]", re.I)
# The same words hidden inside a run with the spaces and hyphens taken out ("tw enty", "T-W-E-N-T-Y"): only the long
# ones that are part of no ordinary word ("forty" and "eighty" are left out: "comfort you", "weighty")
_JOINED_NUMBER = re.compile(r"twenty|thirty|fifty|sixty|seventy|ninety|hundred|thousand|million|billion|percent"
                            r"|kymmen|prosent", re.I)
# Every Roman numeral (XVI, XXV, L, MM), case-sensitive, never the pronoun "I" (review of #618); in lowercase only the
# common ones of two letters or more made of i, v and x ("xii", "vi"), never an English word ("mix")
_ROMAN_NUMERAL = re.compile(r"\b(?!I\b)(?=[MDCLXVI]+\b)M{0,4}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3})\b"
                            r"|\b(?=[ivx]{2,}\b)x{0,3}(?:ix|iv|v?i{0,3})\b")
# A product, a bank or an investment in a general answer: no product is advised (#572 B5, B6; R7). An emergency or
# rainy-day fund is a buffer, not a product; "a share of your income" and "take stock" are plain words. "Your bank"
# stays: an e-invoice arrives in the online bank.
_GENERAL_PRODUCT = re.compile(
    r"\b(?:invest\w*|(?:index|mutual|investment|equity|bond|hedge|pension)\s+funds?|stock\s*markets?|stocks"
    r"|shares\s+in|equit(?:y|ies)|etfs?|bonds?|crypto\w*|bitcoin|sijoit\w*|rahasto\w*|osake\w*|krypto\w*"
    r"|joukkovelkakirj\w*|nordea|osuuspankki|danske|s-?pankki|s-?mobiili|handelsbanken|aktia|säästöpankki"
    r"|saastopankki|revolut|n26|holvi|klarna|apple\s*pay|google\s*pay|mobile\s*pay"
    # products described, not named (review of #618)
    r"|(?:high-interest\s+|high\s+interest\s+)?savings\s+accounts?|deposit\s+accounts?|(?:fixed|term|time)\s+deposits?"
    r"|money\s+market\w*|pension\s+(?:savings|plans?|insurance)|retirement\s+(?:accounts?|funds?|plans?)"
    r"|insurance\s+polic\w*|gold|real\s+estate|robo-?advis\w*|paypal|localtapiola|s-?bonus|netflix|spotify|viaplay"
    r"|säästötil\w*|saastotil\w*|talletu\w*|määräaikai\w*|kulta|kultaa|kullan|kultaan|eläkesäästö\w*"
    r"|eläkevakuutu\w*|sijoitusasun\w*"
    # banks, payment brands and apps by name, and an app at all (closing review of #618)
    r"|op-?ryhmä\w*|pop\s+pankki|oma\s+säästöpankki|ålandsbanken|alandsbanken|bank\s+norwegian|resurs|siirto|pivo"
    r"|mastercard|american\s+express|amex|nordnet|seligson|evli|mandatum|lähitapiola|lahitapiola|fennia"
    r"|apps?|sovellu\w*)\b|\bOP\b"
    # product stems anywhere in a word ("indeksirahasto", "osakesäästötili", "matkavakuutus")
    r"|\w*(?:rahasto|osake|osakk|sijoit|talletu|säästötil|saastotil|eläkesääst|elakesaast|vakuutu|joukkovelkakir"
    r"|krypto|crypto|bitcoin)\w*", re.I)
# Health in a general answer: health stays out (R9; #572). "A healthy buffer" and "financial health" are plain words.
_GENERAL_HEALTH = re.compile(
    r"(?<!financial )\bhealth\b|\bhealth\s*care\b|\b(?:medicine\w*|medication\w*|doctors?|pharmac\w*|therap\w*"
    r"|dentist\w*|hospital\w*|tervey\w*|lääk\w*|apteek\w*|hammaslääk\w*|terapi\w*|sairaala\w*"
    # mental health (review of #618); "that sounds stressful" is empathy, not advice, so stress itself stays
    r"|anxi\w*|meditat\w*|mental\w*|well-?being|addict\w*|treatment\w*|depress\w*|ahdistu\w*"
    r"|rentoutu\w*|mielenterve\w*|riippuvuu\w*|masennu\w*)\b", re.I)
# Other people's money in a general answer (R5; review of #618): "your partner's account", "lend money to your sister"
_GENERAL_OTHERS = re.compile(
    r"\b(?:partner|spouse|husband|wife|friend|neighbou?r|sister|brother|parent|colleague|cousin)s?'?s?\s+"
    r"(?:account|balance|spending|money|salary|income|earnings|card|bank)\w*|\blend\s+(?:some\s+)?money\b"
    r"|\bask\s+(?:a\s+|your\s+)?(?:friend|neighbou?r|colleague)\w*\s+what\s+they\s+(?:earn|spend|make)"
    r"|\bwhat\s+(?:your|the)\s+neighbou?r\w*\s+spend|\bnaapuri\w*|\b(?:puolisosi|ystäväsi|siskosi|veljesi|"
    r"kumppanisi)\s+(?:tili|saldo|palk|kulu|raha)\w*", re.I)
# A link, an address, a handle or a function name: an answer names none (#572 C4, C5; review of #618)
_GENERAL_LINK = re.compile(
    r"https?://|\bwww\.|\b[\w-]+\.(?:com|fi|org|net|io|xyz|ly|co|app|info|biz|eu|se|de|uk|me|ai)\b(?:/\S*)?"
    r"|\b[\w.+-]+@[\w-]+\.\w+|(?<![\w.])@\w+|\b[a-z]+_[a-z_]+\b|\b[a-z]+[A-Z][A-Za-z]+\b"
    r"|\bget\s+safe\s+to\s+spend\b|\banswer\s+in\s+words\b")
# Judging the user or joking about their spending (#572 E1, E2): "bad with money", "irresponsible", "haha", an emoji.
# "No need to feel ashamed" and "vältä tuhlaamasta ruokaa" are plain words (review of #618).
_GENERAL_JUDGING = re.compile(
    r"\b(?:bad|terrible|awful|hopeless|useless)\s+(?:with|at)\s+(?:money|saving|budget\w*|managing\b[\w\s]*)\b"
    r"|\birresponsib\w*|\blazy\b|\bstupid\w*|\bfoolish\w*|\bdumb\b|\bcareless\w*|\breckless\w*|\bwasteful\w*"
    r"|\bwaste\w*\s+(?:your\s+)?money\b|\bspendthrift\w*|\bwallet\s+is\s+crying|\bclowns?\b|\bhilarious\b"
    r"|\bha(?:ha)+\b|\blol\b|\broast\w*|\bshame\s+on\s+you\b"
    r"|\bhuono\w*\s+rahan|\btuhlaat\b|\btuhlari\w*|\btuhlaavai\w*|\btuhlaajat?\b|\btyhm\w*|\btyper\w*|\bholtito\w*"
    r"|\blaiska\w*|\bvastuuto\w*|\bnolo\w*|[\U0001F300-\U0001FAFF\u2600-\u27BF]", re.I)
# Borrowing in any form in a general answer, and in the question that may take the general route (#572 B3, B7, D8;
# review of #618): never a suggestion and never a mention ("Take a car loan.", "A payday lender can bridge the gap",
# "Pikavippi auttaa palkkaan asti", "Osamaksu jakaa kulun", "Käytä tilinylitysoikeutta").
# The stems match anywhere in a word ("pikalaina", "opintolaina", "tililuotto", "korttivelka", "rahoitus"), and a mention
# is rejected even when negated ("Avoid relying on borrowing"): the coordinator's default (closing review of #618).
# "Debt" is borrowing too, so English and Finnish are alike ("velka" was rejected, "debt" was not).
GENERAL_BORROWING = re.compile(
    r"\w*(?:loan|credit|overdraft|borrow|instal{1,2}ment|mortgag|debt|bnpl)\w*|\bfinanc(?:ing|ed)\b"
    r"|\blend(?:er|ers|ing|s)?\b|\b(?:payday|cash|salary|pay|paycheck|wage)\s+advances?\b"
    r"|\badvance\s+on\s+(?:your|my|the)\s+(?:pay|salary|paycheck|wages?)\b|\bbuy\s+now,?\s+pay\s+later\b"
    r"|\w*(?:laina|lainoj|luotto|luoto|luoton|velka|velan|velat|velko|vippi|vipin|vipp|rahoitu|osamaks|tilinylit)\w*"
    r"|\bmaksa\s+myöhemmin\b", re.I)

# ---- The output side as classes (review of #618, pass 3): positive checks on the draft and its folded copies --------
# Borrowing as a class, beyond the stems above: paying or settling later or bit by bit, a purchase split into payments,
# an account in the red or below zero, an advance, a pawn shop, a tab, money asked from someone until payday, what one
# owes; Finnish maksa myöhemmin / vasta, erissä / erään, miinukselle, pakkaselle, ennakko, pantti, maksuaika. Accents
# are folded in one copy, so the Finnish forms are written without them. Draft side only: the question gate keeps
# GENERAL_BORROWING.
_GENERAL_BORROWING_CLASS = re.compile(
    r"\b(?:pay|settle|sort|deal|cover|repay|clear|handle|hoida|maksa|kuittaa|suorita)\w*(?:\s+\w+){0,3}?\s+(?:later"
    r"|next\s+(?:week|month|year|payday)|afterwards|over\s+time|bit\s+by\s+bit|slowly|in\s+(?:parts|pieces|chunks"
    r"|stages|portions|instal\w*)|myohemmin|ensi\s+(?:kuussa|viikolla)|jalkikateen|perasta|osissa)\b"
    r"|\bbuy(?:ing)?[\s-]+(?:it\s+)?now\b|\bpay(?:ing)?\s+(?:it\s+|them\s+)?(?:later|off)\b|\brepay\w*|\bdefer\w*"
    r"|\b(?:split|spread|divide|break)\w*(?:\s+\w+){0,3}?\s+(?:into|over|across)(?:\s+\w+){0,2}?\s+(?:payments?"
    r"|instal\w*|parts|pieces|chunks|months|portions)\b|\b(?:monthly|several|multiple|smaller|equal)\s+(?:payments"
    r"|instal\w*)\b|\bin(?:to)?\s+the\s+red\b|\boverdr[ae]w\w*|\bbelow\s+zero\b|\bnegative\s+balance\b"
    r"|\b(?:an?|the|cash|salary|pay|payday|wage)\s+advances?\b|\badvance\s+on\b|\bpawn\w*|\bquick\s+cash\b"
    r"|\bfast\s+cash\b|\b(?:a|the|your)\s+tab\b|\brun\s+up\b|\bfront\s+you\b|\b(?:owe|owed|owing|iou)\b"
    r"|\bconsolidat\w*|\broll\w*(?:\s+\w+){0,2}?\s+over\b"
    r"|\b(?:ask|beg)\w*(?:\s+\w+){0,3}?\s+(?:for\s+)?(?:some\s+|a\s+bit\s+of\s+|a\s+little\s+)?(?:money|cash|funds"
    r"|help)\b|\bpyyda\w*(?:\s+\w+){0,2}?\s+rahaa\b"
    r"|\b(?:erissa|eraan|erina|eriin|kuukausierissa|kuukausieriin)\b|\bmiinukse\w*|\bpakkase(?:lle|lla)\b"
    r"|\w*ennakko(?:a|ja|n|t|na|sta|lla|lle)?\b|\bpant(?:ti|ata|taa|taamalla)\w*|\bmaksua(?:ika|ikaa|jan|jalla)\w*"
    r"|\bviivekor\w*|\w*ylitysoik\w*", re.I)
# A financial product recommended without a name: interest or yield, or a verb of getting or using one with a product
# noun ("Open an account that pays more.", "Get travel insurance.", "Try online banking.", "Avaa korkeakorkoinen
# tili.", "Käytä verkkopankkia."). Keeping money in an account is a habit, so "keep" and "siirrä" are no such verb.
_GENERAL_PRODUCT_CLASS = re.compile(
    r"\binterest\b(?!\s+in\b)|\bhigh[\s-]*(?:interest|yield)\w*|\bkorko\w*|\w*korkoi\w*|\bindex\s+\w+"
    r"|\b(?:savings|pension)\s+plans?\b|\bdividend\w*"
    r"|\b(?:open|get|take\s+out|sign\s+up\s+for|apply\s+for|switch\s+to|buy|use|try|choose|pick|consider"
    r"|look\s+into|download|install|set\s+up)\b(?:\s+[\w-]+){0,4}?\s+(?:accounts?|cards?|insurance|polic(?:y|ies)"
    r"|wallets?|stocks?|shares|propert(?:y|ies)|funds?|apps?|applications?|banking|deposits?)\b"
    r"|\b(?:avaa|hanki|ota|vaihda|valitse|kayta|lataa|asenna|osta|harkitse)\w*(?:\s+\w+){0,3}?\s+\w*(?:tili|tilin"
    r"|tilia|kortti|kortin|korttia|vakuutu\w*|sovellu\w*|osake\w*|osakke\w*|asunto\w*|lompako\w*|pankki\w*"
    r"|mobiilimaksu\w*)\b|\w*sovellu\w*", re.I)
# A brand or a shop written in lowercase, or at the start of a sentence, where the proper-noun check cannot see it
_GENERAL_BRAND = re.compile(
    r"\b(?:wolt|lidl|amazon|visa|monzo|swedbank|seb|prisma|k-?market|k-?ruoka|k-?citymarket|s-?market|alepa|tokmanni"
    r"|ikea|zalando|foodora|ebay|etsy|temu|shein)\b", re.I)
# Proper nouns: a capitalised word that does not start a sentence, or a word with a capital after its first letter,
# names a bank, a brand, a shop or a product; only these may stand in a general answer (and the pronoun "I", and the
# names of the two languages and the country: "In Finnish, a budget is called budjetti.").
_PROPER_NOUN_ALLOWED = re.compile(r"(?:I(?:['’](?:m|ll|ve|d))?|Sentt?i\w*|S-[Pp]ank\w*|S-mobiil\w*|English|Finnish"
                                  r"|Finland|Finns?|Suom\w*)")
_WORD = re.compile(r"[^\W\d_]+(?:[-'’][^\W\d_]+)*")


def _proper_nouns(text: str) -> list[str]:
    """The capitalised words of a draft that are not sentence-initial, and any word with a capital after its first
    letter ("SEB", "iPhone", "MobilePay"), except the allowed names (review of #618, pass 3)."""
    found = []
    for sentence in SENTENCE_BREAK.split(text):
        words = _WORD.findall(sentence)
        for i, word in enumerate(words):
            if _PROPER_NOUN_ALLOWED.fullmatch(word):
                continue
            inner_capital = any(ch.isupper() for ch in word[1:].replace("-", ""))
            if inner_capital or (i > 0 and word[0].isupper()):
                found.append(word)
    return found


# A statement about the user's own money: the general route reads no data, so it never asserts the user's state
# ("You are saving enough.", "Your buffer is fine.", "You can afford it.", "Puskurisi on kunnossa.", "Sinulla on varaa
# tähän."). Second person as the subject of a main clause with a state, a sufficiency or a judgement; "if you are
# unsure", "when you're ready", "kun säästät" and "jos sinulla on" are conditions, not claims.
_NOT_A_CLAIM = (r"(?<!\bif )(?<!\bwhen )(?<!\bwhenever )(?<!\bwhether )(?<!\bunless )(?<!\bwhile )(?<!\bonce )"
                r"(?<!\buntil )(?<!\bso )(?<!\bthat )(?<!\bcase )(?<!\blong as )(?<!\bbefore )(?<!\bafter )"
                r"(?<!\bwhat )(?<!\bhow )(?<!\bhow much )(?<!\bkun )(?<!\bjos )(?<!\bjotta )")
_GENERAL_OWN_STATE = re.compile(
    _NOT_A_CLAIM + r"\byou(?:['’]re|\s+are|\s+were|['’]ve\s+been|\s+have\s+been)\b(?!\s+not\s+alone\b)"
    r"|" + _NOT_A_CLAIM + r"\byou(?:\s+\w+)?(?:\s+have|['’]ve|\s+got)\s+(?!to\b)(?:\w+\s+){0,2}?(?:enough|plenty"
    r"|a\s+healthy|a\s+good|a\s+solid|a\s+big|room|too|more\s+than|saved|spent|done|covered)\b"
    r"|" + _NOT_A_CLAIM + r"\byou\s+(?:can|could|can['’]t|cannot)\s+(?:\w+\s+)?afford\b"
    r"|\byou\s+(?:\w+\s+)?(?:spend|earn|save|owe|make|pay|manage)\w*\s+(?:\w+\s+){0,2}?(?:too|enough|well|a\s+lot"
    r"|more\s+than|less\s+than|plenty|little|fine|great)\b"
    r"|" + _NOT_A_CLAIM + r"\byou\s+(?:should|need\s+to|must|ought\s+to|have\s+to|can|could)\s+(?:\w+\s+)?"
    r"(?:save|spend|cut|earn)\s+"
    r"(?:\w+\s+)?(?:more|less|back|down)\b"
    r"|\byou\s+(?:don['’]t|do\s+not|won['’]t|will\s+not)\s+need\s+(?:a\s+|any\s+)?(?:bigger|larger|smaller|more"
    r"|less|extra)\b"
    r"|(?:\b(?:based\s+on|given|judging\s+by|looking\s+at)|(?:^|(?<=[.!?] ))with)\s+your\s+(?:own\s+)?(?:income"
    r"|spending|salary|savings|buffer|budget|situation|money|finances|bills|expenses|balance|habits|earnings)\b"
    # "your buffer is fine", never the embedded question "how steady your income is" or "how your spending looks"
    r"|(?<!\bhow )(?<!\bwhere )(?<!\bwhat )(?<!\bwhether )(?<!\bif )\byours?\b(?:\s+(?:own|current|monthly|total"
    r"|overall|food|grocery|emergency|regular|present))*\s+(?:buffer|savings?|spending|money|finances|balance|income"
    r"|salary|budget|bills|expenses|costs|situation|account|habits|cash|wallet|fund|position|cushion|earnings)"
    r"(?:\s+(?:on|for)\s+\w+)?\s+(?:is|are|was|were|looks?|seems?|sounds?|appears?|feels?|isn['’]t|aren['’]t|covers?"
    r"|should\s+(?:cover|be\s+(?:enough|fine|ok|okay|big|large|sufficient))|will\s+(?:cover|be)|can\s+cover)\b"
    r"(?=\s+\w)|\byours\s+(?:is|are|looks?|seems?|should)\b"
    r"|\b(?:people|others|someone|anyone)\s+(?:in\s+your\s+(?:situation|position|shoes)|like\s+you)\b"
    # Finnish, accents folded: säästät / kulutat ... tarpeeksi / liikaa, "puskurisi on", "sinulla on", "olet"
    r"|" + _NOT_A_CLAIM + r"\b(?:saastat|kulutat|kaytat|tienaat|ansaitset|maksat|tuhlaat|parjaat|et\s+(?:saasta"
    r"|kuluta|kayta|tienaa|ansaitse|maksa|parjaa))\b(?:\s+\w+){0,3}?\s+(?:jo\s+)?(?:tarpeeksi|riittavasti|liikaa"
    r"|liian|hyvin|paljon|vahan|enemman|vahemman|kuin)\b"
    r"|\b(?:puskuri|saasto|raha|tili|saldo|tulo|meno|kulu|kulutukse|taloute|tilantee|budjetti|palkka|lasku"
    r"|varallisuute)\w*si\s+(?:\w+\s+)?(?:on|ovat|oli|olivat|nayttaa|nayttavat|vaikuttaa|vaikuttavat|riittaa"
    r"|riittavat|kattaa|kattavat)\b"
    r"|" + _NOT_A_CLAIM + r"\bsinulla\s+(?:on|oli|ei\s+ole)\b"
    r"|\bsinun\s+(?:pitaisi|kannattaisi|tulisi|taytyy|pitaa)\s+(?:\w+\s+)?(?:saastaa|kuluttaa|kayttaa|vahentaa)"
    r"(?:\s+\w+)?\s+(?:enemman|vahemman)\b"
    r"|" + _NOT_A_CLAIM + r"\bolet\b", re.I)
# A draft that says it could not work the question out (composer.md's line for empty <data>) is no answer in words
GENERAL_NON_ANSWER = re.compile(
    r"\bI\s+(?:could\s*not|couldn['’]t|cannot|can['’]t|can\s+not|was\s+unable\s+to|am\s+unable\s+to"
    r"|wasn['’]t\s+able\s+to|don['’]t\s+have|do\s+not\s+have)\b|\bunable\s+to\s+(?:work|figure|calculat|comput"
    r"|answer)\w*|\ben\s+(?:pystynyt|pysty|voinut|voi|osannut|osaa|onnistunut|loytanyt)\b"
    r"|\bei\s+(?:onnistunut|voitu|loytynyt)\b", re.I)
# The language of a general answer (reviews of #618): a positive check, so a language nobody listed is caught too.
# Every letter is of the asked language's alphabet (English: a to z, é; Finnish: a to z, å, ä, ö, é), every sentence
# reads as that language (an English one has an English word, a Finnish one a Finnish word or ending), and no sentence
# carries the other language ("Kannattaa pitää budjetti, to be safe."). The list of other languages' words stays as
# one more signal.
_LETTERS = {"en": set("abcdefghijklmnopqrstuvwxyzé"), "fi": set("abcdefghijklmnopqrstuvwxyzåäöé")}
_ENGLISH_COMMON = re.compile(
    r"\b(?:the|a|an|is|are|was|be|been|to|of|and|or|in|on|at|by|for|with|from|as|it|its|you|your|yours|this|that"
    r"|these|those|they|them|their|we|our|can|could|will|would|should|may|might|do|does|did|not|no|if|so|than|then"
    r"|when|what|how|why|which|who|more|less|most|some|any|each|every|all|one|first|next|also|just|only|before|after"
    r"|until|while|because|keep|set|plan|save|saving|savings|spend|spending|start|try|make|check|pay|put|move|use|track"
    r"|write|pick|choose|wait|think|look|build|cut|avoid|stop|aim|review|list|note|small|little|good|money|budget"
    r"|buffer|bill|bills|payday|habit|habits|month|week|day|costs?|regular|easier|easy|help|helps|many|people)\b", re.I)
_FINNISH_COMMON = re.compile(
    r"[äöÄÖ]|\b(?:ja|ei|että|kun|jos|tai|voit|voi|joka|jotka|mutta|sinun|kannattaa|rahaa|raha|kuin|myös|ennen|sitä"
    r"|siitä|tämä|tuo|niin|aina|kaikki|ovat|olla|on|se|ne|sen|sinä|sinulla|tee|pidä|aloita|siirrä|seuraa|katso"
    r"|valitse|odota|mieti|säästä|saasta|budjetti|puskuri|lasku|laskut|kuukausi|viikko|päivä|paiva|hyvä|hyva|pieni"
    r"|helpompi|helppo|moni|monet|usein|ensin|sitten|jo|vasta|vain|eri|oma|omat)\b", re.I)
_OTHER_LANGUAGE = re.compile(
    r"\b(?:och|att|är|för|inte|eller|också|månad\w*|pengar|utgifter|spara|ditt|dina|två|tre"
    r"|und|nicht|ist|das|ein|eine|oder|auch|monat\w*|geld|sparen|ausgaben|ihr\w*|dein\w*|zwei|drei"
    r"|los|las|que|meses|dinero|gastos|ahorr\w*|tus|una|por|pero|tres"
    r"|les|des|est|pas|mois|argent|dépenses|gardez|épargn\w*|vous|votre|une|pour|avec|deux|trois)\b", re.I)
_FINNISH_WORD = re.compile(r"[äöÄÖ]|\b(?:ja|ei|että|kun|jos|tai|voit|voi|joka|mutta|sinun|kannattaa|rahaa|kuin|myös"
                           r"|ennen|sitä|siitä|tämä|niin|aina|kaikki|ovat|olla)\b", re.I)
_ENGLISH_WORD = re.compile(r"\b(?:the|a|an|is|are|you|your|and|of|to|it|for|with|this|that|be|can|before|money)\b",
                           re.I)
# A Finnish word by its ending, for a Finnish sentence with no Finnish letter ("Budjetti on suunnitelma.")
_FINNISH_ENDING = re.compile(r"\b\w{3,}(?:tti|ssa|ssä|sta|stä|lla|llä|lta|ltä|ksi|nen|aan|ään|uu|yy)\b", re.I)
# On the Finnish side only (review of #618, pass 3): the clitics -kin / -kaan and the verb endings -aa / -ää / -vat
_FINNISH_ENDING_WIDE = re.compile(r"\b\w{3,}(?:kin|kaan|kään|aa|ää|vat|vät)\b", re.I)


def general_language_problems(text: str, language: str) -> list[str]:
    """A general answer in another language than the one asked, or in two (reviews of #618); [] when none."""
    name = "Finnish" if language == "fi" else "English"
    allowed = _LETTERS.get(language, _LETTERS["en"])
    problems = []
    foreign = sorted({ch for ch in TOKEN_TEXT.sub(" ", text).lower() if ch.isalpha() and ch not in allowed})
    if foreign:
        problems.append(f"'{''.join(foreign)[:10]}': a letter outside {name}; answer only in {name}")
    m = _OTHER_LANGUAGE.search(text)
    if m:
        problems.append(f"'{m.group(0)}': a word of another language; answer only in {name}")
    for sentence in (s for s in SENTENCE_BREAK.split(TOKEN_TEXT.sub(" ", text)) if s.strip()):
        english = len(_ENGLISH_WORD.findall(sentence))
        if language == "en":
            finnish = _FINNISH_WORD.search(sentence) or (_FINNISH_ENDING.search(sentence)
                                                         and not _ENGLISH_WORD.search(sentence))
            if finnish or not _ENGLISH_COMMON.search(sentence):
                problems.append(f"'{sentence.strip()[:40]}': not an English sentence; answer only in English")
                break
        else:
            if english >= 2 or not (_FINNISH_COMMON.search(sentence) or _FINNISH_ENDING.search(sentence)
                                    or _FINNISH_ENDING_WIDE.search(sentence)):
                problems.append(f"'{sentence.strip()[:40]}': not a Finnish sentence; answer only in Finnish")
                break
    return problems


TOKEN_TEXT = re.compile(r"\{\{n\d+\}\}")


def _general_copies(text: str) -> list[str]:
    """The text and the copies every general check also reads (closing review of #618): compatibility forms folded
    (fullwidth, mathematical letters), accents and format characters removed ("fïve"), hyphens, dots and apostrophes
    inside a word removed ("tw-enty", "f.i.v.e"), and runs of single letters joined ("T W E N T Y", "p e r c e n t")."""
    nfkc = unicodedata.normalize("NFKC", text)
    bare = "".join(ch for ch in unicodedata.normalize("NFKD", nfkc) if unicodedata.category(ch) not in ("Mn", "Me", "Cf"))
    inside = re.sub(r"(?<=\w)[-.'’·](?=\w)", "", bare)
    letters = re.sub(r"\b(?:\w[\s.\-]+){2,}\w\b", lambda m: re.sub(r"[\s.\-]+", "", m.group(0)), inside)
    return list(dict.fromkeys([text, nfkc, bare, inside, letters]))


def general_problems(text: str) -> list[str]:
    """What a general money answer (#572) must not contain, as retry reasons; [] when nothing. Every pattern reads the
    text and its folded copies (_general_copies); the digit check, the borrowing check and the other text rules run on
    it as on any model text."""
    problems = []
    copies = _general_copies(text)
    joined = re.sub(r"[\W_]+", "", copies[-1])   # all spaces and marks out, for the long number words only
    m = _JOINED_NUMBER.search(joined)
    if m and not any(_JOINED_NUMBER.search(c) for c in copies):
        problems.append(f"'{m.group(0)}': a number word split apart: a general answer states no number of any kind")
    for rx, why in ((_GENERAL_NUMBER_WORD, "a number word: a general answer states no number of any kind"),
                    (_NUMBER_PREFIX, "a number word: a general answer states no number of any kind"),
                    (_ROMAN_NUMERAL, "a Roman numeral: a general answer states no number of any kind"),
                    (_GENERAL_PRODUCT, "a product, bank or investment: a general answer names none"),
                    (_GENERAL_HEALTH, "health: a general answer gives no health advice"),
                    (_GENERAL_OTHERS, "other people's money: a general answer is about the user only"),
                    (_GENERAL_LINK, "a link, an address or a function name: a general answer names none"),
                    (GENERAL_BORROWING, "borrowing: a general answer never mentions a loan, credit or any "
                                        "borrowing"),
                    (_GENERAL_JUDGING, "judging or joking: a general answer never judges the user or jokes "
                                       "about spending"),
                    (_GENERAL_BORROWING_CLASS, "borrowing: a general answer never suggests paying later, in parts, "
                                               "in the red, with an advance or with someone else's money"),
                    (_GENERAL_PRODUCT_CLASS, "a financial product: a general answer recommends no account, card, "
                                             "insurance, app, interest or investment"),
                    (_GENERAL_BRAND, "a brand or a shop: a general answer names none"),
                    (_GENERAL_OWN_STATE, "the user's own money: a general answer reads no data, so it never says "
                                         "how the user is doing, what they can afford or what their money is")):
        m = next((found for found in (rx.search(c) for c in copies) if found), None)
        if m:
            problems.append(f"'{m.group(0)}': {why}")
    names = next((found for found in (_proper_nouns(c) for c in copies[:2]) if found), None)
    if names:
        # S-Pankki and S-mobiili pass this name check, but the product list above still rejects them in a general
        # answer (red-team row B, "Use the S-mobiili savings goal for it."), so the reason names Sentti only
        problems.append(f"'{names[0]}': a name: a general answer names no bank, brand, shop or product (Sentti is "
                        f"the only name it uses)")
    return problems
