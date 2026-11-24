from __future__ import annotations

import re
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

from nex_ae_api.accounting_allocation_authority import (
    ACCOUNTING_ALLOCATION_OPERATION,
    build_accounting_allocation_work_intent,
)
from nex_ae_api.agent_context import TrustedContextResolution
from nex_ae_api.work_intent import validate_work_intent

ACCOUNTING_ALLOCATION_INTENT_PROFILE_VERSION = "accounting-allocation-domain-intent.v1"
ACCOUNTING_ALLOCATION_RESULT_CONTRACT = (
    "contract://nex/mybee/finance/accounting-allocation-result/v1"
)
ACCOUNTING_ALLOCATION_BINDING_FIELD = "accounting_allocation_work_intent"

_PROJECT_CODE = re.compile(r"^[A-Z0-9]{4}[DMSOIG][0-9]{6}$")
_PAIR_NAME = re.compile(r"^allocation_(project_code|ratio)_([1-9][0-9]*)$")
_BASE_PARAMETERS = frozenset(
    {"company_id", "journal_id", "source_record_line_ref", "source_kind"}
)


@dataclass(frozen=True)
class AccountingAllocationIntentActivationError(ValueError):
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class AccountingAllocationIntentActivationResult:
    work_intent: Mapping[str, Any] = field(repr=False)
    context_resolver: Any = field(repr=False)


@dataclass(frozen=True)
class AccountingAllocationIntentActivationProfile:
    capability_id: str = ACCOUNTING_ALLOCATION_OPERATION
    profile_version: str = ACCOUNTING_ALLOCATION_INTENT_PROFILE_VERSION
    result_contract_ref: str = ACCOUNTING_ALLOCATION_RESULT_CONTRACT

    @property
    def source_identity(self) -> str:
        return "nex-ae:accounting-allocation-domain-intent:" + semantic_sha256_hash_ref(
            {
                "capability_id": self.capability_id,
                "profile_version": self.profile_version,
                "result_contract_ref": self.result_contract_ref,
            }
        )


@dataclass(frozen=True)
class AccountingAllocationIntentActivator:
    profile: AccountingAllocationIntentActivationProfile = field(
        default_factory=AccountingAllocationIntentActivationProfile
    )

    def activate(
        self,
        *,
        candidate: Mapping[str, Any],
        work_intent: Mapping[str, Any],
        tenant_id: str,
        principal_id: str,
        resolved_at: str,
    ) -> AccountingAllocationIntentActivationResult:
        if work_intent.get("intent_label") != self.profile.capability_id:
            raise _invalid("Allocation capability does not match WorkIntent.")
        validated = validate_work_intent(work_intent)
        source = validated.get("source")
        if not isinstance(source, Mapping):
            raise _invalid("Allocation WorkIntent source is unavailable.")
        parameters, projects = _candidate_parameters(candidate)
        allocation = build_accounting_allocation_work_intent(
            tenant_id=tenant_id,
            company_id=parameters["company_id"],
            subject_id=principal_id,
            execution_id=str(validated["execution_id"]),
            work_intent_id=str(validated["work_intent_id"]),
            journal_id=parameters["journal_id"],
            source_record_line_ref=parameters["source_record_line_ref"],
            source_kind=parameters["source_kind"],
            projects=projects,
            source_ref=str(source["source_ref"]),
            requested_at=str(source["received_at"]),
            publication_target=(
                "IA_WORKSPACE"
                if source.get("source_type") == "PROMPT"
                else "ACCOUNTING_WORKSPACE"
            ),
            publication_target_ref=str(source["source_ref"]),
        )
        activated = _activate_common_work_intent(
            validated,
            allocation_work_intent=allocation,
            parameters=candidate.get("parameter_candidates"),
            profile=self.profile,
        )
        return AccountingAllocationIntentActivationResult(
            work_intent=activated,
            context_resolver=AccountingAllocationContextResolver(
                tenant_id=tenant_id,
                principal_id=principal_id,
                project_ref=activated.get("project_ref"),
                allocation_intent_hash=str(allocation["intent_hash"]),
                source_ref=str(source["source_ref"]),
                resolved_at=resolved_at,
            ),
        )


