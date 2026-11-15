"""GET /api/evidence/{ref} (contracts/api.md section 9), from the evidence store of core/tools.

The stored spec holds the method, the selection (or the input refs), the value and optional params.
The Number shown at the top is rebuilt from it:
- unit and method name from texts.METHODS (a method this version does not know still opens);
- period from params.period when the number describes another span than its data (bills due
  before payday), else the selection's period, else the first part's period;
- label from the selection (category, basket, MCC group, recurring series) or the method name.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Callable

from fastapi import APIRouter, Path, Query, Request

from core.tools import config, evidence, periods, spending
from core.tools.formatting import display
from core.tools.models import Unit
from core.tools.numbers import json_value
from core.tools.selection import NONE_KEY, Selection

from . import texts
from .deps import CUSTOMER_ID_PATTERN, EVIDENCE_REF_PATTERN, customer_connection
from .errors import ApiError
from .schemas import EvidenceResponse, Language

router = APIRouter()

Loader = Callable[[str], dict[str, Any]]


def _period_of(spec: dict[str, Any], load: Loader) -> tuple[date, date]:
    period = (spec.get("params") or {}).get("period")
    if period:
        return date.fromisoformat(period["start"]), date.fromisoformat(period["end"])
    if spec["kind"] == "transactions":
        sel = spec["selection"]["period"]
        return date.fromisoformat(sel["start"]), date.fromisoformat(sel["end"])
    if spec.get("parts"):
        return _period_of(load(spec["parts"][0]["ref"]), load)
    as_of = date.fromisoformat(spec["as_of"])
    return as_of, as_of


def _label_of(spec: dict[str, Any], language: str, merchant_label: str | None = None) -> str:
    info = texts.method_info(spec["method"])
    params = spec.get("params") or {}
    if spec["method"] == config.METHODS["national_month"] and params.get("category") in config.NATIONAL_WHAT:
        # #569: the table's age band and what the survey's category holds ("transport without buying a vehicle")
        return texts.pick(texts.NATIONAL_LABEL, language).format(
            band=str(params.get("age_group", "")).replace("-", "\u2013"),
            what=config.label(config.NATIONAL_WHAT[params["category"]], language))
    if spec["method"] in (config.METHODS["age_band_median"], config.METHODS["age_band_cohort"]) and params.get("band"):
        # #883: the band ("35–44") and, for a median, the measure
        band = str(params["band"]).replace("-", "–")
        if spec["method"] == config.METHODS["age_band_cohort"]:
            return texts.pick(texts.AGE_BAND_COHORT_LABEL, language).format(band=band)
        measure = params.get("measure")
        what = config.label(config.PEER_TEXT["ordinary_spending"], language) if measure == "ordinary_spending" \
            else config.label(config.BASKET_LABELS[measure], language) if measure in config.BASKET_LABELS \
            else texts.pick(info.name, language)
        return texts.pick(texts.AGE_BAND_LABEL, language).format(band=band, what=what.lower())
    if spec["kind"] != "transactions":
        return texts.pick(info.name, language)
    sel = spec["selection"]
    group = sel.get("group") or {}
    dims = sum(bool(sel.get(k)) for k in ("categories", "mcc_groups", "baskets", "merchant_id"))
    if spec["method"] == config.METHODS["total"] and not group and dims > 1:
        # A filter across dimensions is named as the tool names it, never by its first part alone (#501); the
        # merchant by its alias when the resolver could name it, else neutrally.
        if sel.get("merchant_id") and not merchant_label:
            named = spending.filter_label(sel["categories"], sel["mcc_groups"], sel["baskets"], None, language)
            return named + config.label(config.TEXT["filter_at_unnamed"], language)
        return spending.filter_label(sel["categories"], sel["mcc_groups"], sel["baskets"], merchant_label, language)
    if spec["method"] == config.METHODS["total"] and not group and dims == 0 and sel.get("direction") == "in":
        return config.label(config.TEXT["income"], language)   # an unfiltered income total is income (#501)
    if sel.get("series_key") in config.SERIES_LABELS:
        return config.label(config.SERIES_LABELS[sel["series_key"]], language)
    # A breakdown's own items, named as the tool names them (Number label = card title = evidence title, #567):
    # "Other" is the purchases with no merchant group, "Everything else" the rest after the top items; neither is
    # the customer's total spending.
    if group.get("by") == "mcc_group" and group.get("key") == NONE_KEY:
        return config.label(config.TEXT["no_mcc_group"], language)
    if group.get("not_in") and not group.get("key"):
        return config.label(config.TEXT["everything_else"], language)
    if group.get("by") == "category" and group.get("key") in config.CATEGORY_LABELS:
        return config.label(config.CATEGORY_LABELS[group["key"]], language)
    if group.get("by") == "basket" and group.get("key") in config.BASKET_LABELS:
        return config.label(config.BASKET_LABELS[group["key"]], language)
    if group.get("by") == "mcc_group" and group.get("key") in config.MCC_GROUP_LABELS:
        return spending.group_label(group["key"], language)   # as the tool's item (review of #528)
    if len(sel["categories"]) == 1 and sel["categories"][0] in config.CATEGORY_LABELS:
        return config.label(config.CATEGORY_LABELS[sel["categories"][0]], language)
    if len(sel["mcc_groups"]) == 1 and sel["mcc_groups"][0] in config.MCC_GROUP_LABELS:
        # "Restaurants (card purchases)", never the category's own label (review of #528)
        return spending.group_label(sel["mcc_groups"][0], language)
    if len(sel["baskets"]) == 1 and sel["baskets"][0] in config.BASKET_LABELS:
        return config.label(config.BASKET_LABELS[sel["baskets"][0]], language)
    if spec["method"] == config.METHODS["total"]:
        # A filtered sum is never "Total spending" (#399): every part of the filter is named, as the tool names
        # it; a merchant the view cannot name (its alias needs the history) gets a neutral label.
        named = spending.filter_label(sel["categories"], sel["mcc_groups"], sel["baskets"], None, language)
        if named:
            return named
        if sel.get("merchant_id"):
            return config.label(config.TEXT["spending_merchant"], language)
    return texts.pick(info.name, language)


def number_from_spec(ref: str, spec: dict[str, Any], language: str, load: Loader,
                     merchant_label: str | None = None) -> dict[str, Any]:
    info = texts.method_info(spec["method"])
    value = Decimal(spec["value"])
    start, end = _period_of(spec, load)
    return {
        "value": json_value(value, info.unit),
        "unit": info.unit.value,
        "period": {"start": start, "end": end, "label": periods.period_label(start, end, language)},
        "method": spec["method"],
        "evidence_ref": ref,
        "label": _label_of(spec, language, merchant_label),
        "display": display(value, info.unit, language, spec["method"]),
    }


METRIC_SECTIONS = {  # core/metrics/<file> -> section of metrics.md that defines it
    "01_recurring.sql": "#2-recurring-bills", "02_baskets.sql": "#1-three-baskets",
    "03_safe_to_spend.sql": "#3-safe-to-spend", "04_what_if.sql": "#4-what-if-savings",
    "05_spender_profile.sql": "#5-spender-profile", "06_peer_benchmark.sql": "#6-peer-benchmark",
    "07_store_price_index.sql": "#7-grocery-store-price-index", "09_age_band_peer.sql": "#6-peer-benchmark",
}


def _peer_parts(parts: list[dict[str, Any]], period: dict[str, Any], language: str) -> list[dict[str, Any]]:
    """Group statistics of a peer_aggregate (#69), parts `{role, method, value}` with no refs: each one a
    Number without an evidence ref; the group (`peer_level`) is named in the group size's label."""
    level = next((p["value"] for p in parts if p["role"] == "peer_level"), None)
    out = []
    for p in parts:
        if not p.get("method"):
            continue
        info = texts.method_info(p["method"])
        value = Decimal(p["value"])
        label = texts.pick(info.name, language)
        if p["role"] == "peer_n" and level in texts.PEER_LEVELS:
            label = f"{label} ({texts.pick(texts.PEER_LEVELS[level], language)})"
        out.append({"role": p["role"], "number": {
            "value": json_value(value, info.unit), "unit": info.unit.value, "period": period,
            "method": p["method"], "evidence_ref": None, "label": label,
            "display": display(value, info.unit, language, p["method"])}})
    return out


def _rows(rows: list[dict[str, Any]], language: str) -> list[dict[str, Any]]:
    """Each row's amount also as a localised display, formatted like a Number's (sign kept)."""
    return [{**r, "display": display(Decimal(r["amount"]), Unit.EUR, language)} for r in rows]


def build(conn, res: evidence.Resolution, customer_id: str, language: str) -> EvidenceResponse:
    def load(ref: str) -> dict[str, Any]:
        return evidence.load(conn, ref)[1]

    spec = res.spec if res.spec is not None else load(res.ref)  # a resolver may not hand back its spec

    number = number_from_spec(res.ref, spec, language, load, merchant_label=res.merchant_label)
    info = texts.method_info(res.method)
    body: dict[str, Any] = {
        "evidence_ref": res.ref,
        "kind": res.kind,
        "language": language,
        "title": f"{number['label']}, {number['period']['label']}",
        "number": number,
        "method": {"id": res.method, "name": texts.pick(info.name, language),
                   "summary": texts.pick(info.summary, language), "doc": info.doc},
        "query": None, "rows": [], "row_count": None, "reconciles": None, "parts": [], "next_cursor": None,
    }
    if res.kind == "transactions":
        sel = spec["selection"]
        start, end = date.fromisoformat(sel["period"]["start"]), date.fromisoformat(sel["period"]["end"])
        period = {"start": start, "end": end, "label": periods.period_label(start, end, language)}
        body["query"] = {"categories": sel["categories"], "baskets": sel["baskets"], "mcc_groups": sel["mcc_groups"],
                         "merchant_id": sel["merchant_id"], "period": period}
        body["rows"] = _rows(res.rows, language)
        body["reconciles"] = res.reconciles
        body["next_cursor"] = res.next_cursor
        # row_count is a Number with its own ref (contract section 9): a count over the same selection,
        # under the same label set as the number it counts (#68, R2), so it reconciles too.
        rc_value = Decimal(res.row_count or 0)
        rc_spec = evidence.transactions_spec(customer_id, date.fromisoformat(spec["as_of"]),
                                             config.METHODS["row_count"], Selection.from_spec(sel), rc_value,
                                             label_set=spec.get("labels"))
        rc_ref = evidence.make_ref(rc_spec)
        evidence.write(conn, {rc_ref: rc_spec})
        body["row_count"] = {
            "value": int(rc_value), "unit": "count", "period": period, "method": config.METHODS["row_count"],
            "evidence_ref": rc_ref, "label": texts.pick(texts.ROW_COUNT_LABEL, language),
            "display": display(rc_value, Unit.COUNT, language),
        }
        body["privacy_note"] = texts.pick(texts.PRIVACY_TRANSACTIONS, language)
    elif res.kind == "composite":
        body["parts"] = [{"role": p["role"],
                          "number": number_from_spec(p["ref"], p.get("spec") or load(p["ref"]), language, load)}
                         for p in res.parts]
        body["privacy_note"] = texts.pick(texts.PRIVACY_COMPOSITE, language)
    elif res.kind == "peer_aggregate":
        # #69: statistics of the peer group only (median, quartiles, group size); no rows, no query.
        body["method"]["doc"] = texts.METRICS_DOC + METRIC_SECTIONS["06_peer_benchmark.sql"]
        body["parts"] = _peer_parts(res.parts, number["period"], language)
        body["reconciles"] = res.reconciles
        body["privacy_note"] = texts.pick(texts.PRIVACY_PEER, language)
    else:
        # "metric" (#55): the number is re-run from its metric SQL file; reconciles says whether the re-run
        # gives the same value. Rows are optional and carry no promise to add up (not shown yet).
        source = spec.get("source") or {}
        if source.get("file"):
            body["method"]["doc"] = texts.METRICS_DOC + METRIC_SECTIONS.get(source["file"], "")
            if not body["method"]["summary"]:
                body["method"]["summary"] = f"core/metrics/{source['file']}: {source.get('column', '')}"
        body["reconciles"] = res.reconciles
        body["rows"] = _rows(res.rows, language)
        body["privacy_note"] = texts.pick(texts.PRIVACY_COMPOSITE, language)
        if res.method == config.METHODS["age_band_median"]:
            # #883: the band's size beside its median (group statistics only, never a row of another customer)
            body["parts"] = _age_band_parts(spec, number["period"], language)
            body["privacy_note"] = texts.pick(texts.PRIVACY_PEER, language)
    return EvidenceResponse.model_validate(body)


def _age_band_parts(spec: dict[str, Any], period: dict[str, Any], language: str) -> list[dict[str, Any]]:
    """The band's size as a part with no ref, from the spec's params (as the peer group's size, #69); for the median
    of ordinary spending also the band's three basket medians, each with its own evidence ref (#883)."""
    params = spec.get("params") or {}
    size = params.get("cohort_size")
    if size is None or not str(size).isdigit():
        return []
    method = config.METHODS["age_band_cohort"]
    value = Decimal(str(size))
    parts = [{"role": "cohort_size", "number": {
        "value": json_value(value, Unit.COUNT), "unit": Unit.COUNT.value, "period": period, "method": method,
        "evidence_ref": None, "label": texts.pick(texts.AGE_BAND_COHORT_PART, language),
        "display": display(value, Unit.COUNT, language, method)}}]
    median = config.METHODS["age_band_median"]
    for item in params.get("basket_medians") or []:
        measure, ref = item.get("measure"), item.get("ref")
        if measure not in config.BASKET_LABELS or not isinstance(ref, str) or not ref.startswith("ev_"):
            continue
        try:
            amount = Decimal(str(item.get("value")))
        except ArithmeticError:
            continue
        label = texts.pick(texts.AGE_BAND_BASKET_PART, language).format(
            what=config.label(config.BASKET_LABELS[measure], language))
        parts.append({"role": measure, "number": {
            "value": json_value(amount, Unit.EUR_PER_MONTH), "unit": Unit.EUR_PER_MONTH.value, "period": period,
            "method": median, "evidence_ref": ref, "label": label,
            "display": display(amount, Unit.EUR_PER_MONTH, language, median)}})
    return parts


@router.get("/api/evidence/{ref}", response_model=EvidenceResponse)
def get_evidence(
    request: Request,
    ref: str = Path(pattern=EVIDENCE_REF_PATTERN),
    customer_id: str = Query(pattern=CUSTOMER_ID_PATTERN),
    lang: Language = Query("en"),
    limit: int = Query(evidence.DEFAULT_LIMIT, ge=1, le=evidence.MAX_LIMIT),
    cursor: str | None = Query(None, pattern=r"^cur_[0-9]{1,6}$"),  # offsets up to 999999
) -> EvidenceResponse:
    with customer_connection(request, customer_id) as conn:   # allowlist first, no database (#101)
        try:
            res = evidence.resolve(conn, ref, customer_id, limit=limit, cursor=cursor, language=lang)
        except evidence.EvidenceNotFound:
            raise ApiError("evidence_not_found") from None
        except evidence.EvidenceForbidden:
            raise ApiError("evidence_forbidden") from None
        return build(conn, res, customer_id, lang)
