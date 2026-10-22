from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

import pytest
from nex_ae_api.nsl_v02_public_api import NslV02PublicApiAdapter
from nex_ae_api.nsl_write_evidence import (
    NSL_WRITE_EVIDENCE_SCHEMA_VERSION,
    NslWriteEvidenceError,
    SqlAlchemyNslWriteEvidencePort,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[1]
HASH = "sha256:" + "a" * 64
KEY = "idem:sha256:" + "b" * 64
NOW = datetime(2026, 10, 22, 13, tzinfo=UTC)


@dataclass(frozen=True)
class WriteAttemptRecord:
    tenant_id: str
    execution_id: str
    business_operation_id: str
    invocation_id: str
    node_id: str
    tool_id: str
    contract_hash: str
    approval_request_id: str
    idempotency_key: str
    payload_hash: str
    write_intent_hash: str
    precondition_evidence_id: str
    requested_at: datetime

    @property
    def record_hash(self) -> str:
        return semantic_sha256_hash_ref(
            {
                "tenant_id": self.tenant_id,
                "execution_id": self.execution_id,
                "business_operation_id": self.business_operation_id,
                "invocation_id": self.invocation_id,
                "node_id": self.node_id,
                "tool_id": self.tool_id,
                "contract_hash": self.contract_hash,
                "approval_request_id": self.approval_request_id,
                "idempotency_key": self.idempotency_key,
                "payload_hash": self.payload_hash,
                "write_intent_hash": self.write_intent_hash,
                "precondition_evidence_id": self.precondition_evidence_id,
                "requested_at": self.requested_at.isoformat(),
            }
        )


@dataclass(frozen=True)
class WriteRequestedReceipt:
    record_hash: str
    durable_ref: str
    persisted_at: datetime
    durable: bool


class WriteEvidencePort(Protocol):
    async def record_requested(
        self, record: WriteAttemptRecord
    ) -> WriteRequestedReceipt: ...


def _public_api(
    *,
    port_type: object = WriteEvidencePort,
    record_type: object = WriteAttemptRecord,
    receipt_type: object = WriteRequestedReceipt,
) -> NslV02PublicApiAdapter:
    return NslV02PublicApiAdapter(
        approval_request=object,
        approval_evidence=object,
        approval_suspension_coordinator=object,
        approval_resume_coordinator=object,
        resume_token=object,
        checkpoint_port=object,
        resume_checkpoint_port=object,
        idempotency_coordinator=object,
        idempotency_evidence_port=object,
        idempotency_evidence_record=object,
        idempotency_reservation=object,
        idempotency_disposition=object,
        write_evidence_port=port_type,
        write_attempt_record=record_type,
        write_requested_receipt=receipt_type,
        write_call_request=object,
        write_execution_port=object,
        post_write_verification_port=object,
        runtime_policy_port=object,
        write_policy_request=object,
        policy_decision=object,
        policy_effect=object,
        runtime_preflight_validator=object,
        release_admission_hash=HASH,
        api_contract_hash=HASH,
    )


def _record(**changes: object) -> WriteAttemptRecord:
    values: dict[str, object] = {
        "tenant_id": "tenant-p8-s56",
        "execution_id": "nsl-execution-p8-s56",
        "business_operation_id": "business-operation-p8-s56",
        "invocation_id": "write-invocation-p8-s56",
        "node_id": "write-voucher-draft",
        "tool_id": "FINANCE.CREATE_VOUCHER_DRAFT",
        "contract_hash": "sha256:" + "c" * 64,
        "approval_request_id": "approval-request-p8-s56",
        "idempotency_key": KEY,
        "payload_hash": "sha256:" + "d" * 64,
        "write_intent_hash": "sha256:" + "e" * 64,
        "precondition_evidence_id": "precondition-p8-s56",
        "requested_at": NOW,
    }
    values.update(changes)
    return WriteAttemptRecord(**values)  # type: ignore[arg-type]


@pytest.fixture
def evidence_port():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE ae_nsl_write_evidence (
                    tenant_id TEXT NOT NULL,
                    nsl_execution_id TEXT NOT NULL,
                    business_operation_id TEXT NOT NULL,
                    invocation_id TEXT NOT NULL,
                    write_node_id TEXT NOT NULL,
                    tool_id TEXT NOT NULL,
                    contract_hash TEXT NOT NULL,
                    approval_request_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    write_intent_hash TEXT NOT NULL,
                    precondition_evidence_id TEXT NOT NULL,
                    requested_at TEXT NOT NULL,
                    record_hash TEXT NOT NULL,
                    persisted_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, nsl_execution_id, invocation_id),
                    UNIQUE (tenant_id, record_hash)
                )
                """
            )
        )
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield (
        SqlAlchemyNslWriteEvidencePort(
            factory,
            public_api=_public_api(),
            clock=lambda: NOW + timedelta(seconds=1),
        ),
        engine,
        factory,
    )
    engine.dispose()


def _persist(port, record: WriteAttemptRecord):
    return asyncio.run(port.record_requested(record))


def test_port_persists_then_reuses_exact_write_requested_evidence(
    evidence_port,
) -> None:
    port, engine, _factory = evidence_port
    record = _record()

    first = _persist(port, record)
    replay = _persist(port, record)
    saved = port.get(
        tenant_id=record.tenant_id,
        nsl_execution_id=record.execution_id,
        invocation_id=record.invocation_id,
    )

    assert (
        first
        == replay
        == WriteRequestedReceipt(
            record_hash=record.record_hash,
            durable_ref=f"ae-postgresql:ae_nsl_write_evidence:{record.record_hash}",
            persisted_at=NOW + timedelta(seconds=1),
            durable=True,
        )
    )
    assert saved is not None
    assert saved["schema_version"] == NSL_WRITE_EVIDENCE_SCHEMA_VERSION
    assert saved["business_operation_id"] == record.business_operation_id
    assert saved["write_node_id"] == record.node_id
    assert saved["approval_request_id"] == record.approval_request_id
    assert saved["record_hash"] == record.record_hash
    with engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT count(*) FROM ae_nsl_write_evidence")
            ).scalar_one()
            == 1
        )
    assert (
        port.get(
            tenant_id=record.tenant_id,
            nsl_execution_id=record.execution_id,
            invocation_id="missing",
        )
        is None
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("business_operation_id", "different-operation"),
        ("node_id", "different-node"),
        ("idempotency_key", "idem:sha256:" + "f" * 64),
        ("payload_hash", "sha256:" + "f" * 64),
        ("write_intent_hash", "sha256:" + "f" * 64),
        ("approval_request_id", "different-approval"),
        ("requested_at", NOW + timedelta(milliseconds=1)),
    ],
)
def test_existing_write_attempt_identity_rejects_semantic_drift(
    evidence_port, field: str, value: object
) -> None:
    port, _engine, _factory = evidence_port
    record = _record()
    _persist(port, record)

    with pytest.raises(NslWriteEvidenceError) as error:
        _persist(port, replace(record, **{field: value}))

    assert error.value.error_code == "ae.nsl_write_evidence_conflict"


def test_distinct_invocation_can_reference_same_idempotency_identity(
    evidence_port,
) -> None:
    port, engine, _factory = evidence_port
    _persist(port, _record())
    second = _record(
        invocation_id="write-invocation-retry",
        requested_at=NOW + timedelta(milliseconds=500),
    )

    receipt = _persist(port, second)

    assert receipt.record_hash == second.record_hash
    with engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT count(*) FROM ae_nsl_write_evidence")
            ).scalar_one()
            == 2
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("tenant_id", ""),
        ("execution_id", ""),
        ("business_operation_id", ""),
        ("invocation_id", ""),
        ("node_id", ""),
        ("tool_id", ""),
        ("contract_hash", "bad"),
        ("approval_request_id", ""),
        ("idempotency_key", "sha256:" + "a" * 64),
        ("payload_hash", "bad"),
        ("write_intent_hash", "bad"),
        ("precondition_evidence_id", ""),
        ("requested_at", NOW.replace(tzinfo=None)),
        ("requested_at", datetime.fromisoformat("2026-10-22T22:00:00+09:00")),
        ("requested_at", "not-time"),
        ("requested_at", 1234),
    ],
)
def test_port_rejects_malformed_write_attempt(
    evidence_port, field: str, value: object
) -> None:
    port, _engine, _factory = evidence_port

    with pytest.raises(NslWriteEvidenceError) as error:
        _persist(port, replace(_record(), **{field: value}))

    assert error.value.error_code == "ae.nsl_write_evidence_invalid"


def test_port_rejects_wrong_record_and_constructor_types(evidence_port) -> None:
    port, _engine, factory = evidence_port

    with pytest.raises(NslWriteEvidenceError) as wrong_record:
        asyncio.run(port.record_requested(object()))
    assert wrong_record.value.error_code == "ae.nsl_write_evidence_invalid"
    assert str(wrong_record.value) == wrong_record.value.detail

    with pytest.raises(NslWriteEvidenceError):
        SqlAlchemyNslWriteEvidencePort(
            factory,
            public_api=object(),  # type: ignore[arg-type]
        )
    for field in (
        "port_type",
        "record_type",
        "receipt_type",
    ):
        with pytest.raises(NslWriteEvidenceError):
            SqlAlchemyNslWriteEvidencePort(
                factory,
                public_api=_public_api(**{field: object()}),
            )


def test_port_rejects_future_request_relative_to_durable_clock(evidence_port) -> None:
    _port, _engine, factory = evidence_port
    port = SqlAlchemyNslWriteEvidencePort(
        factory,
        public_api=_public_api(),
        clock=lambda: NOW - timedelta(seconds=1),
    )

    with pytest.raises(NslWriteEvidenceError) as error:
        _persist(port, _record())

    assert error.value.error_code == "ae.nsl_write_evidence_invalid"


def test_port_detects_record_and_timestamp_tampering(evidence_port) -> None:
    port, engine, _factory = evidence_port
    record = _record()
    _persist(port, record)
    identity = {
        "tenant_id": record.tenant_id,
        "nsl_execution_id": record.execution_id,
        "invocation_id": record.invocation_id,
    }
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE ae_nsl_write_evidence SET tool_id = 'TAMPERED' "
                "WHERE tenant_id = :tenant_id "
                "AND nsl_execution_id = :nsl_execution_id "
                "AND invocation_id = :invocation_id"
            ),
            identity,
        )
    with pytest.raises(NslWriteEvidenceError) as record_error:
        port.get(**identity)
    assert record_error.value.error_code == "ae.nsl_write_evidence_integrity_failed"

    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE ae_nsl_write_evidence "
                "SET tool_id = :tool_id, persisted_at = :persisted_at "
                "WHERE tenant_id = :tenant_id "
                "AND nsl_execution_id = :nsl_execution_id "
                "AND invocation_id = :invocation_id"
            ),
            {
                **identity,
                "tool_id": record.tool_id,
                "persisted_at": NOW - timedelta(seconds=1),
            },
        )
    with pytest.raises(NslWriteEvidenceError) as time_error:
        port.get(**identity)
    assert time_error.value.error_code == "ae.nsl_write_evidence_integrity_failed"


def test_port_maps_database_failures_to_retryable_safe_error(evidence_port) -> None:
    port, engine, _factory = evidence_port
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE ae_nsl_write_evidence"))

    with pytest.raises(NslWriteEvidenceError) as write_error:
        _persist(port, _record())
    assert write_error.value.error_code == "ae.nsl_write_evidence_store_unavailable"
    assert write_error.value.retryable is True

    with pytest.raises(NslWriteEvidenceError) as read_error:
        port.get(
            tenant_id="tenant-p8-s56",
            nsl_execution_id="execution",
            invocation_id="invocation",
        )
    assert read_error.value.retryable is True


class MutatingReceipt:
    def __init__(self, **_kwargs: object) -> None:
        self.record_hash = HASH
        self.durable_ref = "changed"
        self.persisted_at = NOW
        self.durable = False


class RaisingReceipt:
    def __init__(self, **_kwargs: object) -> None:
        raise ValueError("private constructor detail")


class MissingBindingReceipt:
    record_hash = HASH
    durable_ref = "changed"
    persisted_at = NOW

    @property
    def durable(self):
        raise RuntimeError("private property detail")


@pytest.mark.parametrize(
    "receipt_type", [MutatingReceipt, RaisingReceipt, MissingBindingReceipt]
)
def test_port_rejects_incompatible_nsl_receipt(
    evidence_port, receipt_type: type
) -> None:
    _port, _engine, factory = evidence_port
    port = SqlAlchemyNslWriteEvidencePort(
        factory,
        public_api=_public_api(receipt_type=receipt_type),
        clock=lambda: NOW + timedelta(seconds=1),
    )

    with pytest.raises(NslWriteEvidenceError) as error:
        _persist(port, _record(invocation_id=f"invocation-{receipt_type.__name__}"))

    assert error.value.error_code == "ae.nsl_write_evidence_invalid"
    assert "private" not in error.value.detail


class BrokenRecordHash(WriteAttemptRecord):
    @property
    def record_hash(self) -> str:
        raise RuntimeError("private hash detail")


class ReconstructionFailureRecord(WriteAttemptRecord):
    reject_construction = False

    def __init__(self, **values: object) -> None:
        if type(self).reject_construction:
            raise ValueError("private reconstruction detail")
        super().__init__(**values)  # type: ignore[arg-type]


def test_port_rejects_unavailable_record_hash(evidence_port) -> None:
    _port, _engine, factory = evidence_port
    port = SqlAlchemyNslWriteEvidencePort(
        factory,
        public_api=_public_api(record_type=BrokenRecordHash),
        clock=lambda: NOW,
    )
    record = BrokenRecordHash(**_record().__dict__)

    with pytest.raises(NslWriteEvidenceError) as error:
        asyncio.run(port.record_requested(record))

    assert error.value.error_code == "ae.nsl_write_evidence_invalid"
    assert "private" not in error.value.detail


def test_port_fails_closed_when_saved_record_cannot_be_reconstructed(
    evidence_port,
) -> None:
    _port, _engine, factory = evidence_port
    record = ReconstructionFailureRecord(**_record().__dict__)
    port = SqlAlchemyNslWriteEvidencePort(
        factory,
        public_api=_public_api(record_type=ReconstructionFailureRecord),
        clock=lambda: NOW + timedelta(seconds=1),
    )
    ReconstructionFailureRecord.reject_construction = True
    try:
        with pytest.raises(NslWriteEvidenceError) as error:
            asyncio.run(port.record_requested(record))
    finally:
        ReconstructionFailureRecord.reject_construction = False

    assert error.value.error_code == "ae.nsl_write_evidence_integrity_failed"
    assert "private" not in error.value.detail


def test_port_fails_closed_if_inserted_record_cannot_be_read(
    evidence_port, monkeypatch: pytest.MonkeyPatch
) -> None:
    port, _engine, _factory = evidence_port
    monkeypatch.setattr(port, "_load", lambda *_args, **_kwargs: None)

    with pytest.raises(NslWriteEvidenceError) as error:
        _persist(port, _record())

    assert error.value.error_code == "ae.nsl_write_evidence_store_unavailable"


def test_get_validates_identity_before_database_access(evidence_port) -> None:
    port, _engine, _factory = evidence_port

    with pytest.raises(NslWriteEvidenceError) as error:
        port.get(tenant_id="", nsl_execution_id="execution", invocation_id="call")

    assert error.value.error_code == "ae.nsl_write_evidence_invalid"


def test_migration_defines_short_append_only_write_evidence_table() -> None:
    path = ROOT / "database/nex-ae-api/migrations/2507_ae_nsl_write_evidence.sql"
    compact = " ".join(path.read_text(encoding="utf-8").lower().split())

    assert "create table if not exists ae_nsl_write_evidence" in compact
    assert "primary key (tenant_id, nsl_execution_id, invocation_id)" in compact
    assert "unique (tenant_id, record_hash)" in compact
    assert "check (persisted_at >= requested_at)" in compact
    assert "'2507_ae_nsl_write_evidence'" in compact
    assert "delete" not in compact
    assert len("ae_nsl_write_evidence") < 40
