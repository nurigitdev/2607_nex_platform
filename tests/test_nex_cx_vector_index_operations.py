from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from nex_runtime import (
    InMemoryOperationalEventStore,
    OperationalEventEmitter,
    SERVICE_SPECS,
    build_service_app,
    issue_mock_service_token,
)
import nex_cx.main as cx_main
from nex_cx.main import build_cx_vector_operations_dependencies
from nex_cx.private_content import CxPrivateContentError
from nex_cx.vector_index_freshness import (
    build_embedding_profile,
    build_source_snapshot,
    build_vector_index_manifest,
    build_vector_payload_snapshot,
    mark_vector_index_ready,
)
from nex_cx.vector_index_operations import (
    CX_VECTOR_INDEX_RECONCILED_EVENT,
    VectorIndexOperationsError,
    _reconciliation_event_id,
    register_vector_index_operations_routes,
)
from nex_cx.vector_index_repository import (
    InMemoryVectorIndexRepository,
    SqlAlchemyVectorIndexRepository,
    VectorIndexRepositoryError,
)


TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"


def _headers(*, owner: str = "owner-a") -> dict[str, str]:
    token = issue_mock_service_token(service_id="nex-ag", audience="nex-cx")
    return {
        "Authorization": f"Bearer {token.access_token}",
        "X-NEX-Tenant-ID": "tenant-a",
        "X-NEX-Subject-ID": owner,
        "X-Request-ID": "request-0938",
        "traceparent": f"00-{TRACE_ID}-00f067aa0ba902b7-01",
    }


def _parts():
    source = build_source_snapshot(
        chunk_set_id=str(uuid4()),
        chunk_policy_id="1000_100",
        source_markdown_sha256="1" * 64,
        chunks=[
            {"chunk_id": str(uuid4()), "ordinal": 0, "text_sha256": "2" * 64}
        ],
    )
    profile = build_embedding_profile(
        provider_alias="mock",
        model_profile_id="qwen-test",
        model_revision="test",
        deployment_id="local",
        vector_dimension=2,
    )
    building = build_vector_index_manifest(
        content_object_id=str(uuid4()),
        tenant_ref={"type": "oa.tenant", "id": "tenant-a"},
        owner_subject_ref={"type": "oa.user", "id": "owner-a"},
        source_snapshot=source,
        embedding_profile=profile,
        trace_id="trace-0938",
        request_id="request-0938",
        observed_at="2026-09-21T16:00:00Z",
    )
    receipt = {
        "chunk_id": source["chunk_refs"][0]["chunk_id"],
        "embedding_sha256": "3" * 64,
        "vector_dimension": 2,
        "storage_uri": f"cx-private://pgvector/{uuid4()}",
    }
    ready = mark_vector_index_ready(
        building,
        payload_receipts=[receipt],
        observed_at="2026-09-21T16:01:00Z",
    )
    return source, profile, ready, receipt


class _Bound:
    def __init__(self, snapshot):
        self.snapshot = snapshot

    def payload_snapshot(self, *, access_context):
        assert access_context.ownership_key == ("tenant-a", "owner-a")
        if isinstance(self.snapshot, Exception):
            raise self.snapshot
        return deepcopy(self.snapshot)


class _Adapter:
    def __init__(self, snapshot):
        self.bound = _Bound(snapshot)

    def bind_index(self, _manifest):
        return self.bound


class _ExplodingEventStore:
    def append(self, _event):
        raise RuntimeError("unavailable")


def _client(*, repository=None, adapter=None, emitter=None):
    source, profile, ready, receipt = _parts()
    selected_repository = repository or InMemoryVectorIndexRepository()
    if repository is None:
        selected_repository.create(ready)
    selected_adapter = adapter or _Adapter(build_vector_payload_snapshot([receipt]))
    event_store = None
    if emitter is None:
        event_store = InMemoryOperationalEventStore()
        emitter = OperationalEventEmitter(service_id="nex-cx", store=event_store)
    app = build_service_app(SERVICE_SPECS["nex-cx"])
    register_vector_index_operations_routes(
        app,
        repository=selected_repository,
        vector_store=selected_adapter,  # type: ignore[arg-type]
        event_emitter=emitter,
    )
    return TestClient(app), source, profile, ready, event_store


