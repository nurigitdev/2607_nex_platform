from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from nex_eos import (
    EOS_BUSINESS_OPERATION_TABLE,
    EOS_IDEMPOTENCY_TABLE,
    EOS_METADATA,
    EOS_OUTBOX_TABLE,
    EosBusinessOperationRequest,
    EosOutboxPublicationError,
    EosOutboxPublishReceipt,
    SqlAlchemyEosBusinessTransactionCoordinator,
    SqlAlchemyEosOutboxPublisher,
)
from nex_eos.outbox_publication import _claim_statement
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from p8_reliability_faults import (
    EosOutboxAckLossFaultError,
    EosOutboxAckLossFaultTransport,
)
from sqlalchemy import create_engine, func, select, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

NOW = datetime(2026, 10, 24, 10, 0, tzinfo=UTC)
LATER = datetime(2026, 10, 24, 10, 1, tzinfo=UTC)
OPERATION_ID = "11111111-1111-4111-8111-111111111111"
OUTBOX_ID = "22222222-2222-4222-8222-222222222222"
EVENT_ID = "33333333-3333-4333-8333-333333333333"


class _IdempotentSink:
    def __init__(self) -> None:
        self.attempts = 0
        self.events: dict[str, object] = {}

    def publish(self, event: Any) -> EosOutboxPublishReceipt:
        self.attempts += 1
        event_id = str(event.event_id)
        self.events.setdefault(event_id, event)
        return EosOutboxPublishReceipt(
            event_id=event_id,
            event_payload_hash=str(event.event_payload_hash),
            receipt_ref=f"sink:event:{event_id}",
        )


class _ReceiptSink:
    def __init__(self, receipt: object) -> None:
        self._receipt = receipt

    def publish(self, _event: object) -> object:
        return self._receipt


def _stack(*, clock=lambda: NOW):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    EOS_METADATA.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    generated = iter((OUTBOX_ID, EVENT_ID))
    coordinator = SqlAlchemyEosBusinessTransactionCoordinator(
        sessions,
        id_factory=lambda: next(generated),
        clock=lambda: NOW,
    )
    publisher = SqlAlchemyEosOutboxPublisher(sessions, clock=clock)
    return engine, sessions, coordinator, publisher


def _request(*, tenant_id: str = "tenant-s80") -> EosBusinessOperationRequest:
    return EosBusinessOperationRequest(
        tenant_id=tenant_id,
        business_operation_id=OPERATION_ID,
        idempotency_key=f"idem:{tenant_id}:voucher",
        operation="CREATE_VOUCHER_DRAFT",
        payload_hash=semantic_sha256_hash_ref({"tenant_id": tenant_id}),
        event_type="VOUCHER_DRAFT_CREATED",
    )


def _seed(coordinator: SqlAlchemyEosBusinessTransactionCoordinator) -> int:
    mutation_calls = 0

    def mutation(_session):
        nonlocal mutation_calls
        mutation_calls += 1
        return {"business_result_ref": "eos:voucher-draft:voucher-s80"}

    result = coordinator.execute(_request(), mutation)
    assert result.created is True
    return mutation_calls


def _outbox(sessions: sessionmaker) -> dict[str, Any]:
    with sessions() as session:
        return dict(session.execute(select(EOS_OUTBOX_TABLE)).mappings().one())


def test_ack_loss_retries_publication_without_repeating_business_mutation() -> None:
    _engine, sessions, coordinator, publisher = _stack(clock=lambda: LATER)
    assert _seed(coordinator) == 1
    sink = _IdempotentSink()
    fault = EosOutboxAckLossFaultTransport(sink)

    lost = publisher.publish_next(fault, tenant_id="tenant-s80")
    assert lost is not None
    assert lost.delivery_state == "PENDING"
    assert lost.attempt_count == 1
    assert lost.retry_required is True
    assert lost.receipt_ref is None
    assert lost.error_code == "EOS_OUTBOX_ACK_UNCONFIRMED"
    assert _outbox(sessions)["published_at"] is None

    published = publisher.publish_next(fault, tenant_id="tenant-s80")
    assert published is not None
    assert published.outbox_id == OUTBOX_ID
    assert published.event_id == EVENT_ID
    assert published.delivery_state == "PUBLISHED"
    assert published.attempt_count == 2
    assert published.retry_required is False
    assert published.receipt_ref == f"sink:event:{EVENT_ID}"
    assert published.error_code is None
    assert publisher.publish_next(fault, tenant_id="tenant-s80") is None

    row = _outbox(sessions)
    assert row["delivery_state"] == "PUBLISHED"
    assert row["attempt_count"] == 2
    assert row["published_at"].replace(tzinfo=UTC) == LATER
    assert fault.evidence.publication_attempts == 2
    assert fault.evidence.downstream_acceptances == 2
    assert fault.evidence.acknowledged_attempts == 1
    assert fault.evidence.unique_event_count == 1
    assert sink.attempts == 2
    assert tuple(sink.events) == (EVENT_ID,)
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(EOS_BUSINESS_OPERATION_TABLE)) == 1
        assert session.scalar(select(func.count()).select_from(EOS_IDEMPOTENCY_TABLE)) == 1


def test_ack_loss_fault_transport_fails_closed_without_contract_or_identity() -> None:
    with pytest.raises(TypeError, match="publish"):
        EosOutboxAckLossFaultTransport(object())

    fault = EosOutboxAckLossFaultTransport(_ReceiptSink(None))
    with pytest.raises(EosOutboxAckLossFaultError, match="identity"):
        fault.publish(object())
    assert fault.evidence.publication_attempts == 1
    assert fault.evidence.downstream_acceptances == 1
    assert fault.evidence.unique_event_count == 0


