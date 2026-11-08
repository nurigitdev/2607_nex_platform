from __future__ import annotations

import copy
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest
from nex_ae_api import nsl_approval_requests as requests
from nex_ae_api.nsl_approval_requests import (
    ProtectedApprovalRequestError,
    SqlAlchemyProtectedApprovalRequestStore,
    build_protected_approval_request_payload,
    canonical_approval_request_data,
)
from nex_runtime.semantic_hashes import canonical_json
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

NOW = datetime(2026, 10, 22, 3, 4, 5, tzinfo=UTC)
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64


@dataclass(frozen=True)
class ApprovalRequestStub:
    data: dict[str, object]

    def to_data(self) -> dict[str, object]:
        return copy.deepcopy(self.data)


def _request(**changes: object) -> ApprovalRequestStub:
    data: dict[str, object] = {
        "tenant_id": "tenant-private-a",
        "execution_id": "nsl-execution-s44-001",
        "business_operation_id": "business-operation-s44-001",
        "approval_id": "APPROVE_VOUCHER_DRAFT",
        "approval_request_id": "approval-request-s44-001",
        "skill_id": "FINANCE.CREATE_VOUCHER_DRAFT",
        "skill_version": "0.2.0",
        "skill_semantic_hash": HASH_A,
        "write_node_id": "write-voucher-draft",
        "tool_id": "finance.create_voucher_draft",
        "payload_hash": HASH_B,
        "write_intent_hash": "write-intent-s44-001",
        "risk_level": "R3",
        "message": "Create the confidential voucher draft.",
        "expires_at": "2026-10-22T04:04:05+00:00",
        "display_safe_summary": {"line_count": 2, "currency": "KRW"},
        "protected_payload_ref": "snapshot://private/write-payload-s44-001",
        "data_classification": "CONFIDENTIAL",
    }
    data.update(changes)
    return ApprovalRequestStub(data)


