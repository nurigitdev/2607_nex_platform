from __future__ import annotations

import os
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from nex_eos import (
    EOS_BUSINESS_OPERATION_TABLE,
    EOS_IDEMPOTENCY_TABLE,
    EOS_NVT_PROJECT_TABLE,
    EOS_OUTBOX_TABLE,
    EOS_PROJECT_MEMBER_TABLE,
    EOS_PROJECT_TABLE,
    PROJECT_CREATE_OPERATION,
    PROJECT_MEMBERSHIP_ADD_MANY_OPERATION,
    PROJECT_MEMBERSHIP_ADD_OPERATION,
    EosGovernedProjectService,
    EosServiceCaller,
    NvtProjectInput,
    SqlAlchemyEosBusinessTransactionCoordinator,
    SqlAlchemyEosProjectRepository,
    build_eos_database_runtime,
    deterministic_project_membership_id,
    project_membership_add_many_payload_hash,
    project_operation_payload_hash,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from sqlalchemy import func, select, text

DATABASE_URL = os.getenv("NEX_EOS_TEST_DATABASE_URL", "")
SMOKE_ENABLED = os.getenv("NEX_EOS_P8_S109_POSTGRES_SMOKE") == "1"
TENANT_ID = "p8-s109-pg"
NVT_ID = "b9100000-0000-4000-8000-000000000001"
PROJECT_ID = "b9200000-0000-4000-8000-000000000001"
OWNER_ID = "owner-s109-pg"
CALLER = EosServiceCaller("service:nex-ae-api", "nex-eos", ("service:call",))

pytestmark = pytest.mark.skipif(
    not DATABASE_URL or not SMOKE_ENABLED,
    reason="Protected P8-S109 PostgreSQL concurrency smoke is disabled",
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
    def effective_authorization(
        self, *, tenant_id: str, subject_id: str
    ) -> Mapping[str, object]:
        return {
            "active": True,
            "tenant_id": tenant_id,
            "subject_id": subject_id,
            "scopes": (
                [
                    "project:project:create",
                    "project:project:admin",
                    "project:membership:manage",
                ]
                if subject_id == OWNER_ID
                else []
            ),
            "revision_hash": "b" * 64,
        }


def _cleanup(runtime) -> None:
    with runtime.engine.begin() as connection:
        for table in _TABLES:
            connection.execute(table.delete().where(table.c.tenant_id == TENANT_ID))


def _service(runtime) -> EosGovernedProjectService:
    return EosGovernedProjectService(
        session_factory=runtime.session_factory,
        coordinator=SqlAlchemyEosBusinessTransactionCoordinator(
            runtime.session_factory
        ),
        authorization_source=AuthorizationSource(),
    )


def _payload(operation: str, sequence: int, **values) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "eos_project_operation.v1",
        "tenant_id": TENANT_ID,
        "business_operation_id": f"b9300000-0000-4000-8000-{sequence:012d}",
        "idempotency_key": f"p8-s109-pg-{sequence}",
        "requester_subject_id": OWNER_ID,
        **values,
    }
    payload["payload_hash"] = project_operation_payload_hash(payload, operation)
    return payload


def _batch(sequence: int, subject_id: str) -> dict[str, object]:
    payload = _payload(
        PROJECT_MEMBERSHIP_ADD_MANY_OPERATION,
        sequence,
        requested_operation=PROJECT_MEMBERSHIP_ADD_MANY_OPERATION,
        project_id=PROJECT_ID,
        target_subject_ids=[subject_id],
        member_role="MEMBER",
        resolution_evidence_hash=semantic_sha256_hash_ref(
            {"tenant_id": TENANT_ID, "subject_id": subject_id}
        ),
    )
    payload["payload_hash"] = project_membership_add_many_payload_hash(payload)
    return payload


def test_s109_actual_postgres_batch_and_single_add_concurrency() -> None:
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

        SqlAlchemyEosProjectRepository(runtime.session_factory).create_nvt_project(
            NvtProjectInput(TENANT_ID, NVT_ID, "NVT-S109-PG", "NVT S109 PG")
        )
        service = _service(runtime)
        service.create_project(
            _payload(
                PROJECT_CREATE_OPERATION,
                1,
                project={
                    "project_id": PROJECT_ID,
                    "project_code": "PROJECT-S109-PG",
                    "name": "Project S109 PG",
                    "nvt_project_id": NVT_ID,
                    "currency": "KRW",
                },
                initial_owner_subject_id=OWNER_ID,
                initial_owner_membership_id=deterministic_project_membership_id(
                    TENANT_ID, PROJECT_ID, OWNER_ID
                ),
            ),
            caller=CALLER,
        )

        batch_barrier = Barrier(2)

        def batch_call(sequence: int):
            batch_barrier.wait(timeout=5)
            return _service(runtime).add_memberships(
                _batch(sequence, "member-batch-race"), caller=CALLER
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            batch_results = list(executor.map(batch_call, (2, 3)))
        assert sorted(
            result["result"]["item_results"][0]["outcome"]
            for result in batch_results
        ) == ["ADDED", "ALREADY_ACTIVE"]
        assert _subject_row_count(runtime, "member-batch-race") == 1

        mixed_barrier = Barrier(2)

        def batch_mixed():
            mixed_barrier.wait(timeout=5)
            return _service(runtime).add_memberships(
                _batch(4, "member-mixed-race"), caller=CALLER
            )

        def single_mixed():
            mixed_barrier.wait(timeout=5)
            return _service(runtime).add_membership(
                _payload(
                    PROJECT_MEMBERSHIP_ADD_OPERATION,
                    5,
                    project_id=PROJECT_ID,
                    target_subject_id="member-mixed-race",
                    project_membership_id=deterministic_project_membership_id(
                        TENANT_ID, PROJECT_ID, "member-mixed-race"
                    ),
                    member_role="MEMBER",
                ),
                caller=CALLER,
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            future_batch = executor.submit(batch_mixed)
            future_single = executor.submit(single_mixed)
            batch_result = future_batch.result(timeout=15)
            single_result = future_single.result(timeout=15)
        assert batch_result["result"]["item_results"][0]["outcome"] in {
            "ADDED",
            "ALREADY_ACTIVE",
        }
        assert single_result["result"]["membership"]["status"] == "ACTIVE"
        assert _subject_row_count(runtime, "member-mixed-race") == 1
    finally:
        _cleanup(runtime)
        with runtime.engine.connect() as connection:
            assert connection.execute(
                select(func.count())
                .select_from(EOS_PROJECT_MEMBER_TABLE)
                .where(EOS_PROJECT_MEMBER_TABLE.c.tenant_id == TENANT_ID)
            ).scalar_one() == 0
        runtime.engine.dispose()


def _subject_row_count(runtime, subject_id: str) -> int:
    with runtime.engine.connect() as connection:
        return connection.execute(
            select(func.count())
            .select_from(EOS_PROJECT_MEMBER_TABLE)
            .where(
                EOS_PROJECT_MEMBER_TABLE.c.tenant_id == TENANT_ID,
                EOS_PROJECT_MEMBER_TABLE.c.project_id == PROJECT_ID,
                EOS_PROJECT_MEMBER_TABLE.c.subject_id == subject_id,
            )
        ).scalar_one()
