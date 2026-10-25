from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from nex_ae_api.intent_candidate_generation import IntentCandidateStageError
from nex_ae_api.intent_policy import resolve_validated_intent_candidate
from nex_ae_api.project_operation_planning import (
    MEMBERSHIP_ADD,
    MEMBERSHIP_LIST,
    MEMBERSHIP_REMOVE,
    PROJECT_CREATE,
    PROJECT_DEACTIVATE,
    PROJECT_GET,
    PROJECT_LIST,
    PROJECT_OPERATIONS,
    ProjectOperationPlanningError,
    activate_project_operation_work_intent,
    admit_project_operation_candidate,
    build_project_operation_capabilities,
    build_project_operation_capability_snapshot,
)
from nex_ae_api.work_intent import build_work_intent_from_decision
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

ROOT = Path(__file__).resolve().parents[1]
READ_ADMISSION = ROOT / "contracts/examples/common/nsl_project_read_artifact_admission.pass.json"
WRITE_ADMISSION = ROOT / "contracts/examples/common/nsl_project_write_artifact_admission.pass.json"

TENANT = "tenant-s100"
REQUESTER = "employee-1001"
PROJECT_ID = "a1000000-0000-4000-8000-000000000001"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _projects(*, duplicate: bool = False, inactive: bool = False) -> list[dict]:
    values = [
        {
            "tenant_id": TENANT,
            "project_id": PROJECT_ID,
            "project_code": "PROJECT-A",
            "name": "프로젝트 A",
            "status": "INACTIVE" if inactive else "ACTIVE",
            "entity_version": 3,
        },
        {
            "tenant_id": "other-tenant",
            "project_id": "a1000000-0000-4000-8000-000000000002",
            "project_code": "PROJECT-A",
            "name": "다른 tenant 프로젝트",
            "status": "ACTIVE",
            "entity_version": 1,
        },
    ]
    if duplicate:
        values.append(
            {
                **values[0],
                "project_id": "a1000000-0000-4000-8000-000000000003",
            }
        )
    return values


def _subjects(*, duplicate: bool = False, inactive: bool = False) -> list[dict]:
    values = [
        {
            "tenant_id": TENANT,
            "subject_id": REQUESTER,
            "employee_id": "EMP-1001",
            "status": "ACTIVE",
        },
        {
            "tenant_id": TENANT,
            "subject_id": "subject-2002",
            "employee_id": "EMP-2002",
            "status": "INACTIVE" if inactive else "ACTIVE",
        },
        {
            "tenant_id": "other-tenant",
            "subject_id": "other-subject",
            "employee_id": "EMP-2002",
            "status": "ACTIVE",
        },
    ]
    if duplicate:
        values.append(
            {
                "tenant_id": TENANT,
                "subject_id": "subject-duplicate",
                "employee_id": "emp-2002",
                "status": "ACTIVE",
            }
        )
    return values


def _candidate(operation: str, *, selector: str | None = "PROJECT-A", **params) -> dict:
    return {
        "schema_version": "p65.intent_candidate.v1",
        "intent_label": operation,
        "suggested_execution_mode": "GENERAL_ANSWER",
        "entity_selectors": (
            []
            if selector is None
            else [
                {
                    "selector_id": "E1",
                    "selector_type": "QUERY_TERM",
                    "value": selector,
                    "confidence": 0.98,
                }
            ]
        ),
        "parameter_candidates": [
            {"name": name, "value": value, "confidence": 0.97}
            for name, value in params.items()
        ],
        "clarification": {"required": False, "reasons": [], "questions": []},
        "confidence": 0.98,
    }


def _admit(candidate: dict, **overrides) -> dict:
    values = {
        "candidate": candidate,
        "tenant_id": TENANT,
        "requester_subject_id": REQUESTER,
        "read_admission": _load(READ_ADMISSION),
        "write_admission": _load(WRITE_ADMISSION),
        "projects": _projects(),
        "subjects": _subjects(),
    }
    values.update(overrides)
    return admit_project_operation_candidate(**values)


