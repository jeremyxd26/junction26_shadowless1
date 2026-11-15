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
    ("Why should I save money?", "en", GOOD_EN),             # the rules would plan the savings plan: reasons instead
    ("Miksi mun pitäisi säästää rahaa?", "fi", GOOD_FI),
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


OPEN2 = finlit_kb.Fragment("suomi-edunvalvonta-8a93fe", "Digi- ja väestötietovirasto (DVV) on Suomi.fi", "Edunvalvonta",
                           "https://www.suomi.fi/edunvalvonta", "Edunvalvonta tarkoittaa ...", "page_text")


def test_the_best_ranked_source_is_named_and_so_is_the_open_text_sent(make):
    model = Composer((GOOD_FI, "fi"))
    p = make(model, FakeSource(fragments=(CARD, OPEN, OPEN2)))
    done = done_of(run(p, "mitä on korkoa korolle", language="fi"))
    assert done["text"] == f"{GOOD_FI} Lähde: Marttaliitto, {CARD.url}; InfoFinland.fi, {OPEN.url}"
    # a third source's open text is not sent, because the line does not name it
    assert {"source": OPEN2.publisher, "title": "Edunvalvonta"} in model.requests[0].sources
    assert "Edunvalvonta tarkoittaa" not in json.dumps(model.requests[0].sources, ensure_ascii=False)


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
    ("Budjetti on suunnitelma. Säästä kolmen kuukauden menot sivuun.", "number word"),
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
    ("What is the capital of Finland?", "en"), ("How do I save on healthcare costs?", "en"),   # health (R9)
])
def test_demo_s_bank_borrowing_products_and_own_terms_keep_their_route(make, question, lang):
    model = Composer()
    p = make(model)
    run(p, question, language=lang)
    assert not finlit_turns(audit(p))
    assert all(r.sources is None for r in model.requests)


def _conversation(p, first, lang="en"):
    events = run(p, first, language=lang)
    return next(pl for e, pl in events if e == "meta")["conversation_id"]


def _turns(p):
    return audit(p)[-1]["planner_turns"]


def test_why_and_tips_in_a_running_conversation_go_to_the_talk_mode_with_the_fragments(make):
    model = Composer((GOOD_EN, "en"), (GOOD_EN, "en"))
    source = FakeSource()
    p = make(model, source)
    cid = _conversation(p, "Where did my money go?")
    done = done_of(run(p, "Tips for saving money?", language="en", conversation_id=cid))
    turns = _turns(p)
    talk = [t for t in turns if "talk" in t]
    assert talk and talk[0]["finlit"] == [OPEN.source_id, CARD.source_id]   # the talk mode's turn, not the route's
    assert done["text"].endswith(f"Source: InfoFinland.fi, {OPEN.url}")
    request = model.requests[-1]
    assert request.literacy is False and request.data[0]["tool"] == "answer_in_words"
    assert {"source": OPEN.publisher, "title": "Velkaneuvonta", "text": OPEN.text} in request.sources


def test_a_bare_why_searches_with_the_previous_question(make):
    model = Composer((GOOD_EN, "en"))
    source = FakeSource()
    p = make(model, source)
    cid = _conversation(p, "Where did my money go?")
    run(p, "why does it matter?", language="en", conversation_id=cid)
    assert source.asked[-1][0] == "Where did my money go? why does it matter?"


def test_no_money_topic_in_the_message_or_the_previous_question_means_no_search(make):
    model = Composer((GOOD_EN, "en"))
    source = FakeSource()
    p = make(model, source)
    cid = _conversation(p, "What kind of spender am I?")
    run(p, "why does it matter?", language="en", conversation_id=cid)
    assert source.asked == [] and all(r.sources is None for r in model.requests)


def test_a_talk_template_names_no_source(make):
    model = Composer(("Noin 300 euroa.", "en"), ("Ota lainaa.", "en"))   # both drafts fail the talk checks
    p = make(model)
    cid = _conversation(p, "Where did my money go?")
    done = done_of(run(p, "why does it matter?", language="en", conversation_id=cid))
    assert "Source:" not in done["text"]
    assert not any("finlit" in t for t in _turns(p))


class _Client:
    def __init__(self):
        self.started = []

    def start_answer(self, key):
        self.started.append(key)


def test_a_compose_only_answer_starts_the_model_answer_state(make):
    """The stand's bug: no planner ran, so the composer met the previous answer's expired deadline (#884)."""
    model = Composer((GOOD_FI, "fi"), (GOOD_EN, "en"))
    model.client = _Client()
    p = make(model)
    run(p, "mitä on korkoa korolle", language="fi")
    assert len(model.client.started) == 1 and model.client.started[0].literacy is True
    cid = _conversation(p, "Where did my money go?")
    before = len(model.client.started)
    run(p, "Tips for saving money?", language="en", conversation_id=cid)   # the talk mode
    assert len(model.client.started) == before + 1


