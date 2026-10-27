from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import psycopg
import pytest
from nex_runtime.database import psycopg_database_url
from nex_runtime.postgres_targets import resolve_postgres_test_targets
from nex_wa import (
    WorkAssetBindingInput,
    WorkAssetInput,
    WorkEvidenceInput,
    build_wa_persistence_runtime,
    deterministic_work_evidence_id,
)
from run_migrations import run_service_migrations
from sqlalchemy import text

pytestmark = pytest.mark.skipif(
    os.getenv("NEX_WA_P9_S05_POSTGRES_SMOKE") != "1",
    reason="set NEX_WA_P9_S05_POSTGRES_SMOKE=1 for actual nex_wa_test smoke",
)


def test_actual_postgres_atomic_replay_and_concurrency() -> None:
    target = resolve_postgres_test_targets(os.environ, service_ids=("nex-wa",))[0]
    database_url = target.database_url
    with (
        psycopg.connect(
            psycopg_database_url(database_url), autocommit=True
        ) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute("SELECT current_database(), current_user")
        assert cursor.fetchone() == ("nex_wa_test", "nex_wa_user")
    run_service_migrations("nex-wa", database_url=database_url, profile="test")
    runtime = build_wa_persistence_runtime(
        environ={"NEX_WA_TEST_DATABASE_URL": database_url},
        database_env="NEX_WA_TEST_DATABASE_URL",
    )
    suffix = uuid4().hex
    tenant_id = f"P9S05-{suffix}"
    now = datetime.now(UTC)

    def evidence(revision: str, marker: str) -> WorkEvidenceInput:
        return WorkEvidenceInput(
            tenant_id=tenant_id,
            source_owner="nex-ae-api",
            source_type="AE_AGENT_RESULT",
            source_ref=f"execution-{suffix}",
            source_revision_ref=revision,
            source_hash="sha256:" + marker * 64,
            evidence_kind="AGENT_EXECUTION_RESULT",
            actor_type="AGENT",
            actor_ref=f"agent-{suffix}",
            agent_type_snapshot="IA",
            occurred_at=now,
            observed_at=now + timedelta(seconds=1),
            classification="CONFIDENTIAL",
        )

    def evidence_id(candidate: WorkEvidenceInput) -> str:
        return deterministic_work_evidence_id(
            tenant_id=candidate.tenant_id,
            source_type=candidate.source_type,
            source_ref=candidate.source_ref,
            source_revision_ref=candidate.source_revision_ref,
        )

    def asset(primary_id: str, supporting_id: str | None = None) -> WorkAssetInput:
        bindings = [WorkAssetBindingInput(primary_id, "PRIMARY")]
        if supporting_id is not None:
            bindings.append(WorkAssetBindingInput(supporting_id, "SUPPORTING"))
        return WorkAssetInput(
            tenant_id=tenant_id,
            asset_type="AGENT_EXECUTION_RESULT",
            agent_execution_id=f"execution-{suffix}",
            actor_type="AGENT",
            actor_ref=f"agent-{suffix}",
            agent_type_snapshot="IA",
            occurred_at=now,
            classification="CONFIDENTIAL",
            bindings=tuple(bindings),
        )

    primary = evidence("result-1", "7")
    primary_asset = asset(evidence_id(primary))
    service = runtime.evidence_admission_service
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            first_pair = list(
                executor.map(
                    lambda _index: service.admit_normalized_evidence(
                        primary,
                        primary_asset,
                    ),
                    range(2),
                )
            )
        assert first_pair[0] == first_pair[1]
        assert first_pair[0].asset.version == 1

        supporting = evidence("result-2", "8")
        expanded_asset = asset(evidence_id(primary), evidence_id(supporting))
        with ThreadPoolExecutor(max_workers=2) as executor:
            updated_pair = list(
                executor.map(
                    lambda _index: service.admit_normalized_evidence(
                        supporting,
                        expanded_asset,
                    ),
                    range(2),
                )
            )
        assert updated_pair[0] == updated_pair[1]
        assert updated_pair[0].asset.version == 2

        with runtime.api_engine.connect() as connection:
            counts = connection.execute(
                text(
                    "SELECT "
                    "(SELECT count(*) FROM wa_work_evidence WHERE tenant_id=:tenant_id), "
                    "(SELECT count(*) FROM wa_work_asset WHERE tenant_id=:tenant_id), "
                    "(SELECT count(*) FROM wa_work_asset_evidence WHERE tenant_id=:tenant_id)"
                ),
                {"tenant_id": tenant_id},
            ).one()
        assert tuple(counts) == (2, 1, 2)
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
            counts = connection.execute(
                text(
                    "SELECT "
                    "(SELECT count(*) FROM wa_work_evidence WHERE tenant_id=:tenant_id), "
                    "(SELECT count(*) FROM wa_work_asset WHERE tenant_id=:tenant_id), "
                    "(SELECT count(*) FROM wa_work_asset_evidence WHERE tenant_id=:tenant_id)"
                ),
                {"tenant_id": tenant_id},
            ).one()
        assert tuple(counts) == (0, 0, 0)
        runtime.dispose()
