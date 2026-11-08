from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import pytest
from jsonschema import Draft202012Validator
from nex_wa import (
    WA_EVIDENCE_INGEST_JOB_TYPE,
    WA_EVIDENCE_INTAKE_ADMISSION_SCHEMA,
    WA_EVIDENCE_INTAKE_REQUEST_SCHEMA,
    WA_ERROR_SCHEMA,
    WA_EXTERNAL_INTAKE_SOURCE_TYPES,
    WA_INTERNAL_SUPPORTING_SOURCE_TYPES,
    WaIntakeContractError,
    build_evidence_intake_admission,
    build_evidence_intake_identity,
    build_wa_error_response,
    normalize_evidence_intake_request,
    require_compatible_intake_replay,
)

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts"
SCHEMAS = CONTRACTS / "schemas" / "service" / "nex_wa"
EXAMPLES = CONTRACTS / "examples" / "service"
NEGATIVES = CONTRACTS / "tests" / "negative" / "service"


def _request(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "wa_evidence_intake_request.v1",
        "tenant_id": "VO00",
        "source_type": "AE_AGENT_RESULT",
        "source_ref": "agent-execution-9001",
        "source_revision_ref": "result-1",
        "source_hash": "sha256:" + "a" * 64,
        "occurred_at": "2026-10-27T18:00:00+09:00",
        "correlation_id": "corr-p9-s06-001",
        "request_id": "req-p9-s06-001",
        "trace_id": "trace-p9-s06-001",
    }
    value.update(overrides)
    return value


def _json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_contract_constants_keep_external_and_supporting_sources_separate() -> None:
    assert WA_EVIDENCE_INGEST_JOB_TYPE == "WA_EVIDENCE_INGEST"
    assert WA_EXTERNAL_INTAKE_SOURCE_TYPES == ("AE_AGENT_RESULT", "AE_ARTIFACT")
    assert WA_INTERNAL_SUPPORTING_SOURCE_TYPES == ("WC_WORK_RESULT",)


def test_request_normalization_and_job_identity_are_deterministic() -> None:
    first = normalize_evidence_intake_request(_request())
    second = normalize_evidence_intake_request(_request())
    identity = build_evidence_intake_identity(first)

    assert first == second
    assert first.occurred_at == "2026-10-27T09:00:00Z"
    assert build_evidence_intake_identity(second) == identity
    assert identity.job_id == "930cc597-42d1-55dc-a816-8b0acef0a4b5"
    assert identity.idempotency_key == (
        "sha256:0ec7ea649193935c76f13bac5bef95394cdeb7b1a3242896b23853c0bde00de8"
    )
    assert str(UUID(identity.job_id)) == identity.job_id
    assert identity.idempotency_key.startswith("sha256:")
    assert len(identity.idempotency_key) == 71


def test_source_hash_and_notification_metadata_do_not_change_identity() -> None:
    original = normalize_evidence_intake_request(_request())
    changed = normalize_evidence_intake_request(
        _request(
            source_hash="sha256:" + "b" * 64,
            occurred_at="2027-01-01T00:00:00Z",
            request_id="retry-request",
            trace_id="retry-trace",
        )
    )

    assert build_evidence_intake_identity(original) == build_evidence_intake_identity(
        changed
    )


def test_source_revision_changes_job_identity() -> None:
    original = normalize_evidence_intake_request(_request())
    revised = normalize_evidence_intake_request(
        _request(source_revision_ref="result-2")
    )

    assert build_evidence_intake_identity(original) != build_evidence_intake_identity(
        revised
    )


def test_exact_semantic_replay_accepts_changed_notification_metadata() -> None:
    original = normalize_evidence_intake_request(_request())
    replay = normalize_evidence_intake_request(
        _request(
            occurred_at="2026-10-27T09:00:01Z",
            request_id="retry-request",
            trace_id="retry-trace",
        )
    )

    require_compatible_intake_replay(original, replay)


@pytest.mark.parametrize(
    ("overrides", "detail"),
    [
        ({"source_hash": "sha256:" + "b" * 64}, "different source hash"),
        ({"source_ref": "agent-execution-OTHER"}, "does not match"),
    ],
)
def test_semantic_replay_conflict_is_typed(
    overrides: dict[str, object], detail: str
) -> None:
    original = normalize_evidence_intake_request(_request())
    candidate = normalize_evidence_intake_request(_request(**overrides))

    with pytest.raises(WaIntakeContractError) as caught:
        require_compatible_intake_replay(original, candidate)

    assert caught.value.error_code == "WA_SOURCE_IDEMPOTENCY_CONFLICT"
    assert caught.value.status_code == 409
    assert detail in caught.value.detail


@pytest.mark.parametrize(
    "field",
    ["prompt", "document_body", "artifact_bytes", "credentials", "token", "salary"],
)
def test_raw_or_sensitive_payload_fields_are_rejected(field: str) -> None:
    with pytest.raises(WaIntakeContractError) as caught:
        normalize_evidence_intake_request(_request(**{field: "private"}))

    assert caught.value.error_code == "WA_INTAKE_PAYLOAD_FORBIDDEN"
    assert field in caught.value.detail


@pytest.mark.parametrize("source_type", ["WC_WORK_RESULT", "UNKNOWN"])
def test_non_external_source_is_rejected(source_type: str) -> None:
    with pytest.raises(WaIntakeContractError) as caught:
        normalize_evidence_intake_request(_request(source_type=source_type))

    assert caught.value.error_code == "WA_INTAKE_SOURCE_UNSUPPORTED"


