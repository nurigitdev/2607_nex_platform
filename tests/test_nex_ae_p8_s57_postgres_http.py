from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from datetime import UTC, date, datetime
from types import MappingProxyType
from typing import Protocol
from uuid import uuid4

import httpx
import pytest
from nex_ae_api.nsl_eos_write_execution import HttpEosWriteExecutionPort
from nex_ae_api.nsl_v02_public_api import NslV02PublicApiAdapter
from nex_eos import (
    EOS_ACCOUNT_TABLE,
    EOS_BUSINESS_OPERATION_TABLE,
    EOS_IDEMPOTENCY_TABLE,
    EOS_NVT_PROJECT_TABLE,
    EOS_OUTBOX_TABLE,
    EOS_PROJECT_TABLE,
    EOS_VOUCHER_ATTACHMENT_TABLE,
    EOS_VOUCHER_DRAFT_LINE_TABLE,
    EOS_VOUCHER_DRAFT_TABLE,
    AccountInput,
    EosCreateVoucherDraftService,
    EosVoucherAuthorizationClient,
    NvtProjectInput,
    ProjectInput,
    create_eos_app,
)
from nex_runtime import issue_mock_service_token
from nex_runtime.semantic_hashes import nsl_write_payload_hash_ref
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url

DATABASE_URL = os.getenv("NEX_EOS_TEST_DATABASE_URL", "")
SMOKE_ENABLED = os.getenv("NEX_P8_S57_POSTGRES_HTTP_SMOKE") == "1"
HASH = "sha256:" + "a" * 64
NOW = datetime(2026, 10, 22, 12, tzinfo=UTC)

pytestmark = pytest.mark.skipif(
    not DATABASE_URL or not SMOKE_ENABLED,
    reason="Protected P8-S57 EOS PostgreSQL HTTP smoke is disabled",
)

_TENANT_TABLES = (
    EOS_VOUCHER_ATTACHMENT_TABLE,
    EOS_VOUCHER_DRAFT_LINE_TABLE,
    EOS_VOUCHER_DRAFT_TABLE,
    EOS_OUTBOX_TABLE,
    EOS_IDEMPOTENCY_TABLE,
    EOS_BUSINESS_OPERATION_TABLE,
    EOS_ACCOUNT_TABLE,
    EOS_PROJECT_TABLE,
    EOS_NVT_PROJECT_TABLE,
)


@dataclass(frozen=True)
class Envelope:
    value: object


@dataclass(frozen=True)
class WriteCallRequest:
    tenant_id: str
    execution_id: str
    business_operation_id: str
    invocation_id: str
    node_id: str
    tool_ref: str
    tool_id: str
    contract_hash: str
    arguments: object
    idempotency_key: str
    payload_hash: str
    approval_id: str
    approval_request_id: str
    write_intent_hash: str
    business_preconditions: object
    trace_refs: tuple[str, ...]


class WriteExecutionPort(Protocol):
    async def execute(self, request: WriteCallRequest) -> object: ...


class AuthorizationSource:
    def __init__(self, *, project_id: str, operation_id: str) -> None:
        self.project_id = project_id
        self.operation_id = operation_id
        self.calls = 0

    def effective_authorization(self, *, tenant_id: str, subject_id: str):
        self.calls += 1
        return {
            "active": True,
            "tenant_id": tenant_id,
            "subject_id": subject_id,
            "scopes": ["finance:voucher-draft:create"],
            "project_ids": [self.project_id],
            "resource_refs": [f"voucher_draft:{self.operation_id}"],
            "revision_hash": "a" * 64,
        }


def _public_api() -> NslV02PublicApiAdapter:
    symbols = [object] * 15 + [WriteCallRequest, WriteExecutionPort] + [object] * 13
    return NslV02PublicApiAdapter(*symbols, HASH, HASH)


def _request(
    *,
    tenant_id: str,
    operation_id: str,
    project_id: str,
    debit_id: str,
    credit_id: str,
) -> WriteCallRequest:
    approval_request_id = f"approval-{tenant_id}"
    payload = {
        "schema_version": "eos_create_voucher_draft_command.v1",
        "tenant_id": tenant_id,
        "requester_ref": {"type": "oa.user", "id": "employee-p8-s57"},
        "project_ref": {"type": "eos.project", "id": project_id},
        "voucher_type": "GENERAL",
        "transaction_date": "2026-10-22",
        "currency": "KRW",
        "description_text": "P8-S57 actual PostgreSQL adapter smoke",
        "lines": [
            {
                "line_no": 1,
                "account_ref": {"type": "eos.account", "id": debit_id},
                "signed_amount": "57000.00",
                "economic_category": "TRAVEL",
                "description": "Protected smoke debit",
                "evidence_refs": ["approval-evidence-p8-s57"],
            },
            {
                "line_no": 2,
                "account_ref": {"type": "eos.account", "id": credit_id},
                "signed_amount": "-57000.00",
                "economic_category": "CASH",
                "description": "Protected smoke credit",
                "evidence_refs": ["approval-evidence-p8-s57"],
            },
        ],
        "attachments": [],
    }
    arguments = MappingProxyType(
        {name: Envelope(value) for name, value in payload.items()}
    )
    return WriteCallRequest(
        tenant_id=tenant_id,
        execution_id=f"nsl-execution-{tenant_id}",
        business_operation_id=operation_id,
        invocation_id=f"invocation-{tenant_id}",
        node_id="write-voucher-draft",
        tool_ref="urn:nex:tool:finance-create-voucher-draft:v1",
        tool_id="FINANCE.CREATE_VOUCHER_DRAFT",
        contract_hash="sha256:" + "b" * 64,
        arguments=arguments,
        idempotency_key="idem:sha256:" + uuid4().hex.ljust(64, "0"),
        payload_hash=nsl_write_payload_hash_ref(payload),
        approval_id="APPROVE_VOUCHER_DRAFT",
        approval_request_id=approval_request_id,
        write_intent_hash="sha256:" + "c" * 64,
        business_preconditions=object(),
        trace_refs=(
            f"trace_id:trace-{tenant_id}",
            f"correlation_id:correlation-{tenant_id}",
            f"causation_id:write-{tenant_id}",
        ),
    )


