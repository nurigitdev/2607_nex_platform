from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from nex_ae_api import approval_decision_event_api as ae_api
from nex_ae_api.approval_decision_event_api import (
    ApprovalDecisionEventError,
    SqlAlchemyNslApprovalDecisionAdmission,
    register_approval_decision_event_routes,
)
from nex_ae_api.nsl_approval_events import NslApprovalEventError
from nex_eos import approval_decision_api as eos_api
from nex_eos.approval_transitions import EosApprovalTransitionError
from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    SERVICE_SPECS,
    build_service_app,
    issue_mock_service_token,
)
from nex_runtime.nsl_runtime_bundle import (
    NSL_RUNTIME_BUNDLE_SCHEMA_VERSION,
    NslRuntimeBundleError,
    _contained,
    _timestamp,
    load_nsl_runtime_bundle,
    verify_nsl_runtime_bundle,
)

TENANT = "VO00"
OUTBOX_ID = "6a14e4b3-5285-4e78-912d-39164ba62f66"
EVENT_ID = "9074f329-1813-44a0-976d-52119c03e498"
WORK_ITEM_ID = "579fbd47-e669-4fe3-bc59-247f461628ae"
DECISION_ID = "eaa2e238-d99d-40bc-8b32-978763a20f12"
INSTANCE_ID = "60a344ec-edf8-42ac-817b-7ad505151771"
REQUEST_ID = "approval-request-1"
EXECUTION_ID = "7dd31a19-c82d-49c2-a346-0cc728aa7a7f"


def _service_token(service_id: str, audience: str) -> str:
    return issue_mock_service_token(
        service_id=service_id,
        audience=audience,
        scopes=[DEFAULT_SERVICE_SCOPE],
    ).access_token


def _bundle_fixture(tmp_path: Path) -> tuple[Path, Path, Path, dict[str, object]]:
    wheel = tmp_path / "nsl-0.2.1-py3-none-any.whl"
    wheel.write_bytes(b"admitted-wheel")
    skill_root = tmp_path / "skills"
    skill_root.mkdir()
    skill = skill_root / "finance.ns"
    skill.write_text("skill FINANCE.VOUCHER.CREATE", encoding="utf-8")
    manifest: dict[str, object] = {
        "schema_version": NSL_RUNTIME_BUNDLE_SCHEMA_VERSION,
        "bundle_id": "nsl-product-bundle-1",
        "admitted_at": "2026-11-01T00:00:00Z",
        "wheel": {
            "filename": wheel.name,
            "sha256": sha256(wheel.read_bytes()).hexdigest(),
            "admission_lock": "locks/nsl-wheel.lock.json",
        },
        "skill": {
            "skill_id": "FINANCE.VOUCHER.CREATE",
            "skill_version": "1.0.0",
            "semantic_hash": "sha256:" + "1" * 64,
            "source_directory": "skills/finance",
            "files": {skill.name: sha256(skill.read_bytes()).hexdigest()},
        },
    }
    path = tmp_path / "bundle.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path, wheel, skill_root, manifest


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        (lambda value: value.update(unexpected="field"), "fields"),
        (lambda value: value.update(schema_version="wrong"), "schema version"),
        (lambda value: value.update(wheel=[]), "wheel must be an object"),
        (lambda value: value["skill"].update(files=[]), "skill.files"),
        (lambda value: value.update(bundle_id=" "), "bounded non-empty"),
        (lambda value: value["wheel"].update(filename="/tmp/wheel"), "relative"),
        (lambda value: value["wheel"].update(sha256="A" * 64), "lowercase"),
        (
            lambda value: value.update(admitted_at="2026-11-01T00:00:00"),
            "UTC RFC3339",
        ),
        (lambda value: value.update(admitted_at="not-a-timeZ"), "UTC RFC3339"),
    ),
)
def test_nsl_bundle_rejects_malformed_admission_fields(
    tmp_path: Path, mutation, message: str
) -> None:
    path, _wheel, _skill_root, manifest = _bundle_fixture(tmp_path)
    mutation(manifest)
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(NslRuntimeBundleError, match=message):
        load_nsl_runtime_bundle(path)


@pytest.mark.parametrize("payload", ("{", "[]"))
def test_nsl_bundle_rejects_unreadable_or_non_object_manifest(
    tmp_path: Path, payload: str
) -> None:
    path = tmp_path / "bundle.json"
    path.write_text(payload, encoding="utf-8")

    with pytest.raises(NslRuntimeBundleError):
        load_nsl_runtime_bundle(path)


