"""User-facing strings of the API endpoints (English, Finnish) and what each method id means.

Product name strings are kept out of here on purpose: display strings that name the coach come from
one place in config when they are needed.
"""

from __future__ import annotations

from core.tools.models import Unit

Pair = tuple[str, str]


def pick(pair: Pair, language: str) -> str:
    return pair[1] if language == "fi" else pair[0]


ERRORS: dict[str, Pair] = {
    "invalid_request": ("The request is not valid.", "Pyyntö ei ole kelvollinen."),
    "customer_not_found": ("We couldn't find this customer.", "Asiakasta ei löytynyt."),
    "evidence_not_found": ("We couldn't find how this number was calculated.",
                           "Luvun laskentatapaa ei löytynyt."),
    "evidence_forbidden": ("This evidence belongs to another customer.", "Tämä tieto kuuluu toiselle asiakkaalle."),
    "invalid_scenario": ("This scenario cannot be calculated.", "Tätä tilannetta ei voi laskea."),
    # the default text; the endpoint sends the sentence of the reason (config.BILL_REFUSAL_TEXT, #242)
    "invalid_bill": ("This bill cannot be explained.", "Tätä laskua ei voi selittää."),
    "tx_ref_not_found": ("This question is not open.", "Tämä kysymys ei ole avoinna."),
    "basket_not_allowed": ("This answer is not one of the options for this question.",
                           "Tämä vastaus ei ole yksi tämän kysymyksen vaihtoehdoista."),
    "rate_limited": ("Too many requests. Please try again soon.", "Liian monta pyyntöä. Yritä pian uudelleen."),
    "data_unavailable": ("Your data is not available right now. Please try again.",
                         "Tietosi eivät ole juuri nyt saatavilla. Yritä uudelleen."),
    "llm_unavailable": ("Explanations are not available right now.", "Selitykset eivät ole juuri nyt saatavilla."),
    "model_unavailable": ("The bill cannot be read right now. You can type its details instead.",
                          "Laskua ei voi lukea juuri nyt. Voit kirjoittaa sen tiedot itse."),
    "internal": ("Something went wrong. Please try again.", "Jokin meni vikaan. Yritä uudelleen."),
    "not_found": ("There is nothing at this address.", "Tästä osoitteesta ei löydy mitään."),
}

AI_DISCLOSURE: Pair = (
    "Explanations are written by AI. The numbers are calculated from your transactions.",
    "Selitykset kirjoittaa tekoäly. Luvut lasketaan tilitapahtumistasi.",
)
GREETING: Pair = ("Hi {name}", "Hei {name}")
GREETING_NO_NAME: Pair = ("Hi", "Hei")
SUGGESTED_QUESTIONS: list[Pair] = [  # the partner's four questions
    ("Where did my money go?", "Mihin rahani menivät?"),
    ("What kind of spender am I?", "Millainen kuluttaja olen?"),
    ("What can I safely spend this week?", "Paljonko voin turvallisesti käyttää tällä viikolla?"),
    ("How could I save more?", "Miten voisin säästää enemmän?"),
]

PRIVACY_TRANSACTIONS: Pair = (
    "Only you can see these transactions. They are never sent to the AI model.",
    "Vain sinä näet nämä tapahtumat. Niitä ei koskaan lähetetä tekoälymallille.",
)
PRIVACY_COMPOSITE: Pair = (
    "Only you can see this. Transactions are never sent to the AI model.",
    "Vain sinä näet tämän. Tapahtumia ei koskaan lähetetä tekoälymallille.",
)
PRIVACY_PEER: Pair = (
    "Only group statistics are shown here, never another customer's transactions.",
    "Tässä näytetään vain ryhmän tilastoja, ei koskaan toisen asiakkaan tapahtumia.",
)
ROW_COUNT_LABEL: Pair = ("Transactions", "Tapahtumat")

