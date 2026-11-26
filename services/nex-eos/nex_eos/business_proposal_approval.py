from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref, validate_hash_ref

from .approval_policies import ApprovalPolicySelection

_SCOPED_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@/-]{0,255}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_MONEY_QUANTUM = Decimal("0.01")


class BusinessProposalSource(Protocol):
    def get(
        self,
        *,
        tenant_id: str,
        proposal_id: str,
        requester_subject_id: str | None = None,
    ) -> dict[str, Any] | None: ...


class LegalEntitySource(Protocol):
    def get_legal_entity(
        self,
        *,
        tenant_id: str,
        company_id: str,
        effective_on: date | None = None,
        active_only: bool = False,
    ) -> dict[str, Any] | None: ...


class FxRateSource(Protocol):
    def resolve_rate(
        self,
        *,
        tenant_id: str,
        company_id: str,
        purpose: str,
        base_currency: str,
        quote_currency: str,
        desired_rate_date: date,
        as_of: datetime | None = None,
    ) -> dict[str, Any]: ...


class ApprovalPolicySource(Protocol):
    def resolve_policy(
        self, selection: ApprovalPolicySelection
    ) -> dict[str, Any] | None: ...


class ApprovalCandidateAuthoritySource(Protocol):
    def list_eligible_candidates(
        self,
        *,
        tenant_id: str,
        company_id: str,
        project_ids: Sequence[str],
        position_type: str,
        effective_at: datetime,
    ) -> Sequence[Mapping[str, Any]]: ...


