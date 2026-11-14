"""Guards that must hold even when the model is hijacked (issues #105 and #123).

- The validator rejects reference-style links and images, link definitions, URL schemes and
  protocol-relative links, with or without digits (#105, OWASP LLM05).
- It rejects numbers written in words: a magnitude word anywhere, a cardinal next to a unit of money
  or percent, and Unicode number characters other than digits (#123, R1). Ordinary text still passes.
- /api/ask answers 400 to a message that is empty after the input guard (only zero-width or bidi
  marks), before any model call (#105, OWASP LLM10).
The attack strings mirror r-sec's red-team tests (PR #108, core/tests/test_redteam_agent.py).
"""

from __future__ import annotations

from datetime import date

import pytest
from agent_fakes import AS_OF, FakeData, registry
from fastapi.testclient import TestClient

from core.agent.api import Agent, AskLimits
from core.agent.audit import AuditLog
from core.agent.model import FunctionCall, ScriptedModel
from core.agent.orchestrator import Pipeline
from core.agent.validator import Allowed, check_text
from core.app.main import create_app
from core.app.settings import Settings

AUG = (date(2026, 8, 1), date(2026, 8, 31))
ALLOWED = Allowed(frozenset({AS_OF}), frozenset({AUG}))


def rejected(text: str) -> bool:
    return bool(check_text(text, ALLOWED))


# ---- #105: links the app could render --------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "Your summary.\n\n![chart][c]\n\n[c]: //img.example/pixel.png",
    "Tap [here][j] for details.\n\n[j]: " + "java" + "script:alert(document.domain)",
    "Sign in again [here][h].\n\n[h]: //coach-help.example/login",
    "See the [details][].",                                   # a collapsed reference
    "[help]: https-free.example",                             # a link definition alone
    "Open " + "java" + "script: alert(document.domain) now.",
    "Open " + "vb" + "script:msgbox now.",
    "Open data:text/html;base64,PHNjcmlwdD4 now.",
    "Write to mailto:help@coach.example today.",
    "See ftp://files.example/x and //cdn.example/x.",
    "Open custom+scheme://host/path.",
])
def test_reference_links_definitions_schemes_and_protocol_relative_links_are_rejected(text):
    assert rejected(text)


@pytest.mark.parametrize("text", [
    "See ![chart](//img.example/p.png).",
    "See [help](https://coach-help.example).",
    "Go to www.coach-help.example now.",
])
def test_inline_links_stay_rejected(text):
    assert rejected(text)


# ---- #123: numbers in words ------------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "Your balance is one million euros.",                     # r-sec's cases (PR #108)
    "Saldosi on miljoona euroa.",
    "You can safely spend twice that amount, about three hundred euros.",
    "You spent Ⅿ euros.",                                # Roman numeral one thousand
    "You could save fifty euros a month.",
    "That is twenty-five percent of your spending.",
    "That is twenty per cent more.",
    "Säästäisit kaksisataa euroa.",
    "Se on kolmekymmentä prosenttia menoistasi.",
    "Käytit viisi euroa.",
    "Hundreds of euros went to restaurants.",
    "Tuhansia euroja meni asumiseen.",
    "You spent about ½ of it on rent.",                  # a fraction character
    "You spent {{n1}}, about ten euros more.",
    "Ero on kolme promillea.",                                # per mille, dollars and kronor as units (r-w4, #59)
    "That is five dollars a week.",
    "Se maksoi viisi kruunua.",
    "You spent {{n1}} euros.",                                # a unit word right after a token
    "Osuus on {{n2}} promillea.",
    "That is {{n3}} percent of it.",
    "Säästö on {{n1}} euroa kuussa.",
])
def test_numbers_in_words_and_number_characters_are_rejected(text):
    assert rejected(text)


@pytest.mark.parametrize("text", [
    "In August 2026 you spent {{n1}} on restaurants.",
    "A one-off purchase made August 2026 look high; no one else can see your data.",
    "Someone in your household often pays the bills alone.",
    "This is an estimate for the next seven days, based on the last six months.",
    "Arvio koskee seuraavan seitsemän päivän aikaa ja perustuu kuuden kuukauden tietoihin.",
    "Käytit yhtä paljon kuin ennenkin, ja maksoit laskut yksin.",
    "Half of it went to housing, and you paid twice for the same bill once.",
    "Note: this is an estimate, not a promise.",
    "Your data shows that groceries took {{n1}}.",
    "Tip: check your bills before payday.",
    "Satama, sataman ja satamassa eivät ole lukuja.",
    "Viimeiset kolme kuukautta",                              # the default clarifying option
    "Your euro spending in August 2026 was {{n1}}, and most of it went to rent.",
    "Want to see what a cut would save? Ask, for example: what if I cut restaurants by half?",
    "Haluatko nähdä, paljonko vähennys säästäisi? Kysy esimerkiksi: entä jos vähentäisin ravintoloita puoleen?",
])
def test_ordinary_text_still_passes(text):
    assert check_text(text, ALLOWED) == []


# ---- #105: an invisible-only message never reaches the model --------------------------------------

@pytest.fixture
def client(tmp_path, monkeypatch):
    for name in ("DATABASE_URL", "AUDIT_API", "ASK_RATE_LIMIT_PER_MIN", "TRUSTED_PROXIES"):
        monkeypatch.delenv(name, raising=False)
    app = create_app(Settings(_env_file=None))
    model = ScriptedModel(plans=[[FunctionCall("fake_spending", {}), FunctionCall("finish")]], drafts=[])
    data = FakeData()
    audit = AuditLog(tmp_path / "audit")
    app.state.agent = Agent(pipeline=Pipeline(registry(), model, data, as_of=AS_OF, audit=audit), data=data,
                            audit=audit, limits=AskLimits(0, 0, 0))
    with TestClient(app) as c:
        c.model = model
        yield c


