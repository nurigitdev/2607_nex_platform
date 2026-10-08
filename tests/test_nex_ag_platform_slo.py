from __future__ import annotations

import math

import pytest

from nex_ag.platform_slo import (
    SloPolicy,
    SloPolicyError,
    default_platform_slo_policies,
    evaluate_slo,
)
from nex_runtime import ObservabilitySignal


def _policy(**overrides: object) -> SloPolicy:
    values: dict[str, object] = {
        "policy_id": "slo:nex-cx:index-freshness",
        "policy_revision": 1,
        "service_id": "nex-cx",
        "sli_name": "cx.index_freshness",
        "signal_name": "cx.index.freshness",
        "measurement_name": "freshness_age_seconds",
        "comparator": "LTE",
        "good_threshold": 300.0,
        "objective_target": 0.99,
        "warning_burn_rate": 1.0,
        "critical_burn_rate": 5.0,
        "window_seconds": 300,
        "minimum_sample_count": 3,
        "maximum_signal_age_seconds": 60,
        "accountable_owner": "content",
        "runbook_ref": "runbook:nex-cx:index-freshness",
    }
    values.update(overrides)
    return SloPolicy(**values)  # type: ignore[arg-type]


def _signal(index: int, value: float, **overrides: object) -> ObservabilitySignal:
    values: dict[str, object] = {
        "signal_id": f"signal:cx:freshness:{index}",
        "service_id": "nex-cx",
        "signal_kind": "METRIC",
        "signal_name": "cx.index.freshness",
        "observed_at": f"2026-10-08T01:00:{index:02d}Z",
        "severity": "INFO",
        "status": "HEALTHY",
        "correlation_key": "cx:index:freshness",
        "measurements": {"freshness_age_seconds": value},
    }
    values.update(overrides)
    return ObservabilitySignal(**values)  # type: ignore[arg-type]


def test_policy_wire_and_hash_are_deterministic() -> None:
    policy = _policy()
    wire = policy.to_wire()
    assert wire["schema_version"] == "ag_slo_policy.v1"
    assert wire["policy_hash"].startswith("sha256:")
    assert policy.policy_hash == _policy().policy_hash
    assert "policy_hash" not in policy.to_wire(include_hash=False)


def test_default_policies_cover_all_service_owners() -> None:
    policies = default_platform_slo_policies()
    assert [policy.service_id for policy in policies] == [
        "nex-oa",
        "nex-ae-api",
        "nex-cx",
        "nex-mo",
        "nex-ag",
    ]
    assert len({policy.policy_hash for policy in policies}) == 5
    assert all(policy.runbook_ref.startswith("runbook:") for policy in policies)


def test_evaluate_healthy_lte_and_gte_policies() -> None:
    signals = [_signal(index, value) for index, value in enumerate((10, 20, 30), start=1)]
    result = evaluate_slo(_policy(), signals, evaluated_at="2026-10-08T01:00:40Z")
    assert result["status"] == "HEALTHY"
    assert result["reason_code"] == "SLO_OBJECTIVE_MET"
    assert result["attainment"] == 1.0
    assert result["burn_rate"] == 0.0
    assert result["private_payload_included"] is False

    gte = _policy(comparator="GTE", good_threshold=0.5)
    gte_signals = [_signal(index, value) for index, value in enumerate((1, 1, 1), start=1)]
    assert evaluate_slo(gte, gte_signals, evaluated_at="2026-10-08T01:00:40Z")["status"] == "HEALTHY"


def test_evaluate_warning_and_critical_burn() -> None:
    warning_policy = _policy(objective_target=0.5, warning_burn_rate=1.0, critical_burn_rate=2.0)
    warning = evaluate_slo(
        warning_policy,
        [_signal(1, 10), _signal(2, 900), _signal(3, 900), _signal(4, 900)],
        evaluated_at="2026-10-08T01:00:40Z",
    )
    assert warning["status"] == "AT_RISK"
    assert warning["reason_code"] == "SLO_WARNING_BURN"
    assert warning["good_count"] == 1
    assert warning["bad_count"] == 3

    critical = evaluate_slo(
        _policy(),
        [_signal(1, 900), _signal(2, 900), _signal(3, 900)],
        evaluated_at="2026-10-08T01:00:40Z",
    )
    assert critical["status"] == "BREACHED"
    assert critical["reason_code"] == "SLO_CRITICAL_BURN"