# Profile labels: English from personas.yaml (the contract's labels); Finnish here.
PROFILE_LABELS_FI: dict[str, str] = {
    "not_enough_income_data": "Tulotiedot puuttuvat",
    "stretched": "Tiukka talous",
    "big_ticket": "Isot hankinnat",
    "everyday_heavy": "Arjen kuluttaja",
    "saver": "Säästäjä",
    "steady": "Vakaa",
}

METRICS_DOC = "docs/design/metrics.md"
DESIGN_DOC = "docs/design/agent-core.md"


class MethodInfo:
    def __init__(self, unit: Unit, name: Pair, summary: Pair, doc: str) -> None:
        self.unit, self.name, self.summary, self.doc = unit, name, summary, doc


METHODS: dict[str, MethodInfo] = {
    "spending.total@1": MethodInfo(
        Unit.EUR, ("Total spending", "Kulutus yhteensä"),
        ("Money spent in the chosen categories during the period.",
         "Valituissa luokissa jakson aikana käytetty raha."), DESIGN_DOC + "#62-data-tools"),
    "spending.n_tx@1": MethodInfo(
        Unit.COUNT, ("Number of transactions", "Tapahtumien määrä"),
        ("How many transactions the total is made of.", "Montako tapahtumaa summaan kuuluu."),
        DESIGN_DOC + "#62-data-tools"),
    "spending.change@1": MethodInfo(
        Unit.EUR, ("Change between two periods", "Muutos kahden jakson välillä"),
        ("The difference between spending in two periods.", "Kahden jakson kulutuksen erotus."),
        DESIGN_DOC + "#62-data-tools"),
    "spending.change_pct@1": MethodInfo(
        Unit.PERCENT, ("Change in percent", "Muutos prosentteina"),
        ("The difference between two periods as a share of the earlier one.",
         "Kahden jakson erotus suhteessa aiempaan jaksoon."), DESIGN_DOC + "#62-data-tools"),
    "spending.share_pct@1": MethodInfo(
        Unit.PERCENT, ("Share of the total", "Osuus kokonaisuudesta"),
        ("One part of spending as a share of the total.", "Kulutuksen osa suhteessa kokonaisuuteen."),
        DESIGN_DOC + "#62-data-tools"),
    "evidence.row_count@1": MethodInfo(
        Unit.COUNT, ROW_COUNT_LABEL, ("The number of transactions shown.", "Näytettyjen tapahtumien määrä."),
        DESIGN_DOC + "#62-data-tools"),
    "baskets.total_eur@1": MethodInfo(
        Unit.EUR, ("Basket total", "Korin summa"),
        ("Spending in one basket during the period.", "Yhden korin kulutus jakson aikana."),
        METRICS_DOC + "#1-three-baskets"),
    "baskets.month_avg_eur@1": MethodInfo(
        Unit.EUR_PER_MONTH, ("Monthly average of a basket", "Korin kuukausikeskiarvo"),
        ("Spending in one basket divided by the months with history.",
         "Yhden korin kulutus jaettuna kuukausilla, joilta on tietoja."), METRICS_DOC + "#1-three-baskets"),
    "baskets.share_pct@1": MethodInfo(
        Unit.PERCENT, ("Share of spending", "Osuus kulutuksesta"),
        ("One basket as a share of all spending.", "Yksi kori osuutena koko kulutuksesta."),
        METRICS_DOC + "#1-three-baskets"),
    "spender_profile.spend_month_eur@1": MethodInfo(
        Unit.EUR_PER_MONTH, ("Spending per month", "Kulutus kuukaudessa"),
        ("All spending divided by the months with history.", "Koko kulutus jaettuna kuukausilla, joilta on tietoja."),
        METRICS_DOC + "#5-spender-profile"),
    "recurring.typical_month_eur@1": MethodInfo(
        Unit.EUR_PER_MONTH, ("Usual monthly amount", "Tavallinen kuukausisumma"),
        ("The middle value of the monthly totals of a recurring payment.",
         "Toistuvan maksun kuukausisummien keskimmäinen arvo."), METRICS_DOC + "#2-recurring-bills"),
    "safe_to_spend.bill_due_eur@1": MethodInfo(
        Unit.EUR, ("Due before payday", "Erääntyy ennen palkkapäivää"),
        ("A bill's usual amount for each due date before payday, or a share of it when it is paid "
         "several times a month.",
         "Laskun tavallinen summa jokaiselle eräpäivälle ennen palkkapäivää, tai osuus siitä, jos se "
         "maksetaan useita kertoja kuussa."), METRICS_DOC + "#3-safe-to-spend"),
    "safe_to_spend.bills_due_eur@1": MethodInfo(
        Unit.EUR, ("Bills before payday", "Laskut ennen palkkapäivää"),
        ("All bills due after today and up to payday.", "Kaikki tämän päivän jälkeen palkkapäivään mennessä "
                                                         "erääntyvät laskut."), METRICS_DOC + "#3-safe-to-spend"),
    "balance_forecast.daily_pace_eur@1": MethodInfo(
        Unit.EUR_PER_DAY, ("Usual spending a day", "Tavallinen kulutus päivässä"),
        ("Everyday spending and essentials without bills, per day, in each of the last three full months; "
         "the middle one of the three.",
         "Arkikulutus ja välttämättömät menot ilman laskuja päivää kohden kolmena viimeisenä täytenä "
         "kuukautena; kolmesta keskimmäinen."), METRICS_DOC + "#33-balance-forecast-until-payday-257"),
    "balance_forecast.bills_to_date_eur@1": MethodInfo(
        Unit.EUR, ("Bills due by then", "Siihen mennessä erääntyvät laskut"),
        ("The bills before payday that fall due after today and up to this day.",
         "Ennen palkkapäivää erääntyvät laskut, jotka erääntyvät tämän päivän jälkeen tähän päivään mennessä."),
        METRICS_DOC + "#33-balance-forecast-until-payday-257"),
    "balance_forecast.balance_eur@1": MethodInfo(
        Unit.EUR, ("Balance on a day before payday", "Saldo päivänä ennen palkkapäivää"),
        ("Today's balance minus the bills due by that day and the usual spending a day for each day.",
         "Tämän päivän saldo miinus siihen mennessä erääntyvät laskut ja tavallinen päiväkulutus jokaiselta "
         "päivältä."), METRICS_DOC + "#33-balance-forecast-until-payday-257"),
}