def test_nsl_bundle_verification_fails_closed_for_artifact_drift(
    tmp_path: Path,
) -> None:
    path, wheel, skill_root, _manifest = _bundle_fixture(tmp_path)
    bundle = load_nsl_runtime_bundle(path)
    assert verify_nsl_runtime_bundle(
        bundle, wheel_path=wheel, skill_root=skill_root
    )["status"] == "PASS"

    with pytest.raises(NslRuntimeBundleError, match="filename"):
        verify_nsl_runtime_bundle(
            bundle,
            wheel_path=tmp_path / "renamed.whl",
            skill_root=skill_root,
        )

    wheel.write_bytes(b"drifted")
    with pytest.raises(NslRuntimeBundleError, match="digest"):
        verify_nsl_runtime_bundle(bundle, wheel_path=wheel, skill_root=skill_root)

    wheel.unlink()
    with pytest.raises(NslRuntimeBundleError, match="unavailable"):
        verify_nsl_runtime_bundle(bundle, wheel_path=wheel, skill_root=skill_root)

    with pytest.raises(NslRuntimeBundleError, match="escapes"):
        _contained(skill_root, "../outside.ns")


def test_nsl_bundle_rejects_non_utc_timestamp_offset() -> None:
    class OffsetTimestamp(str):
        def strip(self, _chars=None):
            return self

        def replace(self, _old, _new, _count=-1):
            return "2026-11-01T00:00:00+01:00"

    with pytest.raises(NslRuntimeBundleError, match="UTC RFC3339"):
        _timestamp(OffsetTimestamp("2026-11-01T00:00:00Z"), "admitted_at")


def _business_delivery() -> dict[str, object]:
    return {
        "schema_version": "wc_approval_delivery.v1",
        "outbox_id": OUTBOX_ID,
        "work_item": {
            "tenant_id": TENANT,
            "approval_work_item_id": WORK_ITEM_ID,
            "approval_domain": "BUSINESS_FORMAL",
            "resume_target_ref": (
                f"eos.approval-instance:{INSTANCE_ID}:stage:stage-1"
            ),
        },
        "decision": {
            "tenant_id": TENANT,
            "approval_work_item_id": WORK_ITEM_ID,
            "decision_id": DECISION_ID,
        },
        "event": {
            "tenant_id": TENANT,
            "event_id": EVENT_ID,
            "approval_work_item_id": WORK_ITEM_ID,
            "decision_id": DECISION_ID,
        },
    }


class _TransitionService:
    def __init__(self, error: EosApprovalTransitionError | None = None) -> None:
        self.error = error

    def advance_from_wc_decision(self, **_kwargs):
        if self.error is not None:
            raise self.error
        return {"instance": {"state": "APPROVED"}}


def _eos_client(service: object | None = None) -> TestClient:
    app = build_service_app(SERVICE_SPECS["nex-eos"])
    if service is not None:
        app.state.eos_approval_transition_service = service
    eos_api.register_approval_decision_routes(app)
    return TestClient(app)


def test_eos_approval_route_fails_closed_for_auth_configuration_and_transition() -> None:
    unauthenticated = _eos_client().post(
        "/internal/v1/approval-decision-events", json=_business_delivery()
    )
    assert unauthenticated.status_code == 401

    headers = {
        "Authorization": f"Bearer {_service_token('nex-ae-api', 'nex-eos')}"
    }
    unavailable = _eos_client().post(
        "/internal/v1/approval-decision-events",
        json=_business_delivery(),
        headers=headers,
    )
    assert unavailable.status_code == 503
    assert unavailable.json()["error_code"] == "EOS_APPROVAL_TRANSITION_UNAVAILABLE"

    invalid = _business_delivery()
    invalid["schema_version"] = "wrong"
    rejected = _eos_client(_TransitionService()).post(
        "/internal/v1/approval-decision-events", json=invalid, headers=headers
    )
    assert rejected.status_code == 400
    assert rejected.json()["error_code"] == "eos.approval_decision_invalid"

    transition_error = EosApprovalTransitionError(
        "eos.approval_conflict",
        "approval state changed",
        status_code=409,
        retryable=False,
    )
    conflict = _eos_client(_TransitionService(transition_error)).post(
        "/internal/v1/approval-decision-events",
        json=_business_delivery(),
        headers=headers,
    )
    assert conflict.status_code == 409
    assert conflict.json()["error_code"] == "eos.approval_conflict"


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        (lambda value: value.update(schema_version="wrong"), "schema"),
        (lambda value: value.update(outbox_id=""), "outbox_id"),
        (lambda value: value.update(work_item=[]), "must be an object"),
        (
            lambda value: value["work_item"].update(approval_domain="NSL_WRITE"),
            "BUSINESS_FORMAL",
        ),
        (lambda value: value["work_item"].update(tenant_id="OTHER"), "work-item"),
        (lambda value: value["decision"].update(tenant_id="OTHER"), "decision lineage"),
        (lambda value: value["decision"].update(decision_id="OTHER"), "event identity"),
        (
            lambda value: value["work_item"].update(resume_target_ref="invalid"),
            "resume target",
        ),
        (
            lambda value: value["work_item"].update(
                resume_target_ref="eos.approval-instance:not-a-uuid:stage:1"
            ),
            "instance identity",
        ),
    ),
)
def test_eos_approval_delivery_rejects_malformed_lineage(
    mutation, message: str
) -> None:
    delivery = _business_delivery()
    mutation(delivery)

    with pytest.raises(eos_api.ApprovalDecisionApiError, match=message):
        _outbox, work_item, _decision, _event = eos_api._delivery(delivery)
        eos_api._approval_instance_id(work_item)


