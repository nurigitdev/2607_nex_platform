from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from nex_oa.identity_lifecycle import (
    OaIdentityLifecycleError,
    plan_membership_status_transition,
    plan_subject_status_transition,
)
from nex_oa.identity_lifecycle_repository import (
    InMemoryOaIdentityLifecycleRepository,
    SqlAlchemyOaIdentityLifecycleRepository,
    _context_text,
    _event_limit,
    _timestamp_to_wire,
    build_identity_lifecycle_repository_for_runtime,
)
from nex_oa.memberships import (
    InMemoryOaTenantMembershipRegistry,
    SqlAlchemyOaTenantMembershipRegistry,
)
from nex_oa.subjects import InMemoryOaSubjectRegistry, SqlAlchemyOaSubjectRegistry
from nex_runtime import build_engine, build_session_factory


CONTEXT = {
    "actor_ref_type": "nex.service",
    "actor_ref_id": "nex-ag",
    "request_id": "request-1215",
    "trace_id": "1234567890abcdef1234567890abcdef",
}


def _memory_repositories():
    subjects = InMemoryOaSubjectRegistry()
    memberships = InMemoryOaTenantMembershipRegistry(subject_registry=subjects)
    snapshot = memberships.ensure_membership(
        {"tenant_id": "tenant-a", "subject_id": "employee-a"}
    )
    repository = InMemoryOaIdentityLifecycleRepository(subjects, memberships)
    return subjects, memberships, repository, snapshot


def _sqlite_repositories():
    engine = build_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        for statement in (
            """
            CREATE TABLE oa_tenants (
                tenant_id TEXT PRIMARY KEY, tenant_ref_type TEXT NOT NULL,
                display_name TEXT NOT NULL, status TEXT NOT NULL,
                metadata TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE oa_subjects (
                tenant_id TEXT NOT NULL, subject_id TEXT NOT NULL,
                subject_ref_type TEXT NOT NULL, display_name TEXT NOT NULL,
                status TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
                metadata TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                PRIMARY KEY (tenant_id, subject_ref_type, subject_id)
            )
            """,
            """
            CREATE TABLE oa_tenant_memberships (
                tenant_id TEXT NOT NULL, subject_ref_type TEXT NOT NULL,
                subject_id TEXT NOT NULL, membership_schema_version TEXT NOT NULL,
                status TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
                roles TEXT NOT NULL, scopes TEXT NOT NULL, metadata TEXT NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                PRIMARY KEY (tenant_id, subject_ref_type, subject_id)
            )
            """,
            """
            CREATE TABLE oa_id_lifecycle_events (
                event_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL,
                subject_id TEXT NOT NULL, entity_type TEXT NOT NULL,
                previous_status TEXT NOT NULL, target_status TEXT NOT NULL,
                previous_revision INTEGER NOT NULL, next_revision INTEGER NOT NULL,
                reason_code TEXT NOT NULL, actor_ref_type TEXT NOT NULL,
                actor_ref_id TEXT NOT NULL, request_id TEXT NOT NULL,
                trace_id TEXT NOT NULL, occurred_at TEXT NOT NULL
            )
            """,
        ):
            connection.execute(text(statement))
    factory = build_session_factory(engine)
    subjects = SqlAlchemyOaSubjectRegistry(factory)
    memberships = SqlAlchemyOaTenantMembershipRegistry(
        factory, subject_registry=subjects
    )
    snapshot = memberships.ensure_membership(
        {"tenant_id": "tenant-sql", "subject_id": "employee-sql"}
    )
    return engine, subjects, memberships, SqlAlchemyOaIdentityLifecycleRepository(factory), snapshot


def test_in_memory_repository_mutates_records_and_appends_events() -> None:
    subjects, memberships, repository, snapshot = _memory_repositories()
    subject_plan = plan_subject_status_transition(
        snapshot["subject_registry_snapshot"],
        target_status="DISABLED",
        expected_revision=1,
        reason_code="admin.subject-disable",
    )
    subject_result = repository.transition_subject(subject_plan, context=CONTEXT)
    membership_plan = plan_membership_status_transition(
        snapshot,
        target_status="DISABLED",
        expected_revision=1,
        reason_code="admin.membership-disable",
    )
    membership_result = repository.transition_membership(
        membership_plan, context=CONTEXT
    )

    assert subject_result["revision"] == 2
    assert membership_result["revision"] == 2
    assert subjects.subjects[("tenant-a", "employee-a")]["status"] == "DISABLED"
    assert memberships.memberships[("tenant-a", "employee-a")]["status"] == "DISABLED"
    events = repository.list_events(
        tenant_id="tenant-a", subject_id="employee-a", limit=1
    )
    assert len(events) == 1
    assert events[0]["entity_type"] == "MEMBERSHIP"
    assert "event_schema_version" in events[0]


def test_in_memory_idempotency_missing_and_conflict_paths() -> None:
    subjects, _, repository, snapshot = _memory_repositories()
    unchanged = plan_subject_status_transition(
        snapshot["subject_registry_snapshot"],
        target_status="ACTIVE",
        expected_revision=1,
    )
    assert repository.transition_subject(unchanged, context=CONTEXT)["event"] is None

    subjects.subjects[("tenant-a", "employee-a")]["revision"] = 2
    with pytest.raises(OaIdentityLifecycleError) as conflict:
        repository.transition_subject(unchanged, context=CONTEXT)
    assert conflict.value.error_code == "oa.lifecycle_revision_conflict"

    missing = {**unchanged, "subject_id": "missing"}
    with pytest.raises(OaIdentityLifecycleError) as not_found:
        repository.transition_subject(missing, context=CONTEXT)
    assert not_found.value.status_code == 404