def _metric(unit: Unit, en: str, fi: str, file: str, section: str) -> MethodInfo:
    return MethodInfo(unit, (en, fi), (f"Calculated by core/metrics/{file}.", f"Laskettu tiedostolla core/metrics/{file}."),
                      METRICS_DOC + section)


# Numbers of the safe-to-spend and what-if tools (#55), re-run from their metric files (evidence kind "metric").
for _col, _unit, _en, _fi in [
    ("safe_to_spend_7d_eur", Unit.EUR, "Safe to spend", "Turvallisesti käytettävissä"),
    ("free_until_payday_eur", Unit.EUR, "Free until payday", "Vapaana palkkapäivään asti"),
    ("balance_limit_7d_eur", Unit.EUR, "Your balance allows", "Saldosi sallii"),
    ("budget_limit_7d_eur", Unit.EUR, "Your monthly budget allows", "Kuukausibudjettisi sallii"),
    ("balance_eur", Unit.EUR, "Balance", "Saldo"),
    ("essentials_reserve_eur", Unit.EUR, "Essentials reserve", "Välttämättömien varaus"),
    ("irregular_reserve_eur", Unit.EUR, "Irregular reserve", "Odottamattomien varaus"),
    ("cushion_eur", Unit.EUR, "Cushion", "Puskuri"),
    ("savings_goal_eur", Unit.EUR_PER_MONTH, "Savings goal set aside first", "Ensin sivuun laitettava säästötavoite"),
]:
    METHODS[f"safe_to_spend.{_col}@1"] = _metric(_unit, _en, _fi, "03_safe_to_spend.sql", "#3-safe-to-spend")
