from __future__ import annotations

import json
import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
import test_nex_eos_mybee_project_pnl as pnl_base
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, FormatChecker
from nex_eos import (
    EOS_PROJECT_TABLE,
    PROJECT_PNL_REFRESH_OPERATION,
    EosProjectPnlPersistenceError,
    EosProjectPnlProjectorError,
    EosProjectPnlRefreshError,
    EosProjectPnlRefreshService,
    ProjectPnlProjectionDraft,
    ProjectPnlRefreshProject,
    ProjectPnlRefreshSource,
)
from nex_eos.project_pnl_refresh_api import register_project_pnl_refresh_routes
from sqlalchemy import select

_PROJECTION_NAMESPACE = uuid.UUID("f49bdff2-292c-5efc-9ab3-68d427281795")
ROOT = Path(__file__).resolve().parents[1]


class _Resolver:
    def __init__(self, source: ProjectPnlRefreshSource) -> None:
        self.source = source
        self.calls: list[dict[str, str]] = []

    def resolve(self, **kwargs):
        self.calls.append(kwargs)
        return self.source


class _Projector:
    def __init__(self, repository, *, status: str = "VERIFIED") -> None:
        self.repository = repository
        self.status = status
        self.freshness = "CURRENT"
        self.statuses_by_project: dict[str, str] = {}
        self.preview_calls = []
        self.rebuild_calls = []
        self.fail_preview: Exception | None = None
        self.fail_rebuild: Exception | None = None
        self.converge_then_conflict = False

    def preview(self, request):
        self.preview_calls.append(request)
        if self.fail_preview is not None:
            raise self.fail_preview
        projection_id = str(
            uuid.uuid5(
                _PROJECTION_NAMESPACE,
                "/".join(
                    (
                        request.tenant_id,
                        request.company_id,
                        request.project_id,
                        request.period_id,
                        str(request.projection_version),
                    )
                ),
            )
        )
        return (
            ProjectPnlProjectionDraft(
                tenant_id=request.tenant_id,
                company_id=request.company_id,
                projection_id=projection_id,
                project_id=request.project_id,
                project_code=request.project_code,
                period_id=request.period_id,
                projection_version=request.projection_version,
                functional_currency=request.functional_currency,
                as_of=request.as_of,
                posting_watermark=f"eos.journal:{request.period_id}",
                posting_watermark_at=request.as_of,
                allocation_watermark=f"eos.allocation:{request.period_id}",
                allocation_watermark_at=request.as_of,
                reconciliation_status=self.statuses_by_project.get(
                    request.project_id, self.status
                ),
                freshness_status=self.freshness,
                staleness_seconds=0,
            ),
            (),
        )

    def rebuild(self, request):
        self.rebuild_calls.append(request)
        if self.fail_rebuild is not None:
            raise self.fail_rebuild
        draft, components = self.preview(request)
        result = self.repository.append(draft, components)
        if self.converge_then_conflict:
            self.converge_then_conflict = False
            raise EosProjectPnlPersistenceError(
                "PROJECT_PNL_CONFLICT",
                "concurrent append won",
                status_code=409,
            )
        return result


class _BrokenRepository:
    def __init__(self, error: EosProjectPnlPersistenceError) -> None:
        self.error = error

    def list_at_boundary(self, **_kwargs):
        raise self.error


def _source(*, committed_at: datetime = pnl_base.NOW):
    return ProjectPnlRefreshSource(
        tenant_id=pnl_base.TENANT,
        company_id=pnl_base.COMPANY_ID,
        business_operation_id="76000000-0000-4000-8000-000000000020",
        batch_id="76000000-0000-4000-8000-000000000021",
        plan_id="76000000-0000-4000-8000-000000000022",
        plan_revision=1,
        period_id=pnl_base.PERIOD_ID,
        functional_currency="KRW",
        allocation_reconciliation_hash="sha256:" + "c" * 64,
        source_set_hash="sha256:" + "d" * 64,
        committed_at=committed_at,
        pool_ids=("76000000-0000-4000-8000-000000000023",),
        affected_projects=(
            ProjectPnlRefreshProject(
                project_id=pnl_base.PROJECT_ID,
                project_code="W601D260001",
                project_status="ACTIVE",
                roles=("ALLOCATION_TARGET",),
            ),
        ),
        source_resolution_hash="sha256:" + "e" * 64,
    )