@pytest.mark.parametrize(
    ("operation", "candidate", "expected"),
    (
        (
            PROJECT_CREATE,
            _candidate(
                PROJECT_CREATE,
                selector=None,
                project_code="PROJECT-NEW",
                project_name="신제품 출시",
                initial_owner_employee_id="SELF",
            ),
            {"currency": "KRW", "initial_owner_subject_id": REQUESTER},
        ),
        (PROJECT_GET, _candidate(PROJECT_GET), {"project_id": PROJECT_ID}),
        (
            PROJECT_LIST,
            _candidate(PROJECT_LIST, selector=None, limit=25, offset=5),
            {"limit": 25, "offset": 5},
        ),
        (
            PROJECT_DEACTIVATE,
            _candidate(PROJECT_DEACTIVATE),
            {"project_id": PROJECT_ID, "expected_version": 3},
        ),
        (
            MEMBERSHIP_ADD,
            _candidate(MEMBERSHIP_ADD, employee_id="EMP-2002", member_role="MEMBER"),
            {"project_id": PROJECT_ID, "target_subject_id": "subject-2002"},
        ),
        (
            MEMBERSHIP_REMOVE,
            _candidate(MEMBERSHIP_REMOVE, employee_id="EMP-2002"),
            {"project_id": PROJECT_ID, "target_subject_id": "subject-2002"},
        ),
        (
            MEMBERSHIP_LIST,
            _candidate(MEMBERSHIP_LIST),
            {"project_id": PROJECT_ID, "limit": 100, "offset": 0},
        ),
    ),
)
def test_all_canonical_project_operations_bind_only_authoritative_ids(
    operation: str, candidate: dict, expected: dict
) -> None:
    result = _admit(candidate)

    assert result["directive"] == "CONTINUE"
    assert result["operation_id"] == operation
    assert result["authoritative_binding"]["capability_ref"]["skill_id"] == operation
    assert result["authoritative_binding"]["model_authority"] is False
    arguments = result["authoritative_binding"]["arguments"]
    assert arguments["tenant_id"] == TENANT
    assert arguments["requester_subject_id"] == REQUESTER
    assert all(arguments[key] == value for key, value in expected.items())
    assert result["admission_hash"] == semantic_sha256_hash_ref(
        {key: value for key, value in result.items() if key != "admission_hash"}
    )


def test_project_and_employee_ambiguity_never_reaches_governed_write() -> None:
    project = _admit(
        _candidate(MEMBERSHIP_ADD, employee_id="EMP-2002", member_role="MEMBER"),
        projects=_projects(duplicate=True),
    )
    employee = _admit(
        _candidate(MEMBERSHIP_ADD, employee_id="EMP-2002", member_role="MEMBER"),
        subjects=_subjects(duplicate=True),
    )
    display_name = _admit(
        _candidate(PROJECT_GET, selector="프로젝트 A"),
    )

    assert project["directive"] == "CLARIFICATION_REQUIRED"
    assert project["failure_code"] == "PROJECT_CANDIDATE_AMBIGUOUS"
    assert employee["failure_code"] == "EMPLOYEE_REFERENCE_AMBIGUOUS"
    assert display_name["failure_code"] == "PROJECT_CONFIRMATION_REQUIRED"
    assert all(
        item["authoritative_binding"] is None
        for item in (project, employee, display_name)
    )


def test_inactive_project_and_subject_are_blocked_not_clarified() -> None:
    project = _admit(
        _candidate(PROJECT_DEACTIVATE), projects=_projects(inactive=True)
    )
    employee = _admit(
        _candidate(MEMBERSHIP_ADD, employee_id="EMP-2002", member_role="MEMBER"),
        subjects=_subjects(inactive=True),
    )

    assert (project["directive"], project["failure_code"]) == (
        "BLOCKED",
        "PROJECT_INACTIVE",
    )
    assert (employee["directive"], employee["failure_code"]) == (
        "BLOCKED",
        "EMPLOYEE_INACTIVE",
    )