METHODS["safe_to_save.week_eur@1"] = MethodInfo(
    Unit.EUR_PER_WEEK, ("Typically left each week", "Tavallisesti jää viikossa"),
    ("What a typical month leaves, per week (x 7 / 30.4375).",
     "Mitä tavallisesta kuukaudesta jää, viikkoa kohden (x 7 / 30,4375)."), METRICS_DOC + "#31-safe-to-save-33")
METHODS["safe_to_save.day_eur@1"] = MethodInfo(
    Unit.EUR_PER_DAY, ("Typically left each day", "Tavallisesti jää päivässä"),
    ("What a typical month leaves, per day (/ 30.4375).",
     "Mitä tavallisesta kuukaudesta jää, päivää kohden (/ 30,4375)."), METRICS_DOC + "#31-safe-to-save-33")
METHODS["safe_to_spend.usual_week_eur@1"] = MethodInfo(
    Unit.EUR_PER_WEEK, ("Usual everyday pace", "Tavallinen arkikulutuksen tahti"),
    ("Usual everyday spending in a typical month of the last six, per week (x 7 / 30.4375).",
     "Tavallinen arkikulutus kuuden viime kuukauden tavallisessa kuukaudessa viikkoa kohden (x 7 / 30,4375)."),
    METRICS_DOC + "#3-safe-to-spend")
# Safe to save (#165), output columns of the same file (metrics.md section 3.1).
for _col, _unit, _en, _fi in [
    ("safe_to_save_monthly_eur", Unit.EUR_PER_MONTH, "Typically left each month", "Tavallisesti jää kuukaudessa"),
    ("free_month_eur", Unit.EUR_PER_MONTH, "Free in a typical month", "Vapaana tavallisessa kuukaudessa"),
    ("everyday_month_eur", Unit.EUR_PER_MONTH, "Everyday spending in a typical month",
     "Arkikulutus tavallisessa kuukaudessa"),
    ("essentials_shortfall_month_eur", Unit.EUR_PER_MONTH, "Bills, essentials and the reserve above income",
     "Laskut, välttämättömät menot ja varaus ylittävät tulot"),
    ("safe_to_save_eur", Unit.EUR, "In your account beyond what you need until payday",
     "Tililläsi yli sen, mitä tarvitset palkkapäivään asti"),
    ("everyday_until_payday_eur", Unit.EUR, "Everyday spending until payday", "Arkikulutus palkkapäivään asti"),
    ("save_reason_month_eur", Unit.EUR_PER_MONTH, "Why a typical month leaves nothing",
     "Miksi tavallisesta kuukaudesta ei jää mitään"),
]:
    METHODS[f"safe_to_spend.{_col}@1"] = _metric(_unit, _en, _fi, "03_safe_to_spend.sql", "#31-safe-to-save-33")
for _col, _unit, _en, _fi in [
    ("baseline_month_eur", Unit.EUR_PER_MONTH, "Usual spending per month", "Tavallinen kulutus kuukaudessa"),
    ("saving_month_eur", Unit.EUR_PER_MONTH, "Saving per month", "Säästö kuukaudessa"),
    ("saving_week_eur", Unit.EUR_PER_WEEK, "Saving per week", "Säästö viikossa"),
    ("saving_year_eur", Unit.EUR_PER_YEAR, "Saving per year", "Säästö vuodessa"),
    ("one_off_excluded_eur", Unit.EUR, "One-offs left out", "Pois jätetyt kertaostot"),
    ("regular_excluded_eur", Unit.EUR, "Regular essentials left out", "Pois jätetyt säännölliset menot"),
]:
    METHODS[f"what_if.{_col}@1"] = _metric(_unit, _en, _fi, "04_what_if.sql", "#4-what-if-savings")
