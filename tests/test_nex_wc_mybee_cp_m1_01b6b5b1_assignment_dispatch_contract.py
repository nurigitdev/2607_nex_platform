from __future__ import annotations

import copy
import os
from pathlib import Path

import pytest
from nex_wc.assignment_dispatch import (
    CLAIM,
    RELOAD,
    RETRY,
    ROUTE,
    TERMINAL,
    AssignmentDispatchContractError,
    action_for_work_item_state,
    build_assignment_dispatch_job,
    claimable_cursor,
    classify_assignment_dispatch_failure,
    project_claimable_work_item,
    validate_assignment_dispatch_job,
    validate_claimable_scan,
    validate_claimable_work_item,
)
from nex_wc.coordination import (
    InMemoryCoordinationRepository,
    SqlAlchemyCoordinationRepository,
)
from nex_wc.work_items import InMemoryWorkItemRepository, SqlAlchemyWorkItemRepository
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
NOW = "2026-11-18T01:00:00Z"


def _record(
    *,
    tenant_id: str = "tenant-b5b1",
    work_item_id: str = "11111111-1111-4111-8111-111111115101",
    state: str = "CREATED",
    version: int = 1,
    created_at: str = NOW,
) -> dict[str, object]:
    return {
        "tenant_id": tenant_id,
        "work_item_id": work_item_id,
        "state": state,
        "version": version,
        "created_at": created_at,
        "updated_at": created_at,
        "work_item": {
            "trace": {"correlation_id": f"trace-{tenant_id}-{work_item_id}"}
        },
    }


def _candidate(**overrides: object) -> dict[str, object]:
    candidate = project_claimable_work_item(_record())
    candidate.update(overrides)
    return candidate


def test_claimable_scan_is_state_bounded_keyset_paginated_and_private() -> None:
    work_items = InMemoryWorkItemRepository()
    records = [
        _record(
            tenant_id="tenant-b",
            work_item_id="22222222-2222-4222-8222-222222225102",
            created_at="2026-11-18T01:00:02Z",
        ),
        _record(
            tenant_id="tenant-a",
            work_item_id="11111111-1111-4111-8111-111111115102",
            created_at="2026-11-18T01:00:01Z",
        ),
        _record(
            tenant_id="tenant-a",
            work_item_id="33333333-3333-4333-8333-333333335102",
            state="ROUTED",
            version=2,
            created_at="2026-11-18T01:00:00Z",
        ),
        _record(
            tenant_id="tenant-a",
            work_item_id="44444444-4444-4444-8444-444444445102",
            state="ASSIGNED",
            version=3,
            created_at="2026-11-18T00:59:59Z",
        ),
    ]
    for record in records:
        key = (str(record["tenant_id"]), str(record["work_item_id"]))
        work_items._records[key] = copy.deepcopy(record)
    repository = InMemoryCoordinationRepository(work_items)

    first_page = repository.list_claimable_work_items(state="CREATED", limit=1)
    second_page = repository.list_claimable_work_items(
        state="CREATED",
        limit=5,
        after=claimable_cursor(first_page[0]),
    )
    routed = repository.list_claimable_work_items(state="ROUTED", limit=5)

    assert [item["tenant_id"] for item in first_page + second_page] == [
        "tenant-a",
        "tenant-b",
    ]
    assert routed[0]["action"] == CLAIM
    assert routed[0]["expected_version"] == 2
    assert set(first_page[0]) == {
        "schema_version",
        "tenant_id",
        "work_item_id",
        "state",
        "action",
        "expected_version",
        "trace_id",
        "created_at",
        "updated_at",
    }
    assert "work_item" not in first_page[0]


@pytest.mark.parametrize(
    ("kwargs", "error_code"),
    (
        ({"state": "ASSIGNED", "limit": 1}, "wc.assignment_dispatch_state_invalid"),
        ({"state": "CREATED", "limit": True}, "wc.assignment_dispatch_limit_invalid"),
        ({"state": "CREATED", "limit": 0}, "wc.assignment_dispatch_limit_invalid"),
        ({"state": "CREATED", "limit": 501}, "wc.assignment_dispatch_limit_invalid"),
        (
            {"state": "CREATED", "limit": 1, "after": {"created_at": NOW}},
            "wc.assignment_dispatch_cursor_invalid",
        ),
    ),
)
def test_claimable_scan_rejects_unbounded_or_malformed_requests(
    kwargs: dict[str, object], error_code: str
) -> None:
    with pytest.raises(AssignmentDispatchContractError) as error:
        validate_claimable_scan(**kwargs)
    assert error.value.error_code == error_code


