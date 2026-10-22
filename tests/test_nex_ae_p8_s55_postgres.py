from __future__ import annotations

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from threading import Barrier
from uuid import uuid4

import pytest
from nex_ae_api.nsl_idempotency import SqlAlchemyNslIdempotencyEvidencePort
from nex_ae_api.nsl_v02_public_api import NslV02PublicApiAdapter
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

DATABASE_URL = os.getenv("NEX_AE_TEST_DATABASE_URL")
SMOKE_ENABLED = os.getenv("NEX_P8_S55_POSTGRES_SMOKE") == "1"
HASH = "sha256:" + "a" * 64

pytestmark = pytest.mark.skipif(
    not SMOKE_ENABLED or not DATABASE_URL,
    reason="Protected P8-S55 AE PostgreSQL smoke is disabled",
)


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


class IdempotencyEvidencePort:
    async def reserve(
        self, evidence: IdempotencyEvidenceRecord
    ) -> IdempotencyReservation: ...


def _public_api() -> NslV02PublicApiAdapter:
    return NslV02PublicApiAdapter(
        object,
        object,
        object,
        object,
        object,
        object,
        object,
        object,
        IdempotencyEvidencePort,
        IdempotencyEvidenceRecord,
        IdempotencyReservation,
        IdempotencyDisposition,
        object,
        object,
        object,
        object,
        object,
        object,
        object,
        HASH,
        HASH,
    )


def test_actual_postgres_reservation_is_atomic_restart_safe_and_conflict_safe() -> None:
    assert DATABASE_URL is not None
    suffix = uuid4().hex
    tenant_id = f"tenant-p8-s55-{suffix}"
    key = "idem:sha256:" + suffix.ljust(64, "0")
    evidence = IdempotencyEvidenceRecord(
        tenant_id=tenant_id,
        business_operation_id=f"business-operation-{suffix}",
        write_node_id="write-voucher-draft",
        tool_id="FINANCE.CREATE_VOUCHER_DRAFT",
        contract_hash="sha256:" + "c" * 64,
        idempotency_key=key,
        payload_hash="sha256:" + "d" * 64,
        provider_guarantee_ref="eos:idempotency:p8-s55-postgres",
        retained_until=datetime.now(UTC) + timedelta(days=30),
    )
    engine = create_engine(DATABASE_URL, poolclass=NullPool)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    port = SqlAlchemyNslIdempotencyEvidencePort(
        factory,
        public_api=_public_api(),
    )
    barrier = Barrier(8)

    def reserve_once() -> IdempotencyReservation:
        barrier.wait(timeout=10)
        return asyncio.run(port.reserve(evidence))

    try:
        with engine.connect() as connection:
            assert connection.execute(
                text(
                    "SELECT count(*) FROM schema_migrations "
                    "WHERE version = '2506_ae_nsl_idempotency_evidence'"
                )
            ).scalar_one() == 1

        with ThreadPoolExecutor(max_workers=8) as executor:
            reservations = list(executor.map(lambda _index: reserve_once(), range(8)))

        dispositions = [reservation.disposition for reservation in reservations]
        assert dispositions.count(IdempotencyDisposition.CREATED) == 1
        assert dispositions.count(IdempotencyDisposition.REUSED) == 7

        restarted_port = SqlAlchemyNslIdempotencyEvidencePort(
            factory,
            public_api=_public_api(),
        )
        replay = asyncio.run(restarted_port.reserve(evidence))
        conflict = asyncio.run(
            restarted_port.reserve(
                replace(evidence, payload_hash="sha256:" + "e" * 64)
            )
        )
        saved = restarted_port.get(tenant_id=tenant_id, idempotency_key=key)

        assert replay.disposition is IdempotencyDisposition.REUSED
        assert conflict.disposition is IdempotencyDisposition.CONFLICT
        assert saved is not None
        assert saved["payload_hash"] == evidence.payload_hash
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT count(*) AS total, min(payload_hash) AS payload_hash "
                    "FROM ae_nsl_idem_evidence WHERE tenant_id = :tenant_id"
                ),
                {"tenant_id": tenant_id},
            ).mappings().one()
        assert row["total"] == 1
        assert row["payload_hash"] == evidence.payload_hash
    finally:
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM ae_nsl_idem_evidence WHERE tenant_id = :tenant_id"),
                {"tenant_id": tenant_id},
            )
        engine.dispose()
