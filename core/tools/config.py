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
    "unclassified": ("Unclassified", "Luokittelematon"),
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

TEXT: dict[str, tuple[str, str]] = {
    "spending": ("Spending", "Kulutus"),
    "income": ("Income", "Tulot"),
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
}
