from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from nex_wa.artifact_source import (
    AeArtifactSourceAdapter,
    HttpAeArtifactProjectionClient,
    HttpEosHistoricalMembershipVerificationClient,
    HttpOaHumanSubjectVerificationClient,
)
from nex_wa.intake_contracts import normalize_evidence_intake_request
from nex_wa.source_adapters import WaSourceAdapterError

TENANT = "VO00"
ARTIFACT = "artifact-001"
VERSION = "artifact-version-001"
SUBJECT = "employee-001"
PROJECT = "44444444-4444-4444-8444-444444444444"
HASH = "sha256:" + "b" * 64
NOW = datetime(2026, 10, 28, 6, 0, tzinfo=UTC)


def _projection(**overrides):
    value = {
        "tenant_id": TENANT,
        "artifact_id": ARTIFACT,
        "artifact_version_id": VERSION,
        "artifact_status": "READY",
        "owner_actor_ref": {
            "actor_type": "user",
            "actor_id": SUBJECT,
            "tenant_id": TENANT,
        },
        "artifact_content_hash": "b" * 64,
        "created_at": "2026-10-28T05:59:00Z",
        "classification": "CONFIDENTIAL",
        "producer_execution_ref": None,
        "project_ref": None,
    }
    value.update(overrides)
    return value


def _request(**overrides):
    value = {
        "schema_version": "wa_evidence_intake_request.v1",
        "tenant_id": TENANT,
        "source_type": "AE_ARTIFACT",
        "source_ref": ARTIFACT,
        "source_revision_ref": VERSION,
        "source_hash": HASH,
        "occurred_at": "2026-10-28T06:00:00Z",
        "correlation_id": "corr-p9-s19",
    }
    value.update(overrides)
    return normalize_evidence_intake_request(value)


class _Source:
    def __init__(self, projection):
        self.projection = projection

    def fetch_version(self, **_kwargs):
        return self.projection


class _Subjects:
    def __init__(self, status="VERIFIED"):
        self.status = status

    def verify_subject(self, *, tenant_id, subject_id):
        return {
            "tenant_id": tenant_id,
            "results": [
                {"subject_id": subject_id, "verification_status": self.status}
            ],
        }


class _Memberships:
    def __init__(self, status="VERIFIED"):
        self.status = status
        self.calls = []

    def verify_membership(self, **kwargs):
        self.calls.append(kwargs)
        return {
            **kwargs,
            "membership_valid": self.status == "VERIFIED",
            "verification_status": self.status,
        }


class _Admission:
    def __init__(self):
        self.calls = []

    def admit_normalized_evidence(self, evidence, asset):
        self.calls.append((evidence, asset))


def _adapter(projection, *, subjects=None, memberships=None):
    admission = _Admission()
    return (
        AeArtifactSourceAdapter(
            source=_Source(projection),
            subjects=subjects or _Subjects(),
            memberships=memberships,
            admission=admission,
            clock=lambda: NOW,
        ),
        admission,
    )


def test_human_ready_artifact_admits_without_inferred_project_or_effort() -> None:
    adapter, admission = _adapter(_projection())
    envelope = adapter.fetch(_request())

    evidence, asset = admission.calls[0]
    assert envelope.source_ref == ARTIFACT
    assert evidence.actor_type == asset.actor_type == "HUMAN"
    assert evidence.actor_ref == asset.actor_ref == SUBJECT
    assert evidence.project_ref is asset.project_ref is None
    assert evidence.agent_type_snapshot is asset.agent_type_snapshot is None
    assert asset.asset_type == "HUMAN_OWNED_ARTIFACT"


def test_agent_produced_human_owned_artifact_does_not_become_agent_or_effort() -> None:
    adapter, admission = _adapter(
        _projection(producer_execution_ref="agent-execution-9")
    )
    adapter.fetch(_request())
    evidence, asset = admission.calls[0]
    assert (evidence.actor_type, asset.actor_type) == ("HUMAN", "HUMAN")
    assert not hasattr(asset, "human_effort_candidate")


@pytest.mark.parametrize("status", ["SUBJECT_NOT_FOUND", "SUBJECT_INACTIVE"])
def test_missing_or_inactive_owner_is_denied(status) -> None:
    adapter, admission = _adapter(_projection(), subjects=_Subjects(status))
    with pytest.raises(WaSourceAdapterError) as exc_info:
        adapter.fetch(_request())
    assert exc_info.value.error_code == "WA_HUMAN_OWNER_DENIED"
    assert admission.calls == []