def _runtime(*, source=None, status="VERIFIED"):
    persistence = pnl_base._runtime()
    resolver = _Resolver(source or _source())
    projector = _Projector(persistence.repository, status=status)
    service = EosProjectPnlRefreshService(
        resolver=resolver,
        projector=projector,
        repository=persistence.repository,
    )
    return persistence, resolver, projector, service


def _refresh(service):
    return service.refresh(
        tenant_id=pnl_base.TENANT,
        company_id=pnl_base.COMPANY_ID,
        batch_id=_source().batch_id,
    )


def test_activation_creates_then_replays_exact_projection_across_restart():
    runtime, resolver, projector, service = _runtime()
    try:
        created = _refresh(service)
        replay = _refresh(service)
        restarted = EosProjectPnlRefreshService(
            resolver=_Resolver(_source()),
            projector=_Projector(runtime.repository),
            repository=runtime.repository,
        )
        restarted_replay = _refresh(restarted)

        assert created["disposition"] == "CREATED"
        assert replay["disposition"] == "EXACT_REPLAY"
        assert restarted_replay["disposition"] == "EXACT_REPLAY"
        assert created["refresh_hash"] == replay["refresh_hash"]
        assert replay["refresh_hash"] == restarted_replay["refresh_hash"]
        assert created["projections"] == replay["projections"]
        assert created["projections"] == restarted_replay["projections"]
        assert created["operation"] == PROJECT_PNL_REFRESH_OPERATION
        assert created["projections"][0]["projection_version"] == 1
        assert len(projector.rebuild_calls) == 1
        assert len(resolver.calls) == 2
        schema = json.loads(
            (
                ROOT / "contracts/schemas/service/nex_eos/"
                "project_pnl_refresh_from_allocation.v1.schema.json"
            ).read_text(encoding="utf-8")
        )
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(created)
    finally:
        runtime.engine.dispose()


def test_concurrent_conflict_converges_to_exact_persisted_result():
    runtime, _resolver, projector, service = _runtime()
    projector.converge_then_conflict = True
    try:
        result = _refresh(service)
        assert result["disposition"] == "EXACT_REPLAY"
        assert len(result["projections"]) == 1
        assert (
            runtime.repository.get(
                tenant_id=pnl_base.TENANT,
                company_id=pnl_base.COMPANY_ID,
                project_id=pnl_base.PROJECT_ID,
                period_id=pnl_base.PERIOD_ID,
            )["projection_hash"]
            == result["projections"][0]["projection_hash"]
        )
    finally:
        runtime.engine.dispose()


def test_later_boundary_appends_the_next_immutable_version():
    earlier = pnl_base.NOW - timedelta(seconds=1)
    runtime, _resolver, _projector, earlier_service = _runtime(
        source=_source(committed_at=earlier)
    )
    try:
        first = _refresh(earlier_service)
        later_service = EosProjectPnlRefreshService(
            resolver=_Resolver(_source()),
            projector=_Projector(runtime.repository),
            repository=runtime.repository,
        )
        second = _refresh(later_service)
        assert first["projections"][0]["projection_version"] == 1
        assert second["projections"][0]["projection_version"] == 2
        assert (
            len(
                runtime.repository.list_at_boundary(
                    tenant_id=pnl_base.TENANT,
                    company_id=pnl_base.COMPANY_ID,
                    project_id=pnl_base.PROJECT_ID,
                    period_id=pnl_base.PERIOD_ID,
                    as_of=pnl_base.NOW,
                )
            )
            == 1
        )
    finally:
        runtime.engine.dispose()