@pytest.mark.parametrize(
    ("candidate", "failure_code"),
    (
        (
            _candidate(
                PROJECT_CREATE,
                selector=None,
                project_name="이름만 있는 프로젝트",
            ),
            "PROJECT_CODE_REQUIRED",
        ),
        (
            _candidate(
                PROJECT_CREATE,
                selector=None,
                project_code="PROJECT-NAME-MISSING",
            ),
            "PROJECT_NAME_REQUIRED",
        ),
        (
            _candidate(MEMBERSHIP_ADD, employee_id="EMP-2002"),
            "MEMBER_ROLE_REQUIRED",
        ),
        (
            _candidate(
                MEMBERSHIP_ADD,
                employee_id="EMP-2002",
                member_role="UNKNOWN",
            ),
            "MEMBER_ROLE_INVALID",
        ),
    ),
)
def test_missing_or_invalid_business_arguments_require_clarification(
    candidate: dict, failure_code: str
) -> None:
    result = _admit(candidate)

    assert result["directive"] == "CLARIFICATION_REQUIRED"
    assert result["failure_code"] == failure_code
    assert result["authoritative_binding"] is None


def test_model_requested_clarification_is_preserved_without_binding() -> None:
    candidate = _candidate(PROJECT_GET)
    candidate["clarification"] = {
        "required": True,
        "reasons": ["프로젝트 코드가 불명확합니다."],
        "questions": ["정확한 프로젝트 코드는 무엇인가요?"],
    }

    result = _admit(candidate)

    assert result["directive"] == "CLARIFICATION_REQUIRED"
    assert result["failure_code"] == "MODEL_CLARIFICATION_REQUIRED"
    assert result["clarification"] == {
        "reasons": candidate["clarification"]["reasons"],
        "questions": candidate["clarification"]["questions"],
    }
    assert result["authoritative_binding"] is None


def test_create_ids_are_deterministic_and_tenant_scoped() -> None:
    candidate = _candidate(
        PROJECT_CREATE,
        selector=None,
        project_code="PROJECT-NEW",
        project_name="신제품 출시",
    )
    first = _admit(candidate)
    second = _admit(deepcopy(candidate))
    changed = _admit(
        _candidate(
            PROJECT_CREATE,
            selector=None,
            project_code="PROJECT-OTHER",
            project_name="다른 프로젝트",
        )
    )

    first_args = first["authoritative_binding"]["arguments"]
    assert first_args == second["authoritative_binding"]["arguments"]
    assert first_args["project_id"] != changed["authoritative_binding"]["arguments"][
        "project_id"
    ]


def test_model_supplied_stable_authority_field_is_rejected_before_binding() -> None:
    candidate = _candidate(PROJECT_GET)
    candidate["parameter_candidates"] = [
        {"name": "project_id", "value": PROJECT_ID, "confidence": 1.0}
    ]

    with pytest.raises(IntentCandidateStageError, match="authority"):
        _admit(candidate)


@pytest.mark.parametrize(
    ("candidate", "failure_code", "directive"),
    (
        (
            _candidate(
                PROJECT_CREATE,
                selector=None,
                project_code="bad code",
                project_name="잘못된 코드",
            ),
            "PROJECT_CODE_INVALID",
            "CLARIFICATION_REQUIRED",
        ),
        (
            _candidate(
                PROJECT_CREATE,
                selector=None,
                project_code="PROJECT-A",
                project_name="중복 프로젝트",
            ),
            "PROJECT_CODE_CONFLICT",
            "BLOCKED",
        ),
        (
            _candidate(
                PROJECT_CREATE,
                selector=None,
                project_code="PROJECT-NEW",
                project_name="잘못된 통화",
                currency="KR",
            ),
            "PROJECT_CURRENCY_INVALID",
            "CLARIFICATION_REQUIRED",
        ),
        (
            _candidate(
                PROJECT_CREATE,
                selector=None,
                project_code="PROJECT-NEW",
                project_name="소유자 없음",
                initial_owner_employee_id="EMP-404",
            ),
            "EMPLOYEE_REFERENCE_NOT_FOUND",
            "CLARIFICATION_REQUIRED",
        ),
        (
            _candidate(PROJECT_GET, selector="PROJECT-404"),
            "PROJECT_CANDIDATE_NOT_FOUND",
            "CLARIFICATION_REQUIRED",
        ),
        (
            _candidate(MEMBERSHIP_ADD, member_role="MEMBER"),
            "EMPLOYEE_REFERENCE_REQUIRED",
            "CLARIFICATION_REQUIRED",
        ),
        (
            _candidate(
                MEMBERSHIP_REMOVE,
                employee_id="EMP-404",
            ),
            "EMPLOYEE_REFERENCE_NOT_FOUND",
            "CLARIFICATION_REQUIRED",
        ),
    ),
)
def test_authoritative_resolution_failures_stop_before_execution(
    candidate: dict, failure_code: str, directive: str
) -> None:
    result = _admit(candidate)

    assert (result["directive"], result["failure_code"]) == (
        directive,
        failure_code,
    )
    assert result["authoritative_binding"] is None


