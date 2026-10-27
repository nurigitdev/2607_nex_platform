from __future__ import annotations

from copy import deepcopy
from urllib.error import HTTPError, URLError

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from nex_ae_api.agent_results import AgentResultAggregate
from nex_ae_api.wa_source_projections import (
    SqlAlchemyAgentResultWaProjectionSource,
    SqlAlchemyArtifactWaProjectionSource,
    WaSourceProjectionError,
    register_wa_agent_result_source_routes,
    register_wa_artifact_source_routes,
)
from nex_runtime import (
    InMemoryJobQueue,
    InMemoryOperationalEventStore,
    OperationalEventEmitter,
    issue_mock_service_token,
)
from nex_wa.intake import WaEvidenceIntakeService
from nex_wa.reconciliation import (
    HttpAeWaReconciliationSource,
    WaAeReconciliationService,
    WaReconciliationError,
    WaReconciliationResult,
    WaReconciliationSourceResult,
)
from nex_wa.reconciliation_main import main as reconciliation_main

TENANT = "VO00"
AFTER = "2026-10-28T00:00:00Z"
BEFORE = "2026-10-29T00:00:00Z"


def _aggregate(index: int) -> AgentResultAggregate:
    result_id = f"00000000-0000-4000-8000-{index:012d}"
    execution_id = f"10000000-0000-4000-8000-{index:012d}"
    created_at = f"2026-10-28T0{index}:00:00Z"
    return AgentResultAggregate(
        result={
            "tenant_id": TENANT,
            "result_id": result_id,
            "agent_execution_id": execution_id,
            "agent_id": f"20000000-0000-4000-8000-{index:012d}",
            "agent_type": "IA",
            "project_id": None,
            "status": "SUCCEEDED",
            "result_hash": "sha256:" + str(index) * 64,
            "artifact_refs": [],
            "evidence_refs": [],
            "business_refs": [],
            "source_work_item_ref": None,
            "source_claim_ref": None,
            "source_claim_generation": None,
            "source_assignment_ref": None,
            "created_at": created_at,
        },
        delivery={
            "tenant_id": TENANT,
            "delivery_id": f"30000000-0000-4000-8000-{index:012d}",
            "result_id": result_id,
            "required": True,
            "target_type": "WORKSPACE_RESULT",
            "state": "ACKNOWLEDGED",
            "acknowledged_at": created_at,
        },
        execution={
            "tenant_id": TENANT,
            "agent_execution_id": execution_id,
            "state": "SUCCEEDED",
        },
    )


class _AgentRepository:
    def __init__(self) -> None:
        self.values = [_aggregate(1), _aggregate(2)]

    def list_for_wa_reconciliation(self, **kwargs):
        cursor = kwargs["cursor_result_id"]
        values = [
            value
            for value in self.values
            if cursor is None or value.result["result_id"] > cursor
        ]
        return values[: kwargs["limit"]]

    def get(self, tenant_id, result_id):
        return next(
            (
                value
                for value in self.values
                if tenant_id == TENANT and value.result["result_id"] == result_id
            ),
            None,
        )


def _artifact(index: int) -> dict:
    return {
        "artifact_id": f"artifact-{index}",
        "artifact_status": "READY",
        "owner_actor_ref": {
            "actor_type": "user",
            "actor_id": "employee-001",
            "tenant_id": TENANT,
        },
        "workspace_ref": {"workspace_id": "workspace-001", "tenant_id": TENANT},
        "project_ref": None,
        "source_refs": [{"structured_draft_content_hash": "a" * 64}],
        "versions": [
            {
                "artifact_id": f"artifact-{index}",
                "artifact_version_id": f"artifact-version-{index}",
                "source_content_hash": "a" * 64,
                "artifact_content_hash": str(index + 2) * 64,
                "created_at": f"2026-10-28T1{index}:00:00Z",
            }
        ],
    }