def test_newer_boundary_and_duplicate_exact_boundary_fail_before_mutation():
    future = pnl_base.NOW + timedelta(seconds=1)
    runtime, _resolver, projector, service = _runtime()
    try:
        request = projector.preview_calls
        future_source = replace(_source(), committed_at=future)
        future_projector = _Projector(runtime.repository)
        future_service = EosProjectPnlRefreshService(
            resolver=_Resolver(future_source),
            projector=future_projector,
            repository=runtime.repository,
        )
        future_created = _refresh(future_service)
        assert future_created["projections"][0]["projection_version"] == 1

        with pytest.raises(EosProjectPnlRefreshError) as stale:
            _refresh(service)
        assert stale.value.error_code == "EOS_PROJECT_PNL_REFRESH_ORDERING_CONFLICT"
        assert request == []

        draft, components = future_projector.preview(
            replace(future_projector.preview_calls[-1], projection_version=2)
        )
        runtime.repository.append(draft, components)
        with pytest.raises(EosProjectPnlRefreshError) as ambiguous:
            _refresh(future_service)
        assert ambiguous.value.error_code == (
            "EOS_PROJECT_PNL_REFRESH_ORDERING_CONFLICT"
        )
    finally:
        runtime.engine.dispose()


def test_non_verified_preview_and_projector_failures_are_fail_closed():
    runtime, _resolver, projector, service = _runtime(status="PARTIAL")
    try:
        with pytest.raises(EosProjectPnlRefreshError) as partial:
            _refresh(service)
        assert partial.value.error_code == (
            "EOS_PROJECT_PNL_REFRESH_PROJECTION_NOT_READY"
        )
        assert projector.rebuild_calls == []

        projector.status = "VERIFIED"
        projector.fail_preview = EosProjectPnlProjectorError(
            "PROJECT_PNL_SOURCE_UNAVAILABLE",
            "offline",
            status_code=503,
            retryable=True,
        )
        with pytest.raises(EosProjectPnlRefreshError) as unavailable:
            _refresh(service)
        assert unavailable.value.error_code == (
            "EOS_PROJECT_PNL_REFRESH_PROJECTOR_UNAVAILABLE"
        )
        assert unavailable.value.retryable is True

        projector.fail_preview = EosProjectPnlProjectorError(
            "PROJECT_PNL_SOURCE_DRIFT",
            "drift",
            status_code=409,
        )
        with pytest.raises(EosProjectPnlRefreshError) as drift:
            _refresh(service)
        assert drift.value.error_code == "EOS_PROJECT_PNL_REFRESH_PROJECTION_DRIFT"

        projector.fail_preview = None
        projector.freshness = "STALE"
        with pytest.raises(EosProjectPnlRefreshError) as stale:
            _refresh(service)
        assert stale.value.error_code == (
            "EOS_PROJECT_PNL_REFRESH_PROJECTION_NOT_READY"
        )
    finally:
        runtime.engine.dispose()