@pytest.mark.parametrize(
    "candidate",
    (
        _candidate(PROJECT_LIST, selector=None, limit=0),
        _candidate(PROJECT_LIST, selector=None, limit=101),
        _candidate(PROJECT_LIST, selector=None, offset=-1),
    ),
)
def test_invalid_pagination_fails_closed(candidate: dict) -> None:
    with pytest.raises(ProjectOperationPlanningError) as raised:
        _admit(candidate)

    assert raised.value.error_code == "P8_PROJECT_PAGE_INVALID"


def test_invalid_authoritative_inputs_fail_closed() -> None:
    with pytest.raises(ProjectOperationPlanningError) as tenant_error:
        _admit(_candidate(PROJECT_LIST, selector=None), tenant_id=" ")
    assert str(tenant_error.value) == "tenant_id must be bounded text."

    with pytest.raises(ProjectOperationPlanningError) as records_error:
        _admit(_candidate(PROJECT_LIST, selector=None), projects="not-a-record-set")
    assert records_error.value.error_code == "P8_PROJECT_AUTHORITY_INVALID"

    invalid_version = _projects()
    invalid_version[0]["entity_version"] = 0
    with pytest.raises(ProjectOperationPlanningError) as version_error:
        _admit(
            _candidate(PROJECT_DEACTIVATE),
            projects=invalid_version,
        )
    assert version_error.value.error_code == "P8_PROJECT_AUTHORITY_INVALID"


def test_unsupported_operation_is_rejected_after_candidate_validation() -> None:
    with pytest.raises(ProjectOperationPlanningError) as raised:
        _admit(_candidate("PROJECT.PROJECT.ARCHIVE"))

    assert raised.value.error_code == "P8_PROJECT_OPERATION_UNSUPPORTED"


def test_capability_snapshot_binds_all_seven_exact_artifacts() -> None:
    read = _load(READ_ADMISSION)
    write = _load(WRITE_ADMISSION)
    capabilities = build_project_operation_capabilities(
        read_admission=read,
        write_admission=write,
    )
    snapshot = build_project_operation_capability_snapshot(
        tenant_id=TENANT,
        read_admission=read,
        write_admission=write,
        capability_snapshot_id="a1000000-0000-4000-8000-000000000100",
        snapshot_version=100,
        created_at="2026-10-25T12:00:00Z",
        baseline_capabilities=(),
    )

    assert {item["capability_id"] for item in capabilities} == PROJECT_OPERATIONS
    assert {item["capability_id"] for item in snapshot["capabilities"]} == PROJECT_OPERATIONS
    assert all(
        item["local_skill_binding"]["backend_profile"] == "NSL_V02_IN_PROCESS"
        for item in capabilities
    )


def test_admitted_binding_activates_intact_work_intent() -> None:
    candidate = _candidate(MEMBERSHIP_REMOVE, employee_id="EMP-2002")
    decision = resolve_validated_intent_candidate(candidate)
    work_intent = build_work_intent_from_decision(
        execution_id="a1000000-0000-4000-8000-000000000101",
        source_ref="interaction:a100",
        actor_ref=f"oa.user:{REQUESTER}",
        received_at="2026-10-25T12:00:00Z",
        intent_decision=decision,
        input_context_hash="sha256:" + "a" * 64,
        prompt_provenance={
            "prompt_binding_key": "AE_INTENT_RESOLUTION_V1",
            "prompt_template_version_id": "a1000000-0000-4000-8000-000000000102",
            "prompt_content_sha256": "a" * 64,
            "rendered_prompt_hash": "b" * 64,
            "model_profile": "general-llm-default",
            "model_ref": "model-test",
        },
        work_intent_id="a1000000-0000-4000-8000-000000000103",
    )
    admission = _admit(candidate)

    activated = activate_project_operation_work_intent(
        work_intent, admission=admission
    )

    assert activated["intent_label"] == MEMBERSHIP_REMOVE
    assert activated["required_capability_hints"] == [MEMBERSHIP_REMOVE]
    assert activated["clarification"]["status"] == "NOT_REQUIRED"
    assert activated["intent_hash"] == semantic_sha256_hash_ref(
        {key: value for key, value in activated.items() if key != "intent_hash"}
    )


