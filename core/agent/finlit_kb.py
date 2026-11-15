"""Financial-literacy answers grounded in official Finnish sources (#884), on Maxim's finlit retrieval (core/finlit).

A general money question ("mikä on budjetti", "how do I build a buffer", "mitä on korkoa korolle") is answered in
plain words by the composer, with 2-3 retrieved fragments in its data and one source line added by code
("Source: <publisher>, <url>" / "Lähde: <publisher>, <url>"). The talk mode (#873) asks for the same fragments.

Rules kept here, not in the prompt:
- Fragments are in the question's language and the customer's age band (or "all"), as the Retriever filters.
- Only sources of a public or non-profit tier are used: authority, public education, international organisation,
  academic, non-profit. Banks, industry associations and "other" are left out (no products, no other bank), and so
  are datasets (their numbers are facts, not an explanation's source).
- A fragment's text reaches the composer only from licence_class open_attribution page text; every other source
  is a title and a link. Digits in a fragment's text are masked, and the draft may state no number at all (the
  validator with no Numbers), so no figure from a source reaches an answer.
- `question_kind` claims only a literacy question: a question frame plus a money topic, never the user's own
  figures, borrowing, a product or investment, S-Bank or S-mobiili (those keep their own routes).

One new question costs one Gemini embedding request (the embedding model's own quota), cached on disk afterwards
(core/finlit/embed.py). The request waits at most EMBED_WAIT_S in the answer; a slower one finishes in the
background and fills the cache. Any failure leaves the message to the usual path.
"""

from __future__ import annotations

import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any, Callable

from core.agent import guard

log = logging.getLogger("uvicorn.error")

EMBED_WAIT_S = 3.0
MAX_FRAGMENTS = 3
# A fragment farther than this cosine distance from the question is not used (None: no floor). Calibrated on the
# probes (15.11): the acceptance questions' sources lie at 0.27-0.37 (why save 0.33-0.37, tips 0.29-0.37, compound
# interest 0.27-0.36), strong pairs at 0.24-0.34; the weak ones start at 0.398 ("Mikä on verokortti?" for 25-34 ->
# InfoFinland's financial-problems page) and include buffer -> Finanssivalvonta's home reserve (0.44) and scam ->
# financial problems (0.42). A weak source is worse than none: below the floor the answer names no source.
MAX_DISTANCE: float | None = 0.39
ALLOWED_TIERS = frozenset({"authority", "public_education", "international_org", "academic", "nonprofit"})
APP_BANDS = ("0-12", "13-17", "18-24", "25-34", "35-44", "45-54", "55-64", "65-74", "75+")
# The two glossary terms that are general ideas rather than Sentti's own figures: "What is a budget?" and "What is
# interest?" get the grounded answer first and keep the glossary's definition as the fallback. Every other glossary
# term (safe to spend, buffer, peer median, ...) stays with the glossary.
GLOSSARY_TERMS = frozenset({"budget", "interest"})
SOURCE_LINE = ("Source: {publisher}, {url}", "Lähde: {publisher}, {url}")

# All patterns run on guard.fold(message): lower case, no diacritics.
_FRAME = re.compile(
    r"^(?:so |and |ok |okay |hmm |no niin |entas |entä |entäs |ja )?"
    r"(?:what(?:'s| is| are| does| do)\b|whats\b|how (?:do|does|can|could|should|would) (?:i|you|one|people|we)\b"
    r"|how to\b|how does\b|why (?:is|are|should|do|does)\b|explain\b|tell me (?:about|what|how|why)\b"
    r"|(?:any |some |give me |share )?(?:tips|advice|ideas)\b"
    r"|is it (?:bad|good|ok|okay|fine|wise|smart|worth|wrong|normal|important|a good idea|a bad idea)\b"
    r"|onko (?:se |ok |okei )?(?:paha|pahasta|huono|hyva|jarkevaa|fiksua|ok|okei|normaalia|vaarin)\b"
    r"|mika on\b|mita on\b|mita (?:tarkoittaa|tarkoitetaan|ovat)\b|mitka ovat\b|miten\b|kuinka\b|miksi\b|selita\b"
    r"|kerro\b|anna (?:vinkkeja|neuvoja)\b|(?:onko )?vinkkeja\b|neuvoja\b|kannattaako\b)")
