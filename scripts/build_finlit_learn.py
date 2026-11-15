"""Build app/src/components/learn/finlitLearn.json from the finlit corpus (facts.jsonl, sources.jsonl).

    python scripts/build_finlit_learn.py <facts.jsonl> <sources.jsonl> [out.json]

For a few Learn lessons, one Statistics Finland number per app age band, as one sentence in EN and FI written
from the fact record's own fields (value, unit, decimals, period, the native age group): the app shows the
sentence as it is and does no maths. Only facts whose table is broken down by age are used; a lesson without a
clean fit has no entry. Plus one "Learn more" link card per topic (title, publisher, link; no page text).
Deterministic: no model, no embeddings, no network. Re-run it when the corpus changes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BANDS = ["18-24", "25-34", "35-44", "45-54", "55-64", "65-74", "75+"]
OUT = Path(__file__).resolve().parents[1] / "app" / "src" / "components" / "learn" / "finlitLearn.json"

# The statistic's page on stat.fi (the fact's own `source_url` is the PxWeb API, not a page to read).
PAGE = {"en": "https://stat.fi/en/statistics/{db}", "fi": "https://stat.fi/tilasto/{db}"}

# lesson key -> which fact, and how its sentence reads. `who`: households by the reference person's age, or people.
SPECS = {
    "money-1": {"table": "StatFin/ktutk/14q4.px", "measure": "kulukk_kt_hk_2_1", "dim": "0", "who": "households",
                "en": "{who}: {value} a month per consumption unit (Statistics Finland, {period})",
                "fi": "{who}: {value} kuukaudessa kulutusyksikköä kohden (Tilastokeskus, {period})"},
    "money-2": {"table": "StatFin/ktutk/14q4.px", "measure": "kulu_pro_kt_hk_2_1", "dim": "04", "who": "households",
                "en": "{who}: housing takes {value} of spending (Statistics Finland, {period})",
                "fi": "{who}: asuminen vie {value} kulutuksesta (Tilastokeskus, {period})"},
    "saving-2": {"table": "StatFin/eot/13iu.px", "measure": "expense_rpros", "dim": None, "who": "people",
                 "en": "{who}: {value} could not cover an unexpected expense (Statistics Finland, {period})",
                 "fi": "{who}: {value} ei pystyisi kattamaan yllättävää menoa (Tilastokeskus, {period})"},
}

# One "Learn more" card per topic: our own short title, the publisher, the link (card only, no copied text).
MORE = {
    "money": [{"source_id_prefix": "oikeuspalveluvirasto-keep-track-of-your-", "lang": "en",
               "title": {"en": "Keep track of your expenses", "fi": "Selvitä menosi"},
               "fi_source_id_prefix": "oikeuspalveluvirasto-selvita-menosi-"}],
    "saving": [{"source_id_prefix": "martat-", "name_contains": "Säästäminen", "lang": "fi",
                "title": {"en": "Saving and a rainy-day buffer (in Finnish)", "fi": "Säästäminen ja puskurirahasto"}}],
}


def number(value: float, decimals: int, unit: str, lang: str) -> str:
    text = f"{value:,.{decimals}f}"
    if lang == "fi":
        text = text.replace(",", " ").replace(".", ",")
    if unit == "euros":
        return f"{text} €" if lang == "fi" else f"€{text}"
    if unit == "%":
        return f"{text} %" if lang == "fi" else f"{text}%"
    return text


def age_label(native: str) -> str:
    """'35 - 44' -> '35–44', '75 -' -> '75+', '17 - 24' -> '17–24'."""
    parts = [p.strip() for p in native.split("-")]
    if len(parts) == 2 and parts[0] and not parts[1]:
        return f"{parts[0]}+"
    if len(parts) == 2 and parts[0] and parts[1]:
        return f"{parts[0]}–{parts[1]}"
    return native.strip()


def who(kind: str, age: str, lang: str) -> str:
    plus = age.endswith("+")
    if kind == "households":
        if lang == "fi":
            return f"Kotitaloudet, joiden viitehenkilö on {'vähintään ' + age[:-1] if plus else age}-vuotias"
        return f"Households headed by someone aged {age}"
    if lang == "fi":
        return f"{'Vähintään ' + age[:-1] if plus else age}-vuotiaat Suomessa"
    return f"People aged {age} in Finland"


def page_url(table: str, lang: str) -> str:
    _, db, _name = table.replace(".px", "").split("/")
    return PAGE[lang].format(db=db)


def build(facts_path: Path, sources_path: Path) -> dict:
    facts = [json.loads(line) for line in facts_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    sources = [json.loads(line) for line in sources_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    out: dict = {"source": {"en": "Statistics Finland (CC BY 4.0)", "fi": "Tilastokeskus (CC BY 4.0)"}, "facts": {}, "more": {}}
    for lesson, spec in SPECS.items():
        rows = [f for f in facts if f["table"] == spec["table"] and f["measure"]["code"] == spec["measure"]
                and (spec["dim"] is None or any(d["value"] == spec["dim"] for d in f["dims"]))]
        entries = {}
        for band in BANDS:
            fact = next((f for f in rows if band in f["age_bands"]), None)   # the first native group covering it
            if fact is None:
                continue
            age = age_label(fact["age_native"])
            entries[band] = {
                "id": fact["id"],
                "en": spec["en"].format(who=who(spec["who"], age, "en"), value=number(fact["value"], fact["decimals"], fact["unit"], "en"), period=fact["period"]),
                "fi": spec["fi"].format(who=who(spec["who"], age, "fi"), value=number(fact["value"], fact["decimals"], fact["unit"], "fi"), period=fact["period"]),
                "url": {"en": page_url(fact["table"], "en"), "fi": page_url(fact["table"], "fi")},
            }
        if entries:
            out["facts"][lesson] = entries
    for topic, cards in MORE.items():
        built = []
        for card in cards:
            def find(prefix: str, contains: str | None = None) -> dict | None:
                return next((s for s in sources if s["id"].startswith(prefix) and (contains is None or contains in (s.get("name") or ""))), None)
            source = find(card["source_id_prefix"], card.get("name_contains"))
            fi_source = find(card["fi_source_id_prefix"]) if card.get("fi_source_id_prefix") else source
            if source is None or fi_source is None:
                continue
            publisher = (source.get("publisher") or "").split(",")[0].split(" (")[0].strip()
            built.append({
                "title": card["title"],
                "publisher": publisher,
                "url": {"en": source["source_url"], "fi": fi_source["source_url"]},
                "licence_class": source.get("licence_class"),
            })
        if built:
            out["more"][topic] = built
    return out


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    data = build(Path(sys.argv[1]), Path(sys.argv[2]))
    target = Path(sys.argv[3]) if len(sys.argv) > 3 else OUT
    target.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {target}: {sum(len(v) for v in data['facts'].values())} facts in {len(data['facts'])} lessons, "
          f"{sum(len(v) for v in data['more'].values())} link cards")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