class _ArtifactRepository:
    def __init__(self) -> None:
        self.values = {f"artifact-{index}": _artifact(index) for index in (1, 2)}

    def list_versions_for_wa_reconciliation(self, **kwargs):
        cursor = kwargs["cursor_version_id"]
        values = [
            (artifact_id, record["versions"][0]["artifact_version_id"])
            for artifact_id, record in sorted(self.values.items())
            if cursor is None or record["versions"][0]["artifact_version_id"] > cursor
        ]
        return values[: kwargs["limit"]]

    def get(self, artifact_id):
        return self.values.get(artifact_id)


def _headers(*, service_id="nex-wa", scopes=None):
    token = issue_mock_service_token(
        service_id=service_id,
        audience="nex-ae-api",
        scopes=scopes or ("service:call", "work:source:read"),
    ).access_token
    return {"Authorization": f"Bearer {token}", "X-NeX-Tenant-Id": TENANT}


def test_agent_result_listing_is_bounded_cursor_stable_and_private() -> None:
    source = SqlAlchemyAgentResultWaProjectionSource(_AgentRepository())
    first = source.list_projections(
        tenant_id=TENANT,
        created_after=AFTER,
        created_before=BEFORE,
        limit=1,
        cursor=None,
    )
    assert first["pagination"]["has_more"] is True
    assert first["pagination"]["returned"] == 1
    assert set(first["items"][0]) == {
        "schema_version",
        "tenant_id",
        "source_type",
        "source_ref",
        "source_revision_ref",
        "source_hash",
        "occurred_at",
        "correlation_id",
    }

    second = source.list_projections(
        tenant_id=TENANT,
        created_after=AFTER,
        created_before=BEFORE,
        limit=1,
        cursor=first["pagination"]["next_cursor"],
    )
    assert second["items"][0]["source_revision_ref"].endswith("000000000002")
    assert second["pagination"]["has_more"] is False

    with pytest.raises(WaSourceProjectionError) as exc_info:
        source.list_projections(
            tenant_id=TENANT,
            created_after=AFTER,
            created_before="2026-10-30T00:00:00Z",
            limit=1,
            cursor=first["pagination"]["next_cursor"],
        )
    assert exc_info.value.error_code == "ae.wa_reconciliation_cursor_invalid"


def test_artifact_listing_returns_ready_version_refs_and_hashes_only() -> None:
    source = SqlAlchemyArtifactWaProjectionSource(_ArtifactRepository())
    page = source.list_projections(
        tenant_id=TENANT,
        created_after=AFTER,
        created_before=BEFORE,
        limit=2,
        cursor=None,
    )
    assert [item["source_type"] for item in page["items"]] == [
        "AE_ARTIFACT",
        "AE_ARTIFACT",
    ]
    assert "owner_actor_ref" not in page["items"][0]
    assert "content" not in str(page).lower()


def test_collection_routes_require_signed_wa_scope_and_bounded_window() -> None:
    app = FastAPI()
    register_wa_agent_result_source_routes(
        app,
        source=SqlAlchemyAgentResultWaProjectionSource(_AgentRepository()),
    )
    register_wa_artifact_source_routes(
        app,
        source=SqlAlchemyArtifactWaProjectionSource(_ArtifactRepository()),
    )
    client = TestClient(app)
    params = {"created_after": AFTER, "created_before": BEFORE, "limit": 1}
    assert (
        client.get(
            "/internal/v1/wa-sources/agent-results",
            params=params,
            headers=_headers(),
        ).status_code
        == 200
    )
    assert (
        client.get(
            "/internal/v1/wa-sources/artifacts",
            params=params,
            headers=_headers(scopes=("service:call",)),
        ).status_code
        == 401
    )
    invalid = client.get(
        "/internal/v1/wa-sources/agent-results",
        params={"created_after": BEFORE, "created_before": AFTER},
        headers=_headers(),
    )
    assert invalid.status_code == 400
    assert invalid.json()["error_code"] == "ae.wa_reconciliation_window_invalid"


def _intake_item(source_type: str, index: int) -> dict:
    is_agent = source_type == "AE_AGENT_RESULT"
    return {
        "schema_version": "wa_evidence_intake_request.v1",
        "tenant_id": TENANT,
        "source_type": source_type,
        "source_ref": f"{'execution' if is_agent else 'artifact'}-{index}",
        "source_revision_ref": f"{'result' if is_agent else 'version'}-{index}",
        "source_hash": "sha256:" + str(index) * 64,
        "occurred_at": f"2026-10-28T0{index}:00:00Z",
        "correlation_id": f"corr-{source_type.lower()}-{index}",
    }


