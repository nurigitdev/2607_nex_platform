"""Thin M1 mapping into the generic installed allocation authority boundary."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any

from mybee_ax.orchestration import AllocationAuthorityLineage
from nex_runtime.business_context import (
    BusinessContextValidationError,
    validate_business_request_context,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

from nex_ae_api.allocation_plan_resolution_runtime import (
    InstalledApprovedAllocationPlanResolution,
)

_PREPARATION_FIELDS = frozenset(
    {
        "schema_version",
        "stage",
        "business_context_hash",
        "authority_hash",
        "authority",
        "adapter_identity",
        "identities",
        "references",
        "preparation_hash",
    }
)


class M1AllocationPlanCompositionError(RuntimeError):
    pass


def resolve_m1_allocation_plan_authority(
    runtime: InstalledApprovedAllocationPlanResolution,
    *,
    work_intent: Mapping[str, Any],
    preparation_checkpoint: Mapping[str, Any],
    source_pool: Mapping[str, Any],
    correlation_id: str,
    existing_checkpoint: Mapping[str, Any] | None = None,
) -> Mapping[str, Any]:
    context = _work_intent_context(work_intent)
    preparation = _preparation(
        preparation_checkpoint, context_hash=context["context_hash"]
    )
    authority = preparation["authority"]
    projects = _projects(
        context.get("requested_allocation"), authority.get("project_refs")
    )
    source_kind = source_pool.get("source_kind")
    if not isinstance(source_kind, str):
        raise _invalid("SourcePool source kind is unavailable.")
    return runtime.resolve_and_bind(
        tenant_id=_text("tenant_id", authority.get("tenant_id")),
        company_id=_text("company_id", authority.get("company_id")),
        source_kind=source_kind,
        effective_on=context["transaction"]["recognition_date"],
        projects=projects,
        correlation_id=correlation_id,
        source_pool=source_pool,
        lineage=AllocationAuthorityLineage(
            business_context_hash=context["context_hash"],
            preparation_hash=preparation["preparation_hash"],
        ),
        existing_checkpoint=existing_checkpoint,
    )


def _work_intent_context(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid("WorkIntent must be an object.")
    try:
        context = validate_business_request_context(
            value.get("business_request_context")
        )
    except BusinessContextValidationError as exc:
        raise _invalid(exc.detail) from exc
    if value.get("business_context_hash") != context["context_hash"] or value.get(
        "intent_hash"
    ) != semantic_sha256_hash_ref(
        {key: item for key, item in value.items() if key != "intent_hash"}
    ):
        raise _invalid("WorkIntent business authority is stale or tampered.")
    return context


def _preparation(value: object, *, context_hash: str) -> dict[str, Any]:
    if (
        not isinstance(value, Mapping)
        or set(value) != _PREPARATION_FIELDS
        or value.get("schema_version") != "nex.mybee.m1-transaction-preparation.v1"
        or value.get("stage") != "READY_FOR_D04"
        or value.get("business_context_hash") != context_hash
    ):
        raise _invalid("READY_FOR_D04 preparation is required.")
    checkpoint = dict(value)
    expected = semantic_sha256_hash_ref(
        {key: item for key, item in checkpoint.items() if key != "preparation_hash"}
    )
    authority = checkpoint.get("authority")
    if checkpoint.get("preparation_hash") != expected or not isinstance(
        authority, Mapping
    ):
        raise _invalid("Preparation checkpoint integrity is invalid.")
    expected_authority = semantic_sha256_hash_ref(
        {key: item for key, item in authority.items() if key != "authority_hash"}
    )
    if (
        authority.get("authority_hash") != expected_authority
        or checkpoint.get("authority_hash") != expected_authority
    ):
        raise _invalid("Preparation authority integrity is invalid.")
    return checkpoint


def _projects(
    allocations: object, project_refs: object
) -> tuple[Mapping[str, Any], ...]:
    if (
        isinstance(allocations, (str, bytes))
        or not isinstance(allocations, Sequence)
        or isinstance(project_refs, (str, bytes))
        or not isinstance(project_refs, Sequence)
    ):
        raise _invalid("Allocation and Project authority sets are required.")
    refs: dict[str, str] = {}
    for item in project_refs:
        if not isinstance(item, Mapping) or set(item) != {
            "project_id",
            "project_code",
            "project_version",
        }:
            raise _invalid("Project authority fields are invalid.")
        code = _text("project_code", item.get("project_code"))
        if code in refs:
            raise _invalid("Project authority contains duplicate codes.")
        refs[code] = _text("project_id", item.get("project_id"))
    projects: list[Mapping[str, Any]] = []
    for allocation in allocations:
        if not isinstance(allocation, Mapping) or set(allocation) != {
            "project_code",
            "ratio",
        }:
            raise _invalid("Requested allocation fields are invalid.")
        code = _text("project_code", allocation.get("project_code"))
        project_id = refs.pop(code, None)
        if project_id is None:
            raise _invalid("Requested Project lacks exact authority.")
        projects.append(
            {
                "project_id": project_id,
                "project_code": code,
                "allocation_ratio": _ratio(allocation.get("ratio")),
            }
        )
    if refs:
        raise _invalid("Project authority contains an unrequested Project.")
    return tuple(projects)


def _ratio(value: object) -> str:
    try:
        ratio = Decimal(str(value)).quantize(Decimal("0.000000000001"))
    except (InvalidOperation, ValueError) as exc:
        raise _invalid("Requested allocation ratio is invalid.") from exc
    if not ratio.is_finite() or ratio <= 0 or ratio > 1:
        raise _invalid("Requested allocation ratio is invalid.")
    return format(ratio, ".12f")


def _text(field: str, value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise _invalid(f"{field} is invalid.")
    return value


def _invalid(detail: str) -> M1AllocationPlanCompositionError:
    return M1AllocationPlanCompositionError(detail)
