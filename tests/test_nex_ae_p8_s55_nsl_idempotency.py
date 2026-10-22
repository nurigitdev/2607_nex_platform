from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Protocol

import pytest
from nex_ae_api import nsl_idempotency as idempotency_module
from nex_ae_api.nsl_idempotency import (
    NSL_IDEMPOTENCY_EVIDENCE_SCHEMA_VERSION,
    NslIdempotencyEvidenceError,
    SqlAlchemyNslIdempotencyEvidencePort,
)
from nex_ae_api.nsl_v02_public_api import NslV02PublicApiAdapter
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[1]
HASH = "sha256:" + "a" * 64
KEY = "idem:sha256:" + "b" * 64
NOW = datetime(2026, 10, 22, 12, tzinfo=UTC)


class IdempotencyDisposition(StrEnum):
    CREATED = "CREATED"
    REUSED = "REUSED"
    CONFLICT = "CONFLICT"


@dataclass(frozen=True)
class IdempotencyEvidenceRecord:
    tenant_id: str
    business_operation_id: str
    write_node_id: str
    tool_id: str
    contract_hash: str
    idempotency_key: str
    payload_hash: str
    provider_guarantee_ref: str
    retained_until: datetime


@dataclass(frozen=True)
class IdempotencyReservation:
    disposition: IdempotencyDisposition
    evidence: IdempotencyEvidenceRecord
    business_result_ref: str | None = None


class IdempotencyEvidencePort(Protocol):
    async def reserve(
        self, evidence: IdempotencyEvidenceRecord
    ) -> IdempotencyReservation: ...


def _public_api(
    *,
    record_type: object = IdempotencyEvidenceRecord,
    reservation_type: object = IdempotencyReservation,
    disposition_type: object = IdempotencyDisposition,
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
        idempotency_evidence_port=IdempotencyEvidencePort,
        idempotency_evidence_record=record_type,
        idempotency_reservation=reservation_type,
        idempotency_disposition=disposition_type,
        write_evidence_port=object,
        write_attempt_record=object,
        write_requested_receipt=object,
        write_call_request=object,
        write_execution_port=object,
        write_outcome_identity=object,
        write_result_envelope=object,
        write_committed=object,
        write_not_committed=object,
        write_commit_unknown=object,
        post_write_verification_port=object,
        verification_request=object,
        verification_observation=object,
        runtime_policy_port=object,
        write_policy_request=object,
        policy_decision=object,
        policy_effect=object,
        runtime_preflight_validator=object,
        release_admission_hash=HASH,
        api_contract_hash=HASH,
    )