class HttpOaApprovalCandidateAuthoritySource:
    def __init__(
        self,
        *,
        base_url: str,
        service_token: str,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._service_token = service_token.strip()
        self._timeout_seconds = timeout_seconds

    def list_eligible_candidates(
        self,
        *,
        tenant_id: str,
        company_id: str,
        project_ids: Sequence[str],
        position_type: str,
        effective_at: datetime,
    ) -> Sequence[Mapping[str, Any]]:
        del company_id, project_ids, effective_at
        if not self._service_token:
            raise RuntimeError("OA service token is not configured")
        query = urlencode({"position_type": position_type, "limit": 100})
        request = Request(
            f"{self._base_url}/internal/v1/identity/memberships/tenants/"
            f"{quote(tenant_id, safe='')}/approver-candidates?{query}",
            method="GET",
            headers={
                "Authorization": f"Bearer {self._service_token}",
                "Accept": "application/json",
                "Cache-Control": "no-store, max-age=0",
                "Pragma": "no-cache",
            },
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("OA approver candidate request failed") from exc
        if not isinstance(payload, Mapping) or not isinstance(payload.get("items"), list):
            raise TypeError("OA approver candidate response is malformed")
        return payload["items"]


class EosBusinessProposalApprovalError(RuntimeError):
    def __init__(
        self,
        error_code: str,
        detail: str,
        *,
        status_code: int,
        retryable: bool = False,
    ) -> None:
        self.error_code = error_code
        self.detail = detail
        self.status_code = status_code
        self.retryable = retryable
        super().__init__(detail)


@dataclass(frozen=True)
class ApprovalLineSelectionInput:
    preview_hash: str
    proposal_id: str
    revision_no: int
    selected_approvers: Sequence[Mapping[str, Any]]


class EosBusinessProposalApprovalService:
    def __init__(
        self,
        proposals: BusinessProposalSource,
        companies: LegalEntitySource,
        fx_rates: FxRateSource,
        policies: ApprovalPolicySource,
        candidates: ApprovalCandidateAuthoritySource,
    ) -> None:
        self._proposals = proposals
        self._companies = companies
        self._fx_rates = fx_rates
        self._policies = policies
        self._candidates = candidates

    def preview(
        self,
        *,
        tenant_id: str,
        proposal_id: str,
        requester_subject_id: str,
        effective_at: datetime,
        risk_level: str | None = None,
    ) -> dict[str, Any]:
        tenant = _scoped_id("tenant_id", tenant_id)
        requester = _scoped_id("requester_subject_id", requester_subject_id)
        at = _instant(effective_at)
        proposal = self._proposals.get(
            tenant_id=tenant,
            proposal_id=proposal_id,
            requester_subject_id=requester,
        )
        if proposal is None:
            raise _not_found("Business proposal was not found for its requester")
        if proposal.get("state") not in {"DRAFT", "REJECTED"}:
            raise _conflict("Only an editable business proposal can be previewed")
        revision = _revision(proposal)
        company = self._companies.get_legal_entity(
            tenant_id=tenant,
            company_id=str(proposal["company_id"]),
            effective_on=at.date(),
            active_only=True,
        )
        if company is None:
            raise _unavailable("Active LegalEntity is unavailable")
        functional_currency = _currency(
            "functional_currency", company.get("functional_currency")
        )
        normalized = self._normalize_amount(
            tenant_id=tenant,
            company_id=str(proposal["company_id"]),
            revision=revision,
            functional_currency=functional_currency,
            effective_at=at,
        )
        policy = self._resolve_consistent_policy(
            tenant_id=tenant,
            revision=revision,
            normalized_amount=Decimal(normalized["normalized_amount"]),
            risk_level=_optional_scoped_id("risk_level", risk_level),
            effective_at=at,
        )
        stages = _stages(policy)
        candidate_stages: list[dict[str, Any]] = []
        project_ids = tuple(str(item) for item in revision["project_ids"])
        for stage in stages:
            eligible = self._eligible_candidates(
                tenant_id=tenant,
                company_id=str(proposal["company_id"]),
                project_ids=project_ids,
                requester_subject_id=requester,
                stage=stage,
                effective_at=at,
            )
            if not eligible:
                raise _unavailable(
                    f"No active OA candidate is eligible for stage {stage['stage_order']}"
                )
            candidate_stages.append({**stage, "candidates": eligible})
        candidate_evidence_hash = semantic_sha256_hash_ref(candidate_stages)
        preview_semantics = {
            "schema_version": "eos_business_proposal_approval_preview.v1",
            "tenant_id": tenant,
            "proposal_id": str(proposal["proposal_id"]),
            "revision_no": int(revision["revision_no"]),
            "proposal_version": int(proposal["version"]),
            "content_hash": _hash_ref("content_hash", revision.get("content_hash")),
            "policy_selection_input_hash": _hash_ref(
                "policy_selection_input_hash",
                revision.get("policy_selection_input_hash"),
            ),
            "normalized_amount_evidence": normalized,
            "risk_level": _optional_scoped_id("risk_level", risk_level),
            "approval_policy_id": str(policy["approval_policy_id"]),
            "approval_policy_hash": _hash_ref(
                "approval_policy_hash", policy.get("policy_hash")
            ),
            "candidate_evidence_hash": candidate_evidence_hash,
            "effective_at": _wire_instant(at),
        }
        return {
            **preview_semantics,
            "preview_hash": semantic_sha256_hash_ref(preview_semantics),
            "approval_policy": policy,
            "required_stages": candidate_stages,
        }

    def select_line(
        self,
        *,
        preview: Mapping[str, Any],
        selection: ApprovalLineSelectionInput,
    ) -> dict[str, Any]:
        if not isinstance(preview, Mapping):
            raise _invalid("preview must be an object")
        if not isinstance(selection, ApprovalLineSelectionInput):
            raise _invalid("selection must be ApprovalLineSelectionInput")
        preview_hash = _hash_ref("preview_hash", preview.get("preview_hash"))
        if _hash_ref("selection.preview_hash", selection.preview_hash) != preview_hash:
            raise _conflict("Approval preview is stale")
        if str(preview.get("proposal_id")) != str(selection.proposal_id):
            raise _conflict("Approval selection proposal does not match its preview")
        if int(preview.get("revision_no", 0)) != _positive_int(
            "revision_no", selection.revision_no
        ):
            raise _conflict("Approval selection revision does not match its preview")
        required = preview.get("required_stages")
        if not isinstance(required, list) or not required:
            raise _invalid("preview.required_stages must be a non-empty list")
        selected = _selected_approvers(selection.selected_approvers)
        if len(selected) != len(required):
            raise _invalid("Exactly one approver must be selected for every stage")
        admitted: list[dict[str, Any]] = []
        for expected_order, stage in enumerate(required, start=1):
            if (
                not isinstance(stage, Mapping)
                or stage.get("stage_order") != expected_order
            ):
                raise _invalid("Preview stages are malformed or unordered")
            choice = selected[expected_order - 1]
            if choice["stage_order"] != expected_order:
                raise _invalid("Selected approvers must be contiguous and ordered")
            candidates = stage.get("candidates")
            if not isinstance(candidates, list):
                raise _invalid("Preview candidate evidence is malformed")
            match = next(
                (
                    item
                    for item in candidates
                    if isinstance(item, Mapping)
                    and item.get("subject_id") == choice["subject_id"]
                ),
                None,
            )
            if match is None:
                raise _denied("Selected approver is not in the fresh OA candidate set")
            admitted.append(
                {
                    "stage_order": expected_order,
                    "position_type": str(stage["position_type"]),
                    "subject_id": choice["subject_id"],
                    "display_name": str(match["display_name"]),
                    "authority_hash": _hash_ref(
                        "authority_hash", match.get("authority_hash")
                    ),
                }
            )
        semantics = {
            "schema_version": "eos_business_proposal_approval_line.v1",
            "tenant_id": str(preview["tenant_id"]),
            "proposal_id": str(preview["proposal_id"]),
            "revision_no": int(preview["revision_no"]),
            "preview_hash": preview_hash,
            "approval_policy_id": str(preview["approval_policy_id"]),
            "approval_policy_hash": _hash_ref(
                "approval_policy_hash", preview.get("approval_policy_hash")
            ),
            "candidate_evidence_hash": _hash_ref(
                "candidate_evidence_hash", preview.get("candidate_evidence_hash")
            ),
            "approvers": admitted,
        }
        return {**semantics, "approval_line_hash": semantic_sha256_hash_ref(semantics)}

    def _normalize_amount(
        self,
        *,
        tenant_id: str,
        company_id: str,
        revision: Mapping[str, Any],
        functional_currency: str,
        effective_at: datetime,
    ) -> dict[str, Any]:
        original_currency = _currency(
            "original_currency", revision.get("original_currency")
        )
        original_amount = _money("requested_amount", revision.get("requested_amount"))
        if original_currency == functional_currency:
            evidence = {
                "schema_version": "eos_business_proposal_amount_normalization.v1",
                "original_amount": _amount_text(original_amount),
                "original_currency": original_currency,
                "functional_currency": functional_currency,
                "normalized_amount": _amount_text(original_amount),
                "conversion_kind": "IDENTITY",
                "rate_snapshot_id": None,
                "rate_snapshot_hash": None,
            }
        else:
            try:
                snapshot = self._fx_rates.resolve_rate(
                    tenant_id=tenant_id,
                    company_id=company_id,
                    purpose="TRANSACTION",
                    base_currency=original_currency,
                    quote_currency=functional_currency,
                    desired_rate_date=effective_at.date(),
                    as_of=effective_at,
                )
            except Exception as exc:
                if isinstance(exc, EosBusinessProposalApprovalError):
                    raise
                raise _unavailable("Trusted FX RateSnapshot is unavailable") from exc
            rate = _positive_decimal("normalized_rate", snapshot.get("normalized_rate"))
            quote_unit = _positive_decimal("quote_unit", snapshot.get("quote_unit"))
            normalized_amount = (original_amount * rate / quote_unit).quantize(
                _MONEY_QUANTUM, rounding=ROUND_HALF_UP
            )
            evidence = {
                "schema_version": "eos_business_proposal_amount_normalization.v1",
                "original_amount": _amount_text(original_amount),
                "original_currency": original_currency,
                "functional_currency": functional_currency,
                "normalized_amount": _amount_text(normalized_amount),
                "conversion_kind": "FX_SNAPSHOT",
                "rate_snapshot_id": str(snapshot.get("rate_snapshot_id")),
                "rate_snapshot_hash": _hash_ref(
                    "snapshot_hash", snapshot.get("snapshot_hash")
                ),
                "rate": _amount_text(rate),
                "quote_unit": _amount_text(quote_unit),
                "selected_rate_date": str(snapshot.get("selected_rate_date")),
            }
        return {**evidence, "calculation_hash": semantic_sha256_hash_ref(evidence)}

    def _resolve_consistent_policy(
        self,
        *,
        tenant_id: str,
        revision: Mapping[str, Any],
        normalized_amount: Decimal,
        risk_level: str | None,
        effective_at: datetime,
    ) -> dict[str, Any]:
        project_ids = tuple(str(item) for item in revision["project_ids"])
        selectors: tuple[str | None, ...] = project_ids or (None,)
        resolved: list[dict[str, Any]] = []
        for project_id in selectors:
            policy = self._policies.resolve_policy(
                ApprovalPolicySelection(
                    tenant_id=tenant_id,
                    approval_domain="BUSINESS_FORMAL",
                    risk_level=risk_level,
                    amount=normalized_amount,
                    transaction_type=str(revision["transaction_type"]),
                    effective_at=effective_at,
                    project_id=project_id,
                )
            )
            if policy is None:
                raise _unavailable("No active approval policy matches the proposal")
            resolved.append(policy)
        hashes = {
            _hash_ref("policy_hash", item.get("policy_hash")) for item in resolved
        }
        if len(hashes) != 1:
            raise _conflict(
                "Project-set proposal does not resolve to one approval policy"
            )
        return resolved[0]

    def _eligible_candidates(
        self,
        *,
        tenant_id: str,
        company_id: str,
        project_ids: Sequence[str],
        requester_subject_id: str,
        stage: Mapping[str, Any],
        effective_at: datetime,
    ) -> list[dict[str, Any]]:
        try:
            raw = self._candidates.list_eligible_candidates(
                tenant_id=tenant_id,
                company_id=company_id,
                project_ids=project_ids,
                position_type=str(stage["position_type"]),
                effective_at=effective_at,
            )
        except Exception as exc:
            if isinstance(exc, EosBusinessProposalApprovalError):
                raise
            raise _unavailable(
                "OA approver candidate authority is unavailable"
            ) from exc
        eligible: list[dict[str, Any]] = []
        seen: set[str] = set()
        for value in raw:
            if not isinstance(value, Mapping) or value.get("active") is not True:
                continue
            subject_id = _scoped_id("candidate.subject_id", value.get("subject_id"))
            if subject_id in seen or (
                stage.get("separation_policy") == "REQUESTER_EXCLUDED"
                and subject_id == requester_subject_id
            ):
                continue
            if str(value.get("position_type")) != str(stage["position_type"]):
                continue
            seen.add(subject_id)
            eligible.append(
                {
                    "subject_id": subject_id,
                    "display_name": _bounded(
                        "candidate.display_name", value.get("display_name"), 256
                    ),
                    "position_type": str(stage["position_type"]),
                    "authority_hash": _hash_ref(
                        "candidate.authority_hash", value.get("authority_hash")
                    ),
                }
            )
        return sorted(
            eligible, key=lambda item: (item["display_name"], item["subject_id"])
        )


def _revision(proposal: Mapping[str, Any]) -> Mapping[str, Any]:
    revision = proposal.get("current_revision")
    if not isinstance(revision, Mapping):
        raise _invalid("Business proposal revision is unavailable")
    return revision


def _stages(policy: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = policy.get("stages")
    if not isinstance(raw, list) or not raw or len(raw) > 5:
        raise _invalid("Approval policy stages are unavailable")
    stages: list[dict[str, Any]] = []
    for expected, value in enumerate(raw, start=1):
        if (
            not isinstance(value, Mapping)
            or int(value.get("stage_order", 0)) != expected
        ):
            raise _invalid("Approval policy stages must be contiguous and ordered")
        if int(value.get("quorum_count", 0)) != 1:
            raise _invalid("Business proposal stages require quorum_count=1")
        stages.append(
            {
                "stage_order": expected,
                "position_type": _scoped_id(
                    "position_type", value.get("position_type")
                ),
                "quorum_count": 1,
                "separation_policy": str(value.get("separation_policy")),
            }
        )
    return stages


def _selected_approvers(values: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise _invalid("selected_approvers must be a list")
    result: list[dict[str, Any]] = []
    for value in values:
        if not isinstance(value, Mapping):
            raise _invalid("selected_approvers entries must be objects")
        result.append(
            {
                "stage_order": _positive_int("stage_order", value.get("stage_order")),
                "subject_id": _scoped_id("subject_id", value.get("subject_id")),
            }
        )
    return result


def _instant(value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise _invalid("effective_at must be timezone-aware")
    return value.astimezone(UTC)


def _currency(field: str, value: object) -> str:
    result = str(value or "").strip().upper()
    if not _CURRENCY.fullmatch(result):
        raise _invalid(f"{field} must be an ISO currency code")
    return result


def _money(field: str, value: object) -> Decimal:
    try:
        result = Decimal(str(value)).quantize(_MONEY_QUANTUM, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise _invalid(f"{field} must be a monetary amount") from exc
    if not result.is_finite() or result <= 0:
        raise _invalid(f"{field} must be positive")
    return result


def _positive_decimal(field: str, value: object) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise _invalid(f"{field} must be a decimal") from exc
    if not result.is_finite() or result <= 0:
        raise _invalid(f"{field} must be positive")
    return result


def _amount_text(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _positive_int(field: str, value: object) -> int:
    if isinstance(value, bool):
        raise _invalid(f"{field} must be a positive integer")
    try:
        result = int(value)
    except (ValueError, TypeError) as exc:
        raise _invalid(f"{field} must be a positive integer") from exc
    if result <= 0:
        raise _invalid(f"{field} must be a positive integer")
    return result


def _scoped_id(field: str, value: object) -> str:
    result = str(value or "").strip()
    if not _SCOPED_ID.fullmatch(result):
        raise _invalid(f"{field} is invalid")
    return result


def _optional_scoped_id(field: str, value: object) -> str | None:
    if value is None:
        return None
    return _scoped_id(field, value)


def _bounded(field: str, value: object, maximum: int) -> str:
    result = str(value or "").strip()
    if not result or len(result) > maximum:
        raise _invalid(f"{field} is invalid")
    return result


def _hash_ref(field: str, value: object) -> str:
    try:
        return validate_hash_ref(value)
    except ValueError as exc:
        raise _invalid(f"{field} is invalid") from exc


def _wire_instant(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _invalid(detail: str) -> EosBusinessProposalApprovalError:
    return EosBusinessProposalApprovalError(
        "BUSINESS_PROPOSAL_APPROVAL_INVALID", detail, status_code=422
    )


def _not_found(detail: str) -> EosBusinessProposalApprovalError:
    return EosBusinessProposalApprovalError(
        "BUSINESS_PROPOSAL_APPROVAL_NOT_FOUND", detail, status_code=404
    )


def _conflict(detail: str) -> EosBusinessProposalApprovalError:
    return EosBusinessProposalApprovalError(
        "BUSINESS_PROPOSAL_APPROVAL_CONFLICT", detail, status_code=409
    )


def _denied(detail: str) -> EosBusinessProposalApprovalError:
    return EosBusinessProposalApprovalError(
        "BUSINESS_PROPOSAL_APPROVAL_DENIED", detail, status_code=403
    )


def _unavailable(detail: str) -> EosBusinessProposalApprovalError:
    return EosBusinessProposalApprovalError(
        "BUSINESS_PROPOSAL_APPROVAL_UNAVAILABLE",
        detail,
        status_code=503,
        retryable=True,
    )
