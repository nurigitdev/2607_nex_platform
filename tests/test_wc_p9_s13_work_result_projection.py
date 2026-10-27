from __future__ import annotations

import json
from copy import deepcopy

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from nex_runtime import issue_mock_service_token
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from nex_wc.work_result_source_projection import (
    WorkResultWaProjectionSource,
    build_work_result_wa_projection,
    register_wa_work_result_source_routes,
)
from nex_wc.work_results import (
    InMemoryWorkResultRepository,
    SqlAlchemyWorkResultRepository,
    WorkResultError,
)
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

TENANT = "VO00"
RESULT_ID = "result-001"
EXECUTION_ID = "execution-001"
WORK_ITEM_ID = "11111111-1111-4111-8111-111111111111"
CLAIM_ID = "22222222-2222-4222-8222-222222222222"
ASSIGNMENT_ID = "33333333-3333-4333-8333-333333333333"
AGENT_ID = "44444444-4444-4444-8444-444444444444"


def _record() -> dict:
    payload = {
        "schema_version": "2.1",
        "tenant_id": TENANT,
        "result_id": RESULT_ID,
        "work_item_id": WORK_ITEM_ID,
        "revision_no": 1,
        "result_type": "REPORT",
        "schema_ref": "schema:report:v1",
        "technical_outcome": "SUCCEEDED",
        "business_outcome": "VERIFIED",
        "source_execution_ref": EXECUTION_ID,
        "claim_ref": CLAIM_ID,
        "claim_generation": 1,
        "assignment_ref": ASSIGNMENT_ID,
        "submitted_by": {"entity_type": "AGENT", "entity_id": AGENT_ID},
        "trace": {"correlation_id": "correlation-001"},
        "submitted_at": "2026-10-28T02:00:00Z",
        "payload": {"raw": "must-not-leak"},
        "summary": "must-not-leak",
    }
    return {
        "tenant_id": TENANT,
        "result_id": RESULT_ID,
        "work_item_id": WORK_ITEM_ID,
        "revision_no": 1,
        "result_hash": semantic_sha256_hash_ref(payload),
        "source_execution_ref": EXECUTION_ID,
        "claim_id": CLAIM_ID,
        "claim_generation": 1,
        "assignment_id": ASSIGNMENT_ID,
        "submitted_agent_id": AGENT_ID,
        "submitted_at": "2026-10-28T02:00:00Z",
        "work_result": payload,
    }


class _Repository:
    def __init__(self, records=None) -> None:
        self.records = list(records or [])

    def get_result_source(self, *, tenant_id, result_id):
        return next(
            (
                record
                for record in self.records
                if record["tenant_id"] == tenant_id
                and record["result_id"] == result_id
            ),
            None,
        )

    def list_result_sources_by_execution(
        self, *, tenant_id, source_execution_ref, limit
    ):
        return [
            record
            for record in self.records
            if record["tenant_id"] == tenant_id
            and record["source_execution_ref"] == source_execution_ref
        ][:limit]


def _client(records=None, *, source=True) -> TestClient:
    app = FastAPI()
    projection_source = (
        WorkResultWaProjectionSource(_Repository(records)) if source else None
    )
    register_wa_work_result_source_routes(app, source=projection_source)
    return TestClient(app)


def _headers(*, service_id="nex-wa", scopes=None, tenant=TENANT):
    token = issue_mock_service_token(
        service_id=service_id,
        audience="nex-wc",
        scopes=scopes or ["service:call", "work:source:read"],
    ).access_token
    return {"Authorization": f"Bearer {token}", "X-NeX-Tenant-Id": tenant}


@pytest.mark.parametrize(
    "path",
    [
        f"/internal/v1/wa-sources/work-results/{RESULT_ID}",
        f"/internal/v1/wa-sources/work-results/by-execution/{EXECUTION_ID}",
    ],
)
def test_exact_and_by_execution_routes_return_bounded_projection(path) -> None:
    response = _client([_record()]).get(path, headers=_headers())
    assert response.status_code == 200
    payload = response.json()
    assert payload["source_execution_ref"] == EXECUTION_ID
    assert payload["claim_generation"] == 1
    serialized = json.dumps(payload)
    assert "payload" not in serialized
    assert "must-not-leak" not in serialized


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_execution_ref", "other-execution"),
        ("claim_generation", 2),
        ("assignment_id", "other-assignment"),
        ("submitted_agent_id", "other-agent"),
    ],
)
def test_projection_fails_closed_on_scalar_lineage_drift(field, value) -> None:
    record = _record()
    record[field] = value
    with pytest.raises(WorkResultError, match="scalar lineage"):
        build_work_result_wa_projection(record)