def test_rebuild_failures_and_non_convergent_conflicts_are_bounded():
    runtime, _resolver, projector, service = _runtime()
    try:
        projector.fail_rebuild = EosProjectPnlProjectorError(
            "PROJECT_PNL_SOURCE_UNAVAILABLE",
            "offline",
            status_code=503,
            retryable=True,
        )
        with pytest.raises(EosProjectPnlRefreshError) as unavailable:
            _refresh(service)
        assert unavailable.value.error_code == (
            "EOS_PROJECT_PNL_REFRESH_PROJECTOR_UNAVAILABLE"
        )

        projector.fail_rebuild = EosProjectPnlPersistenceError(
            "PROJECT_PNL_UNAVAILABLE", "offline", status_code=503
        )
        with pytest.raises(EosProjectPnlRefreshError) as persistence:
            _refresh(service)
        assert persistence.value.error_code == (
            "EOS_PROJECT_PNL_REFRESH_PROJECTION_UNAVAILABLE"
        )

        projector.fail_rebuild = EosProjectPnlPersistenceError(
            "PROJECT_PNL_CONFLICT", "lost", status_code=409
        )
        with pytest.raises(EosProjectPnlRefreshError) as not_converged:
            _refresh(service)
        assert not_converged.value.error_code == (
            "EOS_PROJECT_PNL_REFRESH_ORDERING_CONFLICT"
        )

        calls = 0
        original = runtime.repository.list_at_boundary

        def fail_after_conflict(**kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise EosProjectPnlPersistenceError(
                    "PROJECT_PNL_UNAVAILABLE", "offline", status_code=503
                )
            return original(**kwargs)

        runtime.repository.list_at_boundary = fail_after_conflict
        with pytest.raises(EosProjectPnlRefreshError) as convergence_unavailable:
            _refresh(service)
        assert convergence_unavailable.value.error_code == (
            "EOS_PROJECT_PNL_REFRESH_PROJECTION_UNAVAILABLE"
        )
    finally:
        runtime.engine.dispose()


def test_all_projects_are_preflighted_before_any_projection_is_appended():
    runtime, resolver, projector, service = _runtime()
    second_project_id = "76000000-0000-4000-8000-000000000013"
    with runtime.sessions.begin() as session:
        row = dict(
            session.execute(
                select(EOS_PROJECT_TABLE).where(
                    EOS_PROJECT_TABLE.c.project_id == pnl_base.PROJECT_ID
                )
            )
            .mappings()
            .one()
        )
        row.update(
            project_id=second_project_id,
            project_code="W601D260002",
            project_request_code="W601R260002",
            name="Second Project",
        )
        session.execute(EOS_PROJECT_TABLE.insert().values(**row))
    resolver.source = replace(
        _source(),
        affected_projects=(
            *_source().affected_projects,
            ProjectPnlRefreshProject(
                project_id=second_project_id,
                project_code="W601D260002",
                project_status="ACTIVE",
                roles=("ALLOCATION_TARGET",),
            ),
        ),
    )
    projector.statuses_by_project[second_project_id] = "PARTIAL"
    try:
        with pytest.raises(EosProjectPnlRefreshError) as rejected:
            _refresh(service)
        assert rejected.value.error_code == (
            "EOS_PROJECT_PNL_REFRESH_PROJECTION_NOT_READY"
        )
        assert projector.rebuild_calls == []
        assert (
            runtime.repository.get(
                tenant_id=pnl_base.TENANT,
                company_id=pnl_base.COMPANY_ID,
                project_id=pnl_base.PROJECT_ID,
                period_id=pnl_base.PERIOD_ID,
            )
            is None
        )
    finally:
        runtime.engine.dispose()


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("projection_hash", "sha256:" + "f" * 64),
        ("projection_id", "76000000-0000-4000-8000-000000000099"),
        ("reconciliation_status", "PARTIAL"),
        ("freshness_status", "STALE"),
    ),
)
def test_existing_boundary_must_match_exact_projection_semantics(field, value):
    runtime, _resolver, _projector, service = _runtime()
    try:
        _refresh(service)
        original = runtime.repository.list_at_boundary

        def drifted(**kwargs):
            projections = original(**kwargs)
            return ({**projections[0], field: value},)

        runtime.repository.list_at_boundary = drifted
        with pytest.raises(EosProjectPnlRefreshError) as rejected:
            _refresh(service)
        assert rejected.value.error_code == "EOS_PROJECT_PNL_REFRESH_PROJECTION_DRIFT"
    finally:
        runtime.engine.dispose()


def test_invalid_preview_record_is_mapped_to_ordering_conflict():
    runtime, _resolver, projector, service = _runtime()
    original = projector.preview

    def invalid_preview(request):
        draft, components = original(request)
        return replace(draft, functional_currency="INVALID"), components

    projector.preview = invalid_preview
    try:
        with pytest.raises(EosProjectPnlRefreshError) as rejected:
            _refresh(service)
        assert rejected.value.error_code == (
            "EOS_PROJECT_PNL_REFRESH_ORDERING_CONFLICT"
        )
    finally:
        runtime.engine.dispose()


def test_projection_boundary_parser_rejects_malformed_values():
    from nex_eos.project_pnl_refresh import _parse_wire_time

    for value in (None, "not-a-time"):
        with pytest.raises(EosProjectPnlRefreshError) as rejected:
            _parse_wire_time(value)
        assert rejected.value.error_code == (
            "EOS_PROJECT_PNL_REFRESH_ORDERING_CONFLICT"
        )
    assert _parse_wire_time("2026-11-17T00:00:00").tzinfo == UTC


@pytest.mark.parametrize("status_code", (409, 503))
def test_persistence_errors_are_bounded(status_code):
    source = _source()
    service = EosProjectPnlRefreshService(
        resolver=_Resolver(source),
        projector=SimpleNamespace(),
        repository=_BrokenRepository(
            EosProjectPnlPersistenceError(
                "PROJECT_PNL_FAILURE", "failed", status_code=status_code
            )
        ),
    )
    with pytest.raises(EosProjectPnlRefreshError) as failed:
        _refresh(service)
    assert failed.value.status_code == status_code
    assert failed.value.retryable is (status_code == 503)


