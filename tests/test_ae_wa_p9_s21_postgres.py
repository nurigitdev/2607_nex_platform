from __future__ import annotations

import os

import pytest
from nex_ae_api.agent_results import SqlAlchemyAgentResultRepository
from nex_ae_api.artifacts import SqlAlchemyArtifactRecordStore
from nex_ae_api.wa_source_projections import (
    SqlAlchemyAgentResultWaProjectionSource,
    SqlAlchemyArtifactWaProjectionSource,
)
from nex_runtime.postgres_targets import resolve_postgres_test_targets
from run_migrations import run_service_migrations
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

pytestmark = pytest.mark.skipif(
    os.getenv("NEX_WA_P9_S21_POSTGRES_SMOKE") != "1",
    reason="set NEX_WA_P9_S21_POSTGRES_SMOKE=1 for the P9-S21 PostgreSQL smoke",
)


def test_p9_s21_actual_postgres_bounded_reconciliation_queries() -> None:
    target = resolve_postgres_test_targets(
        os.environ,
        service_ids=("nex-ae-api",),
    )[0]
    run_service_migrations(
        "nex-ae-api",
        database_url=target.database_url,
        profile="test",
    )
    engine = create_engine(target.database_url)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        with engine.connect() as connection:
            assert tuple(
                connection.execute(
                    text("SELECT current_database(), current_user")
                ).one()
            ) == ("nex_ae_test", "nex_ae_user")
        window = {
            "tenant_id": "P9-S21-NO-RESIDUE",
            "created_after": "2099-01-01T00:00:00Z",
            "created_before": "2100-01-01T00:00:00Z",
            "limit": 25,
            "cursor": None,
        }
        agent_page = SqlAlchemyAgentResultWaProjectionSource(
            SqlAlchemyAgentResultRepository(sessions)
        ).list_projections(**window)
        artifact_page = SqlAlchemyArtifactWaProjectionSource(
            SqlAlchemyArtifactRecordStore(sessions)
        ).list_projections(**window)
        assert agent_page["items"] == []
        assert artifact_page["items"] == []
        assert agent_page["pagination"]["has_more"] is False
        assert artifact_page["pagination"]["has_more"] is False
    finally:
        engine.dispose()