def test_readiness_route_is_owner_scoped_and_payload_verified():
    client, _source, _profile, ready, _events = _client()
    path = f"/api/v1/vector-indexes/{ready['vector_index_id']}/readiness"

    response = client.get(path, headers=_headers())
    hidden = client.get(path, headers=_headers(owner="other"))

    assert response.status_code == 200
    assert response.json() == {
        "readiness_schema_version": "cx_vector_index_readiness.v1",
        "vector_index_id": ready["vector_index_id"],
        "content_object_id": ready["content_object_id"],
        "status": "READY",
        "status_reason": None,
        "freshness_status": "READY",
        "freshness_reason": None,
        "checkpoint_version": 1,
        "expected_vector_count": 1,
        "actual_vector_count": 1,
        "retrieval_usable": True,
        "rebuild_required": False,
        "action": "NONE",
    }
    assert hidden.status_code == 404
    assert hidden.json()["error_code"] == "CX_VECTOR_INDEX_NOT_FOUND"
    assert client.get(path).status_code == 401


def test_reconcile_route_persists_payload_drift_and_emits_redacted_event():
    source, profile, ready, _receipt = _parts()
    repository = InMemoryVectorIndexRepository()
    repository.create(ready)
    client, _s, _p, _ready, event_store = _client(
        repository=repository,
        adapter=_Adapter(build_vector_payload_snapshot([])),
    )
    response = client.post(
        f"/api/v1/vector-indexes/{ready['vector_index_id']}/readiness/reconcile",
        headers=_headers(),
        json={
            "source_snapshot": source,
            "embedding_profile": profile,
            "observed_at": "2026-09-21T16:02:00Z",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["action"] == "ADMIT_REBUILD"
    assert payload["status"] == "REBUILD_REQUIRED"
    assert payload["status_reason"] == "PAYLOAD_COUNT_MISMATCH"
    assert payload["freshness_status"] == "STALE"
    assert payload["freshness_reason"] == "PAYLOAD_COUNT_MISMATCH"
    assert payload["checkpoint_version"] == 3
    assert payload["retrieval_usable"] is False
    assert payload["observability"]["ok"] is True
    assert event_store is not None
    events = event_store.list_events(event_type=CX_VECTOR_INDEX_RECONCILED_EVENT)
    assert len(events) == 1
    assert events[0]["severity"] == "WARNING"
    assert events[0]["subject_ref"] == {
        "type": "cx.vector_index",
        "id": ready["vector_index_id"],
    }
    serialized = str(events[0]).lower()
    assert "embedding_sha256" not in serialized
    assert "source_markdown_sha256" not in serialized


def test_reconcile_current_index_is_noop_and_observability_failure_is_non_blocking():
    emitter = OperationalEventEmitter(
        service_id="nex-cx", store=_ExplodingEventStore()  # type: ignore[arg-type]
    )
    client, source, profile, ready, _events = _client(emitter=emitter)
    response = client.post(
        f"/api/v1/vector-indexes/{ready['vector_index_id']}/readiness/reconcile",
        headers=_headers(),
        json={
            "source_snapshot": source,
            "embedding_profile": profile,
            "observed_at": "2026-09-21T16:02:00Z",
        },
    )

    assert response.status_code == 200
    assert response.json()["action"] == "NONE"
    assert response.json()["status"] == "READY"
    assert response.json()["observability"]["ok"] is False


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"source_snapshot": {}, "embedding_profile": {}, "observed_at": None},
    ],
)
def test_reconcile_rejects_incomplete_request(payload):
    client, _source, _profile, ready, _events = _client()
    response = client.post(
        f"/api/v1/vector-indexes/{ready['vector_index_id']}/readiness/reconcile",
        headers=_headers(),
        json=payload,
    )
    assert response.status_code == 422
    assert response.json()["error_code"] == "CX_VECTOR_RECONCILIATION_REQUEST_INVALID"
    assert (
        client.post(
            f"/api/v1/vector-indexes/{ready['vector_index_id']}/readiness/reconcile",
            json=payload,
        ).status_code
        == 401
    )


