from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from nex_runtime.database import psycopg_database_url
from nex_runtime.postgres_targets import resolve_postgres_test_targets
from nex_wa import (
    WA_REQUIRED_MIGRATIONS,
    WorkAssetBindingInput,
    WorkAssetError,
    WorkAssetInput,
    WorkEvidenceInput,
    build_wa_persistence_runtime,
)
from run_migrations import run_service_migrations
from sqlalchemy import text

pytestmark = pytest.mark.skipif(
    os.getenv("NEX_WA_P9_S04_POSTGRES_SMOKE") != "1",
    reason="set NEX_WA_P9_S04_POSTGRES_SMOKE=1 for actual nex_wa_test smoke",
)


def test_actual_postgres_asset_binding_version_and_tenant_invariants() -> None:
    target = resolve_postgres_test_targets(os.environ, service_ids=("nex-wa",))[0]
    database_url = target.database_url
    with (
        psycopg.connect(psycopg_database_url(database_url), autocommit=True) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute("SELECT current_database(), current_user")
        assert cursor.fetchone() == ("nex_wa_test", "nex_wa_user")
    migration = run_service_migrations(
        "nex-wa", database_url=database_url, profile="test"
    )
    assert migration.planned == WA_REQUIRED_MIGRATIONS

    runtime = build_wa_persistence_runtime(
        environ={"NEX_WA_TEST_DATABASE_URL": database_url},
        database_env="NEX_WA_TEST_DATABASE_URL",
    )
    suffix = uuid4().hex
    tenant_id = f"P9S04-{suffix}"
    now = datetime.now(UTC)

    def evidence(revision: str, source_hash: str):
        return runtime.work_evidence_repository.create_or_get(
            WorkEvidenceInput(
                tenant_id=tenant_id,
                source_owner="nex-ae-api",
                source_type="AE_AGENT_RESULT",
                source_ref=f"execution-{suffix}",
                source_revision_ref=revision,
                source_hash=source_hash,
                evidence_kind="AGENT_EXECUTION_RESULT",
                actor_type="AGENT",
                actor_ref=f"agent-{suffix}",
                agent_type_snapshot="CA",
                project_ref=str(uuid4()),
                occurred_at=now,
                observed_at=now + timedelta(seconds=1),
                classification="CONFIDENTIAL",
            )
        )

    primary = evidence("result-1", "sha256:" + "1" * 64)
    supporting = evidence("result-2", "sha256:" + "2" * 64)

    def candidate(bindings: tuple[WorkAssetBindingInput, ...]) -> WorkAssetInput:
        return WorkAssetInput(
            tenant_id=tenant_id,
            asset_type="AGENT_EXECUTION_RESULT",
            agent_execution_id=f"execution-{suffix}",
            actor_type="AGENT",
            actor_ref=f"agent-{suffix}",
            agent_type_snapshot="CA",
            occurred_at=now,
            classification="CONFIDENTIAL",
            bindings=bindings,
        )

    try:
        first = runtime.work_asset_repository.create_or_update(
            candidate((WorkAssetBindingInput(primary.work_evidence_id, "PRIMARY"),))
        )
        replay = runtime.work_asset_repository.create_or_update(
            candidate((WorkAssetBindingInput(primary.work_evidence_id, "PRIMARY"),))
        )
        changed = runtime.work_asset_repository.create_or_update(
            candidate(
                (
                    WorkAssetBindingInput(primary.work_evidence_id, "PRIMARY"),
                    WorkAssetBindingInput(supporting.work_evidence_id, "SUPPORTING"),
                )
            )
        )
        assert replay == first
        assert changed.version == 2
        assert changed.asset_hash != first.asset_hash
        assert len(changed.bindings) == 2

        with pytest.raises(WorkAssetError) as invalid:
            runtime.work_asset_repository.create_or_update(
                candidate(
                    (
                        WorkAssetBindingInput(primary.work_evidence_id, "PRIMARY"),
                        WorkAssetBindingInput(supporting.work_evidence_id, "PRIMARY"),
                    )
                )
            )
        assert invalid.value.error_code == "WA_ASSET_PRIMARY_INVALID"

        with runtime.api_engine.connect() as connection:
            assert connection.execute(
                text(
                    "SELECT count(*) FROM wa_work_asset_evidence "
                    "WHERE tenant_id=:tenant_id AND work_asset_id=:asset_id"
                ),
                {"tenant_id": tenant_id, "asset_id": changed.work_asset_id},
            ).scalar_one() == 2
    finally:
        with runtime.api_engine.begin() as connection:
            connection.execute(
                text("DELETE FROM wa_work_asset WHERE tenant_id=:tenant_id"),
                {"tenant_id": tenant_id},
            )
            connection.execute(
                text("DELETE FROM wa_work_evidence WHERE tenant_id=:tenant_id"),
                {"tenant_id": tenant_id},
            )
        with runtime.api_engine.connect() as connection:
            assert connection.execute(
                text("SELECT count(*) FROM wa_work_asset WHERE tenant_id=:tenant_id"),
                {"tenant_id": tenant_id},
            ).scalar_one() == 0
        runtime.dispose()