def test_tampered_admission_and_incomplete_artifact_set_fail_closed() -> None:
    admission = _admit(_candidate(PROJECT_GET))
    tampered = deepcopy(admission)
    tampered["authoritative_binding"]["arguments"]["project_id"] = "tampered"
    with pytest.raises(ProjectOperationPlanningError) as raised:
        activate_project_operation_work_intent(
            build_work_intent_from_decision(
                execution_id="a1000000-0000-4000-8000-000000000110",
                source_ref="interaction:a110",
                actor_ref=f"oa.user:{REQUESTER}",
                received_at="2026-10-25T12:00:00Z",
                intent_decision=resolve_validated_intent_candidate(
                    _candidate(PROJECT_GET)
                ),
                input_context_hash="sha256:" + "c" * 64,
                prompt_provenance=None,
            ),
            admission=tampered,
        )
    assert raised.value.error_code == "P8_PROJECT_ADMISSION_INVALID"

    write = _load(WRITE_ADMISSION)
    write["skills"].pop()
    with pytest.raises(ProjectOperationPlanningError) as raised:
        build_project_operation_capabilities(
            read_admission=_load(READ_ADMISSION), write_admission=write
        )
    assert raised.value.error_code == "P8_PROJECT_ARTIFACT_ADMISSION_INVALID"


@pytest.mark.parametrize(
    "mutation",
    (
        "status",
        "entry_type",
        "duplicate",
        "digest",
        "version",
        "unsupported_identity",
    ),
)
def test_malformed_artifact_admissions_fail_closed(mutation: str) -> None:
    read = _load(READ_ADMISSION)
    write = _load(WRITE_ADMISSION)
    if mutation == "status":
        read["status"] = "FAIL"
    elif mutation == "entry_type":
        read["skills"][0] = "not-an-artifact"
    elif mutation == "duplicate":
        read["skills"].append(deepcopy(read["skills"][0]))
    elif mutation == "digest":
        read["skills"][0]["semantic_hash"] = "sha256:not-a-digest"
    elif mutation == "version":
        read["skills"][0]["skill_version"] = "2.0.0"
    else:
        read["skills"].append(
            {
                **deepcopy(read["skills"][0]),
                "skill_id": "PROJECT.PROJECT.UNSUPPORTED",
            }
        )

    with pytest.raises(ProjectOperationPlanningError) as raised:
        build_project_operation_capabilities(
            read_admission=read,
            write_admission=write,
        )

    assert raised.value.error_code == "P8_PROJECT_ARTIFACT_ADMISSION_INVALID"


def test_work_intent_and_admission_must_both_be_executable_and_intact() -> None:
    candidate = _candidate(PROJECT_GET)
    decision = resolve_validated_intent_candidate(candidate)
    work_intent = build_work_intent_from_decision(
        execution_id="a1000000-0000-4000-8000-000000000120",
        source_ref="interaction:a120",
        actor_ref=f"oa.user:{REQUESTER}",
        received_at="2026-10-25T12:00:00Z",
        intent_decision=decision,
        input_context_hash="sha256:" + "d" * 64,
        prompt_provenance=None,
    )

    tampered_intent = deepcopy(work_intent)
    tampered_intent["goal"] = "tampered"
    with pytest.raises(ProjectOperationPlanningError) as raised:
        activate_project_operation_work_intent(
            tampered_intent,
            admission=_admit(candidate),
        )
    assert raised.value.error_code == "P8_PROJECT_WORK_INTENT_INVALID"

    stopped_admission = _admit(_candidate(PROJECT_GET, selector="PROJECT-404"))
    with pytest.raises(ProjectOperationPlanningError) as raised:
        activate_project_operation_work_intent(
            work_intent,
            admission=stopped_admission,
        )
    assert raised.value.error_code == "P8_PROJECT_ADMISSION_INVALID"
