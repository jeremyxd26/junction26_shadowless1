"""The API response models mirror contracts/api.md.

Every JSON example in the contract is extracted from the file (never copied by hand), validated
against the response models, and walked field by field: a field the example has but the model does
not, or a field the model has but the example does not, fails the test. Enum values of the models
are compared with the lists written in the contract text.
"""

from __future__ import annotations

import copy
import json
import re
import typing
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from core.app.api import errors, schemas, texts
from core.tools import config as tools_config

CONTRACT = Path(__file__).resolve().parents[2] / "contracts" / "api.md"
EXAMPLE = re.compile(r"<!-- example: ([\w.]+) -->\s*```json\n(.*?)\n```", re.S)

MODELS: dict[str, type[BaseModel]] = {
    "shared.number": schemas.Number,
    "error.response": schemas.ErrorResponse,
    "personas.response": schemas.PersonasResponse,
    "overview.response": schemas.OverviewResponse,
    "overview.response_pending": schemas.OverviewResponse,
    "overview.response_no_hero": schemas.OverviewResponse,   # contract 0.2.2: hero null
    "card.review": schemas.ReviewCard,
    "evidence.response": schemas.EvidenceResponse,
    "evidence.response_composite": schemas.EvidenceResponse,
    "label.request": schemas.LabelRequest,
    "label.request_wanted": schemas.LabelRequest,
    "label.request_undo": schemas.LabelRequest,
    "label.response": schemas.LabelResponse,
    "label.response_wanted": schemas.LabelResponse,
    "label.response_undo": schemas.LabelResponse,
    "label.error": schemas.ErrorResponse,
    "whatif.request": schemas.WhatIfRequest,
    "whatif.request_basket": schemas.WhatIfRequest,
    "whatif.response": schemas.WhatIfResponse,
    "card.safe_to_save": schemas.SafeToSaveCard,            # #165
    "card.safe_to_save_aleksi": schemas.SafeToSaveCard,
    "card.safe_to_save_zero": schemas.SafeToSaveCard,
    "card.safe_to_save_everyday": schemas.SafeToSaveCard,
    "evidence.response_metric": schemas.EvidenceResponse,   # contract 0.2.2
    "evidence.response_peer": schemas.EvidenceResponse,     # contract 0.2.2
    "whatif.error": schemas.ErrorResponse,                  # contract 0.2.2
    "bill.request": schemas.BillExplainRequest,             # contract 0.3.0 (#243); endpoint with #242
    "bill.request_fields": schemas.BillExplainRequest,
    "bill.response": schemas.BillExplainResponse,
    "bill.response_unknown": schemas.BillExplainResponse,
    # bill.error joins with #242, which adds invalid_bill and its `reason` (PENDING_ERROR_CODES);
    # bill.read_response with #250 (section 11.4, not implemented yet)
}

# Fields the models have ahead of the contract (agreed additions, the text follows in the next contract
# version), as paths with [] for every list item, each with the value it would have in the example.
# The check fills them into a copy of the example; test_additions_are_still_missing fails once the
# contract carries one, so it is removed here. Empty since contract 0.2.2 (rows[].display is in it).
ADDITIONS: dict[str, dict[str, typing.Callable[[dict], typing.Any]]] = {}

# Contract fields the models do not implement yet, by example name, with the issue that adds them.
# Whoever implements one removes it here: test_pending_entries_are_still_missing fails while a field
# is both implemented and listed. Empty since #165 implemented `safe_to_save` (both overview examples).
PENDING: dict[str, set[str]] = {}
# Error codes the models do not have yet: invalid_bill comes with the bill endpoint (#242),
# model_unavailable with the bill reading (#250).
PENDING_ERROR_CODES: set[str] = {"invalid_bill", "model_unavailable"}
# Error codes the service has ahead of the contract. Empty since contract 0.2.2 (not_found is in it).
ERROR_CODE_ADDITIONS: set[str] = set()


def contract_text() -> str:
    return CONTRACT.read_text(encoding="utf-8")


def examples() -> dict[str, typing.Any]:
    return {name: json.loads(body) for name, body in EXAMPLE.findall(contract_text())}