# Spender profile features (#69), re-run from 05 (evidence kind "metric"). spend_month_eur is above: it is
# the basket card's own Number over the window's spending rows.
for _col, _unit, _en, _fi in [
    ("keep_rate_pct", Unit.PERCENT, "Share of income kept", "Tuloista jäljelle jäävä osuus"),
    ("net_income_month_eur", Unit.EUR_PER_MONTH, "Income per month", "Tulot kuukaudessa"),
    ("saving_month_eur", Unit.EUR_PER_MONTH, "Saving and investing per month", "Säästäminen ja sijoittaminen kuukaudessa"),
    ("regular_share_pct", Unit.PERCENT, "Share of regular essentials", "Säännöllisten menojen osuus"),
    ("unexpected_share_pct", Unit.PERCENT, "Share of unexpected necessities", "Odottamattomien menojen osuus"),
    ("everyday_share_pct", Unit.PERCENT, "Share of everyday spending", "Arjen kulutuksen osuus"),
    ("one_off_share_pct", Unit.PERCENT, "Share of one-off purchases", "Kertaostosten osuus"),
    ("everyday_weekend_pct", Unit.PERCENT, "Everyday spending at weekends", "Arjen kulutus viikonloppuisin"),
    ("everyday_avg_ticket_eur", Unit.EUR, "Average everyday purchase", "Arjen ostoksen keskihinta"),
    ("everyday_tx_month", Unit.COUNT, "Everyday purchases per month", "Arjen ostoksia kuukaudessa"),
    ("months_out_over_in", Unit.MONTHS, "Months with more out than in", "Kuukaudet, joina menoja oli tuloja enemmän"),
    ("n_tx_below_zero", Unit.COUNT, "Payments that took the balance below zero", "Maksut, jotka veivät saldon miinukselle"),
]:
    METHODS[f"spender_profile.{_col}@1"] = _metric(_unit, _en, _fi, "05_spender_profile.sql", "#5-spender-profile")
# Peer benchmark (#69): the group statistics are re-run from 06 (evidence kind "peer_aggregate").
for _col, _unit, _en, _fi in [
    ("peer_median_month_eur", Unit.EUR_PER_MONTH, "Typical for similar people", "Tyypillinen samankaltaisille"),
    ("peer_p25_month_eur", Unit.EUR_PER_MONTH, "Lower quarter of similar people", "Samankaltaisten alaneljännes"),
    ("peer_p75_month_eur", Unit.EUR_PER_MONTH, "Upper quarter of similar people", "Samankaltaisten yläneljännes"),
    ("percentile", Unit.PERCENTILE, "Your place among similar people", "Sijaintisi samankaltaisten joukossa"),
    ("vs_median_pct", Unit.PERCENT, "Difference from typical", "Ero tyypilliseen"),
    ("peer_n", Unit.COUNT, "Similar people compared", "Verrattuja samankaltaisia"),
]:
    METHODS[f"peer_benchmark.{_col}@1"] = _metric(_unit, _en, _fi, "06_peer_benchmark.sql", "#6-peer-benchmark")
METHODS["peer_benchmark.you_month_eur@1"] = MethodInfo(
    Unit.EUR_PER_MONTH, ("You per month", "Sinä kuukaudessa"),
    ("Your own spending in the compared group, divided by the months with history.",
     "Oma kulutuksesi vertailtavassa ryhmässä jaettuna kuukausilla, joilta on tietoja."),
    METRICS_DOC + "#6-peer-benchmark")

