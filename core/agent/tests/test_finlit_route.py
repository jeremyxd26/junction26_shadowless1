"""The financial-literacy route (#884): a literacy question gets a plain-words answer from the composer with finlit
fragments in its request and the source line added by code. No database and no network: the fragments come from a
fake source, the composer is scripted."""

from __future__ import annotations

import json

import pytest
from agent_fakes import registry, run

from core.agent import finlit_kb
from core.agent.gemini import compose_text
from core.agent.model import ComposeInput, ComposeResult
from core.agent.rules import RuleModel

OPEN = finlit_kb.Fragment("infofinland-financial-problems-9b4838", "InfoFinland.fi (footer: © KEHA Centre)",
                          "Velkaneuvonta", "https://www.infofinland.fi/fi/living-in-finland/money-and-taxes",
                          "Talous- ja velkaneuvonta auttaa maksutta. Noin [number] ihmistä saa apua.", "page_text")
CARD = finlit_kb.Fragment("martat-talouden-suunnittelu-5d", "Marttaliitto (Martat)", "Talouden suunnittelu",
                          "https://www.martat.fi/talous/", None, "source_card")
GOOD_FI = "Budjetti on suunnitelma tuloista ja menoista. Se auttaa näkemään, mihin rahat menevät. Aloita kirjaamalla menot."
GOOD_EN = ("A buffer is money set aside for surprises. Build it little by little, right after payday. "
           "Keep it apart from your everyday spending.")


class FakeSource:
    def __init__(self, fragments=(OPEN, CARD)):
        self.fragments_out = list(fragments)
        self.asked: list[tuple] = []

    def fragments(self, question, lang, band, k=finlit_kb.MAX_FRAGMENTS):
        self.asked.append((question, lang, band))
        return self.fragments_out[:k]


class Composer:
    """A language model whose planner is the rules; compose returns the scripted drafts in turn and records the
    requests (the usual path's drafts come from the rule model)."""

    model_id = "scripted"
    planner_prompt = composer_prompt = "scripted"

    def __init__(self, *drafts):
        self.rules = RuleModel()
        self.drafts = list(drafts)
        self.requests: list[ComposeInput] = []

    def plan(self, request):
        return self.rules.plan(request)

    def compose(self, request):
        self.requests.append(request)
        if request.sources is None:
            return self.rules.compose(request)
        text, lang = self.drafts.pop(0) if self.drafts else (GOOD_EN, request.language)
        return ComposeResult(text=json.dumps({"language": lang, "text": text, "cited": [], "lesson_key": None}))


def done_of(events):
    return next(p for e, p in events if e == "done")


def finlit_turns(pipeline_audit):
    return [t for r in pipeline_audit for t in r["planner_turns"] if "finlit" in t]


@pytest.fixture
def make(make_pipeline):
    def build(model, source=None):
        p = make_pipeline(model, reg=registry())
        p.finlit = source if source is not None else FakeSource()
        return p
    return build


def audit(pipeline):
    from agent_fakes import audit_records
    return audit_records(pipeline)


@pytest.mark.parametrize("question, lang, draft", [
    ("mikä on budjetti", "fi", GOOD_FI),
    ("how do I build a buffer", "en", GOOD_EN),
    ("mitä on korkoa korolle", "fi", GOOD_FI),
    ("What is an emergency fund?", "en", GOOD_EN),
])
def test_a_literacy_question_is_answered_from_the_fragments_with_the_source_line(make, question, lang, draft):
    model = Composer((draft, lang))
    source = FakeSource()
    p = make(model, source)
    done = done_of(run(p, question, language=lang))
    line = finlit_kb.SOURCE_LINE[1 if lang == "fi" else 0].format(publisher="InfoFinland.fi", url=OPEN.url)
    assert done["outcome"] == "answered" and done["cited"] == [] and done["refusal"] is None
    assert done["text"] == f"{draft} {line}"
    req = model.requests[0]
    assert req.literacy is True and req.data == []
    # text only from the open fragment; the card is a title and a publisher, never a link
    assert {"source": OPEN.publisher, "title": "Velkaneuvonta", "text": OPEN.text} in req.sources
    assert {"source": CARD.publisher, "title": "Talouden suunnittelu"} in req.sources
    assert "https://" not in json.dumps(req.sources)
    assert source.asked and source.asked[0][1] == lang
    assert finlit_turns(audit(p))[0]["finlit"] == [OPEN.source_id, CARD.source_id]


def test_the_glossary_definition_goes_with_the_fragments_for_budget(make):
    model = Composer((GOOD_FI, "fi"))
    p = make(model)
    run(p, "mikä on budjetti", language="fi")
    assert model.requests[0].sources[0] == {"source": "Sentti", "title": "definition",
                                            "text": "Budjetti on suunnitelma siitä, paljonko käytät rahaa eri asioihin kuukaudessa."}


