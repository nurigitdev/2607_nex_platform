from __future__ import annotations

import math

import pytest

from nex_runtime import (
    ObservabilitySignal,
    ObservabilitySignalError,
    correlate_observability_signals,
)

TRACE_ID = "a" * 32


def _signal(**overrides: object) -> ObservabilitySignal:
    values: dict[str, object] = {
        "signal_id": "signal:nex-cx:index-freshness:1",
        "service_id": "nex-cx",
        "signal_kind": "METRIC",
        "signal_name": "cx.index.freshness",
        "observed_at": "2026-10-08T01:00:00Z",
        "severity": "INFO",
        "status": "HEALTHY",
        "correlation_key": "cx:index:freshness",
        "trace_id": TRACE_ID,
        "request_id": "request-1474",
        "resource_type": "index",
        "resource_id": "primary",
        "measurements": {"freshness_age_seconds": 3, "pending_count": 0},
        "reason_codes": ("INDEX_FRESH",),
        "safe_attributes": {
            "environment_class": "test",
            "operation": "index-refresh",
            "state": "READY",
            "retryable": False,
        },
    }
    values.update(overrides)
    return ObservabilitySignal(**values)  # type: ignore[arg-type]


def test_signal_wire_is_deterministic_and_metadata_only() -> None:
    signal = _signal()
    wire = signal.to_wire()

    assert wire["schema_version"] == "platform_observability_signal.v1"
    assert wire["observed_at"] == "2026-10-08T01:00:00Z"
    assert wire["measurements"] == {
        "freshness_age_seconds": 3.0,
        "pending_count": 0.0,
    }
    assert wire["reason_codes"] == ["INDEX_FRESH"]
    assert wire["private_payload_included"] is False
    assert wire["signal_digest"].startswith("sha256:")
    assert signal.signal_digest == _signal().signal_digest
    assert "signal_digest" not in signal.to_wire(include_digest=False)


def test_correlation_prefers_trace_and_orders_signals() -> None:
    later = _signal()
    earlier = _signal(
        signal_id="signal:nex-oa:auth:1",
        service_id="nex-oa",
        signal_kind="TRACE",
        signal_name="oa.auth.completed",
        observed_at="2026-10-08T00:59:55+00:00",
        correlation_key="auth:session:1",
        resource_type=None,
        resource_id=None,
        measurements={},
        reason_codes=(),
        safe_attributes={"operation": "authenticate", "state": "SUCCEEDED"},
    )
    untraced = _signal(
        signal_id="signal:nex-ag:projection:1",
        service_id="nex-ag",
        signal_kind="READINESS",
        signal_name="ag.projection.readiness",
        observed_at="2026-10-08T00:59:58Z",
        correlation_key="ag:projection",
        trace_id=None,
        request_id=None,
        resource_type=None,
        resource_id=None,
        measurements={"age_seconds": 1},
        reason_codes=("PROJECTION_READY",),
        safe_attributes={"source_kind": "service-api"},
    )

    result = correlate_observability_signals(
        [later, untraced, earlier],
        checked_at="2026-10-08T01:00:10Z",
        maximum_age_seconds=30,
    )

    assert result["correlation_status"] == "READY"
    assert result["summary"] == {
        "signal_count": 3,
        "group_count": 2,
        "trace_linked_count": 2,
        "stale_count": 0,
        "by_kind": {"METRIC": 1, "READINESS": 1, "TRACE": 1},
        "by_status": {"HEALTHY": 3},
        "private_payload_included": False,
    }
    trace_group = next(item for item in result["groups"] if item["correlation_type"] == "TRACE")
    assert trace_group["signal_ids"] == [earlier.signal_id, later.signal_id]
    assert trace_group["service_ids"] == ["nex-cx", "nex-oa"]
    assert trace_group["degraded"] is False


def test_correlation_marks_stale_and_degraded_without_dropping_signal() -> None:
    result = correlate_observability_signals(
        [
            _signal(
                trace_id=None,
                status="FAILED",
                severity="ERROR",
                observed_at="2026-10-08T00:58:00Z",
                reason_codes=("INDEX_STALE",),
            )
        ],
        checked_at="2026-10-08T01:00:00Z",
        maximum_age_seconds=60,
    )

    assert result["correlation_status"] == "STALE"
    assert result["stale_signal_ids"] == ["signal:nex-cx:index-freshness:1"]
    assert result["groups"][0]["degraded"] is True