def test_authoritative_project_requires_historical_membership() -> None:
    memberships = _Memberships()
    adapter, admission = _adapter(
        _projection(project_ref=PROJECT), memberships=memberships
    )
    adapter.fetch(_request())
    evidence, asset = admission.calls[0]
    assert evidence.project_ref == asset.project_ref == PROJECT
    assert memberships.calls[0]["occurred_at"] == "2026-10-28T05:59:00Z"

    denied, denied_admission = _adapter(
        _projection(project_ref=PROJECT),
        memberships=_Memberships("MEMBERSHIP_EXPIRED"),
    )
    with pytest.raises(WaSourceAdapterError) as exc_info:
        denied.fetch(_request())
    assert exc_info.value.error_code == "WA_PROJECT_MEMBERSHIP_DENIED"
    assert denied_admission.calls == []


def test_project_membership_dependency_is_required_only_when_project_exists() -> None:
    adapter, admission = _adapter(_projection(project_ref=PROJECT))
    with pytest.raises(WaSourceAdapterError) as exc_info:
        adapter.fetch(_request())
    assert exc_info.value.error_code == "WA_PROJECT_MEMBERSHIP_UNAVAILABLE"
    assert exc_info.value.retryable is True
    assert admission.calls == []


@pytest.mark.parametrize(
    ("overrides", "error_code"),
    [
        ({"artifact_status": "RENDERING"}, "WA_ARTIFACT_SOURCE_MISMATCH"),
        ({"artifact_content_hash": "c" * 64}, "WA_ARTIFACT_SOURCE_MISMATCH"),
        ({"owner_actor_ref": None}, "WA_ARTIFACT_SOURCE_INVALID"),
        (
            {
                "owner_actor_ref": {
                    "actor_type": "AGENT",
                    "actor_id": SUBJECT,
                    "tenant_id": TENANT,
                }
            },
            "WA_ARTIFACT_SOURCE_INVALID",
        ),
        ({"classification": "PUBLIC"}, "WA_ARTIFACT_SOURCE_INVALID"),
        ({"created_at": "invalid"}, "WA_ARTIFACT_SOURCE_INVALID"),
        ({"created_at": None}, "WA_ARTIFACT_SOURCE_INVALID"),
        ({"created_at": "2026-10-28T05:59:00"}, "WA_ARTIFACT_SOURCE_INVALID"),
        (
            {
                "owner_actor_ref": {
                    "actor_type": "user",
                    "actor_id": None,
                    "tenant_id": TENANT,
                }
            },
            "WA_ARTIFACT_SOURCE_INVALID",
        ),
        ({"project_ref": ""}, "WA_ARTIFACT_SOURCE_INVALID"),
    ],
)
def test_artifact_projection_drift_fails_closed(overrides, error_code) -> None:
    adapter, admission = _adapter(_projection(**overrides))
    with pytest.raises(WaSourceAdapterError) as exc_info:
        adapter.fetch(_request())
    assert exc_info.value.error_code == error_code
    assert admission.calls == []


def test_classification_is_never_below_confidential() -> None:
    for source, expected in (
        ("INTERNAL", "CONFIDENTIAL"),
        ("CONFIDENTIAL", "CONFIDENTIAL"),
        ("RESTRICTED", "RESTRICTED"),
    ):
        adapter, admission = _adapter(_projection(classification=source))
        adapter.fetch(_request())
        evidence, asset = admission.calls[0]
        assert evidence.classification == asset.classification == expected


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


def test_http_artifact_oa_and_eos_clients(monkeypatch) -> None:
    responses = iter(
        [
            _projection(),
            {"tenant_id": TENANT, "results": []},
            {
                "tenant_id": TENANT,
                "project_id": PROJECT,
                "subject_id": SUBJECT,
                "occurred_at": "2026-10-28T05:59:00Z",
            },
        ]
    )
    monkeypatch.setattr(
        "nex_wa.agent_result_source.urlopen",
        lambda *_args, **_kwargs: _Response(next(responses)),
    )
    artifact = HttpAeArtifactProjectionClient(
        base_url="http://ae", service_token="signed"
    )
    subject = HttpOaHumanSubjectVerificationClient(
        base_url="http://oa", service_token="signed"
    )
    membership = HttpEosHistoricalMembershipVerificationClient(
        base_url="http://eos", service_token="signed"
    )
    assert artifact.fetch_version(
        tenant_id=TENANT, artifact_id=ARTIFACT, artifact_version_id=VERSION
    )["artifact_id"] == ARTIFACT
    assert subject.verify_subject(tenant_id=TENANT, subject_id=SUBJECT)[
        "tenant_id"
    ] == TENANT
    assert membership.verify_membership(
        tenant_id=TENANT,
        project_id=PROJECT,
        subject_id=SUBJECT,
        occurred_at="2026-10-28T05:59:00Z",
    )["project_id"] == PROJECT


def test_adapter_requires_artifact_source_type() -> None:
    adapter, _admission = _adapter(_projection())
    with pytest.raises(WaSourceAdapterError):
        adapter.fetch(_request(source_type="AE_AGENT_RESULT"))