def test_unavailable_and_dependency_failures_are_safe_problem_responses():
    app = build_service_app(SERVICE_SPECS["nex-cx"])
    register_vector_index_operations_routes(app, repository=None, vector_store=None)
    unavailable = TestClient(app).get(
        "/api/v1/vector-indexes/index/readiness", headers=_headers()
    )
    assert unavailable.status_code == 503
    assert unavailable.json()["retryable"] is True

    repository = InMemoryVectorIndexRepository()
    vector_missing_app = build_service_app(SERVICE_SPECS["nex-cx"])
    register_vector_index_operations_routes(
        vector_missing_app,
        repository=repository,
        vector_store=None,
    )
    vector_missing = TestClient(vector_missing_app).get(
        "/api/v1/vector-indexes/index/readiness", headers=_headers()
    )
    assert vector_missing.status_code == 503

    client, _source, _profile, ready, _events = _client(
        adapter=_Adapter(
            CxPrivateContentError(
                status_code=503,
                error_code="CX_PGVECTOR_STORAGE_UNAVAILABLE",
                detail="Vector storage is unavailable.",
                retryable=True,
            )
        )
    )
    failed = client.get(
        f"/api/v1/vector-indexes/{ready['vector_index_id']}/readiness",
        headers=_headers(),
    )
    assert failed.status_code == 503
    assert failed.json()["error_code"] == "CX_PGVECTOR_STORAGE_UNAVAILABLE"


def test_reconcile_maps_payload_and_repository_save_failures():
    failing_adapter = _Adapter(
        CxPrivateContentError(
            status_code=503,
            error_code="CX_PGVECTOR_STORAGE_UNAVAILABLE",
            detail="Vector storage is unavailable.",
            retryable=True,
        )
    )
    client, source, profile, ready, _events = _client(adapter=failing_adapter)
    path = f"/api/v1/vector-indexes/{ready['vector_index_id']}/readiness/reconcile"
    request = {
        "source_snapshot": source,
        "embedding_profile": profile,
        "observed_at": "2026-09-21T16:02:00Z",
    }
    payload_failure = client.post(path, headers=_headers(), json=request)
    assert payload_failure.status_code == 503

    class _SaveFailRepository(InMemoryVectorIndexRepository):
        def save(self, *args, **kwargs):
            raise VectorIndexRepositoryError(
                "cx.vector_index.checkpoint_conflict",
                "Vector index checkpoint changed.",
                retryable=False,
            )

    repository = _SaveFailRepository()
    repository.create(ready)
    save_client, _s, _p, _r, _events = _client(
        repository=repository,
        adapter=_Adapter(build_vector_payload_snapshot([])),
    )
    save_failure = save_client.post(path, headers=_headers(), json=request)
    assert save_failure.status_code == 409
    assert save_failure.json()["error_code"] == "cx.vector_index.checkpoint_conflict"


def test_repository_failure_and_helpers_are_deterministic():
    class _FailingRepository(InMemoryVectorIndexRepository):
        def get(self, *args, **kwargs):
            raise VectorIndexRepositoryError(
                "cx.vector_index.repository_unavailable",
                "Vector index repository is unavailable.",
                retryable=True,
            )

    client, _source, _profile, ready, _events = _client(
        repository=_FailingRepository()
    )
    response = client.get(
        f"/api/v1/vector-indexes/{ready['vector_index_id']}/readiness",
        headers=_headers(),
    )
    assert response.status_code == 503
    first = _reconciliation_event_id(
        vector_index_id=ready["vector_index_id"], checkpoint_version=1, action="NONE"
    )
    second = _reconciliation_event_id(
        vector_index_id=ready["vector_index_id"], checkpoint_version=1, action="NONE"
    )
    assert first == second
    assert str(
        VectorIndexOperationsError(
            error_code="code", detail="detail", status_code=409
        )
    ) == "detail"


def test_main_dependency_builder_is_postgres_only(monkeypatch):
    assert build_cx_vector_operations_dependencies(
        SimpleNamespace(mode="memory", api_session_factory=None)
    ) == (None, None)
    factory = object()
    adapter = object()
    captured = {}
    monkeypatch.setattr(
        cx_main,
        "build_pgvector_cx_vector_store",
        lambda **kwargs: captured.update(kwargs) or adapter,
    )
    repository, store = build_cx_vector_operations_dependencies(
        SimpleNamespace(
            mode="postgres",
            api_session_factory=factory,
            database_env="NEX_CX_TEST_DATABASE_URL",
        )
    )
    assert isinstance(repository, SqlAlchemyVectorIndexRepository)
    assert store is adapter
    assert captured == {
        "database_env": "NEX_CX_TEST_DATABASE_URL",
        "workload": "api",
    }