_TOPIC = re.compile(
    r"budget|buffer|emergency (?:fund|savings)|rainy[ -]day|\bsav(?:e|es|ing|ings)\b|compound interest|\binterest\b"
    r"|inflation|\bdebts?\b|payment default|credit (?:rating|record|history)|debt collection|enforcement|tax card"
    r"|\btax(?:es)?\b|payslip|pay slip|financial literacy|money management|managing money|\bscams?\b|fraud|phishing"
    r"|cost of living|household (?:budget|finances|costs)|needs (?:and|vs\.?|versus) wants|impulse (?:buy|purchas)"
    r"|consumer rights|personal finance|\bfinances\b|\bmoney\b|\bbills?\b|\bspend(?:ing)?\b|hobb(?:y|ies)"
    r"|\bshopping\b|\btravel\b|harrastu\w*|\bkulut\w*|tuhla\w*|ostoks\w*|matkustami\w*"
    r"|budjet|puskur|hatavar|hatarahast|saasta|saasto|saastami|korkoa korolle|\bkorko|\bkoron\b|inflaatio|\bvelk|\bvelat"
    r"|maksuhairi|perinta|perinnan|ulosott|verokort|\bvero\b|\bverot\b|palkkalaskelm|talousosaami|raha-asi|rahankay"
    r"|huijau|huijari|elinkustannu|kotitalou|heraeteost|heratteost|kuluttajan oikeu|\braha\b|\brahaa\b|\blasku")
# The user's own figures (also "How do I compare with people my age?"): their data, never a general answer.
_OWN = re.compile(
    r"\bmy\b|\bmine\b|\b(?:i|we) (?:spent|paid|bought|earned|saved|owe)\b|\bam i\b|\bdid i\b|\bhave i\b"
    r"|\bdo i have\b|\bhow much (?:do|did|have|can|could|will|should) (?:i|we) (?:spend|spent|have|save|pay|get)\b"
    r"|\b(?:minun|mun) (?:kulu|saast|tili|tulo|palk|lasku|raha|budjet|puskur|meno|velk|osto)\w*"
    r"|\bminulla\b|\bmulla\b|\bolenko\b|\bkaytin\b|\bkulutin\b|\bmaksoin\b|\bostin\b|\bsaastin\b"
    r"|\b(?:rahani|menoni|saastoni|tuloni|palkkani|kuluni|laskuni|tilini|saldoni|budjettini|puskurini|velkani)\b")
# Asking to borrow, or naming a credit product: the planner's credit decline, never a literacy answer.
_BORROW = re.compile(
    r"\bloans?\b|\bborrow\w*|credit card|\bcredit\b(?! (?:rating|record|history))|overdraft|instal+ments?|financing"
    r"|buy now|\bbnpl\b|\bmortgage|\blaina\w*|\blainaa\b|luotto\w*|pikavip\w*|vippi\w*|osamaks\w*|asuntolain\w*")
# A product, an investment, a bank or S-Bank's own services: other routes (the planner's investment decline, the
# S-Bank knowledge base), never a literacy answer.
_PRODUCT = re.compile(
    r"(?<!emergency )(?<!rainy day )(?<!rainy-day )\bfunds?\b|\bstocks?\b|\bshares\b|\binvest\w*|crypto\w*|bitcoin"
    r"|\betf\b|\binsurance\b|\bpension\w*|\bbrokers?\b|\baccounts?\b|\bbanks?\b|\bbanking\b|\bcards?\b|\bapps?\b"
    r"|\b(?!hata|puskuri|varmuus|turva)\w*rahasto\w*|\w*osake\w*|\bsijoit\w*|\w*vakuutu\w*|\belake\w*|\btili\w*|\w*pankki\w*|\w*pankin\b|\b(?!vero)\w*kortti\w*"
    r"|\w*kortin\b|\bsovellu\w*|s-?mobiili|s-?bank|\bbonus\w*|s-?etu\w*")


# A period ("last month", "in August", "viime kuussa", "elokuussa") asks about the user's own figures.
_PERIOD = re.compile(
    r"\b(?:last|this|next|past) (?:month|week|year|quarter)\b|\b(?:yesterday|today|tonight)\b"
    r"|\bin (?:january|february|march|april|may|june|july|august|september|october|november|december)\b"
    r"|\bviime (?:kuu|viiko|vuo)\w*|\btalla viikolla\b|\btassa kuussa\b|\btana vuonna\b|\beilen\b|\btanaan\b"
    r"|\b(?:tammi|helmi|maalis|huhti|touko|kesa|heina|elo|syys|loka|marras|joulu)kuu\w*")