def _evidence(**changes: object) -> IdempotencyEvidenceRecord:
    values: dict[str, object] = {
        "tenant_id": "tenant-p8-s55",
        "business_operation_id": "business-operation-p8-s55",
        "write_node_id": "write-voucher-draft",
        "tool_id": "FINANCE.CREATE_VOUCHER_DRAFT",
        "contract_hash": "sha256:" + "c" * 64,
        "idempotency_key": KEY,
        "payload_hash": "sha256:" + "d" * 64,
        "provider_guarantee_ref": "eos:idempotency:p8-s55",
        "retained_until": NOW + timedelta(days=30),
    }
    values.update(changes)
    return IdempotencyEvidenceRecord(**values)  # type: ignore[arg-type]


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
                CREATE TABLE ae_nsl_idem_evidence (
                    tenant_id TEXT NOT NULL,
                    business_operation_id TEXT NOT NULL,
                    write_node_id TEXT NOT NULL,
                    tool_id TEXT NOT NULL,
                    contract_hash TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    provider_guarantee_ref TEXT NOT NULL,
                    retained_until TEXT NOT NULL,
                    evidence_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, idempotency_key),
                    UNIQUE (tenant_id, business_operation_id, write_node_id)
                )
                """
            )
        )
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    yield (
        SqlAlchemyNslIdempotencyEvidencePort(
            factory,
            public_api=_public_api(),
            clock=lambda: NOW,
        ),
        engine,
        factory,
    )
    engine.dispose()


def _reserve(port, evidence: IdempotencyEvidenceRecord):
    return asyncio.run(port.reserve(evidence))


def test_port_creates_then_reuses_durable_evidence(evidence_port) -> None:
    port, _engine, _factory = evidence_port
    evidence = _evidence()

    created = _reserve(port, evidence)
    replayed = _reserve(port, evidence)
    saved = port.get(tenant_id=evidence.tenant_id, idempotency_key=KEY)

    assert created == IdempotencyReservation(IdempotencyDisposition.CREATED, evidence)
    assert replayed == IdempotencyReservation(IdempotencyDisposition.REUSED, evidence)
    assert saved is not None
    assert saved["schema_version"] == NSL_IDEMPOTENCY_EVIDENCE_SCHEMA_VERSION
    assert saved["payload_hash"] == evidence.payload_hash
    assert saved["evidence_hash"].startswith("sha256:")
    assert saved["created_at"] == NOW
    assert (
        port.get(
            tenant_id=evidence.tenant_id, idempotency_key="idem:sha256:" + "f" * 64
        )
        is None
    )


def test_same_key_with_different_payload_returns_conflict(evidence_port) -> None:
    port, engine, _factory = evidence_port
    original = _evidence()
    changed = replace(original, payload_hash="sha256:" + "e" * 64)

    assert _reserve(port, original).disposition is IdempotencyDisposition.CREATED
    conflict = _reserve(port, changed)

    assert conflict == IdempotencyReservation(IdempotencyDisposition.CONFLICT, changed)
    with engine.connect() as connection:
        row = (
            connection.execute(
                text(
                    "SELECT payload_hash, count(*) OVER () AS total "
                    "FROM ae_nsl_idem_evidence WHERE tenant_id = :tenant_id"
                ),
                {"tenant_id": original.tenant_id},
            )
            .mappings()
            .one()
        )
    assert row["payload_hash"] == original.payload_hash
    assert row["total"] == 1


def test_business_identity_cannot_bind_a_different_key(evidence_port) -> None:
    port, _engine, _factory = evidence_port
    original = _evidence()
    changed = replace(original, idempotency_key="idem:sha256:" + "e" * 64)

    _reserve(port, original)

    assert _reserve(port, changed).disposition is IdempotencyDisposition.CONFLICT


def test_key_cannot_drift_to_a_different_business_identity(evidence_port) -> None:
    port, _engine, _factory = evidence_port
    original = _evidence()
    changed = replace(original, business_operation_id="business-operation-other")

    _reserve(port, original)

    assert _reserve(port, changed).disposition is IdempotencyDisposition.CONFLICT


def test_same_key_and_payload_reuses_after_provider_evidence_refresh(
    evidence_port,
) -> None:
    port, _engine, _factory = evidence_port
    original = _evidence()
    refreshed = replace(
        original,
        provider_guarantee_ref="eos:idempotency:p8-s55-reverified",
        retained_until=original.retained_until + timedelta(days=30),
    )

    _reserve(port, original)

    assert _reserve(port, refreshed) == IdempotencyReservation(
        IdempotencyDisposition.REUSED, refreshed
    )


def test_idempotency_key_is_tenant_scoped(evidence_port) -> None:
    port, engine, _factory = evidence_port

    assert _reserve(port, _evidence()).disposition is IdempotencyDisposition.CREATED
    assert (
        _reserve(port, _evidence(tenant_id="tenant-p8-s55-other")).disposition
        is IdempotencyDisposition.CREATED
    )
    with engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT count(*) FROM ae_nsl_idem_evidence")
            ).scalar_one()
            == 2
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("tenant_id", ""),
        ("business_operation_id", ""),
        ("write_node_id", ""),
        ("tool_id", ""),
        ("contract_hash", "not-a-hash"),
        ("idempotency_key", "sha256:" + "a" * 64),
        ("payload_hash", "bad"),
        ("provider_guarantee_ref", ""),
        ("retained_until", datetime.fromisoformat("2026-10-22T12:00:00")),
        ("retained_until", datetime.fromisoformat("2026-10-22T21:00:00+09:00")),
        ("retained_until", "not-time"),
        ("retained_until", 1234),
    ],
)
def test_port_rejects_malformed_evidence(
    evidence_port, field: str, value: object
) -> None:
    port, _engine, _factory = evidence_port

    with pytest.raises(NslIdempotencyEvidenceError) as error:
        _reserve(port, replace(_evidence(), **{field: value}))

    assert error.value.error_code == "ae.nsl_idempotency_invalid"


def test_port_rejects_wrong_evidence_type(evidence_port) -> None:
    port, _engine, _factory = evidence_port

    with pytest.raises(NslIdempotencyEvidenceError) as error:
        asyncio.run(port.reserve(object()))

    assert error.value.error_code == "ae.nsl_idempotency_invalid"
    assert str(error.value) == error.value.detail


def test_constructor_requires_exact_admitted_types(evidence_port) -> None:
    _port, _engine, factory = evidence_port

    with pytest.raises(NslIdempotencyEvidenceError):
        SqlAlchemyNslIdempotencyEvidencePort(
            factory,
            public_api=object(),  # type: ignore[arg-type]
        )
    with pytest.raises(NslIdempotencyEvidenceError):
        SqlAlchemyNslIdempotencyEvidencePort(
            factory,
            public_api=_public_api(record_type=object()),
        )


def test_port_detects_persisted_evidence_tampering(evidence_port) -> None:
    port, engine, _factory = evidence_port
    evidence = _evidence()
    _reserve(port, evidence)
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE ae_nsl_idem_evidence SET tool_id = 'TAMPERED' "
                "WHERE tenant_id = :tenant_id"
            ),
            {"tenant_id": evidence.tenant_id},
        )

    with pytest.raises(NslIdempotencyEvidenceError) as error:
        port.get(tenant_id=evidence.tenant_id, idempotency_key=KEY)

    assert error.value.error_code == "ae.nsl_idempotency_integrity_failed"

    with pytest.raises(NslIdempotencyEvidenceError) as reserve_error:
        _reserve(port, evidence)
    assert reserve_error.value.error_code == "ae.nsl_idempotency_integrity_failed"


def test_port_maps_database_failures_to_retryable_safe_error(evidence_port) -> None:
    port, engine, _factory = evidence_port
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE ae_nsl_idem_evidence"))

    with pytest.raises(NslIdempotencyEvidenceError) as reserve_error:
        _reserve(port, _evidence())
    assert reserve_error.value.error_code == "ae.nsl_idempotency_store_unavailable"
    assert reserve_error.value.retryable is True

    with pytest.raises(NslIdempotencyEvidenceError) as get_error:
        port.get(tenant_id="tenant-p8-s55", idempotency_key=KEY)
    assert get_error.value.retryable is True


class MutatingReservation:
    def __init__(self, **_kwargs: object) -> None:
        self.disposition = IdempotencyDisposition.REUSED
        self.evidence = object()
        self.business_result_ref = "unexpected"


class RaisingReservation:
    def __init__(self, **_kwargs: object) -> None:
        raise ValueError("private constructor detail")


class MissingBindingReservation:
    @property
    def disposition(self):
        raise RuntimeError("private property detail")

    def __init__(self, **_kwargs: object) -> None:
        self.evidence = object()
        self.business_result_ref = None


def test_port_rejects_incompatible_nsl_reservation(evidence_port) -> None:
    _port, _engine, factory = evidence_port
    port = SqlAlchemyNslIdempotencyEvidencePort(
        factory,
        public_api=_public_api(reservation_type=MutatingReservation),
        clock=lambda: NOW,
    )

    with pytest.raises(NslIdempotencyEvidenceError) as error:
        _reserve(port, _evidence())

    assert error.value.error_code == "ae.nsl_idempotency_invalid"

    raising = SqlAlchemyNslIdempotencyEvidencePort(
        factory,
        public_api=_public_api(reservation_type=RaisingReservation),
        clock=lambda: NOW,
    )
    with pytest.raises(NslIdempotencyEvidenceError) as constructor_error:
        _reserve(raising, _evidence(tenant_id="tenant-p8-s55-raising"))
    assert "private constructor detail" not in constructor_error.value.detail

    missing = SqlAlchemyNslIdempotencyEvidencePort(
        factory,
        public_api=_public_api(reservation_type=MissingBindingReservation),
        clock=lambda: NOW,
    )
    with pytest.raises(NslIdempotencyEvidenceError) as binding_error:
        _reserve(missing, _evidence(tenant_id="tenant-p8-s55-missing"))
    assert "private property detail" not in binding_error.value.detail


def test_port_fails_closed_if_inserted_evidence_cannot_be_read(
    evidence_port, monkeypatch: pytest.MonkeyPatch
) -> None:
    port, _engine, _factory = evidence_port
    monkeypatch.setattr(idempotency_module, "_load_by_key", lambda *_args, **_kw: None)
    monkeypatch.setattr(
        idempotency_module,
        "_load_by_business_identity",
        lambda *_args, **_kw: None,
    )

    with pytest.raises(NslIdempotencyEvidenceError) as error:
        _reserve(port, _evidence())

    assert error.value.error_code == "ae.nsl_idempotency_store_unavailable"


def test_migration_defines_short_atomic_evidence_table() -> None:
    path = ROOT / "database/nex-ae-api/migrations/2506_ae_nsl_idempotency_evidence.sql"
    compact = " ".join(path.read_text(encoding="utf-8").lower().split())

    assert "create table if not exists ae_nsl_idem_evidence" in compact
    assert "primary key (tenant_id, idempotency_key)" in compact
    assert "unique (tenant_id, business_operation_id, write_node_id)" in compact
    assert "idempotency_key ~ '^idem:sha256:[0-9a-f]{64}$'" in compact
    assert "'2506_ae_nsl_idempotency_evidence'" in compact
    assert "eos" not in compact
    assert len("ae_nsl_idem_evidence") < 40
