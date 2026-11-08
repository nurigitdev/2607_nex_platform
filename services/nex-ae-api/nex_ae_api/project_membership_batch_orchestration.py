from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any

from nex_runtime.semantic_hashes import canonical_json, semantic_sha256_hash_ref

from nex_ae_api.intent_candidate_generation import parse_intent_candidate
from nex_ae_api.project_membership_batch import (
    PROJECT_MEMBERSHIP_ADD_MANY,
    OaEmployeeBatchResolutionSource,
    ProjectMembershipBatchError,
    admit_project_membership_batch,
    validate_project_membership_batch_admission,
)

PROJECT_MEMBERSHIP_BATCH_ORCHESTRATION_SCHEMA_VERSION = (
    "p8.project_membership_batch_orchestration.v1"
)
PROJECT_MEMBERSHIP_BATCH_RESULT_SCHEMA_VERSION = (
    "p8.project_membership_batch_result_projection.v1"
)

_EMPLOYEE_ID_PARAMETER = re.compile(r"^employee_id(?:_([1-9][0-9]?))?$")
_EMPLOYEE_NAME_PARAMETER = re.compile(r"^employee_name(?:_([1-9][0-9]?))?$")
_MEMBER_ROLES = frozenset({"OWNER", "MANAGER", "MEMBER", "VIEWER"})
_COMMIT_OUTCOMES = frozenset(
    {
        "ADDED",
        "REACTIVATED",
        "ALREADY_ACTIVE",
        "SUBJECT_INACTIVE",
        "ROLE_CONFLICT",
        "NOT_ELIGIBLE",
    }
)
_APPLIED_OUTCOMES = frozenset({"ADDED", "REACTIVATED", "ALREADY_ACTIVE"})


def orchestrate_project_membership_batch_candidate(
    *,
    candidate: Mapping[str, Any],
    tenant_id: str,
    requester_subject_id: str,
    projects: Sequence[Mapping[str, Any]],
    source: OaEmployeeBatchResolutionSource,
    request_id: str,
    trace_id: str,
) -> dict[str, Any]:
    normalized = parse_intent_candidate(canonical_json(dict(candidate)))
    candidate_hash = semantic_sha256_hash_ref(normalized)
    if normalized["intent_label"] != PROJECT_MEMBERSHIP_ADD_MANY:
        raise _error(
            "ae.project_membership_batch_intent_unsupported",
            "The INTENT candidate does not select batch Project membership.",
        )
    if normalized["clarification"]["required"]:
        return _stopped(
            candidate_hash,
            "MODEL_CLARIFICATION_REQUIRED",
            normalized["clarification"],
        )

    tenant = _text(tenant_id, "tenant_id", 128)
    requester = _text(requester_subject_id, "requester_subject_id", 128)
    project, failure = _resolve_project(
        normalized["entity_selectors"], projects, tenant
    )
    if failure is not None:
        return _stopped(candidate_hash, failure["code"], failure["clarification"])

    parameters = _parameter_map(normalized["parameter_candidates"])
    candidates, member_role = _member_candidates(parameters)
    intake = {
        "tenant_id": tenant,
        "requester_subject_id": requester,
        "project_id": _text(project.get("project_id"), "project_id", 128),
        "candidates": candidates,
        "member_role": member_role,
    }
    admission = admit_project_membership_batch(
        intake,
        source=source,
        request_id=request_id,
        trace_id=trace_id,
    )
    result = {
        "schema_version": PROJECT_MEMBERSHIP_BATCH_ORCHESTRATION_SCHEMA_VERSION,
        "directive": admission["directive"],
        "failure_code": (
            None
            if admission["directive"] == "CONTINUE"
            else "ALL_CANDIDATES_REJECTED"
        ),
        "candidate_hash": candidate_hash,
        "intake_hash": semantic_sha256_hash_ref(intake),
        "project_ref": {"type": "eos.project", "id": intake["project_id"]},
        "admission": admission,
        "approval_projection": deepcopy(admission["approval_projection"]),
        "model_authority": False,
    }
    result["orchestration_hash"] = semantic_sha256_hash_ref(result)
    return result


