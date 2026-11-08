from __future__ import annotations

import os
import threading
import time

import pytest
from nex_eos import (
    EOS_BUSINESS_OPERATION_TABLE,
    EOS_IDEMPOTENCY_TABLE,
    EOS_OUTBOX_TABLE,
    EosBusinessOperationError,
    EosBusinessOperationRequest,
    SqlAlchemyEosBusinessTransactionCoordinator,
    build_eos_database_runtime,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from sqlalchemy import text

DATABASE_URL = os.getenv("NEX_EOS_TEST_DATABASE_URL", "")
SMOKE_ENABLED = os.getenv("NEX_EOS_P8_S09_POSTGRES_SMOKE") == "1"
TENANT_ID = "p8-s09-pg-tenant"
ROLLBACK_TENANT_ID = "p8-s09-pg-rollback"

pytestmark = pytest.mark.skipif(
    not DATABASE_URL or not SMOKE_ENABLED,
    reason=(
        "NEX_EOS_TEST_DATABASE_URL and NEX_EOS_P8_S09_POSTGRES_SMOKE=1 "
        "are required for protected EOS PostgreSQL smoke"
    ),
)


def _request(**overrides: str) -> EosBusinessOperationRequest:
    values = {
        "tenant_id": TENANT_ID,
        "business_operation_id": "91111111-1111-4111-8111-111111111111",
        "idempotency_key": "p8-s09-concurrent-key",
        "operation": "CREATE_VOUCHER_DRAFT",
        "payload_hash": semantic_sha256_hash_ref(
            {"tenant_id": TENANT_ID, "voucher": "golden-a"}
        ),
        "event_type": "BUSINESS_TRANSACTION_COMMITTED",
    }
    values.update(overrides)
    return EosBusinessOperationRequest(**values)


def _cleanup(runtime) -> None:
    with runtime.engine.begin() as connection:
        connection.execute(
            EOS_OUTBOX_TABLE.delete().where(
                EOS_OUTBOX_TABLE.c.tenant_id.in_((TENANT_ID, ROLLBACK_TENANT_ID))
            )
        )
        connection.execute(
            EOS_IDEMPOTENCY_TABLE.delete().where(
                EOS_IDEMPOTENCY_TABLE.c.tenant_id.in_((TENANT_ID, ROLLBACK_TENANT_ID))
            )
        )
        connection.execute(
            EOS_BUSINESS_OPERATION_TABLE.delete().where(
                EOS_BUSINESS_OPERATION_TABLE.c.tenant_id.in_(
                    (TENANT_ID, ROLLBACK_TENANT_ID)
                )
            )
        )
        connection.execute(text("DROP TABLE IF EXISTS eos_s09_pg_probe"))


def test_s09_actual_postgres_concurrency_atomicity_rollback_and_zero_residue() -> None:
    runtime = build_eos_database_runtime(
        environ={"NEX_EOS_TEST_DATABASE_URL": DATABASE_URL},
        database_env="NEX_EOS_TEST_DATABASE_URL",
    )
    coordinator = SqlAlchemyEosBusinessTransactionCoordinator(runtime.session_factory)
    _cleanup(runtime)
    with runtime.engine.begin() as connection:
        identity = connection.execute(
            text("SELECT current_database(), current_user")
        ).one()
        assert tuple(identity) == ("nex_eos_test", "nex_eos_user")
        migration = connection.execute(
            text(
                "SELECT count(*) FROM schema_migrations "
                "WHERE version = '2501_eos_business_transaction_core'"
            )
        ).scalar_one()
        assert migration == 1
        connection.execute(
            text(
                "CREATE TABLE eos_s09_pg_probe ("
                "probe_id UUID PRIMARY KEY, tenant_id TEXT NOT NULL)"
            )
        )

    barrier = threading.Barrier(8)
    mutation_calls = 0
    mutation_lock = threading.Lock()

    def execute_once(_index: int):
        nonlocal mutation_calls
        barrier.wait(timeout=5)

        def mutation(session):
            nonlocal mutation_calls
            assert session is not None
            with mutation_lock:
                mutation_calls += 1
            session.execute(
                text(
                    "INSERT INTO eos_s09_pg_probe (probe_id, tenant_id) "
                    "VALUES ('aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', :tenant_id)"
                ),
                {"tenant_id": TENANT_ID},
            )
            time.sleep(0.15)
            return {
                "business_result_ref": "eos:voucher-draft:pg-golden-a",
                "private_amount": "1250000.00",
            }

        return coordinator.execute(_request(), mutation)

    try:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(execute_once, range(8)))

        assert mutation_calls == 1
        assert sum(result.created for result in results) == 1
        assert len({result.outbox_id for result in results}) == 1
        assert len({result.event_id for result in results}) == 1

        with runtime.engine.connect() as connection:
            counts = {
                "operations": connection.execute(
                    text(
                        "SELECT count(*) FROM eos_business_operation "
                        "WHERE tenant_id = :tenant_id"
                    ),
                    {"tenant_id": TENANT_ID},
                ).scalar_one(),
                "idempotency": connection.execute(
                    text(
                        "SELECT count(*) FROM eos_idempotency "
                        "WHERE tenant_id = :tenant_id"
                    ),
                    {"tenant_id": TENANT_ID},
                ).scalar_one(),
                "outbox": connection.execute(
                    text(
                        "SELECT count(*) FROM eos_outbox WHERE tenant_id = :tenant_id"
                    ),
                    {"tenant_id": TENANT_ID},
                ).scalar_one(),
                "business": connection.execute(
                    text(
                        "SELECT count(*) FROM eos_s09_pg_probe "
                        "WHERE tenant_id = :tenant_id"
                    ),
                    {"tenant_id": TENANT_ID},
                ).scalar_one(),
            }
            event_payload = connection.execute(
                text(
                    "SELECT event_payload FROM eos_outbox WHERE tenant_id = :tenant_id"
                ),
                {"tenant_id": TENANT_ID},
            ).scalar_one()
        assert counts == {
            "operations": 1,
            "idempotency": 1,
            "outbox": 1,
            "business": 1,
        }
        assert "private_amount" not in event_payload
        assert event_payload["business_result_ref"].endswith("pg-golden-a")

        with pytest.raises(EosBusinessOperationError) as conflict:
            coordinator.execute(
                _request(payload_hash=semantic_sha256_hash_ref({"changed": True})),
                lambda _session: {"business_result_ref": "must-not-run"},
            )
        assert conflict.value.error_code == "EOS_IDEMPOTENCY_CONFLICT"

        rollback_request = _request(
            tenant_id=ROLLBACK_TENANT_ID,
            business_operation_id="92222222-2222-4222-8222-222222222222",
            idempotency_key="p8-s09-rollback-key",
            payload_hash=semantic_sha256_hash_ref({"rollback": True}),
        )

        def failed_mutation(session):
            assert session is not None
            session.execute(
                text(
                    "INSERT INTO eos_s09_pg_probe (probe_id, tenant_id) "
                    "VALUES ('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', :tenant_id)"
                ),
                {"tenant_id": ROLLBACK_TENANT_ID},
            )
            raise RuntimeError("force rollback")

        with pytest.raises(EosBusinessOperationError) as rollback:
            coordinator.execute(rollback_request, failed_mutation)
        assert rollback.value.error_code == "EOS_BUSINESS_MUTATION_FAILED"

        with runtime.engine.connect() as connection:
            rolled_back = connection.execute(
                text(
                    "SELECT "
                    "(SELECT count(*) FROM eos_business_operation "
                    " WHERE tenant_id = :tenant_id), "
                    "(SELECT count(*) FROM eos_idempotency "
                    " WHERE tenant_id = :tenant_id), "
                    "(SELECT count(*) FROM eos_outbox "
                    " WHERE tenant_id = :tenant_id), "
                    "(SELECT count(*) FROM eos_s09_pg_probe "
                    " WHERE tenant_id = :tenant_id)"
                ),
                {"tenant_id": ROLLBACK_TENANT_ID},
            ).one()
        assert tuple(rolled_back) == (0, 0, 0, 0)
    finally:
        _cleanup(runtime)
        with runtime.engine.connect() as connection:
            residue = connection.execute(
                text(
                    "SELECT "
                    "(SELECT count(*) FROM eos_business_operation "
                    " WHERE tenant_id IN (:tenant_id, :rollback_tenant_id)), "
                    "(SELECT count(*) FROM eos_idempotency "
                    " WHERE tenant_id IN (:tenant_id, :rollback_tenant_id)), "
                    "(SELECT count(*) FROM eos_outbox "
                    " WHERE tenant_id IN (:tenant_id, :rollback_tenant_id))"
                ),
                {
                    "tenant_id": TENANT_ID,
                    "rollback_tenant_id": ROLLBACK_TENANT_ID,
                },
            ).one()
        runtime.dispose()
    assert tuple(residue) == (0, 0, 0)