class _PagedSource:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    def list_sources(self, **kwargs):
        source_type = kwargs["source_type"]
        cursor = kwargs["cursor"]
        self.calls.append((source_type, cursor))
        index = 1 if cursor is None else 2
        has_more = cursor is None
        return {
            "schema_version": "wa_source_reconciliation_page.v1",
            "source_type": source_type,
            "created_after": kwargs["created_after"],
            "created_before": kwargs["created_before"],
            "items": [_intake_item(source_type, index)],
            "pagination": {
                "limit": kwargs["limit"],
                "returned": 1,
                "has_more": has_more,
                "next_cursor": f"{source_type}-page-2" if has_more else None,
            },
        }


def test_missed_sources_reconcile_through_normal_identity_and_restart_reuses() -> None:
    queue = InMemoryJobQueue()
    source = _PagedSource()
    event_store = InMemoryOperationalEventStore()
    service = WaAeReconciliationService(
        source=source,
        intake=WaEvidenceIntakeService(queue),
        event_emitter=OperationalEventEmitter(
            service_id="nex-wa",
            store=event_store,
        ),
    )

    first = service.run(
        tenant_id=TENANT,
        created_after=AFTER,
        created_before=BEFORE,
        mode="operator",
        page_size=1,
        max_pages_per_source=2,
    )
    assert len(queue.list_jobs()) == 4
    assert sum(item.jobs_admitted for item in first.sources) == 4
    assert all(item.complete for item in first.sources)
    assert event_store.list_events(limit=10)[0]["event_type"] == (
        "wa.reconciliation.completed"
    )

    restarted = WaAeReconciliationService(
        source=_PagedSource(),
        intake=WaEvidenceIntakeService(queue),
    ).run(
        tenant_id=TENANT,
        created_after=AFTER,
        created_before=BEFORE,
        mode="startup",
        page_size=1,
        max_pages_per_source=2,
    )
    assert len(queue.list_jobs()) == 4
    assert sum(item.jobs_reused for item in restarted.sources) == 4


def test_reconciliation_stops_at_bound_and_rejects_invalid_pages() -> None:
    service = WaAeReconciliationService(
        source=_PagedSource(),
        intake=WaEvidenceIntakeService(InMemoryJobQueue()),
    )
    bounded = service.run(
        tenant_id=TENANT,
        created_after=AFTER,
        created_before=BEFORE,
        mode="startup",
        page_size=1,
        max_pages_per_source=1,
    )
    assert all(not item.complete for item in bounded.sources)
    assert all(item.next_cursor for item in bounded.sources)

    class _InvalidSource(_PagedSource):
        def list_sources(self, **kwargs):
            page = deepcopy(super().list_sources(**kwargs))
            page["items"][0]["tenant_id"] = "other-tenant"
            return page

    with pytest.raises(WaReconciliationError) as exc_info:
        WaAeReconciliationService(
            source=_InvalidSource(),
            intake=WaEvidenceIntakeService(InMemoryJobQueue()),
        ).run(
            tenant_id=TENANT,
            created_after=AFTER,
            created_before=BEFORE,
            mode="operator",
            page_size=1,
            max_pages_per_source=1,
        )
    assert exc_info.value.error_code == "WA_RECONCILIATION_PAGE_INVALID"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"mode": "scheduler", "page_size": 1, "max_pages_per_source": 1},
        {"mode": "operator", "page_size": 0, "max_pages_per_source": 1},
        {"mode": "operator", "page_size": 1, "max_pages_per_source": 0},
    ],
)
def test_reconciliation_rejects_general_scheduler_and_unbounded_inputs(kwargs) -> None:
    with pytest.raises(WaReconciliationError):
        WaAeReconciliationService(
            source=_PagedSource(),
            intake=WaEvidenceIntakeService(InMemoryJobQueue()),
        ).run(
            tenant_id=TENANT,
            created_after=AFTER,
            created_before=BEFORE,
            **kwargs,
        )


