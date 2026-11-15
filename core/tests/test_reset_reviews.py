"""The demo reset script refuses to run without explicit customer ids (#68). No database is touched."""

from __future__ import annotations

import pytest

from core.scripts import reset_reviews


@pytest.mark.parametrize("argv", [[], ["--dry-run"], ["all"], ["CUST00860", "CUST0086"], ["%"]])
def test_refuses_without_explicit_customer_ids(argv, monkeypatch, capsys):
    monkeypatch.setattr(reset_reviews.db, "connect", lambda: pytest.fail("must not connect"))
    assert reset_reviews.main(argv) == 2
    assert "refusing to run" in capsys.readouterr().err


def test_accepts_the_four_personas_in_one_call():
    args = reset_reviews.parse(["CUST00860", "CUST00493", "CUST00387", "CUST00849"])
    assert args is not None and len(args.customer_ids) == 4
