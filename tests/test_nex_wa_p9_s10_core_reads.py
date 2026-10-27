from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from nex_runtime import DEFAULT_SERVICE_SCOPE, issue_mock_service_token
from nex_wa import (
    WA_EVIDENCE_DETAIL_READ_SCOPE,
    WA_EVIDENCE_READ_SCOPE,
    WaCoreReadService,
    WaPersistenceError,
    WorkAssetBindingInput,
    WorkAssetError,
    WorkAssetInput,
    WorkEvidenceError,
    WorkEvidenceInput,
    build_work_asset,
    build_work_evidence,
)
from nex_wa.app import create_wa_app
from nex_wa.consumer_main import check_consumer_readiness, main

NOW = datetime(2026, 10, 27, 13, 0, tzinfo=UTC)
TENANT = "VO00"
ROOT = Path(__file__).resolve().parents[1]


class _Repository:
    def __init__(self, records):
        self.records = records

    def get(self, tenant_id, record_id):
        return self.records.get((tenant_id, record_id))


def _records():
    primary = build_work_evidence(
        WorkEvidenceInput(
            tenant_id=TENANT,
            source_owner="nex-ae-api",
            source_type="AE_AGENT_RESULT",
            source_ref="execution-primary",
            source_revision_ref="result-1",
            source_hash="sha256:" + "1" * 64,
            evidence_kind="AGENT_EXECUTION_RESULT",
            actor_type="AGENT",
            actor_ref="agent-1",
            agent_type_snapshot="IA",
            project_ref=None,
            occurred_at=NOW + timedelta(minutes=2),
            observed_at=NOW + timedelta(minutes=3),
            classification="CONFIDENTIAL",
        ),
        created_at=NOW + timedelta(minutes=3),
    )
    support_late = build_work_evidence(
        WorkEvidenceInput(
            tenant_id=TENANT,
            source_owner="nex-ae-api",
            source_type="AE_ARTIFACT",
            source_ref="artifact-late",
            source_revision_ref="version-1",
            source_hash="sha256:" + "2" * 64,
            evidence_kind="ARTIFACT",
            actor_type="HUMAN",
            actor_ref="subject-1",
            occurred_at=NOW + timedelta(minutes=1),
            observed_at=NOW + timedelta(minutes=3),
            classification="CONFIDENTIAL",
        ),
        created_at=NOW + timedelta(minutes=3),
    )
    support_early = build_work_evidence(
        WorkEvidenceInput(
            tenant_id=TENANT,
            source_owner="nex-ae-api",
            source_type="AE_ARTIFACT",
            source_ref="artifact-early",
            source_revision_ref="version-1",
            source_hash="sha256:" + "3" * 64,
            evidence_kind="ARTIFACT",
            actor_type="HUMAN",
            actor_ref="subject-1",
            occurred_at=NOW,
            observed_at=NOW + timedelta(minutes=3),
            classification="CONFIDENTIAL",
        ),
        created_at=NOW + timedelta(minutes=3),
    )
    asset = build_work_asset(
        WorkAssetInput(
            tenant_id=TENANT,
            asset_type="AGENT_EXECUTION_RESULT",
            agent_execution_id="execution-primary",
            actor_type="AGENT",
            actor_ref="agent-1",
            agent_type_snapshot="IA",
            occurred_at=NOW + timedelta(minutes=2),
            classification="CONFIDENTIAL",
            bindings=(
                WorkAssetBindingInput(primary.work_evidence_id, "PRIMARY"),
                WorkAssetBindingInput(support_late.work_evidence_id, "SUPPORTING"),
                WorkAssetBindingInput(support_early.work_evidence_id, "SUPPORTING"),
            ),
        ),
        created_at=NOW + timedelta(minutes=3),
        updated_at=NOW + timedelta(minutes=3),
    )
    evidence = {
        (TENANT, record.work_evidence_id): record
        for record in (primary, support_late, support_early)
    }
    return primary, support_early, support_late, asset, WaCoreReadService(
        _Repository(evidence), _Repository({(TENANT, asset.work_asset_id): asset})
    )


def _token(
    *,
    service_id: str = "nex-ae-api",
    scopes: tuple[str, ...] = (
        DEFAULT_SERVICE_SCOPE,
        WA_EVIDENCE_READ_SCOPE,
        WA_EVIDENCE_DETAIL_READ_SCOPE,
    ),
) -> str:
    return issue_mock_service_token(
        service_id=service_id, audience="nex-wa", scopes=scopes
    ).access_token


def _headers(token: str, tenant_id: str = TENANT):
    return {
        "Authorization": f"Bearer {token}",
        "X-NeX-Tenant-Id": tenant_id,
        "X-Request-ID": "request-p9-s10",
        "traceparent": "00-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-bbbbbbbbbbbbbbbb-01",
    }


def _client():
    app = create_wa_app(
        environ={
            "NEX_PROFILE": "test",
            "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK",
        }
    )
    records = _records()
    app.state.wa_core_read_service = records[-1]
    return TestClient(app), records


def test_core_read_service_projects_exact_records_and_ordered_lineage() -> None:
    primary, support_early, support_late, asset, service = _records()

    assert service.get_evidence(TENANT, primary.work_evidence_id)[
        "schema_version"
    ] == "wa_work_evidence.v1"
    assert service.get_asset(TENANT, asset.work_asset_id)["bindings"][0][
        "binding_role"
    ] == "PRIMARY"
    lineage = service.get_asset_evidence(TENANT, asset.work_asset_id)
    assert [item["evidence"]["work_evidence_id"] for item in lineage["items"]] == [
        primary.work_evidence_id,
        support_early.work_evidence_id,
        support_late.work_evidence_id,
    ]


