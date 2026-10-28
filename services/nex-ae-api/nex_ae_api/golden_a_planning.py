from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

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
from nex_ae_api.voucher_attachment_manifest import (
    bind_manifest_to_governed_payload,
    bind_manifest_to_work_intent,
)

GOLDEN_A_FIXTURE_SCHEMA_VERSION = "p8_golden_a_fixture.v1"
GOLDEN_A_PLANNING_SCHEMA_VERSION = "p8.golden_a_planning_activation.v1"
GOLDEN_A_AUTHORITY_PROFILE_SCHEMA_VERSION = (
    "ae.finance_golden_a_authority_profile.v1"
)
GOLDEN_A_PRODUCT_ACTIVATION_SCHEMA_VERSION = (
    "ae.finance_golden_a_activation.v1"
)
GOLDEN_A_CAPABILITY_ID = "FINANCE.CREATE_VOUCHER_DRAFT"
GOLDEN_A_NSL_SKILL_ID = "FINANCE.VOUCHER_DRAFT_CREATE"
GOLDEN_A_INPUT_CONTRACT = "contract://nex/eos/create-voucher-draft-command/v1"
GOLDEN_A_OUTPUT_CONTRACT = "contract://nex/eos/create-voucher-draft-result/v1"
GOLDEN_A_RUNTIME_CONTRACT = "contract://nex/nsl/write-runtime/v0.2"
GOLDEN_A_TRUST_POLICY = "policy://nex/ae/governed-write/golden-a/v1"
GOLDEN_A_WRITE_SCHEMA_VERSION = "eos_create_voucher_draft_command.v1"

_REQUIRED_PARAMETERS = (
    "amount",
    "currency",
    "transaction_date",
    "voucher_type",
    "economic_category",
    "settlement_method",
)


@dataclass(frozen=True)
class GoldenAPlanningError(ValueError):
    error_code: str
    detail: str

    def __str__(self) -> str:
        return self.detail


def build_golden_a_planning_capability(
    fixture: Mapping[str, Any],
) -> dict[str, Any]:
    record = _fixture_projection(fixture)
    return _build_golden_a_planning_capability(record["admission"])


def build_golden_a_product_capability(
    authority_profile: Mapping[str, Any],
) -> dict[str, Any]:
    record = _authority_profile_projection(authority_profile)
    return _build_golden_a_planning_capability(record["admission"])


def _build_golden_a_planning_capability(
    admission: Mapping[str, Any],
) -> dict[str, Any]:
    return build_local_skill_capability(
        skill_id=admission["skill_id"],
        capability_id=admission["capability_id"],
        exact_skill_version=admission["exact_skill_version"],
        skill_semantic_hash=admission["skill_semantic_hash"],
        input_contract_ref=GOLDEN_A_INPUT_CONTRACT,
        output_contract_ref=GOLDEN_A_OUTPUT_CONTRACT,
        runtime_contract_ref=GOLDEN_A_RUNTIME_CONTRACT,
        trust_policy_id=GOLDEN_A_TRUST_POLICY,
        backend_profile=admission["backend_profile"],
        operation_semantics="WRITE",
    )


def build_golden_a_capability_snapshot(
    fixture: Mapping[str, Any],
    *,
    capability_snapshot_id: str,
    snapshot_version: int,
    created_at: str,
    baseline_capabilities: Sequence[Mapping[str, Any]] = DEFAULT_P5_CAPABILITIES,
) -> dict[str, Any]:
    record = _fixture_projection(fixture)
    return build_capability_snapshot(
        tenant_id=record["tenant_id"],
        capability_snapshot_id=capability_snapshot_id,
        snapshot_version=snapshot_version,
        created_at=created_at,
        capabilities=(
            *baseline_capabilities,
            build_golden_a_planning_capability(fixture),
        ),
    )