# A concept or judgement question ("what is budgeting?", "is it bad to spend on hobbies?", "mitä on budjetointi?",
# "onko paha …?") asks about the idea, not the user's figures: the literacy route answers it even when a data rule
# would claim the message (a rules decline still wins; the glossary keeps its own terms).
CONCEPT = re.compile(
    r"^(?:so |and |ok |okay |hmm )?(?:what(?:'s| is| are| does .* mean)\b|whats\b|explain\b"
    r"|is it (?:bad|good|ok|okay|fine|wise|smart|worth|wrong|normal|important|a good idea|a bad idea)\b"
    r"|mika on\b|mita on\b|mita (?:tarkoittaa|tarkoitetaan)\b|mitka ovat\b|selita\b"
    r"|onko (?:se |ok |okei )?(?:paha|pahasta|huono|hyva|jarkevaa|fiksua|ok|okei|normaalia|vaarin)\b)")


def overrides_rules(message: str) -> bool:
    """True for a why-should, concept or judgement question: the literacy route answers it over a data rule."""
    folded = guard.fold(message or "").strip()
    return bool(WHY_GENERAL.search(folded) or CONCEPT.search(folded))


def age_band(age: Any) -> str | None:
    """The app band of an age in years (core/knowledge/finlit/README.md), or None when the age is unknown."""
    try:
        years = int(age)
    except (TypeError, ValueError):
        return None
    if years < 0:
        return None
    for limit, band in ((12, "0-12"), (17, "13-17"), (24, "18-24"), (34, "25-34"), (44, "35-44"), (54, "45-54"),
                        (64, "55-64"), (74, "65-74")):
        if years <= limit:
            return band
    return "75+"


def question_kind(message: str) -> str | None:
    """"literacy" for a general financial-literacy question, else None (the usual path)."""
    folded = guard.fold(message or "").strip()
    if not folded or re.search(r"\d", folded) or len(folded) > 200:
        return None
    if _OWN.search(folded) or _BORROW.search(folded) or _PRODUCT.search(folded) or _PERIOD.search(folded):
        return None
    if not (_FRAME.search(folded) and _TOPIC.search(folded)):
        return None
    return "literacy"


def has_money_topic(message: str) -> bool:
    """True when the message names a money topic ("why does a buffer matter?"); a bare "why does it matter?" does not,
    so the talk mode (#873) asks for fragments only when they can be about something."""
    return bool(_TOPIC.search(guard.fold(message or "")))


def flags_allow(message: str, raw: str) -> bool:
    """True when the guard raises no flag, or only the investment flag for an emergency or rainy-day fund (a buffer,
    not a product): "What is an emergency fund?" is a literacy question."""
    flags = guard.flags(message, raw=raw)
    if not flags:
        return True
    if set(flags) != {"investment_keyword"}:
        return False
    swapped = re.sub(r"(?i)\b(emergency|rainy[ -]day)\s+funds?\b", r"\1 savings", message)
    return not guard.flags(swapped, raw=swapped)


@dataclass(frozen=True)
class Fragment:
    source_id: str
    publisher: str
    title: str
    url: str
    text: str | None      # open_attribution page text with digits masked, else None (a link only)
    kind: str             # page_text | source_card
    distance: float | None = None   # cosine distance of the chunk to the question (0 = the same direction)

    def record(self) -> dict[str, Any]:
        """The fragment as the conversation turn keeps it (turn["finlit"]): ids, publisher, title, link, open text."""
        return {"source_id": self.source_id, "publisher": self.publisher, "title": self.title, "url": self.url,
                "text": self.text, "kind": self.kind}

    def data(self, include_text: bool = True) -> dict[str, Any]:
        """What the composer sees: never the link, never a digit; the text only when this source is named."""
        out: dict[str, Any] = {"source": self.publisher, "title": _mask(self.title)}
        if self.text and include_text:
            out["text"] = self.text
        return out


def _mask(text: str) -> str:
    return re.sub(r"\d(?:[\d\s.,:]*\d)?(?:\s*(?:%|€))?", "[number]", text or "")


