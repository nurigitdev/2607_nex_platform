from __future__ import annotations

import json
from copy import deepcopy

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from nex_ae_api.artifacts import ArtifactHandoffError
from nex_ae_api.wa_source_projections import (
    SqlAlchemyArtifactWaProjectionSource,
    WaSourceProjectionError,
    build_artifact_wa_projection,
    register_wa_artifact_source_routes,
)
from nex_runtime import issue_mock_service_token

TENANT = "VO00"
ARTIFACT_ID = "artifact-001"
VERSION_ID = "artifact-version-001"


def _record(*, status: str = "READY", producer: str | None = None):
    return {
        "artifact_id": ARTIFACT_ID,
        "artifact_status": status,
        "owner_actor_ref": {
            "actor_type": "user",
            "actor_id": "employee-001",
            "tenant_id": TENANT,
            "private_claim": "must-not-leak",
        },
        "workspace_ref": {"workspace_id": "workspace-001", "tenant_id": TENANT},
        "producer_execution_ref": producer,
        "project_ref": None,
        "source_refs": [{"structured_draft_content_hash": "a" * 64}],
        "versions": [
            {
                "artifact_id": ARTIFACT_ID,
                "artifact_version_id": VERSION_ID,
                "source_generation_id": "cx-generation-001",
                "source_content_hash": "a" * 64,
                "artifact_content_hash": "b" * 64,
                "created_at": "2026-10-28T01:00:00Z",
                "rendered_bytes": b"must-not-leak",
            }
        ],
        "files": [{"storage_ref": "ae://private/artifact-001"}],
        "rendered_markdown": "must-not-leak",
    }


class _Repository:
    def __init__(self, record=None, error=None) -> None:
        self.record = record
        self.error = error

    def get(self, artifact_id: str):
        if self.error is not None:
            raise self.error
        if artifact_id != ARTIFACT_ID:
            return None
        return self.record


class _Source:
    def __init__(self, record=None, error=None) -> None:
        self.record = record
        self.error = error

    def get_projection(self, *, tenant_id, artifact_id, artifact_version_id):
        if self.error is not None:
            raise self.error
        if tenant_id != TENANT or artifact_id != ARTIFACT_ID:
            return None
        return build_artifact_wa_projection(
            self.record,
            artifact_version_id=artifact_version_id,
        )


def _client(source) -> TestClient:
    app = FastAPI()
    register_wa_artifact_source_routes(app, source=source)
    return TestClient(app)


def _headers(*, service_id: str = "nex-wa", scopes=None, tenant: str = TENANT):
    token = issue_mock_service_token(
        service_id=service_id,
        audience="nex-ae-api",
        scopes=scopes or ["service:call", "work:source:read"],
    ).access_token
    return {"Authorization": f"Bearer {token}", "X-NeX-Tenant-Id": tenant}


