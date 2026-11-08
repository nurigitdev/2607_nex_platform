from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest
from nex_ae_api.delegated_work import (
    DelegatedWorkError,
    SqlAlchemyWaitRegistrationRepository,
    deterministic_nsl_approval_wait_id,
)
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool, StaticPool

DATABASE_URL = os.getenv("NEX_AE_TEST_DATABASE_URL")
POSTGRES_SMOKE = os.getenv("NEX_AE_P8_S46_POSTGRES_SMOKE") == "1"
NOW = "2026-10-22T11:00:00Z"


@pytest.fixture
def repository():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE ae_wait_registration (
                    wait_id TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    agent_execution_id TEXT NOT NULL,
                    executable_step_id TEXT NOT NULL,
                    wait_type TEXT NOT NULL,
                    external_ref TEXT NOT NULL,
                    result_contract_ref TEXT NOT NULL,
                    state TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    satisfied_at TEXT,
                    nsl_execution_id TEXT,
                    business_operation_id TEXT,
                    approval_request_id TEXT,
                    checkpoint_version INTEGER,
                    PRIMARY KEY (tenant_id, wait_id),
                    UNIQUE (
                        tenant_id, agent_execution_id,
                        executable_step_id, wait_type
                    )
                )
                """
            )
        )
    value = SqlAlchemyWaitRegistrationRepository(
        sessionmaker(bind=engine, expire_on_commit=False)
    )
    yield value
    engine.dispose()


def _binding(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "wait_id": "11111111-1111-4111-8111-111111111146",
        "tenant_id": "tenant-p8-s46",
        "agent_execution_id": "22222222-2222-4222-8222-222222222246",
        "executable_step_id": "33333333-3333-4333-8333-333333333346",
        "external_ref": "approval-request-p8-s46",
        "result_contract_ref": "urn:nex:approval-resume:p8:v1",
        "created_at": NOW,
        "wait_type": "NSL_APPROVAL",
        "nsl_execution_id": "nsl-execution-p8-s46",
        "business_operation_id": "business-operation-p8-s46",
        "approval_request_id": "approval-request-p8-s46",
        "checkpoint_version": 3,
    }
    value.update(changes)
    return value


def test_registers_exact_nsl_approval_lineage_idempotently(repository) -> None:
    first = repository.register(**_binding())
    replay = repository.register(**_binding(created_at="2026-10-22T11:05:00Z"))

    assert replay == first
    assert first["nsl_execution_id"] == "nsl-execution-p8-s46"
    assert first["business_operation_id"] == "business-operation-p8-s46"
    assert first["approval_request_id"] == first["external_ref"]
    assert first["checkpoint_version"] == 3


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"nsl_execution_id": None}, "nsl_execution_id"),
        ({"business_operation_id": None}, "business_operation_id"),
        ({"approval_request_id": None}, "approval_request_id"),
        ({"checkpoint_version": 0}, "positive integer"),
        ({"checkpoint_version": True}, "positive integer"),
        ({"external_ref": "different-request"}, "must equal"),
    ],
)
def test_nsl_approval_lineage_fails_closed(
    repository, changes: dict[str, object], message: str
) -> None:
    with pytest.raises(DelegatedWorkError, match=message) as invalid:
        repository.register(**_binding(**changes))
    assert invalid.value.error_code == "ae.delegate_work_invalid"


def test_work_result_rejects_nsl_lineage(repository) -> None:
    with pytest.raises(DelegatedWorkError, match="must not carry"):
        repository.register(
            **_binding(
                wait_type="WORK_RESULT",
                external_ref="44444444-4444-4444-8444-444444444446",
            )
        )


def test_changed_checkpoint_conflicts_with_immutable_wait(repository) -> None:
    repository.register(**_binding())
    with pytest.raises(DelegatedWorkError) as conflict:
        repository.register(**_binding(checkpoint_version=4))
    assert conflict.value.error_code == "ae.wait_registration_immutable_conflict"


def test_deterministic_approval_wait_id_binds_request_and_checkpoint() -> None:
    args = {
        "tenant_id": "tenant-p8-s46",
        "agent_execution_id": "22222222-2222-4222-8222-222222222246",
        "executable_step_id": "33333333-3333-4333-8333-333333333346",
        "approval_request_id": "approval-request-p8-s46",
        "checkpoint_version": 3,
    }
    first = deterministic_nsl_approval_wait_id(**args)
    assert first == deterministic_nsl_approval_wait_id(**args)
    assert first != deterministic_nsl_approval_wait_id(
        **{**args, "checkpoint_version": 4}
    )


def test_s46_migration_binds_protected_request_lineage() -> None:
    migration = (
        Path(__file__).resolve().parents[1]
        / "database/nex-ae-api/migrations/2503_ae_nsl_approval_wait_binding.sql"
    ).read_text(encoding="utf-8")
    compact = " ".join(migration.lower().split())

    for column in (
        "nsl_execution_id text null",
        "business_operation_id text null",
        "approval_request_id text null",
        "checkpoint_version integer null",
    ):
        assert column in compact
    assert "external_ref = approval_request_id" in compact
    assert "checkpoint_version >= 1" in compact
    assert "references ae_nsl_approval_request" in compact
    assert "'2503_ae_nsl_approval_wait_binding'" in compact
    assert "create table" not in compact


@pytest.mark.skipif(
    not POSTGRES_SMOKE or not DATABASE_URL,
    reason="Protected P8-S46 PostgreSQL smoke is disabled",
)
def test_actual_postgres_persists_exact_nsl_approval_wait_binding() -> None:
    assert DATABASE_URL is not None
    suffix = uuid4().hex
    tenant_id = f"tenant-p8-s46-{suffix}"
    agent_id = str(uuid4())
    execution_id = str(uuid4())
    step_id = str(uuid4())
    request_id = f"approval-request-{suffix}"
    nsl_execution_id = f"nsl-execution-{suffix}"
    business_operation_id = f"business-operation-{suffix}"
    engine = create_engine(DATABASE_URL, poolclass=NullPool)
    repository = SqlAlchemyWaitRegistrationRepository(
        sessionmaker(bind=engine, expire_on_commit=False)
    )
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO ae_agent_identity ("
                    "tenant_id, agent_id, agent_type, profile_ref, status"
                    ") VALUES (:tenant_id, :agent_id, 'IA', "
                    "'profile://p8-s46', 'ACTIVE')"
                ),
                {"tenant_id": tenant_id, "agent_id": agent_id},
            )
            connection.execute(
                text(
                    "INSERT INTO ae_agent_execution ("
                    "tenant_id, agent_execution_id, agent_id, agent_type, "
                    "principal_id, trigger_id, source_type, source_ref, state, "
                    "phase, correlation_id, received_at"
                    ") VALUES ("
                    ":tenant_id, :execution_id, :agent_id, 'IA', 'subject-p8-s46', "
                    ":trigger_id, 'PROMPT', 'prompt://p8-s46', 'RUNNING', "
                    "'STEP_EXECUTION', :correlation_id, now())"
                ),
                {
                    "tenant_id": tenant_id,
                    "execution_id": execution_id,
                    "agent_id": agent_id,
                    "trigger_id": str(uuid4()),
                    "correlation_id": f"corr-{suffix}",
                },
            )
            connection.execute(
                text(
                    "INSERT INTO ae_executable_step ("
                    "tenant_id, executable_step_id, agent_execution_id, step_kind, "
                    "state, legacy_interaction_id, correlation_id"
                    ") VALUES (:tenant_id, :step_id, :execution_id, "
                    "'P4_CHAT_RAG_COMPATIBILITY', 'WAITING', "
                    ":interaction_id, :correlation_id)"
                ),
                {
                    "tenant_id": tenant_id,
                    "step_id": step_id,
                    "execution_id": execution_id,
                    "interaction_id": str(uuid4()),
                    "correlation_id": f"corr-{suffix}",
                },
            )
            connection.execute(
                text(
                    "INSERT INTO ae_nsl_approval_request ("
                    "tenant_id, approval_request_id, nsl_execution_id, "
                    "business_operation_id, protected_request_ref, "
                    "approval_request_hash, request_size_bytes, content_type, "
                    "data_classification, created_at, approval_request_bytes"
                    ") VALUES (:tenant_id, :request_id, :nsl_execution_id, "
                    ":business_operation_id, :protected_ref, :request_hash, 2, "
                    "'application/json', 'INTERNAL', now(), :request_bytes)"
                ),
                {
                    "tenant_id": tenant_id,
                    "request_id": request_id,
                    "nsl_execution_id": nsl_execution_id,
                    "business_operation_id": business_operation_id,
                    "protected_ref": f"ae://nsl-approval-requests/aa/{'c' * 64}.json",
                    "request_hash": f"sha256:{'d' * 64}",
                    "request_bytes": b"{}",
                },
            )

        saved = repository.register(
            **_binding(
                wait_id=str(uuid4()),
                tenant_id=tenant_id,
                agent_execution_id=execution_id,
                executable_step_id=step_id,
                external_ref=request_id,
                nsl_execution_id=nsl_execution_id,
                business_operation_id=business_operation_id,
                approval_request_id=request_id,
                checkpoint_version=7,
            )
        )
        assert saved["checkpoint_version"] == 7
        assert saved["approval_request_id"] == request_id

        with engine.connect() as connection:
            migration_count = connection.execute(
                text(
                    "SELECT count(*) FROM schema_migrations "
                    "WHERE version = '2503_ae_nsl_approval_wait_binding'"
                )
            ).scalar_one()
            row = (
                connection.execute(
                    text(
                        "SELECT external_ref, approval_request_id, "
                        "nsl_execution_id, business_operation_id, checkpoint_version "
                        "FROM ae_wait_registration WHERE tenant_id = :tenant_id"
                    ),
                    {"tenant_id": tenant_id},
                )
                .mappings()
                .one()
            )
        assert migration_count == 1
        assert dict(row) == {
            "external_ref": request_id,
            "approval_request_id": request_id,
            "nsl_execution_id": nsl_execution_id,
            "business_operation_id": business_operation_id,
            "checkpoint_version": 7,
        }
    finally:
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM ae_wait_registration WHERE tenant_id = :tenant_id"),
                {"tenant_id": tenant_id},
            )
            connection.execute(
                text(
                    "DELETE FROM ae_nsl_approval_request "
                    "WHERE tenant_id = :tenant_id"
                ),
                {"tenant_id": tenant_id},
            )
            connection.execute(
                text("DELETE FROM ae_executable_step WHERE tenant_id = :tenant_id"),
                {"tenant_id": tenant_id},
            )
            connection.execute(
                text("DELETE FROM ae_agent_execution WHERE tenant_id = :tenant_id"),
                {"tenant_id": tenant_id},
            )
            connection.execute(
                text("DELETE FROM ae_agent_identity WHERE tenant_id = :tenant_id"),
                {"tenant_id": tenant_id},
            )
        engine.dispose()
