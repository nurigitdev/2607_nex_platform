from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

import pytest
from nex_ae_api.project_membership_batch import (
    OA_EMPLOYEE_BATCH_RESOLUTION_SCHEMA_VERSION,
    PROJECT_MEMBERSHIP_ADD_MANY,
    ProjectMembershipBatchError,
)
from nex_ae_api.project_membership_batch_orchestration import (
    PROJECT_MEMBERSHIP_BATCH_ORCHESTRATION_SCHEMA_VERSION,
    PROJECT_MEMBERSHIP_BATCH_RESULT_SCHEMA_VERSION,
    activate_project_membership_batch_work_intent,
    build_project_membership_batch_result_projection,
    orchestrate_project_membership_batch_candidate,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

TENANT = "tenant-s111"
REQUESTER = "subject-chairman"
PROJECT_ID = "b1110000-0000-4000-8000-000000000001"
TRACE_ID = "b" * 32


@dataclass
class Source:
    response: dict
    calls: int = 0
    request: dict | None = None

    def resolve_batch(self, payload, *, request_id, trace_id):
        self.calls += 1
        self.request = deepcopy(dict(payload))
        return deepcopy(self.response)


def _candidate(**overrides: Any) -> dict:
    value = {
        "schema_version": "p65.intent_candidate.v1",
        "intent_label": PROJECT_MEMBERSHIP_ADD_MANY,
        "suggested_execution_mode": "GENERAL_ANSWER",
        "entity_selectors": [
            {
                "selector_id": "E1",
                "selector_type": "QUERY_TERM",
                "value": "NVT-DEMO",
                "confidence": 0.99,
            }
        ],
        "parameter_candidates": [
            {"name": "employee_id_2", "value": "EMP-0002", "confidence": 0.98},
            {"name": "employee_name_2", "value": "김 둘", "confidence": 0.95},
            {"name": "employee_id_1", "value": "EMP-0001", "confidence": 0.98},
            {"name": "member_role", "value": "manager", "confidence": 0.97},
        ],
        "clarification": {"required": False, "reasons": [], "questions": []},
        "confidence": 0.98,
    }
    value.update(overrides)
    return value


def _projects(**overrides: Any) -> list[dict]:
    project = {
        "tenant_id": TENANT,
        "project_id": PROJECT_ID,
        "project_code": "NVT-DEMO",
        "name": "NVT 시연 프로젝트",
        "status": "ACTIVE",
    }
    project.update(overrides)
    return [
        project,
        {
            **project,
            "tenant_id": "other-tenant",
            "project_id": "b1110000-0000-4000-8000-000000000002",
        },
    ]


def _resolution() -> dict:
    items = [
        {
            "input_index": 0,
            "resolution_status": "RESOLVED",
            "normalized_employee_id": "emp-0001",
            "subject_id": "subject-a",
            "display_name": "김 하나",
            "subject_revision": 2,
            "tenant_membership_revision": 3,
        },
        {
            "input_index": 1,
            "resolution_status": "NAME_MISMATCH",
            "normalized_employee_id": "emp-0002",
        },
    ]
    evidence = {
        "schema_version": OA_EMPLOYEE_BATCH_RESOLUTION_SCHEMA_VERSION,
        "tenant_id": TENANT,
        "results": items,
    }
    return {
        "resolution_schema_version": OA_EMPLOYEE_BATCH_RESOLUTION_SCHEMA_VERSION,
        "service_id": "nex-oa",
        "tenant_id": TENANT,
        "requested_count": 2,
        "resolved_count": 1,
        "rejected_count": 1,
        "results": items,
        "resolution_evidence_hash": semantic_sha256_hash_ref(evidence),
        "request_id": "req-oa-s111",
        "trace_id": TRACE_ID,
    }


def _orchestrate(**overrides: Any) -> tuple[dict, Source]:
    source = Source(_resolution())
    values = {
        "candidate": _candidate(),
        "tenant_id": TENANT,
        "requester_subject_id": REQUESTER,
        "projects": _projects(),
        "source": source,
        "request_id": "req-s111",
        "trace_id": TRACE_ID,
    }
    values.update(overrides)
    return orchestrate_project_membership_batch_candidate(**values), source


def _eos_result(admission: dict, *, outcome: str = "ADDED") -> dict:
    rejected_count = int(outcome not in {"ADDED", "REACTIVATED", "ALREADY_ACTIVE"})
    return {
        "created": True,
        "tenant_id": TENANT,
        "business_operation_id": "b1110000-0000-4000-8000-000000000010",
        "idempotency_key": "s111-idempotency",
        "operation": PROJECT_MEMBERSHIP_ADD_MANY,
        "payload_hash": admission["payload_hash"],
        "commit_state": "COMMITTED",
        "result": {
            "business_result_ref": "eos.project-membership-batch:s111",
            "operation_status": "APPLIED" if not rejected_count else "REJECTED",
            "requested_count": 1,
            "resolved_count": 1,
            "added_count": int(outcome == "ADDED"),
            "reactivated_count": int(outcome == "REACTIVATED"),
            "unchanged_count": int(outcome == "ALREADY_ACTIVE"),
            "rejected_count": rejected_count,
            "project_id": PROJECT_ID,
            "member_role": admission["member_role"],
            "resolution_evidence_hash": admission["resolution_evidence_hash"],
            "item_results": [
                {
                    "subject_id": admission["admitted_members"][0]["subject_id"],
                    "outcome": outcome,
                }
            ],
            "authorization_revision_hash": "a" * 64,
            "requested_operation": PROJECT_MEMBERSHIP_ADD_MANY,
            "canonical_operation": PROJECT_MEMBERSHIP_ADD_MANY,
        },
        "outbox": {},
    }


def test_natural_language_candidate_becomes_one_authoritative_batch() -> None:
    result, source = _orchestrate()

    assert result["schema_version"] == (
        PROJECT_MEMBERSHIP_BATCH_ORCHESTRATION_SCHEMA_VERSION
    )
    assert result["directive"] == "CONTINUE"
    assert result["model_authority"] is False
    assert result["project_ref"] == {"type": "eos.project", "id": PROJECT_ID}
    assert result["approval_projection"]["target_subject_ids"] == ["subject-a"]
    assert source.calls == 1
    assert source.request == {
        "tenant_id": TENANT,
        "candidates": [
            {"input_index": 0, "employee_id": "EMP-0001"},
            {
                "input_index": 1,
                "employee_id": "EMP-0002",
                "expected_name": "김 둘",
            },
        ],
    }
    assert result["orchestration_hash"] == semantic_sha256_hash_ref(
        {key: item for key, item in result.items() if key != "orchestration_hash"}
    )


def test_batch_activation_binds_only_the_admitted_capability() -> None:
    orchestration, _ = _orchestrate()
    work_intent = {"schema_version": "1.1", "constraints": []}
    work_intent["intent_hash"] = semantic_sha256_hash_ref(work_intent)

    activated = activate_project_membership_batch_work_intent(
        work_intent, orchestration=orchestration
    )

    assert activated["intent_label"] == PROJECT_MEMBERSHIP_ADD_MANY
    assert activated["required_capability_hints"] == [PROJECT_MEMBERSHIP_ADD_MANY]
    assert activated["clarification"]["status"] == "NOT_REQUIRED"
    assert activated["intent_hash"] == semantic_sha256_hash_ref(
        {key: item for key, item in activated.items() if key != "intent_hash"}
    )
    assert "subject-a" not in str(activated)


@pytest.mark.parametrize(
    ("candidate", "projects", "failure_code", "directive"),
    (
        (
            _candidate(
                clarification={
                    "required": True,
                    "reasons": ["ambiguous"],
                    "questions": ["확인해 주세요."],
                }
            ),
            _projects(),
            "MODEL_CLARIFICATION_REQUIRED",
            "CLARIFICATION_REQUIRED",
        ),
        (_candidate(entity_selectors=[]), _projects(), "PROJECT_CANDIDATE_NOT_FOUND", "CLARIFICATION_REQUIRED"),
        (_candidate(), _projects(status="INACTIVE"), "PROJECT_INACTIVE", "BLOCKED"),
        (
            _candidate(
                entity_selectors=[
                    {
                        "selector_id": "E1",
                        "selector_type": "QUERY_TERM",
                        "value": "NVT 시연 프로젝트",
                        "confidence": 0.99,
                    }
                ]
            ),
            _projects(),
            "PROJECT_CONFIRMATION_REQUIRED",
            "CLARIFICATION_REQUIRED",
        ),
    ),
)
def test_clarification_and_inactive_project_stop_before_oa(
    candidate, projects, failure_code, directive
) -> None:
    result, source = _orchestrate(candidate=candidate, projects=projects)
    assert result["failure_code"] == failure_code
    assert result["directive"] == directive
    assert result["admission"] is None
    assert source.calls == 0


@pytest.mark.parametrize(
    "parameters",
    (
        [{"name": "employee_name_1", "value": "이름", "confidence": 0.9}],
        [{"name": "employee_id_1", "value": " ", "confidence": 0.9}],
        [{"name": "employee_id_1", "value": "E1", "confidence": 0.9}, {"name": "member_role", "value": "AUDITOR", "confidence": 0.9}],
        [{"name": "members", "value": "E1,E2", "confidence": 0.9}],
    ),
)
def test_malformed_batch_parameters_fail_before_oa(parameters) -> None:
    with pytest.raises(ProjectMembershipBatchError):
        _orchestrate(candidate=_candidate(parameter_candidates=parameters))


def test_wrong_operation_is_not_routed_to_batch_orchestration() -> None:
    with pytest.raises(ProjectMembershipBatchError, match="does not select"):
        _orchestrate(candidate=_candidate(intent_label="PROJECT.MEMBERSHIP.ADD"))


def test_result_projection_merges_pre_admission_and_commit_outcomes() -> None:
    orchestration, _ = _orchestrate()
    admission = orchestration["admission"]
    projection = build_project_membership_batch_result_projection(
        admission, _eos_result(admission)
    )

    assert projection["schema_version"] == PROJECT_MEMBERSHIP_BATCH_RESULT_SCHEMA_VERSION
    assert projection["overall_status"] == "PARTIALLY_APPLIED"
    assert projection["summary"] == {
        "requested_count": 2,
        "admitted_count": 1,
        "applied_count": 1,
        "pre_admission_rejected_count": 1,
        "commit_rejected_count": 0,
        "total_rejected_count": 1,
    }
    assert [item["stage"] for item in projection["items"]] == [
        "OA_RESOLUTION",
        "EOS_COMMIT",
    ]
    assert projection["metadata"] == {
        "model_authority": False,
        "raw_prompt_included": False,
        "credentials_included": False,
        "provider_configuration_included": False,
    }
    assert projection["result_hash"] == semantic_sha256_hash_ref(
        {key: item for key, item in projection.items() if key != "result_hash"}
    )

    rejected = build_project_membership_batch_result_projection(
        admission, _eos_result(admission, outcome="SUBJECT_INACTIVE")
    )
    assert rejected["overall_status"] == "REJECTED"
    assert rejected["summary"]["applied_count"] == 0


def test_fully_applied_result_preserves_eos_terminal_status() -> None:
    resolution = _resolution()
    resolution["results"] = [resolution["results"][0]]
    resolution["requested_count"] = 1
    resolution["rejected_count"] = 0
    evidence = {
        "schema_version": OA_EMPLOYEE_BATCH_RESOLUTION_SCHEMA_VERSION,
        "tenant_id": TENANT,
        "results": resolution["results"],
    }
    resolution["resolution_evidence_hash"] = semantic_sha256_hash_ref(evidence)
    candidate = _candidate(
        parameter_candidates=[
            {"name": "employee_id", "value": "EMP-0001", "confidence": 0.98}
        ]
    )
    orchestration, _ = _orchestrate(
        candidate=candidate,
        source=Source(resolution),
    )
    admission = orchestration["admission"]

    projection = build_project_membership_batch_result_projection(
        admission, _eos_result(admission)
    )

    assert projection["overall_status"] == "APPLIED"
    assert projection["summary"]["total_rejected_count"] == 0


@pytest.mark.parametrize(
    "mutate",
    (
        lambda value: value.update(payload_hash="sha256:" + "0" * 64),
        lambda value: value.update(commit_state="UNKNOWN"),
        lambda value: value["result"].update(project_id="other"),
        lambda value: value["result"].update(requested_count=2),
        lambda value: value["result"]["item_results"][0].update(subject_id="other"),
        lambda value: value["result"]["item_results"][0].update(outcome="UNKNOWN"),
    ),
)
def test_result_projection_fails_closed_on_eos_drift(mutate) -> None:
    orchestration, _ = _orchestrate()
    admission = orchestration["admission"]
    response = _eos_result(admission)
    mutate(response)
    with pytest.raises(ProjectMembershipBatchError):
        build_project_membership_batch_result_projection(admission, response)


def test_activation_rejects_tamper_and_stopped_orchestration() -> None:
    work_intent = {"schema_version": "1.1", "constraints": []}
    work_intent["intent_hash"] = semantic_sha256_hash_ref(work_intent)
    admitted, _ = _orchestrate()
    admitted["candidate_hash"] = "sha256:" + "0" * 64
    with pytest.raises(ProjectMembershipBatchError, match="integrity"):
        activate_project_membership_batch_work_intent(
            work_intent, orchestration=admitted
        )

    stopped, _ = _orchestrate(candidate=_candidate(entity_selectors=[]))
    with pytest.raises(ProjectMembershipBatchError, match="cannot activate"):
        activate_project_membership_batch_work_intent(
            work_intent, orchestration=stopped
        )

    intact, _ = _orchestrate()
    bad_intent = deepcopy(work_intent)
    bad_intent["constraints"] = [{}]
    with pytest.raises(ProjectMembershipBatchError, match="intact WorkIntent"):
        activate_project_membership_batch_work_intent(
            bad_intent, orchestration=intact
        )

    with pytest.raises(ProjectMembershipBatchError, match="orchestration is invalid"):
        activate_project_membership_batch_work_intent(
            work_intent, orchestration=[]  # type: ignore[arg-type]
        )


def test_result_projection_rejects_non_executable_and_malformed_shapes() -> None:
    rejected_response = _resolution()
    rejected_response["results"] = [
        {
            "input_index": 0,
            "resolution_status": "EMPLOYEE_NOT_FOUND",
            "normalized_employee_id": "emp-0001",
        },
        rejected_response["results"][1],
    ]
    rejected_response["resolved_count"] = 0
    rejected_response["rejected_count"] = 2
    evidence = {
        "schema_version": OA_EMPLOYEE_BATCH_RESOLUTION_SCHEMA_VERSION,
        "tenant_id": TENANT,
        "results": rejected_response["results"],
    }
    rejected_response["resolution_evidence_hash"] = semantic_sha256_hash_ref(evidence)
    rejected, _ = _orchestrate(source=Source(rejected_response))
    with pytest.raises(ProjectMembershipBatchError, match="has no EOS result"):
        build_project_membership_batch_result_projection(rejected["admission"], {})

    admitted, _ = _orchestrate()
    admission = admitted["admission"]
    with pytest.raises(ProjectMembershipBatchError, match="result is invalid"):
        build_project_membership_batch_result_projection(
            admission, []  # type: ignore[arg-type]
        )
    malformed = _eos_result(admission)
    malformed["result"]["item_results"] = {}
    with pytest.raises(ProjectMembershipBatchError, match="item results are invalid"):
        build_project_membership_batch_result_projection(admission, malformed)


def test_duplicate_exact_project_codes_require_clarification() -> None:
    projects = _projects()
    projects.append(
        {
            **projects[0],
            "project_id": "b1110000-0000-4000-8000-000000000003",
        }
    )
    result, source = _orchestrate(projects=projects)
    assert result["failure_code"] == "PROJECT_CANDIDATE_AMBIGUOUS"
    assert source.calls == 0