def test_projection_fails_closed_on_semantic_hash_and_payload_shape() -> None:
    hash_drift = _record()
    hash_drift["result_hash"] = "sha256:" + "0" * 64
    with pytest.raises(WorkResultError, match="semantic hash"):
        build_work_result_wa_projection(hash_drift)

    missing_payload = _record()
    missing_payload["work_result"] = None
    with pytest.raises(WorkResultError, match="payload"):
        build_work_result_wa_projection(missing_payload)

    missing_submitter = _record()
    missing_submitter["work_result"] = {**missing_submitter["work_result"]}
    missing_submitter["work_result"]["submitted_by"] = None
    missing_submitter["result_hash"] = semantic_sha256_hash_ref(
        missing_submitter["work_result"]
    )
    with pytest.raises(WorkResultError, match="submitted Agent"):
        build_work_result_wa_projection(missing_submitter)


def test_duplicate_by_execution_is_ambiguous() -> None:
    duplicate = deepcopy(_record())
    duplicate["result_id"] = "result-002"
    duplicate["work_result"]["result_id"] = "result-002"
    duplicate["result_hash"] = semantic_sha256_hash_ref(duplicate["work_result"])
    response = _client([_record(), duplicate]).get(
        f"/internal/v1/wa-sources/work-results/by-execution/{EXECUTION_ID}",
        headers=_headers(),
    )
    assert response.status_code == 409
    assert response.json()["error_code"] == "wc.wa_source_result_ambiguous"


def test_by_execution_selects_latest_revision_and_reports_predecessor() -> None:
    previous = _record()
    current = deepcopy(previous)
    current["result_id"] = "result-002"
    current["revision_no"] = 2
    current["submitted_at"] = "2026-10-28T03:00:00Z"
    current["work_result"].update(
        {
            "result_id": "result-002",
            "revision_no": 2,
            "submitted_at": "2026-10-28T03:00:00Z",
        }
    )
    current["result_hash"] = semantic_sha256_hash_ref(current["work_result"])

    response = _client([previous, current]).get(
        f"/internal/v1/wa-sources/work-results/by-execution/{EXECUTION_ID}",
        headers=_headers(),
    )
    assert response.status_code == 200
    assert response.json()["result_id"] == "result-002"
    assert response.json()["supersedes_result_id"] == RESULT_ID
    assert response.json()["supersedes_revision_no"] == 1


def test_by_execution_rejects_revisions_from_different_lineage() -> None:
    previous = _record()
    current = deepcopy(previous)
    current["result_id"] = "result-002"
    current["revision_no"] = 2
    current["work_item_id"] = "55555555-5555-4555-8555-555555555555"
    current["work_result"].update(
        {
            "result_id": "result-002",
            "revision_no": 2,
            "work_item_id": current["work_item_id"],
        }
    )
    current["result_hash"] = semantic_sha256_hash_ref(current["work_result"])
    response = _client([previous, current]).get(
        f"/internal/v1/wa-sources/work-results/by-execution/{EXECUTION_ID}",
        headers=_headers(),
    )
    assert response.status_code == 409
    assert response.json()["error_code"] == "wc.wa_source_result_ambiguous"


def test_routes_map_invalid_lineage_and_empty_execution_lookup() -> None:
    invalid = _record()
    invalid["claim_generation"] = 2
    invalid_response = _client([invalid]).get(
        f"/internal/v1/wa-sources/work-results/{RESULT_ID}",
        headers=_headers(),
    )
    assert invalid_response.status_code == 409

    missing_response = _client([]).get(
        f"/internal/v1/wa-sources/work-results/by-execution/{EXECUTION_ID}",
        headers=_headers(),
    )
    assert missing_response.status_code == 404


