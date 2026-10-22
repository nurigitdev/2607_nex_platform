from __future__ import annotations

import asyncio
import importlib.metadata
import json
import os
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from nex_ae_api.nsl_eos_post_write_verification import (
    HttpEosPostWriteVerificationAdapter,
)
from nex_ae_api.nsl_eos_write_execution import HttpEosWriteExecutionPort
from nex_ae_api.nsl_v02_public_api import load_nsl_v02_public_api
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
from sqlalchemy import event, func, select, text
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
DATABASE_URL = os.getenv("NEX_EOS_TEST_DATABASE_URL", "")
SMOKE_ENABLED = os.getenv("NEX_P8_S61_ACTUAL_WHEEL_POSTGRES_SMOKE") == "1"
NOW = datetime(2026, 10, 22, 13, tzinfo=UTC)

pytestmark = pytest.mark.skipif(
    not DATABASE_URL or not SMOKE_ENABLED,
    reason="Protected P8-S61 actual-wheel PostgreSQL smoke is disabled",
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


def _payload(
    *,
    tenant_id: str,
    project_id: str,
    debit_id: str,
    credit_id: str,
) -> dict[str, object]:
    return {
        "schema_version": "eos_create_voucher_draft_command.v1",
        "tenant_id": tenant_id,
        "requester_ref": {"type": "oa.user", "id": "employee-p8-s61"},
        "project_ref": {"type": "eos.project", "id": project_id},
        "voucher_type": "GENERAL",
        "transaction_date": "2026-10-22",
        "currency": "KRW",
        "description": "P8-S61 post-write verification smoke",
        "lines": [
            {
                "line_no": 1,
                "account_ref": {"type": "eos.account", "id": debit_id},
                "signed_amount": "61000.00",
                "economic_category": "TRAVEL",
                "description": "Protected smoke debit",
                "evidence_refs": ["approval-evidence-p8-s61"],
            },
            {
                "line_no": 2,
                "account_ref": {"type": "eos.account", "id": credit_id},
                "signed_amount": "-61000.00",
                "economic_category": "CASH",
                "description": "Protected smoke credit",
                "evidence_refs": ["approval-evidence-p8-s61"],
            },
        ],
        "nsl_approval_request_id": f"approval-{tenant_id}",
        "nsl_approval_evidence_ref": "approval-evidence-p8-s61",
        "business_approval_proof_ref": None,
        "attachments": [],
    }


def _write_request(
    *,
    tenant_id: str,
    operation_id: str,
    project_id: str,
    debit_id: str,
    credit_id: str,
) -> object:
    from nsl.api import (
        BusinessPreconditionEvidence,
        BusinessPreconditionMechanism,
        WriteCallRequest,
        compute_payload_hash,
    )
    from nsl.core import (
        STRING,
        ApprovalRequestId,
        BusinessOperationId,
        IdempotencyKey,
        ValueEnvelope,
    )

    payload = _payload(
        tenant_id=tenant_id,
        project_id=project_id,
        debit_id=debit_id,
        credit_id=credit_id,
    )
    arguments = {
        name: ValueEnvelope.complete(value, STRING) for name, value in payload.items()
    }
    payload_hash = compute_payload_hash(arguments)
    precondition = BusinessPreconditionEvidence(
        evidence_id=f"precondition-{tenant_id}",
        tenant_id=tenant_id,
        business_operation_id=BusinessOperationId(operation_id),
        write_node_id="write-voucher-draft",
        tool_id="FINANCE.CREATE_VOUCHER_DRAFT",
        contract_hash="sha256:" + "b" * 64,
        payload_hash=payload_hash,
        write_intent_hash="sha256:" + "d" * 64,
        mechanism=BusinessPreconditionMechanism.ETAG,
        evidence_ref=f"etag:opaque:{tenant_id}",
        observed_at=NOW,
        expires_at=NOW + timedelta(hours=1),
        provider_atomic_enforcement=True,
    )
    return WriteCallRequest(
        tenant_id=tenant_id,
        execution_id=f"nsl-execution-{tenant_id}",
        business_operation_id=BusinessOperationId(operation_id),
        invocation_id=f"invocation-{tenant_id}",
        node_id="write-voucher-draft",
        tool_ref="urn:nex:tool:finance-create-voucher-draft:v1",
        tool_id="FINANCE.CREATE_VOUCHER_DRAFT",
        contract_hash="sha256:" + "b" * 64,
        arguments=arguments,
        idempotency_key=IdempotencyKey("idem:sha256:" + uuid4().hex.ljust(64, "0")),
        payload_hash=payload_hash,
        approval_id="APPROVE_VOUCHER_DRAFT",
        approval_request_id=ApprovalRequestId(payload["nsl_approval_request_id"]),
        write_intent_hash="sha256:" + "d" * 64,
        business_preconditions=precondition,
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


def test_actual_wheel_postgres_verification_is_repeatable_and_select_only() -> None:
    from nsl.core import STRING, record_type

    assert importlib.metadata.version("nex-skill-language") == "0.2.0"
    target = make_url(DATABASE_URL)
    assert target.username == "nex_eos_user"
    assert target.database == "nex_eos_test"
    readiness = json.loads(
        (ROOT / "reports/deployment/p8-s04-nsl-v0.2-readiness.json").read_text(
            encoding="utf-8"
        )
    )["readiness"]
    public_api = load_nsl_v02_public_api(readiness)
    suffix = uuid4().hex[:16]
    tenant_id = f"p8-s61-{suffix}"
    nvt_id = str(uuid4())
    project_id = str(uuid4())
    debit_id = str(uuid4())
    credit_id = str(uuid4())
    operation_id = str(uuid4())
    voucher_id = str(uuid4())
    app = create_eos_app(
        environ={
            "NEX_EOS_SERVICE_ID": "nex-eos",
            "NEX_PROFILE": "test",
            "NEX_VERSION": "2.1.0-p8-s61",
            "NEX_BUILD_SHA": "p8s61protected",
            "NEX_EOS_DATABASE_URL": DATABASE_URL,
            "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK",
        }
    )
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
    statements: list[str] = []

    def capture(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement.strip().split(None, 1)[0].upper())

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
            NvtProjectInput(tenant_id, nvt_id, f"NVT-{suffix}", "P8 S61 NVT")
        )
        app.state.eos_projects.create_project(
            ProjectInput(
                tenant_id,
                project_id,
                f"PROJECT-{suffix}",
                "P8 S61 Project",
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
        write_request = _write_request(
            tenant_id=tenant_id,
            operation_id=operation_id,
            project_id=project_id,
            debit_id=debit_id,
            credit_id=credit_id,
        )
        transport = httpx.ASGITransport(app=app)
        write = HttpEosWriteExecutionPort(
            public_api=public_api,
            base_url="http://nex-eos.test",
            service_token=token,
            transport=transport,
        )
        write_started_at = datetime.now(UTC)
        created = asyncio.run(write.execute_raw(write_request))
        assert created.status_code == 201
        before = _counts(runtime, tenant_id)

        voucher_type = record_type("VoucherDraft", voucher_no=STRING)
        verification_request = public_api.verification_request(
            identity=public_api.write_outcome_identity.from_request(write_request),
            verification_tool_id="FINANCE.GET_VOUCHER_DRAFT",
            business_reference=f"eos.voucher_draft:{voucher_id}",
            provider_transaction_id=operation_id,
            reference_schema=voucher_type,
            consistency_hint="READ_AFTER_WRITE_STRONG",
        )
        verification = HttpEosPostWriteVerificationAdapter(
            public_api=public_api,
            base_url="http://nex-eos.test",
            service_token=token,
            transport=transport,
        )
        assert isinstance(verification, public_api.post_write_verification_port)
        event.listen(runtime.engine, "before_cursor_execute", capture)
        first = asyncio.run(verification.read(verification_request))
        second = asyncio.run(verification.read(verification_request))
        event.remove(runtime.engine, "before_cursor_execute", capture)

        assert isinstance(first, public_api.verification_observation)
        assert first == second
        assert first.request_hash == verification_request.request_hash
        assert first.business_reference == f"eos.voucher_draft:{voucher_id}"
        assert first.matched is True
        assert first.reason_code is None
        assert first.observed_at.tzinfo is UTC
        assert write_started_at <= first.observed_at <= datetime.now(UTC)
        assert first.evidence_ref.startswith(
            f"eos.voucher_verification:{operation_id}:sha256:"
        )
        assert statements and set(statements) == {"SELECT"}
        assert _counts(runtime, tenant_id) == before
        assert authorization.calls == 1
        assert before[EOS_BUSINESS_OPERATION_TABLE.name] == 1
        assert before[EOS_IDEMPOTENCY_TABLE.name] == 1
        assert before[EOS_VOUCHER_DRAFT_TABLE.name] == 1
        assert before[EOS_VOUCHER_DRAFT_LINE_TABLE.name] == 2
        assert before[EOS_OUTBOX_TABLE.name] == 1
    finally:
        if event.contains(runtime.engine, "before_cursor_execute", capture):
            event.remove(runtime.engine, "before_cursor_execute", capture)
        _cleanup(runtime, tenant_id)
        assert all(count == 0 for count in _counts(runtime, tenant_id).values())
        runtime.dispose()