# S-Bonus what-if estimate (#158): composites of the grocery month average and the rules file.
BONUS_DOC = "docs/domain/s-group-benefits.md#4-how-the-coach-can-estimate-s-bonus-a-what-if-only"
for _id, _unit, _name, _summary in [
    ("share_pct", Unit.PERCENT, ("Assumed share at S-Group stores", "Oletettu osuus S-ryhmän kaupoissa"),
     ("The what-if share of grocery spending, from the rules file when not given.",
      "Ruokaostosten oletettu osuus; sääntötiedostosta, ellei sitä anneta.")),
    ("level_base_eur", Unit.EUR_PER_MONTH, ("Purchases that set the Bonus level", "Bonustason määräävät ostot"),
     ("Grocery spending a month times the what-if share.", "Ruokaostokset kuukaudessa kertaa oletettu osuus.")),
    ("bonus_percent", Unit.PERCENT, ("Bonus level", "Bonustaso"),
     ("The percentage of the highest row of the default Bonus table at or below those purchases.",
      "Tavallisen Bonustaulukon korkeimman tason prosentti, jonka raja ei ylitä ostoja.")),
    ("bonus_month_eur", Unit.EUR_PER_MONTH, ("Bonus a month", "Bonus kuukaudessa"),
     ("The Bonus percentage of those purchases.", "Bonusprosentti näistä ostoista.")),
    ("payment_benefit_month_eur", Unit.EUR_PER_MONTH, ("Payment benefit a month", "Maksutapaetu kuukaudessa"),
     ("The payment benefit rate of those purchases, paid with an S-Etukortti Visa.",
      "Maksutapaedun osuus näistä ostoista S-Etukortti Visalla maksettuna.")),
    ("total_month_eur", Unit.EUR_PER_MONTH, ("Bonus and payment benefit a month", "Bonus ja maksutapaetu kuukaudessa"),
     ("The Bonus and the payment benefit together.", "Bonus ja maksutapaetu yhteensä.")),
    ("total_year_eur", Unit.EUR_PER_YEAR, ("Bonus and payment benefit a year", "Bonus ja maksutapaetu vuodessa"),
     ("The monthly sum times twelve.", "Kuukausisumma kertaa kaksitoista.")),
    ("lowest_level_eur", Unit.EUR_PER_MONTH, ("Lowest Bonus level", "Alin Bonustaso"),
     ("The purchases a month the lowest row of the default Bonus table needs.",
      "Ostot kuukaudessa, joita tavallisen Bonustaulukon alin taso edellyttää.")),
]:
    METHODS[f"bonus_estimate.{_id}@1"] = MethodInfo(_unit, _name, _summary, BONUS_DOC)

# The bill explanation (#242, contracts/api.md section 11; the rules in metrics.md section 3.4). The two
# input methods appear in an evidence view only as the inline part of a bill composite: an amount in euros.
BILL_DOC = METRICS_DOC + "#34-a-bill-and-safe-to-spend-242"
for _id, _unit, _name, _summary in [
    ("user_input@1", Unit.EUR, ("Typed by you", "Itse kirjoitettu"),
     ("A value you typed or confirmed.", "Arvo, jonka kirjoitit tai vahvistit.")),
    ("bill_barcode@1", Unit.EUR, ("Read from the bill's barcode", "Luettu laskun viivakoodista"),
     ("A value read from the bill's virtual barcode and checked by code.",
      "Laskun virtuaaliviivakoodista luettu ja koodilla tarkistettu arvo.")),
    ("bill.vs_typical_eur@1", Unit.EUR, ("Difference from the usual amount", "Ero tavalliseen summaan"),
     ("The bill's amount minus the typical monthly amount of the same bill.",
      "Laskun summa miinus saman laskun tavallinen kuukausisumma.")),
    ("bill.vs_typical_pct@1", Unit.PERCENT, ("Difference from the usual amount", "Ero tavalliseen summaan"),
     ("The difference from the typical monthly amount, in percent of it.",
      "Ero tavalliseen kuukausisummaan prosentteina siitä.")),
    ("bill.counted_eur@1", Unit.EUR, ("Added to the bills before payday", "Lisätään laskuihin ennen palkkapäivää"),
     ("The bill's amount, or only its excess over what is already counted for the same bill before payday.",
      "Laskun summa tai vain se osa, joka ylittää saman laskun jo laskuihin ennen palkkapäivää lasketun summan.")),
    ("bill.free_until_payday_after_eur@1", Unit.EUR,
     ("Free until payday after the bill", "Vapaana palkkapäivään asti laskun jälkeen"),
     ("Free until payday minus what the bill adds to the bills before payday.",
      "Palkkapäivään asti vapaana oleva summa miinus se, mitä lasku lisää laskuihin ennen palkkapäivää.")),
    ("bill.safe_to_spend_after_eur@1", Unit.EUR,
     ("Safe to spend after the bill", "Turvallisesti käytettävissä laskun jälkeen"),
     ("The smaller of the balance limit, recomputed with the bill, and the monthly budget limit.",
      "Pienempi kahdesta: laskun kanssa uudelleen laskettu saldoraja ja kuukausibudjetin raja.")),
    ("bill.forecast_counted_eur@1", Unit.EUR, ("Taken from the forecast by the bill", "Lasku vie ennusteesta"),
     ("The bill's amount, or only its excess over what the balance forecast already subtracts for the same bill "
      "by the due date.",
      "Laskun summa tai vain se osa, joka ylittää sen, mitä saldoennuste vähentää samasta laskusta jo "
      "eräpäivään mennessä.")),
    ("bill.forecast_after_eur@1", Unit.EUR, ("Forecast balance after the bill", "Ennustettu saldo laskun jälkeen"),
     ("The forecast balance on the due date minus what the bill takes from it.",
      "Ennustettu saldo eräpäivänä miinus se, mitä lasku siitä vie.")),
    ("bill.forecast_shortfall_eur@1", Unit.EUR, ("Short of the bill", "Laskusta puuttuu"),
     ("What the bill takes from the forecast minus the forecast balance on the due date.",
      "Se, mitä lasku vie ennusteesta, miinus ennustettu saldo eräpäivänä.")),
]:
    METHODS[_id] = MethodInfo(_unit, _name, _summary, BILL_DOC)