def ask(client, message):
    return client.post("/api/ask", json={"customer_id": "CUST00860", "conversation_id": None, "message": message,
                                         "language": "auto"}, headers={"Accept": "application/json"})


@pytest.mark.parametrize("message", ["​​​", "⁠﻿", "‎‏‮", " ​ \t "])
def test_an_invisible_message_is_rejected_before_the_model(client, message):
    response = ask(client, message)
    assert response.status_code == 400 and response.json()["error"]["code"] == "invalid_request"
    assert client.model.plan_inputs == []


def test_a_real_message_with_invisible_marks_still_runs(client):
    assert ask(client, "​Restaurants in August 2026?​").status_code != 400
    assert len(client.model.plan_inputs) == 1


# ---- review of #129: obfuscation, Finnish word forms, slang -----------------------------------------

@pytest.mark.parametrize("text", [
    "Your balance is three hun\u200bdred euros.",              # zero-width space inside a word
    "Säästit tu\u00adhat euroa.",                               # soft hyphen
    "That is a thou\u2060sand more.",                           # word joiner
    "That is a thou\ufeffsand more.",                           # BOM
    "Your balance is three hun\u0301dred euros.",              # combining mark
    "Your balance is three hun-dred euros.",                    # visible hyphen inside the word
    "Your balance is one \uff54\uff48\uff4f\uff55\uff53\uff41\uff4e\uff44 euros.",   # fullwidth letters
    "Your balance is one th\u043eusand euros.",                # Cyrillic o in "thousand"
    "Open \uff4a\uff41\uff56\uff41\uff53\uff43\uff52\uff49\uff50\uff54:alert(x) now.",  # fullwidth scheme
    "Maksoit sadalla eurolla.",                                 # inflected magnitudes, whole words
    "Nousi sataan euroon.",
    "Sadat eurot menivät ruokaan.",
    "Tuhannet eurot menivät asumiseen.",
    "Se maksoi kahdensadan euron verran.",
    "Säästö oli kolmetuhatta euroa.",
    "That costs a grand.",                                      # slang and unit forms
    "That is five k a year.",
    "You spent fifty bucks on taxis.",
    "That is ten pct more.",
    "You spent \u20actwenty on parking.",
    "You spent EUR twenty on parking.",
    "Se maksoi tonnin.",
    "Annoit satasen.",
    "Annoit kympin.",
    "Ostit sen kympillä.",
])
def test_obfuscated_and_slang_numbers_are_rejected(text):
    assert rejected(text)


@pytest.mark.parametrize("text", [
    "Voit osata säästää, jos tasata laskut kumppanin kanssa.",   # osata, tasata: ordinary verbs
    "Älä kasata kuluja kuun loppuun.",                           # kasata
    "Jos huomenna sataa, käytät ehkä taksia.",                   # sataa: it rains
    "Sataman pysäköinti näkyy liikenteessä.",
    "Your **regular** and **flexible** costs: [regular] [flexible].",
    "In August 2026 you spent a grand total of {{n1}}.",
    "Käytit elokuussa 2026 ruokaan {{n1}}.",                     # precomposed Finnish letters
    "This is a one-off, not a habit.",
])
def test_ordinary_finnish_verbs_and_brackets_still_pass(text):
    assert check_text(text, ALLOWED) == []


@pytest.mark.parametrize("message", ["\u2800\u2800", "\u3164", "\u0301\u0301", " \u2800 \u0308 "])
def test_blank_look_alikes_and_mark_only_messages_are_empty(client, message):
    response = ask(client, message)
    assert response.status_code == 400 and client.model.plan_inputs == []


# ---- review of PR #219: inflected Finnish cardinals next to an inflected unit -------------------------

@pytest.mark.parametrize("text", [
    "Säästäisit kahdellakymmenellä eurolla.",
    "Säästäisit kolmellakymmenellä eurolla.",
    "Säästäisit kymmenellä eurolla.",
    "Menot laskisivat viidelläkymmenellä prosentilla.",
    "Säästäisit kahdeksallatoista eurolla.",
    "Se maksoi kahdenkymmenen euron verran.",
    "Se on neljänkymmenen prosentin osuus.",
    "Säästäisit yhdellä eurolla.",
    "Säästäisit kolmella eurolla.",
    "Säästäisit viidellä eurolla.",
    "Kulutus nousi neljässä eurossa.",                          # inessive unit
    "Summa muuttui kahdeksi euroksi.",                          # translative
    "Viidestä eurosta jäi jäljelle osa.",                       # elative
    "Kuuteen euroon asti.",                                     # illative
    "Se maksoi tonnin.",                                        # tonni as a whole word with case forms
    "Tonneilla euroilla.",
])
def test_inflected_finnish_cardinals_and_units_are_rejected(text):
    assert rejected(text)


@pytest.mark.parametrize("text", [
    "Söin tonnikalaa lounaaksi.",                               # tonnikala is not "tonni"
    "Ostit ruokaa Seven K-Marketista.",                         # K-Market is not "k" after a number
    "That was a grand idea.",
    "Käytit yhtä paljon kuin viime kuussa.",
    "Kuusi kuukautta sitten ja kolmen kuukauden aikana.",       # lengths of time, no unit
    "Euroopan unionissa hinnat vaihtelevat.",                   # Euroopan is not "euroa"
    "Kymmenen minuutin päästä.",
    "Viidessä kategoriassa kulutus pysyi ennallaan.",           # a numeral without a unit
])
def test_ordinary_finnish_still_passes(text):
    assert check_text(text, ALLOWED) == []
