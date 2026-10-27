from __future__ import annotations

import json
from datetime import UTC, datetime
from urllib.error import HTTPError, URLError
from uuid import UUID

import pytest
from nex_wa.agent_result_source import (
    AeAgentResultSourceAdapter,
    HttpAeAgentResultProjectionClient,
    HttpEosProjectVerificationClient,
)
from nex_wa.intake_contracts import normalize_evidence_intake_request
from nex_wa.service_auth import resolve_wa_outbound_service_token
from nex_wa.source_adapters import WaSourceAdapterError

TENANT = "VO00"
EXECUTION = "11111111-1111-4111-8111-111111111111"
RESULT = "22222222-2222-4222-8222-222222222222"
AGENT = "33333333-3333-4333-8333-333333333333"
PROJECT = "44444444-4444-4444-8444-444444444444"
HASH = "sha256:" + "a" * 64
NOW = datetime(2026, 10, 28, 5, 0, tzinfo=UTC)


def _projection(agent_type="IA", *, complete=True):
    background = agent_type != "IA"
    return {
        "tenant_id": TENANT,
        "result_id": RESULT,
        "agent_execution_id": EXECUTION,
        "agent_id": AGENT,
        "agent_type": agent_type,
        "project_id": PROJECT if background else None,
        "status": "PARTIAL" if background else "SUCCEEDED",
        "result_hash": HASH,
        "created_at": "2026-10-28T04:59:00Z",
        "agent_execution_state": "SUCCEEDED" if complete else "RUNNING",
        "required_delivery_target_type": (
            "WC_WORK_RESULT" if background else "WORKSPACE_RESULT"
        ),
        "required_delivery_state": "ACKNOWLEDGED" if complete else "PENDING",
        "source_work_item_ref": "work-1" if background else None,
        "source_claim_ref": "claim-1" if background else None,
        "source_claim_generation": 2 if background else None,
        "source_assignment_ref": "assignment-1" if background else None,
    }


def _request(**overrides):
    payload = {
        "schema_version": "wa_evidence_intake_request.v1",
        "tenant_id": TENANT,
        "source_type": "AE_AGENT_RESULT",
        "source_ref": EXECUTION,
        "source_revision_ref": RESULT,
        "source_hash": HASH,
        "occurred_at": "2026-10-28T05:00:00Z",
        "correlation_id": "corr-p9-s17",
    }
    payload.update(overrides)
    return normalize_evidence_intake_request(payload)


class _Source:
    def __init__(self, projection):
        self.projection = projection

    def fetch_result(self, **_kwargs):
        return self.projection


class _Projects:
    def __init__(self, status="VERIFIED"):
        self.status = status
        self.calls = []

    def verify_project(self, *, tenant_id, project_id):
        self.calls.append((tenant_id, project_id))
        return {
            "tenant_id": tenant_id,
            "results": [
                {"project_id": project_id, "verification_status": self.status}
            ],
        }


class _Admission:
    def __init__(self):
        self.calls = []

    def admit_normalized_evidence(self, evidence, asset):
        self.calls.append((evidence, asset))
        return object()


def _adapter(projection, *, projects=None):
    admission = _Admission()
    adapter = AeAgentResultSourceAdapter(
        source=_Source(projection),
        admission=admission,
        projects=projects,
        clock=lambda: NOW,
    )
    return adapter, admission


def test_ia_post_ack_creates_one_primary_project_neutral_asset() -> None:
    adapter, admission = _adapter(_projection())
    envelope = adapter.fetch(_request())

    evidence, asset = admission.calls[0]
    assert envelope.source_ref == EXECUTION
    assert evidence.actor_type == asset.actor_type == "AGENT"
    assert evidence.agent_type_snapshot == asset.agent_type_snapshot == "IA"
    assert evidence.project_ref is asset.project_ref is None
    assert asset.agent_execution_id == EXECUTION
    assert asset.bindings[0].binding_role == "PRIMARY"
    assert UUID(asset.bindings[0].work_evidence_id)


@pytest.mark.parametrize("agent_type", ["CA", "PA", "EA"])
def test_claimed_background_profiles_require_and_verify_project(agent_type) -> None:
    projects = _Projects()
    adapter, admission = _adapter(_projection(agent_type), projects=projects)
    adapter.fetch(_request())

    evidence, asset = admission.calls[0]
    assert projects.calls == [(TENANT, PROJECT)]
    assert evidence.project_ref == asset.project_ref == PROJECT
    assert asset.agent_type_snapshot == agent_type


def test_incomplete_result_is_typed_retry_and_never_admitted() -> None:
    adapter, admission = _adapter(_projection(complete=False))
    with pytest.raises(WaSourceAdapterError) as exc_info:
        adapter.fetch(_request())
    assert exc_info.value.error_code == "WA_AGENT_RESULT_NOT_COMPLETE"
    assert exc_info.value.retryable is True
    assert admission.calls == []


@pytest.mark.parametrize(
    ("agent_type", "mutate"),
    [
        ("IA", lambda p: p.update(agent_type="AUTONOMOUS_HARNESS")),
        ("IA", lambda p: p.update(project_id=PROJECT)),
        ("IA", lambda p: p.update(required_delivery_target_type="WC_WORK_RESULT")),
        ("PA", lambda p: p.update(source_claim_ref=None)),
        ("PA", lambda p: p.update(source_claim_generation=True)),
    ],
)
def test_unknown_or_malformed_authority_profile_fails_closed(
    agent_type, mutate
) -> None:
    projection = _projection(agent_type)
    mutate(projection)
    adapter, admission = _adapter(projection, projects=_Projects())
    with pytest.raises(WaSourceAdapterError) as exc_info:
        adapter.fetch(_request())
    assert exc_info.value.error_code == "WA_AGENT_AUTHORITY_PROFILE_UNSUPPORTED"
    assert exc_info.value.retryable is False
    assert admission.calls == []


