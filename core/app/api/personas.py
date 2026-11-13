"""GET /api/personas (contracts/api.md section 5), from core/config/personas.yaml. No database."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, Query, Request

from . import texts
from .schemas import Language, PersonasResponse

PERSONAS_FILE = Path(__file__).resolve().parents[2] / "config" / "personas.yaml"

router = APIRouter()


@lru_cache(maxsize=1)
def load_personas() -> dict[str, Any]:
    """The YAML as a dict. Read once per process."""
    return yaml.safe_load(PERSONAS_FILE.read_text(encoding="utf-8"))


def persona_by_id(customer_id: str) -> dict[str, Any] | None:
    return next((p for p in load_personas()["personas"] if p["customer_id"] == customer_id), None)


def build(language: str, as_of) -> PersonasResponse:
    """Only the contract's fields: the YAML's team notes (lead, age, why, ...) never leave the service."""
    personas = sorted(load_personas()["personas"], key=lambda p: not p.get("lead", False))  # lead first
    out = []
    for p in personas:
        profile_label = p["profile"]["label"]
        if language == "fi":
            profile_label = texts.PROFILE_LABELS_FI.get(p["profile"]["key"], profile_label)
        out.append({
            "customer_id": p["customer_id"],
            "display_name": p["display_name"],
            "age_band": p["age_band"],
            "postal_area": {"code": p["postal_area"]["code"], "label": p["postal_area"]["label"]},
            "profile": {"key": p["profile"]["key"], "label": profile_label},
            "tagline": p["tagline"],  # the YAML has English taglines only
            "default_language": p["default_language"],
        })
    return PersonasResponse(as_of=as_of, language=language, personas=out)


@router.get("/api/personas", response_model=PersonasResponse)
def get_personas(request: Request, lang: Language = Query("en")) -> PersonasResponse:
    return build(lang, request.app.state.settings.demo_today)