@pytest.mark.parametrize("bad, reason", [
    ("Budjetti on suunnitelma. Noin 300 euroa kuussa riittää.", "digit"),          # a figure from a fragment
    ("Budjetti on suunnitelma. Voit ottaa lainaa yllätyksiin.", "borrowing"),
    ("Budjetti on suunnitelma. Sijoita ylijäämä rahastoihin.", "investing"),
    ("Budjetti on suunnitelma. S-Pankki auttaa tässä.", "brand"),
    ("Budjetti on suunnitelma. Lähde: Martat.", "source"),
    ("En pystynyt selvittämään tätä juuri nyt.", "non-answer"),
    ("A budget is a plan for your money. It helps you see where it goes.", "language"),
])
def test_a_bad_draft_is_retried_and_the_retry_gets_the_reasons(make, bad, reason):
    model = Composer((bad, "fi"), (GOOD_FI, "fi"))
    p = make(model)
    done = done_of(run(p, "mitä on korkoa korolle", language="fi"))
    assert done["text"].startswith(GOOD_FI)
    assert len(model.requests) == 2 and model.requests[1].validation_errors


def test_two_bad_drafts_leave_the_message_to_the_usual_path(make):
    model = Composer(("Noin 300 euroa riittää.", "fi"), ("Ota lainaa.", "fi"))
    p = make(model)
    done = done_of(run(p, "mikä on budjetti", language="fi"))
    # the glossary answers as before
    assert done["text"].startswith("Budjetti on suunnitelma siitä, paljonko käytät rahaa")
    assert "Lähde:" not in done["text"] and not finlit_turns(audit(p))


def test_nothing_retrieved_leaves_the_message_to_the_usual_path(make):
    model = Composer()
    p = make(model, FakeSource(fragments=()))
    done = done_of(run(p, "mikä on budjetti", language="fi"))
    assert done["text"].startswith("Budjetti on suunnitelma siitä") and not model.requests


@pytest.mark.parametrize("question, lang", [
    ("What is safe to spend?", "en"), ("Where did my money go?", "en"), ("How could I save more?", "en"),
    ("What if I spent 20% less on restaurants?", "en"), ("Should I buy bitcoin?", "en"),
    ("How much did I spend at the pharmacy last month?", "en"), ("What kind of spender am I?", "en"),
    ("What can I safely spend this week?", "en"), ("Why is my safe to spend lower than it was?", "en"),
    ("Mihin rahani menivät?", "fi"), ("Miten voisin säästää enemmän?", "fi"), ("Millainen kuluttaja olen?", "fi"),
    ("Mitä jos käyttäisin 20 % vähemmän ravintoloihin?", "fi"),
    ("Paljonko voin turvallisesti käyttää tällä viikolla?", "fi"),
    ("Miksi turvallinen käyttövarani on pienempi kuin ennen?", "fi"),
    ("How do I block my card?", "en"), ("Miten tilaan e-laskun?", "fi"),           # S-Bank's knowledge base
    ("Should I take a loan?", "en"), ("Kannattaako ottaa pikavippi?", "fi"),       # borrowing
    ("Should I invest in funds?", "en"), ("What is a buffer?", "en"),               # a product; Sentti's own term
    ("What is the capital of Finland?", "en"),
])
def test_demo_s_bank_borrowing_products_and_own_terms_keep_their_route(make, question, lang):
    model = Composer()
    p = make(model)
    run(p, question, language=lang)
    assert not finlit_turns(audit(p))
    assert all(r.sources is None for r in model.requests)


def test_tips_in_a_running_conversation_are_left_to_the_talk_mode(make):
    model = Composer((GOOD_EN, "en"), (GOOD_EN, "en"))
    p = make(model)
    first = done_of(run(p, "how do I build a buffer", language="en"))
    assert "Source:" in first["text"]
    events = run(p, "Tips for saving money?", language="en", conversation_id=next(
        pl for e, pl in run(p, "Where did my money go?", language="en") if e == "meta")["conversation_id"])
    assert "Source:" not in done_of(events)["text"]


def test_no_route_without_a_source(make_pipeline):
    model = Composer()
    p = make_pipeline(model, reg=registry())
    done = done_of(run(p, "mitä on korkoa korolle", language="fi"))
    assert "Lähde:" not in done["text"] and all(r.sources is None for r in model.requests)