def test_route_enforces_trust_shape_status_and_no_store(monkeypatch):
    results = iter(
        (
            {"disposition": "CREATED"},
            {"disposition": "EXACT_REPLAY"},
        )
    )
    service = SimpleNamespace(refresh=lambda **_kwargs: next(results))
    monkeypatch.setattr(
        "nex_eos.project_pnl_refresh_api.admit_service_token_from_request",
        lambda *_args, **_kwargs: SimpleNamespace(subject="nex-ae-api"),
    )
    app = FastAPI()
    app.state.eos_project_pnl_refresh_service = service
    register_project_pnl_refresh_routes(app)
    headers = {
        "Authorization": "Bearer signed-service-token",
        "X-NeX-Tenant-Id": pnl_base.TENANT,
        "X-NeX-Company-Id": pnl_base.COMPANY_ID,
        "X-NeX-Correlation-Id": "corr-refresh-1",
    }
    path = (
        "/internal/v2/finance/cost-allocation-batches/"
        f"{_source().batch_id}:refresh-project-pnl"
    )
    with TestClient(app) as client:
        created = client.post(path, headers=headers)
        replay = client.post(path, headers=headers)
        query_denied = client.post(f"{path}?project_id=bad", headers=headers)
        body_denied = client.post(path, headers=headers, json={})

    assert created.status_code == 201
    assert replay.status_code == 200
    assert query_denied.status_code == 400
    assert body_denied.status_code == 400
    assert query_denied.json()["error_code"] == ("EOS_PROJECT_PNL_REFRESH_SHAPE_DENIED")
    for response in (created, replay, query_denied, body_denied):
        assert response.headers["cache-control"] == "no-store, max-age=0"
        assert response.headers["pragma"] == "no-cache"


def test_route_maps_token_denial_dependency_and_domain_errors(monkeypatch):
    app = FastAPI()
    register_project_pnl_refresh_routes(app)
    headers = {
        "X-NeX-Tenant-Id": pnl_base.TENANT,
        "X-NeX-Company-Id": pnl_base.COMPANY_ID,
        "X-NeX-Correlation-Id": "corr-refresh-2",
    }
    path = (
        "/internal/v2/finance/cost-allocation-batches/"
        f"{_source().batch_id}:refresh-project-pnl"
    )
    monkeypatch.setattr(
        "nex_eos.project_pnl_refresh_api.admit_service_token_from_request",
        lambda *_args, **_kwargs: JSONResponse(
            {"error_code": "TOKEN_DENIED"}, status_code=401
        ),
    )
    with TestClient(app) as client:
        denied = client.post(path, headers=headers)
    assert denied.status_code == 401
    assert denied.headers["cache-control"] == "no-store, max-age=0"

    monkeypatch.setattr(
        "nex_eos.project_pnl_refresh_api.admit_service_token_from_request",
        lambda *_args, **_kwargs: SimpleNamespace(subject="nex-ae-api"),
    )
    with TestClient(app) as client:
        unavailable = client.post(path, headers=headers)
        app.state.eos_project_pnl_refresh_service = SimpleNamespace(
            refresh=lambda **_kwargs: (_ for _ in ()).throw(
                EosProjectPnlRefreshError(
                    "EOS_PROJECT_PNL_REFRESH_BATCH_NOT_VERIFIED",
                    "not verified",
                    status_code=409,
                )
            )
        )
        rejected = client.post(path, headers=headers)
    assert unavailable.status_code == 503
    assert rejected.status_code == 409
    assert rejected.json()["error_code"] == (
        "EOS_PROJECT_PNL_REFRESH_BATCH_NOT_VERIFIED"
    )


def test_route_rejects_malformed_content_length_helper():
    from nex_eos.project_pnl_refresh_api import _has_request_body

    assert _has_request_body(SimpleNamespace(headers={"content-length": "bad"})) is True
    assert (
        _has_request_body(SimpleNamespace(headers={"transfer-encoding": "chunked"}))
        is True
    )
    assert _has_request_body(SimpleNamespace(headers={})) is False