def test_identity_drift_and_project_denial_fail_closed() -> None:
    drifted = _projection()
    drifted["result_hash"] = "sha256:" + "b" * 64
    with pytest.raises(WaSourceAdapterError) as identity:
        _adapter(drifted)[0].fetch(_request())
    assert identity.value.error_code == "WA_AGENT_RESULT_SOURCE_MISMATCH"

    adapter, admission = _adapter(
        _projection("CA"), projects=_Projects("PROJECT_INACTIVE")
    )
    with pytest.raises(WaSourceAdapterError) as project:
        adapter.fetch(_request())
    assert project.value.error_code == "WA_PROJECT_ATTRIBUTION_DENIED"
    assert admission.calls == []


def test_background_requires_project_verifier_and_adapter_type_matches() -> None:
    adapter, _admission = _adapter(_projection("CA"))
    with pytest.raises(WaSourceAdapterError) as unavailable:
        adapter.fetch(_request())
    assert unavailable.value.error_code == "WA_PROJECT_VERIFICATION_UNAVAILABLE"

    with pytest.raises(WaSourceAdapterError) as mismatch:
        _adapter(_projection())[0].fetch(_request(source_type="AE_ARTIFACT"))
    assert mismatch.value.error_code == "WA_AGENT_RESULT_SOURCE_INVALID"


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


def test_http_source_and_project_clients_use_bounded_signed_boundaries(monkeypatch) -> None:
    responses = iter([_projection(), {"tenant_id": TENANT, "results": []}])
    monkeypatch.setattr(
        "nex_wa.agent_result_source.urlopen",
        lambda *_args, **_kwargs: _Response(next(responses)),
    )
    source = HttpAeAgentResultProjectionClient(
        base_url="http://ae", service_token="signed"
    )
    projects = HttpEosProjectVerificationClient(
        base_url="http://eos", service_token="signed"
    )
    assert source.fetch_result(tenant_id=TENANT, result_id=RESULT)["result_id"] == RESULT
    assert projects.verify_project(tenant_id=TENANT, project_id=PROJECT)[
        "tenant_id"
    ] == TENANT


@pytest.mark.parametrize(
    ("error", "retryable"),
    [
        (HTTPError("http://ae", 409, "conflict", None, None), False),
        (HTTPError("http://ae", 503, "offline", None, None), True),
        (URLError("offline"), True),
    ],
)
def test_http_source_failures_are_typed(monkeypatch, error, retryable) -> None:
    monkeypatch.setattr(
        "nex_wa.agent_result_source.urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(error),
    )
    client = HttpAeAgentResultProjectionClient(
        base_url="http://ae", service_token="signed"
    )
    with pytest.raises(WaSourceAdapterError) as exc_info:
        client.fetch_result(tenant_id=TENANT, result_id=RESULT)
    assert exc_info.value.retryable is retryable


def test_invalid_transport_configuration_and_response_fail_closed(monkeypatch) -> None:
    with pytest.raises(WaSourceAdapterError):
        HttpAeAgentResultProjectionClient(
            base_url="http://ae", service_token=""
        ).fetch_result(tenant_id=TENANT, result_id=RESULT)
    monkeypatch.setattr(
        "nex_wa.agent_result_source.urlopen",
        lambda *_args, **_kwargs: _Response([]),
    )
    with pytest.raises(WaSourceAdapterError):
        HttpAeAgentResultProjectionClient(
            base_url="http://ae", service_token="signed"
        ).fetch_result(tenant_id=TENANT, result_id=RESULT)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("created_at", None),
        ("created_at", "not-a-time"),
        ("created_at", "2026-10-28T05:00:00"),
        ("agent_id", None),
    ],
)
def test_malformed_projection_fields_fail_closed(field, value) -> None:
    projection = _projection()
    projection[field] = value
    with pytest.raises(WaSourceAdapterError):
        _adapter(projection)[0].fetch(_request())


def test_wa_outbound_token_profiles_are_fail_closed() -> None:
    scopes = ("service:call", "work:source:read")
    assert resolve_wa_outbound_service_token(
        "signed", audience="nex-ae-api", scopes=scopes, environ={}
    ) == "signed"
    assert resolve_wa_outbound_service_token(
        None,
        audience="nex-ae-api",
        scopes=scopes,
        environ={"NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "TEST_MOCK"},
    )
    assert resolve_wa_outbound_service_token(
        None,
        audience="nex-ae-api",
        scopes=scopes,
        environ={
            "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "SIGNED_ONLY",
            "NEX_WA_TO_AE_SERVICE_TOKEN": "signed",
        },
    ) == "signed"
    for configured, environ in (
        (" bad", {}),
        (None, {"NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "INVALID"}),
        (None, {"NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "SIGNED_ONLY"}),
        (
            None,
            {
                "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "SIGNED_ONLY",
                "NEX_WA_TO_AE_SERVICE_TOKEN": " bad",
            },
        ),
    ):
        with pytest.raises(ValueError):
            resolve_wa_outbound_service_token(
                configured,
                audience="nex-ae-api",
                scopes=scopes,
                environ=environ,
            )
