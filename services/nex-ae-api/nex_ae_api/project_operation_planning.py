from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from nex_runtime.semantic_hashes import (
    canonical_json,
    semantic_sha256_hash_ref,
    validate_hash_ref,
)

from nex_ae_api.intent_candidate_generation import parse_intent_candidate
from nex_ae_api.nsl_backend_profiles import NSL_V02_IN_PROCESS_BACKEND
from nex_ae_api.planning_capabilities import (
    DEFAULT_P5_CAPABILITIES,
    build_capability_snapshot,
    build_local_skill_capability,
)

PROJECT_OPERATION_ADMISSION_SCHEMA_VERSION = "p8.project_operation_admission.v1"
PROJECT_OPERATION_TRUST_POLICY = "policy://nex/ae/governed-project-operation/v1"
PROJECT_OPERATION_RUNTIME_CONTRACT = "contract://nex/nsl/write-runtime/v0.2"
PROJECT_OPERATION_READ_RUNTIME_CONTRACT = "contract://nex/nsl/read-runtime/v0.2"
DEFAULT_PROJECT_CURRENCY = "KRW"

PROJECT_CREATE = "PROJECT.PROJECT.CREATE"
PROJECT_GET = "PROJECT.PROJECT.GET"
PROJECT_LIST = "PROJECT.PROJECT.LIST"
PROJECT_DEACTIVATE = "PROJECT.PROJECT.DEACTIVATE"
NVT_PROJECT_CREATE = "PROJECT.NVT_PROJECT.CREATE"
NVT_PROJECT_GET = "PROJECT.NVT_PROJECT.GET"
NVT_PROJECT_LIST = "PROJECT.NVT_PROJECT.LIST"
NVT_PROJECT_UPDATE = "PROJECT.NVT_PROJECT.UPDATE"
MEMBERSHIP_ADD = "PROJECT.MEMBERSHIP.ADD"
MEMBERSHIP_REMOVE = "PROJECT.MEMBERSHIP.REMOVE"
MEMBERSHIP_LIST = "PROJECT.MEMBERSHIP.LIST"

PROJECT_READ_OPERATIONS = frozenset(
    {PROJECT_GET, PROJECT_LIST, NVT_PROJECT_GET, NVT_PROJECT_LIST, MEMBERSHIP_LIST}
)
PROJECT_WRITE_OPERATIONS = frozenset(
    {
        PROJECT_CREATE,
        PROJECT_DEACTIVATE,
        NVT_PROJECT_CREATE,
        NVT_PROJECT_UPDATE,
        MEMBERSHIP_ADD,
        MEMBERSHIP_REMOVE,
    }
)
PROJECT_OPERATIONS = PROJECT_READ_OPERATIONS | PROJECT_WRITE_OPERATIONS

_PROJECT_REQUIRED = frozenset(
    {PROJECT_GET, PROJECT_DEACTIVATE, MEMBERSHIP_ADD, MEMBERSHIP_REMOVE, MEMBERSHIP_LIST}
)
_NVT_PROJECT_REQUIRED = frozenset({NVT_PROJECT_GET, NVT_PROJECT_UPDATE})
_SUBJECT_REQUIRED = frozenset({MEMBERSHIP_ADD, MEMBERSHIP_REMOVE})
_PROJECT_CODE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_MEMBER_ROLES = frozenset({"OWNER", "MANAGER", "MEMBER", "VIEWER"})
_NVT_PROJECT_STATUSES = frozenset({"ACTIVE", "INACTIVE"})


@dataclass(frozen=True)
class ProjectOperationPlanningError(ValueError):
    error_code: str
    detail: str

    def __str__(self) -> str:
        return self.detail