def activate_project_membership_batch_work_intent(
    work_intent: Mapping[str, Any],
    *,
    orchestration: Mapping[str, Any],
) -> dict[str, Any]:
    normalized = _validate_orchestration(orchestration)
    if normalized["directive"] != "CONTINUE":
        raise _error(
            "ae.project_membership_batch_not_admitted",
            "A stopped membership batch cannot activate a WorkIntent.",
        )
    record = deepcopy(dict(work_intent))
    expected = semantic_sha256_hash_ref(
        {key: value for key, value in record.items() if key != "intent_hash"}
    )
    if record.get("schema_version") != "1.1" or record.get("intent_hash") != expected:
        raise _error(
            "ae.project_membership_batch_work_intent_invalid",
            "Batch activation requires an intact WorkIntent v1.1.",
        )
    record.update(
        {
            "intent_label": PROJECT_MEMBERSHIP_ADD_MANY,
            "goal": (
                "Resolve and add the admitted employee set to the selected "
                "Project through one governed operation."
            ),
            "required_capability_hints": [PROJECT_MEMBERSHIP_ADD_MANY],
            "constraints": [
                *record.get("constraints", []),
                {
                    "constraint_type": "DETERMINISTIC_AUTHORITY",
                    "description": (
                        "Project and subject authority comes from EOS and OA, "
                        "never model output."
                    ),
                },
                {
                    "constraint_type": "PROJECT_MEMBERSHIP_BATCH_ADMISSION",
                    "description": normalized["admission"]["admission_hash"],
                },
            ],
            "clarification": {
                "status": "NOT_REQUIRED",
                "reasons": [],
                "questions": [],
            },
        }
    )
    record["intent_hash"] = semantic_sha256_hash_ref(
        {key: value for key, value in record.items() if key != "intent_hash"}
    )
    return record


def build_project_membership_batch_result_projection(
    admission: Mapping[str, Any],
    eos_response: Mapping[str, Any],
) -> dict[str, Any]:
    admitted = validate_project_membership_batch_admission(admission)
    if admitted["directive"] != "CONTINUE":
        raise _error(
            "ae.project_membership_batch_not_admitted",
            "Rejected membership intake has no EOS result projection.",
        )
    response = _validate_eos_result(admitted, eos_response)
    business_result = response["result"]
    pre_admission_items = [
        {
            "stage": "OA_RESOLUTION",
            "input_index": item["input_index"],
            "subject_id": None,
            "normalized_employee_id": item.get("normalized_employee_id"),
            "outcome": item["outcome_code"],
            "applied": False,
        }
        for item in admitted["rejected_candidates"]
    ]
    commit_items = [
        {
            "stage": "EOS_COMMIT",
            "input_index": None,
            "subject_id": item["subject_id"],
            "normalized_employee_id": None,
            "outcome": item["outcome"],
            "applied": item["outcome"] in _APPLIED_OUTCOMES,
        }
        for item in business_result["item_results"]
    ]
    applied_count = sum(item["applied"] for item in commit_items)
    total_rejected = len(pre_admission_items) + business_result["rejected_count"]
    if total_rejected and applied_count:
        overall_status = "PARTIALLY_APPLIED"
    elif total_rejected:
        overall_status = "REJECTED"
    else:
        overall_status = business_result["operation_status"]
    result = {
        "schema_version": PROJECT_MEMBERSHIP_BATCH_RESULT_SCHEMA_VERSION,
        "operation_id": PROJECT_MEMBERSHIP_ADD_MANY,
        "payload_hash": admitted["payload_hash"],
        "project_id": admitted["project_id"],
        "member_role": admitted["member_role"],
        "overall_status": overall_status,
        "business_result_ref": business_result["business_result_ref"],
        "summary": {
            "requested_count": admitted["requested_count"],
            "admitted_count": admitted["admitted_count"],
            "applied_count": applied_count,
            "pre_admission_rejected_count": len(pre_admission_items),
            "commit_rejected_count": business_result["rejected_count"],
            "total_rejected_count": total_rejected,
        },
        "items": [*pre_admission_items, *commit_items],
        "metadata": {
            "model_authority": False,
            "raw_prompt_included": False,
            "credentials_included": False,
            "provider_configuration_included": False,
        },
    }
    result["result_hash"] = semantic_sha256_hash_ref(result)
    return result