def short_publisher(publisher: str) -> str:
    """The publisher's name for the source line: up to the first ';', '.', ' with ', ' (' clause, at most 60 chars."""
    name = re.split(r";|\. | with | yhdessä | \(| – | - ", publisher or "", maxsplit=1)[0].strip(" ,")
    if len(name) > 60:
        name = name[:60].rsplit(" ", 1)[0]
    return name or (publisher or "").strip()[:60]


def named(fragments: list[Fragment]) -> list[Fragment]:
    """The sources an answer names: the best-ranked one, and the best one whose open text was sent when that is
    another (CC BY text is always credited). Only these send their text to the composer."""
    if not fragments:
        return []
    top = fragments[0]
    text = next((f for f in fragments if f.text), None)
    return [top] if text is None or text is top else [top, text]


def sources_field(fragments: list[Fragment], lang: str) -> list[dict[str, str]]:
    """The done event's `sources` (contract 0.3.19): up to MAX_FRAGMENTS, in retrieval order, one per link, https only;
    each {publisher, title, url, lang}. The app shows them as a Sources row under the answer; the text has no link."""
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for f in fragments:
        if not f.url.startswith("https://") or f.url in seen:
            continue
        seen.add(f.url)
        out.append({"publisher": short_publisher(f.publisher), "title": f.title, "url": f.url, "lang": lang})
        if len(out) == MAX_FRAGMENTS:
            break
    return out


def source_line(fragments: list[Fragment], lang: str) -> str:
    """'Source: <publisher>, <url>' (or 'Lähde: ...'); two sources are joined with '; '."""
    head = SOURCE_LINE[1 if lang == "fi" else 0].split(" {")[0]   # "Source:" / "Lähde:"
    return head + " " + "; ".join(f"{short_publisher(f.publisher)}, {f.url}" for f in fragments)


class FinlitSource:
    """Fragments for a question from schema finlit. `connect` gives a database connection (the service's pool);
    `embedder` is a core.finlit.embed.Embedder. Thread-safe: one embedding request at a time."""

    def __init__(self, connect: Callable[[], AbstractContextManager[Any]], embedder: Any, model: str,
                 wait_s: float = EMBED_WAIT_S) -> None:
        self.connect = connect
        self.embedder = embedder
        self.model = model
        self.wait_s = wait_s
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="finlit-embed")
        self.calls = 0   # fragments() calls that reached the database

    def _embed(self, question: str) -> list[float]:
        from core.finlit.embed import QUERY

        with self._lock:
            return self.embedder.embed([question], QUERY)[0]

    def query_vector(self, question: str) -> list[float] | None:
        future = self._pool.submit(self._embed, question)
        try:
            return future.result(timeout=self.wait_s)
        except FutureTimeout:
            log.warning("finlit: the embedding request took over %.1f s; the answer goes without it", self.wait_s)
            return None

    def fragments(self, question: str, lang: str, band: str | None, k: int = MAX_FRAGMENTS) -> list[Fragment]:
        """Up to k fragments, best first, at most one per source; [] when anything fails."""
        if lang not in ("en", "fi"):
            return []
        try:
            vec = self.query_vector(question)
            if vec is None:
                return []
            from core.finlit.retrieve import Retriever

            with self.connect() as conn:
                self.calls += 1
                hits = Retriever(conn, None, self.model).search(question, lang, band if band in APP_BANDS else None,
                                                                k_texts=12, k_facts=0, per_source=1,
                                                                query_vec=vec).texts
                meta = _sources(conn, [h.source_id for h in hits])
                dist = _distances(conn, self.model, vec, [h.chunk_id for h in hits])
        except Exception as exc:  # noqa: BLE001 - the class name only: a driver message can carry the URL
            log.warning("finlit: retrieval failed (%s); the usual path answers", type(exc).__name__)
            return []
        out: list[Fragment] = []
        for h in hits:
            m = meta.get(h.source_id)
            url = str(h.source_url)
            if (m is None or m["tier"] not in ALLOWED_TIERS or m["kind"] == "dataset" or not url.startswith("https://")
                    or "/api/" in url.lower()):
                continue   # a dataset is for numbers (facts), and an API endpoint is no page to send a person to
            open_text = h.kind == "page_text" and m["licence_class"] == "open_attribution"
            d = dist.get(h.chunk_id)
            if MAX_DISTANCE is not None and d is not None and d > MAX_DISTANCE:
                continue   # too far from the question to be named as its source
            out.append(Fragment(h.source_id, m["publisher"], h.title, h.source_url,
                                _mask(h.text) if open_text else None, h.kind, d))
            if len(out) == k:
                break
        return out