@dataclass(frozen=True)
class AccountingAllocationContextResolver:
    tenant_id: str
    principal_id: str
    project_ref: Mapping[str, Any] | None = field(repr=False)
    allocation_intent_hash: str
    source_ref: str
    resolved_at: str

    def resolve(self, request: Any) -> TrustedContextResolution:
        if request is not None and (
            request.tenant_id != self.tenant_id
            or request.principal_id != self.principal_id
            or request.agent_type not in {"IA", "CA", "PA", "EA"}
            or (request.agent_type == "IA" and request.source_type != "IA_PROMPT")
            or (
                request.agent_type != "IA" and request.source_type != "CLAIMED_WORKITEM"
            )
        ):
            raise AccountingAllocationIntentActivationError(
                "ACCOUNTING_ALLOCATION_CONTEXT_SCOPE_MISMATCH",
                "Allocation context scope does not match the execution.",
            )
        project_ref = (
            None if request is None or request.agent_type == "IA" else self.project_ref
        )
        if request is not None and request.agent_type != "IA" and project_ref is None:
            raise _invalid("Background allocation context requires Project scope.")
        return TrustedContextResolution(
            project_ref=project_ref,
            authority_ref=None,
            resolved_entities=(),
            retrieval_refs=(),
            evidence_refs=(),
            conflicts=(),
            degradations=(),
            context_manifest=(
                {
                    "kind": "ACCOUNTING_ALLOCATION_INTENT",
                    "source_ref": self.source_ref,
                    "source_version": ACCOUNTING_ALLOCATION_INTENT_PROFILE_VERSION,
                    "content_hash": self.allocation_intent_hash,
                    "as_of": self.resolved_at,
                },
            ),
            budget_tokens=1024,
            estimated_used_tokens=128,
        )


def _candidate_parameters(
    candidate: Mapping[str, Any],
) -> tuple[dict[str, str], tuple[dict[str, str], ...]]:
    values = candidate.get("parameter_candidates")
    if not isinstance(values, list):
        raise _invalid("Allocation parameter candidates are unavailable.")
    parameters: dict[str, str] = {}
    confidences: dict[str, float] = {}
    for item in values:
        if not isinstance(item, Mapping) or not isinstance(item.get("name"), str):
            raise _invalid("Allocation parameter candidate is malformed.")
        name = str(item["name"])
        if name not in _BASE_PARAMETERS and _PAIR_NAME.fullmatch(name) is None:
            raise _invalid("Allocation candidate contains an unsupported parameter.")
        if name in parameters:
            raise _invalid("Allocation candidate parameter is duplicated.")
        value = item.get("value")
        confidence = item.get("confidence")
        if (
            not isinstance(value, str)
            or not value.strip()
            or value != value.strip()
            or isinstance(confidence, bool)
            or not isinstance(confidence, (int, float))
            or not 0.0 <= float(confidence) <= 1.0
        ):
            raise _invalid("Allocation candidate parameter value is invalid.")
        parameters[name] = value
        confidences[name] = float(confidence)
    if not _BASE_PARAMETERS.issubset(parameters):
        raise AccountingAllocationIntentActivationError(
            "ACCOUNTING_ALLOCATION_CLARIFICATION_REQUIRED",
            "Allocation requires company, Journal, source line, and source kind.",
        )
    _uuid("company_id", parameters["company_id"])
    _uuid("journal_id", parameters["journal_id"])
    projects = _projects(parameters)
    return parameters, projects