def _validate_orchestration(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _error(
            "ae.project_membership_batch_orchestration_invalid",
            "Membership batch orchestration is invalid.",
        )
    supplied = deepcopy(dict(value))
    expected = semantic_sha256_hash_ref(
        {key: item for key, item in supplied.items() if key != "orchestration_hash"}
    )
    if (
        supplied.get("schema_version")
        != PROJECT_MEMBERSHIP_BATCH_ORCHESTRATION_SCHEMA_VERSION
        or supplied.get("orchestration_hash") != expected
        or supplied.get("model_authority") is not False
    ):
        raise _error(
            "ae.project_membership_batch_orchestration_invalid",
            "Membership batch orchestration integrity failed.",
        )
    if supplied.get("directive") == "CONTINUE":
        supplied["admission"] = validate_project_membership_batch_admission(
            supplied.get("admission")
        )
    return supplied


def _validate_eos_result(
    admission: Mapping[str, Any], eos_response: Mapping[str, Any]
) -> dict[str, Any]:
    if not isinstance(eos_response, Mapping):
        raise _error(
            "ae.project_membership_batch_result_invalid",
            "EOS membership batch result is invalid.",
        )
    response = deepcopy(dict(eos_response))
    result = response.get("result")
    if (
        response.get("operation") != PROJECT_MEMBERSHIP_ADD_MANY
        or response.get("commit_state") != "COMMITTED"
        or response.get("tenant_id") != admission["tenant_id"]
        or response.get("payload_hash") != admission["payload_hash"]
        or not isinstance(result, Mapping)
        or result.get("project_id") != admission["project_id"]
        or result.get("member_role") != admission["member_role"]
        or result.get("resolution_evidence_hash")
        != admission["resolution_evidence_hash"]
    ):
        raise _error(
            "ae.project_membership_batch_result_invalid",
            "EOS membership batch result does not match the admitted command.",
        )
    items = result.get("item_results")
    if not isinstance(items, list) or any(not isinstance(item, Mapping) for item in items):
        raise _error(
            "ae.project_membership_batch_result_invalid",
            "EOS membership batch item results are invalid.",
        )
    subjects = [item.get("subject_id") for item in items]
    expected_subjects = [item["subject_id"] for item in admission["admitted_members"]]
    if subjects != expected_subjects or len(set(subjects)) != len(subjects):
        raise _error(
            "ae.project_membership_batch_result_invalid",
            "EOS membership batch item set does not match admission.",
        )
    outcomes = [item.get("outcome") for item in items]
    if any(outcome not in _COMMIT_OUTCOMES for outcome in outcomes):
        raise _error(
            "ae.project_membership_batch_result_invalid",
            "EOS membership batch item outcome is invalid.",
        )
    counts = {
        "requested_count": len(items),
        "resolved_count": len(items),
        "added_count": outcomes.count("ADDED"),
        "reactivated_count": outcomes.count("REACTIVATED"),
        "unchanged_count": outcomes.count("ALREADY_ACTIVE"),
        "rejected_count": sum(outcome not in _APPLIED_OUTCOMES for outcome in outcomes),
    }
    if any(result.get(key) != expected for key, expected in counts.items()):
        raise _error(
            "ae.project_membership_batch_result_invalid",
            "EOS membership batch aggregate counts are invalid.",
        )
    return response


def _resolve_project(selectors, projects, tenant_id):
    tenant_projects = [
        item
        for item in projects
        if isinstance(item, Mapping) and item.get("tenant_id") == tenant_id
    ]
    values = [str(item["value"]) for item in selectors]
    exact = {
        str(project.get("project_id")): project
        for value in values
        for project in tenant_projects
        if value.casefold() == str(project.get("project_code", "")).casefold()
    }
    if len(exact) == 1:
        project = next(iter(exact.values()))
        if project.get("status") != "ACTIVE":
            return None, _failure(
                "PROJECT_INACTIVE",
                "선택한 프로젝트가 활성 상태가 아닙니다.",
                blocked=True,
            )
        return project, None
    if len(exact) > 1:
        return None, _failure(
            "PROJECT_CANDIDATE_AMBIGUOUS",
            "작업할 프로젝트 코드를 하나만 선택해 주세요.",
        )
    if any(
        value.casefold() == str(project.get("name", "")).casefold()
        for value in values
        for project in tenant_projects
    ):
        return None, _failure(
            "PROJECT_CONFIRMATION_REQUIRED",
            "검색된 프로젝트의 정확한 프로젝트 코드를 확인해 주세요.",
        )
    return None, _failure(
        "PROJECT_CANDIDATE_NOT_FOUND",
        "정확한 프로젝트 코드를 입력해 주세요.",
    )


def _parameter_map(items) -> dict[str, Mapping[str, Any]]:
    parameters = {item["name"]: item for item in items}
    allowed = {"member_role", "employee_id", "employee_name"}
    unknown = [
        name
        for name in parameters
        if name not in allowed
        and _EMPLOYEE_ID_PARAMETER.fullmatch(name) is None
        and _EMPLOYEE_NAME_PARAMETER.fullmatch(name) is None
    ]
    if unknown:
        raise _error(
            "ae.project_membership_batch_parameter_invalid",
            "Batch membership candidate contains unsupported parameters.",
        )
    return parameters


def _member_candidates(
    parameters: Mapping[str, Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], str]:
    employee_ids: dict[int, str] = {}
    names: dict[int, str] = {}
    for name, item in parameters.items():
        id_match = _EMPLOYEE_ID_PARAMETER.fullmatch(name)
        name_match = _EMPLOYEE_NAME_PARAMETER.fullmatch(name)
        if id_match is not None:
            index = int(id_match.group(1) or "1")
            employee_ids[index] = _text(item.get("value"), name, 128)
        elif name_match is not None:
            index = int(name_match.group(1) or "1")
            names[index] = _text(item.get("value"), name, 256)
    if not employee_ids or len(employee_ids) > 50 or set(names) - set(employee_ids):
        raise _error(
            "ae.project_membership_batch_candidates_invalid",
            "Batch membership employee candidates are incomplete.",
        )
    role_item = parameters.get("member_role")
    member_role = (
        "MEMBER"
        if role_item is None
        else _text(role_item.get("value"), "member_role", 32).upper()
    )
    if member_role not in _MEMBER_ROLES:
        raise _error(
            "ae.project_membership_batch_role_invalid",
            "Batch membership role is invalid.",
        )
    candidates = []
    for input_index, source_index in enumerate(sorted(employee_ids)):
        candidate = {
            "input_index": input_index,
            "employee_id": employee_ids[source_index],
        }
        if source_index in names:
            candidate["expected_name"] = names[source_index]
        candidates.append(candidate)
    return candidates, member_role


def _stopped(candidate_hash, failure_code, clarification):
    result = {
        "schema_version": PROJECT_MEMBERSHIP_BATCH_ORCHESTRATION_SCHEMA_VERSION,
        "directive": (
            "BLOCKED" if failure_code == "PROJECT_INACTIVE" else "CLARIFICATION_REQUIRED"
        ),
        "failure_code": failure_code,
        "candidate_hash": candidate_hash,
        "intake_hash": None,
        "project_ref": None,
        "admission": None,
        "approval_projection": None,
        "model_authority": False,
        "clarification": deepcopy(dict(clarification)),
    }
    result["orchestration_hash"] = semantic_sha256_hash_ref(result)
    return result


def _failure(code, question, *, blocked=False):
    return {
        "code": code,
        "blocked": blocked,
        "clarification": {
            "required": not blocked,
            "reasons": [code],
            "questions": [] if blocked else [question],
        },
    }


def _text(value: object, field_name: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise _error(
            "ae.project_membership_batch_parameter_invalid",
            f"{field_name} must be bounded non-empty text.",
        )
    return value.strip()


def _error(code: str, detail: str) -> ProjectMembershipBatchError:
    return ProjectMembershipBatchError(422, code, detail, False)