def test_http_reconciliation_source_uses_signed_tenant_bounded_request(
    monkeypatch,
) -> None:
    captured = {}

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b'{"schema_version":"wa_source_reconciliation_page.v1"}'

    def _urlopen(request, timeout):
        captured.update(
            url=request.full_url, headers=dict(request.headers), timeout=timeout
        )
        return _Response()

    monkeypatch.setattr("nex_wa.reconciliation.urlopen", _urlopen)
    page = HttpAeWaReconciliationSource(
        base_url="http://ae.local/",
        service_token="signed-token",
        timeout_seconds=7,
    ).list_sources(
        tenant_id=TENANT,
        source_type="AE_ARTIFACT",
        created_after=AFTER,
        created_before=BEFORE,
        limit=25,
        cursor="opaque-cursor",
    )
    assert page["schema_version"] == "wa_source_reconciliation_page.v1"
    assert captured["url"].startswith(
        "http://ae.local/internal/v1/wa-sources/artifacts?"
    )
    assert "cursor=opaque-cursor" in captured["url"]
    assert captured["headers"]["X-nex-tenant-id"] == TENANT
    assert captured["headers"]["Authorization"] == "Bearer signed-token"
    assert captured["timeout"] == 7


def test_maintenance_command_check_is_bounded_and_redacts_token(capsys) -> None:
    exit_code = reconciliation_main(
        ["--check"],
        environ={
            "NEX_PROFILE": "test",
            "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK",
            "NEX_AE_API_BASE_URL": "http://127.0.0.1:8101",
        },
    )
    output = capsys.readouterr().out
    assert exit_code == 0
    assert '"status": "READY"' in output
    assert "eyJ" not in output


@pytest.mark.parametrize(
    "kwargs",
    [
        {"base_url": "", "service_token": "token"},
        {"base_url": "http://ae.local", "service_token": ""},
        {
            "base_url": "http://ae.local",
            "service_token": "token",
            "timeout_seconds": 0,
        },
    ],
)
def test_http_reconciliation_source_rejects_invalid_bootstrap(kwargs) -> None:
    with pytest.raises(ValueError):
        HttpAeWaReconciliationSource(**kwargs)


def test_http_reconciliation_source_rejects_unknown_source_and_invalid_payload(
    monkeypatch,
) -> None:
    source = HttpAeWaReconciliationSource(
        base_url="http://ae.local",
        service_token="token",
    )
    with pytest.raises(WaReconciliationError) as unsupported:
        source.list_sources(
            tenant_id=TENANT,
            source_type="WC_WORK_RESULT",
            created_after=AFTER,
            created_before=BEFORE,
            limit=1,
            cursor=None,
        )
    assert unsupported.value.retryable is False

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b"[]"

    monkeypatch.setattr(
        "nex_wa.reconciliation.urlopen", lambda *args, **kwargs: _Response()
    )
    with pytest.raises(WaReconciliationError) as invalid:
        source.list_sources(
            tenant_id=TENANT,
            source_type="AE_AGENT_RESULT",
            created_after=AFTER,
            created_before=BEFORE,
            limit=1,
            cursor=None,
        )
    assert invalid.value.error_code == "WA_RECONCILIATION_PAGE_INVALID"


@pytest.mark.parametrize(
    ("failure", "retryable"),
    [
        (HTTPError("http://ae.local", 503, "offline", {}, None), True),
        (HTTPError("http://ae.local", 400, "invalid", {}, None), False),
        (URLError("offline"), True),
    ],
)
def test_http_reconciliation_source_maps_transport_failures(
    monkeypatch,
    failure,
    retryable,
) -> None:
    def _raise(*args, **kwargs):
        raise failure

    monkeypatch.setattr("nex_wa.reconciliation.urlopen", _raise)
    with pytest.raises(WaReconciliationError) as exc_info:
        HttpAeWaReconciliationSource(
            base_url="http://ae.local",
            service_token="token",
        ).list_sources(
            tenant_id=TENANT,
            source_type="AE_AGENT_RESULT",
            created_after=AFTER,
            created_before=BEFORE,
            limit=1,
            cursor=None,
        )
    assert exc_info.value.retryable is retryable


