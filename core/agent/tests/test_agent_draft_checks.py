"""The model-draft checks of #398, #418 and #419 against the review table of #437: each check rejects the
named bad forms and passes ordinary drafts, negations and data statements. No database."""

from __future__ import annotations

from decimal import Decimal

import pytest
from agent_fakes import AUG

from core.agent.validator import Allowed, check_text, contents_claim, draft_problems
from core.answer_text import borrowing_suggestion
from core.tools.formatting import display
from core.tools.models import Number, Unit


def _n(i, value, unit, method, label):
    return Number(id=i, value=value, unit=unit, period=AUG, method=method, evidence_ref="ev_x", label=label,
                  display=display(Decimal(str(value)), unit, "en"))


NUMBERS = {
    "n1": _n("n1", 1146.05, Unit.EUR, "spending.total@1", "Total spending"),
    "n2": _n("n2", 64, Unit.COUNT, "spending.count@1", "Transactions"),
    "n3": _n("n3", 45.91, Unit.EUR_PER_MONTH, "what_if.saving_month_eur@1", "Saving"),
    "n5": _n("n5", 1.2, Unit.PERCENT, "peer_benchmark.vs_median_pct@1", "Compared with typical"),
    "n7": _n("n7", 850.0, Unit.EUR, "spending.total@1", "Housing"),
}


def problems(text):
    return draft_problems(text, NUMBERS, has_data=True)


def has(text, needle):
    return any(needle in p for p in problems(text))


# ---- 1. cutting a regular essential: suggestions only, no negations, no "lower" -------------------------------

@pytest.mark.parametrize("text", [
    "August 2026 cost {{n1}}. Want to see what cutting housing would do?",          # the stand's row 9
    "You could cut your rent to save more.",
    "Try reducing your insurance this month.",
    "Consider cutting back on housing.",
    "Cut your rent where you can.",
    "Voisit vähentää asumiskuluja.",
    "Kokeile leikata vuokraa.",
    "Why not cut your rent a little?",
    "Maybe trim your insurance a little.",
    "Try to bring down your rent.",
    "By cutting your rent you would save {{n3}}.",
    "Tinkimällä vuokrasta säästäisit {{n3}}.",
])
def test_a_suggestion_to_cut_a_regular_essential_is_rejected(text):
    assert has(text, "never suggest cutting"), problems(text)


@pytest.mark.parametrize("text", [
    "Regular essentials, such as housing, are not cut in a what-if, so there is nothing to cut here.",
    "There is nothing to cut in housing, because it is a regular essential.",
    "I can't cut your housing in a what-if; restaurants could save {{n3}} a month.",
    "Regular essentials are not cut in a what-if, so there is nothing to cut in this selection.",
    "Säännöllisiä välttämättömiä menoja ei leikata, joten tässä valinnassa ei ole leikattavaa.",
    "Ravintoloista voisi säästää {{n3}} kuukaudessa, mutta asumista ei voi vähentää laskelmassa.",
    "Your spending was lower than usual, and rent stayed as planned.",
    "Your bills are lower than usual, with rent at {{n7}}.",
    "Cutting dining out by 20% saves {{n3}}; your rent stays at {{n7}}.",
    "You cut spending on restaurants and housing stayed at {{n7}}.",
    "You could cut restaurants; your rent stays at {{n7}}.",
    "You could cut restaurants and rent stays at {{n7}}.",
])
def test_a_statement_about_essentials_is_not_a_cut_suggestion(text):
    assert not has(text, "never suggest cutting"), problems(text)


# ---- 2. a count without its noun: only the stand's shape -------------------------------------------------------

@pytest.mark.parametrize("text", [
    "August 2026 cost {{n1}} across {{n2}}.",                                        # the stand's row 2
    "You spent {{n1}} over {{n2}}, more than usual.",
    "Elokuussa 2026 käytit {{n1}} yhteensä {{n2}}.",
])
def test_a_count_after_across_or_over_with_no_noun_is_rejected(text):
    assert has(text, "a count keeps its noun"), problems(text)


