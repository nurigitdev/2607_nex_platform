from __future__ import annotations

import pytest

from nex_runtime import (
    CrossServiceTraceError,
    build_cross_service_trace_source_projection,
    build_cross_service_trace_stage,
    build_cross_service_trace_timeline,
    validate_cross_service_trace_source_projection,
)

TRACE_ID = "13731373137313731373137313731373"
OWNER_DIGEST = "a" * 64


def _stage(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "stage_id": "stage-generation-1373",
        "trace_id": TRACE_ID,
        "request_id": "request-1373",
        "service_id": "nex-cx",
        "stage_family": "GENERATION",
        "stage_status": "SUCCEEDED",
        "operation_timestamp": "2026-10-06T09:13:00Z",
        "correlation_refs": {
            "retrieval_package_id": "retrieval-1373",
            "cx_generation_id": "generation-1373",
        },
        "safe_attributes": {
            "event_type": "generation.completed",
            "attempt": 1,
            "retryable": False,
            "progress_percent": 100.0,
            "model_revision": "qwen-revision-1",
            "deployment_id": "dgx-generation",
            "provider_route_id": "route-general-default",
            "provider_mode": "live",
        },
        "owner_digest": OWNER_DIGEST,
    }
    values.update(overrides)
    return build_cross_service_trace_stage(**values)  # type: ignore[arg-type]


def test_build_stage_normalizes_only_metadata_safe_values() -> None:
    result = _stage()

    assert result["stage_schema_version"] == "cross_service_trace_stage.v1"
    assert result["owner_digest"] == OWNER_DIGEST
    assert list(result["correlation_refs"]) == [
        "cx_generation_id",
        "retrieval_package_id",
    ]
    assert list(result["safe_attributes"]) == [
        "attempt",
        "deployment_id",
        "event_type",
        "model_revision",
        "progress_percent",
        "provider_mode",
        "provider_route_id",
        "retryable",
    ]
    assert result["private_payload_included"] is False


def test_build_timeline_sorts_and_summarizes_ready_stages() -> None:
    later = _stage()
    earlier = _stage(
        stage_id="stage-auth-1373",
        service_id="nex-oa",
        stage_family="AUTH",
        operation_timestamp="2026-10-06T09:12:00+00:00",
        correlation_refs={"session_id": "session-1373"},
        safe_attributes={"result_code": "AUTHENTICATED"},
        owner_digest=None,
    )

    result = build_cross_service_trace_timeline(
        trace_id=TRACE_ID,
        stages=[later, earlier],
        source_statuses={"nex-cx": "READY", "nex-oa": "READY"},
        checked_at="2026-10-06T09:14:00Z",
    )

    assert result["projection_status"] == "READY"
    assert [item["stage_id"] for item in result["timeline"]] == [
        "stage-auth-1373",
        "stage-generation-1373",
    ]
    assert result["source_statuses"] == [
        {"service_id": "nex-cx", "source_status": "READY"},
        {"service_id": "nex-oa", "source_status": "READY"},
    ]
    assert result["summary"] == {
        "stage_count": 2,
        "source_count": 2,
        "by_family": {"AUTH": 1, "GENERATION": 1},
        "by_status": {"SUCCEEDED": 2},
        "private_payload_included": False,
    }


def test_build_source_projection_reuses_validated_timeline() -> None:
    result = build_cross_service_trace_source_projection(
        service_id="nex-cx",
        trace_id=TRACE_ID,
        stages=[_stage()],
        source_status="READY",
        checked_at="2026-10-06T09:14:00Z",
    )

    assert result["projection_schema_version"] == (
        "service_cross_service_trace_projection.v1"
    )
    assert result["service_id"] == "nex-cx"
    assert result["source_status"] == "READY"
    assert result["summary"] == {
        "stage_count": 1,
        "by_family": {"GENERATION": 1},
        "by_status": {"SUCCEEDED": 1},
        "private_payload_included": False,
    }


def test_validate_source_projection_requires_exact_metadata_only_contract() -> None:
    projection = build_cross_service_trace_source_projection(
        service_id="nex-cx",
        trace_id=TRACE_ID,
        stages=[_stage()],
        source_status="READY",
        checked_at="2026-10-06T09:14:00Z",
    )

    assert (
        validate_cross_service_trace_source_projection(
            projection,
            expected_service_id="nex-cx",
            expected_trace_id=TRACE_ID,
        )
        == projection
    )

    invalid_cases = []
    with_extra = {**projection, "prompt": "private"}
    invalid_cases.append((with_extra, "trace.source_projection_fields_invalid"))
    wrong_version = {**projection, "projection_schema_version": "old"}
    invalid_cases.append((wrong_version, "trace.source_projection_version_invalid"))
    wrong_service = {**projection, "service_id": "nex-mo"}
    invalid_cases.append((wrong_service, "trace.source_projection_service_mismatch"))
    wrong_trace = {**projection, "trace_id": "a" * 32}
    invalid_cases.append((wrong_trace, "trace.source_projection_trace_mismatch"))
    wrong_stages = {**projection, "stages": {}}
    invalid_cases.append((wrong_stages, "trace.source_projection_stages_invalid"))
    wrong_summary = {
        **projection,
        "summary": {**projection["summary"], "stage_count": 2},
    }
    invalid_cases.append((wrong_summary, "trace.source_projection_contract_invalid"))
    private_stage = {**projection["stages"][0], "generated_text": "private"}
    invalid_cases.append(
        (
            {**projection, "stages": [private_stage]},
            "trace.source_projection_contract_invalid",
        )
    )

    for payload, error_code in invalid_cases:
        with pytest.raises(CrossServiceTraceError) as exc_info:
            validate_cross_service_trace_source_projection(
                payload,
                expected_service_id="nex-cx",
                expected_trace_id=TRACE_ID,
            )
        assert exc_info.value.error_code == error_code


