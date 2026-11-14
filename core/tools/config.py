"""The one config file of the tools: categories, flows, MCC groups, method ids and labels.

Sources (also listed in the PR of issue #31):
- Categories and flows: docs/design/metrics.md section 0; income = Salary + Other Income (metrics.md
  section 2.3: Invest Withdraw is the customer's own saving coming back, so it is not income).
- MCC groups taxi, public_transport, fuel, parking: the shared classification block of
  core/metrics/02_baskets.sql (identical in 02-06) and metrics.md section 1, rules 4 and 6.
- MCC groups groceries, restaurants, health, electronics_home: not listed in metrics; each is every
  MCC that occurs under that category on the sample CUST00000-CUST00099 up to 2026-09-30
  (every MCC in the data occurs under exactly one category).
- Method ids: contracts/api.md 0.1.1 and agent-core.md section 6.2 (`spending.*`, `evidence.*`).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

# First day of the dataset. Periods are clamped to [DATA_START, as_of] (agent-core.md section 4).
DATA_START = date(2024, 10, 1)

DEFAULT_AS_OF = date(2026, 9, 30)  # DEMO_TODAY default (contracts/api.md section 1)

CATEGORIES: tuple[str, ...] = (
    "Groceries", "Restaurants", "Transportation", "Utilities", "Entertainment",
    "Health", "Home & Tech", "Housing", "Lifestyle", "Travel",
    "Salary", "Other Income", "Invest Withdraw", "Invest Deposit", "Salary Sweep",
)

# Flows (metrics.md section 0). Spending is every category that is not in another flow.
INCOME_CATEGORIES = frozenset({"Salary", "Other Income"})
OWN_SAVINGS_BACK_CATEGORIES = frozenset({"Invest Withdraw"})  # money in, but not income
SAVING_CATEGORIES = frozenset({"Invest Deposit"})
TRANSFER_CATEGORIES = frozenset({"Salary Sweep"})
NON_SPEND_CATEGORIES = INCOME_CATEGORIES | OWN_SAVINGS_BACK_CATEGORIES | SAVING_CATEGORIES | TRANSFER_CATEGORIES
SPEND_CATEGORIES = frozenset(c for c in CATEGORIES if c not in NON_SPEND_CATEGORIES)

# Which categories a caller may name for each direction. Without named categories, "out" means
# the spend flow and "in" means income.
OUT_CATEGORIES = SPEND_CATEGORIES | SAVING_CATEGORIES | TRANSFER_CATEGORIES
IN_CATEGORIES = INCOME_CATEGORIES | OWN_SAVINGS_BACK_CATEGORIES

BASKETS: tuple[str, ...] = ("regular_essentials", "unexpected_necessities", "everyday_spending")

MCC_GROUPS: dict[str, tuple[str, ...]] = {
    "groceries": ("5411", "5422", "5451", "5499"),          # sample: category Groceries
    "restaurants": ("5812", "5813", "5814"),                # sample: category Restaurants
    "taxi": ("4121",),                                      # 02_baskets.sql rule 4
    "public_transport": ("4111",),                          # metrics.md section 1, rule 6
    "fuel": ("5541", "5542"),                               # metrics.md section 1, rule 6
    "parking": ("7523",),                                   # metrics.md section 1, rule 6
    "health": ("5912", "8011", "8021", "8099"),             # sample: category Health
    "electronics_home": ("5200", "5251", "5712", "5732", "5734"),  # sample: category Home & Tech
}
MCC_TO_GROUP: dict[str, str] = {mcc: group for group, codes in MCC_GROUPS.items() for mcc in codes}

# Classification constants (metrics.md sections 0 and 1, 02_baskets.sql).
ONE_OFF_FACTOR = 5          # a purchase > 5x the category median of the last 365 days
ONE_OFF_MIN_PURCHASES = 8   # needs at least 8 purchases in that category in those 365 days
WINDOW_MONTHS = 6           # "last 6 complete calendar months"
SUBSCRIPTION_MIN_MONTHS = 4
SUBSCRIPTION_MAX_CV = 0.10

METHODS = {
    "total": "spending.total@1",
    "n_tx": "spending.n_tx@1",
    "change": "spending.change@1",
    "change_pct": "spending.change_pct@1",
    "share_pct": "spending.share_pct@1",
    "row_count": "evidence.row_count@1",
    # get_basket_breakdown (metrics.md section 1, 02_baskets.sql; total from 05_spender_profile.sql)
    "basket_total": "baskets.total_eur@1",
    "basket_month_avg": "baskets.month_avg_eur@1",
    "basket_share": "baskets.share_pct@1",
    "spend_month": "spender_profile.spend_month_eur@1",
    # get_recurring_bills (metrics.md sections 2 and 3, 01_recurring.sql, 03_safe_to_spend.sql)
    "typical_month": "recurring.typical_month_eur@1",
    "bill_due": "safe_to_spend.bill_due_eur@1",
    "bills_due": "safe_to_spend.bills_due_eur@1",
    # get_peer_benchmark (metrics.md section 6, 06_peer_benchmark.sql): the customer's own value
    "peer_you": "peer_benchmark.you_month_eur@1",
    # get_balance_forecast (#257, metrics.md section 3.3)
    "daily_pace": "balance_forecast.daily_pace_eur@1",
    "bills_to_date": "balance_forecast.bills_to_date_eur@1",
    # get_small_purchases (#256; metrics.md section 12, 08_small_purchases.sql: the output columns)
    "small_count": "small_purchases.count@1",
    "small_total": "small_purchases.total_eur@1",
    "small_avg": "small_purchases.avg_eur@1",
    "small_share": "small_purchases.share_pct@1",
    "small_flexible": "small_purchases.flexible_total_eur@1",
    "small_max": "small_purchases.max_amount_eur@1",
    "small_month_avg": "small_purchases.month_avg_eur@1",
}

# ---- labels (en, fi) ------------------------------------------------------------------------------

CATEGORY_LABELS: dict[str, tuple[str, str]] = {
    "Groceries": ("Groceries", "Ruokaostokset"),
    "Restaurants": ("Restaurants", "Ravintolat"),
    "Transportation": ("Transportation", "Liikkuminen"),
    "Utilities": ("Utilities", "Kodin laskut"),
    "Entertainment": ("Entertainment", "Viihde"),
    "Health": ("Health", "Terveys"),
    "Home & Tech": ("Home & Tech", "Koti ja tekniikka"),
    "Housing": ("Housing", "Asuminen"),
    "Lifestyle": ("Lifestyle", "Ostokset ja vapaa-aika"),
    "Travel": ("Travel", "Matkailu"),
    "Salary": ("Salary", "Palkka"),
    "Other Income": ("Other income", "Muut tulot"),
    "Invest Withdraw": ("Investment withdrawals", "Sijoitusten nostot"),
    "Invest Deposit": ("Investment deposits", "Sijoitukset"),
    "Salary Sweep": ("Salary sweep", "Palkan siirto"),
}

BASKET_LABELS: dict[str, tuple[str, str]] = {
    "regular_essentials": ("Regular essentials", "Säännölliset välttämättömät"),
    "unexpected_necessities": ("Unexpected necessities", "Odottamattomat välttämättömät"),
    "everyday_spending": ("Everyday spending", "Arjen kulutus"),
    # A purchase whose spike review is pending (contract 0.2.0, #68). The rules alone put no purchase of
    # the dataset's categories here.
    "unclassified": ("Waiting for your answer", "Odottaa vastaustasi"),
}

MCC_GROUP_LABELS: dict[str, tuple[str, str]] = {
    "groceries": ("Groceries", "Ruokaostokset"),
    "restaurants": ("Restaurants", "Ravintolat"),
    "taxi": ("Taxi", "Taksi"),
    "public_transport": ("Public transport", "Joukkoliikenne"),
    "fuel": ("Fuel", "Polttoaine"),
    "parking": ("Parking", "Pysäköinti"),
    "health": ("Health", "Terveys"),
    "electronics_home": ("Electronics and home", "Elektroniikka ja koti"),
    "other": ("Other", "Muut"),
}

# Merchant kinds for alias labels ("Grocery store A"). MCC first, then category. No digits.
MERCHANT_KIND_BY_MCC: dict[str, tuple[str, str]] = {
    "4121": ("Taxi", "Taksi"),
    "4111": ("Public transport", "Joukkoliikenne"),
    "5541": ("Fuel station", "Huoltoasema"),
    "5542": ("Fuel station", "Huoltoasema"),
    "7523": ("Parking", "Pysäköinti"),
    "7011": ("Hotel", "Hotelli"),
    "4511": ("Airline", "Lentoyhtiö"),
    "4722": ("Travel agency", "Matkatoimisto"),
    "7512": ("Car rental", "Autovuokraamo"),
}
MERCHANT_KIND_BY_CATEGORY: dict[str, tuple[str, str]] = {
    "Groceries": ("Grocery store", "Ruokakauppa"),
    "Restaurants": ("Restaurant", "Ravintola"),
    "Transportation": ("Transport", "Liikenne"),
    "Health": ("Health service", "Terveyspalvelu"),   # neutral wording (R9)
    "Home & Tech": ("Home and tech store", "Kodin ja tekniikan kauppa"),
    "Lifestyle": ("Shop", "Kauppa"),
    "Entertainment": ("Entertainment", "Viihde"),
    "Travel": ("Travel", "Matkailu"),
}
MERCHANT_KIND_DEFAULT = ("Merchant", "Kauppias")

FILTER_LABEL_CAP = 5   # parts of one dimension from which a filter label counts them (#501)
TEXT: dict[str, tuple[str, str]] = {
    "spending": ("Spending", "Kulutus"),
    "income": ("Income", "Tulot"),
    # a merchant-filtered sum in the evidence view, which cannot name the merchant's alias (#399)
    "spending_merchant": ("Spending at the chosen merchant", "Kulutus valitulla kauppiaalla"),
    # a filter of FILTER_LABEL_CAP or more parts in one dimension is counted, not listed (#501)
    "filter_many": ("Spending in {what}", "Kulutus {what}"),
    "filter_many_categories": ("several categories", "useassa luokassa"),
    "filter_many_mcc_groups": ("several groups", "useassa ryhmässä"),
    "filter_many_baskets": ("several baskets", "useassa korissa"),
    # across dimensions the selection is an intersection (core/tools/selection.py): a basket "within" (English),
    # the other parts in brackets (Finnish, no agreement to get wrong), a merchant "at" (#501, review of #528)
    "filter_within": (" within ", ""),
    "filter_at": (" at ", " kauppiaalla "),
    "filter_at_unnamed": (" at the chosen merchant", " valitulla kauppiaalla"),   # the evidence view, no alias
    "transactions": ("Transactions", "Tapahtumat"),
    "share": ("Share of total", "Osuus kokonaisuudesta"),
    "change_vs": ("Change vs {label}", "Muutos verrattuna: {label}"),
    "vs": ("vs {label}", "verrattuna: {label}"),
    "everything_else": ("Everything else", "Kaikki muu"),
    "no_merchant": ("Payments without a merchant", "Maksut ilman kauppiasta"),
    "no_mcc_group": ("Other", "Muut"),
    "note_clamped": (
        "The period was limited to the data available: {label}.",
        "Jakso rajattiin saatavilla olevaan dataan: {label}.",
    ),
    "note_empty": ("No transactions in this period.", "Ei tapahtumia tällä jaksolla."),
    "note_typical": (
        "A comparison with a typical period is not defined yet, so none is shown.",
        "Vertailua tyypilliseen jaksoon ei ole vielä määritelty, joten sitä ei näytetä.",
    ),
    "note_no_baseline": (
        "No comparison: the earlier period starts before the data ({start}).",
        "Ei vertailua: aiempi jakso alkaa ennen datan alkua ({start}).",
    ),
}


def label(pair: tuple[str, str], language: str) -> str:
    """Pick the English or Finnish label."""
    return pair[1] if language == "fi" else pair[0]


# ---- get_basket_breakdown and get_recurring_bills (#46) -------------------------------------------

# Labels of non-card recurring series (tx_type keys, metrics.md section 2). Card series use aliases.
SERIES_LABELS: dict[str, tuple[str, str]] = {
    "housing_payment": ("Housing", "Asuminen"),
    "utilities_payment": ("Utilities", "Kodin laskut"),
    "investment_deposit": ("Investment deposit", "Sijoitus"),
    "investment_withdrawal": ("Investment withdrawal", "Sijoitusten nosto"),
    "salary": ("Salary", "Palkka"),
    "other_income": ("Other income", "Muut tulot"),
    "salary_sweep": ("Salary sweep", "Palkan siirto"),
}

# ---- the bill explanation (#242, contracts/api.md section 11) ----------------------------------------
# Known payee names of each kind of recurring bill, matched exactly after normalisation (case, spaces and
# punctuation ignored), like the bills' labels. A real bank knows the counterparty of earlier payments;
# the synthetic dataset has none, so this table stands in for that history in the demo. Fictional
# companies only; the sample bills (#249) use the same strings.
PAYEE_ALIASES: dict[str, tuple[str, ...]] = {
    "housing_payment": ("Esimerkki Asunnot Oy",),
    "utilities_payment": ("Esimerkki Energia Oy", "Esimerkki Vesi Oy"),
}
BILL_AMOUNT_MAX = Decimal("100000.00")
BILL_ABOVE_USUAL_RATIO = Decimal("1.5")    # a matched bill at least 150% of its typical month (decision 10)
BILL_ABOVE_LARGEST_RATIO = Decimal("1")    # any other bill above the largest typical month of the regular bills
BILL_SHORT_TERM_DAYS = 7                   # due fewer than 7 days after as_of (and not before it)
# A matched bill is the regular bill only when it fits it (#400): a once-a-month series and at least half of its
# typical month. Otherwise it is a bill from the same payee category (a quarterly water bill among utilities).
BILL_FIT_MIN_RATIO = Decimal("0.5")

BILL_TEXT: dict[str, tuple[str, str]] = {
    "amount": ("Amount due", "Maksettava summa"),
    "match_matched": ("This is your regular {label} bill.", "Tämä on tavallinen laskusi: {label}."),
    # #400: the same payee category, but not the regular bill (another billing period or another amount)
    "match_category": ("This bill is from the same payee category as your regular {label} payments.",
                       "Tämä lasku on samasta maksunsaajaluokasta kuin tavalliset maksusi: {label}."),
    "match_not_matched": ("This payee is not one of your regular bills.",
                          "Tämä maksunsaaja ei ole tavallisten laskujesi joukossa."),
    "match_no_payee": ("Add the payee's name to compare this bill with your regular bills.",
                       "Lisää maksunsaajan nimi, niin laskua verrataan tavallisiin laskuihisi."),
    "comparison": ("vs your usual {label} bill", "verrattuna tavalliseen laskuusi: {label}"),
    "change": ("Difference from the usual amount", "Ero tavalliseen summaan"),
    "basket_regular": ("It counts as regular essentials, like your other {label} payments.",
                       "Se kuuluu säännöllisiin välttämättömiin menoihin, kuten muutkin laskusi: {label}."),
    "basket_other": ("It is not one of your regular bills, so it would count as an unexpected necessity. "
                     "Nothing is saved.",
                     "Se ei ole tavallisten laskujesi joukossa, joten se olisi odottamaton välttämätön meno. "
                     "Mitään ei tallenneta."),
    "counted": ("Added to the bills before payday", "Lisätään laskuihin ennen palkkapäivää"),
    "free_after": ("Free until payday after this bill", "Vapaana palkkapäivään asti tämän laskun jälkeen"),
    "balance_after": ("Your balance allows, after this bill", "Saldosi sallii tämän laskun jälkeen"),
    "after": ("Safe to spend after this bill", "Turvallisesti käytettävissä tämän laskun jälkeen"),
    "effect_after_payday": ("Due on {due}, after your payday on {payday}, so it changes nothing before then.",
                            "Eräpäivä on {due}, palkkapäiväsi {payday} jälkeen, joten se ei muuta mitään "
                            "ennen sitä."),
    # safe_to_spend.text is at most two sentences (contracts/api.md 11.2): one of the effect_* sentences on
    # free until payday, then at most one sts_* sentence on the weekly number.
    "effect_excess": ("{reserved} is already set aside for your {label} payments before payday on {payday}, so "
                      "only the extra {counted} is added: free until payday goes from {free_before} to {free_after}.",
                      "Maksuillesi ({label}) on jo varattu {reserved} ennen palkkapäivää {payday}, joten vain "
                      "ylimenevä {counted} lisätään: palkkapäivään asti vapaana on {free_after} "
                      "(ennen laskua {free_before})."),
    "effect_covered": ("{reserved} is already set aside for your {label} payments before payday on {payday}, "
                       "which covers this one, so nothing changes.",
                       "Maksuillesi ({label}) on jo varattu {reserved} ennen palkkapäivää {payday}, mikä kattaa "
                       "tämän laskun, joten mikään ei muutu."),
    "effect_full": ("Due before your payday on {payday}, it is added to the bills before payday: free until "
                    "payday goes from {free_before} to {free_after}.",
                    "Eräpäivä on ennen palkkapäivääsi {payday}, joten lasku lisätään laskuihin ennen "
                    "palkkapäivää: palkkapäivään asti vapaana on {free_after} (ennen laskua {free_before})."),
    "sts_moves": ("Your weekly safe to spend goes from {before} to {after}.",
                  "Viikon turvallisesti käytettävissä oleva summasi on {after} (ennen laskua {before})."),
    "sts_budget": ("Your weekly safe to spend stays {before}: your monthly budget limits it, not your balance.",
                   "Viikon turvallisesti käytettävissä oleva summasi pysyy ennallaan, {before}: sitä rajaa "
                   "kuukausibudjettisi, ei saldosi."),
    "sts_negative": ("This bill takes more than is free until payday, so your weekly safe to spend is {after}.",
                     "Tämä lasku vie enemmän kuin palkkapäivään asti on vapaana, joten viikon turvallisesti "
                     "käytettävissä oleva summasi on {after}."),
    # warnings: a small note that never repeats a signal (contracts/api.md 11.2); today only a past due date
    "warn_past": ("The due date has passed. The payee may charge late-payment interest, so pay it soon.",
                  "Eräpäivä on mennyt. Maksunsaaja voi periä viivästyskorkoa, joten maksa lasku pian."),
    # signals: the warning signs, never a verdict (#242 decision 10); a failed check says what to do
    "sig_iban_check_failed": ("This account number does not pass its check. Compare it with the paper bill "
                              "before paying.",
                              "Tilinumero ei läpäise tarkistusta. Vertaa sitä paperilaskuun ennen maksamista."),
    "sig_reference_check_failed": ("This reference number does not pass its check. Compare it with the paper bill "
                                   "before paying.",
                                   "Viitenumero ei läpäise tarkistusta. Vertaa sitä paperilaskuun ennen maksamista."),
    "sig_new_payee": ("This payee is not one of your regular bills.",
                      "Tämä maksunsaaja ei ole tavallisten laskujesi joukossa."),
    # No ratio in the words: the threshold is a setting (BILL_ABOVE_USUAL_RATIO), the text stays true for any
    "sig_above_usual": ("This bill is {amount}, much more than usual ({typical}).",
                        "Tämä lasku on {amount}, paljon tavallista enemmän ({typical})."),
    # #400: a bill of the same payee category is compared with the category's whole month, and says so
    "sig_above_category": ("This bill is {amount}, much more than all your {label} payments in a usual month "
                           "({typical}).",
                           "Tämä lasku on {amount}, paljon enemmän kuin kaikki maksusi ({label}) tavallisena "
                           "kuukautena ({typical})."),
    "sig_above_largest": ("This bill is {amount}, more than your largest regular bill ({largest}).",
                          "Tämä lasku on {amount}, enemmän kuin suurin tavallinen laskusi ({largest})."),
    "sig_short_term": ("The due date is less than a week away.", "Eräpäivään on alle viikko."),
    "action": ("Add to payments", "Lisää maksuihin"),
}
# The message of a 422 invalid_bill, by reason (contracts/api.md section 11.1).
BILL_REFUSAL_TEXT: dict[str, tuple[str, str]] = {
    "one_of_barcode_or_fields": ("Send the barcode or the bill's details, one of the two.",
                                 "Lähetä viivakoodi tai laskun tiedot, toinen niistä."),
    "payee_with_fields": ("Put the payee's name inside the bill's details.",
                          "Kirjoita maksunsaajan nimi laskun tietoihin."),
    "barcode_length": ("This barcode cannot be read. Check it, or type the details from the bill.",
                       "Viivakoodia ei voi lukea. Tarkista se tai kirjoita laskun tiedot."),
    "barcode_check": ("This barcode does not pass its check. Compare it with the paper bill, or type the fields.",
                      "Viivakoodi ei läpäise tarkistusta. Vertaa sitä paperilaskuun tai kirjoita tiedot."),
    "amount_missing": ("This barcode has no amount. Type the details from the bill.",
                       "Viivakoodissa ei ole summaa. Kirjoita laskun tiedot."),
    "due_date_missing": ("This barcode has no due date. Type the details from the bill.",
                         "Viivakoodissa ei ole eräpäivää. Kirjoita laskun tiedot."),
    "amount_too_large": ("This bill is over the largest amount this service explains.",
                         "Lasku on suurempi kuin suurin summa, jonka tämä palvelu selittää."),
}
for _reason in ("barcode_version", "barcode_chars", "due_date"):   # read like a wrong length
    BILL_REFUSAL_TEXT[_reason] = BILL_REFUSAL_TEXT["barcode_length"]
# The four fixed glossary entries of a bill explanation: term -> ((label en, fi), (text en, fi)).
BILL_GLOSSARY: dict[str, tuple[tuple[str, str], tuple[str, str]]] = {
    "reference_number": (
        ("Reference number (viitenumero)", "Viitenumero"),
        ("The number that tells the payee which bill a payment is for; its last digit is a check digit, so "
         "most typing errors are caught.",
         "Numero, josta maksunsaaja tietää, mitä laskua maksu koskee; sen viimeinen numero on tarkiste, joten "
         "useimmat kirjoitusvirheet huomataan.")),
    "due_date": (
        ("Due date (eräpäivä)", "Eräpäivä"),
        ("The last day to pay the bill without a late-payment charge.",
         "Viimeinen päivä, jona lasku maksetaan ilman viivästysmaksua.")),
    "virtual_barcode": (
        ("Virtual barcode (virtuaaliviivakoodi)", "Virtuaaliviivakoodi"),
        ("A 54-digit code that holds the account, amount, reference number and due date, so the bill can be "
         "paid without typing them.",
         "54-numeroinen koodi, jossa ovat tili, summa, viitenumero ja eräpäivä, joten laskun voi maksaa "
         "kirjoittamatta niitä.")),
    "late_payment_interest": (
        ("Late-payment interest (viivästyskorko)", "Viivästyskorko"),
        ("Interest the payee may charge for each day a bill is paid after its due date.",
         "Korko, jonka maksunsaaja voi periä jokaiselta päivältä, jonka lasku maksetaan eräpäivän jälkeen.")),
}

COUNT_WORDS: dict[int, tuple[str, str]] = {
    2: ("two", "kaksi"), 3: ("three", "kolme"), 4: ("four", "neljä"), 5: ("five", "viisi"),
}

BASKET_TEXT: dict[str, tuple[str, str]] = {
    "title_monthly": ("Where your money goes in a typical month", "Mihin rahasi menevät tavallisena kuukautena"),
    "title_period": ("Where your money went", "Mihin rahasi menivät"),
    "subtitle_monthly": ("Monthly average, {label}", "Kuukausikeskiarvo, {label}"),
    "total": ("Total spending", "Kulutus yhteensä"),
    "share": ("Share of spending", "Osuus kulutuksesta"),
    "action_label": ("What is in everyday spending?", "Mitä arjen kulutukseen kuuluu?"),
    "action_prompt": ("What is in my everyday spending?", "Mitä arjen kulutukseeni kuuluu?"),
}

BILLS_TEXT: dict[str, tuple[str, str]] = {
    "title": ("Bills before payday", "Laskut ennen palkkapäivää"),
    "until_payday": ("Until payday on {date}", "Palkkapäivään {date} asti"),
    "until_assumed_payday": ("Next 30 days", "Seuraavat 30 päivää"),
    "typical": ("Usual amount", "Tavallinen summa"),
    "due": ("Due before payday", "Erääntyy ennen palkkapäivää"),
    "due_pro_rata": ("Due before payday, pro rata", "Erääntyy ennen palkkapäivää, suhteutettuna"),
    "estimate_label": ("Estimate", "Arvio"),
    "estimate_text": (
        "Some bills are paid several times a month, so the amount until payday is pro rata.",
        "Osa laskuista maksetaan useita kertoja kuussa, joten summa palkkapäivään asti on suhteutettu.",
    ),
    "status_spread": ("About {word} payments a month", "Noin {word} maksua kuussa"),
    "status_spread_many": ("Several payments a month", "Useita maksuja kuussa"),
    "status_done": ("Paid this month, usually around the {day}", "Maksettu tässä kuussa, yleensä noin {day}"),
    "status_upcoming": ("Due around the {day}", "Erääntyy noin {day}"),
    "status_late": ("Not paid yet, usually by the {day}", "Ei vielä maksettu, yleensä {day} mennessä"),
    "status_skipped": ("Not paid this month", "Ei maksettu tässä kuussa"),
    "note_sweep": (
        "Part of the salary moves to another account each month. That is a transfer, so it is not listed as a bill.",
        "Osa palkasta siirtyy joka kuukausi toiselle tilille. Se on siirto, joten sitä ei näytetä laskuna.",
    ),
    "note_no_salary": (
        "No regular salary was found, so the next 30 days are used instead of payday.",
        "Säännöllistä palkkaa ei löytynyt, joten palkkapäivän sijaan käytetään seuraavia 30 päivää.",
    ),
    "action_label": ("Show the payments", "Näytä maksut"),
    "note_after_payday": (
        "{label} falls due after payday, so it adds nothing before payday.",
        "{label} erääntyy palkkapäivän jälkeen, joten se ei kuulu summaan ennen palkkapäivää.",
    ),
}


# ---- get_safe_to_spend and run_what_if (#55) -------------------------------------------------------
# Numbers are read from core/metrics/03_safe_to_spend.sql and 04_what_if.sql for one customer
# (core/tools/metric_sql.py). Method ids are `<metric>.<output column>@1` (agent-core.md section 6.2).
# Bills due before payday is NOT read here: it is the same Number get_recurring_bills returns
# (METHODS["bills_due"], from recurring.bills_due_numbers: the unrounded per-bill terms summed and
# rounded once, like bills_due_eur in 03), so both cards show one value. get_safe_to_spend checks it
# against 03's bills_due_eur on every call.

SAFE_TO_SPEND_FILE = "03_safe_to_spend.sql"
SAFE_TO_SPEND_CUSHION_EUR = "100"   # metrics.md section 10, decision 3 (configurable; 03's default)
WHAT_IF_FILE = "04_what_if.sql"
USER_INPUT_METHOD = "user_input@1"
# The only metric files a stored `metric` evidence spec may name; resolve() refuses any other file.
METRIC_EVIDENCE_FILES = frozenset({SAFE_TO_SPEND_FILE, WHAT_IF_FILE})

# ---- get_spender_profile and get_peer_benchmark (#69) ----------------------------------------------
# Numbers are read from core/metrics/05_spender_profile.sql and 06_peer_benchmark.sql for one customer
# (core/tools/metric_sql.py). Method ids are `<metric>.<output column>@1` (agent-core.md section 6.2).
# Labels, descriptions and notes carry no digits except the fixed "at least 20" of the peer estimate
# text (contracts/api.md card.peer): every number is a Number object.

PROFILE_FILE = "05_spender_profile.sql"
PEER_FILE = "06_peer_benchmark.sql"
# The peer comparison invites a change only when the customer spends more than the median by more than
# this many percent (#418); within the margin either way it is "about the same", below it the answer says
# that is already their saving. Compared on the value as the text shows it (one decimal).
PEER_ACTION_MARGIN_PCT = 1.0
# Spending that is not cut (regular essentials, housing, utilities, groceries): no offer to cut it.
PEER_NO_CUT_ACTION = frozenset({"regular_essentials", "Housing", "Utilities", "Groceries"})


def peer_gap_shown(value) -> float:
    """The peer gap in percent as the text shows it (one decimal), so "0.0%" is never said as a gap."""
    return round(float(value), 1)


def peer_offers_cut(metric: str, value) -> bool:
    """The peer answer offers a cut (the text and the card's action together, #418): above the median by more
    than the margin, for spending that can be cut."""
    return value is not None and metric not in PEER_NO_CUT_ACTION and peer_gap_shown(value) > PEER_ACTION_MARGIN_PCT
PEER_MIN_N = "20"   # app.peer_min_n of 06: at least 20 other peers (metrics.md section 10, decision 7)
# The profile writes `metric` evidence specs for 05 (#122 lets evidence re-run only listed files).
METRIC_EVIDENCE_FILES = METRIC_EVIDENCE_FILES | frozenset({PROFILE_FILE})

PROFILE_KEYS = ("not_enough_income_data", "stretched", "big_ticket", "everyday_heavy", "saver", "steady")
PROFILE_TRAITS = ("salary_moved_elsewhere", "went_below_zero", "regular_investor", "weekend_spender",
                  "frequent_small_purchases")

# Label thresholds of 05 (metrics.md section 5): fixed constants, in percent or purchases a month.
PROFILE_THRESHOLDS = {
    "big_ticket_one_off_share": 5,      # one_off_share >= 5
    "everyday_heavy_share": 30,         # everyday share >= 30
    "saver_keep_rate": 20,              # keep_rate >= 20 (stretched: keep_rate < 0)
    "weekend_spender_share": 45,        # trait: everyday weekend share >= 45
    "frequent_purchases_month": 12,     # trait: everyday purchases a month >= 12
}

# Profile features: (key, output column of 05, unit value). Keys are the feature names of metrics.md
# section 5 where it names one (keep_rate, net_income, spend, saving, one_off_share), else the column.
PROFILE_FEATURES = (
    ("keep_rate", "keep_rate_pct", "percent"),
    ("net_income", "net_income_month_eur", "eur_per_month"),
    ("spend", "spend_month_eur", "eur_per_month"),
    ("saving", "saving_month_eur", "eur_per_month"),
    ("regular_share_pct", "regular_share_pct", "percent"),
    ("unexpected_share_pct", "unexpected_share_pct", "percent"),
    ("everyday_share_pct", "everyday_share_pct", "percent"),
    ("one_off_share", "one_off_share_pct", "percent"),
    ("everyday_weekend_pct", "everyday_weekend_pct", "percent"),
    ("everyday_avg_ticket_eur", "everyday_avg_ticket_eur", "eur"),
    ("everyday_tx_month", "everyday_tx_month", "count"),
    ("months_out_over_in", "months_out_over_in", "months"),
    ("n_tx_below_zero", "n_tx_below_zero", "count"),
)
# The features the profile card shows (the features that decided the label come first).
PROFILE_CARD_FEATURES = ("keep_rate", "everyday_share_pct", "one_off_share", "everyday_weekend_pct",
                         "everyday_tx_month")
# Which feature each trait rests on (salary_moved_elsewhere rests on the sweep series, not a feature).
TRAIT_FEATURES = {
    "went_below_zero": "n_tx_below_zero",
    "regular_investor": "saving",
    "weekend_spender": "everyday_weekend_pct",
    "frequent_small_purchases": "everyday_tx_month",
}

PROFILE_LABELS: dict[str, tuple[str, str]] = {   # contracts/api.md section 5 where it has one
    "not_enough_income_data": ("Not enough income data", "Liian vähän tulotietoja"),
    "stretched": ("Stretched", "Tiukilla"),
    "big_ticket": ("Big ticket", "Isot hankinnat"),
    "everyday_heavy": ("Everyday spender", "Arjen kuluttaja"),
    "saver": ("Saver", "Säästäjä"),
    "steady": ("Steady", "Tasainen"),
}
PROFILE_DESCRIPTIONS: dict[str, tuple[str, str]] = {
    "not_enough_income_data": (
        "This account shows too little income to say what kind of spender you are.",
        "Tilillä näkyy liian vähän tuloja, jotta kulutustyyliäsi voisi arvioida.",
    ),
    "stretched": (
        "Over your last six full months you spent more than came in.",
        "Kuuden viimeisen täyden kuukauden aikana kulutit enemmän kuin sait tuloja.",
    ),
    "big_ticket": (
        "Large one-off purchases make up a notable part of your spending.",
        "Isot kertaostokset ovat merkittävä osa kulutustasi.",
    ),
    "everyday_heavy": (
        "A large share of your money goes to everyday spending, such as eating out and entertainment.",
        "Suuri osa rahoistasi menee arjen kulutukseen, kuten ulkona syömiseen ja viihteeseen.",
    ),
    "saver": (
        "You keep a good part of what comes in.",
        "Sinulle jää hyvä osa tuloistasi.",
    ),
    "steady": (
        "Your spending stays within your income, without a heavy everyday share or large one-off purchases.",
        "Kulutuksesi pysyy tulojesi rajoissa ilman suurta arjen kulutuksen osuutta tai isoja kertaostoksia.",
    ),
}
TRAIT_LABELS: dict[str, tuple[str, str]] = {
    "salary_moved_elsewhere": ("Salary moved elsewhere", "Palkka siirtyy muualle"),
    "went_below_zero": ("Went below zero", "Saldo meni miinukselle"),
    "regular_investor": ("Regular investor", "Säännöllinen sijoittaja"),
    "weekend_spender": ("Weekend spender", "Viikonloppukuluttaja"),
    "frequent_small_purchases": ("Many small purchases", "Paljon pieniä ostoksia"),
}
TRAIT_NOTES: dict[str, tuple[str, str]] = {
    "salary_moved_elsewhere": (
        "Most of your salary moves to another account each month, so this account shows only part of your money.",
        "Suurin osa palkastasi siirtyy joka kuukausi toiselle tilille, joten tämä tili näyttää vain osan rahoistasi.",
    ),
    "went_below_zero": (
        "Your balance went below zero at least once.",
        "Saldosi meni ainakin kerran miinukselle.",
    ),
    "regular_investor": (
        "You put money into investments.",
        "Sijoitat rahaa.",
    ),
    "weekend_spender": (
        "Much of your everyday spending happens at weekends.",
        "Suuri osa arjen kulutuksestasi tapahtuu viikonloppuisin.",
    ),
    "frequent_small_purchases": (
        "You make many small everyday purchases each month.",
        "Teet joka kuukausi paljon pieniä arjen ostoksia.",
    ),
}
PROFILE_FEATURE_LABELS: dict[str, tuple[str, str]] = {
    "keep_rate": ("Kept from income", "Tuloista jäi"),
    "net_income": ("Income a month", "Tulot kuukaudessa"),
    "spend": ("Spending a month", "Kulutus kuukaudessa"),
    "saving": ("Investments a month", "Sijoitukset kuukaudessa"),
    "regular_share_pct": ("Regular essentials, share of spending", "Säännölliset välttämättömät, osuus kulutuksesta"),
    "unexpected_share_pct": ("Unexpected necessities, share of spending",
                             "Odottamattomat välttämättömät, osuus kulutuksesta"),
    "everyday_share_pct": ("Everyday spending, share of spending", "Arjen kulutus, osuus kulutuksesta"),
    "one_off_share": ("One-off purchases, share of spending", "Kertaostokset, osuus kulutuksesta"),
    "everyday_weekend_pct": ("Everyday spending at weekends", "Arjen kulutus viikonloppuisin"),
    "everyday_avg_ticket_eur": ("Average everyday purchase", "Keskimääräinen arjen ostos"),
    "everyday_tx_month": ("Everyday purchases a month", "Arjen ostoksia kuukaudessa"),
    "months_out_over_in": ("Months when more went out than came in", "Kuukaudet, joina menot ylittivät tulot"),
    "n_tx_below_zero": ("Payments that took the balance below zero", "Maksut, jotka veivät saldon miinukselle"),
}
PROFILE_TEXT: dict[str, tuple[str, str]] = {
    "title": ("What kind of spender are you?", "Millainen kuluttaja olet?"),
    "subtitle": ("Based on {label}", "Perustuu jaksoon {label}"),
    "action_label": ("Compare with people like me", "Vertaa minua kaltaisiini"),
    "action_prompt": ("How does my spending compare with people like me?",
                      "Miten kulutukseni vertautuu kaltaisiini ihmisiin?"),
    "note_no_income": (
        "This account shows too little income for a verdict, so no keep rate is computed.",
        "Tilillä näkyy liian vähän tuloja arvioon, joten tuloista jäävää osuutta ei lasketa.",
    ),
    "note_sweep": (
        "Most of the salary moves to another account each month, so this account shows only part of the spending.",
        "Suurin osa palkasta siirtyy joka kuukausi toiselle tilille, joten tämä tili näyttää vain osan kulutuksesta.",
    ),
}

# Peer metrics: exactly the metric_list of 06 (Health is never benchmarked, R9).
PEER_METRICS: tuple[str, ...] = (
    "spend_total", "regular_essentials", "unexpected_necessities", "everyday_spending",
    "Groceries", "Restaurants", "Transportation", "Entertainment", "Lifestyle", "Travel", "Home & Tech",
    "Utilities", "Housing",
)
PEER_SENSITIVE = frozenset({"Health"})   # never benchmarked or singled out (R9)
PEER_LEVELS = ("age_band+area3", "age_band+city", "age_band", "all")
PEER_STATS = (  # (key, output column of 06, unit value): group statistics, evidence kind peer_aggregate
    ("peer_median", "peer_median_month_eur", "eur_per_month"),
    ("peer_p25", "peer_p25_month_eur", "eur_per_month"),
    ("peer_p75", "peer_p75_month_eur", "eur_per_month"),
    ("percentile", "percentile", "percentile"),
    ("vs_median", "vs_median_pct", "percent"),
    ("size", "peer_n", "count"),
)
CITY_LABELS: dict[str, tuple[str, str]] = {   # metrics.md section 6: first two digits of the postal code
    "00": ("Helsinki", "Helsinki"),
    "01": ("Vantaa", "Vantaa"),
    "02": ("Espoo and Kauniainen", "Espoo ja Kauniainen"),
}
PEER_TEXT: dict[str, tuple[str, str]] = {
    "title": ("{what}: you and people like you", "{what}: sinä ja kaltaisesi"),
    "subtitle": ("Monthly average, {label}", "Kuukausikeskiarvo, {label}"),
    "spend_total": ("Total spending", "Kulutus yhteensä"),
    "you": ("You", "Sinä"),
    "peer_median": ("Typical for your group", "Tyypillinen ryhmässäsi"),
    "peer_p25": ("Lower quarter", "Alaneljännes"),
    "peer_p75": ("Upper quarter", "Yläneljännes"),
    "percentile": ("Your position", "Sijaintisi"),
    "vs_median": ("Compared with typical", "Verrattuna tyypilliseen"),
    "size": ("Other people in the group", "Muita ryhmässä"),
    "group_age_band+area3": ("Age {age}, postal area {area}", "Ikä {age}, postinumeroalue {area}"),
    "group_age_band+city": ("Age {age}, {city}", "Ikä {age}, {city}"),
    "group_city_other": ("postal codes starting {code}", "postinumerot alkavat {code}"),
    "group_age_band": ("Age {age}", "Ikä {age}"),
    "group_all": ("All customers", "Kaikki asiakkaat"),
    "estimate_label": ("Estimate", "Arvio"),
    "estimate_age_band+area3": (
        "Compared with at least 20 other customers of your age band and postal area. "
        "Only group statistics are shown.",
        "Verrattu vähintään 20 muuhun saman ikäryhmän ja postinumeroalueen asiakkaaseen. "
        "Vain ryhmän tunnusluvut näytetään.",
    ),
    "estimate_age_band+city": (
        "Compared with at least 20 other customers of your age band in your city. Only group statistics are shown.",
        "Verrattu vähintään 20 muuhun saman ikäryhmän asiakkaaseen kaupungissasi. Vain ryhmän tunnusluvut näytetään.",
    ),
    "estimate_age_band": (
        "Compared with at least 20 other customers of your age band. Only group statistics are shown.",
        "Verrattu vähintään 20 muuhun saman ikäryhmän asiakkaaseen. Vain ryhmän tunnusluvut näytetään.",
    ),
    "estimate_all": (
        "Compared with at least 20 other customers. Only group statistics are shown.",
        "Verrattu vähintään 20 muuhun asiakkaaseen. Vain ryhmän tunnusluvut näytetään.",
    ),
    "note": (
        "Only group statistics are shown, never another customer's transactions.",
        "Vain ryhmän tunnusluvut näytetään, ei koskaan toisen asiakkaan tapahtumia.",
    ),
    "reason_not_comparable": (
        "Most of the salary moves to another account each month, so this account is not compared with others.",
        "Suurin osa palkasta siirtyy joka kuukausi toiselle tilille, joten tätä tiliä ei verrata muihin.",
    ),
    "reason_group_too_small": (
        "There are too few similar customers to compare with, so no comparison is shown.",
        "Samankaltaisia asiakkaita on liian vähän vertailuun, joten vertailua ei näytetä.",
    ),
    "action_label": ("How could I spend less here?", "Miten voisin kuluttaa tähän vähemmän?"),
    # The category's offer is the what-if itself; the what-if rule then asks by how much (#418).
    "action_prompt": ("What if I cut {what}?", "Entä jos vähentäisin luokassa {what}?"),
    "action_prompt_total": ("How could I save more?", "Miten voisin säästää enemmän?"),
}

SAFE_TO_SPEND_NUMBERS = (  # (key, output column) read from 03_safe_to_spend.sql as metric numbers
    ("free_until_payday", "free_until_payday_eur"),
    ("balance_limit", "balance_limit_7d_eur"),
    ("budget_limit", "budget_limit_7d_eur"),
    ("balance", "balance_eur"),
    ("essentials_reserve", "essentials_reserve_eur"),
    ("irregular_reserve", "irregular_reserve_eur"),
    ("cushion", "cushion_eur"),
)
SAFE_TO_SPEND_COMPONENTS = ("balance", "bills_due", "essentials_reserve", "irregular_reserve", "cushion")
# Pay yourself first (#391): the weekly figure is "below the usual pace" when it is more than this many
# euros a week under it (then the sentence names the usual pace).
USUAL_PACE_MARGIN_EUR = "5"
USUAL_WEEK_METHOD = "safe_to_spend.usual_week_eur@1"   # everyday month x 7 / 30.4375

WHAT_IF_NUMBERS = (  # (key, output column, unit value)
    ("baseline_per_month", "baseline_month_eur", "eur_per_month"),
    ("saving_per_month", "saving_month_eur", "eur_per_month"),
    ("saving_per_week", "saving_week_eur", "eur_per_week"),
    ("saving_per_year", "saving_year_eur", "eur_per_year"),
    ("one_off_excluded", "one_off_excluded_eur", "eur"),
    ("regular_excluded", "regular_excluded_eur", "eur"),
)

# Categories a what-if may name: spending only, never Health on its own (R9).
WHAT_IF_CATEGORIES = SPEND_CATEGORIES - {"Health"}

SAFE_TO_SPEND_TEXT: dict[str, tuple[str, str]] = {
    "title": ("Safe to spend in the next 7 days", "Turvallisesti käytettävissä seuraavat 7 päivää"),
    "next_7_days": ("Next 7 days", "Seuraavat 7 päivää"),
    "until_payday": ("Until payday on {date}", "Palkkapäivään {date} asti"),
    "until_assumed_payday": ("Next 30 days", "Seuraavat 30 päivää"),
    "safe_to_spend": ("Safe to spend", "Turvallisesti käytettävissä"),
    "free_until_payday": ("Free until payday", "Vapaana palkkapäivään asti"),
    "balance_limit": ("Your balance allows", "Saldosi sallii"),
    "budget_limit": ("Your monthly budget allows", "Kuukausibudjettisi sallii"),
    "savings_goal": ("Set aside first each month", "Ensin sivuun kuukaudessa"),          # #391
    # #391 answers (template, number tokens): the goal is quoted next to safe to spend, so they add up.
    "with_goal": ("You can spend about {safe} this week, after setting aside about {goal}.",
                  "Voit käyttää tällä viikolla noin {safe}, kun ensin laitat sivuun noin {goal}."),
    "below_usual_with_goal": ("To keep setting aside {goal}, about {safe} a week is safe to spend, below your "
                              "usual {usual}.",
                              "Jotta voit laittaa sivuun {goal}, turvallisesti käytettävissä on noin {safe} "
                              "viikossa, alle tavallisen {usual}."),
    "usual_week": ("Usual everyday pace", "Tavallinen arkikulutuksen tahti"),            # the display says "a week"
    "balance": ("Balance", "Saldo"),
    "bills_due": ("Bills before payday", "Laskut ennen palkkapäivää"),
    "essentials_reserve": ("Essentials reserve", "Varaus välttämättömiin"),
    "irregular_reserve": ("Irregular reserve", "Varaus odottamattomiin"),
    "cushion": ("Cushion", "Puskuri"),
    "c_balance": ("Money on your account", "Rahaa tililläsi"),
    "c_bills_due": ("Bills due before payday", "Ennen palkkapäivää erääntyvät laskut"),
    "c_essentials_reserve": ("Usual essentials until payday", "Tavalliset välttämättömät palkkapäivään asti"),
    "c_irregular_reserve": ("Reserve for unexpected necessities", "Varaus odottamattomiin välttämättömiin"),
    "c_cushion": ("Cushion", "Puskuri"),
    "estimate_label": ("Estimate", "Arvio"),
    "estimate_text": (
        "Your balance minus bills, usual essentials and a small cushion until payday, spread over the "
        "days to payday. It is also capped by your usual monthly budget after your savings goal is set "
        "aside first. A recurring investment deposit is your own saving plan, so it is kept aside too.",
        "Saldosi miinus laskut, tavalliset välttämättömät menot ja pieni puskuri palkkapäivään asti, "
        "jaettuna päiville ennen palkkapäivää. Summaa rajaa myös tavallinen kuukausibudjettisi, kun "
        "säästötavoitteesi on ensin laitettu sivuun. Säännöllinen sijoitus on oma säästösuunnitelmasi, "
        "joten se pidetään myös sivussa.",
    ),
    "how": ("How is this calculated?", "Miten tämä lasketaan?"),
    "note_no_salary": (
        "No regular salary shows on this account, so safe to spend cannot be estimated reliably.",
        "Tilillä ei näy säännöllistä palkkaa, joten turvallista käyttövaraa ei voi arvioida luotettavasti.",
    ),
    "note_late_salary": (
        "This month's salary has not arrived yet, so payday is taken as the end of the month.",
        "Tämän kuun palkka ei ole vielä tullut, joten palkkapäiväksi oletetaan kuun loppu.",
    ),
}

# ---- get_balance_forecast (#257, metrics.md section 3.3) ------------------------------------------
# Number labels have no digits except a date written exactly as the number's own period label (the
# validator accepts it); the card's row labels are card text only and may carry dates.
FORECAST_BALANCE_METHOD = "balance_forecast.balance_eur@1"   # composite, formula `balance_forecast`
FORECAST_BASKETS = ("everyday_spending", "regular_essentials")   # the usual spending of the daily pace
FORECAST_TEXT: dict[str, tuple[str, str]] = {
    "title": ("Balance until payday", "Saldo palkkapäivään asti"),
    "balance_now": ("Balance today", "Saldo tänään"),
    "bills_until_payday": ("Bills before payday", "Laskut ennen palkkapäivää"),
    "daily_pace": ("Usual spending", "Tavallinen kulutus"),   # the display says "a day" / "/ pv"
    "bills_to_date": ("Bills due by then", "Siihen mennessä erääntyvät laskut"),
    "lowest": ("Lowest point, {date}", "Alin kohta, {date}"),
    "lowest_day_before_payday": ("Lowest point, the day before payday, {date}",
                                 "Alin kohta, palkkapäivää edeltävä päivä, {date}"),
    "day_before_payday": ("Day before payday, {date}", "Palkkapäivää edeltävä päivä, {date}"),
    "below_zero": ("First day below zero, {date}", "Ensimmäinen päivä miinuksella, {date}"),
    "after_bills": ("After bills, {date}", "Laskujen jälkeen, {date}"),
    "row_today": ("Today", "Tänään"),
    "row_bills": ("{bills} paid", "{bills} maksettu"),
    "row_below_zero": ("below zero", "miinuksella"),
    "row_lowest": ("lowest point", "alin kohta"),
    "row_day_before_payday": ("day before payday", "palkkapäivää edeltävä päivä"),
    "estimate_label": ("Estimate", "Arvio"),
    "estimate_text": (
        "If you spend as usual: about {pace}, the middle one of your last three full months' daily "
        "averages of everyday spending and essentials, bills left out. Bills come on their usual days. "
        "Salary and other money coming in before payday are not counted.",
        "Jos kulutat tavalliseen tapaan: noin {pace}, kolmen viimeisen täyden kuukauden "
        "päiväkeskiarvoista keskimmäinen, arkikulutus ja välttämättömät menot ilman laskuja. Laskut tulevat "
        "tavallisina päivinään. Palkkaa tai muita ennen palkkapäivää tulevia rahoja ei lasketa mukaan.",
    ),
    "note_comfortable": ("Your balance stays comfortably above the bills due before payday.",
                         "Saldosi pysyy selvästi suurempana kuin ennen palkkapäivää erääntyvät laskut."),
    "note_above_zero": ("Your balance stays above zero until payday if you spend as usual, but with little to spare.",
                        "Saldosi pysyy plussalla palkkapäivään asti, jos kulutat tavalliseen tapaan, mutta "
                        "liikkumavaraa on vähän."),
    "note_below_zero": ("If you spend as usual, your balance goes below zero on {date}.",
                        "Jos kulutat tavalliseen tapaan, saldosi menee miinukselle {date}."),
    "note_estimate": (
        "This is an estimate: it assumes you spend as usual and your bills come on their usual days, and "
        "it leaves out money coming in before payday.",
        "Tämä on arvio: se olettaa, että kulutat tavalliseen tapaan ja laskut tulevat tavallisina päivinään, "
        "eikä siinä ole mukana ennen palkkapäivää tulevia rahoja.",
    ),
    "note_payday_bills": (
        "Bills due on payday itself are in the bills before payday, but not in the balance the day before.",
        "Palkkapäivänä erääntyvät laskut ovat mukana ennen palkkapäivää erääntyvissä laskuissa, mutta eivät "
        "edellisen päivän saldossa.",
    ),
    "note_no_salary": (
        "No regular salary shows on this account, so payday is assumed to be a month away.",
        "Tilillä ei näy säännöllistä palkkaa, joten palkkapäivän oletetaan olevan kuukauden päästä.",
    ),
    "note_late_salary": (
        "This month's salary has not arrived yet, so payday is taken as the end of the month.",
        "Tämän kuun palkka ei ole vielä tullut, joten palkkapäiväksi oletetaan kuun loppu.",
    ),
    "note_no_data": ("Your balance until payday cannot be estimated: there are no transactions to start from.",
                     "Saldoa palkkapäivään asti ei voi arvioida: aloitukseen ei ole tapahtumia."),
    "how": ("How is this calculated?", "Miten tämä lasketaan?"),
    "whatif_label": ("What could I cut?", "Mistä voisin vähentää?"),
    "whatif_prompt": ("What if I cut my spending?", "Entä jos vähentäisin kulutustani?"),
}

# ---- get_safe_to_save (#165, metrics.md section 3.1) ----------------------------------------------
# Read from the same row of 03_safe_to_spend.sql as get_safe_to_spend (one run per request). Monthly
# figures describe a typical month of the last 6 complete months; the stock describes today + 1 to payday.
SAFE_TO_SAVE_NUMBERS = (  # (key, output column, unit value)
    ("monthly", "safe_to_save_monthly_eur", "eur_per_month"),
    ("free_month", "free_month_eur", "eur_per_month"),
    ("everyday_month", "everyday_month_eur", "eur_per_month"),
    ("essentials_shortfall", "essentials_shortfall_month_eur", "eur_per_month"),
    ("stock", "safe_to_save_eur", "eur"),
    ("free_until_payday", "free_until_payday_eur", "eur"),
    ("everyday_until_payday", "everyday_until_payday_eur", "eur"),
    ("reason", "save_reason_month_eur", "eur_per_month"),   # only when a typical month leaves nothing
)
SENSITIVE_CATEGORIES = frozenset({"Health"})   # never named by the safe-to-save reason (R9)

SAFE_TO_SAVE_TEXT: dict[str, tuple[str, str]] = {
    # #267: the step into the bank's own app; names the destination only (no fund, no advice, no returns)
    "host_monthly_saving": ("See monthly saving in S-mobiili", "Katso kuukausisäästäminen S-mobiilissa"),
    "title": ("Safe to save", "Turvallisesti säästettävissä"),
    "subtitle": ("What a typical month leaves", "Mitä tavallisesta kuukaudesta jää"),
    # #391: the savings goal is quoted next to safe to spend, so the two add up; the headline stays safe to
    # save by its own formula, and the subtitle says how it relates to the goal (card text, displays).
    "subtitle_with_goal": ("You could set aside about {goal} on top of spending about {weekly} a week.",
                           "Voisit laittaa sivuun noin {goal} ja käyttää silti noin {weekly} viikossa."),
    "subtitle_below_goal": ("Your goal is {goal}; at your usual pace about {monthly} would be left.",
                            "Tavoitteesi on {goal}; tavallisella tahdilla jäisi noin {monthly}."),
    "savings_goal": ("Your savings goal", "Säästötavoitteesi"),
    "safe_to_spend_week": ("Safe to spend in the next 7 days", "Turvallisesti käytettävissä seuraavat 7 päivää"),
    "estimate_text": (
        "A typical month of your last six: income minus bills, saving you set up, usual essentials, a "
        "reserve for unexpected costs and your usual everyday spending.",
        "Tavallinen kuukausi kuuden viimeisen joukosta: tulot miinus laskut, sopimasi säästöt, tavalliset "
        "välttämättömät menot, varaus yllättäviin menoihin ja tavallinen arkikulutuksesi.",
    ),
    # Number labels
    "monthly": ("Typically left each month", "Tavallisesti jää kuukaudessa"),
    "free_month": ("Free in a typical month", "Vapaana tavallisessa kuukaudessa"),
    "everyday_month": ("Everyday spending in a typical month", "Arkikulutus tavallisessa kuukaudessa"),
    "essentials_shortfall": ("Bills, essentials and the reserve above income",
                             "Laskut, välttämättömät menot ja varaus ylittävät tulot"),
    "stock": ("In your account beyond what you need until payday",
              "Tililläsi yli sen, mitä tarvitset palkkapäivään asti"),
    "free_until_payday": ("Free until payday", "Vapaana palkkapäivään asti"),
    "everyday_until_payday": ("Everyday spending until payday", "Arkikulutus palkkapäivään asti"),
    # component labels
    "c_free_month": ("Left after bills, essentials and the reserve",
                     "Jää laskujen, välttämättömien menojen ja varauksen jälkeen"),
    "c_everyday_month": ("Usual everyday spending", "Tavallinen arkikulutus"),
    "c_essentials_shortfall": ("Short before any everyday spending", "Vajaa jo ennen arkikulutusta"),
    "c_free_until_payday": ("Free until payday", "Vapaana palkkapäivään asti"),
    "c_everyday_until_payday": ("Usual everyday spending until payday", "Tavallinen arkikulutus palkkapäivään asti"),
    # one sentence, never a call to action, no digits (R7)
    "stock_explanation": (
        "Money in your account beyond what you need until payday, after bills, reserves, a small cushion "
        "and your usual everyday spending.",
        "Tililläsi oleva raha yli sen, mitä tarvitset palkkapäivään asti, kun laskut, varaukset, pieni "
        "puskuri ja tavallinen arkikulutuksesi on otettu huomioon.",
    ),
    # the reason when a typical month leaves nothing; no digits (the app shows the amount next to it)
    "reason_essentials_exceed_income": (
        "Nothing is left in a typical month: your bills, the saving you set up, usual essentials and the "
        "reserve for unexpected costs already come to more than your income.",
        "Tavallisesta kuukaudesta ei jää mitään: laskusi, sopimasi säästöt, tavalliset välttämättömät menot "
        "ja varaus yllättäviin menoihin ovat jo yhteensä enemmän kuin tulosi.",
    ),
    "reason_largest_everyday_category": (
        "Nothing is left in a typical month. Your largest everyday spending category is {category}.",
        "Tavallisesta kuukaudesta ei jää mitään. Suurin arkikulutuksesi luokka on {category}.",
    ),
    "reason_everyday_uses_it_up": (   # the category would be sensitive (R9): it is not named
        "Nothing is left in a typical month after your usual everyday spending.",
        "Tavallisesta kuukaudesta ei jää mitään tavallisen arkikulutuksesi jälkeen.",
    ),
    "reason_amount_shortfall": ("Short each month", "Vajaa kuukaudessa"),
    "reason_amount_category": ("{category} in a typical month", "{category} tavallisessa kuukaudessa"),
    "reason_amount_everyday": ("Largest everyday category in a typical month",
                               "Suurin arkikulutuksen luokka tavallisessa kuukaudessa"),
}

WHAT_IF_TEXT: dict[str, tuple[str, str]] = {
    "scenario": ("Spend {pct}% less on {what}", "Käytä {pct} % vähemmän: {what}"),
    "subtitle": ("Based on your last 6 full months", "Perustuu 6 viimeiseen täyteen kuukauteesi"),
    "cut": ("Cut you chose", "Valitsemasi leikkaus"),
    "baseline_per_month": ("{what} in a typical month", "{what} tavallisena kuukautena"),
    "saving_per_month": ("You would save", "Säästäisit"),
    "saving_per_week": ("Per week", "Viikossa"),
    "saving_per_year": ("Per year", "Vuodessa"),
    "one_off_excluded": ("One-off purchases left out", "Pois jätetyt kertaostokset"),
    "regular_excluded": ("Regular essentials left out", "Pois jätetyt säännölliset välttämättömät"),
    "estimate_label": ("Estimate", "Arvio"),
    "estimate_text": (
        "Average of your last 6 full months (one-off purchases left out), cut by {pct}%.",
        "6 viimeisen täyden kuukautesi keskiarvo (kertaostokset pois jätettyinä), {pct} % pienempänä.",
    ),
    "assume_rest": ("The rest of your spending stays as it is.", "Muu kulutuksesi pysyy ennallaan."),
    "caveat_estimate": (
        "This is an estimate, not a promise. Prices and habits change.",
        "Tämä on arvio, ei lupaus. Hinnat ja tottumukset muuttuvat.",
    ),
    "caveat_unexpected": (
        "Part of this is unexpected necessities: needed costs that can only sometimes be reduced.",
        "Osa tästä on odottamattomia välttämättömiä menoja, joita voi vain joskus vähentää.",
    ),
    "caveat_not_offered": (
        "Regular essentials are not cut in a what-if, so there is nothing to cut in this selection.",
        "Säännöllisiä välttämättömiä menoja ei leikata, joten tässä valinnassa ei ole leikattavaa.",
    ),
    "mcc": ("purchases with MCC {codes}", "ostokset, MCC {codes}"),
    "how": ("How is this calculated?", "Miten tämä lasketaan?"),
}

# ---- spike reviews (#68, contract 0.2.0 sections 3 and 10) ----------------------------------------
# Fixed, reviewed templates: the AI model never writes them. The question, the option labels and the
# Finnish effects are Renat's decision on issue #68 (they differ from the wording of contract 0.2.0,
# which #34 corrects); "turvallisesti käytettävissä" is the Finnish term for safe to spend everywhere.
# The question is filled in on the server: {amount} is the amount Number's display, {category} the
# category label, {date} the purchase date, all in the card's language.
PRODUCT_NAME = "Sentti"

REVIEW_TEXT: dict[str, tuple[str, str]] = {
    "title": ("One question about a large purchase", "Yksi kysymys isosta ostoksesta"),
    "question": ("{amount} at {category} on {date} — needed, or your choice?",
                 "{amount} {category}, {date} — välttämätön hankinta vai oma valinta?"),
    "option_unexpected_necessities": ("Needed", "Välttämätön"),
    "option_everyday_spending": ("My choice", "Oma valinta"),
    "effect_unexpected_necessities": (
        "It counts as an unexpected necessity. {product} keeps a bigger reserve for surprises like this, so "
        "your safe to spend goes down.",
        "Se lasketaan välttämättömäksi yllätysmenoksi. {product} varaa jatkossa enemmän rahaa tällaisiin "
        "yllätyksiin, joten turvallisesti käytettävissä oleva summa pienenee.",
    ),
    "effect_everyday_spending": (
        "It counts as everyday spending. Your safe to spend stays the same; your everyday spending this "
        "month is higher than usual.",
        "Se lasketaan arkikulutukseksi. Turvallisesti käytettävissä oleva summa pysyy ennallaan, mutta "
        "arkikulutuksesi on tässä kuussa tavallista suurempi.",
    ),
    "why": (
        "Only you know what this purchase was. Your answer changes only how your own spending is grouped.",
        "Vain sinä tiedät, mikä tämä ostos oli. Vastauksesi muuttaa vain sitä, miten omat menosi ryhmitellään.",
    ),
    "amount": ("{category} purchase", "Ostos: {category}"),
    "see_purchase": ("See the purchase", "Näytä ostos"),
    "month_avg": ("{label}, monthly average", "{label}, kuukausikeskiarvo"),
    # label confirmations (POST /api/baskets/label)
    "done_unexpected_necessities": (
        "Thanks. {product} now keeps a bigger reserve for surprises like this, so your safe to spend is lower.",
        "Kiitos. {product} varaa nyt enemmän rahaa tällaisiin yllätyksiin, joten turvallisesti käytettävissä "
        "oleva summa on pienempi.",
    ),
    "done_everyday_spending": (
        "Thanks. This counts as everyday spending, so your everyday spending this month is {amount} higher "
        "than usual. Your safe to spend stays the same.",
        "Kiitos. Tämä lasketaan arkikulutukseksi, joten arkikulutuksesi on tässä kuussa {amount} tavallista "
        "suurempi. Turvallisesti käytettävissä oleva summa pysyy ennallaan.",
    ),
    "undone_pending": ("Undone. This purchase is waiting for your answer again.",
                       "Peruttu. Tämä ostos odottaa taas vastaustasi."),
    "undone_closed": ("Undone. This purchase is back in the group the rules give it.",
                      "Peruttu. Tämä ostos on taas siinä ryhmässä, johon säännöt sen sijoittavat."),
    "unchanged": ("Nothing changed: this answer is already saved.",
                  "Mikään ei muuttunut: tämä vastaus on jo tallennettu."),
    "still_pending": ("Nothing changed: this purchase is still waiting for your answer.",
                      "Mikään ei muuttunut: tämä ostos odottaa yhä vastaustasi."),
}
# The effect of an answer (#382), built from the real difference of the overview's numbers before and
# after, within the answer length rule (two sentences, three numbers). {amount} is the purchase, {before}
# and {after} the number that moved; "why" says where the purchase went, and only says the reserve grows
# when it did. Safe to spend and safe to save are the same money seen two ways (#381): a text never adds them.
LABEL_EFFECT_TEXT: dict[str, tuple[str, str]] = {
    "moved": ("Your safe to spend this week goes from {before} to {after}: {amount} {why}.",
              "Tämän viikon turvallisesti käytettävissä oleva summa on nyt {after}, kun se oli {before}: "
              "{amount} {why}."),
    "basket": ("{amount} {why}.", "{amount} {why}."),
    "why_unexpected_reserve": ("now counts as an unexpected necessity, so the reserve grows",
                               "lasketaan nyt odottamattomaksi välttämättömäksi menoksi, joten varaus kasvaa"),
    "why_unexpected": ("now counts as an unexpected necessity",
                       "lasketaan nyt odottamattomaksi välttämättömäksi menoksi"),
    "why_everyday": ("now counts as everyday spending", "lasketaan nyt arjen kulutukseksi"),
    "why_pending": ("is waiting for your answer again", "odottaa taas vastaustasi"),
    "why_closed": ("is back in the group the rules give it", "on taas siinä ryhmässä, johon säännöt sen sijoittavat"),
    "save_moved": ("This week's safe to spend stays the same, but what you can typically put aside goes from "
                   "{before} to {after}.",
                   "Tämän viikon turvallisesti käytettävissä oleva summa pysyy samana, mutta tavallisesti "
                   "säästöön jäävä summa on nyt {after}, kun se oli {before}."),
    "same_budget": ("This does not change this week's safe to spend: your monthly budget, not this purchase, sets "
                    "the limit.",
                    "Tämä ei muuta tämän viikon turvallisesti käytettävissä olevaa summaa: kuukausibudjettisi, ei "
                    "tämä ostos, asettaa rajan."),
    "same_balance": ("This does not change this week's safe to spend: your balance sets the limit, and this "
                     "purchase is already in it.",
                     "Tämä ei muuta tämän viikon turvallisesti käytettävissä olevaa summaa: saldosi asettaa rajan, "
                     "ja tämä ostos näkyy siinä jo."),
}
# ---- the way to a human (#420, contract 0.3.3) ------------------------------------------------------
# The label of the `open_host_screen` action with target `contact_bank`: the bank's own contact screen,
# carried by every refusal and by a bill explanation with warning signs. It names the destination only.
HOST_CONTACT_BANK: tuple[str, str] = ("Contact S-Pankki", "Ota yhteyttä S-Pankkiin")


def contact_bank_action(language: str) -> dict[str, str]:
    """The action as the API sends it: type, label and target, nothing else (contracts/api.md section 3)."""
    return {"type": "open_host_screen", "label": label(HOST_CONTACT_BANK, language), "target": "contact_bank"}


# ---- S-Bonus what-if estimate (#158, docs/domain/s-group-benefits.md sections 4 and 6) -------------
# The rules and their numbers live in core/config/s_group_benefits.yaml only; these are the fixed texts.
# Nothing here names a store or says where the customer shops.
BONUS_TEXT: dict[str, tuple[str, str]] = {
    # #267: the step into the bank's own app; names the destination only (no fund, no advice, no returns)
    "host_bonus_to_fund": ("See Bonus to fund in S-mobiili", "Katso Bonus rahastoon S-mobiilissa"),
    "title": ("S-Bonus estimate", "S-Bonus-arvio"),
    "scenario": ("If {share} of your grocery spending went to S-Group stores",
                 "Jos {share} ruokaostoksistasi tehtäisiin S-ryhmän kaupoissa"),
    "grocery_month": ("Your grocery spending a month", "Ruokaostoksesi kuukaudessa"),
    "share_typed": ("Share at S-Group stores", "Osuus S-ryhmän kaupoissa"),
    "share_default": ("Assumed share at S-Group stores", "Oletettu osuus S-ryhmän kaupoissa"),
    "level_base": ("Purchases that set the Bonus level", "Bonustason määräävät ostot"),
    "bonus_percent": ("Bonus level", "Bonustaso"),
    "bonus_month": ("Bonus a month", "Bonus kuukaudessa"),
    "payment_benefit_month": ("Payment benefit a month", "Maksutapaetu kuukaudessa"),
    "total_month": ("Bonus and payment benefit a month", "Bonus ja maksutapaetu kuukaudessa"),
    "total_year": ("Bonus and payment benefit a year", "Bonus ja maksutapaetu vuodessa"),
    "lowest_level": ("Lowest Bonus level", "Alin Bonustaso"),
    "estimate_label": ("Estimate", "Arvio"),
    "estimate_text": (
        "A what-if on your own grocery spending, not a statement about where you shop.",
        "Laskelma omista ruokaostoksistasi, ei tieto siitä, missä asioit.",
    ),
    # Every assumption reads as one: nothing says the customer is a co-op member or shops anywhere.
    "assume_household": ("Assumes you are the only shopper in a co-op household.",
                         "Oletus: olisit osuuskaupan talouden ainoa ostaja."),
    "assume_table": ("Assumes the default Bonus table, not the KPO or Koillismaa table.",
                     "Oletus: tavallinen Bonustaulukko, ei KPO:n tai Koillismaan taulukko."),
    "assume_card": ("Assumes payment with an S-Etukortti Visa, which adds the payment benefit.",
                    "Oletus: maksu S-Etukortti Visalla, joka tuo maksutapaedun."),
    "assume_goods": ("Assumes none of it is alcohol, tobacco or lottery, which earn no Bonus.",
                     "Oletus: ostoksissa ei ole alkoholia, tupakkaa eikä arpoja, joista ei saa Bonusta."),
    "assume_share": ("Assumes the share at S-Group stores; it is a what-if, not a fact about where you shop.",
                     "Oletus: osuus S-ryhmän kaupoissa on laskelma, ei tieto siitä, missä asioit."),
    "reason_below_lowest": ("These purchases stay below the lowest Bonus level, so no Bonus would be paid.",
                            "Nämä ostot jäävät alimman Bonustason alle, joten Bonusta ei maksettaisi."),
    "how": ("How is this calculated?", "Miten tämä lasketaan?"),
}
BONUS_ASSUMPTIONS = ("assume_household", "assume_table", "assume_card", "assume_goods", "assume_share")

# ---- small purchases (#256, metrics.md section 12, 08_small_purchases.sql) --------------------------
# The flexible everyday categories whose small purchases are counted: the everyday_spending basket's
# categories except Travel (classify.basket_of). The default limit is a setting; the tool allows 1..25.
SMALL_PURCHASE_CATEGORIES: tuple[str, ...] = ("Entertainment", "Lifestyle", "Restaurants")
SMALL_PURCHASE_MAX_EUR = "10.00"     # euros, the default of max_amount (and 08's app.small_max)
SMALL_PURCHASE_MAX_RANGE = (1, 25)   # the allowed max_amount, in euros
SMALL_PURCHASE_MIN_COUNT = 5         # fewer small purchases: "not much here" (decision 5 of #256)
# The default period: the last 3 complete months; one month holds too few small purchases for any of the
# personas (coordinator, #256, after the persona data). 08_small_purchases.sql has the same default.
SMALL_PURCHASE_DEFAULT_PERIOD = "last_3_months"
# Where the small purchases of a category happen, as the takeaway sentence names them ("most of them at
# restaurants and cafés"); a category's label otherwise.
SMALL_PURCHASE_WHERE: dict[str, tuple[str, str]] = {
    "Restaurants": ("restaurants and cafés", "ravintoloissa ja kahviloissa"),
    "Entertainment": ("entertainment", "viihteessä"),
    "Lifestyle": ("lifestyle shopping", "lifestyle-ostoksissa"),
}
SMALL_PURCHASES_TEXT: dict[str, tuple[str, str]] = {
    "title": ("Small purchases", "Pienet ostokset"),
    "count": ("Small purchases", "Pieniä ostoksia"),
    "total": ("Small purchases in total", "Pienet ostokset yhteensä"),
    "average": ("Average small purchase", "Pienen ostoksen keskihinta"),
    "month_average": ("Small purchases a month", "Pieniä ostoksia kuukaudessa"),
    "share": ("Share of everyday spending", "Osuus arjen kulutuksesta"),
    "flexible": ("Everyday spending", "Arjen kulutus"),
    "max_amount": ("Largest amount counted as small", "Suurin pieneksi laskettu summa"),
    "category_share": ("Share of small purchases", "Osuus pienistä ostoksista"),
    "show": ("Show the purchases", "Näytä ostokset"),
    # The what-if question for the largest category, with no amount: the user says how much (#142).
    "action_label": ("What if I cut {what}?", "Kokeile vähentää: {what}"),
    "action_prompt": ("What if I cut {what}?", "Mitä jos vähentäisin kulutusta luokassa {what}?"),
}

# ---- the savings plan (#369, metrics.md section 13) ---------------------------------------------------
# "How could I save more?": a few cuts below the usual pace, from the what-if tool, with one total a month and
# a year. The two cut levers are always different categories, so nothing is counted twice; small purchases are
# no lever (in the data they are restaurant visits, which the first lever covers). The S-Bonus is never shown
# with the plan: its question is the answer's first follow-up (coordinator, #411). The bank button uses the one
# label of SAFE_TO_SAVE_TEXT["host_monthly_saving"] (#267).
SAVINGS_PLAN_FIRST = ("Restaurants", 20)             # eating out, cut by 20 %
SAVINGS_PLAN_OTHER_CATEGORIES = ("Entertainment", "Lifestyle", "Travel")   # the flexible everyday categories
SAVINGS_PLAN_OTHER_CUT_PCT = 10                     # the largest of them, cut by 10 %
SAVINGS_PLAN_MIN_EUR = Decimal("5.00")              # a lever counts only from 5 euros a month
SAVINGS_PLAN_METHODS = {"total_month": "savings_plan.total_month_eur@1", "total_year": "savings_plan.total_year_eur@1",
                        "cut_pct": "savings_plan.cut_pct@1"}
# A cut share in words, so no answer needs a digit for it; any other share is cited as its Number (#411).
SAVINGS_PLAN_CUT_WORDS: dict[int, tuple[str, str]] = {
    10: ("a tenth", "kymmenyksen"), 20: ("a fifth", "viidenneksen"), 25: ("a quarter", "neljänneksen"),
    50: ("half", "puolet"),
}
# No lever reaches the threshold: the baskets card, where the money goes (coordinator, #411), over the same
# window as the earlier save-more answer.
SAVINGS_PLAN_NONE_BASKETS = {"period": {"preset": "last_6_months"}}
SAVINGS_PLAN_TEXT: dict[str, tuple[str, str]] = {
    "title": ("Your savings plan", "Säästösuunnitelmasi"),
    "total_month": ("These changes together, a month", "Nämä muutokset yhteensä kuukaudessa"),
    "total_year": ("These changes together, a year", "Nämä muutokset yhteensä vuodessa"),
    # card rows in words: no digit outside a Number on the card (review of #411)
    "lever": ("{what}, {words} less", "{what}, {words} vähemmän"),
    "lever_no_words": ("{what}, less than usual", "{what}, tavallista vähemmän"),
    "cut": ("Cut in {what}", "Vähennys: {what}"),
    # the answer's first follow-up when the S-Bonus estimate is offered; the bonus rule claims it as written
    "bonus_follow_up": ("How much S-Bonus could I get?", "Paljonko S-Bonusta voisin saada?"),
    "estimate_label": ("Estimate", "Arvio"),
    "estimate_text": ("About, if you cut these as shown and the rest of your spending stays as it is.",
                      "Noin, jos vähennät näitä kuten näytetään ja muu kulutuksesi pysyy ennallaan."),
    "how": ("How is this calculated?", "Miten tämä lasketaan?"),
}