def _projects(parameters: Mapping[str, str]) -> tuple[dict[str, str], ...]:
    indexed: dict[int, dict[str, str]] = {}
    for name, value in parameters.items():
        match = _PAIR_NAME.fullmatch(name)
        if match is None:
            continue
        field_name, raw_index = match.groups()
        indexed.setdefault(int(raw_index), {})[field_name] = value
    if not indexed or set(indexed) != set(range(1, len(indexed) + 1)):
        raise AccountingAllocationIntentActivationError(
            "ACCOUNTING_ALLOCATION_CLARIFICATION_REQUIRED",
            "Allocation Project and ratio candidates must use contiguous indexes.",
        )
    result: list[dict[str, str]] = []
    project_codes: set[str] = set()
    total = Decimal(0)
    for index in range(1, len(indexed) + 1):
        pair = indexed[index]
        if set(pair) != {"project_code", "ratio"}:
            raise AccountingAllocationIntentActivationError(
                "ACCOUNTING_ALLOCATION_CLARIFICATION_REQUIRED",
                "Every allocation Project requires one matching ratio.",
            )
        project_code = pair["project_code"].upper()
        if (
            _PROJECT_CODE.fullmatch(project_code) is None
            or project_code in project_codes
        ):
            raise _invalid(
                "Allocation Project candidates must be unique canonical codes."
            )
        try:
            ratio = Decimal(pair["ratio"])
        except InvalidOperation as exc:
            raise _invalid("Allocation ratio candidate is invalid.") from exc
        if not ratio.is_finite() or ratio <= 0:
            raise _invalid("Allocation ratio candidate must be positive.")
        project_codes.add(project_code)
        total += ratio
        result.append(
            {
                "project_code": project_code,
                "allocation_ratio": format(ratio, "f"),
            }
        )
    if total != Decimal(1):
        raise _invalid("Allocation ratio candidates must total exactly one.")
    return tuple(result)


def _activate_common_work_intent(
    work_intent: Mapping[str, Any],
    *,
    allocation_work_intent: Mapping[str, Any],
    parameters: object,
    profile: AccountingAllocationIntentActivationProfile,
) -> dict[str, Any]:
    record = deepcopy(dict(work_intent))
    record.update(
        {
            "intent_label": profile.capability_id,
            "goal": "Allocate an authorized posted accounting source to Projects.",
            "work_class": "BUSINESS_TRANSACTION",
            "required_capability_hints": [profile.capability_id],
            "parameter_candidates": deepcopy(parameters)
            if isinstance(parameters, list)
            else [],
            "constraints": [
                {
                    "constraint_type": "INDEPENDENT_ACCOUNTING_AUTHORITY",
                    "description": (
                        "Resolve fresh OA and EOS authority before allocation."
                    ),
                }
            ],
            "completion_criteria": [
                {
                    "criterion_id": "C1",
                    "description": "Allocation and Project P&L refresh are published.",
                    "required": True,
                    "result_contract_ref": profile.result_contract_ref,
                }
            ],
            "clarification": {
                "status": "NOT_REQUIRED",
                "reasons": [],
                "questions": [],
            },
            ACCOUNTING_ALLOCATION_BINDING_FIELD: _thaw(allocation_work_intent),
        }
    )
    record["intent_hash"] = semantic_sha256_hash_ref(
        {key: value for key, value in record.items() if key != "intent_hash"}
    )
    return validate_work_intent(record)


def _uuid(field_name: str, value: str) -> str:
    try:
        parsed = str(UUID(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise _invalid(f"Allocation {field_name} must be a canonical UUID.") from exc
    if parsed != value:
        raise _invalid(f"Allocation {field_name} must be a canonical UUID.")
    return parsed


def _thaw(value: object) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_thaw(item) for item in value]
    return value


def _invalid(detail: str) -> AccountingAllocationIntentActivationError:
    return AccountingAllocationIntentActivationError(
        "ACCOUNTING_ALLOCATION_INTENT_INVALID", detail
    )


__all__ = [
    "ACCOUNTING_ALLOCATION_BINDING_FIELD",
    "ACCOUNTING_ALLOCATION_INTENT_PROFILE_VERSION",
    "AccountingAllocationIntentActivationError",
    "AccountingAllocationIntentActivationProfile",
    "AccountingAllocationIntentActivationResult",
    "AccountingAllocationIntentActivator",
]