def mismatches(inst: typing.Any, raw: typing.Any, path: str = "$") -> list[str]:
    """Fields present on one side only, walking the validated model and the raw example together."""
    out: list[str] = []
    if isinstance(inst, BaseModel):
        fields = set(type(inst).model_fields)
        keys = set(raw)
        out += [f"{path}.{k}: in the example, not in {type(inst).__name__}" for k in sorted(keys - fields)]
        out += [f"{path}.{k}: in {type(inst).__name__}, not in the example" for k in sorted(fields - keys)]
        for name in sorted(fields & keys):
            out += mismatches(getattr(inst, name), raw[name], f"{path}.{name}")
    elif isinstance(inst, list) and isinstance(raw, list):
        for i, (a, b) in enumerate(zip(inst, raw)):
            out += mismatches(a, b, f"{path}[{i}]")
    elif isinstance(inst, dict) and isinstance(raw, dict):
        for k in raw:
            if k in inst:
                out += mismatches(inst[k], raw[k], f"{path}.{k}")
    return out


def _split(path: str) -> tuple[list[str], str]:
    """'$.rows[].display' -> (['rows', '[]'], 'display')."""
    parts = re.findall(r"\[\]|[^.\[\]$]+", path)
    return parts[:-1], parts[-1]


def _parents(obj: typing.Any, parts: list[str]) -> typing.Iterator[dict]:
    if not parts:
        yield obj
        return
    head, rest = parts[0], parts[1:]
    for child in (obj if head == "[]" else [obj[head]]):
        yield from _parents(child, rest)


def with_additions(name: str, raw: typing.Any) -> typing.Any:
    out = copy.deepcopy(raw)
    for path, value_of in ADDITIONS.get(name, {}).items():
        parents, key = _split(path)
        for parent in _parents(out, parents):
            parent[key] = value_of(parent)
    return out


def check(name: str, raw: typing.Any) -> list[str]:
    raw = with_additions(name, raw)
    inst = MODELS[name].model_validate(raw)
    pending = PENDING.get(name, set())
    return [m for m in mismatches(inst, raw) if m.split(":")[0] not in pending]


def test_contract_has_the_examples_we_implement():
    assert set(MODELS) <= set(examples())


@pytest.mark.parametrize("name", sorted(MODELS))
def test_example_matches_the_model_field_by_field(name):
    assert check(name, examples()[name]) == []


def test_pending_entries_are_still_missing():
    """A PENDING path must be in the contract example and still missing from the model."""
    for name, paths in PENDING.items():
        raw = examples()[name]
        found = {m.split(":")[0] for m in mismatches(MODELS[name].model_validate(raw), raw)
                 if "in the example, not in" in m}
        assert paths <= found, f"{name}: {sorted(paths - found)} implemented or gone; remove from PENDING"
    assert not PENDING_ERROR_CODES & literal_values(schemas.ErrorBody, "code"), "remove from PENDING_ERROR_CODES"


def test_additions_are_still_missing_from_the_contract():
    """An ADDITIONS path must have parents in the example (so it is exercised) and not be there yet."""
    for name, paths in ADDITIONS.items():
        raw = examples()[name]
        for path in paths:
            parents, key = _split(path)
            found = list(_parents(raw, parents))
            assert found, f"{name}: {path} has nothing to attach to in the example"
            assert all(key not in p for p in found), f"{name}: the contract has {path} now; remove it from ADDITIONS"
        # without the addition the model refuses the example: the field is required, not optional
        with pytest.raises(ValidationError):
            MODELS[name].model_validate(raw)


def test_the_check_fails_on_an_unknown_field_and_on_a_missing_one():
    good = examples()["overview.response"]
    extra = copy.deepcopy(good)
    extra["cards"][1]["items"][0]["surprise"] = 1           # a field the model would silently drop
    assert any("surprise" in m for m in check("overview.response", extra))
    missing = copy.deepcopy(good)
    del missing["cards"][0]["items"][0]["flags"]            # a field the model requires
    with pytest.raises(ValidationError):
        check("overview.response", missing)
    # A field with a default would validate when it is missing; the walk still reports it.
    number = schemas.Number.model_validate(good["cards"][0]["total"])
    assert mismatches(number, {k: v for k, v in good["cards"][0]["total"].items() if k != "display"}) == [
        "$.display: in Number, not in the example"]


def test_unknown_enum_values_are_rejected():
    bad = copy.deepcopy(examples()["overview.response"])
    bad["cards"][1]["items"][0]["status"] = "paid_twice"
    with pytest.raises(ValidationError):
        check("overview.response", bad)


# ---- enum values against the lists written in the contract text ------------------------------------

def literal_values(model: type[BaseModel], field: str) -> set[str]:
    def flatten(tp) -> set[str]:
        if typing.get_origin(tp) is typing.Literal:
            return set(typing.get_args(tp))
        return set().union(*(flatten(a) for a in typing.get_args(tp))) if typing.get_args(tp) else set()

    return flatten(model.model_fields[field].annotation) - {None}


def backticked(line_pattern: str) -> set[str]:
    line = next(l for l in contract_text().splitlines() if re.search(line_pattern, l))
    return set(re.findall(r"`([^`]+)`", line))


