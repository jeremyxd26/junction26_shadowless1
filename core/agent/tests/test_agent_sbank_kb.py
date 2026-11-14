"""The S-Bank knowledge base (#791): a question about S-Bank or S-mobiili gets our fixed text from S-Bank's public
help pages, its source line and the way to the bank (contact_bank). No model, no database: the file, the matcher
and the pipeline's early route with the rule model."""

from __future__ import annotations

import re

import pytest
from agent_fakes import audit_records, run

from core.agent import sbank_kb
from core.agent.guard import detect_language
from core.agent.rules import RuleModel

ENTRIES = sbank_kb.ENTRIES
CONTACT = {"type": "open_host_screen", "target": "contact_bank"}


def done_of(events):
    return dict(events)["done"]


def kb_turns(pipeline):
    return [t for t in audit_records(pipeline)[-1]["planner_turns"] if "sbank_kb" in t]


def has_contact(done):
    return any(a.get("type") == CONTACT["type"] and a.get("target") == CONTACT["target"] for a in done["actions"])


# ---- the file ----

def test_only_the_contact_and_step_entries_may_carry_digits():
    assert {e.id for e in ENTRIES if e.digits} == set(PUBLISHED_DIGITS)


@pytest.mark.parametrize("entry", ENTRIES, ids=lambda e: e.id)
def test_every_entry_has_an_english_and_a_finnish_answer_in_that_language(entry):
    assert detect_language(entry.answer_en) == "en", entry.answer_en
    assert detect_language(entry.answer_fi) == "fi", entry.answer_fi


def test_the_file_has_between_thirty_and_sixty_entries_with_every_field():
    assert 30 <= len(ENTRIES) <= 60
    assert len({e.id for e in ENTRIES}) == len(ENTRIES)
    for e in ENTRIES:
        assert e.topic and e.questions_en and e.questions_fi and e.answer_en and e.answer_fi
        assert re.fullmatch(r"https://www\.s-pankki\.fi/fi/asiakaspalvelu/[\w./-]+", e.source_url), e.source_url
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", e.retrieved_at)


# The only texts with digits (#808): the published contact numbers and postal address, and step numbers.
PUBLISHED_DIGITS = {"contact": {"09 6964 6820", "020 333", "77", "00088"}, "e_invoice_order": {"1.", "2.", "3.", "4."}}


@pytest.mark.parametrize("entry", ENTRIES, ids=lambda e: e.id)
def test_no_answer_has_a_digit_a_euro_sign_or_speaks_as_the_bank(entry):
    for text in (entry.answer_en, entry.answer_fi):
        assert not re.search(r"€|%", text), text
        if entry.digits:
            published = PUBLISHED_DIGITS[entry.id]
            found = set(re.findall(r"\d[\d ]*\d\.?|\d\.?", text))
            assert {f.strip() for f in found} <= published | {d.rstrip(".") for d in published}, (entry.id, found)
            assert re.sub(r"\d[\d ]*\d|\d", "", text).count("€") == 0
        else:
            assert not re.search(r"\d", text), text
    assert not re.search(r"\b(we|our|us)\b", entry.answer_en, re.I), entry.answer_en
    assert not re.search(r"\b(me|meidän|meille|meillä|meiltä|meitä|tarjoamme|autamme)\b", entry.answer_fi, re.I)
    assert not re.search(r"\b(free|recommend|should choose|best)\b", entry.answer_en, re.I)
    assert not re.search(r"\b(maksuton\w*|suosittel\w*|kannattaa|paras\w*)\b", entry.answer_fi, re.I)


# ---- the matcher: find_bank_entry ----

@pytest.mark.parametrize("entry", ENTRIES, ids=lambda e: e.id)
def test_every_question_variant_finds_its_own_entry(entry):
    for q in entry.questions_en:
        assert sbank_kb.find_bank_entry(q, "en") is entry, q
    for q in entry.questions_fi:
        assert sbank_kb.find_bank_entry(q, "fi") is entry, q


@pytest.mark.parametrize("question, lang, entry_id", [
    ("How do I block my S-Bank card?", "en", "lost_card"),
    ("What should I do if I lose my card?", "en", "lost_card"),
    ("Miten suljen korttini?", "fi", "lost_card"),
    ("Mita teen jos korttini katoaa", "fi", "lost_card"),          # without diacritics
    ("How do I delete an e-invoice in S-mobiili?", "en", "e_invoice_edit"),
    ("Miten poistan e-laskun?", "fi", "e_invoice_edit"),
    ("I lost my phone, what about S-mobiili?", "en", "lost_phone"),
    ("Puhelimeni katosi, mitä nyt?", "fi", "lost_phone"),
    ("Where can I check my card PIN?", "en", "card_pin"),
    ("Mistä löydän S-Pankin BIC-tunnuksen?", "fi", "bic"),
    ("Is my money safe in S-Bank?", "en", "deposit_protection"),
])
def test_matching_in_english_and_finnish(question, lang, entry_id):
    assert sbank_kb.find_bank_entry(question, lang).id == entry_id