def test_claimable_projection_and_action_contract_fail_closed() -> None:
    assert action_for_work_item_state("CREATED") == ROUTE
    assert action_for_work_item_state("ROUTED") == CLAIM
    with pytest.raises(AssignmentDispatchContractError) as terminal:
        action_for_work_item_state("CLOSED")
    assert terminal.value.error_code == "wc.assignment_dispatch_state_terminal"

    for invalid in (
        _record(version=0),
        {**_record(), "tenant_id": ""},
        {**_record(), "work_item": {}},
    ):
        with pytest.raises(AssignmentDispatchContractError):
            project_claimable_work_item(invalid)

    with pytest.raises(AssignmentDispatchContractError):
        validate_claimable_work_item({**_candidate(), "private": "not-admitted"})
    with pytest.raises(AssignmentDispatchContractError):
        validate_claimable_work_item({**_candidate(), "action": CLAIM})


def test_dispatch_job_identity_is_deterministic_versioned_and_content_minimal() -> None:
    candidate = _candidate()
    first = build_assignment_dispatch_job(candidate, created_at=NOW)
    replay = build_assignment_dispatch_job(candidate, created_at=NOW)
    routed = build_assignment_dispatch_job(
        _candidate(state="ROUTED", action=CLAIM, expected_version=2),
        created_at=NOW,
    )

    assert first == replay
    assert first["job_id"] != routed["job_id"]
    assert first["idempotency_key"] != routed["idempotency_key"]
    assert first["payload"] == {
        "schema_version": "wc_assignment_dispatch.v1",
        "tenant_id": "tenant-b5b1",
        "work_item_id": "11111111-1111-4111-8111-111111115101",
        "expected_version": 1,
        "action": "ROUTE",
    }
    assert first["max_attempts"] == 5
    assert first["subject_ref"] == {
        "type": "WC_WORK_ITEM",
        "id": candidate["work_item_id"],
    }
    assert "goal" not in str(first)
    assert validate_assignment_dispatch_job(first) == first


@pytest.mark.parametrize(
    ("mutator", "error_code"),
    (
        (
            lambda job: job.update(job_type="OTHER"),
            "wc.assignment_dispatch_job_type_invalid",
        ),
        (
            lambda job: job["payload"].update(extra="value"),
            "wc.assignment_dispatch_job_payload_invalid",
        ),
        (
            lambda job: job["payload"].update(schema_version="v2"),
            "wc.assignment_dispatch_schema_invalid",
        ),
        (
            lambda job: job["payload"].update(action="EXECUTE"),
            "wc.assignment_dispatch_action_invalid",
        ),
        (
            lambda job: job["payload"].update(expected_version=0),
            "wc.assignment_dispatch_version_invalid",
        ),
        (
            lambda job: job.update(subject_ref={"type": "OTHER", "id": "other"}),
            "wc.assignment_dispatch_subject_invalid",
        ),
        (
            lambda job: job.update(request_id="other"),
            "wc.assignment_dispatch_request_invalid",
        ),
        (
            lambda job: job.update(links={}),
            "wc.assignment_dispatch_links_invalid",
        ),
        (
            lambda job: job.update(idempotency_key="wrong"),
            "wc.assignment_dispatch_identity_invalid",
        ),
        (
            lambda job: job.update(job_id="wrong"),
            "wc.assignment_dispatch_identity_invalid",
        ),
    ),
)
def test_dispatch_job_tampering_fails_closed(mutator, error_code: str) -> None:
    job = build_assignment_dispatch_job(_candidate(), created_at=NOW)
    mutator(job)
    with pytest.raises(AssignmentDispatchContractError) as error:
        validate_assignment_dispatch_job(job)
    assert error.value.error_code == error_code


@pytest.mark.parametrize(
    ("error_code", "retryable", "expected"),
    (
        ("wc.assignment_no_eligible_agent", False, RETRY),
        ("wc.agent_registry_unavailable", True, RETRY),
        ("wc.work_item_route_conflict", False, RELOAD),
        ("wc.work_item_claim_conflict", False, RELOAD),
        ("wc.active_claim_exists", False, RELOAD),
        ("wc.claim_authorization_denied", False, TERMINAL),
        ("wc.routing_decision_not_claimable", False, TERMINAL),
        ("wc.unknown", False, TERMINAL),
    ),
)
def test_dispatch_failure_disposition_is_explicit(
    error_code: str, retryable: bool, expected: str
) -> None:
    assert (
        classify_assignment_dispatch_failure(
            error_code=error_code, retryable=retryable
        )
        == expected
    )