def build_project_operation_capabilities(
    *,
    read_admission: Mapping[str, Any],
    write_admission: Mapping[str, Any],
) -> tuple[dict[str, Any], ...]:
    artifacts = _artifact_map(read_admission, write_admission)
    capabilities = []
    for operation_id in sorted(PROJECT_OPERATIONS):
        artifact = artifacts[operation_id]
        write = operation_id in PROJECT_WRITE_OPERATIONS
        capabilities.append(
            build_local_skill_capability(
                skill_id=operation_id,
                exact_skill_version=artifact["skill_version"],
                skill_semantic_hash=artifact["semantic_hash"],
                input_contract_ref=(
                    f"contract://nex/eos/{operation_id.casefold()}/request/v1"
                ),
                output_contract_ref=(
                    f"contract://nex/eos/{operation_id.casefold()}/result/v1"
                ),
                runtime_contract_ref=(
                    PROJECT_OPERATION_RUNTIME_CONTRACT
                    if write
                    else PROJECT_OPERATION_READ_RUNTIME_CONTRACT
                ),
                trust_policy_id=PROJECT_OPERATION_TRUST_POLICY,
                backend_profile=NSL_V02_IN_PROCESS_BACKEND,
                operation_semantics="WRITE" if write else "READ",
            )
        )
    return tuple(capabilities)


def build_project_operation_capability_snapshot(
    *,
    tenant_id: str,
    read_admission: Mapping[str, Any],
    write_admission: Mapping[str, Any],
    capability_snapshot_id: str,
    snapshot_version: int,
    created_at: str,
    baseline_capabilities: Sequence[Mapping[str, Any]] = DEFAULT_P5_CAPABILITIES,
) -> dict[str, Any]:
    return build_capability_snapshot(
        tenant_id=_text(tenant_id, "tenant_id", 128),
        capability_snapshot_id=capability_snapshot_id,
        snapshot_version=snapshot_version,
        created_at=created_at,
        capabilities=(
            *baseline_capabilities,
            *build_project_operation_capabilities(
                read_admission=read_admission,
                write_admission=write_admission,
            ),
        ),
    )


