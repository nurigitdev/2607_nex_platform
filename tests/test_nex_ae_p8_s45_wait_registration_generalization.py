from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from nex_ae_api import delegated_work as delegated_work_module
from nex_ae_api.delegated_work import (
    DelegatedWorkError,
    SqlAlchemyWaitRegistrationRepository,
)
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool, StaticPool

DATABASE_URL = os.getenv("NEX_AE_TEST_DATABASE_URL")
POSTGRES_SMOKE = os.getenv("NEX_AE_P8_S45_POSTGRES_SMOKE") == "1"
NOW = "2026-10-22T10:00:00Z"


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


def _registration(**changes: object) -> dict[str, object]:
    value = {
        "wait_id": "11111111-1111-4111-8111-111111111145",
        "tenant_id": "tenant-p8-s45",
        "agent_execution_id": "22222222-2222-4222-8222-222222222245",
        "executable_step_id": "33333333-3333-4333-8333-333333333345",
        "external_ref": "approval-request:p8-s45:non-uuid",
        "result_contract_ref": "urn:nex:approval-resume:p8:v1",
        "created_at": NOW,
        "wait_type": "NSL_APPROVAL",
        "nsl_execution_id": "nsl-execution-p8-s45",
        "business_operation_id": "business-operation-p8-s45",
        "approval_request_id": "approval-request:p8-s45:non-uuid",
        "checkpoint_version": 1,
    }
    value.update(changes)
    return value


def test_nsl_approval_wait_accepts_bounded_non_uuid_external_ref(repository) -> None:
    first = repository.register(**_registration())
    replay = repository.register(**_registration(created_at="2026-10-22T10:05:00Z"))

    assert replay == first
    assert first["wait_type"] == "NSL_APPROVAL"
    assert first["external_ref"] == "approval-request:p8-s45:non-uuid"
    assert (
        repository.get(
            tenant_id=first["tenant_id"],
            agent_execution_id=first["agent_execution_id"],
            executable_step_id=first["executable_step_id"],
            wait_type="NSL_APPROVAL",
        )
        == first
    )
    assert (
        repository.get(
            tenant_id=first["tenant_id"],
            agent_execution_id=first["agent_execution_id"],
            executable_step_id=first["executable_step_id"],
        )
        is None
    )


def test_historical_work_result_defaults_remain_compatible(repository) -> None:
    value = _registration(
        wait_type="WORK_RESULT",
        external_ref="44444444-4444-4444-8444-444444444445",
        nsl_execution_id=None,
        business_operation_id=None,
        approval_request_id=None,
        checkpoint_version=None,
    )
    saved = repository.register(**value)

    assert saved["wait_type"] == "WORK_RESULT"
    assert (
        repository.get(
            tenant_id=value["tenant_id"],
            agent_execution_id=value["agent_execution_id"],
            executable_step_id=value["executable_step_id"],
        )
        == saved
    )


def test_distinct_wait_types_can_share_one_step(repository) -> None:
    work_result = _registration(
        wait_id="55555555-5555-4555-8555-555555555545",
        wait_type="WORK_RESULT",
        external_ref="66666666-6666-4666-8666-666666666645",
        nsl_execution_id=None,
        business_operation_id=None,
        approval_request_id=None,
        checkpoint_version=None,
    )
    approval = _registration()

    assert repository.register(**work_result)["wait_type"] == "WORK_RESULT"
    assert repository.register(**approval)["wait_type"] == "NSL_APPROVAL"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("wait_type", "UNKNOWN"),
        ("external_ref", ""),
        ("external_ref", "x" * 257),
    ],
)
def test_wait_type_and_external_ref_fail_closed(
    repository, field: str, value: str
) -> None:
    with pytest.raises(DelegatedWorkError) as invalid:
        repository.register(**_registration(**{field: value}))
    assert invalid.value.error_code == "ae.delegate_work_invalid"


def test_same_typed_step_with_changed_identity_conflicts(repository) -> None:
    repository.register(**_registration())

    with pytest.raises(DelegatedWorkError) as conflict:
        repository.register(
            **_registration(
                external_ref="approval-request:p8-s45:changed",
                approval_request_id="approval-request:p8-s45:changed",
            )
        )
    assert conflict.value.error_code == "ae.wait_registration_immutable_conflict"


def test_shared_wait_helpers_cover_safe_shape_and_timestamp_variants() -> None:
    with pytest.raises(DelegatedWorkError, match="must be an object"):
        delegated_work_module._json_object([], "plan_json")

    assert delegated_work_module._timestamp(
        datetime(2026, 10, 22, 10, 0, tzinfo=UTC)
    ) == "2026-10-22T10:00:00Z"
    assert delegated_work_module._timestamp(
        datetime(2026, 10, 22, 10, 0)
    ) == "2026-10-22T10:00:00"

    class TimestampValue:
        def isoformat(self) -> str:
            return "2026-10-22T10:00:00"

    assert (
        delegated_work_module._timestamp(TimestampValue())
        == "2026-10-22T10:00:00"
    )


def test_s45_migration_generalizes_uuid_without_rewriting_history() -> None:
    migration = (
        Path(__file__).resolve().parents[1]
        / "database/nex-ae-api/migrations/2502_ae_wait_registration_generalization.sql"
    ).read_text(encoding="utf-8")
    compact = " ".join(migration.lower().split())

    assert "alter column external_ref type text using external_ref::text" in compact
    assert "wait_type in ('work_result', 'nsl_approval')" in compact
    assert "char_length(external_ref) between 1 and 256" in compact
    assert "'2502_ae_wait_registration_generalization'" in compact
    assert "drop table" not in compact
    assert "delete from ae_wait_registration" not in compact


