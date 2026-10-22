from __future__ import annotations

import os
from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from nex_eos import (
    EOS_ACCOUNT_TABLE,
    EOS_BUSINESS_OPERATION_TABLE,
    EOS_IDEMPOTENCY_TABLE,
    EOS_NVT_PROJECT_TABLE,
    EOS_OUTBOX_TABLE,
    EOS_PROJECT_TABLE,
    EOS_VOUCHER_DRAFT_LINE_TABLE,
    EOS_VOUCHER_DRAFT_TABLE,
    AccountInput,
    EosCreateVoucherDraftService,
    EosVoucherAuthorizationClient,
    NvtProjectInput,
    ProjectInput,
    create_eos_app,
    voucher_payload_hash,
)
from nex_runtime import issue_mock_service_token
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url

DATABASE_URL = os.getenv("NEX_EOS_TEST_DATABASE_URL", "")
SMOKE_ENABLED = os.getenv("NEX_P8_S58_POSTGRES_SMOKE") == "1"
NOW = datetime(2026, 10, 22, 14, tzinfo=UTC)

pytestmark = pytest.mark.skipif(
    not DATABASE_URL or not SMOKE_ENABLED,
    reason="Protected P8-S58 EOS PostgreSQL smoke is disabled",
)

TENANT_TABLES = (
    EOS_VOUCHER_DRAFT_LINE_TABLE,
    EOS_VOUCHER_DRAFT_TABLE,
    EOS_OUTBOX_TABLE,
    EOS_IDEMPOTENCY_TABLE,
    EOS_BUSINESS_OPERATION_TABLE,
    EOS_ACCOUNT_TABLE,
    EOS_PROJECT_TABLE,
    EOS_NVT_PROJECT_TABLE,
)
MUTATION_TABLES = (
    EOS_VOUCHER_DRAFT_LINE_TABLE,
    EOS_VOUCHER_DRAFT_TABLE,
    EOS_OUTBOX_TABLE,
    EOS_IDEMPOTENCY_TABLE,
    EOS_BUSINESS_OPERATION_TABLE,
)


class CurrentAuthorizationSource:
    def __init__(self, *, project_id: str, operation_id: str) -> None:
        self.project_id = project_id
        self.operation_id = operation_id
        self.allowed = False
        self.calls: list[bool] = []

    def effective_authorization(self, *, tenant_id: str, subject_id: str):
        self.calls.append(self.allowed)
        return {
            "active": True,
            "tenant_id": tenant_id,
            "subject_id": subject_id,
            "scopes": (["finance:voucher-draft:create"] if self.allowed else []),
            "project_ids": [self.project_id],
            "resource_refs": [f"voucher_draft:{self.operation_id}"],
            "revision_hash": ("a" if self.allowed else "b") * 64,
        }


def _counts(runtime, tenant_id: str, tables=TENANT_TABLES) -> dict[str, int]:
    with runtime.engine.connect() as connection:
        return {
            table.name: connection.execute(
                select(func.count())
                .select_from(table)
                .where(table.c.tenant_id == tenant_id)
            ).scalar_one()
            for table in tables
        }


def _cleanup(runtime, tenant_id: str) -> None:
    with runtime.engine.begin() as connection:
        for table in TENANT_TABLES:
            connection.execute(table.delete().where(table.c.tenant_id == tenant_id))