@pytest.mark.parametrize("question", ["How much did I spend at S-market?", "What is my S-mobiili balance?",
                                      "Paljonko käytin S-marketissa?", "Mikä on S-mobiilin saldoni?",
                                      "Which S-Bank card should I get?", "Kannattaako S-Pankin tili?",
                                      "Did I pay with my S-Bank card in August?", "How much bonus did I get?"])
def test_the_customers_own_figures_and_a_recommendation_are_never_answered_here(question):
    assert sbank_kb.answer_for(question, "fi" if re.search(r"[äö]|paljonko|kannattaako", question, re.I) else "en") is None


@pytest.mark.parametrize("question, lang", [
    ("Can I afford a new bicycle?", "en"), ("Keep my savings separate from bills", "en"), ("I paid swiftly", "en"),
    ("Is my pink jacket expensive?", "en"), ("What's bank interest?", "en")])
def test_english_phrases_are_whole_words_and_an_apostrophe_s_is_not_s_bank(question, lang):
    assert sbank_kb.find_bank_entry(question, lang) is None and sbank_kb.answer_for(question, lang) is None


@pytest.mark.parametrize("question, lang", [
    ("Show my S-Bank transactions", "en"), ("What's on my S-Bank account?", "en"),
    ("What are my latest S-mobiili purchases?", "en"), ("Tell me about my S-Bank account", "en"),
    ("Näytä S-Pankin tilitapahtumani", "fi"), ("Onko S-Pankin tililläni tarpeeksi rahaa vuokraan?", "fi"),
    ("Kerro S-Pankin tilistäni", "fi")])
def test_an_own_data_question_about_s_bank_never_gets_the_dont_know_line(question, lang):
    assert sbank_kb.answer_for(question, lang) is None


def test_no_match_but_clearly_about_s_bank_is_the_dont_know_line():
    en = sbank_kb.answer_for("Is S-Bank open on Sunday?", "en")
    fi = sbank_kb.answer_for("Onko S-Pankilla kahvila?", "fi")
    assert en.entry_id is None and en.text == "I don't know that one; the bank can tell you."
    assert fi.entry_id is None and fi.text == "En tiedä sitä; pankki osaa kertoa."
    assert sbank_kb.answer_for("Does the library have a cafe?", "en") is None


# ---- the route ----

# The rule model claims this one for its bills rule ("e-lasku" is a bills word) and it keeps that route; the
# e-invoice how-to entries (sbank_kb.OVER_BILLS_RULE) answer before the bills rule (#808).
RULES_CLAIM = {("e_invoice", "fi")}


@pytest.mark.parametrize("lang", ["en", "fi"])
@pytest.mark.parametrize("entry", ENTRIES, ids=lambda e: e.id)
def test_every_entry_is_answered_by_the_route_with_its_source_and_contact_bank(make_pipeline, entry, lang):
    pipeline = make_pipeline(RuleModel())
    question = (entry.questions_fi if lang == "fi" else entry.questions_en)[0]
    done = done_of(run(pipeline, question, language=lang))
    if (entry.id, lang) in RULES_CLAIM:
        assert not kb_turns(pipeline) and "s-pankki.fi" not in done["text"]
        return
    line = (sbank_kb.SOURCE_LINE[1] if lang == "fi" else sbank_kb.SOURCE_LINE[0]).format(url=entry.source_url)
    assert done["outcome"] == "answered" and done["refusal"] is None and done["cited"] == []
    assert done["text"] == f"{entry.answer(lang)} {line}"
    assert has_contact(done)
    assert kb_turns(pipeline) == [{"round": 1, "source": "rules", "sbank_kb": entry.id, "calls": []}]


@pytest.mark.parametrize("question, lang, text", [
    ("Is S-Bank open on Sunday?", "en", "I don't know that one; the bank can tell you."),
    ("Onko S-Pankilla kahvila?", "fi", "En tiedä sitä; pankki osaa kertoa."),
])
def test_the_dont_know_line_comes_with_contact_bank(make_pipeline, question, lang, text):
    pipeline = make_pipeline(RuleModel())
    done = done_of(run(pipeline, question, language=lang))
    assert done["outcome"] == "answered" and done["text"] == text and has_contact(done)
    assert kb_turns(pipeline)[0]["sbank_kb"] == "unknown"