def admit_project_operation_candidate(
    *,
    candidate: Mapping[str, Any],
    tenant_id: str,
    requester_subject_id: str,
    read_admission: Mapping[str, Any],
    write_admission: Mapping[str, Any],
    projects: Sequence[Mapping[str, Any]],
    subjects: Sequence[Mapping[str, Any]],
    nvt_projects: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    tenant = _text(tenant_id, "tenant_id", 128)
    requester = _text(requester_subject_id, "requester_subject_id", 128)
    normalized = parse_intent_candidate(canonical_json(dict(candidate)))
    candidate_hash = semantic_sha256_hash_ref(normalized)
    operation_id = normalized["intent_label"]
    artifacts = _artifact_map(read_admission, write_admission)
    if operation_id not in PROJECT_OPERATIONS:
        raise _error(
            "P8_PROJECT_OPERATION_UNSUPPORTED",
            "The INTENT candidate does not select a canonical Project operation.",
        )

    if normalized["clarification"]["required"]:
        return _stopped(
            candidate_hash=candidate_hash,
            operation_id=operation_id,
            directive="CLARIFICATION_REQUIRED",
            failure_code="MODEL_CLARIFICATION_REQUIRED",
            reasons=normalized["clarification"]["reasons"],
            questions=normalized["clarification"]["questions"],
        )

    tenant_projects = _tenant_records(projects, tenant, "project")
    tenant_subjects = _tenant_records(subjects, tenant, "subject")
    tenant_nvt_projects = _tenant_records(nvt_projects, tenant, "NVTProject")
    parameters = _parameter_map(normalized["parameter_candidates"])

    project: Mapping[str, Any] | None = None
    if operation_id in _PROJECT_REQUIRED:
        project, failure = _resolve_project(
            normalized["entity_selectors"], tenant_projects
        )
        if failure is not None:
            return _failure(candidate_hash, operation_id, failure)

    nvt_project: Mapping[str, Any] | None = None
    if operation_id in _NVT_PROJECT_REQUIRED:
        nvt_project, failure = _resolve_nvt_project(
            normalized["entity_selectors"], tenant_nvt_projects
        )
        if failure is not None:
            return _failure(candidate_hash, operation_id, failure)

    subject: Mapping[str, Any] | None = None
    if operation_id in _SUBJECT_REQUIRED:
        subject, failure = _resolve_subject(
            parameters.get("employee_id"),
            requester_subject_id=requester,
            subjects=tenant_subjects,
        )
        if failure is not None:
            return _failure(candidate_hash, operation_id, failure)

    arguments: dict[str, Any]
    if operation_id == PROJECT_CREATE:
        arguments, failure = _create_arguments(
            parameters,
            tenant=tenant,
            requester=requester,
            candidate_hash=candidate_hash,
            projects=tenant_projects,
            subjects=tenant_subjects,
        )
        if failure is not None:
            return _failure(candidate_hash, operation_id, failure)
    elif operation_id == NVT_PROJECT_CREATE:
        arguments, failure = _nvt_create_arguments(
            parameters,
            tenant=tenant,
            requester=requester,
            candidate_hash=candidate_hash,
            nvt_projects=tenant_nvt_projects,
        )
        if failure is not None:
            return _failure(candidate_hash, operation_id, failure)
    elif operation_id == PROJECT_LIST:
        arguments = {
            "tenant_id": tenant,
            "requester_subject_id": requester,
            "limit": _bounded_page(parameters.get("limit"), 100),
            "offset": _bounded_offset(parameters.get("offset")),
        }
    elif operation_id == NVT_PROJECT_LIST:
        status, failure = _nvt_status(parameters.get("status"), default="ACTIVE")
        if failure is not None:
            return _failure(candidate_hash, operation_id, failure)
        arguments = {
            "tenant_id": tenant,
            "requester_subject_id": requester,
            "status": status,
            "limit": _bounded_page(parameters.get("limit"), 100),
            "offset": _bounded_offset(parameters.get("offset")),
        }
    elif operation_id in _NVT_PROJECT_REQUIRED:
        assert nvt_project is not None
        arguments = {
            "tenant_id": tenant,
            "requester_subject_id": requester,
            "nvt_project_id": _nvt_project_id(nvt_project),
        }
        if operation_id == NVT_PROJECT_UPDATE:
            update, failure = _nvt_update_arguments(parameters, nvt_project)
            if failure is not None:
                return _failure(candidate_hash, operation_id, failure)
            arguments.update(update)
    else:
        assert project is not None
        arguments = {
            "tenant_id": tenant,
            "requester_subject_id": requester,
            "project_id": _project_id(project),
        }
        if operation_id == PROJECT_DEACTIVATE:
            arguments["expected_version"] = _positive_int(
                project.get("entity_version", project.get("version")),
                "project entity_version",
            )
        elif operation_id == MEMBERSHIP_ADD:
            assert subject is not None
            role, failure = _member_role(parameters.get("member_role"))
            if failure is not None:
                return _failure(candidate_hash, operation_id, failure)
            assert role is not None
            arguments.update(
                {
                    "target_subject_id": _subject_id(subject),
                    "project_membership_id": _stable_uuid(
                        "membership",
                        tenant,
                        _project_id(project),
                        _subject_id(subject),
                    ),
                    "member_role": role,
                }
            )
        elif operation_id == MEMBERSHIP_REMOVE:
            assert subject is not None
            arguments["target_subject_id"] = _subject_id(subject)
        elif operation_id == MEMBERSHIP_LIST:
            arguments.update(
                {
                    "limit": _bounded_page(parameters.get("limit"), 100),
                    "offset": _bounded_offset(parameters.get("offset")),
                }
            )

    artifact = artifacts[operation_id]
    binding = {
        "operation_id": operation_id,
        "tenant_id": tenant,
        "requester_subject_id": requester,
        "capability_ref": {
            "capability_id": operation_id,
            "skill_id": operation_id,
            "skill_version": artifact["skill_version"],
            "skill_semantic_hash": artifact["semantic_hash"],
            "source_sha256": artifact["source_sha256"],
        },
        "arguments": arguments,
        "project_ref": (
            None
            if project is None
            else {"type": "eos.project", "id": _project_id(project)}
        ),
        "nvt_project_ref": (
            {"type": "eos.nvt_project", "id": arguments["nvt_project_id"]}
            if operation_id == NVT_PROJECT_CREATE
            else (
                None
                if nvt_project is None
                else {"type": "eos.nvt_project", "id": _nvt_project_id(nvt_project)}
            )
        ),
        "target_subject_ref": (
            None
            if subject is None
            else {"type": "oa.user", "id": _subject_id(subject)}
        ),
        "model_authority": False,
    }
    return _finish(
        {
            "schema_version": PROJECT_OPERATION_ADMISSION_SCHEMA_VERSION,
            "directive": "CONTINUE",
            "failure_code": None,
            "candidate_hash": candidate_hash,
            "operation_id": operation_id,
            "clarification": {"reasons": [], "questions": []},
            "authoritative_binding": binding,
        }
    )


def activate_project_operation_work_intent(
    work_intent: Mapping[str, Any],
    *,
    admission: Mapping[str, Any],
) -> dict[str, Any]:
    record = deepcopy(dict(work_intent))
    expected = semantic_sha256_hash_ref(
        {key: value for key, value in record.items() if key != "intent_hash"}
    )
    if record.get("schema_version") != "1.1" or record.get("intent_hash") != expected:
        raise _error(
            "P8_PROJECT_WORK_INTENT_INVALID",
            "Project operation activation requires an intact WorkIntent v1.1.",
        )
    _require_admission_integrity(admission)
    binding = admission["authoritative_binding"]
    operation_id = binding["operation_id"]
    record.update(
        {
            "intent_label": operation_id,
            "goal": f"Execute the governed canonical operation {operation_id}.",
            "required_capability_hints": [operation_id],
            "constraints": [
                *record.get("constraints", []),
                {
                    "constraint_type": "DETERMINISTIC_AUTHORITY",
                    "description": (
                        "Tenant, Project, subject, and stable identifiers come from "
                        "authoritative OA/EOS resolution, never model output."
                    ),
                },
                {
                    "constraint_type": "PROJECT_OPERATION_BINDING",
                    "description": admission["admission_hash"],
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


def _artifact_map(
    read_admission: Mapping[str, Any], write_admission: Mapping[str, Any]
) -> dict[str, dict[str, Any]]:
    expected = (
        (
            read_admission,
            "nsl_project_read_artifact_admission.v1",
            PROJECT_READ_OPERATIONS,
        ),
        (
            write_admission,
            "nsl_project_write_artifact_admission.v1",
            PROJECT_WRITE_OPERATIONS,
        ),
    )
    result: dict[str, dict[str, Any]] = {}
    for admission, schema_version, identities in expected:
        if (
            not isinstance(admission, Mapping)
            or admission.get("schema_version") != schema_version
            or admission.get("status") != "PASS"
            or not isinstance(admission.get("skills"), Sequence)
        ):
            raise _error(
                "P8_PROJECT_ARTIFACT_ADMISSION_INVALID",
                "Project operation artifact admission is invalid.",
            )
        for raw in admission["skills"]:
            if not isinstance(raw, Mapping):
                raise _error(
                    "P8_PROJECT_ARTIFACT_ADMISSION_INVALID",
                    "Project operation artifact entry is invalid.",
                )
            skill_id = raw.get("skill_id")
            if skill_id in result:
                raise _error(
                    "P8_PROJECT_ARTIFACT_ADMISSION_INVALID",
                    "Project operation artifact identity is duplicated.",
                )
            try:
                validate_hash_ref(raw.get("semantic_hash"))
                validate_hash_ref(raw.get("source_sha256"))
            except ValueError as exc:
                raise _error(
                    "P8_PROJECT_ARTIFACT_ADMISSION_INVALID",
                    "Project operation artifact digest is invalid.",
                ) from exc
            if raw.get("skill_version") != "1.0.0":
                raise _error(
                    "P8_PROJECT_ARTIFACT_ADMISSION_INVALID",
                    "Project operation artifact version is unsupported.",
                )
            result[str(skill_id)] = dict(raw)
        if set(result).intersection(identities) != set(identities):
            raise _error(
                "P8_PROJECT_ARTIFACT_ADMISSION_INVALID",
                "Project operation artifact set is incomplete.",
            )
    if set(result) != PROJECT_OPERATIONS:
        raise _error(
            "P8_PROJECT_ARTIFACT_ADMISSION_INVALID",
            "Project operation artifact set contains an unsupported identity.",
        )
    return result


def _create_arguments(parameters, *, tenant, requester, candidate_hash, projects, subjects):
    if parameters.get("project_code") is None:
        return {}, _clarification(
            "PROJECT_CODE_REQUIRED",
            "Project code is required.",
            "새 프로젝트의 프로젝트 코드를 입력해 주세요.",
        )
    project_code = _parameter_text(parameters.get("project_code"), "project_code", 64)
    if _PROJECT_CODE.fullmatch(project_code) is None:
        return {}, _clarification(
            "PROJECT_CODE_INVALID",
            "Project code is invalid.",
            "영문, 숫자, 점, 밑줄 또는 하이픈으로 된 프로젝트 코드를 확인해 주세요.",
        )
    if any(
        str(item.get("project_code", "")).casefold() == project_code.casefold()
        for item in projects
    ):
        return {}, _blocked(
            "PROJECT_CODE_CONFLICT",
            "The Project code already exists in the tenant.",
        )
    if parameters.get("project_name") is None:
        return {}, _clarification(
            "PROJECT_NAME_REQUIRED",
            "Project name is required.",
            "새 프로젝트의 이름을 입력해 주세요.",
        )
    project_name = _parameter_text(parameters.get("project_name"), "project_name", 200)
    currency_item = parameters.get("currency")
    currency = (
        DEFAULT_PROJECT_CURRENCY
        if currency_item is None
        else _parameter_text(currency_item, "currency", 3).upper()
    )
    if _CURRENCY.fullmatch(currency) is None:
        return {}, _clarification(
            "PROJECT_CURRENCY_INVALID",
            "Project currency is invalid.",
            "프로젝트 통화를 ISO 3자리 코드로 확인해 주세요.",
        )
    owner, failure = _resolve_subject(
        parameters.get("initial_owner_employee_id"),
        requester_subject_id=requester,
        subjects=subjects,
        default_self=True,
    )
    if failure is not None:
        return {}, failure
    assert owner is not None
    project_id = _stable_uuid("project", tenant, candidate_hash, project_code)
    return {
        "tenant_id": tenant,
        "requester_subject_id": requester,
        "project_id": project_id,
        "project_code": project_code,
        "project_name": project_name,
        "initial_owner_subject_id": _subject_id(owner),
        "initial_owner_membership_id": _stable_uuid(
            "membership", tenant, project_id, _subject_id(owner)
        ),
        "currency": currency,
    }, None


def _nvt_create_arguments(
    parameters,
    *,
    tenant,
    requester,
    candidate_hash,
    nvt_projects,
):
    if parameters.get("nvt_project_code") is None:
        return {}, _clarification(
            "NVT_PROJECT_CODE_REQUIRED",
            "NVTProject code is required.",
            "새 NVT 프로젝트의 코드를 입력해 주세요.",
        )
    code = _parameter_text(parameters.get("nvt_project_code"), "nvt_project_code", 64)
    if _PROJECT_CODE.fullmatch(code) is None:
        return {}, _clarification(
            "NVT_PROJECT_CODE_INVALID",
            "NVTProject code is invalid.",
            "영문, 숫자, 점, 밑줄 또는 하이픈으로 된 NVT 프로젝트 코드를 확인해 주세요.",
        )
    if any(
        str(item.get("nvt_project_code", "")).casefold() == code.casefold()
        for item in nvt_projects
    ):
        return {}, _blocked(
            "NVT_PROJECT_CODE_CONFLICT",
            "The NVTProject code already exists in the tenant.",
        )
    if parameters.get("nvt_project_name") is None:
        return {}, _clarification(
            "NVT_PROJECT_NAME_REQUIRED",
            "NVTProject name is required.",
            "새 NVT 프로젝트의 이름을 입력해 주세요.",
        )
    name = _parameter_text(parameters.get("nvt_project_name"), "nvt_project_name", 256)
    status, failure = _nvt_status(parameters.get("status"), default="ACTIVE")
    if failure is not None:
        return {}, failure
    if status != "ACTIVE":
        return {}, _clarification(
            "NVT_PROJECT_INITIAL_STATUS_INVALID",
            "A new NVTProject must start ACTIVE.",
            "새 NVT 프로젝트의 초기 상태는 ACTIVE로 지정해 주세요.",
        )
    return {
        "tenant_id": tenant,
        "requester_subject_id": requester,
        "nvt_project_id": _stable_uuid("nvt-project", tenant, candidate_hash, code),
        "nvt_project_code": code,
        "nvt_project_name": name,
        "status": "ACTIVE",
    }, None


def _nvt_update_arguments(parameters, nvt_project):
    name_item = parameters.get("nvt_project_name")
    status_item = parameters.get("status")
    if name_item is None and status_item is None:
        return {}, _clarification(
            "NVT_PROJECT_CHANGE_REQUIRED",
            "An NVTProject name or status change is required.",
            "변경할 NVT 프로젝트 이름 또는 상태를 입력해 주세요.",
        )
    name = (
        _text(nvt_project.get("name"), "NVTProject name", 256)
        if name_item is None
        else _parameter_text(name_item, "nvt_project_name", 256)
    )
    status, failure = _nvt_status(status_item, default=nvt_project.get("status"))
    if failure is not None:
        return {}, failure
    return {
        "expected_version": _positive_int(
            nvt_project.get("entity_version", nvt_project.get("version")),
            "NVTProject entity_version",
        ),
        "nvt_project_name": name,
        "status": status,
    }, None


def _nvt_status(item, *, default):
    status = (
        str(default).strip().upper()
        if item is None
        else _parameter_text(item, "status", 16).upper()
    )
    if status not in _NVT_PROJECT_STATUSES:
        return None, _clarification(
            "NVT_PROJECT_STATUS_INVALID",
            "NVTProject status is invalid.",
            "NVT 프로젝트 상태를 ACTIVE 또는 INACTIVE로 입력해 주세요.",
        )
    return status, None


def _resolve_project(selectors, projects):
    values = [str(item["value"]) for item in selectors]
    exact = {
        _project_id(project): project
        for value in values
        for project in projects
        if value.casefold() == str(project.get("project_code", "")).casefold()
    }
    if len(exact) == 1:
        project = next(iter(exact.values()))
        if project.get("status") != "ACTIVE":
            return None, _blocked(
                "PROJECT_INACTIVE", "The selected Project is inactive."
            )
        return project, None
    if len(exact) > 1:
        return None, _clarification(
            "PROJECT_CANDIDATE_AMBIGUOUS",
            "Multiple Project codes were proposed.",
            "작업할 프로젝트 코드를 하나만 선택해 주세요.",
        )
    if any(
        value.casefold() == str(project.get("name", "")).casefold()
        for value in values
        for project in projects
    ):
        return None, _clarification(
            "PROJECT_CONFIRMATION_REQUIRED",
            "A Project display-name match requires exact-code confirmation.",
            "검색된 프로젝트의 정확한 프로젝트 코드를 확인해 주세요.",
        )
    return None, _clarification(
        "PROJECT_CANDIDATE_NOT_FOUND",
        "No tenant-scoped exact Project code was resolved.",
        "정확한 프로젝트 코드를 입력해 주세요.",
    )


def _resolve_nvt_project(selectors, nvt_projects):
    values = [str(item["value"]) for item in selectors]
    exact = {
        _nvt_project_id(project): project
        for value in values
        for project in nvt_projects
        if value.casefold() == str(project.get("nvt_project_code", "")).casefold()
    }
    if len(exact) == 1:
        return next(iter(exact.values())), None
    if len(exact) > 1:
        return None, _clarification(
            "NVT_PROJECT_CANDIDATE_AMBIGUOUS",
            "Multiple NVTProject codes were proposed.",
            "작업할 NVT 프로젝트 코드를 하나만 선택해 주세요.",
        )
    if any(
        value.casefold() == str(project.get("name", "")).casefold()
        for value in values
        for project in nvt_projects
    ):
        return None, _clarification(
            "NVT_PROJECT_CONFIRMATION_REQUIRED",
            "An NVTProject display-name match requires exact-code confirmation.",
            "검색된 NVT 프로젝트의 정확한 코드를 확인해 주세요.",
        )
    return None, _clarification(
        "NVT_PROJECT_CANDIDATE_NOT_FOUND",
        "No tenant-scoped exact NVTProject code was resolved.",
        "정확한 NVT 프로젝트 코드를 입력해 주세요.",
    )


def _resolve_subject(
    item,
    *,
    requester_subject_id,
    subjects,
    default_self: bool = False,
):
    if item is None and default_self:
        value = "SELF"
    elif item is None:
        return None, _clarification(
            "EMPLOYEE_REFERENCE_REQUIRED",
            "An employee reference is required.",
            "대상 직원의 사번을 입력해 주세요.",
        )
    else:
        value = _parameter_text(item, "employee_id", 128)
    if value.upper() == "SELF":
        matches = [
            subject
            for subject in subjects
            if _subject_id(subject) == requester_subject_id
        ]
    else:
        matches = [
            subject
            for subject in subjects
            if value.casefold() == str(subject.get("employee_id", "")).casefold()
        ]
    if len(matches) > 1:
        return None, _clarification(
            "EMPLOYEE_REFERENCE_AMBIGUOUS",
            "The employee reference resolved to multiple subjects.",
            "대상 직원의 정확한 사번을 확인해 주세요.",
        )
    if not matches:
        return None, _clarification(
            "EMPLOYEE_REFERENCE_NOT_FOUND",
            "The employee reference was not found in the tenant.",
            "등록된 직원의 정확한 사번을 입력해 주세요.",
        )
    subject = matches[0]
    if subject.get("status") != "ACTIVE":
        return None, _blocked(
            "EMPLOYEE_INACTIVE", "The selected employee is inactive."
        )
    return subject, None


def _parameter_map(items):
    result = {}
    for item in items:
        name = item["name"]
        if name in result:
            raise _error(
                "P8_PROJECT_PARAMETER_DUPLICATE",
                "Project operation parameter names must be unique.",
            )
        result[name] = item
    return result


def _parameter_text(item, field_name, limit):
    if not isinstance(item, Mapping):
        raise _error(
            "P8_PROJECT_PARAMETER_REQUIRED", f"{field_name} is required."
        )
    return _text(item.get("value"), field_name, limit)


def _member_role(item):
    if item is None:
        return None, _clarification(
            "MEMBER_ROLE_REQUIRED",
            "Project member role is required.",
            "추가할 직원의 프로젝트 역할을 선택해 주세요.",
        )
    role = _parameter_text(item, "member_role", 32).upper()
    if role not in _MEMBER_ROLES:
        return None, _clarification(
            "MEMBER_ROLE_INVALID",
            "Project member role is invalid.",
            "OWNER, MANAGER, MEMBER, VIEWER 중 하나를 선택해 주세요.",
        )
    return role, None


def _bounded_page(item, default):
    if item is None:
        return default
    value = item.get("value") if isinstance(item, Mapping) else None
    if type(value) is not int or not 1 <= value <= 100:
        raise _error("P8_PROJECT_PAGE_INVALID", "Project list limit is invalid.")
    return value


def _bounded_offset(item):
    if item is None:
        return 0
    value = item.get("value") if isinstance(item, Mapping) else None
    if type(value) is not int or value < 0:
        raise _error("P8_PROJECT_PAGE_INVALID", "Project list offset is invalid.")
    return value


def _tenant_records(records, tenant_id, label):
    if isinstance(records, (str, bytes)) or not isinstance(records, Sequence):
        raise _error(
            "P8_PROJECT_AUTHORITY_INVALID", f"Authoritative {label} set is invalid."
        )
    return tuple(
        record
        for record in records
        if isinstance(record, Mapping) and record.get("tenant_id") == tenant_id
    )


def _project_id(project):
    return _text(project.get("project_id"), "project_id", 128)


def _nvt_project_id(project):
    return _text(project.get("nvt_project_id"), "nvt_project_id", 128)


def _subject_id(subject):
    return _text(subject.get("subject_id"), "subject_id", 128)


def _positive_int(value, field_name):
    if type(value) is not int or value < 1:
        raise _error(
            "P8_PROJECT_AUTHORITY_INVALID", f"{field_name} must be positive."
        )
    return value


def _stable_uuid(kind, *parts):
    return str(uuid5(NAMESPACE_URL, "nex:p8:project-operation:" + kind + ":" + ":".join(parts)))


def _clarification(code, reason, question):
    return "CLARIFICATION_REQUIRED", code, reason, question


def _blocked(code, reason):
    return "BLOCKED", code, reason, ""


def _failure(candidate_hash, operation_id, failure):
    directive, code, reason, question = failure
    return _stopped(
        candidate_hash=candidate_hash,
        operation_id=operation_id,
        directive=directive,
        failure_code=code,
        reasons=[reason],
        questions=[] if not question else [question],
    )


def _stopped(
    *, candidate_hash, operation_id, directive, failure_code, reasons, questions
):
    return _finish(
        {
            "schema_version": PROJECT_OPERATION_ADMISSION_SCHEMA_VERSION,
            "directive": directive,
            "failure_code": failure_code,
            "candidate_hash": candidate_hash,
            "operation_id": operation_id,
            "clarification": {
                "reasons": list(dict.fromkeys(reasons)),
                "questions": list(dict.fromkeys(questions)),
            },
            "authoritative_binding": None,
        }
    )


def _require_admission_integrity(admission):
    if (
        not isinstance(admission, Mapping)
        or admission.get("schema_version") != PROJECT_OPERATION_ADMISSION_SCHEMA_VERSION
        or admission.get("directive") != "CONTINUE"
        or not isinstance(admission.get("authoritative_binding"), Mapping)
    ):
        raise _error(
            "P8_PROJECT_ADMISSION_INVALID",
            "Project operation admission is not executable.",
        )
    expected = semantic_sha256_hash_ref(
        {key: value for key, value in admission.items() if key != "admission_hash"}
    )
    if admission.get("admission_hash") != expected:
        raise _error(
            "P8_PROJECT_ADMISSION_INVALID",
            "Project operation admission integrity is invalid.",
        )


def _finish(value):
    result = dict(value)
    result["admission_hash"] = semantic_sha256_hash_ref(result)
    return result


def _text(value, field_name, limit):
    if (
        not isinstance(value, str)
        or value != value.strip()
        or not value
        or len(value) > limit
    ):
        raise _error(
            "P8_PROJECT_INPUT_INVALID", f"{field_name} must be bounded text."
        )
    return value


def _error(code, detail):
    return ProjectOperationPlanningError(code, detail)