def _payload(
    *,
    tenant_id: str,
    operation_id: str,
    project_id: str,
    debit_id: str,
    credit_id: str,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "eos_create_voucher_draft_command.v1",
        "tenant_id": tenant_id,
        "business_operation_id": operation_id,
        "idempotency_key": f"p8-s58:{operation_id}",
        "payload_hash": "sha256:" + "0" * 64,
        "requester_ref": {"type": "oa.user", "id": "employee-p8-s58"},
        "project_ref": {"type": "eos.project", "id": project_id},
        "voucher_type": "GENERAL",
        "transaction_date": "2026-10-22",
        "currency": "KRW",
        "description": "P8-S58 protected fresh authorization smoke",
        "lines": [
            {
                "line_no": 1,
                "account_ref": {"type": "eos.account", "id": debit_id},
                "signed_amount": "58000.00",
                "economic_category": "TRAVEL",
                "description": "Debit",
                "evidence_refs": ["approval-evidence-p8-s58"],
            },
            {
                "line_no": 2,
                "account_ref": {"type": "eos.account", "id": credit_id},
                "signed_amount": "-58000.00",
                "economic_category": "CASH",
                "description": "Credit",
                "evidence_refs": ["approval-evidence-p8-s58"],
            },
        ],
        "nsl_approval_request_id": "approval-request-p8-s58",
        "nsl_approval_evidence_ref": "approval-evidence-p8-s58",
        "business_approval_proof_ref": None,
        "attachments": [],
        "trace": {
            "trace_id": "trace-p8-s58",
            "correlation_id": "correlation-p8-s58",
            "causation_id": "nsl-write-p8-s58",
        },
    }
    payload["payload_hash"] = voucher_payload_hash(payload)
    return payload


def test_actual_postgres_fresh_denial_zero_mutation_and_revoked_replay() -> None:
    target = make_url(DATABASE_URL)
    assert target.username == "nex_eos_user"
    assert target.database == "nex_eos_test"

    suffix = uuid4().hex[:16]
    tenant_id = f"p8-s58-{suffix}"
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
            "NEX_VERSION": "2.1.0-p8-s58",
            "NEX_BUILD_SHA": "p8s58protected",
            "NEX_EOS_DATABASE_URL": DATABASE_URL,
            "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK",
        }
    )
    runtime = app.state.eos_database_runtime
    assert runtime is not None
    authorization = CurrentAuthorizationSource(
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
            identity = tuple(
                connection.execute(
                    text("SELECT current_database(), current_user")
                ).one()
            )
            migrations = set(
                connection.execute(
                    text("SELECT version FROM schema_migrations")
                ).scalars()
            )
        assert identity == ("nex_eos_test", "nex_eos_user")
        assert "2508_eos_operation_name_compatibility" in migrations

        app.state.eos_projects.create_nvt_project(
            NvtProjectInput(tenant_id, nvt_id, f"NVT-{suffix}", "P8 S58 NVT")
        )
        app.state.eos_projects.create_project(
            ProjectInput(
                tenant_id,
                project_id,
                f"PROJECT-{suffix}",
                "P8 S58 Project",
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

        payload = _payload(
            tenant_id=tenant_id,
            operation_id=operation_id,
            project_id=project_id,
            debit_id=debit_id,
            credit_id=credit_id,
        )
        token = issue_mock_service_token(
            service_id="nex-ae-api",
            audience="nex-eos",
        ).access_token
        headers = {
            "Authorization": f"Bearer {token}",
            "X-NeX-Tenant-Id": tenant_id,
        }
        path = "/internal/v1/finance/voucher-drafts"
        with TestClient(app) as client:
            denied = client.post(path, json=payload, headers=headers)
            assert denied.status_code == 403, denied.text
            assert denied.json()["error_code"] == "EOS_AUTHORIZATION_DENIED"
            assert all(
                count == 0
                for count in _counts(runtime, tenant_id, MUTATION_TABLES).values()
            )

            authorization.allowed = True
            created = client.post(path, json=payload, headers=headers)
            assert created.status_code == 201, created.text
            assert created.json()["idempotency_disposition"] == "CREATED"
            committed_counts = _counts(runtime, tenant_id, MUTATION_TABLES)
            assert committed_counts == {
                "eos_voucher_draft_line": 2,
                "eos_voucher_draft": 1,
                "eos_outbox": 1,
                "eos_idempotency": 1,
                "eos_business_operation": 1,
            }

            authorization.allowed = False
            revoked_replay = client.post(path, json=payload, headers=headers)
            assert revoked_replay.status_code == 403, revoked_replay.text
            assert _counts(runtime, tenant_id, MUTATION_TABLES) == committed_counts
            assert authorization.calls == [False, True, False]
    finally:
        _cleanup(runtime, tenant_id)
        assert all(value == 0 for value in _counts(runtime, tenant_id).values())
        runtime.dispose()
