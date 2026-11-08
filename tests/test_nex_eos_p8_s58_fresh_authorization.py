from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from nex_eos import (
    EOS_BUSINESS_OPERATION_TABLE,
    EOS_IDEMPOTENCY_TABLE,
    EOS_METADATA,
    EOS_OUTBOX_TABLE,
    EOS_VOUCHER_DRAFT_TABLE,
    AccountInput,
    EosCreateVoucherDraftService,
    EosServiceCaller,
    EosVoucherAuthorizationClient,
    EosVoucherCommandError,
    NvtProjectInput,
    ProjectInput,
    SqlAlchemyEosAccountRepository,
    SqlAlchemyEosBusinessTransactionCoordinator,
    SqlAlchemyEosProjectRepository,
    SqlAlchemyEosVoucherRepository,
    voucher_payload_hash,
)
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[1]
PROJECT_ID = "82000000-0000-4000-8000-000000000001"
OPERATION_ID = "86000000-0000-4000-8000-000000000001"
NOW = datetime(2026, 10, 22, 13, tzinfo=UTC)
MUTATION_TABLES = (
    EOS_VOUCHER_DRAFT_TABLE,
    EOS_BUSINESS_OPERATION_TABLE,
    EOS_IDEMPOTENCY_TABLE,
    EOS_OUTBOX_TABLE,
)


class CurrentAuthorizationSource:
    def __init__(self) -> None:
        self.allowed = False
        self.calls: list[bool] = []

    def effective_authorization(self, *, tenant_id: str, subject_id: str):
        self.calls.append(self.allowed)
        return {
            "active": True,
            "tenant_id": tenant_id,
            "subject_id": subject_id,
            "scopes": (["finance:voucher-draft:create"] if self.allowed else []),
            "project_ids": [PROJECT_ID],
            "resource_refs": [f"voucher_draft:{OPERATION_ID}"],
            "revision_hash": ("a" if self.allowed else "b") * 64,
        }


def _factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    EOS_METADATA.create_all(engine)
    return engine, sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _seed(factory) -> None:
    projects = SqlAlchemyEosProjectRepository(factory)
    accounts = SqlAlchemyEosAccountRepository(factory)
    projects.create_nvt_project(
        NvtProjectInput(
            "tenant-a",
            "81000000-0000-4000-8000-000000000001",
            "NVT-S58",
            "NVT S58",
        )
    )
    projects.create_project(
        ProjectInput(
            "tenant-a",
            PROJECT_ID,
            "PROJECT-S58",
            "Project S58",
            nvt_project_id="81000000-0000-4000-8000-000000000001",
        )
    )
    for account_id, code, category in (
        ("83000000-0000-4000-8000-000000000001", "TRAVEL-S58", "EXPENSE"),
        ("83000000-0000-4000-8000-000000000002", "CASH-S58", "ASSET"),
    ):
        accounts.create_account(
            AccountInput(
                "tenant-a",
                account_id,
                code,
                code,
                category,
                "GENERAL",
                date(2026, 1, 1),
            )
        )


def _payload() -> dict[str, object]:
    payload = json.loads(
        (
            ROOT
            / "contracts/examples/service/eos_create_voucher_draft_command.golden_a.json"
        ).read_text(encoding="utf-8")
    )
    payload["description"] = "P8-S58 fresh EOS authorization"
    payload["payload_hash"] = voucher_payload_hash(payload)
    return payload


def _counts(factory) -> dict[str, int]:
    with factory() as session:
        return {
            table.name: session.execute(
                select(func.count()).select_from(table)
            ).scalar_one()
            for table in MUTATION_TABLES
        }


def test_current_eos_denial_overrides_upstream_allow_and_blocks_replay() -> None:
    engine, factory = _factory()
    _seed(factory)
    source = CurrentAuthorizationSource()
    identifiers = iter(
        (
            "87000000-0000-4000-8000-000000000058",
            "88000000-0000-4000-8000-000000000058",
        )
    )
    service = EosCreateVoucherDraftService(
        coordinator=SqlAlchemyEosBusinessTransactionCoordinator(
            factory,
            id_factory=lambda: next(identifiers),
            clock=lambda: NOW,
        ),
        vouchers=SqlAlchemyEosVoucherRepository(factory),
        authorizer=EosVoucherAuthorizationClient(source, clock=lambda: NOW),
        id_factory=lambda: "84000000-0000-4000-8000-000000000058",
        clock=lambda: NOW,
    )
    caller = EosServiceCaller("nex-ae-api", "nex-eos", ("service:call",))
    payload = _payload()

    # This canonical call is downstream of an admitted NSL WriteGuard ALLOW.
    with pytest.raises(EosVoucherCommandError) as denied:
        service.execute(payload, caller=caller)
    assert denied.value.error_code == "EOS_AUTHORIZATION_DENIED"
    assert denied.value.status_code == 403
    assert all(value == 0 for value in _counts(factory).values())

    source.allowed = True
    created = service.execute(payload, caller=caller)
    assert created["idempotency_disposition"] == "CREATED"
    committed_counts = _counts(factory)
    assert committed_counts == {
        "eos_voucher_draft": 1,
        "eos_business_operation": 1,
        "eos_idempotency": 1,
        "eos_outbox": 1,
    }

    source.allowed = False
    with pytest.raises(EosVoucherCommandError) as revoked_replay:
        service.execute(payload, caller=caller)
    assert revoked_replay.value.error_code == "EOS_AUTHORIZATION_DENIED"
    assert _counts(factory) == committed_counts
    assert source.calls == [False, True, False]

    with factory() as session:
        stored = session.execute(select(EOS_BUSINESS_OPERATION_TABLE)).mappings().one()
    assert stored["result_json"]["authorization_revision_hash"] == "a" * 64
    engine.dispose()
