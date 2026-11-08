from __future__ import annotations

import asyncio
import importlib.metadata
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from nex_ae_api.nsl_v02_public_api import load_nsl_v02_public_api
from nex_ae_api.nsl_write_evidence import SqlAlchemyNslWriteEvidencePort
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[1]
DATABASE_URL = os.getenv("NEX_AE_TEST_DATABASE_URL")
SMOKE_ENABLED = os.getenv("NEX_P8_S56_ACTUAL_WHEEL_SMOKE") == "1"

pytestmark = pytest.mark.skipif(
    not SMOKE_ENABLED or not DATABASE_URL,
    reason="Protected P8-S56 admitted-wheel PostgreSQL smoke is disabled",
)


def test_admitted_nsl_v02_types_round_trip_actual_postgres() -> None:
    assert DATABASE_URL is not None
    assert importlib.metadata.version("nex-skill-language") == "0.2.0"
    readiness_evidence = json.loads(
        (ROOT / "reports/deployment/p8-s04-nsl-v0.2-readiness.json").read_text(
            encoding="utf-8"
        )
    )
    public_api = load_nsl_v02_public_api(readiness_evidence["readiness"])
    suffix = uuid4().hex
    tenant_id = f"tenant-p8-s56-wheel-{suffix}"
    requested_at = datetime.now(UTC)
    record = public_api.write_attempt_record(
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
        requested_at=requested_at,
    )
    engine = create_engine(DATABASE_URL, poolclass=NullPool)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    port = SqlAlchemyNslWriteEvidencePort(factory, public_api=public_api)

    try:
        receipt = asyncio.run(port.record_requested(record))
        restarted = SqlAlchemyNslWriteEvidencePort(factory, public_api=public_api)
        replay = asyncio.run(restarted.record_requested(record))
        saved = restarted.get(
            tenant_id=tenant_id,
            nsl_execution_id=record.execution_id,
            invocation_id=record.invocation_id,
        )

        assert isinstance(receipt, public_api.write_requested_receipt)
        assert replay == receipt
        assert receipt.record_hash == record.record_hash
        assert receipt.durable is True
        assert receipt.persisted_at >= requested_at
        assert saved is not None
        assert saved["record_hash"] == record.record_hash
        with engine.connect() as connection:
            assert (
                connection.execute(
                    text(
                        "SELECT count(*) FROM ae_nsl_write_evidence "
                        "WHERE tenant_id = :tenant_id"
                    ),
                    {"tenant_id": tenant_id},
                ).scalar_one()
                == 1
            )
    finally:
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM ae_nsl_write_evidence WHERE tenant_id = :tenant_id"),
                {"tenant_id": tenant_id},
            )
        engine.dispose()