@pytest.mark.parametrize(
    ("overrides", "error_code"),
    [
        ({"signal_id": ""}, "observability.identifier_invalid"),
        ({"signal_id": "prompt-content"}, "observability.private_field_forbidden"),
        ({"service_id": "unknown"}, "observability.service_invalid"),
        ({"signal_kind": "EVENT"}, "observability.kind_invalid"),
        ({"severity": "PANIC"}, "observability.severity_invalid"),
        ({"status": "PASS"}, "observability.status_invalid"),
        ({"trace_id": "bad"}, "observability.trace_id_invalid"),
        ({"request_id": "bad value"}, "observability.identifier_invalid"),
        ({"resource_id": None}, "observability.resource_binding_invalid"),
        ({"observed_at": "bad"}, "observability.timestamp_invalid"),
        ({"observed_at": None}, "observability.timestamp_invalid"),
        ({"observed_at": "2026-10-08T01:00:00"}, "observability.timestamp_timezone_required"),
        ({"measurements": {"Bad": 1}}, "observability.measurement_name_invalid"),
        ({"measurements": {"prompt_count": 1}}, "observability.private_field_forbidden"),
        ({"measurements": {"latency": True}}, "observability.measurement_value_invalid"),
        ({"measurements": {"latency": math.inf}}, "observability.measurement_value_invalid"),
        ({"reason_codes": "BAD"}, "observability.reason_codes_invalid"),
        ({"reason_codes": ("BAD", "BAD")}, "observability.reason_codes_duplicate"),
        ({"safe_attributes": {"raw": "value"}}, "observability.attribute_field_forbidden"),
        ({"safe_attributes": {"state": []}}, "observability.attribute_value_invalid"),
        ({"safe_attributes": {"state": "x" * 201}}, "observability.attribute_value_invalid"),
        ({"safe_attributes": {"capability": math.nan}}, "observability.attribute_value_invalid"),
    ],
)
def test_signal_rejects_invalid_or_private_values(
    overrides: dict[str, object], error_code: str
) -> None:
    with pytest.raises(ObservabilitySignalError) as exc_info:
        _signal(**overrides)
    assert exc_info.value.error_code == error_code


def test_signal_rejects_bounded_collection_overflow() -> None:
    with pytest.raises(ObservabilitySignalError) as exc_info:
        _signal(measurements={f"metric.{index}": index for index in range(33)})
    assert exc_info.value.error_code == "observability.measurement_count_invalid"

    with pytest.raises(ObservabilitySignalError) as exc_info:
        _signal(reason_codes=tuple(f"REASON_{index}" for index in range(17)))
    assert exc_info.value.error_code == "observability.reason_codes_invalid"

    attributes = {"state": "ready"}
    for index in range(16):
        attributes[f"unknown_{index}"] = "x"
    with pytest.raises(ObservabilitySignalError) as exc_info:
        _signal(safe_attributes=attributes)
    assert exc_info.value.error_code == "observability.attribute_count_invalid"


@pytest.mark.parametrize(
    ("signals", "checked_at", "maximum_age", "error_code"),
    [
        ([], "2026-10-08T01:00:00Z", 60, "observability.signal_count_invalid"),
        (None, "2026-10-08T01:00:00Z", 60, "observability.signal_count_invalid"),
        ("one", "2026-10-08T01:00:00Z", 0, "observability.maximum_age_invalid"),
        ("duplicate", "2026-10-08T01:00:00Z", 60, "observability.signal_duplicate"),
        ("one", "2026-10-08T00:59:59Z", 60, "observability.signal_from_future"),
    ],
)
def test_correlation_rejects_invalid_collections(
    signals: object, checked_at: str, maximum_age: int, error_code: str
) -> None:
    collection = (
        [_signal(), _signal()]
        if signals == "duplicate"
        else [_signal()]
        if signals == "one"
        else signals
    )
    with pytest.raises(ObservabilitySignalError) as exc_info:
        correlate_observability_signals(
            collection,  # type: ignore[arg-type]
            checked_at=checked_at,
            maximum_age_seconds=maximum_age,
        )
    assert exc_info.value.error_code == error_code
