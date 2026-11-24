"""Provider-neutral binding of SourcePool and approved AllocationPlan authority."""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from typing import Any

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref, validate_hash_ref

from ..integrations.nex_allocation_plan_client import AllocationPlanProviderRequest

APPROVED_ALLOCATION_PLAN_AUTHORITY_SCHEMA = (
    "mybee.approved_allocation_plan_authority.v1"
)
INDEPENDENT_ALLOCATION_PLAN_AUTHORITY_SCHEMA = (
    "mybee.approved_allocation_plan_authority.v2"
)
APPROVED_ALLOCATION_PLAN_AUTHORITY_STAGE = "READY_FOR_ALLOCATION"

_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,255}$")
_PROJECT_CODE = re.compile(r"^[A-Z0-9]{4}[DMSOIG][0-9]{6}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_AMOUNT = re.compile(r"^-?[0-9]+\.[0-9]{4}$")
_SOURCE_KINDS = frozenset(
    {
        "PAYROLL",
        "PURCHASE",
        "SERVICE",
        "SHARED_EXPENSE",
        "REVENUE",
        "FX_GAIN_LOSS",
        "OTHER",
    }
)
_SOURCE_POOL_FIELDS = frozenset(
    {
        "schema_version",
        "operation",
        "idempotency_disposition",
        "tenant_id",
        "company_id",
        "pool_id",
        "journal_id",
        "journal_line_no",
        "eligible_component_id",
        "source_business_operation_id",
        "source_project_id",
        "source_project_code",
        "source_kind",
        "allocation_mode",
        "source_amount_functional",
        "eligible_amount_functional",
        "functional_currency",
        "account_id",
        "account_category",
        "monetary_class",
        "recognition_date",
        "recognized_at",
        "period_id",
        "source_record_ref",
        "source_hash",
        "eligibility_policy_hash",
        "pool_state",
        "source_journal_hash",
        "created_at",
    }
)
_CHECKPOINT_FIELDS = frozenset(
    {
        "schema_version",
        "stage",
        "tenant_id",
        "company_id",
        "business_context_hash",
        "preparation_hash",
        "source_pool",
        "allocation_plan",
        "authority_binding_hash",
        "checkpoint_hash",
    }
)
_INDEPENDENT_CHECKPOINT_FIELDS = frozenset(
    {
        "schema_version",
        "stage",
        "tenant_id",
        "company_id",
        "business_context_hash",
        "allocation_authority_hash",
        "source_pool",
        "allocation_plan",
        "authority_binding_hash",
        "checkpoint_hash",
    }
)


class ApprovedAllocationPlanAuthorityError(RuntimeError):
    def __init__(self, error_code: str, detail: str) -> None:
        self.error_code = error_code
        self.detail = detail
        super().__init__(detail)


@dataclass(frozen=True)
class AllocationAuthorityLineage:
    business_context_hash: str
    preparation_hash: str | None = None
    allocation_authority_hash: str | None = None


class ApprovedAllocationPlanAuthorityBinder:
    """Binds exact resolver evidence without knowing an Agent or scenario."""

    def bind(
        self,
        *,
        request: AllocationPlanProviderRequest,
        resolution: Mapping[str, Any],
        source_pool: Mapping[str, Any],
        lineage: AllocationAuthorityLineage,
        existing_checkpoint: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        context_hash = _hash("business_context_hash", lineage.business_context_hash)
        lineage_field, lineage_hash = _lineage(lineage)
        pool = _source_pool(source_pool, request=request)
        plan = _allocation_plan(resolution, request=request)
        pool_hash = semantic_sha256_hash_ref(dict(pool))
        binding = {
            "tenant_id": request.tenant_id,
            "company_id": request.company_id,
            "business_context_hash": context_hash,
            lineage_field: lineage_hash,
            "source_pool_hash": pool_hash,
            "source_pool_source_hash": pool["source_hash"],
            "source_journal_hash": pool["source_journal_hash"],
            "selector_hash": plan["selector_hash"],
            "resolution_hash": plan["resolution_hash"],
            "plan_id": plan["plan_id"],
            "plan_revision": plan["plan_revision"],
            "plan_hash": plan["plan_hash"],
        }
        independent = lineage_field == "allocation_authority_hash"
        allocation_plan = {
            "plan_id": plan["plan_id"],
            "plan_revision": plan["plan_revision"],
            "plan_hash": plan["plan_hash"],
            "approved_proof": plan["approved_proof"],
            "selector_hash": plan["selector_hash"],
            "resolution_hash": plan["resolution_hash"],
        }
        if independent:
            allocation_plan["project_refs"] = _project_refs(plan)
        semantics = {
            "schema_version": (
                INDEPENDENT_ALLOCATION_PLAN_AUTHORITY_SCHEMA
                if independent
                else APPROVED_ALLOCATION_PLAN_AUTHORITY_SCHEMA
            ),
            "stage": APPROVED_ALLOCATION_PLAN_AUTHORITY_STAGE,
            "tenant_id": request.tenant_id,
            "company_id": request.company_id,
            "business_context_hash": context_hash,
            lineage_field: lineage_hash,
            "source_pool": {
                "pool_id": pool["pool_id"],
                "journal_id": pool["journal_id"],
                "journal_line_no": pool["journal_line_no"],
                "source_kind": pool["source_kind"],
                "recognition_date": pool["recognition_date"],
                "source_hash": pool["source_hash"],
                "source_journal_hash": pool["source_journal_hash"],
                "source_pool_hash": pool_hash,
            },
            "allocation_plan": allocation_plan,
            "authority_binding_hash": semantic_sha256_hash_ref(binding),
        }
        checkpoint = {
            **semantics,
            "checkpoint_hash": semantic_sha256_hash_ref(semantics),
        }
        if existing_checkpoint is not None:
            existing = _checkpoint(existing_checkpoint)
            if existing != checkpoint:
                raise _error(
                    "ALLOCATION_PLAN_AUTHORITY_REPLAY_CONFLICT",
                    "Existing allocation authority differs from the exact replay.",
                )
            return existing_checkpoint
        return _freeze_checkpoint(checkpoint)


def _source_pool(
    value: object, *, request: AllocationPlanProviderRequest
) -> dict[str, Any]:
    pool = _exact_mapping("source_pool", value, _SOURCE_POOL_FIELDS)
    if (
        pool.get("schema_version") != "eos_cost_source_pool.v1"
        or pool.get("operation")
        not in {"FINANCE.COST_SOURCE_POOL.ADMIT", "FINANCE.COST_SOURCE_POOL.GET"}
        or pool.get("idempotency_disposition") not in {"CREATED", "EXACT_REPLAY"}
        or pool.get("tenant_id") != request.tenant_id
        or pool.get("company_id") != request.company_id
        or pool.get("source_kind") != request.body["source_kind"]
        or pool.get("allocation_mode") != "MANAGEMENT_ALLOCATION"
        or pool.get("recognition_date") != request.body["effective_on"]
        or pool.get("pool_state") != "OPEN"
    ):
        raise _invalid("SourcePool identity, state, or selector lineage drifted.")
    for name in (
        "company_id",
        "pool_id",
        "journal_id",
        "source_business_operation_id",
        "source_project_id",
        "account_id",
        "period_id",
    ):
        _uuid(name, pool[name])
    _positive_int("journal_line_no", pool["journal_line_no"])
    _text("eligible_component_id", pool["eligible_component_id"], 128)
    _pattern("source_project_code", pool["source_project_code"], _PROJECT_CODE)
    _choice("source_kind", pool["source_kind"], _SOURCE_KINDS)
    _amount("source_amount_functional", pool["source_amount_functional"])
    _amount("eligible_amount_functional", pool["eligible_amount_functional"])
    _pattern("functional_currency", pool["functional_currency"], _CURRENCY)
    _choice("account_category", pool["account_category"], {"EXPENSE", "REVENUE"})
    _choice("monetary_class", pool["monetary_class"], {"MONETARY", "NON_MONETARY"})
    _date("recognition_date", pool["recognition_date"])
    for name in ("recognized_at", "created_at"):
        _timestamp(name, pool[name])
    _text("source_record_ref", pool["source_record_ref"], 256)
    for name in (
        "source_hash",
        "eligibility_policy_hash",
        "source_journal_hash",
    ):
        _hash(name, pool[name])
    return pool


def _allocation_plan(
    value: object, *, request: AllocationPlanProviderRequest
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid("AllocationPlan resolution must be an object.")
    plan = dict(value)
    if (
        plan.get("schema_version")
        not in {
            "eos_cost_allocation_plan_resolution.v1",
            "eos_cost_allocation_plan_resolution.v2",
        }
        or plan.get("operation") != "FINANCE.COST_ALLOCATION_PLAN.RESOLVE"
        or plan.get("resolution_disposition") != "EXACT_MATCH"
        or plan.get("tenant_id") != request.tenant_id
        or plan.get("company_id") != request.company_id
        or plan.get("source_kind") != request.body["source_kind"]
        or plan.get("scope_type") != "PROJECT_SET"
        or plan.get("state") != "APPROVED"
    ):
        raise _invalid("AllocationPlan resolution authority drifted.")
    _uuid("plan_id", plan.get("plan_id"))
    _positive_int("plan_revision", plan.get("plan_revision"))
    for name in ("plan_hash", "selector_hash", "resolution_hash"):
        _hash(name, plan.get(name))
    approved_proof = plan.get("approved_proof")
    if not isinstance(approved_proof, str) or not approved_proof.startswith(
        "eos.approval-proof:"
    ):
        raise _invalid("AllocationPlan approval proof is invalid.")
    return plan


def _checkpoint(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid("checkpoint fields are not canonical.")
    schema_version = value.get("schema_version")
    fields = (
        _INDEPENDENT_CHECKPOINT_FIELDS
        if schema_version == INDEPENDENT_ALLOCATION_PLAN_AUTHORITY_SCHEMA
        else _CHECKPOINT_FIELDS
    )
    checkpoint = _exact_mapping("checkpoint", value, fields)
    for field in ("source_pool", "allocation_plan"):
        nested = checkpoint.get(field)
        if not isinstance(nested, Mapping):
            raise _invalid(f"Existing allocation authority {field} is invalid.")
        checkpoint[field] = dict(nested)
    if (
        checkpoint.get("schema_version")
        not in {
            APPROVED_ALLOCATION_PLAN_AUTHORITY_SCHEMA,
            INDEPENDENT_ALLOCATION_PLAN_AUTHORITY_SCHEMA,
        }
        or checkpoint.get("stage") != APPROVED_ALLOCATION_PLAN_AUTHORITY_STAGE
    ):
        raise _invalid("Existing allocation authority checkpoint is invalid.")
    expected = semantic_sha256_hash_ref(
        {key: item for key, item in checkpoint.items() if key != "checkpoint_hash"}
    )
    if checkpoint.get("checkpoint_hash") != expected:
        raise _invalid("Existing allocation authority checkpoint hash drifted.")
    return checkpoint


def _lineage(lineage: AllocationAuthorityLineage) -> tuple[str, str]:
    values = (
        lineage.preparation_hash is not None,
        lineage.allocation_authority_hash is not None,
    )
    if values == (True, False):
        return "preparation_hash", _hash("preparation_hash", lineage.preparation_hash)
    if values == (False, True):
        return "allocation_authority_hash", _hash(
            "allocation_authority_hash", lineage.allocation_authority_hash
        )
    raise _invalid("Exactly one allocation lineage authority is required.")


def _project_refs(plan: Mapping[str, Any]) -> list[dict[str, Any]]:
    lines = plan.get("lines")
    if not isinstance(lines, (list, tuple)) or not lines:
        raise _invalid("AllocationPlan Project authority is unavailable.")
    refs: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_codes: set[str] = set()
    for line in lines:
        if not isinstance(line, Mapping):
            raise _invalid("AllocationPlan Project authority is invalid.")
        project_id = _uuid("project_id", line.get("project_id"))
        project_code = _pattern("project_code", line.get("project_code"), _PROJECT_CODE)
        if project_id in seen_ids or project_code in seen_codes:
            raise _invalid("AllocationPlan Project authority is duplicated.")
        seen_ids.add(project_id)
        seen_codes.add(project_code)
        refs.append(
            {
                "project_id": project_id,
                "project_code": project_code,
                "allocation_ratio": str(line.get("allocation_ratio")),
            }
        )
    return sorted(refs, key=lambda item: item["project_code"])


def _freeze_checkpoint(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(
        {
            **value,
            "source_pool": MappingProxyType(dict(value["source_pool"])),
            "allocation_plan": MappingProxyType(dict(value["allocation_plan"])),
        }
    )


def _exact_mapping(field: str, value: object, fields: frozenset[str]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise _invalid(f"{field} fields are not canonical.")
    return dict(value)


def _hash(field: str, value: object) -> str:
    try:
        return validate_hash_ref(value)
    except (TypeError, ValueError) as exc:
        raise _invalid(f"{field} is invalid.") from exc


def _uuid(field: str, value: object) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise _invalid(f"{field} is invalid.") from exc


def _positive_int(field: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise _invalid(f"{field} is invalid.")
    return value


def _text(field: str, value: object, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > maximum
    ):
        raise _invalid(f"{field} is invalid.")
    return value


def _pattern(field: str, value: object, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise _invalid(f"{field} is invalid.")
    return value


def _choice(field: str, value: object, allowed: set[str] | frozenset[str]) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise _invalid(f"{field} is invalid.")
    return value


def _amount(field: str, value: object) -> str:
    selected = _pattern(field, value, _AMOUNT)
    try:
        number = Decimal(selected)
    except InvalidOperation as exc:
        raise _invalid(f"{field} is invalid.") from exc
    if not number.is_finite():
        raise _invalid(f"{field} is invalid.")
    return selected


def _date(field: str, value: object) -> str:
    if not isinstance(value, str):
        raise _invalid(f"{field} is invalid.")
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise _invalid(f"{field} is invalid.") from exc


def _timestamp(field: str, value: object) -> str:
    if not isinstance(value, str):
        raise _invalid(f"{field} is invalid.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _invalid(f"{field} is invalid.") from exc
    if parsed.tzinfo is None:
        raise _invalid(f"{field} is invalid.")
    return value


def _invalid(detail: str) -> ApprovedAllocationPlanAuthorityError:
    return _error("ALLOCATION_PLAN_AUTHORITY_INVALID", detail)


def _error(error_code: str, detail: str) -> ApprovedAllocationPlanAuthorityError:
    return ApprovedAllocationPlanAuthorityError(error_code, detail)