def test_evaluate_no_data_for_sample_floor_staleness_and_missing_measurement() -> None:
    insufficient = evaluate_slo(
        _policy(),
        [_signal(1, 10)],
        evaluated_at="2026-10-08T01:00:40Z",
    )
    assert insufficient["status"] == "NO_DATA"
    assert insufficient["reason_code"] == "SLO_SAMPLE_FLOOR_NOT_MET"

    stale = evaluate_slo(
        _policy(),
        [
            _signal(index, 10, observed_at=f"2026-10-08T00:56:{index:02d}Z")
            for index in range(1, 4)
        ],
        evaluated_at="2026-10-08T01:00:00Z",
    )
    assert stale["status"] == "NO_DATA"
    assert stale["reason_code"] == "SLO_SIGNAL_STALE"

    missing = _signal(1, 10, measurements={"other": 1})
    unrelated = _signal(2, 10, service_id="nex-mo", signal_name="mo.provider.latency")
    outside = _signal(3, 10, observed_at="2026-10-08T00:50:00Z")
    no_data = evaluate_slo(
        _policy(), [missing, unrelated, outside], evaluated_at="2026-10-08T01:00:10Z"
    )
    assert no_data["sample_count"] == 0
    assert no_data["latest_observed_at"] is None


def test_evaluate_rejects_future_and_nonfinite_samples() -> None:
    with pytest.raises(SloPolicyError) as exc_info:
        evaluate_slo(_policy(), [_signal(1, 10)], evaluated_at="2026-10-08T00:59:00Z")
    assert exc_info.value.error_code == "slo.signal_from_future"

    signal = _signal(1, 10)
    object.__setattr__(signal, "measurements", {"freshness_age_seconds": math.inf})
    with pytest.raises(SloPolicyError) as exc_info:
        evaluate_slo(_policy(minimum_sample_count=1), [signal], evaluated_at="2026-10-08T01:00:40Z")
    assert exc_info.value.error_code == "slo.sample_invalid"


@pytest.mark.parametrize(
    ("overrides", "error_code"),
    [
        ({"policy_id": "bad value"}, "slo.identifier_invalid"),
        ({"policy_revision": 0}, "slo.policy_revision_invalid"),
        ({"comparator": "EQ"}, "slo.comparator_invalid"),
        ({"good_threshold": math.inf}, "slo.numeric_value_invalid"),
        ({"objective_target": 0}, "slo.objective_target_invalid"),
        ({"objective_target": 1}, "slo.objective_target_invalid"),
        ({"warning_burn_rate": 0.9}, "slo.burn_rate_invalid"),
        ({"critical_burn_rate": 1.0}, "slo.burn_rate_invalid"),
        ({"window_seconds": 59}, "slo.window_invalid"),
        ({"minimum_sample_count": 0}, "slo.sample_floor_invalid"),
        ({"maximum_signal_age_seconds": 0}, "slo.freshness_invalid"),
        ({"maximum_signal_age_seconds": 301}, "slo.freshness_invalid"),
    ],
)
def test_policy_rejects_invalid_configuration(overrides: dict[str, object], error_code: str) -> None:
    with pytest.raises(SloPolicyError) as exc_info:
        _policy(**overrides)
    assert exc_info.value.error_code == error_code


@pytest.mark.parametrize(
    ("value", "error_code"),
    [
        (None, "slo.timestamp_invalid"),
        ("bad", "slo.timestamp_invalid"),
        ("2026-10-08T01:00:00", "slo.timestamp_timezone_required"),
    ],
)
def test_evaluation_rejects_invalid_timestamp(value: object, error_code: str) -> None:
    with pytest.raises(SloPolicyError) as exc_info:
        evaluate_slo(_policy(), [], evaluated_at=value)  # type: ignore[arg-type]
    assert exc_info.value.error_code == error_code
