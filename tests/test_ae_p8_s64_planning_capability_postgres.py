from __future__ import annotations

import os
from uuid import uuid4

import pytest
from nex_ae_api.golden_a_planning import build_golden_a_capability_snapshot
from nex_ae_api.planning_capabilities import SqlAlchemyCapabilitySnapshotRepository
from p8_golden_a_fixture import load_golden_a_fixture
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

DATABASE_URL = os.getenv("NEX_AE_TEST_DATABASE_URL")
SMOKE_ENABLED = os.getenv("NEX_P8_S64_POSTGRES_GATE") == "1"

pytestmark = pytest.mark.skipif(
    not DATABASE_URL or not SMOKE_ENABLED,
    reason="Protected P8-S64 AE PostgreSQL gate is disabled",
)


def test_actual_postgres_persists_and_reloads_exact_write_capability() -> None:
    assert DATABASE_URL is not None
    fixture = load_golden_a_fixture()
    tenant_id = fixture["tenant"]["tenant_id"]
    snapshot_id = str(uuid4())
    engine = create_engine(DATABASE_URL, poolclass=NullPool)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    repository = SqlAlchemyCapabilitySnapshotRepository(factory)
    try:
        with engine.connect() as connection:
            migration_count = connection.execute(
                text(
                    "SELECT count(*) FROM schema_migrations "
                    "WHERE version = '2203_ae_local_skill_activation'"
                )
            ).scalar_one()
            snapshot_version = connection.execute(
                text(
                    "SELECT COALESCE(max(snapshot_version), 0) + 1 "
                    "FROM ae_capability_snapshot WHERE tenant_id = :tenant_id"
                ),
                {"tenant_id": tenant_id},
            ).scalar_one()
        assert migration_count == 1
        snapshot = build_golden_a_capability_snapshot(
            fixture,
            capability_snapshot_id=snapshot_id,
            snapshot_version=int(snapshot_version),
            created_at="2026-10-23T09:00:00Z",
        )

        assert repository.save(snapshot) == snapshot
        restarted = SqlAlchemyCapabilitySnapshotRepository(factory)
        reloaded = restarted.get(
            tenant_id=tenant_id,
            capability_snapshot_id=snapshot_id,
        )
        assert reloaded == snapshot
        capability = next(
            item
            for item in reloaded["capabilities"]
            if item["capability_id"] == "FINANCE.CREATE_VOUCHER_DRAFT"
        )
        assert capability["operation_semantics"] == "WRITE"
        assert capability["local_skill_binding"]["backend_profile"] == (
            "NSL_V02_IN_PROCESS"
        )
        with engine.connect() as connection:
            assert (
                connection.execute(
                    text(
                        "SELECT count(*) FROM ae_capability_snapshot "
                        "WHERE tenant_id = :tenant_id "
                        "AND capability_snapshot_id = :snapshot_id"
                    ),
                    {"tenant_id": tenant_id, "snapshot_id": snapshot_id},
                ).scalar_one()
                == 1
            )
    finally:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "DELETE FROM ae_capability_snapshot "
                    "WHERE tenant_id = :tenant_id "
                    "AND capability_snapshot_id = :snapshot_id"
                ),
                {"tenant_id": tenant_id, "snapshot_id": snapshot_id},
            )
        engine.dispose()