def _counts(runtime, tenant_id: str) -> dict[str, int]:
    with runtime.engine.connect() as connection:
        return {
            table.name: connection.execute(
                select(func.count())
                .select_from(table)
                .where(table.c.tenant_id == tenant_id)
            ).scalar_one()
            for table in _TENANT_TABLES
        }


def _cleanup(runtime, tenant_id: str) -> None:
    with runtime.engine.begin() as connection:
        for table in _TENANT_TABLES:
            connection.execute(table.delete().where(table.c.tenant_id == tenant_id))


def test_actual_eos_postgres_http_adapter_commit_replay_and_zero_residue() -> None:
    target = make_url(DATABASE_URL)
    assert target.username == "nex_eos_user"
    assert target.database == "nex_eos_test"

    suffix = uuid4().hex[:16]
    tenant_id = f"p8-s57-{suffix}"
    nvt_id = str(uuid4())
    project_id = str(uuid4())
    debit_id = str(uuid4())
    credit_id = str(uuid4())
    operation_id = str(uuid4())
    voucher_id = str(uuid4())
    environment = {
        "NEX_EOS_SERVICE_ID": "nex-eos",
        "NEX_PROFILE": "test",
        "NEX_VERSION": "2.1.0-p8-s57",
        "NEX_BUILD_SHA": "p8s57protected",
        "NEX_EOS_DATABASE_URL": DATABASE_URL,
        "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK",
    }
    app = create_eos_app(environ=environment)
    runtime = app.state.eos_database_runtime
    assert runtime is not None
    authorization = AuthorizationSource(
        project_id=project_id,
        operation_id=operation_id,
    )
    app.state.eos_voucher_command_service = EosCreateVoucherDraftService(
        coordinator=app.state.eos_business_transactions,
        vouchers=app.state.eos_vouchers,
        authorizer=EosVoucherAuthorizationClient(
            authorization,
            clock=lambda: NOW,
        ),
        id_factory=lambda: voucher_id,
        clock=lambda: NOW,
    )
    _cleanup(runtime, tenant_id)
    try:
        with runtime.engine.connect() as connection:
            current = tuple(
                connection.execute(
                    text("SELECT current_database(), current_user")
                ).one()
            )
            migrations = set(
                connection.execute(
                    text("SELECT version FROM schema_migrations")
                ).scalars()
            )
        assert current == ("nex_eos_test", "nex_eos_user")
        assert "2508_eos_operation_name_compatibility" in migrations

        app.state.eos_projects.create_nvt_project(
            NvtProjectInput(tenant_id, nvt_id, f"NVT-{suffix}", "P8 S57 NVT")
        )
        app.state.eos_projects.create_project(
            ProjectInput(
                tenant_id,
                project_id,
                f"PROJECT-{suffix}",
                "P8 S57 Project",
                nvt_project_id=nvt_id,
            )
        )
        for account_id, code, category in (
            (debit_id, f"TRAVEL-{suffix}", "EXPENSE"),
            (credit_id, f"CASH-{suffix}", "ASSET"),
        ):
            app.state.eos_accounts.create_account(
                AccountInput(
                    tenant_id,
                    account_id,
                    code,
                    code,
                    category,
                    "GENERAL",
                    date(2026, 1, 1),
                )
            )

        token = issue_mock_service_token(
            service_id="nex-ae-api",
            audience="nex-eos",
        ).access_token
        request = _request(
            tenant_id=tenant_id,
            operation_id=operation_id,
            project_id=project_id,
            debit_id=debit_id,
            credit_id=credit_id,
        )
        port = HttpEosWriteExecutionPort(
            public_api=_public_api(),
            base_url="http://nex-eos.test",
            service_token=token,
            transport=httpx.ASGITransport(app=app),
        )

        created = asyncio.run(port.execute_raw(request))
        replayed = asyncio.run(port.execute_raw(request))

        assert created.status_code == 201
        assert created.payload["idempotency_disposition"] == "CREATED"
        assert replayed.status_code == 200
        assert replayed.payload["idempotency_disposition"] == "REPLAYED"
        assert created.payload["business_operation_id"] == operation_id
        assert created.payload["payload_hash"] == request.payload_hash
        assert authorization.calls == 2
        counts = _counts(runtime, tenant_id)
        assert counts[EOS_BUSINESS_OPERATION_TABLE.name] == 1
        assert counts[EOS_IDEMPOTENCY_TABLE.name] == 1
        assert counts[EOS_VOUCHER_DRAFT_TABLE.name] == 1
        assert counts[EOS_VOUCHER_DRAFT_LINE_TABLE.name] == 2
        assert counts[EOS_OUTBOX_TABLE.name] == 1
    finally:
        _cleanup(runtime, tenant_id)
        assert all(count == 0 for count in _counts(runtime, tenant_id).values())
        runtime.dispose()