@pytest.mark.parametrize(
    ("service_id", "source_status", "stage_service", "error_code"),
    [
        ("unknown", "READY", "nex-cx", "trace.source_service_invalid"),
        ("nex-cx", "BROKEN", "nex-cx", "trace.source_status_invalid"),
        (
            "nex-cx",
            "READY",
            "nex-mo",
            "trace.source_stage_service_mismatch",
        ),
    ],
)
def test_source_projection_rejects_invalid_source_binding(
    service_id: str,
    source_status: str,
    stage_service: str,
    error_code: str,
) -> None:
    with pytest.raises(CrossServiceTraceError) as exc_info:
        build_cross_service_trace_source_projection(
            service_id=service_id,
            trace_id=TRACE_ID,
            stages=[_stage(service_id=stage_service)],
            source_status=source_status,
            checked_at="2026-10-06T09:14:00Z",
        )

    assert exc_info.value.error_code == error_code


@pytest.mark.parametrize(
    ("sources", "stage_status"),
    [
        ({"nex-cx": "DEGRADED"}, "SUCCEEDED"),
        ({"nex-cx": "READY"}, "FAILED"),
        ({"nex-cx": "READY"}, "BLOCKED"),
    ],
)
def test_build_timeline_reports_degraded_sources_or_stages(
    sources: dict[str, str], stage_status: str
) -> None:
    result = build_cross_service_trace_timeline(
        trace_id=TRACE_ID,
        stages=[_stage(stage_status=stage_status)],
        source_statuses=sources,
        checked_at="2026-10-06T09:14:00Z",
    )

    assert result["projection_status"] == "DEGRADED"


@pytest.mark.parametrize(
    ("overrides", "error_code"),
    [
        ({"stage_id": " bad"}, "trace.identifier_invalid"),
        ({"request_id": ""}, "trace.identifier_invalid"),
        ({"trace_id": "ABC"}, "trace.trace_id_invalid"),
        ({"service_id": "nex-unknown"}, "trace.service_id_invalid"),
        ({"stage_family": "PRIVATE"}, "trace.stage_family_invalid"),
        ({"stage_status": "DONE"}, "trace.stage_status_invalid"),
        ({"operation_timestamp": 1}, "trace.timestamp_invalid"),
        ({"operation_timestamp": "not-a-time"}, "trace.timestamp_invalid"),
        ({"operation_timestamp": "2026-10-06T09:13:00"}, "trace.timestamp_invalid"),
        ({"owner_digest": "short"}, "trace.owner_digest_invalid"),
        (
            {"correlation_refs": {"prompt_ref": "private"}},
            "trace.private_field_forbidden",
        ),
        (
            {"correlation_refs": {"unknown_ref": "value"}},
            "trace.correlation_field_forbidden",
        ),
        (
            {"correlation_refs": {1: "value"}},
            "trace.field_name_invalid",
        ),
        (
            {"correlation_refs": {"session_id": " bad"}},
            "trace.identifier_invalid",
        ),
        (
            {"safe_attributes": {"source_text": "private"}},
            "trace.private_field_forbidden",
        ),
        (
            {"safe_attributes": {"unknown": "value"}},
            "trace.attribute_field_forbidden",
        ),
        (
            {"safe_attributes": {"event_type": ["value"]}},
            "trace.attribute_value_invalid",
        ),
        (
            {"safe_attributes": {"event_type": b"value"}},
            "trace.attribute_value_invalid",
        ),
        (
            {"safe_attributes": {"event_type": ""}},
            "trace.attribute_value_invalid",
        ),
        (
            {"safe_attributes": {"event_type": "x" * 129}},
            "trace.attribute_value_invalid",
        ),
    ],
)
def test_stage_rejects_unsafe_values(
    overrides: dict[str, object], error_code: str
) -> None:
    with pytest.raises(CrossServiceTraceError) as exc_info:
        _stage(**overrides)

    assert exc_info.value.error_code == error_code
    assert exc_info.value.detail


@pytest.mark.parametrize(
    ("trace_id", "sources", "error_code"),
    [
        ("invalid", {"nex-cx": "READY"}, "trace.trace_id_invalid"),
        (TRACE_ID, {"nex-private": "READY"}, "trace.source_service_invalid"),
        (TRACE_ID, {"nex-cx": "BROKEN"}, "trace.source_status_invalid"),
    ],
)
def test_timeline_rejects_invalid_identity_and_source_status(
    trace_id: str, sources: dict[str, str], error_code: str
) -> None:
    with pytest.raises(CrossServiceTraceError) as exc_info:
        build_cross_service_trace_timeline(
            trace_id=trace_id,
            stages=[],
            source_statuses=sources,
            checked_at="2026-10-06T09:14:00Z",
        )

    assert exc_info.value.error_code == error_code


def test_timeline_rejects_missing_stage_field_and_trace_mismatch() -> None:
    incomplete = _stage()
    del incomplete["request_id"]
    with pytest.raises(CrossServiceTraceError) as missing:
        build_cross_service_trace_timeline(
            trace_id=TRACE_ID,
            stages=[incomplete],
            source_statuses={"nex-cx": "READY"},
            checked_at="2026-10-06T09:14:00Z",
        )
    assert missing.value.error_code == "trace.stage_field_missing"

    with pytest.raises(CrossServiceTraceError) as mismatch:
        build_cross_service_trace_timeline(
            trace_id="f" * 32,
            stages=[_stage()],
            source_statuses={"nex-cx": "READY"},
            checked_at="2026-10-06T09:14:00Z",
        )
    assert mismatch.value.error_code == "trace.stage_trace_mismatch"
