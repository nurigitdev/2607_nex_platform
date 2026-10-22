from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from nex_ae_api.platform_approval_evidence import (
    PLATFORM_APPROVAL_EVIDENCE_SCHEMA_VERSION,
    PlatformApprovalEvidenceError,
    SqlAlchemyPlatformApprovalEvidenceRepository,
    build_platform_approval_evidence,
    validate_platform_approval_evidence,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[1]


class ApprovalRequestStub:
    def __init__(self, value: dict[str, object]) -> None:
        self.value = value

    def to_data(self) -> dict[str, object]:
        return dict(self.value)


def _sources() -> dict[str, object]:
    tenant_id = "tenant-p8-s48"
    request_id = "approval-request-p8-s48"
    nsl_execution_id = "nsl-execution-p8-s48"
    business_operation_id = "business-operation-p8-s48"
    agent_execution_id = str(uuid4())
    executable_step_id = str(uuid4())
    work_item_id = str(uuid4())
    protected_ref = "ae://nsl-approval-requests/ab/" + "a" * 64 + ".json"
    protected_hash = "sha256:" + "b" * 64
    request = {
        "tenant_id": tenant_id,
        "execution_id": nsl_execution_id,
        "business_operation_id": business_operation_id,
        "approval_id": "APPROVE_VOUCHER_DRAFT",
        "approval_request_id": request_id,
        "skill_id": "FINANCE.CREATE_VOUCHER_DRAFT",
        "skill_version": "0.2.0",
        "skill_semantic_hash": "sha256:" + "c" * 64,
        "write_node_id": "write-voucher-draft",
        "tool_id": "finance.create_voucher_draft",
        "payload_hash": "sha256:" + "d" * 64,
        "write_intent_hash": "write-intent-p8-s48",
        "risk_level": "R3",
        "message": "Create the protected voucher draft.",
        "expires_at": "2026-10-23T12:00:00Z",
        "display_safe_summary": {"line_count": 2},
        "protected_payload_ref": "snapshot://private/p8-s48",
        "data_classification": "CONFIDENTIAL",
    }
    protected = {
        "schema_version": "ae_nsl_approval_request.v2",
        "tenant_id": tenant_id,
        "approval_request_id": request_id,
        "nsl_execution_id": nsl_execution_id,
        "business_operation_id": business_operation_id,
        "protected_request_ref": protected_ref,
        "approval_request_hash": protected_hash,
        "request_size_bytes": 512,
        "content_type": "application/json",
        "data_classification": "CONFIDENTIAL",
        "created_at": "2026-10-22T11:55:00Z",
    }
    wait = {
        "wait_id": str(uuid4()),
        "tenant_id": tenant_id,
        "agent_execution_id": agent_execution_id,
        "executable_step_id": executable_step_id,
        "wait_type": "NSL_APPROVAL",
        "external_ref": request_id,
        "result_contract_ref": "urn:nex:approval-resume:p8:v1",
        "state": "PENDING",
        "version": 1,
        "created_at": "2026-10-22T11:55:00Z",
        "satisfied_at": None,
        "nsl_execution_id": nsl_execution_id,
        "business_operation_id": business_operation_id,
        "approval_request_id": request_id,
        "checkpoint_version": 7,
    }
    work_item = {
        "schema_version": "wc_approval_work_item.v1",
        "tenant_id": tenant_id,
        "approval_work_item_id": work_item_id,
        "approval_domain": "NSL_WRITE",
        "source_ref": request_id,
        "semantic_hash": protected_hash,
        "title": "Approve NSL WRITE",
        "display_safe_summary": "{}",
        "approval_provider_type": "NSL",
        "approval_target_ref": request_id,
        "target_approver_ref": "employee-1004",
        "target_role_ref": None,
        "target_org_scope_ref": None,
        "target_project_scope_ref": None,
        "agent_execution_id": agent_execution_id,
        "executable_step_id": executable_step_id,
        "nsl_execution_id": nsl_execution_id,
        "business_operation_id": business_operation_id,
        "approval_request_id": request_id,
        "protected_request_ref": protected_ref,
        "resume_target_ref": f"ae-wait:{wait['wait_id']}",
        "state": "APPROVED",
        "created_at": "2026-10-22T11:55:00Z",
        "expires_at": "2026-10-23T12:00:00Z",
        "version": 2,
    }
    decision = {
        "schema_version": "wc_approval_decision.v1",
        "tenant_id": tenant_id,
        "decision_id": str(uuid4()),
        "approval_work_item_id": work_item_id,
        "decision": "APPROVE",
        "decided_by": "employee-1004",
        "decision_comment": "Approved for the Golden A flow.",
        "decision_version": 1,
        "authorized_by_oa": True,
        "oa_decision_ref": "oa-decision-p8-s48",
        "authorization_revision_hash": "sha256:" + "e" * 64,
        "authorization_checked_at": "2026-10-22T11:59:00Z",
        "decided_at": "2026-10-22T12:00:00Z",
    }
    return {
        "approval_request": request,
        "protected_request": protected,
        "wait_registration": wait,
        "approval_work_item": work_item,
        "approval_decision": decision,
    }


def _build(sources: dict[str, object] | None = None) -> dict[str, object]:
    values = _sources() if sources is None else sources
    return build_platform_approval_evidence(
        **values,
        created_at=datetime(2026, 10, 22, 12, 1, tzinfo=UTC),
    )


@pytest.fixture
def evidence_repo():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE ae_approval_evidence (
                    tenant_id TEXT NOT NULL,
                    agent_execution_id TEXT NOT NULL,
                    executable_step_id TEXT NOT NULL,
                    nsl_execution_id TEXT NOT NULL,
                    business_operation_id TEXT NOT NULL,
                    approval_id TEXT NOT NULL,
                    approval_request_id TEXT NOT NULL,
                    skill_semantic_hash TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    approver_id TEXT NOT NULL,
                    decided_at TEXT NOT NULL,
                    expires_at TEXT NULL,
                    payload_hash TEXT NOT NULL,
                    write_intent_hash TEXT NOT NULL,
                    approval_work_item_ref TEXT NOT NULL,
                    oa_decision_ref TEXT NOT NULL,
                    protected_request_ref TEXT NOT NULL,
                    evidence_integrity TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, approval_request_id),
                    UNIQUE (tenant_id, approval_work_item_ref)
                )
                """
            )
        )
    yield (
        SqlAlchemyPlatformApprovalEvidenceRepository(
            sessionmaker(bind=engine, expire_on_commit=False)
        ),
        engine,
    )
    engine.dispose()


def test_builds_full_canonical_platform_evidence() -> None:
    evidence = _build()

    assert evidence["schema_version"] == PLATFORM_APPROVAL_EVIDENCE_SCHEMA_VERSION
    assert evidence["decision"] == "APPROVE"
    assert evidence["approver_id"] == "employee-1004"
    assert evidence["decided_at"] == "2026-10-22T12:00:00Z"
    assert evidence["expires_at"] == "2026-10-23T12:00:00Z"
    assert evidence["evidence_integrity"] == semantic_sha256_hash_ref(
        {
            key: value
            for key, value in evidence.items()
            if key not in {"schema_version", "evidence_integrity", "created_at"}
        }
    )


def test_build_accepts_nsl_public_request_object() -> None:
    sources = _sources()
    sources["approval_request"] = ApprovalRequestStub(
        sources["approval_request"]  # type: ignore[arg-type]
    )

    assert _build(sources)["approval_request_id"] == "approval-request-p8-s48"


def test_builds_rejected_evidence_and_accepts_resumed_wait() -> None:
    sources = _sources()
    sources["wait_registration"]["state"] = "RESUME_QUEUED"  # type: ignore[index]
    sources["approval_work_item"]["state"] = "REJECTED"  # type: ignore[index]
    sources["approval_decision"]["decision"] = "REJECT"  # type: ignore[index]

    assert _build(sources)["decision"] == "REJECT"


@pytest.mark.parametrize(
    ("source", "field", "value"),
    [
        ("wait_registration", "wait_type", "WORK_RESULT"),
        ("wait_registration", "checkpoint_version", 0),
        ("wait_registration", "state", "CANCELLED"),
        ("wait_registration", "external_ref", "other-request"),
        ("protected_request", "tenant_id", "other-tenant"),
        ("protected_request", "protected_request_ref", "file:///tmp/request"),
        ("protected_request", "approval_request_hash", "not-a-hash"),
        ("approval_work_item", "business_operation_id", "other-operation"),
        ("approval_work_item", "approval_domain", "AGENT_FORMAL"),
        ("approval_work_item", "approval_work_item_id", "not-a-uuid"),
        ("approval_work_item", "state", "PENDING"),
        ("approval_decision", "tenant_id", "other-tenant"),
        ("approval_decision", "decision_id", "not-a-uuid"),
        ("approval_decision", "decision_version", 0),
        ("approval_decision", "authorization_revision_hash", "bad-hash"),
        ("approval_decision", "authorization_checked_at", "2026-10-22T12:01:00Z"),
    ],
)
def test_builder_fails_closed_on_source_mismatch(
    source: str, field: str, value: object
) -> None:
    sources = _sources()
    sources[source][field] = value  # type: ignore[index]

    with pytest.raises(PlatformApprovalEvidenceError) as error:
        _build(sources)

    assert error.value.error_code == "ae.approval_evidence_invalid"


def test_builder_rejects_non_mapping_and_noncanonical_request() -> None:
    sources = _sources()
    sources["protected_request"] = []
    with pytest.raises(PlatformApprovalEvidenceError):
        _build(sources)

    sources = _sources()
    del sources["approval_request"]["skill_id"]  # type: ignore[index]
    with pytest.raises(PlatformApprovalEvidenceError):
        _build(sources)


def test_builder_rejects_expiration_drift_and_expired_decision() -> None:
    sources = _sources()
    sources["approval_work_item"]["expires_at"] = None  # type: ignore[index]
    with pytest.raises(PlatformApprovalEvidenceError):
        _build(sources)

    sources = _sources()
    sources["approval_decision"]["decided_at"] = "2026-10-23T12:00:00Z"  # type: ignore[index]
    sources["approval_decision"]["authorization_checked_at"] = (  # type: ignore[index]
        "2026-10-23T11:59:00Z"
    )
    with pytest.raises(PlatformApprovalEvidenceError):
        _build(sources)


def test_validation_rejects_tamper_and_invalid_shape() -> None:
    evidence = _build()
    tampered = {**evidence, "approver_id": "employee-9999"}
    with pytest.raises(PlatformApprovalEvidenceError) as integrity:
        validate_platform_approval_evidence(tampered)
    assert integrity.value.error_code == "ae.approval_evidence_integrity_failed"

    malformed = dict(evidence)
    malformed["unexpected"] = True
    with pytest.raises(PlatformApprovalEvidenceError):
        validate_platform_approval_evidence(malformed)

    wrong_version = {**evidence, "schema_version": "v0"}
    with pytest.raises(PlatformApprovalEvidenceError):
        validate_platform_approval_evidence(wrong_version)

    expired = {
        **evidence,
        "expires_at": "2026-10-22T11:59:00Z",
    }
    with pytest.raises(PlatformApprovalEvidenceError):
        validate_platform_approval_evidence(expired)

    assert str(integrity.value) == integrity.value.detail


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("tenant_id", ""),
        ("agent_execution_id", "bad"),
        ("skill_semantic_hash", "bad"),
        ("decision", "MAYBE"),
        ("approval_work_item_ref", "bad"),
        ("protected_request_ref", "s3://bucket/request"),
        ("decided_at", "not-time"),
        ("decided_at", 1234),
        ("created_at", "2026-10-22T12:00:00"),
    ],
)
def test_validation_rejects_invalid_field(field: str, value: object) -> None:
    evidence = {**_build(), field: value}
    with pytest.raises(PlatformApprovalEvidenceError):
        validate_platform_approval_evidence(evidence)


def test_repository_is_append_once_and_idempotent(evidence_repo) -> None:
    repository, _engine = evidence_repo
    evidence = _build()

    first = repository.create_or_get(evidence)
    replay = repository.create_or_get(
        {**evidence, "created_at": "2026-10-22T12:02:00Z"}
    )

    assert first == replay
    assert (
        repository.get(
            tenant_id=evidence["tenant_id"],
            approval_request_id=evidence["approval_request_id"],
        )
        == first
    )
    assert (
        repository.get(tenant_id=evidence["tenant_id"], approval_request_id="missing")
        is None
    )


def test_repository_rejects_changed_semantics(evidence_repo) -> None:
    repository, _engine = evidence_repo
    evidence = _build()
    repository.create_or_get(evidence)
    changed = {**evidence, "oa_decision_ref": "oa-decision-other"}
    changed["evidence_integrity"] = semantic_sha256_hash_ref(
        {
            key: value
            for key, value in changed.items()
            if key not in {"schema_version", "evidence_integrity", "created_at"}
        }
    )

    with pytest.raises(PlatformApprovalEvidenceError) as error:
        repository.create_or_get(changed)

    assert error.value.error_code == "ae.approval_evidence_idempotency_conflict"


def test_repository_maps_unique_work_item_conflict(evidence_repo) -> None:
    repository, _engine = evidence_repo
    evidence = _build()
    repository.create_or_get(evidence)
    changed = {
        **evidence,
        "approval_request_id": "approval-request-p8-s48-other",
    }
    changed["evidence_integrity"] = semantic_sha256_hash_ref(
        {
            key: value
            for key, value in changed.items()
            if key not in {"schema_version", "evidence_integrity", "created_at"}
        }
    )

    with pytest.raises(PlatformApprovalEvidenceError) as error:
        repository.create_or_get(changed)

    assert error.value.error_code == "ae.approval_evidence_idempotency_conflict"


def test_repository_rejects_tampered_persisted_evidence(evidence_repo) -> None:
    repository, engine = evidence_repo
    evidence = _build()
    repository.create_or_get(evidence)
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE ae_approval_evidence SET approver_id = 'tampered' "
                "WHERE tenant_id = :tenant_id"
            ),
            {"tenant_id": evidence["tenant_id"]},
        )

    with pytest.raises(PlatformApprovalEvidenceError) as error:
        repository.get(
            tenant_id=evidence["tenant_id"],
            approval_request_id=evidence["approval_request_id"],
        )

    assert error.value.error_code == "ae.approval_evidence_integrity_failed"


def test_repository_maps_database_failures(evidence_repo) -> None:
    repository, engine = evidence_repo
    evidence = _build()
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE ae_approval_evidence"))

    with pytest.raises(PlatformApprovalEvidenceError) as create_error:
        repository.create_or_get(evidence)
    assert create_error.value.retryable is True

    with pytest.raises(PlatformApprovalEvidenceError) as get_error:
        repository.get(
            tenant_id=evidence["tenant_id"],
            approval_request_id=evidence["approval_request_id"],
        )
    assert get_error.value.retryable is True


def test_migration_defines_short_immutable_evidence_table() -> None:
    content = (
        ROOT / "database/nex-ae-api/migrations/2504_ae_approval_evidence.sql"
    ).read_text(encoding="utf-8")
    compact = " ".join(content.lower().split())

    assert "create table if not exists ae_approval_evidence" in compact
    assert "primary key (tenant_id, approval_request_id)" in compact
    assert "unique (tenant_id, approval_work_item_ref)" in compact
    assert "references ae_nsl_approval_request" in compact
    assert "'2504_ae_approval_evidence'" in compact
    assert "update ae_approval_evidence" not in compact
    assert "delete from ae_approval_evidence" not in compact
    assert len("ae_approval_evidence") < 40