@pytest.mark.parametrize("question, lang", [
    ("Should I invest in S-Bank funds?", "en"),                     # investment advice
    ("Can S-Bank give me a loan for a car?", "en"),                 # a credit decision
    ("Show my wife's S-Bank account", "en"),                        # another person's data
    ("Transfer 50 euros from my S-Bank account to Matti", "en"),    # moving money
    ("Siirrä rahaa S-Pankin tililtäni Matille", "fi"),
    ("Kannattaako sijoittaa S-Pankin rahastoihin?", "fi"),
])
def test_hard_rules_win(make_pipeline, question, lang):
    pipeline = make_pipeline(RuleModel())
    done = done_of(run(pipeline, question, language=lang))
    assert not kb_turns(pipeline)
    assert sbank_kb.UNKNOWN[0] not in done["text"] and sbank_kb.UNKNOWN[1] not in done["text"]
    assert "s-pankki.fi" not in done["text"]


@pytest.mark.parametrize("question, lang", [
    ("How much did I spend at S-market?", "en"), ("What is my S-mobiili balance?", "en"),
    ("Paljonko käytin S-marketissa elokuussa 2026?", "fi"), ("my S-mobiili balance", "en"),
    ("My card was stolen", "en"), ("Asiakaspalvelu", "fi"),          # human_request first, as on dev
])
def test_customer_number_questions_and_human_requests_keep_their_route(make_pipeline, question, lang):
    pipeline = make_pipeline(RuleModel())
    run(pipeline, question, language=lang)
    assert not kb_turns(pipeline)


def test_no_knowledge_base_text_enters_a_money_answer(make_pipeline):
    pipeline = make_pipeline(RuleModel())
    done = done_of(run(pipeline, "How much did I spend on restaurants in August 2026?", language="en"))
    assert not kb_turns(pipeline)
    texts = [e.answer_en for e in ENTRIES] + [e.answer_fi for e in ENTRIES]
    assert "s-pankki.fi" not in done["text"] and not any(t in done["text"] for t in texts)


# ---- #808: Renat's wordings, the question's language, contact, e-invoice steps ----

@pytest.mark.parametrize("question, request_lang, entry_id, answer_lang", [
    ("How do I contact S-Bank?", "en", "contact", "en"),
    ("How do I contact S-Bank?", "fi", "contact", "en"),
    ("Miten otan yhteyttä S-Pankkiin?", "fi", "contact", "fi"),
    ("Miten otan yhteyttä S-Pankkiin?", "en", "contact", "fi"),     # the app asked in English
    ("Miten tilaan e-laskun?", "fi", "e_invoice_order", "fi"),
    ("Miten tilaan e-laskun?", "en", "e_invoice_order", "fi"),
    ("How do I order an e-invoice?", "en", "e_invoice_order", "en"),
    ("Miten suljen korttini?", "en", "lost_card", "fi"),
    ("Mikä on S-Pankin BIC-tunnus?", "en", "bic", "fi"),
])
def test_renats_wordings_get_their_entry_in_the_questions_language(make_pipeline, question, request_lang, entry_id,
                                                                     answer_lang):
    pipeline = make_pipeline(RuleModel())
    done = done_of(run(pipeline, question, language=request_lang))
    entry = sbank_kb.BY_ID[entry_id]
    line = sbank_kb.SOURCE_LINE[1 if answer_lang == "fi" else 0].format(url=entry.source_url)
    assert done["outcome"] == "answered" and done["text"] == f"{entry.answer(answer_lang)} {line}"
    assert has_contact(done)
    label = [a["label"] for a in done["actions"] if a.get("target") == "contact_bank"][0]
    from core.tools import config
    assert label == config.contact_bank_action(answer_lang)["label"]
    assert kb_turns(pipeline)[0]["sbank_kb"] == entry_id


def test_the_contact_answer_carries_the_published_numbers():
    entry = sbank_kb.BY_ID["contact"]
    for text in (entry.answer_en, entry.answer_fi):
        assert "09 6964 6820" in text and "020 333" in text
    assert entry.source_url == "https://www.s-pankki.fi/fi/asiakaspalvelu/"


def test_the_e_invoice_order_answer_is_numbered_steps():
    entry = sbank_kb.BY_ID["e_invoice_order"]
    for text in (entry.answer_en, entry.answer_fi):
        assert [m for m in re.findall(r"(\d)\. ", text)] == ["1", "2", "3", "4"]


@pytest.mark.parametrize("question, lang", [("How do I order a new card in S-mobiili?", "en"),
                                            ("Miten tilaan uuden kortin S-mobiilissa?", "fi")])
def test_ordering_a_new_card_is_not_the_card_validity_answer(question, lang):
    found = sbank_kb.find_bank_entry(question, lang)
    assert found is None or found.id != "card_expiry"


def test_an_own_bills_question_about_e_invoices_keeps_the_bills_rule(make_pipeline):
    pipeline = make_pipeline(RuleModel())
    run(pipeline, "Mitkä e-laskuni ovat tulossa?", language="fi")
    assert not kb_turns(pipeline)