def test_protected_routes_enforce_basic_detail_caller_and_tenant_boundaries() -> None:
    client, records = _client()
    primary, _early, _late, asset, _service = records
    basic = _token(scopes=(DEFAULT_SERVICE_SCOPE, WA_EVIDENCE_READ_SCOPE))

    asset_response = client.get(
        f"/internal/v1/work-assets/{asset.work_asset_id}", headers=_headers(basic)
    )
    evidence_denied = client.get(
        f"/internal/v1/work-evidence/{primary.work_evidence_id}",
        headers=_headers(basic),
    )
    evidence_response = client.get(
        f"/internal/v1/work-evidence/{primary.work_evidence_id}",
        headers=_headers(_token()),
    )
    lineage_response = client.get(
        f"/internal/v1/work-assets/{asset.work_asset_id}/evidence",
        headers=_headers(_token(service_id="nex-ag")),
    )

    assert asset_response.status_code == 200
    assert asset_response.json()["schema_version"] == "wa_work_asset.v1"
    assert evidence_denied.status_code == 403
    assert evidence_response.status_code == 200
    assert lineage_response.status_code == 200
    assert len(lineage_response.json()["items"]) == 3

    forbidden = client.get(
        f"/internal/v1/work-assets/{asset.work_asset_id}",
        headers=_headers(_token(service_id="nex-cx")),
    )
    wrong_tenant = client.get(
        f"/internal/v1/work-assets/{asset.work_asset_id}",
        headers=_headers(_token(), tenant_id="OTHER"),
    )
    invalid_tenant = client.get(
        f"/internal/v1/work-assets/{asset.work_asset_id}",
        headers=_headers(_token(), tenant_id=" VO00"),
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["error_code"] == "WA_READ_CALLER_FORBIDDEN"
    assert wrong_tenant.status_code == 404
    assert invalid_tenant.status_code == 422


def test_read_service_and_route_failures_are_typed_and_redacted() -> None:
    primary, _early, _late, asset, _service = _records()

    class BrokenEvidence:
        def get(self, *_args):
            raise WorkEvidenceError("WA_EVIDENCE_STORE_UNAVAILABLE", "redacted", 503)

    class BrokenAsset:
        def get(self, *_args):
            raise WorkAssetError("WA_ASSET_STORE_UNAVAILABLE", "redacted", 503)

    broken = WaCoreReadService(BrokenEvidence(), BrokenAsset())  # type: ignore[arg-type]
    with pytest.raises(Exception) as evidence_error:
        broken.get_evidence(TENANT, primary.work_evidence_id)
    with pytest.raises(Exception) as asset_error:
        broken.get_asset(TENANT, asset.work_asset_id)
    assert evidence_error.value.error_code == "WA_EVIDENCE_STORE_UNAVAILABLE"
    assert asset_error.value.error_code == "WA_ASSET_STORE_UNAVAILABLE"

    app = create_wa_app(
        environ={
            "NEX_PROFILE": "test",
            "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK",
        }
    )
    client = TestClient(app)
    unavailable = client.get(
        f"/internal/v1/work-assets/{asset.work_asset_id}", headers=_headers(_token())
    )
    assert unavailable.status_code == 503
    assert unavailable.json()["error_code"] == "WA_READ_UNAVAILABLE"


def test_read_contract_fixtures_validate() -> None:
    from jsonschema import Draft202012Validator

    for schema_name, example_name in (
        ("wa_work_evidence.v1", "wa_work_evidence.agent_result"),
        ("wa_work_asset.v1", "wa_work_asset.agent_result"),
        (
            "wa_work_asset_evidence_lineage.v1",
            "wa_work_asset_evidence_lineage.mixed",
        ),
    ):
        schema = json.loads(
            (
                ROOT
                / f"contracts/schemas/service/nex_wa/{schema_name}.schema.json"
            ).read_text(encoding="utf-8")
        )
        example = json.loads(
            (ROOT / f"contracts/examples/service/{example_name}.json").read_text(
                encoding="utf-8"
            )
        )
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(example)


def test_consumer_check_reports_ready_not_ready_and_disposes(capsys) -> None:
    class Runtime:
        def __init__(self, ready=True):
            self.ready = ready
            self.disposed = False

        def migration_readiness(self):
            return {"name": "wa_migrations", "ok": self.ready}

        def consumer_storage_readiness(self):
            return {"name": "wa_consumer_storage", "ok": self.ready}

        def dispose(self):
            self.disposed = True

    runtime = Runtime()
    assert main(
        ["--check"], environ={}, persistence_builder=lambda **_: runtime
    ) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["readiness_status"] == "READY"
    assert runtime.disposed is True

    unavailable = check_consumer_readiness(
        {},
        persistence_builder=lambda **_: (_ for _ in ()).throw(
            WaPersistenceError("unavailable")
        ),
    )
    assert unavailable["readiness_status"] == "NOT_READY"
    not_ready_runtime = Runtime(ready=False)
    assert main(
        ["--check"],
        environ={},
        persistence_builder=lambda **_: not_ready_runtime,
    ) == 1
    assert json.loads(capsys.readouterr().out)["readiness_status"] == "NOT_READY"
    with pytest.raises(SystemExit):
        main([], environ={}, persistence_builder=lambda **_: Runtime())