def test_publisher_applies_tenant_scope_and_preserves_other_pending_rows() -> None:
    _engine, sessions, first, publisher = _stack()
    _seed(first)
    generated = iter(
        (
            "44444444-4444-4444-8444-444444444444",
            "55555555-5555-4555-8555-555555555555",
        )
    )
    second = SqlAlchemyEosBusinessTransactionCoordinator(
        sessions,
        id_factory=lambda: next(generated),
        clock=lambda: NOW,
    )
    second.execute(
        EosBusinessOperationRequest(
            **{
                **_request(tenant_id="tenant-other").__dict__,
                "business_operation_id": "66666666-6666-4666-8666-666666666666",
            }
        ),
        lambda _session: {"business_result_ref": "eos:voucher-draft:other"},
    )

    result = publisher.publish_next(_IdempotentSink(), tenant_id="tenant-other")
    assert result is not None and result.delivery_state == "PUBLISHED"
    with sessions() as session:
        states = dict(
            session.execute(
                select(EOS_OUTBOX_TABLE.c.tenant_id, EOS_OUTBOX_TABLE.c.delivery_state)
            ).all()
        )
    assert states == {"tenant-s80": "PENDING", "tenant-other": "PUBLISHED"}


def test_postgres_claim_uses_skip_locked_without_changing_schema() -> None:
    engine = create_engine("postgresql+psycopg://")
    session = sessionmaker(bind=engine)()
    try:
        statement = _claim_statement(session, tenant_id="tenant-s80")
        sql = str(statement.compile(dialect=postgresql.dialect()))
    finally:
        session.close()
        engine.dispose()

    assert "FOR UPDATE SKIP LOCKED" in sql
    assert "eos_outbox.tenant_id" in sql


@pytest.mark.parametrize(
    "receipt",
    (
        None,
        EosOutboxPublishReceipt(EVENT_ID, "sha256:" + "0" * 64, "receipt"),
        EosOutboxPublishReceipt(
            "44444444-4444-4444-8444-444444444444",
            semantic_sha256_hash_ref(
                {
                    "schema_version": "1.0",
                    "tenant_id": "tenant-s80",
                    "business_operation_id": OPERATION_ID,
                    "operation": "CREATE_VOUCHER_DRAFT",
                    "business_result_ref": "eos:voucher-draft:voucher-s80",
                }
            ),
            "receipt",
        ),
        EosOutboxPublishReceipt(EVENT_ID, "not-a-hash", "receipt"),
        EosOutboxPublishReceipt(
            EVENT_ID,
            semantic_sha256_hash_ref(
                {
                    "schema_version": "1.0",
                    "tenant_id": "tenant-s80",
                    "business_operation_id": OPERATION_ID,
                    "operation": "CREATE_VOUCHER_DRAFT",
                    "business_result_ref": "eos:voucher-draft:voucher-s80",
                }
            ),
            "",
        ),
    ),
)
def test_unconfirmed_or_invalid_receipt_keeps_event_pending(receipt: object) -> None:
    _engine, sessions, coordinator, publisher = _stack()
    _seed(coordinator)

    result = publisher.publish_next(_ReceiptSink(receipt))

    assert result is not None
    assert result.delivery_state == "PENDING"
    assert result.attempt_count == 1
    assert result.retry_required is True
    assert _outbox(sessions)["delivery_state"] == "PENDING"


def test_invalid_inputs_and_drift_fail_closed_before_publication() -> None:
    engine, sessions, coordinator, publisher = _stack()
    _seed(coordinator)

    with pytest.raises(EosOutboxPublicationError) as missing_publish:
        publisher.publish_next(object())  # type: ignore[arg-type]
    assert missing_publish.value.error_code == "EOS_OUTBOX_PUBLICATION_INVALID"
    with pytest.raises(EosOutboxPublicationError):
        publisher.publish_next(_IdempotentSink(), tenant_id=" bad ")

    with engine.begin() as connection:
        connection.execute(
            update(EOS_OUTBOX_TABLE).values(event_payload_hash="sha256:" + "f" * 64)
        )
    with pytest.raises(EosOutboxPublicationError, match="drifted"):
        publisher.publish_next(_IdempotentSink())
    assert _outbox(sessions)["attempt_count"] == 0


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("outbox_id", "not-a-uuid"),
        ("tenant_id", " bad "),
        ("event_id", "not-a-uuid"),
        ("business_operation_id", "not-a-uuid"),
        ("event_type", ""),
        ("event_payload", []),
        ("attempt_count", -1),
    ),
)
def test_malformed_pending_row_is_not_published(field: str, value: object) -> None:
    engine, _sessions, coordinator, publisher = _stack()
    _seed(coordinator)
    with engine.begin() as connection:
        connection.execute(update(EOS_OUTBOX_TABLE).values({field: value}))

    with pytest.raises(EosOutboxPublicationError):
        publisher.publish_next(_IdempotentSink())


def test_clock_and_persistence_failures_are_typed() -> None:
    engine, _sessions, coordinator, publisher = _stack(
        clock=lambda: NOW.replace(tzinfo=None)
    )
    _seed(coordinator)
    with pytest.raises(EosOutboxPublicationError, match="timezone-aware"):
        publisher.publish_next(_IdempotentSink())

    engine.dispose()
    with pytest.raises(EosOutboxPublicationError) as unavailable:
        publisher.publish_next(_IdempotentSink())
    assert unavailable.value.error_code == "EOS_OUTBOX_PERSISTENCE_UNAVAILABLE"
    assert unavailable.value.retryable is True
