"""Scratch only (issue #83): proves each CI job fails for the right reason. Never merged."""
import os  # unused on purpose: the lint job must fail


def test_ci_failproof_plain_failure():
    assert 1 == 2, "planted failure: the tests job must fail"


def test_redteam_ci_failproof():
    assert False, "planted failure: the red-team step must fail"
