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
    SqlAlchemyWorkEvidenceRepository,
    WorkEvidenceError,
    WorkEvidenceInput,
    build_wa_persistence_runtime,
)
from run_migrations import run_service_migrations
from sqlalchemy import text

pytestmark = pytest.mark.skipif(
    os.getenv("NEX_WA_P9_S03_POSTGRES_SMOKE") != "1",
    reason="set NEX_WA_P9_S03_POSTGRES_SMOKE=1 for actual nex_wa_test smoke",
)


def test_actual_postgres_work_evidence_identity_conflict_and_supersession() -> None:
    target = resolve_postgres_test_targets(
        os.environ,
        service_ids=("nex-wa",),
    )[0]
    database_url = target.database_url
    with (
        psycopg.connect(psycopg_database_url(database_url), autocommit=True) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute("SELECT current_database(), current_user")
        assert cursor.fetchone() == ("nex_wa_test", "nex_wa_user")

    migration = run_service_migrations(
        "nex-wa",
        database_url=database_url,
        profile="test",
    )
    assert migration.planned == WA_REQUIRED_MIGRATIONS

    runtime = build_wa_persistence_runtime(
        environ={"NEX_WA_TEST_DATABASE_URL": database_url},
        database_env="NEX_WA_TEST_DATABASE_URL",
    )
    repository: SqlAlchemyWorkEvidenceRepository = runtime.work_evidence_repository
    suffix = uuid4().hex
    tenant_id = f"P9S03-{suffix}"
    now = datetime.now(UTC)

    def candidate(**overrides: object) -> WorkEvidenceInput:
        values: dict[str, object] = {
            "tenant_id": tenant_id,
            "source_owner": "nex-ae-api",
            "source_type": "AE_ARTIFACT",
            "source_ref": f"artifact-{suffix}",
            "source_revision_ref": "version-1",
            "source_hash": "sha256:" + "d" * 64,
            "evidence_kind": "OWNERSHIP_OR_DELIVERABLE_EVIDENCE",
            "actor_type": "HUMAN",
            "actor_ref": f"subject-{suffix}",
            "occurred_at": now,
            "observed_at": now + timedelta(seconds=1),
            "classification": "CONFIDENTIAL",
        }
        values.update(overrides)
        return WorkEvidenceInput(**values)  # type: ignore[arg-type]

    try:
        first = repository.create_or_get(candidate())
        assert repository.create_or_get(
            candidate(observed_at=now + timedelta(minutes=1))
        ) == first
        with pytest.raises(WorkEvidenceError) as conflict:
            repository.create_or_get(candidate(source_hash="sha256:" + "e" * 64))
        assert conflict.value.error_code == "WA_SOURCE_IDEMPOTENCY_CONFLICT"

        correction = repository.create_or_get(
            candidate(
                source_revision_ref="version-2",
                source_hash="sha256:" + "f" * 64,
                supersedes_evidence_id=first.work_evidence_id,
            )
        )
        assert correction.supersedes_evidence_id == first.work_evidence_id
        assert correction.work_evidence_id != first.work_evidence_id

        with runtime.api_engine.connect() as connection:
            assert connection.execute(
                text(
                    "SELECT count(*) FROM wa_work_evidence "
                    "WHERE tenant_id = :tenant_id"
                ),
                {"tenant_id": tenant_id},
            ).scalar_one() == 2
    finally:
        with runtime.api_engine.begin() as connection:
            connection.execute(
                text("DELETE FROM wa_work_evidence WHERE tenant_id = :tenant_id"),
                {"tenant_id": tenant_id},
            )
        with runtime.api_engine.connect() as connection:
            assert connection.execute(
                text(
                    "SELECT count(*) FROM wa_work_evidence "
                    "WHERE tenant_id = :tenant_id"
                ),
                {"tenant_id": tenant_id},
            ).scalar_one() == 0
        runtime.dispose()