def test_why_save_gets_the_fixed_reasons_when_no_draft_passes(make):
    model = Composer(("Sijoita säästösi rahastoon.", "fi"), ("Noin 300 euroa riittää.", "fi"))
    p = make(model)
    events = run(p, "Miksi mun pitäisi säästää rahaa?", language="fi")
    done = done_of(events)
    assert done["outcome"] == "answered" and done["text"] == finlit_kb.WHY_SAVE_TEXT[1]
    assert not any(e == "card" for e, _ in events) and "Lähde" not in done["text"]
    assert finlit_turns(audit(p))[0]["finlit"] == "fixed_reasons"


@pytest.mark.parametrize("lang", ["en", "fi"])
def test_the_fixed_reasons_pass_the_literacy_checks(lang):
    text = finlit_kb.WHY_SAVE_TEXT[1 if lang == "fi" else 0]
    assert finlit_kb.draft_problems({"language": lang, "text": text, "cited": [], "lesson_key": None}, lang)[1] == []


def test_a_buffer_fund_is_not_an_investment():
    ok = {"language": "fi", "text": "Hätärahasto auttaa yllätyksissä. Puskurirahasto kasvaa pienistä summista.",
          "cited": [], "lesson_key": None}
    assert finlit_kb.draft_problems(ok, "fi")[1] == []
    bad = {"language": "fi", "text": "Sijoita säästösi rahastoon.", "cited": [], "lesson_key": None}
    assert any("investing" in e for e in finlit_kb.draft_problems(bad, "fi")[1])
    assert finlit_kb.question_kind("Mikä on hätärahasto?") == "literacy"
    assert finlit_kb.question_kind("Mihin rahastoon kannattaa sijoittaa?") is None


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
        self.chunk_id = f"{sid}:chunk"


class _Conn:
    def __init__(self, meta, dist=None):
        self.meta = meta
        self.dist = dist or {}

    def execute(self, sql, params=None):
        class R:
            def __init__(self, rows):
                self.rows = rows

            def fetchall(self):
                return self.rows
        if "chunk_embeddings" in sql:
            return R([(f"{k}:chunk", self.dist.get(k, 0.2)) for k in self.meta])
        return R([(k, *v) for k, v in self.meta.items()])


def test_fragments_keep_public_tiers_and_open_text_only_and_no_datasets(monkeypatch):
    hits = [_Hit("bank1", "source_card"), _Hit("closed", "page_text"), _Hit("open", "page_text"),
            _Hit("data", "source_card"), _Hit("api", "source_card", url="https://e.fi/service/api/external/1"),
            _Hit("card", "source_card"), _Hit("http", "source_card", url="http://a.fi"), _Hit("ngo", "source_card")]
    meta = {"bank1": ("Nordea", "bank", "all_rights_reserved", "course"),
            "closed": ("KKV", "authority", "terms_allow_reuse", "course"),
            "open": ("InfoFinland", "authority", "open_attribution", "course"),
            "data": ("Tilastokeskus", "authority", "open_attribution", "dataset"),
            "api": ("Opetushallitus", "public_education", "not_stated", "course"),
            "card": ("Kela", "authority", "not_stated", "course"),
            "http": ("THL", "authority", "open_attribution", "course"),
            "ngo": ("Martat", "nonprofit", "not_stated", "course")}

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
    assert out[0].distance == 0.2


def test_a_fragment_beyond_the_distance_floor_is_left_out(monkeypatch):
    hits = [_Hit("far", "source_card"), _Hit("near", "source_card")]
    meta = {"far": ("Kela", "authority", "not_stated", "course"), "near": ("THL", "authority", "not_stated", "course")}

    class FakeRetriever:
        def __init__(self, conn, embedder, model):
            pass

        def search(self, question, lang, band, **kw):
            return type("R", (), {"texts": hits})()

    import core.finlit.retrieve as retrieve
    monkeypatch.setattr(retrieve, "Retriever", FakeRetriever)
    monkeypatch.setattr(finlit_kb, "MAX_DISTANCE", 0.4)
    from contextlib import contextmanager

    @contextmanager
    def connect():
        yield _Conn(meta, dist={"far": 0.6, "near": 0.3})

    src = finlit_kb.FinlitSource(connect, embedder=None, model="m")
    monkeypatch.setattr(src, "query_vector", lambda q: [0.0])
    assert [f.source_id for f in src.fragments("q", "fi", None)] == ["near"]


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
    "Mikä on verokortti?", "Tips for saving money?", "What is an emergency fund?", "Mikä on hätävara?",
    "Why should I save money?", "Miksi mun pitäisi säästää rahaa?"])
def test_literacy_questions(question):
    assert finlit_kb.question_kind(question) == "literacy"


@pytest.mark.parametrize("question", [
    "What is my budget?", "How much did I spend?", "Should I take a loan?", "Should I buy bitcoin?",
    "Which savings account should I open?", "Mikä on S-Pankin korko?", "Paljonko käytin ruokaan?", "Mikä on luottokortti?",
    "What if I spent 20% less on restaurants?", "any more tips?", "why does it matter? explain", "hello",
    "Miksi mun rahat menee ruokaan?", "Paljonko minun säästöni ovat?"])
def test_not_literacy_questions(question):
    assert finlit_kb.question_kind(question) is None