@pytest.fixture
def sqlite_store():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE ae_nsl_approval_request (
                    tenant_id TEXT NOT NULL,
                    approval_request_id TEXT NOT NULL,
                    nsl_execution_id TEXT NOT NULL,
                    business_operation_id TEXT NOT NULL,
                    protected_request_ref TEXT NOT NULL,
                    approval_request_hash TEXT NOT NULL,
                    request_size_bytes INTEGER NOT NULL,
                    content_type TEXT NOT NULL,
                    data_classification TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    approval_request_bytes BLOB NOT NULL,
                    PRIMARY KEY (tenant_id, approval_request_id),
                    UNIQUE (tenant_id, protected_request_ref)
                )
                """
            )
        )
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield engine, SqlAlchemyProtectedApprovalRequestStore(factory, clock=lambda: NOW)
    engine.dispose()


def test_canonical_payload_is_exact_bounded_bytes_with_opaque_reference() -> None:
    request = _request()
    canonical = canonical_approval_request_data(request)
    payload = build_protected_approval_request_payload(request)
    content = payload["content_bytes"].decode("utf-8")

    assert canonical == request.to_data()
    assert content == canonical_json(request.to_data())
    assert payload["size_bytes"] == len(payload["content_bytes"])
    assert (
        payload["content_sha256"]
        == hashlib.sha256(payload["content_bytes"]).hexdigest()
    )
    assert payload["storage_ref"].startswith("ae://nsl-approval-requests/")
    assert "tenant-private-a" not in payload["storage_ref"]
    assert "approval-request-s44-001" not in payload["storage_ref"]
    assert "Create the confidential" in content
    assert "snapshot://private" in content


def test_repository_round_trip_is_single_transaction_and_idempotent(
    sqlite_store,
) -> None:
    engine, repository = sqlite_store
    first = repository.persist(_request())
    replay = repository.persist(_request())

    assert replay == first
    assert first["schema_version"] == "ae_nsl_approval_request.v2"
    assert first["approval_request_hash"].startswith("sha256:")
    assert first["data_classification"] == "CONFIDENTIAL"
    assert "approval_request_bytes" not in first
    assert "_approval_request_bytes" not in first
    assert (
        repository.get(
            tenant_id="tenant-private-a",
            approval_request_id="approval-request-s44-001",
        )
        == first
    )
    assert (
        repository.load_request(
            tenant_id="tenant-private-a",
            approval_request_id="approval-request-s44-001",
        )
        == _request().to_data()
    )

    with engine.connect() as connection:
        row = (
            connection.execute(
                text(
                    "SELECT * FROM ae_nsl_approval_request "
                    "WHERE tenant_id = 'tenant-private-a'"
                )
            )
            .mappings()
            .one()
        )
    assert set(row) == {
        "tenant_id",
        "approval_request_id",
        "nsl_execution_id",
        "business_operation_id",
        "protected_request_ref",
        "approval_request_hash",
        "request_size_bytes",
        "content_type",
        "data_classification",
        "created_at",
        "approval_request_bytes",
    }
    assert bytes(row["approval_request_bytes"]) == canonical_json(
        _request().to_data()
    ).encode("utf-8")


def test_repository_missing_identity_returns_none(sqlite_store) -> None:
    _engine, repository = sqlite_store

    assert (
        repository.get(
            tenant_id="tenant-private-a",
            approval_request_id="approval-request-missing",
        )
        is None
    )
    assert (
        repository.load_request(
            tenant_id="tenant-private-a",
            approval_request_id="approval-request-missing",
        )
        is None
    )


def test_repository_rejects_changed_semantics_without_extra_row(sqlite_store) -> None:
    engine, repository = sqlite_store
    repository.persist(_request())

    with pytest.raises(ProtectedApprovalRequestError) as collision:
        repository.persist(_request(message="A different protected request"))
    assert collision.value.error_code.endswith("idempotency_conflict")
    with engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT count(*) FROM ae_nsl_approval_request")
            ).scalar_one()
            == 1
        )


@pytest.mark.parametrize(
    ("assignment", "parameters"),
    [
        ("approval_request_bytes = :value", {"value": b"tampered"}),
        ("approval_request_hash = :value", {"value": "invalid"}),
        ("request_size_bytes = :value", {"value": 1}),
        ("content_type = :value", {"value": "text/plain"}),
        ("data_classification = :value", {"value": "SECRET"}),
        ("business_operation_id = :value", {"value": "changed-operation"}),
    ],
)
def test_repository_detects_body_and_binding_corruption(
    sqlite_store, assignment: str, parameters: dict[str, object]
) -> None:
    engine, repository = sqlite_store
    repository.persist(_request())
    with engine.begin() as connection:
        connection.execute(
            text(f"UPDATE ae_nsl_approval_request SET {assignment}"), parameters
        )

    with pytest.raises(ProtectedApprovalRequestError) as corrupted:
        repository.get(
            tenant_id="tenant-private-a",
            approval_request_id="approval-request-s44-001",
        )
    assert corrupted.value.error_code.endswith("integrity_failed")


def test_repository_rejects_non_binary_database_body(sqlite_store) -> None:
    _engine, _repository = sqlite_store
    record = {
        "tenant_id": "tenant-private-a",
        "approval_request_id": "approval-request-s44-001",
        "nsl_execution_id": "nsl-execution-s44-001",
        "business_operation_id": "business-operation-s44-001",
        "protected_request_ref": "ae://nsl-approval-requests/aa/" + "a" * 64 + ".json",
        "approval_request_hash": HASH_A,
        "request_size_bytes": 10,
        "content_type": "application/json",
        "data_classification": "CONFIDENTIAL",
        "created_at": NOW,
        "approval_request_bytes": "not-bytes",
    }

    class FakeMappings:
        def first(self):
            return record

    class FakeResult:
        def mappings(self):
            return FakeMappings()

    class FakeSession:
        def execute(self, *_args, **_kwargs):
            return FakeResult()

    with pytest.raises(ProtectedApprovalRequestError) as corrupted:
        requests._load_record(
            FakeSession(),
            tenant_id="tenant-private-a",
            approval_request_id="approval-request-s44-001",
        )
    assert corrupted.value.error_code.endswith("integrity_failed")


def test_unique_reference_blocker_maps_to_retryable_database_failure(
    sqlite_store,
) -> None:
    engine, repository = sqlite_store
    record = repository.persist(_request())
    payload = build_protected_approval_request_payload(_request())
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM ae_nsl_approval_request"))
        connection.execute(
            text(
                """
                INSERT INTO ae_nsl_approval_request (
                    tenant_id, approval_request_id, nsl_execution_id,
                    business_operation_id, protected_request_ref,
                    approval_request_hash, request_size_bytes, content_type,
                    data_classification, created_at, approval_request_bytes
                ) VALUES (
                    :tenant_id, 'blocker-request', :nsl_execution_id,
                    :business_operation_id, :protected_request_ref,
                    :approval_request_hash, :request_size_bytes, :content_type,
                    :data_classification, :created_at, :approval_request_bytes
                )
                """
            ),
            {**record, "approval_request_bytes": payload["content_bytes"]},
        )
    with pytest.raises(ProtectedApprovalRequestError) as blocked:
        repository.persist(_request())
    assert blocked.value.retryable is True


@pytest.mark.parametrize(
    "approval_request",
    [
        object(),
        ApprovalRequestStub({"tenant_id": "tenant-only"}),
        _request(skill_semantic_hash="sha256:BAD"),
        _request(payload_hash="sha256:BAD"),
        _request(risk_level="R9"),
        _request(data_classification="SECRET"),
        _request(display_safe_summary=[]),
        _request(protected_payload_ref=""),
        _request(expires_at="not-time"),
        _request(expires_at="2026-10-22T04:04:05"),
        _request(message=object()),
        _request(message="x" * 4097),
    ],
)
def test_malformed_nsl_request_fails_closed(approval_request: object) -> None:
    with pytest.raises(ProtectedApprovalRequestError) as invalid:
        canonical_approval_request_data(approval_request)
    assert invalid.value.error_code == "ae.nsl_approval_request_invalid"


def test_request_serialization_failure_and_optional_fields_are_supported() -> None:
    class BrokenRequest:
        def to_data(self):
            raise RuntimeError("private detail")

    with pytest.raises(ProtectedApprovalRequestError, match="serialization"):
        canonical_approval_request_data(BrokenRequest())
    result = canonical_approval_request_data(
        _request(protected_payload_ref=None, expires_at=None)
    )
    assert result["protected_payload_ref"] is None
    assert result["expires_at"] is None


def test_payload_size_boundary_fails_closed(monkeypatch) -> None:
    monkeypatch.setattr(requests, "MAX_PROTECTED_APPROVAL_REQUEST_BYTES", 8)
    with pytest.raises(ProtectedApprovalRequestError, match="size"):
        build_protected_approval_request_payload(_request())


@pytest.mark.parametrize(
    ("payload", "approval_request_id"),
    [
        (b"\xff", "approval-request-s44-001"),
        (b"not-json", "approval-request-s44-001"),
        (b'{ "tenant_id": "invalid-spacing" }', "approval-request-s44-001"),
        (
            canonical_json(
                _request(approval_request_id="different-request").to_data()
            ).encode("utf-8"),
            "approval-request-s44-001",
        ),
    ],
)
def test_database_body_decoder_rejects_invalid_canonical_content(
    payload: bytes, approval_request_id: str
) -> None:
    with pytest.raises(ProtectedApprovalRequestError) as invalid:
        requests._decode_request(
            payload,
            approval_request_id=approval_request_id,
            digest=hashlib.sha256(payload).hexdigest(),
            size=len(payload),
        )
    assert invalid.value.error_code.endswith("integrity_failed")


def test_request_from_record_requires_private_bytes() -> None:
    with pytest.raises(ProtectedApprovalRequestError) as missing:
        requests._request_from_record({})
    assert missing.value.error_code.endswith("integrity_failed")


def test_repository_maps_database_failure() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    repository = SqlAlchemyProtectedApprovalRequestStore(sessionmaker(bind=engine))
    with pytest.raises(ProtectedApprovalRequestError) as unavailable:
        repository.persist(_request())
    assert unavailable.value.retryable is True
    with pytest.raises(ProtectedApprovalRequestError) as read_unavailable:
        repository.get(
            tenant_id="tenant-private-a",
            approval_request_id="approval-request-s44-001",
        )
    assert read_unavailable.value.retryable is True
    with pytest.raises(ProtectedApprovalRequestError) as load_unavailable:
        repository.load_request(
            tenant_id="tenant-private-a",
            approval_request_id="approval-request-s44-001",
        )
    assert load_unavailable.value.retryable is True
    engine.dispose()


def test_public_lookup_validates_bounded_identity(sqlite_store) -> None:
    _engine, repository = sqlite_store
    for tenant_id, approval_request_id in (("", "request"), ("tenant", "")):
        with pytest.raises(ProtectedApprovalRequestError):
            repository.get(
                tenant_id=tenant_id,
                approval_request_id=approval_request_id,
            )


def test_error_string_is_safe_detail() -> None:
    error = ProtectedApprovalRequestError("code", "safe detail")
    assert str(error) == "safe detail"


def test_migrations_preserve_base_and_add_fail_closed_bytea_body() -> None:
    root = Path(__file__).resolve().parents[1]
    base = (
        root / "database/nex-ae-api/migrations/2500_ae_nsl_approval_request.sql"
    ).read_text(encoding="utf-8")
    body = (
        root / "database/nex-ae-api/migrations/2501_ae_nsl_approval_request_body.sql"
    ).read_text(encoding="utf-8")
    compact_base = " ".join(base.lower().split())
    compact_body = " ".join(body.lower().split())

    assert "create table if not exists ae_nsl_approval_request" in compact_base
    assert "'2500_ae_nsl_approval_request'" in compact_base
    assert "approval_request_bytes bytea" not in compact_base
    assert "add column if not exists approval_request_bytes bytea" in compact_body
    assert "approval_request_bytes is null" in compact_body
    assert "alter column approval_request_bytes set not null" in compact_body
    assert "octet_length(approval_request_bytes) between 1 and 1048576" in compact_body
    assert "'2501_ae_nsl_approval_request_body'" in compact_body
    assert len("ae_nsl_approval_request") < 40
