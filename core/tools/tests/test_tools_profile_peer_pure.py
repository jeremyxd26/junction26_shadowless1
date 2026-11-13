"""Pure-logic tests for get_spender_profile and get_peer_benchmark (no database)."""

import json
from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from core.tools import config, evidence
from core.tools.models import PeerMetric
from core.tools.peer import (
    GetPeerBenchmarkArgs, group_label, peer_status,
)
from core.tools.profile import DECIDING, GetSpenderProfileArgs, keep_rate, profile_key

D = Decimal


# ---- spender profile: keep rate and label thresholds (05_spender_profile.sql) ----------------------

def test_keep_rate_needs_positive_net_income():
    assert keep_rate(D("0"), D("120.00")) is None             # no income: no keep rate
    assert keep_rate(D("-250.00"), D("120.00")) is None       # sweep larger than the salary
    assert keep_rate(D("0"), D("0")) is None
    assert keep_rate(D("2388.42"), D("2087.92")).quantize(D("0.1")) == D("12.6")   # metrics.md, CUST00001
    assert keep_rate(D("1628.40"), D("1702.17")).quantize(D("0.1")) == D("-4.5")   # CUST00002


@pytest.mark.parametrize("net_income", ["0", "-250.00"])
def test_zero_or_negative_net_income_gives_no_verdict(net_income):
    rate = keep_rate(D(net_income), D("900.00"))
    assert profile_key(rate, D("12.0"), D("45.0")) == "not_enough_income_data"


@pytest.mark.parametrize("keep, one_off, everyday, expected", [
    ("-4.5", "0.0", "25.3", "stretched"),          # CUST00002
    ("-0.1", "9.0", "40.0", "stretched"),          # stretched is checked first
    ("0.0", "0.0", "10.0", "steady"),              # 0 is not below 0
    ("15.4", "6.0", "19.9", "big_ticket"),         # CUST00860
    ("15.4", "5.0", "19.9", "big_ticket"),         # >= 5
    ("15.4", "4.9", "19.9", "steady"),
    ("22.6", "4.3", "30.1", "everyday_heavy"),     # CUST00349: checked before saver
    ("10.0", "0.0", "30.0", "everyday_heavy"),     # >= 30
    ("10.0", "0.0", "29.9", "steady"),
    ("24.8", "0.0", "19.7", "saver"),              # CUST00006
    ("20.0", "0.0", "19.7", "saver"),              # >= 20
    ("19.9", "0.0", "19.7", "steady"),
    ("12.6", None, None, "steady"),                # no spending: shares are NULL in 05
    ("25.0", None, None, "saver"),
])
def test_label_thresholds(keep, one_off, everyday, expected):
    value = lambda v: None if v is None else D(v)  # noqa: E731
    assert profile_key(D(keep), value(one_off), value(everyday)) == expected


def test_every_label_names_the_features_that_decided_it():
    feature_keys = {k for k, _, _ in config.PROFILE_FEATURES}
    assert set(DECIDING) == set(config.PROFILE_KEYS)
    for key, features in DECIDING.items():
        assert features and set(features) <= feature_keys, key


def test_labels_descriptions_and_notes_carry_no_digits_and_no_sensitive_terms():
    texts = [*config.PROFILE_LABELS.values(), *config.PROFILE_DESCRIPTIONS.values(),
             *config.TRAIT_LABELS.values(), *config.TRAIT_NOTES.values()]
    for en, fi in texts:
        for text in (en, fi):
            assert not any(ch.isdigit() for ch in text), text
            assert "health" not in text.lower() and "terve" not in text.lower(), text


def test_profile_takes_no_arguments():
    GetSpenderProfileArgs.model_validate({})
    with pytest.raises(ValidationError):
        GetSpenderProfileArgs.model_validate({"customer_id": "CUST00002"})


# ---- peer benchmark: arguments (R9, R4) -------------------------------------------------------------

def test_health_is_rejected_at_the_argument_level():
    with pytest.raises(ValidationError, match="R9"):
        GetPeerBenchmarkArgs.model_validate({"metric": "Health"})
    assert "Health" not in {m.value for m in PeerMetric}
    assert "Health" not in json.dumps(GetPeerBenchmarkArgs.model_json_schema())


@pytest.mark.parametrize("metric", config.PEER_METRICS)
def test_every_metric_of_06_is_accepted(metric):
    assert GetPeerBenchmarkArgs.model_validate({"metric": metric}).metric.value == metric


@pytest.mark.parametrize("args", [
    {"metric": "Salary"}, {"metric": "health"}, {"metric": "groceries"}, {"metric": "MRC-GRO-0032"},
    {"metric": "spend_total", "period": "last_3_months"},            # 06 has one window only
    {"metric": "spend_total", "customer_id": "CUST00002"},           # never a customer field (R4)
    {},
])
def test_invalid_peer_arguments(args):
    with pytest.raises(ValidationError):
        GetPeerBenchmarkArgs.model_validate(args)


def test_period_defaults_to_the_window():
    assert GetPeerBenchmarkArgs.model_validate({"metric": "Restaurants"}).period.value == "last_6_months"


# ---- peer benchmark: group status (06 `shown`) -------------------------------------------------------

@pytest.mark.parametrize("comparable, peer_n, expected", [
    (True, 118, (True, None)),
    (True, 20, (True, None)),                         # exactly 20 other peers is enough
    (True, 19, (False, "group_too_small")),           # a group below 20 is never shown
    (True, 0, (False, "group_too_small")),            # one-customer run without marts
    (False, 132, (False, "not_comparable")),          # sweep customer (CUST00006), however large the group
    (False, 3, (False, "not_comparable")),
])
def test_peer_status(comparable, peer_n, expected):
    assert peer_status(comparable, peer_n, 20) == expected


# ---- peer benchmark: labels ----------------------------------------------------------------------------


def test_group_labels_are_coarse():
    assert group_label("age_band+area3", "35-44 005", "en") == "Age 35-44, postal area 005"
    assert group_label("age_band+city", "25-34 02", "en") == "Age 25-34, Espoo and Kauniainen"
    assert group_label("age_band+city", "25-34 00", "fi") == "Ikä 25-34, Helsinki"
    assert group_label("age_band", "75+", "en") == "Age 75+"
    assert group_label("all", "all", "en") == "All customers"


def test_peer_spec_is_stable_and_records_the_metric():
    args = ("CUST00860", date(2026, 9, 30), "peer_benchmark.peer_median_month_eur@1", "06_peer_benchmark.sql",
            "spend_total", "peer_median_month_eur", {"peer_min_n": "20"}, D("2975.65"),
            {"start": "2026-04-01", "end": "2026-09-30"})
    spec = evidence.peer_spec(*args)
    assert spec["kind"] == "peer_aggregate" and spec["source"]["metric"] == "spend_total"
    assert evidence.make_ref(spec) == evidence.make_ref(evidence.peer_spec(*args))
    other_metric = evidence.peer_spec(*args[:4], "Restaurants", *args[5:])
    assert evidence.make_ref(other_metric) != evidence.make_ref(spec)
