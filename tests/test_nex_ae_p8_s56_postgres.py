from __future__ import annotations

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Barrier
from typing import Protocol
from uuid import uuid4

import pytest
from nex_ae_api.nsl_v02_public_api import NslV02PublicApiAdapter
from nex_ae_api.nsl_write_evidence import SqlAlchemyNslWriteEvidencePort
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

DATABASE_URL = os.getenv("NEX_AE_TEST_DATABASE_URL")
SMOKE_ENABLED = os.getenv("NEX_P8_S56_POSTGRES_SMOKE") == "1"
HASH = "sha256:" + "a" * 64

pytestmark = pytest.mark.skipif(
    not SMOKE_ENABLED or not DATABASE_URL,
    reason="Protected P8-S56 AE PostgreSQL smoke is disabled",
)


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
                **self.__dict__,
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


def _public_api() -> NslV02PublicApiAdapter:
    symbols = (
        [object] * 12
        + [
            WriteEvidencePort,
            WriteAttemptRecord,
            WriteRequestedReceipt,
        ]
        + [object] * 13
    )
    return NslV02PublicApiAdapter(*symbols, HASH, HASH)


def test_actual_postgres_write_evidence_is_atomic_and_restart_safe() -> None:
    assert DATABASE_URL is not None
    suffix = uuid4().hex
    tenant_id = f"tenant-p8-s56-{suffix}"
    record = WriteAttemptRecord(
        tenant_id=tenant_id,
        execution_id=f"nsl-execution-{suffix}",
        business_operation_id=f"business-operation-{suffix}",
        invocation_id=f"write-invocation-{suffix}",
        node_id="write-voucher-draft",
        tool_id="FINANCE.CREATE_VOUCHER_DRAFT",
        contract_hash="sha256:" + "c" * 64,
        approval_request_id=f"approval-request-{suffix}",
        idempotency_key="idem:sha256:" + suffix.ljust(64, "0"),
        payload_hash="sha256:" + "d" * 64,
        write_intent_hash="sha256:" + "e" * 64,
        precondition_evidence_id=f"precondition-{suffix}",
        requested_at=datetime.now(UTC),
    )
    engine = create_engine(DATABASE_URL, poolclass=NullPool)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    port = SqlAlchemyNslWriteEvidencePort(factory, public_api=_public_api())
    barrier = Barrier(8)

    def persist_once() -> WriteRequestedReceipt:
        barrier.wait(timeout=10)
        return asyncio.run(port.record_requested(record))

    try:
        with engine.connect() as connection:
            assert (
                connection.execute(
                    text(
                        "SELECT count(*) FROM schema_migrations "
                        "WHERE version = '2507_ae_nsl_write_evidence'"
                    )
                ).scalar_one()
                == 1
            )

        with ThreadPoolExecutor(max_workers=8) as executor:
            receipts = list(executor.map(lambda _index: persist_once(), range(8)))

        assert {receipt.record_hash for receipt in receipts} == {record.record_hash}
        assert {receipt.durable_ref for receipt in receipts} == {
            f"ae-postgresql:ae_nsl_write_evidence:{record.record_hash}"
        }
        assert all(receipt.durable for receipt in receipts)
        assert len({receipt.persisted_at for receipt in receipts}) == 1

        restarted = SqlAlchemyNslWriteEvidencePort(factory, public_api=_public_api())
        replay = asyncio.run(restarted.record_requested(record))
        saved = restarted.get(
            tenant_id=tenant_id,
            nsl_execution_id=record.execution_id,
            invocation_id=record.invocation_id,
        )
        assert replay == receipts[0]
        assert saved is not None
        assert saved["record_hash"] == record.record_hash
        assert saved["persisted_at"] >= saved["requested_at"]
        with engine.connect() as connection:
            row = (
                connection.execute(
                    text(
                        "SELECT count(*) AS total, min(record_hash) AS record_hash "
                        "FROM ae_nsl_write_evidence WHERE tenant_id = :tenant_id"
                    ),
                    {"tenant_id": tenant_id},
                )
                .mappings()
                .one()
            )
        assert row["total"] == 1
        assert row["record_hash"] == record.record_hash
    finally:
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM ae_nsl_write_evidence WHERE tenant_id = :tenant_id"),
                {"tenant_id": tenant_id},
            )
        engine.dispose()