def test_the_compose_request_carries_the_blocks_only_when_set():
    base = ComposeInput(question="q", language="en", as_of="2026-09-30", data=[])
    assert compose_text(base) == compose_text(ComposeInput(question="q", language="en", as_of="2026-09-30", data=[],
                                                           sources=None, literacy=False))
    text = compose_text(ComposeInput(question="q", language="en", as_of="2026-09-30", data=[],
                                     sources=[{"source": "Kela", "title": "t"}], literacy=True))
    assert "<sources>" in text and "Kind of answer: a general money question" in text


def test_fragment_data_masks_digits_and_never_carries_the_link():
    f = finlit_kb.Fragment("s", "P", "Title 2024", "https://x.fi/a1", finlit_kb._mask("Costs 1 200 € or 12,5 % in 2024."),
                           "page_text")
    assert f.data() == {"source": "P", "title": "Title [number]", "text": "Costs [number] or [number] in [number]."}


@pytest.mark.parametrize("age, band", [(17, "13-17"), (18, "18-24"), (24, "18-24"), (25, "25-34"), (35, "35-44"),
                                       (52, "45-54"), (80, "75+"), (None, None), ("x", None)])
def test_age_band(age, band):
    assert finlit_kb.age_band(age) == band


class _Hit:
    def __init__(self, sid, kind, text="body 12 text", url="https://a.fi/x"):
        self.source_id, self.kind, self.title, self.text, self.source_url = sid, kind, "T", text, url


class _Conn:
    def __init__(self, meta):
        self.meta = meta

    def execute(self, sql, params=None):
        class R:
            def __init__(self, rows):
                self.rows = rows

            def fetchall(self):
                return self.rows
        return R([(k, *v) for k, v in self.meta.items()])


def test_fragments_keep_public_tiers_and_open_text_only(monkeypatch):
    hits = [_Hit("bank1", "source_card"), _Hit("closed", "page_text"), _Hit("open", "page_text"),
            _Hit("card", "source_card"), _Hit("http", "source_card", url="http://a.fi"), _Hit("ngo", "source_card")]
    meta = {"bank1": ("Nordea", "bank", "all_rights_reserved"), "closed": ("KKV", "authority", "terms_allow_reuse"),
            "open": ("InfoFinland", "authority", "open_attribution"), "card": ("Kela", "authority", "not_stated"),
            "http": ("THL", "authority", "open_attribution"), "ngo": ("Martat", "nonprofit", "not_stated")}

    class FakeRetriever:
        def __init__(self, conn, embedder, model):
            pass

        def search(self, question, lang, band, **kw):
            assert kw["k_facts"] == 0 and kw["per_source"] == 1
            return type("R", (), {"texts": hits})()

    import core.finlit.retrieve as retrieve
    monkeypatch.setattr(retrieve, "Retriever", FakeRetriever)
    from contextlib import contextmanager

    @contextmanager
    def connect():
        yield _Conn(meta)

    src = finlit_kb.FinlitSource(connect, embedder=None, model="m")
    monkeypatch.setattr(src, "query_vector", lambda q: [0.0])
    out = src.fragments("q", "fi", "25-34")
    assert [f.source_id for f in out] == ["closed", "open", "card"]
    assert out[0].text is None and out[1].text == "body [number] text" and out[2].text is None


def test_fragments_are_empty_when_the_embedding_times_out_or_the_database_fails(monkeypatch):
    def broken():
        raise RuntimeError("db down")
    src = finlit_kb.FinlitSource(broken, embedder=None, model="m")
    monkeypatch.setattr(src, "query_vector", lambda q: [0.0])
    assert src.fragments("q", "fi", None) == []
    monkeypatch.setattr(src, "query_vector", lambda q: None)
    assert src.fragments("q", "fi", None) == []
    assert src.fragments("q", "sv", None) == []


@pytest.mark.parametrize("question", [
    "mikä on budjetti", "how do I build a buffer", "mitä on korkoa korolle", "What is compound interest?",
    "What is a payment default?", "Mikä on maksuhäiriö?", "Miten tunnistan huijauksen?", "What is inflation?",
    "Mikä on verokortti?", "Tips for saving money?", "What is an emergency fund?", "Mikä on hätävara?"])
def test_literacy_questions(question):
    assert finlit_kb.question_kind(question) == "literacy"


@pytest.mark.parametrize("question", [
    "What is my budget?", "How much did I spend?", "Should I take a loan?", "Should I buy bitcoin?",
    "Which savings account should I open?", "Mikä on S-Pankin korko?", "Paljonko käytin ruokaan?", "Mikä on luottokortti?",
    "What if I spent 20% less on restaurants?", "any more tips?", "why does it matter? explain", "hello"])
def test_not_literacy_questions(question):
    assert finlit_kb.question_kind(question) is None