def test_dispatch_failure_disposition_rejects_invalid_metadata() -> None:
    with pytest.raises(AssignmentDispatchContractError):
        classify_assignment_dispatch_failure(error_code="", retryable=False)
    with pytest.raises(AssignmentDispatchContractError):
        classify_assignment_dispatch_failure(error_code="wc.error", retryable="yes")


def test_dispatch_scan_migration_is_partial_and_matches_query_order() -> None:
    migration = (
        ROOT
        / "database/nex-wc/migrations/1007_wc_assignment_dispatch_scan.sql"
    ).read_text(encoding="utf-8")
    assert "ix_wc_work_item_dispatch_scan" in migration
    assert "(state, created_at, tenant_id, work_item_id)" in migration
    assert "WHERE state IN ('CREATED', 'ROUTED')" in migration
    assert "CREATE TABLE" not in migration


@pytest.mark.skipif(
    not os.getenv("NEX_WC_TEST_DATABASE_URL"),
    reason="NEX_WC_TEST_DATABASE_URL is required for protected WC PostgreSQL smoke",
)
def test_actual_postgres_claimable_scan_uses_admitted_index_and_leaves_no_residue() -> None:
    engine = create_engine(os.environ["NEX_WC_TEST_DATABASE_URL"])
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    tenant = "cp-m1-01b6b5b1"
    work_item_id = "55555555-5555-4555-8555-555555555501"
    repository = SqlAlchemyCoordinationRepository(sessions)
    with engine.begin() as connection:
        connection.execute(
            text("DELETE FROM wc_work_item WHERE tenant_id = :tenant_id"),
            {"tenant_id": tenant},
        )
    try:
        record = _record(tenant_id=tenant, work_item_id=work_item_id)
        record.update(
            {
                "idempotency_key": "sha256:" + "1" * 64,
                "delegation_semantic_hash": "sha256:" + "2" * 64,
                "delegation_spec": {},
                "source_type": "AGENT_PLAN_STEP",
                "parent_execution_id": "execution-b5b1",
                "parent_plan_id": "plan-b5b1",
                "parent_step_id": "step-b5b1",
                "delegation_revision": 1,
                "project_id": "project-b5b1",
                "required_agent_type": "PA",
                "create_authorization_revision_hash": "sha256:" + "3" * 64,
                "create_authorization_checked_at": NOW,
                "create_authorized_subject_id": "user-b5b1",
            }
        )
        SqlAlchemyWorkItemRepository(sessions).create(record)
        candidates = repository.list_claimable_work_items(
            state="CREATED", limit=100
        )
        admitted = next(item for item in candidates if item["tenant_id"] == tenant)
        assert admitted["work_item_id"] == work_item_id
        assert admitted["action"] == ROUTE
        after = repository.list_claimable_work_items(
            state="CREATED",
            limit=100,
            after=claimable_cursor(admitted),
        )
        assert all(item["work_item_id"] != work_item_id for item in after)
        with engine.connect() as connection:
            index_definition = connection.execute(
                text(
                    "SELECT indexdef FROM pg_indexes "
                    "WHERE schemaname = current_schema() "
                    "AND indexname = 'ix_wc_work_item_dispatch_scan'"
                )
            ).scalar_one()
            migration_applied = connection.execute(
                text(
                    "SELECT count(*) FROM schema_migrations "
                    "WHERE version = '1007_wc_assignment_dispatch_scan'"
                )
            ).scalar_one()
        assert "state, created_at, tenant_id, work_item_id" in index_definition
        assert "WHERE (state = ANY" in index_definition
        assert migration_applied == 1
    finally:
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM wc_work_item WHERE tenant_id = :tenant_id"),
                {"tenant_id": tenant},
            )
            remaining = connection.execute(
                text("SELECT count(*) FROM wc_work_item WHERE tenant_id = :tenant_id"),
                {"tenant_id": tenant},
            ).scalar_one()
        engine.dispose()
    assert remaining == 0