# Small purchases (#256): the output columns of 08_small_purchases.sql, metrics.md section 12.
SMALL_DOC = METRICS_DOC + "#12-small-purchases-256"
for _id, _unit, _name, _summary in [
    ("count", Unit.COUNT, ("Small purchases", "Pieniä ostoksia"),
     ("Purchases in restaurants, entertainment and lifestyle of at most the small amount, in the period.",
      "Ravintola-, viihde- ja elämäntapaostokset, enintään pienen summan suuruiset, jakson aikana.")),
    ("total_eur", Unit.EUR, ("Small purchases in total", "Pienet ostokset yhteensä"),
     ("The sum of those small purchases.", "Näiden pienten ostosten summa.")),
    ("avg_eur", Unit.EUR, ("Average small purchase", "Pienen ostoksen keskihinta"),
     ("The total divided by the number of small purchases.", "Summa jaettuna pienten ostosten määrällä.")),
    ("month_avg_eur", Unit.EUR_PER_MONTH, ("Small purchases a month", "Pieniä ostoksia kuukaudessa"),
     ("The total divided by the number of whole months in the period.",
      "Summa jaettuna jakson kokonaisten kuukausien määrällä.")),
    ("share_pct", Unit.PERCENT, ("Share", "Osuus"),
     ("A part of a total, in percent: the small purchases of everyday spending, or a category of the small "
      "purchases.", "Osa kokonaisuudesta prosentteina: pienet ostokset arjen kulutuksesta tai luokka pienistä "
      "ostoksista.")),
    ("flexible_total_eur", Unit.EUR, ("Everyday spending", "Arjen kulutus"),
     ("Everyday spending in the period, refunds netted.", "Arjen kulutus jakson aikana, palautukset vähennettyinä.")),
    ("max_amount_eur", Unit.EUR, ("Largest amount counted as small", "Suurin pieneksi laskettu summa"),
     ("The limit a purchase must not exceed to count as small.", "Raja, jota pieneksi laskettu ostos ei ylitä.")),
]:
    METHODS[f"small_purchases.{_id}@1"] = MethodInfo(_unit, _name, _summary, SMALL_DOC)