@pytest.mark.parametrize(
    ("headers", "status"),
    [
        ({"X-NeX-Tenant-Id": TENANT}, 401),
        (_headers(scopes=["service:call"]), 401),
        (_headers(service_id="nex-ag"), 403),
        (_headers(tenant="other-tenant"), 404),
    ],
)
def test_routes_fail_closed_for_auth_scope_caller_and_tenant(headers, status) -> None:
    response = _client([_record()]).get(
        f"/internal/v1/wa-sources/work-results/{RESULT_ID}",
        headers=headers,
    )
    assert response.status_code == status


def test_routes_require_tenant_and_available_source() -> None:
    headers = _headers()
    headers.pop("X-NeX-Tenant-Id")
    path = f"/internal/v1/wa-sources/work-results/{RESULT_ID}"
    assert _client([_record()]).get(path, headers=headers).status_code == 400
    assert _client(source=False).get(path, headers=_headers()).status_code == 503

    by_execution = (
        f"/internal/v1/wa-sources/work-results/by-execution/{EXECUTION_ID}"
    )
    assert _client([_record()]).get(by_execution).status_code == 401
    assert _client(source=False).get(
        by_execution,
        headers=_headers(),
    ).status_code == 503


def test_by_execution_rejects_repository_execution_mismatch() -> None:
    class _MismatchedRepository(_Repository):
        def list_result_sources_by_execution(self, **kwargs):
            record = _record()
            record["source_execution_ref"] = "other-execution"
            record["work_result"]["source_execution_ref"] = "other-execution"
            record["result_hash"] = semantic_sha256_hash_ref(record["work_result"])
            return [record]

    source = WorkResultWaProjectionSource(_MismatchedRepository())
    with pytest.raises(WorkResultError, match="mismatched"):
        source.get_by_execution(
            tenant_id=TENANT,
            agent_execution_id=EXECUTION_ID,
        )


def test_in_memory_repository_supports_exact_and_by_execution_lookup() -> None:
    repository = InMemoryWorkResultRepository(None)
    repository._results[(TENANT, RESULT_ID)] = _record()

    assert repository.get_result_source(
        tenant_id=TENANT,
        result_id=RESULT_ID,
    )["result_id"] == RESULT_ID
    assert repository.get_result_source(
        tenant_id="other-tenant",
        result_id=RESULT_ID,
    ) is None
    assert len(
        repository.list_result_sources_by_execution(
            tenant_id=TENANT,
            source_execution_ref=EXECUTION_ID,
            limit=2,
        )
    ) == 1


def test_sqlalchemy_repository_supports_exact_and_by_execution_lookup() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    factory = sessionmaker(bind=engine)
    record = _record()
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE wc_work_result ("
                "tenant_id TEXT NOT NULL, result_id TEXT NOT NULL, "
                "work_item_id TEXT NOT NULL, revision_no INTEGER NOT NULL, "
                "result_hash TEXT NOT NULL, result_payload TEXT NOT NULL, "
                "source_execution_ref TEXT NOT NULL, claim_id TEXT NOT NULL, "
                "claim_generation INTEGER NOT NULL, assignment_id TEXT NOT NULL, "
                "submitted_agent_id TEXT NOT NULL, submitted_at TEXT NOT NULL)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO wc_work_result VALUES ("
                ":tenant_id, :result_id, :work_item_id, :revision_no, :result_hash, "
                ":result_payload, :source_execution_ref, :claim_id, "
                ":claim_generation, :assignment_id, :submitted_agent_id, "
                ":submitted_at)"
            ),
            {**record, "result_payload": json.dumps(record["work_result"])},
        )

    repository = SqlAlchemyWorkResultRepository(factory)
    exact = repository.get_result_source(tenant_id=TENANT, result_id=RESULT_ID)
    assert exact is not None
    assert exact["work_result"]["result_id"] == RESULT_ID
    assert repository.get_result_source(
        tenant_id=TENANT,
        result_id="missing",
    ) is None
    by_execution = repository.list_result_sources_by_execution(
        tenant_id=TENANT,
        source_execution_ref=EXECUTION_ID,
        limit=2,
    )
    assert len(by_execution) == 1
    assert by_execution[0]["result_id"] == RESULT_ID
