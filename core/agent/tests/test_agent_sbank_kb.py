"""The S-Bank knowledge base (#791): a question about S-Bank or S-mobiili gets our fixed text from S-Bank's public
help pages, its source line and the way to the bank (contact_bank). No model, no database: the file, the matcher
and the pipeline's early route with the rule model."""

from __future__ import annotations

import re

import pytest
from agent_fakes import audit_records, run

from core.agent import sbank_kb
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

def test_the_file_has_between_thirty_and_sixty_entries_with_every_field():
    assert 30 <= len(ENTRIES) <= 60
    assert len({e.id for e in ENTRIES}) == len(ENTRIES)
    for e in ENTRIES:
        assert e.topic and e.questions_en and e.questions_fi and e.answer_en and e.answer_fi
        assert e.source_url.startswith("https://www.s-pankki.fi/")
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", e.retrieved_at)


@pytest.mark.parametrize("entry", ENTRIES, ids=lambda e: e.id)
def test_no_answer_has_a_digit_a_euro_sign_or_speaks_as_the_bank(entry):
    for text in (entry.answer_en, entry.answer_fi):
        assert not re.search(r"\d|€|%", text), text
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


def test_no_match_but_clearly_about_s_bank_is_the_dont_know_line():
    en = sbank_kb.answer_for("Does S-Bank have a cafe?", "en")
    fi = sbank_kb.answer_for("Onko S-Pankilla kahvila?", "fi")
    assert en.entry_id is None and en.text == "I don't know that one; the bank can tell you."
    assert fi.entry_id is None and fi.text == "En tiedä sitä; pankki osaa kertoa."
    assert sbank_kb.answer_for("Does the library have a cafe?", "en") is None


# ---- the route ----

@pytest.mark.parametrize("lang", ["en", "fi"])
@pytest.mark.parametrize("entry", ENTRIES, ids=lambda e: e.id)
def test_every_entry_is_answered_by_the_route_with_its_source_and_contact_bank(make_pipeline, entry, lang):
    pipeline = make_pipeline(RuleModel())
    question = (entry.questions_fi if lang == "fi" else entry.questions_en)[0]
    done = done_of(run(pipeline, question, language=lang))
    line = (sbank_kb.SOURCE_LINE[1] if lang == "fi" else sbank_kb.SOURCE_LINE[0]).format(url=entry.source_url)
    assert done["outcome"] == "answered" and done["refusal"] is None and done["cited"] == []
    assert done["text"] == f"{entry.answer(lang)} {line}"
    assert has_contact(done)
    assert kb_turns(pipeline) == [{"round": 1, "source": "rules", "sbank_kb": entry.id, "calls": []}]


@pytest.mark.parametrize("question, lang, text", [
    ("Does S-Bank have a cafe?", "en", "I don't know that one; the bank can tell you."),
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
