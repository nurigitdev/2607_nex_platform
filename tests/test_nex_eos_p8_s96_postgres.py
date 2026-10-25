from __future__ import annotations

import os

import pytest
from nex_eos import (
    EOS_BUSINESS_OPERATION_TABLE,
    EOS_IDEMPOTENCY_TABLE,
    EOS_NVT_PROJECT_TABLE,
    EOS_OUTBOX_TABLE,
    EOS_PROJECT_MEMBER_TABLE,
    EOS_PROJECT_TABLE,
    PROJECT_CREATE_OPERATION,
    PROJECT_MEMBERSHIP_ADD_OPERATION,
    EosGovernedProjectService,
    EosServiceCaller,
    NvtProjectInput,
    SqlAlchemyEosBusinessTransactionCoordinator,
    SqlAlchemyEosProjectRepository,
    build_eos_database_runtime,
    project_operation_payload_hash,
)
from sqlalchemy import func, select, text

DATABASE_URL = os.getenv("NEX_EOS_TEST_DATABASE_URL", "")
SMOKE_ENABLED = os.getenv("NEX_EOS_P8_S96_POSTGRES_SMOKE") == "1"
TENANT_ID = "p8-s96-pg"
NVT_ID = "91000000-0000-4000-8000-000000000001"
PROJECT_ID = "92000000-0000-4000-8000-000000000001"
OWNER_MEMBERSHIP_ID = "93000000-0000-4000-8000-000000000001"
MEMBER_MEMBERSHIP_ID = "93000000-0000-4000-8000-000000000002"

pytestmark = pytest.mark.skipif(
    not DATABASE_URL or not SMOKE_ENABLED,
    reason="Protected P8-S96 PostgreSQL smoke is disabled",
)

_TABLES = (
    EOS_OUTBOX_TABLE,
    EOS_IDEMPOTENCY_TABLE,
    EOS_BUSINESS_OPERATION_TABLE,
    EOS_PROJECT_MEMBER_TABLE,
    EOS_PROJECT_TABLE,
    EOS_NVT_PROJECT_TABLE,
)


class AuthorizationSource:
    def effective_authorization(self, *, tenant_id: str, subject_id: str):
        return {
            "active": True,
            "tenant_id": tenant_id,
            "subject_id": subject_id,
            "scopes": [
                "project:project:create",
                "project:project:read",
                "project:project:admin",
                "project:membership:manage",
            ],
            "revision_hash": "b" * 64,
        }


def _cleanup(runtime) -> None:
    with runtime.engine.begin() as connection:
        for table in _TABLES:
            connection.execute(table.delete().where(table.c.tenant_id == TENANT_ID))


def _payload(operation: str, sequence: int, **values) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "eos_project_operation.v1",
        "tenant_id": TENANT_ID,
        "business_operation_id": f"94000000-0000-4000-8000-{sequence:012d}",
        "idempotency_key": f"p8-s96-pg-{sequence}",
        "requester_subject_id": "owner-pg",
        **values,
    }
    payload["payload_hash"] = project_operation_payload_hash(payload, operation)
    return payload


def test_s96_actual_postgres_governed_project_operation_and_cleanup() -> None:
    runtime = build_eos_database_runtime(
        environ={"NEX_EOS_TEST_DATABASE_URL": DATABASE_URL},
        database_env="NEX_EOS_TEST_DATABASE_URL",
    )
    _cleanup(runtime)
    try:
        with runtime.engine.connect() as connection:
            assert tuple(
                connection.execute(text("SELECT current_database(), current_user")).one()
            ) == ("nex_eos_test", "nex_eos_user")
        projects = SqlAlchemyEosProjectRepository(runtime.session_factory)
        projects.create_nvt_project(
            NvtProjectInput(TENANT_ID, NVT_ID, "NVT-S96-PG", "NVT S96 PG")
        )
        service = EosGovernedProjectService(
            session_factory=runtime.session_factory,
            coordinator=SqlAlchemyEosBusinessTransactionCoordinator(
                runtime.session_factory
            ),
            authorization_source=AuthorizationSource(),
        )
        caller = EosServiceCaller("service:nex-ae-api", "nex-eos", ("service:call",))
        created = service.create_project(
            _payload(
                PROJECT_CREATE_OPERATION,
                1,
                project={
                    "project_id": PROJECT_ID,
                    "project_code": "PROJECT-S96-PG",
                    "name": "Project S96 PG",
                    "nvt_project_id": NVT_ID,
                },
                initial_owner_subject_id="owner-pg",
                initial_owner_membership_id=OWNER_MEMBERSHIP_ID,
            ),
            caller=caller,
        )
        replay = service.create_project(
            _payload(
                PROJECT_CREATE_OPERATION,
                1,
                project={
                    "project_id": PROJECT_ID,
                    "project_code": "PROJECT-S96-PG",
                    "name": "Project S96 PG",
                    "nvt_project_id": NVT_ID,
                },
                initial_owner_subject_id="owner-pg",
                initial_owner_membership_id=OWNER_MEMBERSHIP_ID,
            ),
            caller=caller,
        )
        service.add_membership(
            _payload(
                PROJECT_MEMBERSHIP_ADD_OPERATION,
                2,
                project_id=PROJECT_ID,
                target_subject_id="member-pg",
                project_membership_id=MEMBER_MEMBERSHIP_ID,
                member_role="MEMBER",
            ),
            caller=caller,
        )
        assert created["created"] is True
        assert replay["created"] is False
        assert service.get_project(
            tenant_id=TENANT_ID,
            project_id=PROJECT_ID,
            requester_subject_id="owner-pg",
        )["project_code"] == "PROJECT-S96-PG"
        assert len(
            service.list_memberships(
                tenant_id=TENANT_ID,
                project_id=PROJECT_ID,
                requester_subject_id="owner-pg",
            )
        ) == 2
        with runtime.engine.connect() as connection:
            assert connection.execute(
                select(func.count())
                .select_from(EOS_BUSINESS_OPERATION_TABLE)
                .where(EOS_BUSINESS_OPERATION_TABLE.c.tenant_id == TENANT_ID)
            ).scalar_one() == 2
    finally:
        _cleanup(runtime)
        with runtime.engine.connect() as connection:
            residue = {
                table.name: connection.execute(
                    select(func.count())
                    .select_from(table)
                    .where(table.c.tenant_id == TENANT_ID)
                ).scalar_one()
                for table in _TABLES
            }
        runtime.dispose()
    assert set(residue.values()) == {0}