# "Why should I save money?" asks for reasons, not for the customer's savings plan: the literacy route answers it
# even when a data rule would claim the message (a rules decline still wins).
WHY_GENERAL = re.compile(r"^(?:so |and |ok )?(?:why (?:should|would|do|does) (?:i|you|one|people|we) "
                         r"|why (?:is|are) (?:it|saving|a budget|a buffer|budgeting) (?:important|good|smart|wise|useful)"
                         r"|miksi (?:mun |minun |mina |ma |ihmisten |kannattaa|pitaisi|pitais|on tarkeaa))")

# "Why should I save?" when no draft passes the checks: our fixed reasons, with no number, no product, no source.
WHY_SAVE_TEXT = (
    "Saving gives you a cushion for surprises, so an unexpected bill does not upset your month. It also lets you plan "
    "for things you want later, without stress. Even small amounts set aside regularly build up that security over "
    "time.",
    "Säästäminen antaa puskurin yllätyksiin, joten odottamaton lasku ei sotke kuukauttasi. Se auttaa myös "
    "suunnittelemaan asioita, joita haluat myöhemmin, ilman stressiä. Pienetkin säännöllisesti sivuun laitetut summat "
    "kasvattavat turvaa ajan myötä.")
_SAVE = re.compile(r"\bsav(?:e|es|ing|ings)\b|saast")


def why_fallback(message: str, lang: str) -> str | None:
    """The fixed reasons for a why-save question (WHY_GENERAL about saving), else None (the usual path answers)."""
    folded = guard.fold(message or "")
    if WHY_GENERAL.search(folded) and _SAVE.search(folded):
        return WHY_SAVE_TEXT[1 if lang == "fi" else 0]
    return None


# Tips or advice asked in a running conversation are the talk mode's, from the customer's own data (#873).
TIPS = re.compile(r"\btips\b|\badvice\b|\bideas\b|\bsuggest\w*|vinkk\w*|neuvo\w*|ehdot\w*|mita (?:mun|minun) pitais")

# What a literacy draft may never say, on the folded text (no diacritics): borrowing, a product or investment, a bank
# or brand by name, a statement about the user's own money (no data was read), a non-answer, a source or a link.
FORBIDDEN = (
    (re.compile(r"\b(?:take|taking|get|getting|apply for) (?:out )?(?:a |an |some )?(?:loan|credit)|\bborrow\w*"
                r"|credit cards?|overdraft|buy now|pikavip\w*|\bvipp\w*|osamaks\w*|luottokort\w*"
                r"|(?:ota|ottaa|otat|ottamalla|ottaminen|hae|hakea|hakemalla) (?:\w+ )?lainaa?\b"),
     "it suggests borrowing or a credit product; a literacy answer never does"),
    (re.compile(r"\binvest\w*|\bstocks?\b|\bshares\b|\betfs?\b|crypto\w*|bitcoin|(?<!emergency )\bfunds?\b"
                r"|sijoit\w*|osake\w*|(?<!hata)(?<!puskuri)(?<!varmuus)(?<!turva)rahasto\w*"),
     "it mentions investing or an investment product; a literacy answer never does"),
    (re.compile(r"\bnordea\b|osuuspankk\w*|\bop[- ]pohjola\b|danske|s-?pankk\w*|s-?bank\b|handelsbanken|\baktia\b"
                r"|saastopankk\w*|pop pankk\w*|klarna|revolut|mobilepay|s-?mobiili"),
     "it names a bank, a brand or an app; a literacy answer names none"),
    (re.compile(r"\byou (?:spent|paid|earned|saved|have spent|have saved)\b|\bkaytit\b|\bkulutit\b|\bmaksoit\b"
                r"|\bsaastit\b"),
     "it states what the user did with their money; no data was read for this answer"),
    (re.compile(r"could not work|couldn't work|cannot work|can't work|could not calculate|en pystynyt|en voinut"
                r"|ei voitu laskea|could not find|couldn't find|can't find|cannot find|no data|en loytanyt|en loyda"
                r"|ei tietoja|tietoja ei"),
     "it says something could not be worked out; a literacy answer explains the idea in plain words"),
    (re.compile(r"\bsource:|\blahde:|https?:|www\.|\.fi\b|\.com\b"),
     "it names a source or a link; the server adds the source line"),
    (re.compile(r"\b(?:two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|fifteen|twenty|thirty|forty|fifty"
                r"|hundreds?|thousands?|millions?|billions?|half|halves|twice|double|triple|quarters?|thirds?|dozens?"
                r"|percent|per cent)\b"
                r"|\b(?:kaksi|kahden|kahdeksan\w*|kolme|kolmen|kolmas\w*|kolmannes\w*|nelja\w*|viisi|viiden|kuusi"
                r"|kuuden|seitseman\w*|yhdeksan\w*|kymmen\w*|sata|sadan|satoja|tuhat|tuhannen|tuhansi\w*|miljoon\w*"
                r"|puolet|puolikas\w*|kaksinkertai\w*|prosent\w*)\b"),
     "it states a number in words; a literacy answer states no number in any form"),
)