@pytest.mark.parametrize("text", [
    "Elokuussa 2026 käytit {{n1}}, ja tapahtumia oli {{n2}}.",
    "In August 2026 you spent {{n1}}, and the number of transactions was {{n2}}.",
    "Elokuussa 2026 käytit {{n1}}, ja tapahtumien määrä oli {{n2}}.",
    "August 2026 cost {{n1}} over {{n2}} visits, more than usual.",
    "You made {{n2}} purchases in August 2026.",
])
def test_a_count_with_its_noun_before_or_after_passes(text):
    assert not has(text, "a count keeps its noun"), problems(text)


# ---- 3, 4. the same value twice is no longer a rejection; a token cited twice is -------------------------------

def test_two_numbers_with_the_same_value_pass():
    numbers = dict(NUMBERS, n8=_n("n8", 1146.05, Unit.EUR, "spending.total@1", "Bills"))
    assert draft_problems("Your bills were {{n8}}, and all your spending was {{n1}}.", numbers, has_data=True) == []


def test_a_token_cited_twice_is_rejected():
    assert has("August 2026 cost {{n1}}. This is mainly because your budget allows {{n1}}.", "cite each number once")


# ---- 5, 6. ranking words next to a peer number -----------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "You spend {{n5}} than the median of people like you, putting you near the top.",
    "You spend {{n5}} than the median, better than 60% of people.",
    "You spend {{n5}} than the median. You beat most people.",
    "Kulutat {{n5}} kuin kaltaisesi, parempi kuin useimmat.",
    "Kulutat {{n5}} kuin kaltaisesi, joten olet kärjessä.",
    "You spend {{n5}} than the median. You're the best saver in your group.",
    "You spend {{n5}} than the median, among the best of people like you.",
])
def test_ranking_words_next_to_a_peer_number_are_rejected(text):
    assert has(text, "no ranking words"), problems(text)


@pytest.mark.parametrize("text", [
    "You spend {{n5}} than the median of people like you; the top category is restaurants.",
    "You spend {{n5}} than the median of people like you; restaurants are in the top category.",
    "Kulutat parhaillaan {{n5}} kuin kaltaisesi.",
    "You spend {{n5}} than the median of people like you; the best way to see why is a what-if.",
    "Kulutat {{n5}} kuin kaltaisesi; paras tapa nähdä syy on laskelma.",
    "You spend {{n5}} than the median of people like you, and a what-if can show what a cut would save.",
])
def test_a_peer_comparison_without_ranking_words_passes(text):
    assert not has(text, "no ranking words"), problems(text)


# ---- 5, 6. borrowing: the named forms, negations and data statements --------------------------------------------

@pytest.mark.parametrize("text", [
    "Ota laina.",
    "A credit card could cover the gap.",
    "A short-term loan could help here.",
    "A personal loan is one option.",
    "Your bank offers an overdraft of {{n1}}.",
    "Financing the purchase is possible.",
    "Lainaa rahaa kaverilta.",
    "Maksa tämä tililuotolla.",
    "You could take out a small loan to cover the repair.",
    "Consider using your credit card and pay it later.",
    "Voit ottaa lainaa korjaukseen.",
    "Why not take out a loan?",
    "Don't hesitate to use your credit card.",
    "It's not a bad idea to take a loan.",
    "Miksi et ottaisi lainaa?",
    "You can't go wrong if you take a loan.",
    "I don't see why you wouldn't take a loan.",
    "I would suggest an overdraft.",
    "No need to wait: take out a small loan.",
    "If you do not have enough, consider a loan.",
    "Instead of waiting, take out a loan.",
    "Älä odota, ota lainaa.",
    "Sinun ei tarvitse säästää, ota lainaa.",
    "You asked about it. Take out a small loan.",
    "There is no reason not to take a loan.",
    "There is no reason to hesitate to take a loan.",
])
def test_a_borrowing_suggestion_is_found(text):
    assert borrowing_suggestion(text) is not None, text