# The savings plan (#369, metrics.md section 13): the sum of its cut levers, each a what-if saving.
PLAN_DOC = METRICS_DOC + "#13-savings-plan-369"
METHODS["savings_plan.total_month_eur@1"] = MethodInfo(
    Unit.EUR_PER_MONTH, ("These changes together, a month", "Nämä muutokset yhteensä kuukaudessa"),
    ("The sum of the plan's cuts, each the what-if saving of a different category, so nothing is counted twice.",
     "Suunnitelman vähennysten summa; kukin on eri luokan mitä jos -säästö, joten mitään ei lasketa kahdesti."),
    PLAN_DOC)
METHODS["savings_plan.total_year_eur@1"] = MethodInfo(
    Unit.EUR_PER_YEAR, ("These changes together, a year", "Nämä muutokset yhteensä vuodessa"),
    ("The monthly total times twelve.", "Kuukausisumma kertaa kaksitoista."), PLAN_DOC)
METHODS["savings_plan.cut_pct@1"] = MethodInfo(
    Unit.PERCENT, ("Cut share", "Vähennyksen osuus"),
    ("How much of a category's usual spending the plan cuts, a setting of the plan.",
     "Kuinka suuren osan luokan tavallisesta kulutuksesta suunnitelma vähentää; suunnitelman asetus."),
    PLAN_DOC)
# What already goes to savings, beside the plan (#560): never part of the plan's total.
METHODS["savings_plan.already_share_pct@1"] = MethodInfo(
    Unit.PERCENT, ("Share of your income", "Osuus tuloistasi"),
    ("The typical month of the regular transfer to savings or investments, as a share of the typical monthly "
     "income; both are the recurring series' own typical months.",
     "Säännöllisen säästö- tai sijoitussiirron tavallinen kuukausi osuutena tavallisen kuukauden tuloista; "
     "molemmat ovat toistuvien sarjojen omia tavallisia kuukausia."),
    PLAN_DOC)
METHODS["savings_plan.already_month_eur@1"] = MethodInfo(
    Unit.EUR_PER_MONTH, ("Already goes to savings, a month", "Säästöihin menee jo kuukaudessa"),
    ("The sum of the typical months of the regular transfers to savings or investments, when there are several.",
     "Säännöllisten säästö- tai sijoitussiirtojen tavallisten kuukausien summa, kun niitä on useita."),
    PLAN_DOC)
METHODS["savings_plan.income_month_eur@1"] = MethodInfo(
    Unit.EUR_PER_MONTH, ("Your income, a typical month", "Tulosi tavallisena kuukautena"),
    ("The sum of the typical months of the income series, when there are several.",
     "Tulosarjojen tavallisten kuukausien summa, kun niitä on useita."),
    PLAN_DOC)

# The peer group a peer_aggregate compares with (06_peer_benchmark.sql `peer_level`).
PEER_LEVELS: dict[str, Pair] = {
    "age_band+area3": ("same age group and postal area", "sama ikäryhmä ja postinumeroalue"),
    "age_band+city": ("same age group and city", "sama ikäryhmä ja kaupunki"),
    "age_band": ("same age group", "sama ikäryhmä"),
    "all": ("all customers", "kaikki asiakkaat"),
}


def method_info(method: str) -> MethodInfo:
    """Known methods from the table; any other method (for example from a newer tool) still gets a
    plain name and a unit guessed from its id, so its evidence opens instead of failing."""
    if method in METHODS:
        return METHODS[method]
    base = method.split("@", 1)[0]
    if "percentile" in base:
        unit = Unit.PERCENTILE
    elif "pct" in base or "percent" in base:
        unit = Unit.PERCENT
    elif base.endswith("_month_eur"):
        unit = Unit.EUR_PER_MONTH
    elif base.endswith(("n_tx", "_n", "count", "visits")) or ".n_" in base:
        unit = Unit.COUNT
    else:
        unit = Unit.EUR
    name = base.replace("_", " ").replace(".", ": ")
    return MethodInfo(unit, (name, name), ("", ""), METRICS_DOC)