def _nsl_delivery() -> dict[str, object]:
    delivery = _business_delivery()
    delivery["work_item"] = {
        **delivery["work_item"],
        "approval_domain": "NSL_WRITE",
        "approval_request_id": REQUEST_ID,
        "agent_execution_id": EXECUTION_ID,
        "executable_step_id": "step-1",
    }
    delivery["decision"] = {
        **delivery["decision"],
        "decision": "APPROVE",
        "decided_at": "2026-11-01T00:00:00Z",
    }
    delivery["event"] = {
        **delivery["event"],
        "correlation_id": "correlation-1",
    }
    return delivery


class _RequestStore:
    def __init__(self, value: object | None) -> None:
        self.value = value

    def load_request(self, **_kwargs):
        return self.value

    def get(self, **_kwargs):
        return self.value


class _WaitStore:
    def __init__(self, value: object | None) -> None:
        self.value = value

    def get(self, **_kwargs):
        return self.value


class _EvidenceStore:
    def create_or_get(self, evidence):
        assert evidence == {"evidence": "bound"}
        return {
            "nsl_execution_id": "nsl-execution-1",
            "business_operation_id": "business-operation-1",
            "decision": "APPROVE",
            "evidence_integrity": "sha256:" + "2" * 64,
        }


class _EventService:
    def __init__(self) -> None:
        self.event = None

    def ingest(self, event):
        self.event = event
        return {"inbox_state": "ACCEPTED", "resume_runtime_job_id": "job-1"}


def _admission(value: object | None) -> SqlAlchemyNslApprovalDecisionAdmission:
    admission = object.__new__(SqlAlchemyNslApprovalDecisionAdmission)
    admission._requests = _RequestStore(value)
    admission._waits = _WaitStore(value)
    admission._evidence = _EvidenceStore()
    admission._events = _EventService()
    return admission


def test_ae_nsl_admission_rejects_wrong_domain_and_incomplete_lineage() -> None:
    event_service = _EventService()
    constructed = SqlAlchemyNslApprovalDecisionAdmission(
        lambda: None, event_service=event_service
    )
    with pytest.raises(ApprovalDecisionEventError, match="NSL_WRITE"):
        constructed.ingest(_business_delivery())

    with pytest.raises(ApprovalDecisionEventError) as caught:
        _admission(None).ingest(_nsl_delivery())
    assert caught.value.error_code == "ae.approval_decision_lineage_missing"

    malformed = _nsl_delivery()
    malformed["outbox_id"] = ""
    with pytest.raises(ApprovalDecisionEventError, match="outbox_id"):
        ae_api._delivery(malformed)


def test_ae_nsl_admission_builds_bound_resume_event(monkeypatch) -> None:
    monkeypatch.setattr(
        ae_api,
        "build_platform_approval_evidence",
        lambda **_kwargs: {"evidence": "bound"},
    )
    admission = _admission({"persisted": True})

    result = admission.ingest(_nsl_delivery())

    assert result == {
        "schema_version": "ae_approval_decision_receipt.v1",
        "outbox_id": OUTBOX_ID,
        "event_id": EVENT_ID,
        "approval_domain": "NSL_WRITE",
        "disposition": "ACCEPTED",
        "resume_runtime_job_id": "job-1",
    }
    assert admission._events.event["approval_request_id"] == REQUEST_ID
    assert admission._events.event["correlation_id"] == "correlation-1"


class _RaisingAdmission:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def ingest(self, _payload):
        raise self.error


def _ae_client(admission: object | None) -> TestClient:
    app = build_service_app(SERVICE_SPECS["nex-ae-api"])
    register_approval_decision_event_routes(app, admission=admission)
    return TestClient(app)


def test_ae_approval_route_maps_unavailable_and_typed_failures() -> None:
    headers = {"Authorization": f"Bearer {_service_token('nex-wc', 'nex-ae-api')}"}

    unavailable = _ae_client(None).post(
        "/internal/v1/approval-decision-events",
        json=_nsl_delivery(),
        headers=headers,
    )
    assert unavailable.status_code == 503
    assert unavailable.json()["error_code"] == "AE_APPROVAL_DECISION_UNAVAILABLE"

    invalid = _ae_client(
        _RaisingAdmission(
            ApprovalDecisionEventError(
                "ae.approval_decision_invalid",
                "invalid delivery",
                status_code=422,
            )
        )
    ).post(
        "/internal/v1/approval-decision-events",
        json=_nsl_delivery(),
        headers=headers,
    )
    assert invalid.status_code == 422
    assert invalid.json()["error_code"] == "ae.approval_decision_invalid"

    conflict = _ae_client(
        _RaisingAdmission(
            NslApprovalEventError(
                "ae.approval_event_conflict",
                "approval event conflicts",
                status_code=409,
            )
        )
    ).post(
        "/internal/v1/approval-decision-events",
        json=_nsl_delivery(),
        headers=headers,
    )
    assert conflict.status_code == 409
    assert conflict.json()["error_code"] == "ae.approval_event_conflict"
