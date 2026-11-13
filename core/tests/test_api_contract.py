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

from core.app.api import schemas

CONTRACT = Path(__file__).resolve().parents[2] / "contracts" / "api.md"
EXAMPLE = re.compile(r"<!-- example: ([\w.]+) -->\s*```json\n(.*?)\n```", re.S)

MODELS: dict[str, type[BaseModel]] = {
    "shared.number": schemas.Number,
    "error.response": schemas.ErrorResponse,
    "personas.response": schemas.PersonasResponse,
    "overview.response": schemas.OverviewResponse,
    "evidence.response": schemas.EvidenceResponse,
    "evidence.response_composite": schemas.EvidenceResponse,
}

# Contract fields the models do not implement yet, by example name, with the issue that adds them.
# Contract 0.2.0 added these to the overview. Whoever implements one removes it here:
# test_pending_entries_are_still_missing fails while a field is both implemented and listed.
PENDING: dict[str, set[str]] = {
    "overview.response": {
        "$.reviews",       # at most one pending review card (#68)
        "$.safe_to_save",  # the safe_to_save card (#53/#55)
    },
}
# Error codes of the label endpoint, POST /api/baskets/label (contract 0.2.0, section 10, #68).
PENDING_ERROR_CODES = {"tx_ref_not_found", "basket_not_allowed"}


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


def check(name: str, raw: typing.Any) -> list[str]:
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
    assert literal_values(schemas.ErrorBody, "code") == error_codes - PENDING_ERROR_CODES
    assert literal_values(schemas.Persona, "age_band") == backticked(r"^\| Age bands \|") - {"metrics.md"}
    units = backticked(r"^\| `unit` \| enum \|") - {"unit"}
    assert typing.get_args(schemas.UnitName) == tuple(sorted(units, key=list(typing.get_args(schemas.UnitName)).index))
    profile_line = backticked(r"`profile\.key` is")
    assert literal_values(schemas.ProfileRef, "key") <= profile_line
    bills_line = backticked(r"^\| `bills` \|")
    assert literal_values(schemas.BillItem, "status") <= bills_line
    kinds = re.search(r"`kind` is one of (.*?)\.", contract_text()).group(1)
    assert literal_values(schemas.Insight, "kind") == set(re.findall(r"`([^`]+)`", kinds))
