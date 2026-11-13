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

from core.tools import config, evidence, periods
from core.tools.formatting import display
from core.tools.models import Unit
from core.tools.selection import Selection

from . import texts
from .deps import CUSTOMER_ID_PATTERN, EVIDENCE_REF_PATTERN, connection, require_customer
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


def _label_of(spec: dict[str, Any], language: str) -> str:
    info = texts.method_info(spec["method"])
    if spec["kind"] != "transactions":
        return texts.pick(info.name, language)
    sel = spec["selection"]
    group = sel.get("group") or {}
    if sel.get("series_key") in config.SERIES_LABELS:
        return config.label(config.SERIES_LABELS[sel["series_key"]], language)
    if group.get("by") == "category" and group.get("key") in config.CATEGORY_LABELS:
        return config.label(config.CATEGORY_LABELS[group["key"]], language)
    if group.get("by") == "basket" and group.get("key") in config.BASKET_LABELS:
        return config.label(config.BASKET_LABELS[group["key"]], language)
    if group.get("by") == "mcc_group" and group.get("key") in config.MCC_GROUP_LABELS:
        return config.label(config.MCC_GROUP_LABELS[group["key"]], language)
    if len(sel["categories"]) == 1 and sel["categories"][0] in config.CATEGORY_LABELS:
        return config.label(config.CATEGORY_LABELS[sel["categories"][0]], language)
    if len(sel["mcc_groups"]) == 1 and sel["mcc_groups"][0] in config.MCC_GROUP_LABELS:
        return config.label(config.MCC_GROUP_LABELS[sel["mcc_groups"][0]], language)
    if len(sel["baskets"]) == 1 and sel["baskets"][0] in config.BASKET_LABELS:
        return config.label(config.BASKET_LABELS[sel["baskets"][0]], language)
    return texts.pick(info.name, language)


def number_from_spec(ref: str, spec: dict[str, Any], language: str, load: Loader) -> dict[str, Any]:
    info = texts.method_info(spec["method"])
    value = Decimal(spec["value"])
    start, end = _period_of(spec, load)
    return {
        "value": int(value) if info.unit is Unit.COUNT else float(value),
        "unit": info.unit.value,
        "period": {"start": start, "end": end, "label": periods.period_label(start, end, language)},
        "method": spec["method"],
        "evidence_ref": ref,
        "label": _label_of(spec, language),
        "display": display(value, info.unit, language),
    }


METRIC_SECTIONS = {  # core/metrics/<file> -> section of metrics.md that defines it
    "01_recurring.sql": "#2-recurring-bills", "02_baskets.sql": "#1-three-baskets",
    "03_safe_to_spend.sql": "#3-safe-to-spend", "04_what_if.sql": "#4-what-if-savings",
    "05_spender_profile.sql": "#5-spender-profile", "06_peer_benchmark.sql": "#6-peer-benchmark",
    "07_store_price_index.sql": "#7-grocery-store-price-index",
}


def build(conn, res: evidence.Resolution, customer_id: str, language: str) -> EvidenceResponse:
    def load(ref: str) -> dict[str, Any]:
        return evidence.load(conn, ref)[1]

    spec = res.spec if res.spec is not None else load(res.ref)  # a resolver may not hand back its spec

    number = number_from_spec(res.ref, spec, language, load)
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
        body["rows"] = res.rows
        body["reconciles"] = res.reconciles
        body["next_cursor"] = res.next_cursor
        # row_count is a Number with its own ref (contract section 9): a count over the same selection.
        rc_value = Decimal(res.row_count or 0)
        rc_spec = evidence.transactions_spec(customer_id, date.fromisoformat(spec["as_of"]),
                                             config.METHODS["row_count"], Selection.from_spec(sel), rc_value)
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
    else:
        # "metric" (#55): the number is re-run from its metric SQL file; reconciles says whether the re-run
        # gives the same value. Rows are optional and carry no promise to add up (not shown yet).
        source = spec.get("source") or {}
        if source.get("file"):
            body["method"]["doc"] = texts.METRICS_DOC + METRIC_SECTIONS.get(source["file"], "")
            if not body["method"]["summary"]:
                body["method"]["summary"] = f"core/metrics/{source['file']}: {source.get('column', '')}"
        body["reconciles"] = res.reconciles
        body["rows"] = res.rows
        body["privacy_note"] = texts.pick(texts.PRIVACY_COMPOSITE, language)
    return EvidenceResponse.model_validate(body)


@router.get("/api/evidence/{ref}", response_model=EvidenceResponse)
def get_evidence(
    request: Request,
    ref: str = Path(pattern=EVIDENCE_REF_PATTERN),
    customer_id: str = Query(pattern=CUSTOMER_ID_PATTERN),
    lang: Language = Query("en"),
    limit: int = Query(evidence.DEFAULT_LIMIT, ge=1, le=evidence.MAX_LIMIT),
    cursor: str | None = Query(None, pattern=r"^cur_[0-9]{1,6}$"),  # offsets up to 999999
) -> EvidenceResponse:
    with connection(request) as conn:
        require_customer(conn, customer_id)
        try:
            res = evidence.resolve(conn, ref, customer_id, limit=limit, cursor=cursor, language=lang)
        except evidence.EvidenceNotFound:
            raise ApiError("evidence_not_found") from None
        except evidence.EvidenceForbidden:
            raise ApiError("evidence_forbidden") from None
        return build(conn, res, customer_id, lang)
