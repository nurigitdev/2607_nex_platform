from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from nex_runtime import DEFAULT_SERVICE_SCOPE, issue_mock_service_token
from nex_wa import (
    WA_EVIDENCE_AUDIT_READ_SCOPE,
    WA_EVIDENCE_DETAIL_READ_SCOPE,
    WA_EVIDENCE_READ_SCOPE,
    SqlAlchemyWorkEvidenceRepository,
    WaCoreReadService,
    WaReadError,
    WorkAssetBindingInput,
    WorkAssetInput,
    WorkEvidenceError,
    WorkEvidenceInput,
    build_work_asset,
    build_work_evidence,
)
from nex_wa.app import create_wa_app
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

NOW = datetime(2026, 10, 28, 7, 0, tzinfo=UTC)
TENANT = "VO00"


def _candidate(**overrides) -> WorkEvidenceInput:
    values = {
        "tenant_id": TENANT,
        "source_owner": "nex-ae-api",
        "source_type": "AE_ARTIFACT",
        "source_ref": "artifact-correction-001",
        "source_revision_ref": "version-1",
        "source_hash": "sha256:" + "1" * 64,
        "evidence_kind": "OWNERSHIP_OR_DELIVERABLE_EVIDENCE",
        "actor_type": "HUMAN",
        "actor_ref": "employee-001",
        "occurred_at": NOW,
        "observed_at": NOW + timedelta(seconds=1),
        "classification": "CONFIDENTIAL",
    }
    values.update(overrides)
    return WorkEvidenceInput(**values)