def test_enums_match_the_contract_text():
    error_codes = set(re.findall(r"^\| \d{3} \| `([a-z_]+)` \|", contract_text(), re.M))
    assert PENDING_ERROR_CODES <= error_codes
    assert not ERROR_CODE_ADDITIONS & error_codes, "the contract has it now: remove it from ERROR_CODE_ADDITIONS"
    assert literal_values(schemas.ErrorBody, "code") == (error_codes - PENDING_ERROR_CODES) | ERROR_CODE_ADDITIONS
    assert set(errors.STATUS) == literal_values(schemas.ErrorBody, "code") == set(texts.ERRORS)
    assert literal_values(schemas.Persona, "age_band") == backticked(r"^\| Age bands \|") - {"metrics.md"}
    units = backticked(r"^\| `unit` \| enum \|") - {"unit"}
    assert typing.get_args(schemas.UnitName) == tuple(sorted(units, key=list(typing.get_args(schemas.UnitName)).index))
    profile_line = backticked(r"`profile\.key` is")
    assert literal_values(schemas.ProfileRef, "key") <= profile_line
    bills_line = backticked(r"^\| `bills` \|")
    assert literal_values(schemas.BillItem, "status") <= bills_line
    kinds = re.search(r"`kind` is one of (.*?)\.", contract_text()).group(1)
    assert literal_values(schemas.Insight, "kind") == set(re.findall(r"`([^`]+)`", kinds))
    whatif = contract_text().split("## 8. `POST /api/whatif`")[1].split("## 9.")[0]
    assert literal_values(schemas.WhatIfResponse, "status") == set(re.findall(r"^- `([a-z_]+)`:", whatif, re.M))
    request_fields = {"customer_id", "scenario", "language"}
    kinds_table = set(re.findall(r"^\| `([a-z_]+)` \| ", whatif, re.M)) - request_fields
    assert set(typing.get_args(schemas.SelectionKind)) == kinds_table


# ---- every method id a tool can emit has a name and a unit (texts.METHODS) ---------------------------
# The evidence view names each number's method and formats its value with the method's unit, so a tool
# that emits a method id texts.METHODS does not know would show a guessed name and unit. The ids are
# found in the tools' source: quoted ids such as "spending.total@1", and `f"{METRIC}.{column}@1"`
# built from a config table iterated as `for key, column[, unit] in config.TABLE`.

TOOLS = Path(__file__).resolve().parents[1] / "tools"
QUOTED_METHOD_ID = re.compile(r"[\"']([a-z_]+\.[a-z0-9_]+@\d+)[\"']")
TABLE_LOOP = re.compile(r"for\s+\w+,\s*column(?:,\s*\w+)?\s+in\s+config\.([A-Z_]+)")
FSTRING_COLUMN = re.compile(r"f[\"']\{METRIC\}\.([a-z0-9_]+)@(\d+)[\"']")


def emitted_method_ids() -> dict[str, str | None]:
    """Method id -> the unit its config table gives (None when the table names none)."""
    ids: dict[str, str | None] = {}
    for path in sorted(TOOLS.glob("*.py")):
        src = path.read_text(encoding="utf-8")
        for method in QUOTED_METHOD_ID.findall(src):
            ids.setdefault(method, None)
        metric = re.search(r"^METRIC = [\"']([a-z_]+)[\"']", src, re.M)
        if metric is None or "{METRIC}." not in src:
            continue
        tables, columns = TABLE_LOOP.findall(src), FSTRING_COLUMN.findall(src)
        assert tables or columns, f"{path.name} builds method ids in a way this scan cannot see; extend it"
        for table in tables:
            for row in getattr(tools_config, table):
                ids[f"{metric.group(1)}.{row[1]}@1"] = row[2] if len(row) > 2 else None
        for column, version in columns:
            ids.setdefault(f"{metric.group(1)}.{column}@{version}", None)
    return ids


def test_every_method_id_a_tool_emits_has_a_name_and_a_unit():
    ids = emitted_method_ids()
    # the scan sees each kind of source: config.METHODS, a metric table, and an f-string column
    assert {"spending.total@1", "what_if.saving_month_eur@1", "safe_to_spend.safe_to_spend_7d_eur@1"} <= set(ids)
    missing = sorted(set(ids) - set(texts.METHODS))
    assert missing == [], f"add these method ids to core/app/api/texts.py METHODS: {missing}"
    wrong_unit = {m: (u, texts.METHODS[m].unit.value) for m, u in ids.items() if u and texts.METHODS[m].unit.value != u}
    assert wrong_unit == {}, wrong_unit