@pytest.mark.parametrize(
    ("overrides", "detail"),
    [
        ({"schema_version": "wa_evidence_intake_request.v2"}, "unsupported"),
        ({"source_hash": "bad-hash"}, "source_hash"),
        ({"occurred_at": "not-a-date"}, "RFC3339"),
        ({"occurred_at": "2026-10-27T09:00:00"}, "timezone"),
        ({"tenant_id": " VO00"}, "trimmed"),
        ({"source_ref": ""}, "non-empty"),
        ({"tenant_id": "V" * 129}, "exceeds 128"),
        ({"occurred_at": 42}, "RFC3339"),
        ({"request_id": 42}, "request_id"),
    ],
)
def test_invalid_request_values_are_rejected(
    overrides: dict[str, object], detail: str
) -> None:
    with pytest.raises(WaIntakeContractError) as caught:
        normalize_evidence_intake_request(_request(**overrides))

    assert caught.value.error_code == "WA_INTAKE_REQUEST_INVALID"
    assert detail in caught.value.detail


def test_missing_field_non_mapping_and_oversized_payload_are_rejected() -> None:
    missing = _request()
    del missing["source_ref"]
    with pytest.raises(WaIntakeContractError, match="missing required"):
        normalize_evidence_intake_request(missing)
    with pytest.raises(WaIntakeContractError, match="must be an object"):
        normalize_evidence_intake_request([])  # type: ignore[arg-type]
    with pytest.raises(WaIntakeContractError) as caught:
        normalize_evidence_intake_request(_request(source_ref="x" * 5000))
    assert caught.value.error_code == "WA_INTAKE_PAYLOAD_TOO_LARGE"
    assert caught.value.status_code == 413


def test_optional_refs_are_omitted_from_bounded_job_payload() -> None:
    value = _request()
    del value["request_id"]
    del value["trace_id"]
    normalized = normalize_evidence_intake_request(value)

    assert normalized.request_id is None
    assert normalized.trace_id is None
    assert set(normalized.to_job_payload()) == {
        "schema_version",
        "tenant_id",
        "source_type",
        "source_ref",
        "source_revision_ref",
        "source_hash",
        "occurred_at",
        "correlation_id",
    }


def test_admission_and_error_projections_use_frozen_contracts() -> None:
    request = normalize_evidence_intake_request(_request())
    admission = build_evidence_intake_admission(
        request,
        request_id="req-p9-s06-001",
        trace_id="trace-p9-s06-001",
        idempotent_reuse=False,
    )
    error = WaIntakeContractError(
        "WA_SOURCE_IDEMPOTENCY_CONFLICT",
        "source identity was reused with a different source hash",
        409,
    )
    response = build_wa_error_response(
        error,
        request_id="req-p9-s06-002",
        trace_id="trace-p9-s06-002",
    )

    assert admission.schema_version == WA_EVIDENCE_INTAKE_ADMISSION_SCHEMA
    assert admission.job_type == WA_EVIDENCE_INGEST_JOB_TYPE
    assert admission.status == "QUEUED"
    assert admission.to_dict()["idempotent_reuse"] is False
    assert response.schema_version == WA_ERROR_SCHEMA
    assert response.error_code == error.error_code
    assert response.to_dict()["detail"] == error.detail


@pytest.mark.parametrize(
    ("schema_name", "example_name"),
    [
        (
            "wa_evidence_intake_request.v1.schema.json",
            "wa_evidence_intake_request.agent_result.json",
        ),
        (
            "wa_evidence_intake_admission.v1.schema.json",
            "wa_evidence_intake_admission.queued.json",
        ),
        ("wa_error.v1.schema.json", "wa_error.idempotency_conflict.json"),
    ],
)
def test_positive_contract_fixtures_validate(
    schema_name: str, example_name: str
) -> None:
    schema = _json(SCHEMAS / schema_name)
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(_json(EXAMPLES / example_name))


@pytest.mark.parametrize(
    "negative_name",
    [
        "wa_evidence_intake_request.raw_prompt.json",
        "wa_evidence_intake_request.unsupported_source.json",
        "wa_evidence_intake_request.invalid_hash.json",
    ],
)
def test_negative_contract_fixtures_are_rejected(negative_name: str) -> None:
    schema = _json(SCHEMAS / "wa_evidence_intake_request.v1.schema.json")

    assert list(
        Draft202012Validator(schema).iter_errors(_json(NEGATIVES / negative_name))
    )


def test_contract_fixture_indexes_include_every_p9_s06_fixture() -> None:
    examples = {
        entry["path"] for entry in _json(CONTRACTS / "examples" / "index.json")["examples"]
    }
    negatives = {
        entry["path"]
        for entry in _json(CONTRACTS / "tests" / "negative" / "index.json")[
            "negative_examples"
        ]
    }

    assert {
        "examples/service/wa_evidence_intake_request.agent_result.json",
        "examples/service/wa_evidence_intake_admission.queued.json",
        "examples/service/wa_error.idempotency_conflict.json",
    }.issubset(examples)
    assert {
        "tests/negative/service/wa_evidence_intake_request.raw_prompt.json",
        "tests/negative/service/wa_evidence_intake_request.unsupported_source.json",
        "tests/negative/service/wa_evidence_intake_request.invalid_hash.json",
    }.issubset(negatives)