def draft_problems(raw: Any, language: str) -> tuple[Any, list[str]]:
    """Every check a literacy draft passes before it is shown (#884), as retry reasons: the validator with no
    Numbers and nothing allowed (no digit, no date, no markup, the right language field), cited empty, the length rule
    for a general answer (four sentences at most), the model-draft checks, the text in the answer's language and
    FORBIDDEN. Returns the draft and the reasons."""
    from core.agent.validator import Allowed, validate
    from core.agent.validator import draft_problems as model_draft_problems
    from core.answer_text import length_problems

    draft, errors = validate(raw, language=language, numbers={}, allowed=Allowed(frozenset(), frozenset()))
    if errors or draft is None:
        return draft, errors or ["no draft"]
    text = draft.text
    errors = length_problems(text, 0, kind="general") + model_draft_problems(text, {}, has_data=True)
    if draft.cited:
        errors.append("cited must be empty: a literacy answer states no number")
    detected = guard.confident_language(text)
    if detected in ("en", "fi") and detected != language:
        errors.append(f"the text is not in the answer language ({language})")
    folded = guard.fold(text)
    for rx, reason in FORBIDDEN:
        m = rx.search(folded)
        if m:
            errors.append(f"'{m.group(0)}': {reason}")
    return draft, errors


def _distances(conn: Any, model: str, vec: list[float], chunk_ids: list[str]) -> dict[str, float]:
    from core.finlit.store import vector_literal

    if not chunk_ids:
        return {}
    rows = conn.execute("SELECT chunk_id, embedding <=> %s::vector FROM finlit.chunk_embeddings "
                        "WHERE model = %s AND chunk_id = ANY(%s)", (vector_literal(vec), model, chunk_ids)).fetchall()
    return {r[0]: float(r[1]) for r in rows}


def _sources(conn: Any, ids: list[str]) -> dict[str, dict[str, str]]:
    if not ids:
        return {}
    rows = conn.execute("SELECT id, publisher, tier, licence_class, kind FROM finlit.sources WHERE id = ANY(%s)",
                        (ids,)).fetchall()
    return {r[0]: {"publisher": r[1], "tier": r[2], "licence_class": r[3], "kind": r[4]} for r in rows}


def from_settings(settings: Any, connect: Callable[[], AbstractContextManager[Any]]) -> FinlitSource | None:
    """The service's source, or None (the route is off): no Gemini key, FINLIT_RAG=off, or the package missing."""
    import os

    if (os.environ.get("FINLIT_RAG") or "on").strip().lower() in ("off", "0", "false", "no"):
        return None
    key = getattr(settings, "gemini_api_key", None)
    if not key:
        return None
    try:
        from core.finlit.embed import Embedder
        from core.finlit.settings import FinlitSettings
        from google import genai

        model = FinlitSettings().finlit_embed_model
        # A 10 s client timeout: the API refuses a shorter server deadline; the answer waits EMBED_WAIT_S at most.
        client = genai.Client(api_key=key.get_secret_value(), http_options={"timeout": 10_000})
        return FinlitSource(connect, Embedder(client, model, max_retries=0), model)
    except Exception as exc:  # noqa: BLE001
        log.warning("finlit: retrieval is off (%s)", type(exc).__name__)
        return None