def test_sql_repository_persists_both_transitions_and_history() -> None:
    engine, subjects, memberships, repository, snapshot = _sqlite_repositories()
    subject_plan = plan_subject_status_transition(
        snapshot["subject_registry_snapshot"],
        target_status="DISABLED",
        expected_revision=1,
        reason_code="admin.subject-disable",
    )
    repository.transition_subject(subject_plan, context=CONTEXT)
    updated_subject = subjects.get_subject(
        tenant_id="tenant-sql", subject_id="employee-sql"
    )
    assert updated_subject["subject"]["revision"] == 2

    membership_plan = plan_membership_status_transition(
        memberships.get_membership(
            tenant_id="tenant-sql", subject_id="employee-sql"
        ),
        target_status="DISABLED",
        expected_revision=1,
        reason_code="admin.membership-disable",
    )
    repository.transition_membership(membership_plan, context=CONTEXT)
    events = repository.list_events(
        tenant_id="tenant-sql", subject_id="employee-sql"
    )
    assert [event["entity_type"] for event in events] == ["MEMBERSHIP", "SUBJECT"]
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT count(*) FROM oa_id_lifecycle_events")
        ).scalar_one() == 2
    engine.dispose()


def test_sql_repository_handles_idempotent_stale_missing_and_unavailable() -> None:
    engine, _, _, repository, snapshot = _sqlite_repositories()
    unchanged = plan_subject_status_transition(
        snapshot["subject_registry_snapshot"],
        target_status="ACTIVE",
        expected_revision=1,
    )
    assert repository.transition_subject(unchanged, context=CONTEXT)["changed"] is False

    changed = plan_subject_status_transition(
        snapshot["subject_registry_snapshot"],
        target_status="DISABLED",
        expected_revision=1,
        reason_code="admin.disable",
    )
    repository.transition_subject(changed, context=CONTEXT)
    with pytest.raises(OaIdentityLifecycleError) as stale:
        repository.transition_subject(changed, context=CONTEXT)
    assert stale.value.status_code == 409

    missing = {**unchanged, "subject_id": "missing"}
    with pytest.raises(OaIdentityLifecycleError) as not_found:
        repository.transition_subject(missing, context=CONTEXT)
    assert not_found.value.status_code == 404
    engine.dispose()

    broken_engine = build_engine("sqlite+pysqlite:///:memory:")
    broken = SqlAlchemyOaIdentityLifecycleRepository(
        build_session_factory(broken_engine)
    )
    with pytest.raises(OaIdentityLifecycleError) as unavailable:
        broken.list_events(tenant_id="tenant-a", subject_id="employee-a")
    assert unavailable.value.status_code == 503
    with pytest.raises(OaIdentityLifecycleError) as transition_unavailable:
        broken.transition_subject(unchanged, context=CONTEXT)
    assert transition_unavailable.value.error_code == "oa.lifecycle_repository_unavailable"
    broken_engine.dispose()


def test_builder_and_validation_helpers_cover_edges() -> None:
    subjects, memberships, _, _ = _memory_repositories()
    memory = build_identity_lifecycle_repository_for_runtime(
        SimpleNamespace(mode="memory", api_session_factory=None),
        subject_registry=subjects,
        membership_registry=memberships,
    )
    assert isinstance(memory, InMemoryOaIdentityLifecycleRepository)

    engine, _, _, sql, _ = _sqlite_repositories()
    built = build_identity_lifecycle_repository_for_runtime(
        SimpleNamespace(mode="postgres", api_session_factory=sql._session_factory),
        subject_registry=subjects,
        membership_registry=memberships,
    )
    assert isinstance(built, SqlAlchemyOaIdentityLifecycleRepository)
    engine.dispose()

    assert _event_limit("500") == 500
    for value in (True, 0, 501, " 1", None):
        with pytest.raises(OaIdentityLifecycleError):
            _event_limit(value)
    assert _context_text({"actor": "value"}, "actor") == "value"
    for value in (None, "", "x" * 129):
        with pytest.raises(OaIdentityLifecycleError):
            _context_text({"actor": value}, "actor")
    assert _timestamp_to_wire(datetime(2026, 1, 1)) == "2026-01-01T00:00:00Z"
    assert _timestamp_to_wire(datetime(2026, 1, 1, tzinfo=UTC)).endswith("Z")
    assert _timestamp_to_wire("wire") == "wire"


def test_migration_uses_short_valid_identifiers() -> None:
    source = (
        __import__("pathlib").Path(__file__).resolve().parents[1]
        / "database/nex-oa/migrations/1215_oa_identity_lifecycle.sql"
    ).read_text(encoding="utf-8")

    assert "ADD COLUMN IF NOT EXISTS revision" in source
    assert "CREATE TABLE IF NOT EXISTS oa_id_lifecycle_events" in source
    assert "1215_oa_identity_lifecycle" in source
    identifiers = [
        token.strip()
        for line in source.splitlines()
        for token in line.strip().split()[1:2]
        if line.strip().startswith(("CONSTRAINT ", "CREATE INDEX "))
    ]
    assert identifiers and all(len(identifier) <= 63 for identifier in identifiers)