def test_reconciliation_result_projection_and_empty_tenant_guard() -> None:
    result = WaReconciliationResult(
        tenant_id=TENANT,
        mode="OPERATOR",
        created_after=AFTER,
        created_before=BEFORE,
        sources=(
            WaReconciliationSourceResult("AE_AGENT_RESULT", 1, 2, 1, 1, True, None),
        ),
    )
    assert result.to_dict()["sources"][0]["jobs_reused"] == 1
    with pytest.raises(WaReconciliationError) as exc_info:
        WaAeReconciliationService(
            source=_PagedSource(),
            intake=WaEvidenceIntakeService(InMemoryJobQueue()),
        ).run(
            tenant_id=" ",
            created_after=AFTER,
            created_before=BEFORE,
            mode="operator",
        )
    assert exc_info.value.error_code == "WA_RECONCILIATION_TENANT_REQUIRED"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda page: page["items"].__setitem__(0, "invalid"),
        lambda page: page["items"][0].pop("source_hash"),
        lambda page: page["pagination"].update(next_cursor="unexpected"),
    ],
)
def test_reconciliation_rejects_malformed_item_and_pagination(mutate) -> None:
    class _InvalidSource(_PagedSource):
        def list_sources(self, **kwargs):
            page = deepcopy(super().list_sources(**kwargs))
            page["pagination"]["has_more"] = False
            page["pagination"]["next_cursor"] = None
            mutate(page)
            return page

    with pytest.raises(WaReconciliationError):
        WaAeReconciliationService(
            source=_InvalidSource(),
            intake=WaEvidenceIntakeService(InMemoryJobQueue()),
        ).run(
            tenant_id=TENANT,
            created_after=AFTER,
            created_before=BEFORE,
            mode="operator",
            page_size=1,
            max_pages_per_source=1,
        )


@pytest.mark.parametrize(("complete", "expected_exit"), [(True, 0), (False, 2)])
def test_maintenance_command_executes_bounded_mode_and_disposes(
    monkeypatch,
    capsys,
    complete,
    expected_exit,
) -> None:
    class _Persistence:
        job_queue = InMemoryJobQueue()
        disposed = False

        def dispose(self):
            self.disposed = True

    persistence = _Persistence()
    result = WaReconciliationResult(
        TENANT,
        "OPERATOR",
        AFTER,
        BEFORE,
        (WaReconciliationSourceResult("AE_AGENT_RESULT", 1, 0, 0, 0, complete, None),),
    )

    class _Service:
        def __init__(self, **kwargs):
            pass

        def run(self, **kwargs):
            return result

    monkeypatch.setattr(
        "nex_wa.reconciliation_main.build_wa_persistence_runtime",
        lambda **kwargs: persistence,
    )
    monkeypatch.setattr(
        "nex_wa.reconciliation_main.HttpAeWaReconciliationSource",
        lambda **kwargs: object(),
    )
    monkeypatch.setattr(
        "nex_wa.reconciliation_main.WaAeReconciliationService", _Service
    )
    exit_code = reconciliation_main(
        [
            "--mode",
            "operator",
            "--tenant-id",
            TENANT,
            "--created-after",
            AFTER,
            "--created-before",
            BEFORE,
        ],
        environ={
            "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK",
            "NEX_AE_API_BASE_URL": "http://127.0.0.1:8101",
        },
    )
    assert exit_code == expected_exit
    assert persistence.disposed is True
    assert '"tenant_id": "VO00"' in capsys.readouterr().out


def test_maintenance_command_redacts_bootstrap_failure(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "nex_wa.reconciliation_main.resolve_wa_outbound_service_token",
        lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("secret-token")),
    )
    assert (
        reconciliation_main(
            ["--check"],
            environ={"NEX_AE_API_BASE_URL": "http://127.0.0.1:8101"},
        )
        == 1
    )
    output = capsys.readouterr().out
    assert "secret-token" not in output
    assert "WA_RECONCILIATION_BOOTSTRAP_FAILED" in output
