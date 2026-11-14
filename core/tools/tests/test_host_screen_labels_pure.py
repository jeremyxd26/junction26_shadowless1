"""#417: the button into the bank's screen names the screen only, and no template joins an amount to it.

- One label per host target: core/tools/config.py is read as source (a `"host_<target>"` dict key or a
  `HOST_<TARGET>` constant), because a duplicate key in a dict literal is silently dropped at runtime.
- No label has a digit, a currency sign or an action verb ("start saving", "put", "move", "invest" and
  their Finnish forms), in English and Finnish.
- The template answers of the two tools that carry an `open_host_screen` action (safe to save, the Bonus
  estimate) never name an amount and the bank's screen or product in one sentence, in English and Finnish:
  at runtime that check rejects model drafts only (core/agent/validator.py), so templates are held to it here.
No database."""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest
from test_bonus_pure import run as bonus_run
from test_tools_safe_to_save_pure import AS_OF, row
from test_tools_safe_to_save_pure import run as save_run

from core.agent import template
from core.agent.validator import allowed_from, amount_with_bank_product
from core.tools import config
from core.tools.models import HOST_SCREEN_TARGETS

CONFIG = Path(config.__file__)
CURRENCY = re.compile(r"[€$£]|\beur(?:o|os)?\b|\beuroa?\b", re.I)
ACTION_VERBS = re.compile(
    r"\b(?:start\w*|put\w*|mov(?:e|es|ing)\b|invest\w*|transfer\w*|deposit\w*|set\s+aside)"
    r"|\b(?:aloit\w*|laita\w*|laitta\w*|siirr\w*|siirtä\w*|sijoit\w*|talleta\w*|talletu\w*)", re.I)


def host_label_entries() -> list[tuple[str, int, tuple[str, str]]]:
    """Every host-screen label in config.py with its line and its (en, fi) value, as (target, line, labels):
    a `"host_<target>"` key of a dict literal, or a module constant `HOST_<TARGET>` (en, fi)."""
    out = []
    tree = ast.parse(CONFIG.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and isinstance(key.value, str) and key.value.startswith("host_"):
                    out.append((key.value.removeprefix("host_"), key.lineno, ast.literal_eval(value)))
    for node in tree.body:
        target = node.targets[0] if isinstance(node, ast.Assign) and len(node.targets) == 1 else             node.target if isinstance(node, ast.AnnAssign) else None
        if isinstance(target, ast.Name) and target.id.startswith("HOST_") and node.value is not None:
            value = ast.literal_eval(node.value)
            if isinstance(value, tuple) and len(value) == 2 and all(isinstance(v, str) for v in value):
                out.append((target.id.removeprefix("HOST_").lower(), node.lineno, value))
    return out


def test_one_label_per_host_target_under_one_key():
    entries = host_label_entries()
    targets = [t for t, _, _ in entries]
    duplicates = sorted({t for t in targets if targets.count(t) > 1})
    assert not duplicates, f"a host target has more than one label in config.py: {duplicates}"
    assert sorted(targets) == sorted(HOST_SCREEN_TARGETS)


def test_the_check_sees_a_duplicate_key_that_python_would_drop(tmp_path, monkeypatch):
    fake = tmp_path / "config.py"
    fake.write_text("\n".join([
        "T = {",
        '    "host_monthly_saving": ("See monthly saving in S-mobiili", "Katso"),',
        '    "host_monthly_saving": ("Start saving in S-mobiili", "Aloita säästäminen S-mobiilissa"),',
        "}", ""]), encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "CONFIG", fake)
    entries = host_label_entries()
    assert [t for t, _, _ in entries] == ["monthly_saving", "monthly_saving"]
    assert ACTION_VERBS.search(entries[1][2][0]) and ACTION_VERBS.search(entries[1][2][1])


@pytest.mark.parametrize("target, line, labels", host_label_entries())
def test_a_host_label_names_the_screen_only(target, line, labels):
    en, fi = labels
    for text in (en, fi):
        assert not re.search(r"[0-9]", text), (target, line, text)
        assert not CURRENCY.search(text), (target, line, text)
        assert not ACTION_VERBS.search(text), (target, line, text)
        assert "S-mobiili" in text or "S-Pankki" in text, (target, line, text)   # the host's own screen


@pytest.mark.parametrize("language", ["en", "fi"])
def test_the_cards_use_these_labels_and_nothing_else(language):
    labels = {t: v for t, _, v in host_label_entries()}
    save, _ = save_run(row(), language)
    bonus, _ = bonus_run(language=language)
    for result, target in ((save, "monthly_saving"), (bonus, "bonus_to_fund")):
        host = [a for a in result.card.actions if a.type == "open_host_screen"]
        assert [(a.target, a.label) for a in host] == [
            (target, labels[target][0 if language == "en" else 1])]


SAVE_ROWS = {
    "lead": row(),                                                                   # 184.61 a month, goal 360
    "no_goal": row(savings_goal_eur="0.00"),
    "above_goal": row(savings_goal_eur="150.00"),
    "below_goal": row(savings_goal_eur="400.00"),
    "zero_month": row(everyday_month_eur="900.00", safe_to_save_monthly_eur="0.00",
                      save_reason="largest_everyday_category", save_reason_category="Restaurants",
                      save_reason_month_eur="186.93"),
}


def template_text(result, numbers, language: str, question: str) -> str:
    allowed = allowed_from(numbers.values(), [result.model_view], AS_OF)
    draft = template.template_draft([result.model_view], [], language, allowed, question)
    return draft["text"] if isinstance(draft, dict) else draft


@pytest.mark.parametrize("language, question", [("en", "How could I save more?"),
                                                ("fi", "Miten voisin säästää enemmän?")])
@pytest.mark.parametrize("name", sorted(SAVE_ROWS))
def test_the_safe_to_save_template_keeps_the_amount_apart_from_the_bank(name, language, question):
    result, ctx = save_run(SAVE_ROWS[name], language)
    numbers = ctx.numbers.all()
    text = template_text(result, numbers, language, question)
    assert re.search(r"\{\{n[0-9]+\}\}", text), text                 # the template does cite an amount
    assert amount_with_bank_product(text, numbers) is None, text


@pytest.mark.parametrize("language, question", [("en", "What would S-Bonus give me?"),
                                                ("fi", "Paljonko saisin S-Bonusta?")])
def test_the_bonus_template_keeps_the_amount_apart_from_the_bank(language, question):
    result, _ = bonus_run(language=language)
    assert result.data.status == "estimate"                          # the card carries the fund action
    numbers = {}
    for n in (result.data.total_month, result.data.bonus_month, result.data.bonus_percent, result.data.total_year,
              result.data.level_base, result.data.grocery_month):
        numbers[n.id] = n
    text = template_text(result, numbers, language, question)
    assert amount_with_bank_product(text, numbers) is None, text
