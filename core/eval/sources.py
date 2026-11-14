"""Answer sources for the eval runner (core/eval/run.py, issue #40).

An answer source is a callable (customer_id, question, language) -> Answer.

- ReferenceSource answers each eval question from SQL, with the same functions that produce the
  expected values (expected.py), and writes a plain templated text in English or Finnish with
  locale number formats. It is the "perfect coach": it shows that the eval set is consistent with
  the data today, and that the checks accept a correct answer in both languages.
- ApiSource asks the coach's POST /api/ask (contracts/api.md, section 7.4, Accept: application/json)
  and reads the tool calls from the internal audit endpoint GET /api/audit/{answer_id}
  (agent-core.md section 9.1). It is written against the contract and has not run yet: the coach
  does not exist at the time of writing.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field

import expected
from core import answer_text

# Data tools of agent-core.md section 6.2. decline, ask_clarifying_question and finish read no data.
DATA_TOOLS = {"get_spending", "get_basket_breakdown", "get_recurring_bills", "get_safe_to_spend", "run_what_if",
              "get_spender_profile", "get_peer_benchmark", "compare_store_prices", "down_payment_plan",
              "get_balance_forecast"}


@dataclass
class Answer:
    text: str                          # the text as the user sees it (text_rendered)
    outcome: str                       # answered | refused | clarify | fallback (contract section 7)
    refusal_kind: str | None = None    # refusal.kind when refused
    numbers: list[dict] = field(default_factory=list)   # Number objects: value, unit, period, ...
    dates: list[str] = field(default_factory=list)      # ISO dates the answer returned (as_of, due dates, payday)
    labels: list[str] | None = None    # keys the answer reports (profile, what-if status); None = unknown
    tool_calls: list[str] | None = None  # tool and function names called; None = unknown
    error: str | None = None           # the source could not produce an answer (HTTP error, ...)
    # The numbers the answer's tool calls returned (from the audit's model views): a declared number
    # outside a case's list passes only if it is one of these. None = unknown.
    tool_numbers: list[dict] | None = None
    follow_ups: list[str] | None = None  # the chips the answer offers (done.follow_ups); None = unknown


# ---- reference source ------------------------------------------------------------------------------

REFUSAL = {
    "investment_advice": {
        "en": "I can't give investment advice, such as which shares or funds to choose. I can show how much "
              "you could set aside each month. For investing, an S-Pankki adviser can help.",
        "fi": "En voi antaa sijoitusneuvontaa, esimerkiksi mitä osakkeita tai rahastoja kannattaa valita. Voin "
              "näyttää, paljonko voisit säästää kuukaudessa. Sijoittamisessa S-Pankin neuvoja auttaa.",
    },
    "credit_decision": {
        "en": "I can't predict loan decisions or rate creditworthiness. The bank's loan process gives that answer. "
              "I can help you see what you could save each month.",
        "fi": "En voi ennustaa lainapäätöksiä enkä arvioida luottokelpoisuutta. Pankin lainaprosessi antaa "
              "vastauksen. Voin auttaa näkemään, paljonko voisit säästää kuukaudessa.",
    },
    "other": {
        "en": "I can only help with questions about your own money. You could ask: Where did my money go? "
              "What can I safely spend this week?",
        "fi": "Voin auttaa vain omiin raha-asioihisi liittyvissä kysymyksissä. Voit kysyä esimerkiksi: Mihin "
              "rahani menivät? Paljonko voin turvallisesti käyttää tällä viikolla?",
    },
}
NO_DATA = {
    "en": "There is no data for that period. Your transactions are available up to {date}.",
    "fi": "Tältä ajalta ei ole tietoja. Tapahtumasi ovat saatavilla {date} asti.",
}
INTRO = {"en": "Here is what I found.", "fi": "Tässä tulokset."}
NBSP = " "


def fmt_date(iso: str, lang: str) -> str:
    y, m, d = iso.split("-")
    return iso if lang == "en" else f"{int(d)}.{int(m)}.{y}"


def fmt_number(value, unit: str, lang: str, method: str | None = None) -> str:
    """The tools' own formatter (core/tools/formatting.display), so the reference answer's displays are
    exactly what the pipeline sends: en €1,234.56 / 12.5% / "€45.91 a month", fi 1 234,56 € / 12,5 %;
    with the method, a typed cut is "20%"."""
    return answer_text.formatted(value, unit, lang, method)


def label_of(name: str) -> str:
    return name.replace("_", " ")


def method_of(src: dict) -> str:
    if "metric" in src:
        return f"{src['metric']}.{src['column']}@1"
    if src.get("query") == "bonus":  # the tool's own method ids (core/tools/bonus.py, #216)
        return f"bonus_estimate.{src['column']}_eur@1"
    return {"total_eur": "spending.total@1", "n_tx": "spending.n_tx@1",
            "change_eur": "spending.change@1", "change_pct": "spending.change_pct@1"}[src["column"]]


class ReferenceSource:
    def __init__(self, doc: dict):
        self.as_of = str(doc["as_of"])
        self.db = expected.connect(self.as_of)
        self.index = {(c["persona"], q): c for c in doc["cases"] for q in c["question"].values()}

    def stats(self) -> str:
        return f", {self.db.queries} queries, {self.db.seconds:.2f} s in the database"

    def __call__(self, customer_id: str, question: str, language: str) -> Answer:
        case = self.index.get((customer_id, question))
        if case is None:  # the reference only knows the eval questions
            return Answer(text=REFUSAL["other"][language], outcome="refused", refusal_kind="out_of_scope",
                          labels=[], tool_calls=[])
        if case["expect"] == "meta":  # Sentti introduces itself (#287): the template text and the four chips
            from core.agent import template
            lang = language if language in ("en", "fi") else "en"
            return Answer(text=template.meta_text(case["intent"], lang), outcome="answered", labels=[],
                          tool_calls=[], follow_ups=template.brief_questions(lang))
        if case["expect"] == "refused":
            kind = case["refusal_kinds"][0]
            text = REFUSAL.get(kind, REFUSAL["other"])[language]
            return Answer(text=text, outcome="refused", refusal_kind=kind, labels=[], tool_calls=["decline"])
        if case["expect"] == "no_data":
            return Answer(text=NO_DATA[language].format(date=fmt_date(self.as_of, language)), outcome="answered",
                          dates=[self.as_of], labels=[], tool_calls=["get_spending"])

        numbers, parts = [], [INTRO[language]]
        for item in case.get("numbers") or []:
            src = item["source"]
            value = expected.fresh_value(self.db, customer_id, item)
            period = None
            if src.get("query") in ("spending", "spending_change"):
                period = {"start": src["start"], "end": min(src["end"], self.as_of)}
            method = method_of(src)
            shown = fmt_number(value, item["unit"], language, method)
            numbers.append({"name": item["name"], "value": value, "unit": item["unit"], "period": period,
                            "method": method, "display": shown})
            text = f"{label_of(item['name'])}: {shown}"
            if period:
                text += f" ({fmt_date(period['start'], language)} – {fmt_date(period['end'], language)})"
            parts.append(text + ".")
            pct = (src.get("settings") or {}).get("whatif_pct")
            # The cut is the user's own number: state it only when the question does.
            if pct is not None and str(pct) in question and not any(n["method"] == "user_input@1" for n in numbers):
                numbers.append({"name": "cut_pct", "value": float(pct), "unit": "percent", "period": None,
                                "method": "user_input@1", "display": fmt_number(pct, "percent", language, "user_input@1")})
                parts.append(f"{label_of('cut')}: {fmt_number(pct, 'percent', language, 'user_input@1')}.")
        dates = [self.as_of]
        for item in case.get("dates") or []:
            value = expected.fresh_value(self.db, customer_id, item)
            dates.append(value)
            parts.append(f"{label_of(item['name'])}: {fmt_date(value, language)}.")
        labels = []
        for item in case.get("labels") or []:
            value = expected.fresh_value(self.db, customer_id, item)
            labels.append(value)
            parts.append(f"{label_of(item['name'])}: {label_of(value)}.")
        return Answer(text=" ".join(parts), outcome="answered", numbers=numbers, dates=dates, labels=labels,
                      tool_calls=list(case.get("expected_tools") or []),
                      tool_numbers=[{"id": f"n{i + 1}", **n} for i, n in enumerate(numbers)])


# ---- the coach's API --------------------------------------------------------------------------------

ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _walk(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k, v
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


class ApiSource:
    def __init__(self, base_url: str, as_of: str, timeout: float = 60):
        self.base = base_url.rstrip("/")
        self.as_of = as_of
        self.timeout = timeout

    def _get_json(self, req) -> dict:
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.load(r)

    def __call__(self, customer_id: str, question: str, language: str) -> Answer:
        try:
            return self._ask(customer_id, question, language)
        except urllib.error.HTTPError as exc:
            return Answer(text="", outcome="error", error=f"HTTP {exc.code}")
        except (urllib.error.URLError, OSError, ValueError) as exc:
            return Answer(text="", outcome="error", error=type(exc).__name__)

    def _ask(self, customer_id: str, question: str, language: str) -> Answer:
        body = json.dumps({"customer_id": customer_id, "conversation_id": None, "message": question,
                           # a question in another language (Russian, #287) lets the service detect it
                           "language": language if language in ("en", "fi") else "auto"}).encode("utf-8")
        resp = self._get_json(urllib.request.Request(
            f"{self.base}/api/ask", data=body, method="POST",
            headers={"Content-Type": "application/json", "Accept": "application/json"}))
        numbers = list((resp.get("numbers") or {}).values())
        dates = {resp.get("as_of") or self.as_of}
        dates.update(v for _, v in _walk([resp.get("numbers"), resp.get("cards")]) if isinstance(v, str) and ISO.match(v))
        labels = []
        for card in resp.get("cards") or []:
            if card.get("type") == "profile":
                labels.append((card.get("profile") or {}).get("key"))
            if card.get("type") == "whatif":
                labels.append((card.get("result") or {}).get("status"))
        record = self._audit(resp.get("answer_id"))
        tool_calls = tool_numbers = None
        if record is not None:
            tool_calls = [c.get("name") for turn in record.get("planner_turns") or [] for c in turn.get("calls") or []]
            # Model views carry no method; the record's cited numbers do, so a cited tool number gets its
            # method from there (an uncited one keeps none and can match no declared number).
            methods = {k: (v or {}).get("method") for k, v in (record.get("numbers") or {}).items()}
            tool_numbers = [{**v, "method": methods.get(v["id"])} for _, v in _walk(record.get("tool_outputs") or {})
                            if isinstance(v, dict) and {"id", "value", "unit"} <= v.keys()]
        return Answer(text=resp.get("text_rendered") or resp.get("text") or "", outcome=resp.get("outcome"),
                      refusal_kind=(resp.get("refusal") or {}).get("kind"), numbers=numbers, dates=sorted(dates),
                      follow_ups=resp.get("follow_ups"),
                      labels=[x for x in labels if x], tool_calls=tool_calls, tool_numbers=tool_numbers)

    def _audit(self, answer_id: str | None) -> dict | None:
        """The audit record (GET /api/audit/{id}, needs AUDIT_API=1); None when it cannot be read, so the
        tool calls and tool numbers are unknown and those checks fail as "unverified"."""
        if not answer_id:
            return None
        try:
            return self._get_json(urllib.request.Request(f"{self.base}/api/audit/{answer_id}"))
        except Exception:
            return None

    def _tool_calls(self, answer_id: str | None) -> list[str] | None:
        record = self._audit(answer_id)
        if record is None:
            return None
        return [c.get("name") for turn in record.get("planner_turns") or [] for c in turn.get("calls") or []]
