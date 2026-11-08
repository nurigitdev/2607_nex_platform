from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
from nex_ae_api.project_membership_batch import (
    OA_EMPLOYEE_BATCH_RESOLUTION_SCHEMA_VERSION,
    PROJECT_MEMBERSHIP_ADD_MANY,
    PROJECT_MEMBERSHIP_BATCH_SKILL_BINDING_SCHEMA_VERSION,
    HttpOaEmployeeBatchResolutionSource,
    ProjectMembershipBatchError,
    admit_project_membership_batch,
    batch_approval_display_summary,
    bind_project_membership_batch_skill,
    build_default_oa_employee_batch_resolution_source,
    require_project_membership_batch_approval_binding,
    validate_project_membership_batch_admission,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

TENANT = "tenant-s108"
REQUESTER = "subject-requester"
PROJECT_ID = "a1080000-0000-4000-8000-000000000001"
TRACE_ID = "1" * 32
ROOT = Path(__file__).resolve().parents[1]
WRITE_ADMISSION = (
    ROOT / "contracts/examples/common/nsl_project_write_artifact_admission.pass.json"
)


def _request(*, role: str | None = None, candidates: list[dict] | None = None) -> dict:
    value = {
        "tenant_id": TENANT,
        "requester_subject_id": REQUESTER,
        "project_id": PROJECT_ID,
        "candidates": candidates
        or [
            {"input_index": 0, "employee_id": "EMP-001", "expected_name": "김 하나"},
            {"input_index": 1, "employee_id": "EMP-002"},
        ],
    }
    if role is not None:
        value["member_role"] = role
    return value


def _resolved(index: int, employee: str, subject: str, revision: int = 1) -> dict:
    return {
        "input_index": index,
        "resolution_status": "RESOLVED",
        "normalized_employee_id": employee.casefold(),
        "subject_id": subject,
        "display_name": f"직원 {index}",
        "subject_revision": revision,
        "tenant_membership_revision": revision + 10,
    }


def _rejected(index: int, status: str, employee: str | None = None) -> dict:
    result: dict[str, Any] = {
        "input_index": index,
        "resolution_status": status,
    }
    if employee is not None:
        result["normalized_employee_id"] = employee.casefold()
    return result


def _resolution(results: list[dict], **overrides: Any) -> dict:
    payload = {
        "schema_version": OA_EMPLOYEE_BATCH_RESOLUTION_SCHEMA_VERSION,
        "tenant_id": TENANT,
        "results": results,
    }
    value = {
        "resolution_schema_version": OA_EMPLOYEE_BATCH_RESOLUTION_SCHEMA_VERSION,
        "service_id": "nex-oa",
        "tenant_id": TENANT,
        "requested_count": len(results),
        "resolved_count": sum(item["resolution_status"] == "RESOLVED" for item in results),
        "rejected_count": sum(item["resolution_status"] != "RESOLVED" for item in results),
        "results": results,
        "resolution_evidence_hash": semantic_sha256_hash_ref(payload),
        "request_id": "req-oa",
        "trace_id": TRACE_ID,
    }
    value.update(overrides)
    return value


@dataclass
class Source:
    response: Any
    received: dict | None = None

    def resolve_batch(self, payload, *, request_id, trace_id):
        self.received = {
            "payload": deepcopy(dict(payload)),
            "request_id": request_id,
            "trace_id": trace_id,
        }
        if isinstance(self.response, Exception):
            raise self.response
        return deepcopy(self.response)


def _admit(response: dict, request: dict | None = None) -> tuple[dict, Source]:
    source = Source(response)
    result = admit_project_membership_batch(
        request or _request(),
        source=source,
        request_id="req-s108",
        trace_id=TRACE_ID,
    )
    return result, source


def _write_admission() -> dict:
    return json.loads(WRITE_ADMISSION.read_text(encoding="utf-8"))


def test_mixed_batch_is_deduplicated_sorted_and_bound_to_one_approval() -> None:
    request = _request(
        role=" manager ",
        candidates=[
            {"input_index": 0, "employee_id": "EMP-003"},
            {"input_index": 1, "employee_id": "EMP-001"},
            {"input_index": 2, "employee_id": "EMP-009"},
            {"input_index": 3, "employee_id": "EMP-004"},
        ],
    )
    response = _resolution(
        [
            _resolved(0, "EMP-003", "subject-z", 3),
            _resolved(1, "EMP-001", "subject-a", 4),
            _rejected(2, "EMPLOYEE_NOT_FOUND", "EMP-009"),
            _resolved(3, "EMP-004", "subject-a", 4),
        ]
    )

    result, source = _admit(response, request)

    assert result["directive"] == "CONTINUE"
    assert result["operation_id"] == PROJECT_MEMBERSHIP_ADD_MANY
    assert result["member_role"] == "MANAGER"
    assert [item["subject_id"] for item in result["admitted_members"]] == [
        "subject-a",
        "subject-z",
    ]
    assert result["requested_count"] == 4
    assert result["admitted_count"] == 2
    assert result["rejected_count"] == 2
    assert [item["outcome_code"] for item in result["rejected_candidates"]] == [
        "EMPLOYEE_NOT_FOUND",
        "DUPLICATE_SUBJECT",
    ]
    assert result["governed_payload"] == {
        "tenant_id": TENANT,
        "requester_subject_id": REQUESTER,
        "project_id": PROJECT_ID,
        "target_subject_ids": ["subject-a", "subject-z"],
        "member_role": "MANAGER",
        "resolution_evidence_hash": response["resolution_evidence_hash"],
    }
    assert result["approval_projection"]["payload_hash"] == result["payload_hash"]
    assert source.received == {
        "payload": {"tenant_id": TENANT, "candidates": request["candidates"]},
        "request_id": "req-s108",
        "trace_id": TRACE_ID,
    }
    assert validate_project_membership_batch_admission(result) == result
    assert batch_approval_display_summary(result) == result["approval_projection"]
    approval = {
        "payload_hash": result["payload_hash"],
        "display_safe_summary": result["approval_projection"],
    }
    assert require_project_membership_batch_approval_binding(result, approval) == result[
        "payload_hash"
    ]


def test_default_member_role_and_canonical_order_make_reordering_semantically_stable() -> None:
    first, _ = _admit(
        _resolution(
            [
                _resolved(0, "EMP-002", "subject-b"),
                _resolved(1, "EMP-001", "subject-a"),
            ]
        )
    )
    second_request = _request(
        candidates=[
            {"input_index": 0, "employee_id": "EMP-001"},
            {"input_index": 1, "employee_id": "EMP-002"},
        ]
    )
    second, _ = _admit(
        _resolution(
            [
                _resolved(0, "EMP-001", "subject-a"),
                _resolved(1, "EMP-002", "subject-b"),
            ]
        ),
        second_request,
    )

    assert first["member_role"] == "MEMBER"
    assert first["governed_payload"]["target_subject_ids"] == ["subject-a", "subject-b"]
    assert second["governed_payload"]["target_subject_ids"] == ["subject-a", "subject-b"]
    assert first["payload_hash"] != second["payload_hash"]
    assert first["resolution_evidence_hash"] != second["resolution_evidence_hash"]


def test_all_rejected_stops_before_approval_or_write() -> None:
    result, _ = _admit(
        _resolution(
            [
                _rejected(0, "EMPLOYEE_NOT_FOUND", "EMP-001"),
                _rejected(1, "SUBJECT_INACTIVE", "EMP-002"),
            ]
        )
    )

    assert result["directive"] == "REJECTED"
    assert result["admitted_count"] == 0
    assert result["governed_payload"] is None
    assert result["payload_hash"] is None
    assert result["approval_projection"] is None
    assert validate_project_membership_batch_admission(result) == result
    with pytest.raises(ProjectMembershipBatchError, match="cannot enter approval"):
        batch_approval_display_summary(result)
    with pytest.raises(ProjectMembershipBatchError, match="cannot bind approval"):
        require_project_membership_batch_approval_binding(result, {})


@pytest.mark.parametrize(
    "mutate",
    (
        lambda value: value.update(extra=True),
        lambda value: value.pop("tenant_id"),
        lambda value: value.update(tenant_id=" padded "),
        lambda value: value.update(requester_subject_id=""),
        lambda value: value.update(project_id=1),
        lambda value: value.update(member_role="AUDITOR"),
        lambda value: value.update(candidates=[]),
        lambda value: value.update(candidates=[{}] * 51),
        lambda value: value.update(candidates="EMP-001"),
        lambda value: value.update(candidates=["EMP-001"]),
        lambda value: value.update(candidates=[{"input_index": 0, "employee_id": "E", "x": 1}]),
        lambda value: value.update(candidates=[{"input_index": True, "employee_id": "E"}]),
        lambda value: value.update(candidates=[{"input_index": -1, "employee_id": "E"}]),
        lambda value: value.update(
            candidates=[
                {"input_index": 0, "employee_id": "E1"},
                {"input_index": 0, "employee_id": "E2"},
            ]
        ),
        lambda value: value.update(
            candidates=[{"input_index": 0, "employee_id": "E", "expected_name": 1}]
        ),
    ),
)
def test_structural_intake_failures_stop_before_oa(mutate) -> None:
    request = _request()
    mutate(request)
    source = Source(_resolution([]))

    with pytest.raises(ProjectMembershipBatchError) as error:
        admit_project_membership_batch(
            request,
            source=source,
            request_id="req",
            trace_id=TRACE_ID,
        )

    assert error.value.status_code == 400
    assert error.value.retryable is False
    assert source.received is None


def test_invalid_trace_and_request_id_stop_before_oa() -> None:
    source = Source(_resolution([]))
    with pytest.raises(ProjectMembershipBatchError, match="trace_id"):
        admit_project_membership_batch(
            _request(), source=source, request_id="req", trace_id="BAD"
        )
    with pytest.raises(ProjectMembershipBatchError, match="request_id"):
        admit_project_membership_batch(
            _request(), source=source, request_id=" ", trace_id=TRACE_ID
        )
    assert source.received is None


@pytest.mark.parametrize(
    "mutate",
    (
        lambda value: value.update(extra=True),
        lambda value: value.update(resolution_schema_version="v0"),
        lambda value: value.update(service_id="nex-ae-api"),
        lambda value: value.update(tenant_id="other"),
        lambda value: value.update(results={}),
        lambda value: value.update(results=value["results"][:1]),
        lambda value: value["results"].__setitem__(0, []),
        lambda value: value["results"][0].update(input_index=9),
        lambda value: value["results"][0].update(input_index=True),
        lambda value: value["results"][0].update(resolution_status="UNKNOWN"),
        lambda value: value["results"][0].update(subject_revision=0),
        lambda value: value["results"][0].update(extra=True),
        lambda value: value["results"][1].update(subject_id="leak"),
        lambda value: value.update(requested_count=99),
        lambda value: value.update(resolved_count=0),
        lambda value: value.update(rejected_count=0),
        lambda value: value.update(resolution_evidence_hash="sha256:" + "0" * 64),
    ),
)
def test_malformed_or_tampered_oa_response_is_retryable_failure(mutate) -> None:
    response = _resolution(
        [
            _resolved(0, "EMP-001", "subject-a"),
            _rejected(1, "EMPLOYEE_NOT_FOUND", "EMP-002"),
        ]
    )
    mutate(response)

    with pytest.raises(ProjectMembershipBatchError) as error:
        _admit(response)

    assert error.value.status_code == 503
    assert error.value.retryable is True


def test_invalid_employee_id_without_normalized_alias_is_preserved_safely() -> None:
    result, _ = _admit(
        _resolution(
            [
                _rejected(0, "INVALID_EMPLOYEE_ID"),
                _resolved(1, "EMP-002", "subject-b"),
            ]
        )
    )
    assert result["rejected_candidates"] == [
        {"input_index": 0, "outcome_code": "INVALID_EMPLOYEE_ID"}
    ]
    assert validate_project_membership_batch_admission(result) == result


def test_typed_source_failure_propagates_and_unknown_failure_is_wrapped() -> None:
    typed = ProjectMembershipBatchError(504, "oa.timeout", "safe", True)
    with pytest.raises(ProjectMembershipBatchError) as typed_error:
        _admit(typed)  # type: ignore[arg-type]
    assert typed_error.value is typed

    with pytest.raises(ProjectMembershipBatchError) as wrapped:
        _admit(RuntimeError("private"))  # type: ignore[arg-type]
    assert wrapped.value.status_code == 503
    assert wrapped.value.retryable is True
    assert "private" not in wrapped.value.detail


def test_approval_binding_rejects_mapping_and_object_tamper() -> None:
    result, _ = _admit(
        _resolution(
            [
                _resolved(0, "EMP-001", "subject-a"),
                _resolved(1, "EMP-002", "subject-b"),
            ]
        )
    )

    class Request:
        def to_data(self):
            return {
                "payload_hash": result["payload_hash"],
                "display_safe_summary": result["approval_projection"],
            }

    assert require_project_membership_batch_approval_binding(result, Request()) == result[
        "payload_hash"
    ]
    for approval in (
        {"payload_hash": "sha256:" + "0" * 64, "display_safe_summary": result["approval_projection"]},
        {"payload_hash": result["payload_hash"], "display_safe_summary": {}},
        [],
    ):
        with pytest.raises(ProjectMembershipBatchError):
            require_project_membership_batch_approval_binding(result, approval)


def test_batch_skill_binding_preserves_approved_payload_and_exact_artifact() -> None:
    result, _ = _admit(
        _resolution(
            [
                _resolved(0, "EMP-001", "subject-a"),
                _resolved(1, "EMP-002", "subject-b"),
            ]
        )
    )
    write_admission = _write_admission()
    approval = {
        "payload_hash": result["payload_hash"],
        "display_safe_summary": result["approval_projection"],
    }

    binding = bind_project_membership_batch_skill(
        result,
        approval_request=approval,
        write_admission=write_admission,
    )

    artifact = next(
        item
        for item in write_admission["skills"]
        if item["skill_id"] == PROJECT_MEMBERSHIP_ADD_MANY
    )
    assert binding["schema_version"] == (
        PROJECT_MEMBERSHIP_BATCH_SKILL_BINDING_SCHEMA_VERSION
    )
    assert binding["payload_hash"] == result["payload_hash"]
    assert binding["arguments"] == result["governed_payload"]
    assert binding["approval_projection"] == result["approval_projection"]
    assert binding["capability_ref"] == {
        "capability_id": PROJECT_MEMBERSHIP_ADD_MANY,
        "skill_id": PROJECT_MEMBERSHIP_ADD_MANY,
        "skill_version": "1.0.0",
        "skill_semantic_hash": artifact["semantic_hash"],
        "source_sha256": artifact["source_sha256"],
        "artifact_source_revision": write_admission["artifact_source_revision"],
    }
    assert binding["model_authority"] is False
    assert binding["binding_hash"] == semantic_sha256_hash_ref(
        {key: item for key, item in binding.items() if key != "binding_hash"}
    )


@pytest.mark.parametrize(
    "mutate",
    (
        lambda value: value.update(schema_version="bad"),
        lambda value: value.update(status="FAIL"),
        lambda value: value.update(skills="bad"),
        lambda value: value.update(artifact_source_revision="bad"),
        lambda value: value.update(artifact_manifest_sha256="bad"),
        lambda value: value["skills"].__setitem__(
            next(
                index
                for index, item in enumerate(value["skills"])
                if item["skill_id"] == PROJECT_MEMBERSHIP_ADD_MANY
            ),
            {"skill_id": "OTHER"},
        ),
        lambda value: value["skills"].append(
            deepcopy(
                next(
                    item
                    for item in value["skills"]
                    if item["skill_id"] == PROJECT_MEMBERSHIP_ADD_MANY
                )
            )
        ),
        lambda value: next(
            item
            for item in value["skills"]
            if item["skill_id"] == PROJECT_MEMBERSHIP_ADD_MANY
        ).update(skill_version="2.0.0"),
        lambda value: next(
            item
            for item in value["skills"]
            if item["skill_id"] == PROJECT_MEMBERSHIP_ADD_MANY
        ).update(operation_kind="UPDATE"),
        lambda value: next(
            item
            for item in value["skills"]
            if item["skill_id"] == PROJECT_MEMBERSHIP_ADD_MANY
        ).update(required_scope="project:read"),
        lambda value: next(
            item
            for item in value["skills"]
            if item["skill_id"] == PROJECT_MEMBERSHIP_ADD_MANY
        ).update(verification_tool_id="PROJECT.PROJECT.GET"),
        lambda value: next(
            item
            for item in value["skills"]
            if item["skill_id"] == PROJECT_MEMBERSHIP_ADD_MANY
        ).update(semantic_hash="bad"),
        lambda value: next(
            item
            for item in value["skills"]
            if item["skill_id"] == PROJECT_MEMBERSHIP_ADD_MANY
        ).update(source_sha256="bad"),
    ),
)
def test_batch_skill_binding_rejects_unadmitted_or_tampered_artifact(mutate) -> None:
    result, _ = _admit(
        _resolution(
            [
                _resolved(0, "EMP-001", "subject-a"),
                _resolved(1, "EMP-002", "subject-b"),
            ]
        )
    )
    approval = {
        "payload_hash": result["payload_hash"],
        "display_safe_summary": result["approval_projection"],
    }
    write_admission = _write_admission()
    mutate(write_admission)

    with pytest.raises(ProjectMembershipBatchError):
        bind_project_membership_batch_skill(
            result,
            approval_request=approval,
            write_admission=write_admission,
        )


@pytest.mark.parametrize(
    "mutate",
    (
        lambda value: value.update(schema_version="bad"),
        lambda value: value.update(admission_hash="bad"),
        lambda value: value.update(operation_id="PROJECT.MEMBERSHIP.ADD"),
        lambda value: value.update(directive="WAIT"),
        lambda value: value.update(admitted_members={}),
        lambda value: value.update(rejected_candidates={}),
        lambda value: value.update(admitted_count=99),
        lambda value: value["admitted_members"].reverse(),
        lambda value: value.update(governed_payload=None),
        lambda value: value.update(payload_hash="sha256:" + "0" * 64),
        lambda value: value["approval_projection"].update(payload_hash="sha256:" + "0" * 64),
    ),
)
def test_admission_validation_rejects_tamper_even_with_recomputed_hash(mutate) -> None:
    result, _ = _admit(
        _resolution(
            [
                _resolved(0, "EMP-001", "subject-a"),
                _resolved(1, "EMP-002", "subject-b"),
            ]
        )
    )
    mutate(result)
    if result.get("admission_hash") != "bad":
        result["admission_hash"] = semantic_sha256_hash_ref(
            {key: item for key, item in result.items() if key != "admission_hash"}
        )
    with pytest.raises(ProjectMembershipBatchError):
        validate_project_membership_batch_admission(result)


def test_admission_validation_covers_integrity_and_rejected_write_authority() -> None:
    admitted, _ = _admit(
        _resolution(
            [
                _resolved(0, "EMP-001", "subject-a"),
                _resolved(1, "EMP-002", "subject-b"),
            ]
        )
    )
    admitted["member_role"] = "VIEWER"
    with pytest.raises(ProjectMembershipBatchError, match="integrity"):
        validate_project_membership_batch_admission(admitted)
    with pytest.raises(ProjectMembershipBatchError, match="must be an object"):
        validate_project_membership_batch_admission([])  # type: ignore[arg-type]

    rejected, _ = _admit(
        _resolution(
            [
                _rejected(0, "EMPLOYEE_NOT_FOUND", "EMP-001"),
                _rejected(1, "SUBJECT_INACTIVE", "EMP-002"),
            ]
        )
    )
    rejected["governed_payload"] = {}
    rejected["admission_hash"] = semantic_sha256_hash_ref(
        {key: item for key, item in rejected.items() if key != "admission_hash"}
    )
    with pytest.raises(ProjectMembershipBatchError, match="write authority"):
        validate_project_membership_batch_admission(rejected)


@pytest.mark.parametrize(
    "mutate",
    (
        lambda value: value.update(member_role="AUDITOR"),
        lambda value: value["admitted_members"].__setitem__(0, {}),
        lambda value: value["admitted_members"][0].update(subject_revision=0),
        lambda value: value["admitted_members"][1].update(subject_id="subject-a"),
        lambda value: value["rejected_candidates"][0].update(extra=True),
        lambda value: value["rejected_candidates"][0].update(input_index=True),
        lambda value: value["rejected_candidates"][0].update(outcome_code="UNKNOWN"),
        lambda value: value.update(directive="REJECTED"),
        lambda value: value["governed_payload"].update(project_id="other-project"),
        lambda value: value["approval_projection"].update(target_count=99),
    ),
)
def test_semantic_admission_validation_matrix(mutate) -> None:
    result, _ = _admit(
        _resolution(
            [
                _resolved(0, "EMP-001", "subject-a"),
                _resolved(1, "EMP-002", "subject-b"),
                _rejected(2, "EMPLOYEE_NOT_FOUND", "EMP-003"),
            ]
        ),
        _request(
            candidates=[
                {"input_index": 0, "employee_id": "EMP-001"},
                {"input_index": 1, "employee_id": "EMP-002"},
                {"input_index": 2, "employee_id": "EMP-003"},
            ]
        ),
    )
    mutate(result)
    result["admission_hash"] = semantic_sha256_hash_ref(
        {key: item for key, item in result.items() if key != "admission_hash"}
    )
    with pytest.raises(ProjectMembershipBatchError):
        validate_project_membership_batch_admission(result)


def test_approval_object_must_return_mapping() -> None:
    result, _ = _admit(
        _resolution(
            [
                _resolved(0, "EMP-001", "subject-a"),
                _resolved(1, "EMP-002", "subject-b"),
            ]
        )
    )

    class BadRequest:
        def to_data(self):
            return []

    with pytest.raises(ProjectMembershipBatchError, match="ApprovalRequest is invalid"):
        require_project_membership_batch_approval_binding(result, BadRequest())


def test_http_oa_source_sends_protected_request() -> None:
    captured = {}
    response_payload = _resolution(
        [_resolved(0, "EMP-001", "subject-a"), _resolved(1, "EMP-002", "subject-b")]
    )

    def requester(method, url, **kwargs):
        captured.update(method=method, url=url, **kwargs)
        return httpx.Response(200, json=response_payload)

    source = HttpOaEmployeeBatchResolutionSource(
        base_url="http://oa.local/",
        service_token="signed-token",
        timeout_seconds=21.0,
        requester=requester,
    )
    body = source.resolve_batch(
        {"tenant_id": TENANT, "candidates": _request()["candidates"]},
        request_id="req-http",
        trace_id=TRACE_ID,
    )

    assert body == response_payload
    assert captured["method"] == "POST"
    assert captured["url"].endswith("/internal/v1/identity/employees:resolve-batch")
    assert captured["headers"]["Authorization"] == "Bearer signed-token"
    assert captured["headers"]["X-NeX-Tenant-Id"] == TENANT
    assert captured["timeout"] == 21.0


@pytest.mark.parametrize(
    ("failure", "status", "code"),
    (
        (httpx.TimeoutException("late"), 504, "ae.oa_employee_batch_timeout"),
        (httpx.ConnectError("down"), 503, "ae.oa_employee_batch_unavailable"),
    ),
)
def test_http_oa_source_maps_transport_failures(failure, status, code) -> None:
    def requester(*_args, **_kwargs):
        raise failure

    source = HttpOaEmployeeBatchResolutionSource(
        service_token="token", requester=requester
    )
    with pytest.raises(ProjectMembershipBatchError) as error:
        source.resolve_batch({}, request_id="req", trace_id=TRACE_ID)
    assert error.value.status_code == status
    assert error.value.error_code == code
    assert error.value.retryable is True


@pytest.mark.parametrize(
    ("response", "retryable"),
    (
        (httpx.Response(200, text="not-json"), True),
        (httpx.Response(200, json=[]), True),
        (httpx.Response(400, json={"detail": "private"}), False),
        (httpx.Response(503, json={"detail": "private"}), True),
    ),
)
def test_http_oa_source_rejects_invalid_or_error_response(response, retryable) -> None:
    source = HttpOaEmployeeBatchResolutionSource(
        service_token="token", requester=lambda *_args, **_kwargs: response
    )
    with pytest.raises(ProjectMembershipBatchError) as error:
        source.resolve_batch({}, request_id="req", trace_id=TRACE_ID)
    assert error.value.retryable is retryable
    assert "private" not in error.value.detail


def test_default_http_source_uses_environment_and_validates_timeout() -> None:
    source = build_default_oa_employee_batch_resolution_source(
        {
            "NEX_OA_BASE_URL": "https://oa.example",
            "NEX_AE_TO_OA_SERVICE_TOKEN": "token",
            "NEX_AE_OA_EMPLOYEE_BATCH_TIMEOUT_SECONDS": "22.5",
        }
    )
    assert source.base_url == "https://oa.example"
    assert source.service_token == "token"
    assert source.timeout_seconds == 22.5
    assert build_default_oa_employee_batch_resolution_source({}).timeout_seconds == 15.0
    for value in ("bad", "0", "-1"):
        with pytest.raises(ValueError):
            build_default_oa_employee_batch_resolution_source(
                {"NEX_AE_OA_EMPLOYEE_BATCH_TIMEOUT_SECONDS": value}
            )


def test_error_string_is_safe_detail() -> None:
    assert str(ProjectMembershipBatchError(400, "code", "safe")) == "safe"