@pytest.mark.skipif(
    not POSTGRES_SMOKE or not DATABASE_URL,
    reason="Protected P8-S45 PostgreSQL smoke is disabled",
)
def test_actual_postgres_supports_historical_and_nsl_waits() -> None:
    assert DATABASE_URL is not None
    suffix = uuid4().hex
    tenant_id = f"tenant-p8-s45-{suffix}"
    agent_id = str(uuid4())
    execution_id = str(uuid4())
    trigger_id = str(uuid4())
    step_id = str(uuid4())
    factory_engine = create_engine(DATABASE_URL, poolclass=NullPool)
    repository = SqlAlchemyWaitRegistrationRepository(
        sessionmaker(bind=factory_engine, expire_on_commit=False)
    )
    try:
        with factory_engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO ae_agent_identity ("
                    "tenant_id, agent_id, agent_type, profile_ref, status"
                    ") VALUES ("
                    ":tenant_id, :agent_id, 'IA', 'profile://p8-s45', 'ACTIVE'"
                    ")"
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
                    ":tenant_id, :execution_id, :agent_id, 'IA', 'subject-p8-s45', "
                    ":trigger_id, 'PROMPT', 'prompt://p8-s45', 'RUNNING', "
                    "'STEP_EXECUTION', :correlation_id, now()"
                    ")"
                ),
                {
                    "tenant_id": tenant_id,
                    "execution_id": execution_id,
                    "agent_id": agent_id,
                    "trigger_id": trigger_id,
                    "correlation_id": f"corr-{suffix}",
                },
            )
            connection.execute(
                text(
                    "INSERT INTO ae_executable_step ("
                    "tenant_id, executable_step_id, agent_execution_id, step_kind, "
                    "state, legacy_interaction_id, correlation_id"
                    ") VALUES ("
                    ":tenant_id, :step_id, :execution_id, "
                    "'P4_CHAT_RAG_COMPATIBILITY', 'WAITING', "
                    ":interaction_id, :correlation_id"
                    ")"
                ),
                {
                    "tenant_id": tenant_id,
                    "step_id": step_id,
                    "execution_id": execution_id,
                    "interaction_id": str(uuid4()),
                    "correlation_id": f"corr-{suffix}",
                },
            )
            request_id = f"approval-request:{suffix}"
            nsl_execution_id = f"nsl-execution:{suffix}"
            business_operation_id = f"business-operation:{suffix}"
            request_bytes = b"{}"
            connection.execute(
                text(
                    "INSERT INTO ae_nsl_approval_request ("
                    "tenant_id, approval_request_id, nsl_execution_id, "
                    "business_operation_id, protected_request_ref, "
                    "approval_request_hash, request_size_bytes, content_type, "
                    "data_classification, created_at, approval_request_bytes"
                    ") VALUES ("
                    ":tenant_id, :approval_request_id, :nsl_execution_id, "
                    ":business_operation_id, :protected_request_ref, "
                    ":approval_request_hash, :request_size_bytes, "
                    "'application/json', 'INTERNAL', now(), :request_bytes"
                    ")"
                ),
                {
                    "tenant_id": tenant_id,
                    "approval_request_id": request_id,
                    "nsl_execution_id": nsl_execution_id,
                    "business_operation_id": business_operation_id,
                    "protected_request_ref": f"ae://nsl-approval-requests/aa/{'a' * 64}.json",
                    "approval_request_hash": f"sha256:{'b' * 64}",
                    "request_size_bytes": len(request_bytes),
                    "request_bytes": request_bytes,
                },
            )

        approval = repository.register(
            wait_id=str(uuid4()),
            tenant_id=tenant_id,
            agent_execution_id=execution_id,
            executable_step_id=step_id,
            external_ref=request_id,
            result_contract_ref="urn:nex:approval-resume:p8:v1",
            created_at=NOW,
            wait_type="NSL_APPROVAL",
            nsl_execution_id=nsl_execution_id,
            business_operation_id=business_operation_id,
            approval_request_id=request_id,
            checkpoint_version=1,
        )
        work_result = repository.register(
            wait_id=str(uuid4()),
            tenant_id=tenant_id,
            agent_execution_id=execution_id,
            executable_step_id=step_id,
            external_ref=str(uuid4()),
            result_contract_ref="urn:nex:work-result:p7:v1",
            created_at=NOW,
        )
        assert approval["external_ref"] == request_id
        assert work_result["wait_type"] == "WORK_RESULT"

        with factory_engine.connect() as connection:
            column_type = connection.execute(
                text(
                    "SELECT data_type FROM information_schema.columns "
                    "WHERE table_schema = current_schema() "
                    "AND table_name = 'ae_wait_registration' "
                    "AND column_name = 'external_ref'"
                )
            ).scalar_one()
            wait_types = set(
                connection.execute(
                    text(
                        "SELECT wait_type FROM ae_wait_registration "
                        "WHERE tenant_id = :tenant_id"
                    ),
                    {"tenant_id": tenant_id},
                ).scalars()
            )
        assert column_type == "text"
        assert wait_types == {"WORK_RESULT", "NSL_APPROVAL"}
    finally:
        with factory_engine.begin() as connection:
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
        factory_engine.dispose()