def build_golden_a_canonical_write_payload(
    fixture: Mapping[str, Any],
    *,
    attachment_manifest: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve the model-independent Golden A Tool-contract payload."""

    record = _fixture_projection(fixture)
    scenario = record["scenario"]
    policy = record["voucher_line_policy"]
    evidence_ref = f"policy:{policy['policy_id']}"
    account_ids = (policy["debit_account_id"], policy["credit_account_id"])
    amounts = (scenario["amount"], f"-{scenario['amount']}")
    categories = (scenario["economic_category"], scenario["settlement_method"])
    descriptions = (
        "Golden A travel expense",
        "Golden A cash settlement",
    )
    payload = {
        "schema_version": GOLDEN_A_WRITE_SCHEMA_VERSION,
        "tenant_id": record["tenant_id"],
        "requester_ref": {
            "type": "oa.user",
            "id": scenario["requester_subject_id"],
        },
        "project_ref": {
            "type": "eos.project",
            "id": record["projects"][1]["project_id"],
        },
        "voucher_type": scenario["voucher_type"],
        "transaction_date": scenario["transaction_date"],
        "currency": scenario["currency"],
        "description_text": scenario["description"],
        "lines": [
            {
                "line_no": line_no,
                "account_ref": {"type": "eos.account", "id": account_id},
                "signed_amount": amount,
                "economic_category": category,
                "description": description,
                "evidence_refs": [evidence_ref],
            }
            for line_no, (account_id, amount, category, description) in enumerate(
                zip(account_ids, amounts, categories, descriptions, strict=True),
                start=1,
            )
        ],
        "attachments": list(scenario["attachments"]),
    }
    return (
        payload
        if attachment_manifest is None
        else bind_manifest_to_governed_payload(payload, attachment_manifest)
    )


def bind_golden_a_planning_candidate(
    *,
    fixture: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> dict[str, Any]:
    record = _fixture_projection(fixture)
    return _bind_golden_a_candidate(
        record=record,
        candidate=candidate,
        schema_version=GOLDEN_A_PLANNING_SCHEMA_VERSION,
        source_name="fixture_ref",
        source_ref=_fixture_ref(record),
        capability=_build_golden_a_planning_capability(record["admission"]),
    )


def bind_golden_a_product_candidate(
    *,
    authority_profile: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> dict[str, Any]:
    record = _authority_profile_projection(authority_profile)
    return _bind_golden_a_candidate(
        record=record,
        candidate=candidate,
        schema_version=GOLDEN_A_PRODUCT_ACTIVATION_SCHEMA_VERSION,
        source_name="authority_ref",
        source_ref=_authority_profile_ref(record),
        capability=_build_golden_a_planning_capability(record["admission"]),
    )


def _bind_golden_a_candidate(
    *,
    record: Mapping[str, Any],
    candidate: Mapping[str, Any],
    schema_version: str,
    source_name: str,
    source_ref: Mapping[str, str],
    capability: Mapping[str, Any],
) -> dict[str, Any]:
    normalized = parse_intent_candidate(canonical_json(dict(candidate)))
    candidate_hash = semantic_sha256_hash_ref(normalized)
    if normalized["intent_label"] != GOLDEN_A_CAPABILITY_ID:
        raise GoldenAPlanningError(
            "P8_GOLDEN_A_INTENT_UNSUPPORTED",
            "Golden A activation only admits the voucher-draft intent.",
        )

    reasons = list(normalized["clarification"]["reasons"])
    questions = list(normalized["clarification"]["questions"])
    failure_code: str | None = None
    if normalized["clarification"]["required"]:
        failure_code = "MODEL_CLARIFICATION_REQUIRED"

    project, project_failure = _resolve_project_candidate(
        normalized["entity_selectors"], record["projects"]
    )
    if project_failure is not None:
        failure_code, reason, question = project_failure
        reasons.append(reason)
        questions.append(question)

    parameters = {item["name"]: item for item in normalized["parameter_candidates"]}
    parameter_failures = _parameter_failures(parameters, record["scenario"])
    if parameter_failures:
        failure_code = failure_code or "BUSINESS_INPUT_CLARIFICATION_REQUIRED"
        reasons.extend(parameter_failures)
        questions.append(
            "금액, 통화, 전표일자, 전표유형, 경제분류, 결제수단을 확인해 주세요."
        )

    if failure_code is not None:
        return _finish(
            {
                "schema_version": schema_version,
                "directive": "CLARIFICATION_REQUIRED",
                "failure_code": failure_code,
                "candidate_hash": candidate_hash,
                source_name: dict(source_ref),
                "clarification": {
                    "reasons": _unique(reasons),
                    "questions": _unique(questions),
                },
                "authoritative_binding": None,
            }
        )

    assert project is not None
    binding = _authoritative_binding(record, project, capability)
    return _finish(
        {
            "schema_version": schema_version,
            "directive": "CONTINUE",
            "failure_code": None,
            "candidate_hash": candidate_hash,
            source_name: dict(source_ref),
            "clarification": {"reasons": [], "questions": []},
            "authoritative_binding": binding,
        }
    )


def activate_golden_a_work_intent(
    work_intent: Mapping[str, Any],
    *,
    candidate: Mapping[str, Any],
    activation: Mapping[str, Any],
    attachment_manifest: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    record = deepcopy(dict(work_intent))
    expected = semantic_sha256_hash_ref(
        {key: value for key, value in record.items() if key != "intent_hash"}
    )
    if record.get("schema_version") != "1.1" or record.get("intent_hash") != expected:
        raise GoldenAPlanningError(
            "P8_GOLDEN_A_WORK_INTENT_INVALID",
            "Golden A activation requires an intact WorkIntent v1.1.",
        )
    if activation.get("directive") != "CONTINUE":
        raise GoldenAPlanningError(
            "P8_GOLDEN_A_BINDING_UNAVAILABLE",
            "Golden A WorkIntent cannot activate before deterministic binding.",
        )
    normalized = parse_intent_candidate(canonical_json(dict(candidate)))
    _require_activation_integrity(
        activation,
        candidate_hash=semantic_sha256_hash_ref(normalized),
    )
    binding = activation.get("authoritative_binding")
    capability_ref = (
        binding.get("capability_ref") if isinstance(binding, Mapping) else None
    )
    if (
        not isinstance(binding, Mapping)
        or not isinstance(capability_ref, Mapping)
        or capability_ref.get("capability_id") != GOLDEN_A_CAPABILITY_ID
        or capability_ref.get("skill_id") != GOLDEN_A_NSL_SKILL_ID
    ):
        raise GoldenAPlanningError(
            "P8_GOLDEN_A_BINDING_INVALID",
            "Golden A authoritative binding is invalid.",
        )
    project_code = binding.get("project_code")
    matching_selectors = [
        item for item in normalized["entity_selectors"] if item["value"] == project_code
    ]
    parameters = {item["name"]: item for item in normalized["parameter_candidates"]}
    if (
        not isinstance(project_code, str)
        or len(matching_selectors) != 1
        or not set(_REQUIRED_PARAMETERS).issubset(parameters)
    ):
        raise GoldenAPlanningError(
            "P8_GOLDEN_A_BINDING_INVALID",
            "Golden A authoritative binding does not match its candidate shape.",
        )
    project_selector = matching_selectors[0]
    record.update(
        {
            "intent_label": GOLDEN_A_CAPABILITY_ID,
            "goal": "Create a governed voucher draft after deterministic business binding.",
            "work_class": "DOCUMENT",
            "required_capability_hints": [GOLDEN_A_CAPABILITY_ID],
            "entity_selectors": [
                {
                    "selector_id": "E1",
                    "entity_type": "PROJECT",
                    "raw_text": project_code,
                    "attributes": {"authority": "MODEL_CANDIDATE_ONLY"},
                    "required": True,
                    "confidence": float(project_selector["confidence"]),
                }
            ],
            "parameter_candidates": [
                {
                    "name": name,
                    "value": parameters[name]["value"],
                    "value_type": _parameter_type(name),
                    "source": "MODEL_CANDIDATE",
                    "confidence": float(parameters[name]["confidence"]),
                }
                for name in _REQUIRED_PARAMETERS
            ],
            "constraints": [
                {
                    "constraint_type": "DETERMINISTIC_AUTHORITY",
                    "description": "Project, accounts, and voucher lines come from the protected Golden A binding.",
                },
                {
                    "constraint_type": "WRITE_GOVERNANCE",
                    "description": "Approval, idempotency, and EOS commit state remain outside LLM authority.",
                },
            ],
            "completion_criteria": [
                {
                    "criterion_id": "C1",
                    "description": "A governed voucher-draft result is produced.",
                    "required": True,
                    "result_contract_ref": GOLDEN_A_OUTPUT_CONTRACT,
                }
            ],
            "clarification": {"status": "NOT_REQUIRED", "reasons": [], "questions": []},
            "confidence": {
                **record["confidence"],
                "entities": float(project_selector["confidence"]),
                "parameters": min(
                    float(parameters[name]["confidence"])
                    for name in _REQUIRED_PARAMETERS
                ),
            },
        }
    )
    record["intent_hash"] = semantic_sha256_hash_ref(
        {key: value for key, value in record.items() if key != "intent_hash"}
    )
    return (
        record
        if attachment_manifest is None
        else bind_manifest_to_work_intent(record, attachment_manifest)
    )


def _fixture_projection(fixture: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(fixture, Mapping):
        raise _fixture_error("Golden A fixture must be an object.")
    record = deepcopy(dict(fixture))
    if record.get("schema_version") != GOLDEN_A_FIXTURE_SCHEMA_VERSION:
        raise _fixture_error("Golden A fixture schema version is unsupported.")
    supplied_hash = record.get("fixture_hash")
    try:
        validate_hash_ref(supplied_hash)
    except ValueError as exc:
        raise _fixture_error("Golden A fixture hash is invalid.") from exc
    hash_input = deepcopy(record)
    hash_input.pop("fixture_hash", None)
    if semantic_sha256_hash_ref(hash_input) != supplied_hash:
        raise _fixture_error("Golden A fixture hash does not match its content.")
    try:
        tenant_id = record["tenant"]["tenant_id"]
        projects = (record["projects"]["mother"], record["projects"]["child"])
        accounts = record["accounts"]
        policy = record["voucher_line_policy"]
        admission = record["admission"]
        scenario = record["scenario"]
    except (KeyError, TypeError) as exc:
        raise _fixture_error("Golden A fixture is missing planning data.") from exc
    if not _is_golden_a_admission(admission):
        raise _fixture_error("Golden A WRITE admission does not match P8-S64.")
    account_by_id = {item.get("account_id"): item for item in accounts}
    if len(account_by_id) != len(accounts) or not {
        policy.get("debit_account_id"),
        policy.get("credit_account_id"),
    }.issubset(account_by_id):
        raise _fixture_error("Golden A line policy account mapping is invalid.")
    if any(
        scenario.get(name) != policy.get(name)
        for name in (
            "currency",
            "voucher_type",
            "economic_category",
            "settlement_method",
        )
    ):
        raise _fixture_error("Golden A scenario does not match its line policy.")
    try:
        scenario_date = date.fromisoformat(scenario["transaction_date"])
        policy_date = date.fromisoformat(policy["effective_from"])
    except (TypeError, ValueError) as exc:
        raise _fixture_error("Golden A policy dates are invalid.") from exc
    if scenario_date < policy_date:
        raise _fixture_error("Golden A line policy is not yet effective.")
    return {
        "fixture_id": record["fixture_id"],
        "fixture_hash": supplied_hash,
        "tenant_id": tenant_id,
        "projects": tuple(projects),
        "accounts": account_by_id,
        "voucher_line_policy": policy,
        "admission": admission,
        "scenario": scenario,
    }


def _authority_profile_projection(
    authority_profile: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(authority_profile, Mapping):
        raise _profile_error("Golden A authority profile must be an object.")
    profile = deepcopy(dict(authority_profile))
    if profile.get("schema_version") != GOLDEN_A_AUTHORITY_PROFILE_SCHEMA_VERSION:
        raise _profile_error("Golden A authority profile version is unsupported.")
    supplied_hash = profile.get("profile_hash")
    try:
        validate_hash_ref(supplied_hash)
    except ValueError as exc:
        raise _profile_error("Golden A authority profile hash is invalid.") from exc
    hash_input = deepcopy(profile)
    hash_input.pop("profile_hash", None)
    if semantic_sha256_hash_ref(hash_input) != supplied_hash:
        raise _profile_error(
            "Golden A authority profile hash does not match its content."
        )
    try:
        profile_id = profile["profile_id"]
        profile_version = profile["profile_version"]
        tenant_id = profile["tenant_id"]
        principals = tuple(profile["authorized_principal_ids"])
        projects = tuple(profile["projects"])
        accounts = tuple(profile["accounts"])
        policy = profile["voucher_line_policy"]
        admission = profile["admission"]
        scenario = profile["protected_input"]
    except (KeyError, TypeError) as exc:
        raise _profile_error(
            "Golden A authority profile is missing product binding data."
        ) from exc
    if (
        not isinstance(profile_id, str)
        or not profile_id
        or not isinstance(profile_version, int)
        or profile_version < 1
        or not isinstance(tenant_id, str)
        or not tenant_id
        or not principals
        or any(not isinstance(item, str) or not item for item in principals)
        or len(set(principals)) != len(principals)
    ):
        raise _profile_error("Golden A authority profile identity is invalid.")
    project_ids = [item.get("project_id") for item in projects]
    project_codes = [item.get("project_code") for item in projects]
    if (
        not projects
        or any(not value for value in (*project_ids, *project_codes))
        or len(set(project_ids)) != len(project_ids)
        or len(set(project_codes)) != len(project_codes)
    ):
        raise _profile_error("Golden A project authority mapping is invalid.")
    account_by_id = {item.get("account_id"): item for item in accounts}
    if len(account_by_id) != len(accounts) or not {
        policy.get("debit_account_id"),
        policy.get("credit_account_id"),
    }.issubset(account_by_id):
        raise _profile_error("Golden A account authority mapping is invalid.")
    if not _is_golden_a_admission(admission):
        raise _profile_error("Golden A product admission is invalid.")
    if scenario.get("requester_subject_id") not in principals:
        raise _profile_error("Golden A protected requester is not authorized.")
    if any(
        scenario.get(name) != policy.get(name)
        for name in (
            "currency",
            "voucher_type",
            "economic_category",
            "settlement_method",
        )
    ):
        raise _profile_error("Golden A protected input does not match its policy.")
    try:
        scenario_date = date.fromisoformat(scenario["transaction_date"])
        policy_date = date.fromisoformat(policy["effective_from"])
    except (KeyError, TypeError, ValueError) as exc:
        raise _profile_error("Golden A authority dates are invalid.") from exc
    if scenario_date < policy_date:
        raise _profile_error("Golden A line policy is not yet effective.")
    return {
        "profile_id": profile_id,
        "profile_version": str(profile_version),
        "profile_hash": supplied_hash,
        "tenant_id": tenant_id,
        "authorized_principal_ids": principals,
        "projects": projects,
        "accounts": account_by_id,
        "voucher_line_policy": policy,
        "admission": admission,
        "scenario": scenario,
    }


def _is_golden_a_admission(admission: Mapping[str, Any]) -> bool:
    return (
        admission.get("activation_state") == "LOCKED_PENDING_P8_S64"
        and admission.get("skill_id") == GOLDEN_A_NSL_SKILL_ID
        and admission.get("capability_id") == GOLDEN_A_CAPABILITY_ID
        and admission.get("tool_id") == GOLDEN_A_CAPABILITY_ID
        and admission.get("executor_kind") == "LOCAL_SKILL"
        and admission.get("operation_semantics") == "WRITE"
        and admission.get("backend_profile") == NSL_V02_IN_PROCESS_BACKEND
    )


def _resolve_project_candidate(
    selectors: Sequence[Mapping[str, Any]], projects: Sequence[Mapping[str, Any]]
) -> tuple[Mapping[str, Any] | None, tuple[str, str, str] | None]:
    values = [(item["value"], item["confidence"]) for item in selectors]
    exact = [
        project
        for value, _confidence in values
        for project in projects
        if value == project.get("project_code")
    ]
    if len(exact) == 1:
        return exact[0], None
    if len(exact) > 1:
        return None, (
            "PROJECT_CANDIDATE_AMBIGUOUS",
            "Multiple exact project-code candidates were proposed.",
            "사용할 프로젝트 코드를 하나만 선택해 주세요.",
        )
    stable_ids = {project.get("project_id") for project in projects}
    if any(value in stable_ids for value, _confidence in values):
        return None, (
            "PROJECT_TRUSTED_SELECTION_REQUIRED",
            "A model-proposed stable ProjectRef cannot establish authority.",
            "신뢰된 프로젝트 선택 화면에서 프로젝트를 다시 선택해 주세요.",
        )
    names = {str(project.get("name", "")).casefold() for project in projects}
    if any(value.casefold() in names for value, _confidence in values):
        return None, (
            "PROJECT_CONFIRMATION_REQUIRED",
            "A project display-name match requires explicit confirmation.",
            "검색된 프로젝트의 정확한 코드를 확인해 주세요.",
        )
    return None, (
        "PROJECT_CANDIDATE_NOT_FOUND",
        "No tenant-scoped exact project code was proposed.",
        "정확한 프로젝트 코드를 입력해 주세요.",
    )


def _parameter_failures(
    candidates: Mapping[str, Mapping[str, Any]], scenario: Mapping[str, Any]
) -> list[str]:
    failures: list[str] = []
    for name in _REQUIRED_PARAMETERS:
        item = candidates.get(name)
        if item is None:
            failures.append(f"Required candidate parameter is missing: {name}.")
            continue
        if not _same_parameter(name, item["value"], scenario[name]):
            failures.append(
                f"Candidate parameter differs from protected input: {name}."
            )
    return failures


def _same_parameter(name: str, value: object, expected: object) -> bool:
    if name == "amount":
        try:
            return Decimal(str(value)) == Decimal(str(expected))
        except InvalidOperation:
            return False
    if name == "transaction_date":
        try:
            return date.fromisoformat(str(value)) == date.fromisoformat(str(expected))
        except ValueError:
            return False
    return str(value).upper() == str(expected).upper()


def _authoritative_binding(
    record: Mapping[str, Any],
    project: Mapping[str, Any],
    capability: Mapping[str, Any],
) -> dict[str, Any]:
    scenario = record["scenario"]
    policy = record["voucher_line_policy"]
    accounts = record["accounts"]
    amount = Decimal(str(scenario["amount"])).quantize(Decimal("0.01"))
    debit = accounts[policy["debit_account_id"]]
    credit = accounts[policy["credit_account_id"]]
    return {
        "capability_ref": {
            "capability_id": capability["capability_id"],
            "capability_version": capability["capability_version"],
            "skill_id": capability["local_skill_binding"]["skill_id"],
            "skill_version": capability["local_skill_binding"]["exact_skill_version"],
            "skill_semantic_hash": capability["local_skill_binding"][
                "skill_semantic_hash"
            ],
            "tool_id": record["admission"]["tool_id"],
            "executor_kind": capability["executor_kind"],
            "backend_profile": capability["local_skill_binding"]["backend_profile"],
        },
        "project_ref": {
            "system": "nex-eos",
            "resource_type": "PROJECT",
            "resource_id": project["project_id"],
            "version": "1",
        },
        "project_code": project["project_code"],
        "line_policy_ref": {
            "policy_id": policy["policy_id"],
            "policy_version": policy["policy_version"],
            "policy_hash": semantic_sha256_hash_ref(policy),
        },
        "voucher": {
            "amount": f"{amount:.2f}",
            "currency": scenario["currency"],
            "transaction_date": scenario["transaction_date"],
            "voucher_type": scenario["voucher_type"],
            "economic_category": scenario["economic_category"],
            "settlement_method": scenario["settlement_method"],
            "lines": [
                _line(1, "DEBIT", debit, amount, scenario["economic_category"]),
                _line(2, "CREDIT", credit, -amount, scenario["settlement_method"]),
            ],
        },
        "authority_sources": {
            "project_ref": "TENANT_EXACT_PROJECT_CODE",
            "account_refs": "VERSIONED_VOUCHER_LINE_POLICY",
            "voucher_lines": "VERSIONED_VOUCHER_LINE_POLICY",
            "business_values": "PROTECTED_GOLDEN_A_SCENARIO",
        },
    }


def _line(
    line_no: int,
    direction: str,
    account: Mapping[str, Any],
    amount: Decimal,
    economic_category: str,
) -> dict[str, Any]:
    return {
        "line_no": line_no,
        "direction": direction,
        "account_ref": {
            "system": "nex-eos",
            "resource_type": "ACCOUNT",
            "resource_id": account["account_id"],
            "version": "1",
        },
        "signed_amount": f"{amount:.2f}",
        "economic_category": economic_category,
    }


def _finish(value: dict[str, Any]) -> dict[str, Any]:
    value["activation_hash"] = semantic_sha256_hash_ref(value)
    return value


def _fixture_ref(record: Mapping[str, Any]) -> dict[str, str]:
    return {
        "fixture_id": record["fixture_id"],
        "fixture_hash": record["fixture_hash"],
        "tenant_id": record["tenant_id"],
    }


def _authority_profile_ref(record: Mapping[str, Any]) -> dict[str, str]:
    return {
        "profile_id": record["profile_id"],
        "profile_version": record["profile_version"],
        "profile_hash": record["profile_hash"],
        "tenant_id": record["tenant_id"],
    }


def _require_activation_integrity(
    activation: Mapping[str, Any], *, candidate_hash: str
) -> None:
    try:
        supplied_hash = validate_hash_ref(activation.get("activation_hash"))
    except (AttributeError, ValueError) as exc:
        raise GoldenAPlanningError(
            "P8_GOLDEN_A_ACTIVATION_INVALID",
            "Golden A activation hash is invalid.",
        ) from exc
    expected_hash = semantic_sha256_hash_ref(
        {key: value for key, value in activation.items() if key != "activation_hash"}
    )
    if (
        supplied_hash != expected_hash
        or activation.get("candidate_hash") != candidate_hash
    ):
        raise GoldenAPlanningError(
            "P8_GOLDEN_A_ACTIVATION_MISMATCH",
            "Golden A activation does not match its candidate or semantic content.",
        )


def _parameter_type(name: str) -> str:
    return {
        "amount": "MONEY",
        "transaction_date": "DATE",
        "currency": "ENUM",
        "voucher_type": "ENUM",
        "economic_category": "ENUM",
        "settlement_method": "ENUM",
    }[name]


def _unique(values: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(item for item in values if item))


def _fixture_error(detail: str) -> GoldenAPlanningError:
    return GoldenAPlanningError("P8_GOLDEN_A_FIXTURE_INVALID", detail)


def _profile_error(detail: str) -> GoldenAPlanningError:
    return GoldenAPlanningError("FINANCE_AUTHORITY_PROFILE_INVALID", detail)