def test_exact_ready_version_projection_excludes_bytes_and_raw_content() -> None:
    response = _client(_Source(_record())).get(
        f"/internal/v1/wa-sources/artifacts/{ARTIFACT_ID}/versions/{VERSION_ID}",
        headers=_headers(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["artifact_status"] == "READY"
    assert payload["owner_actor_ref"]["actor_type"] == "user"
    assert "private_claim" not in payload["owner_actor_ref"]
    assert payload["classification"] == "CONFIDENTIAL"
    assert payload["producer_execution_ref"] is None
    assert payload["project_ref"] is None
    serialized = json.dumps(payload)
    assert "rendered" not in serialized
    assert "storage_ref" not in serialized
    assert "must-not-leak" not in serialized


def test_agent_produced_human_owned_artifact_keeps_distinct_lineage() -> None:
    projection = build_artifact_wa_projection(
        _record(producer="agent-execution-001"),
        artifact_version_id=VERSION_ID,
    )
    assert projection is not None
    assert projection["owner_actor_ref"]["actor_type"] == "user"
    assert projection["producer_execution_ref"] == "agent-execution-001"


def test_exact_version_mismatch_is_not_found() -> None:
    response = _client(_Source(_record())).get(
        f"/internal/v1/wa-sources/artifacts/{ARTIFACT_ID}/versions/other-version",
        headers=_headers(),
    )
    assert response.status_code == 404


@pytest.mark.parametrize(
    ("mutate", "error_code"),
    [
        (lambda value: value.update(artifact_status="ARCHIVED"), "not_ready"),
        (
            lambda value: value["versions"][0].update(source_content_hash="c" * 64),
            "content_hash_mismatch",
        ),
        (
            lambda value: value["versions"][0].update(artifact_id="other-artifact"),
            "artifact_invalid",
        ),
    ],
)
def test_projection_rejects_non_admissible_or_inconsistent_version(
    mutate,
    error_code,
) -> None:
    record = _record()
    mutate(record)
    with pytest.raises(WaSourceProjectionError) as exc_info:
        build_artifact_wa_projection(record, artifact_version_id=VERSION_ID)
    assert error_code in exc_info.value.error_code


@pytest.mark.parametrize(
    ("headers", "status"),
    [
        ({"X-NeX-Tenant-Id": TENANT}, 401),
        (_headers(scopes=["service:call"]), 401),
        (_headers(service_id="nex-ag"), 403),
        (_headers(tenant="other-tenant"), 404),
    ],
)
def test_route_fails_closed_for_auth_scope_caller_and_tenant(headers, status) -> None:
    response = _client(_Source(_record())).get(
        f"/internal/v1/wa-sources/artifacts/{ARTIFACT_ID}/versions/{VERSION_ID}",
        headers=headers,
    )
    assert response.status_code == status


def test_route_requires_tenant_and_available_source() -> None:
    no_tenant = _headers()
    no_tenant.pop("X-NeX-Tenant-Id")
    path = f"/internal/v1/wa-sources/artifacts/{ARTIFACT_ID}/versions/{VERSION_ID}"
    assert _client(_Source(_record())).get(path, headers=no_tenant).status_code == 400
    assert _client(None).get(path, headers=_headers()).status_code == 503


@pytest.mark.parametrize(("retryable", "status"), [(False, 409), (True, 503)])
def test_route_maps_typed_source_failures(retryable, status) -> None:
    source = _Source(
        error=WaSourceProjectionError("ae.wa_source_failed", "failed", retryable)
    )
    response = _client(source).get(
        f"/internal/v1/wa-sources/artifacts/{ARTIFACT_ID}/versions/{VERSION_ID}",
        headers=_headers(),
    )
    assert response.status_code == status


def test_sqlalchemy_source_is_tenant_exact_and_maps_repository_failure() -> None:
    source = SqlAlchemyArtifactWaProjectionSource(_Repository(_record()))
    assert (
        source.get_projection(
            tenant_id="other-tenant",
            artifact_id=ARTIFACT_ID,
            artifact_version_id=VERSION_ID,
        )
        is None
    )
    assert source.get_projection(
        tenant_id=TENANT,
        artifact_id=ARTIFACT_ID,
        artifact_version_id=VERSION_ID,
    )["artifact_id"] == ARTIFACT_ID

    unavailable = SqlAlchemyArtifactWaProjectionSource(
        _Repository(error=ArtifactHandoffError(503, "ae.store_offline", "offline", True))
    )
    with pytest.raises(WaSourceProjectionError, match="offline") as exc_info:
        unavailable.get_projection(
            tenant_id=TENANT,
            artifact_id=ARTIFACT_ID,
            artifact_version_id=VERSION_ID,
        )
    assert exc_info.value.retryable is True


def test_projection_rejects_invalid_hash_and_tenant_reference_shapes() -> None:
    record = _record()
    invalid_hash = deepcopy(record)
    invalid_hash["versions"][0]["artifact_content_hash"] = "not-a-hash"
    with pytest.raises(WaSourceProjectionError, match="SHA-256"):
        build_artifact_wa_projection(invalid_hash, artifact_version_id=VERSION_ID)

    invalid_owner = deepcopy(record)
    invalid_owner["owner_actor_ref"] = {"actor_id": "employee-001"}
    with pytest.raises(WaSourceProjectionError, match="owner"):
        build_artifact_wa_projection(invalid_owner, artifact_version_id=VERSION_ID)

    tenant_drift = deepcopy(record)
    tenant_drift["workspace_ref"]["tenant_id"] = "other-tenant"
    with pytest.raises(WaSourceProjectionError, match="inconsistent"):
        build_artifact_wa_projection(tenant_drift, artifact_version_id=VERSION_ID)
