from __future__ import annotations

import copy
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from nex_ae_api.nsl_approval_requests import (
    ProtectedApprovalRequestError,
    SqlAlchemyProtectedApprovalRequestStore,
)
from nex_runtime.semantic_hashes import canonical_json
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

SMOKE_ENABLED = os.getenv("NEX_AE_P8_S44A_POSTGRES_SMOKE") == "1"
DATABASE_URL = os.getenv("NEX_AE_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not SMOKE_ENABLED or not DATABASE_URL,
    reason="Protected P8-S44A PostgreSQL smoke is disabled",
)


@dataclass(frozen=True)
class ApprovalRequestStub:
    data: dict[str, object]

    def to_data(self) -> dict[str, object]:
        return copy.deepcopy(self.data)


def _request(suffix: str, **changes: object) -> ApprovalRequestStub:
    data: dict[str, object] = {
        "tenant_id": f"tenant-p8-s44a-{suffix}",
        "execution_id": f"nsl-execution-{suffix}",
        "business_operation_id": f"business-operation-{suffix}",
        "approval_id": "APPROVE_VOUCHER_DRAFT",
        "approval_request_id": f"approval-request-{suffix}",
        "skill_id": "FINANCE.CREATE_VOUCHER_DRAFT",
        "skill_version": "0.2.0",
        "skill_semantic_hash": "sha256:" + "a" * 64,
        "write_node_id": "write-voucher-draft",
        "tool_id": "finance.create_voucher_draft",
        "payload_hash": "sha256:" + "b" * 64,
        "write_intent_hash": f"write-intent-{suffix}",
        "risk_level": "R3",
        "message": "Protected PostgreSQL BYTEA smoke request",
        "expires_at": "2026-10-22T12:00:00+00:00",
        "display_safe_summary": {"line_count": 2},
        "protected_payload_ref": f"snapshot://private/{suffix}",
        "data_classification": "CONFIDENTIAL",
    }
    data.update(changes)
    return ApprovalRequestStub(data)


def test_actual_postgres_persists_and_reloads_exact_canonical_bytea() -> None:
    assert DATABASE_URL is not None
    suffix = uuid4().hex
    request = _request(suffix)
    tenant_id = str(request.data["tenant_id"])
    approval_request_id = str(request.data["approval_request_id"])
    engine = create_engine(DATABASE_URL, poolclass=NullPool)
    repository = SqlAlchemyProtectedApprovalRequestStore(
        sessionmaker(bind=engine, expire_on_commit=False),
        clock=lambda: datetime(2026, 10, 22, 4, 0, tzinfo=UTC),
    )
    try:
        with engine.begin() as connection:
            migrations = {
                str(value)
                for value in connection.execute(
                    text(
                        "SELECT version FROM schema_migrations "
                        "WHERE version IN ("
                        "'2500_ae_nsl_approval_request', "
                        "'2501_ae_nsl_approval_request_body')"
                    )
                ).scalars()
            }
            columns = {
                str(row[0]): str(row[1])
                for row in connection.execute(
                    text(
                        "SELECT column_name, data_type "
                        "FROM information_schema.columns "
                        "WHERE table_schema = current_schema() "
                        "AND table_name = 'ae_nsl_approval_request'"
                    )
                )
            }
        assert migrations == {
            "2500_ae_nsl_approval_request",
            "2501_ae_nsl_approval_request_body",
        }
        assert set(columns) == {
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
        assert columns["approval_request_bytes"] == "bytea"

        first = repository.persist(request)
        replay = repository.persist(request)
        assert replay == first
        assert "approval_request_bytes" not in first
        assert (
            repository.load_request(
                tenant_id=tenant_id,
                approval_request_id=approval_request_id,
            )
            == request.to_data()
        )
        assert "tenant-p8-s44a" not in first["protected_request_ref"]
        assert approval_request_id not in first["protected_request_ref"]
        assert suffix not in first["protected_request_ref"]

        with engine.connect() as connection:
            persisted = (
                connection.execute(
                    text(
                        "SELECT approval_request_bytes, request_size_bytes "
                        "FROM ae_nsl_approval_request "
                        "WHERE tenant_id = :tenant_id "
                        "AND approval_request_id = :approval_request_id"
                    ),
                    {
                        "tenant_id": tenant_id,
                        "approval_request_id": approval_request_id,
                    },
                )
                .mappings()
                .one()
            )
        expected = canonical_json(request.to_data()).encode("utf-8")
        assert bytes(persisted["approval_request_bytes"]) == expected
        assert persisted["request_size_bytes"] == len(expected)

        with pytest.raises(ProtectedApprovalRequestError) as conflict:
            repository.persist(_request(suffix, message="Changed protected semantics"))
        assert conflict.value.error_code.endswith("idempotency_conflict")

        with engine.connect() as connection:
            count = connection.execute(
                text(
                    "SELECT count(*) FROM ae_nsl_approval_request "
                    "WHERE tenant_id = :tenant_id"
                ),
                {"tenant_id": tenant_id},
            ).scalar_one()
        assert count == 1
    finally:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "DELETE FROM ae_nsl_approval_request WHERE tenant_id = :tenant_id"
                ),
                {"tenant_id": tenant_id},
            )
        engine.dispose()