@pytest.mark.parametrize("text", [
    "I can't recommend taking a loan.",
    "I would not use a credit card for this.",
    "Sentti does not suggest using credit.",
    "Älä ota lainaa tähän.",
    "En ottaisi lainaa tähän.",
    "You spent {{n1}} using your credit card in August 2026.",
    "You can get your credit card statement from the bank app.",
    "Your pay later purchases cost {{n1}}.",
    "I can't predict whether a loan or mortgage would be approved, and I don't rate creditworthiness.",
    "En voi ennustaa, myönnetäänkö laina tai asuntolaina, enkä arvioi luottokelpoisuutta.",
    "You asked whether to take a loan; I can't advise on that.",
    "You asked whether you should use a credit card; I can't recommend one.",
    "You asked about taking a loan, which I can't recommend.",
    "Whether to take a loan is a decision I can't help with.",
    "Taking a loan is not something I suggest.",
    "Kysyit, kannattaako ottaa lainaa; en voi neuvoa siinä.",
    "En voi neuvoa, kannattaako ottaa lainaa.",
    "I wouldn't take a loan for this.",
    "You asked whether to take a loan. I can't recommend that; safe to spend is {{n1}}.",
    "Kysyit, kannattaako ottaa lainaa. En voi neuvoa siinä.",
    "There is no reason to take a loan; saving {{n3}} is enough.",
    "There is no reason to take out a loan for this.",
    "Ei ole syytä ottaa lainaa; turvallisesti käytettävissä on {{n1}}.",
])
def test_a_negation_or_a_data_statement_is_not_a_borrowing_suggestion(text):
    assert borrowing_suggestion(text) is None, (text, borrowing_suggestion(text))


# ---- 5, 6. a number as a sum ----------------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "That figure is {{n1}} combined with your bills in August 2026.",               # the stand's row 1
    "Together they make {{n1}}.",
    "Together these come to {{n1}}.",
    "Your bills and groceries add up to {{n1}}.",
])
def test_a_number_explained_as_a_sum_is_rejected(text):
    assert has(text, "sum or combination"), problems(text)


@pytest.mark.parametrize("text", [
    "Your income, combined with lower bills, leaves {{n1}}.",
    "The sum of money safe to spend is {{n1}}.",
])
def test_a_plain_sentence_with_combined_or_sum_passes(text):
    assert not has(text, "sum or combination"), problems(text)


# ---- 6. wrong words in their exact forms; Finnish contents with numbers ---------------------------------------

@pytest.mark.parametrize("text, wrong", [
    ("Salgosi on {{n1}} elokuussa 2026.", True),
    ("Luokittelemattomat kulut olivat {{n1}} elokuussa 2026.", True),
    ("Osto on vielä luokittelematon.", False),
    ("Osto jäi luokittelematta.", False),
])
def test_wrong_words_are_the_exact_forms(text, wrong):
    assert has(text, "a wrong word") is wrong, problems(text)


def test_finnish_contents_with_their_numbers_pass():
    assert contents_claim("Menot sisältävät vuokran {{n2}} ja sähkön {{n3}}.") is None


# ---- #447 row 2: number words spelled in three more ways ------------------------------------------------------

ALLOWED = Allowed(frozenset(), frozenset({(AUG.start, AUG.end)}))


@pytest.mark.parametrize("text", [
    "You could have o n e  m i l l i o n saved.",
    "You could have o n e m i l l i o n saved.",
    "That is a dozen purchases.",
    "Ostoksia oli tusinan verran.",
    "You spent MM euros on it.",
    "You spent €XL on it.",
])
def test_a_spelled_out_number_is_rejected(text):
    assert any("a number written in words" in e for e in check_text(text, ALLOWED)), text


@pytest.mark.parametrize("text", [
    "Did you mix up the dates? You spent {{n1}}.",
    "I can show it in the S Group app.",
    "Ostokset, MCC-ryhmä ravintolat, maksoivat {{n1}}.",
])
def test_ordinary_words_are_not_spelled_numbers(text):
    assert not any("a number written in words" in e for e in check_text(text, ALLOWED)), text
