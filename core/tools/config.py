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
    # get_peer_benchmark (metrics.md section 6, 06_peer_benchmark.sql): the customer's own value
    "peer_you": "peer_benchmark.you_month_eur@1",
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
PEER_MIN_N = "20"   # app.peer_min_n of 06: at least 20 other peers (metrics.md section 10, decision 7)

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
    "action_prompt": ("How could I spend less on {what}?", "Miten voisin kuluttaa vähemmän: {what}?"),
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
        "days to payday. It is also capped by your usual monthly budget. A recurring investment deposit "
        "is your own saving plan, so it is kept aside too.",
        "Saldosi miinus laskut, tavalliset välttämättömät menot ja pieni puskuri palkkapäivään asti, "
        "jaettuna päiville ennen palkkapäivää. Summaa rajaa myös tavallinen kuukausibudjettisi. "
        "Säännöllinen sijoitus on oma säästösuunnitelmasi, joten se pidetään myös sivussa.",
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
# ---- S-Bonus what-if estimate (#158, docs/domain/s-group-benefits.md sections 4 and 6) -------------
# The rules and their numbers live in core/config/s_group_benefits.yaml only; these are the fixed texts.
# Nothing here names a store or says where the customer shops.
BONUS_TEXT: dict[str, tuple[str, str]] = {
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