@pytest.fixture
def evidence_repository() -> SqlAlchemyWorkEvidenceRepository:
    engine = create_engine("sqlite+pysqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _foreign_keys(connection, _record) -> None:
        connection.execute("PRAGMA foreign_keys=ON")

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE wa_work_evidence (
                    tenant_id TEXT NOT NULL,
                    work_evidence_id TEXT NOT NULL,
                    source_owner TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_ref TEXT NOT NULL,
                    source_revision_ref TEXT NOT NULL,
                    source_hash TEXT NOT NULL,
                    evidence_kind TEXT NOT NULL,
                    actor_type TEXT NOT NULL,
                    actor_ref TEXT NOT NULL,
                    agent_type_snapshot TEXT,
                    project_ref TEXT,
                    occurred_at TIMESTAMP NOT NULL,
                    observed_at TIMESTAMP NOT NULL,
                    classification TEXT NOT NULL,
                    evidence_status TEXT NOT NULL,
                    evidence_hash TEXT NOT NULL,
                    supersedes_evidence_id TEXT,
                    created_at TIMESTAMP NOT NULL,
                    PRIMARY KEY (tenant_id, work_evidence_id),
                    UNIQUE (tenant_id, source_type, source_ref, source_revision_ref),
                    FOREIGN KEY (tenant_id, supersedes_evidence_id)
                        REFERENCES wa_work_evidence (tenant_id, work_evidence_id)
                )
                """
            )
        )
    return SqlAlchemyWorkEvidenceRepository(
        sessionmaker(bind=engine, autoflush=False, expire_on_commit=False),
        clock=lambda: NOW + timedelta(minutes=1),
    )


def test_correction_is_immutable_atomic_and_auditable(evidence_repository) -> None:
    first = evidence_repository.create_or_get(_candidate())
    correction = evidence_repository.create_or_get(
        _candidate(
            source_revision_ref="version-2",
            source_hash="sha256:" + "2" * 64,
            supersedes_evidence_id=first.work_evidence_id,
        )
    )

    stored_first = evidence_repository.get(TENANT, first.work_evidence_id)
    assert stored_first.evidence_status == "SUPERSEDED"
    assert stored_first.source_hash == first.source_hash
    assert stored_first.evidence_hash == first.evidence_hash
    assert correction.evidence_status == "ACTIVE"
    assert correction.supersedes_evidence_id == first.work_evidence_id
    assert evidence_repository.create_or_get(
        _candidate(
            source_revision_ref="version-2",
            source_hash="sha256:" + "2" * 64,
            supersedes_evidence_id=first.work_evidence_id,
        )
    ) == correction

    lineage = evidence_repository.list_source_lineage(
        TENANT, correction.work_evidence_id
    )
    assert [item.evidence_status for item in lineage] == ["SUPERSEDED", "ACTIVE"]
    invalidated = evidence_repository.invalidate(TENANT, correction.work_evidence_id)
    assert invalidated.evidence_status == "INVALIDATED"
    assert evidence_repository.invalidate(TENANT, correction.work_evidence_id) == invalidated


def test_correction_rejects_unrelated_target_and_hash_conflict(
    evidence_repository,
) -> None:
    first = evidence_repository.create_or_get(_candidate())
    unrelated = evidence_repository.create_or_get(
        _candidate(
            source_ref="artifact-other",
            source_revision_ref="version-1",
            source_hash="sha256:" + "3" * 64,
        )
    )
    with pytest.raises(WorkEvidenceError) as wrong_lineage:
        evidence_repository.create_or_get(
            _candidate(
                source_revision_ref="version-2",
                supersedes_evidence_id=unrelated.work_evidence_id,
            )
        )
    assert wrong_lineage.value.error_code == "WA_SUPERSESSION_INVALID"

    with pytest.raises(WorkEvidenceError) as conflict:
        evidence_repository.create_or_get(
            _candidate(source_hash="sha256:" + "4" * 64)
        )
    assert conflict.value.error_code == "WA_SOURCE_IDEMPOTENCY_CONFLICT"
    assert evidence_repository.get(TENANT, first.work_evidence_id).evidence_status == "ACTIVE"
    assert evidence_repository.list_source_lineage(
        TENANT, "99999999-9999-4999-8999-999999999999"
    ) == ()
    with pytest.raises(WorkEvidenceError) as missing:
        evidence_repository.invalidate(
            TENANT, "99999999-9999-4999-8999-999999999999"
        )
    assert missing.value.error_code == "WA_EVIDENCE_NOT_FOUND"


class _EvidenceRepository:
    def __init__(self, records):
        self.records = records

    def get(self, tenant_id, record_id):
        return self.records.get((tenant_id, record_id))

    def list_source_lineage(self, tenant_id, record_id):
        anchor = self.get(tenant_id, record_id)
        if anchor is None:
            return ()
        return tuple(
            record
            for (item_tenant, _item_id), record in self.records.items()
            if item_tenant == tenant_id
            and record.source_type == anchor.source_type
            and record.source_ref == anchor.source_ref
        )


class _AssetRepository:
    def __init__(self, records):
        self.records = records

    def get(self, tenant_id, record_id):
        return self.records.get((tenant_id, record_id))


def _read_service():
    first = build_work_evidence(_candidate(), created_at=NOW)
    second = build_work_evidence(
        _candidate(
            source_revision_ref="version-2",
            source_hash="sha256:" + "2" * 64,
            supersedes_evidence_id=first.work_evidence_id,
        ),
        created_at=NOW + timedelta(minutes=1),
    )
    first = replace(first, evidence_status="SUPERSEDED")
    asset = build_work_asset(
        WorkAssetInput(
            tenant_id=TENANT,
            asset_type="HUMAN_OWNED_ARTIFACT",
            artifact_id="artifact-correction-001",
            artifact_version_id="version-2",
            actor_type="HUMAN",
            actor_ref="employee-001",
            occurred_at=NOW,
            classification="CONFIDENTIAL",
            bindings=(WorkAssetBindingInput(second.work_evidence_id, "PRIMARY"),),
        ),
        created_at=NOW,
        updated_at=NOW,
    )
    evidence = {
        (TENANT, first.work_evidence_id): first,
        (TENANT, second.work_evidence_id): second,
    }
    service = WaCoreReadService(
        _EvidenceRepository(evidence),
        _AssetRepository({(TENANT, asset.work_asset_id): asset}),
    )
    return service, first, second, asset


def _token(*scopes, audience="nex-wa") -> str:
    return issue_mock_service_token(
        service_id="nex-ae-api",
        audience=audience,
        scopes=(DEFAULT_SERVICE_SCOPE, *scopes),
    ).access_token


def _headers(token: str, tenant_id: str = TENANT):
    return {
        "Authorization": f"Bearer {token}",
        "X-NeX-Tenant-Id": tenant_id,
    }


def test_basic_detail_and_audit_scopes_are_separated() -> None:
    service, first, second, asset = _read_service()
    app = create_wa_app(
        environ={
            "NEX_PROFILE": "test",
            "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK",
        }
    )
    app.state.wa_core_read_service = service
    client = TestClient(app)
    basic = _token(WA_EVIDENCE_READ_SCOPE)
    detail = _token(WA_EVIDENCE_READ_SCOPE, WA_EVIDENCE_DETAIL_READ_SCOPE)
    audit = _token(
        WA_EVIDENCE_READ_SCOPE,
        WA_EVIDENCE_DETAIL_READ_SCOPE,
        WA_EVIDENCE_AUDIT_READ_SCOPE,
    )

    summary = client.get(
        f"/internal/v1/work-assets/{asset.work_asset_id}", headers=_headers(basic)
    )
    assert summary.status_code == 200
    assert summary.json()["evidence_count"] == 1
    assert "bindings" not in summary.json()
    assert client.get(
        f"/internal/v1/work-evidence/{second.work_evidence_id}",
        headers=_headers(basic),
    ).status_code == 403
    assert client.get(
        f"/internal/v1/work-evidence/{first.work_evidence_id}/audit",
        headers=_headers(detail),
    ).status_code == 403

    audit_response = client.get(
        f"/internal/v1/work-evidence/{first.work_evidence_id}/audit",
        headers=_headers(audit),
    )
    assert audit_response.status_code == 200
    assert [item["evidence_status"] for item in audit_response.json()["items"]] == [
        "SUPERSEDED",
        "ACTIVE",
    ]
    assert client.get(
        f"/internal/v1/work-evidence/{first.work_evidence_id}/audit",
        headers=_headers(audit, tenant_id="OTHER"),
    ).status_code == 404
    assert client.get(
        f"/internal/v1/work-assets/{asset.work_asset_id}",
        headers=_headers(_token(WA_EVIDENCE_READ_SCOPE, audience="nex-ae-api")),
    ).status_code == 403


def test_audit_read_failures_are_typed() -> None:
    service, first, _second, _asset = _read_service()
    with pytest.raises(WaReadError) as missing:
        service.get_evidence_audit(
            TENANT, "99999999-9999-4999-8999-999999999999"
        )
    assert missing.value.status_code == 404

    class BrokenEvidence:
        def list_source_lineage(self, *_args):
            raise WorkEvidenceError("WA_EVIDENCE_STORE_UNAVAILABLE", "redacted", 503)

    broken = WaCoreReadService(BrokenEvidence(), _AssetRepository({}))
    with pytest.raises(WaReadError) as unavailable:
        broken.get_evidence_audit(TENANT, first.work_evidence_id)
    assert unavailable.value.status_code == 503
