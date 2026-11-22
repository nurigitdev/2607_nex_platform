from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request as UrlRequest
from urllib.request import urlopen
from uuid import UUID

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse
from nex_runtime import problem_response
from sqlalchemy.orm import Session, sessionmaker

from nex_ae_api.delegated_work import (
    DelegatedWorkError,
    SqlAlchemyWaitRegistrationRepository,
)
from nex_ae_api.nsl_approval_events import (
    NslApprovalEventError,
    SqlAlchemyNslApprovalEventService,
)
from nex_ae_api.nsl_approval_requests import (
    ProtectedApprovalRequestError,
    SqlAlchemyProtectedApprovalRequestStore,
)
from nex_ae_api.platform_approval_evidence import (
    PlatformApprovalEvidenceError,
    SqlAlchemyPlatformApprovalEvidenceRepository,
    build_platform_approval_evidence,
)
from nex_ae_api.route_auth import authorize_ae_internal_service_request


class ApprovalDecisionEventAdmission(Protocol):
    def ingest(self, delivery: object) -> dict[str, Any]: ...


class ProductAuthorityEventAdmission(Protocol):
    def ingest(self, payload: Mapping[str, Any]) -> dict[str, Any]: ...


class ProductWaitContextSource(Protocol):
    def resolve_product_wait_context(
        self,
        *,
        tenant_id: str,
        authority_kind: str,
        authority_ref: str,
    ) -> dict[str, Any] | None: ...


class ApprovalDecisionEventError(RuntimeError):
    def __init__(
        self,
        error_code: str,
        detail: str,
        *,
        status_code: int = 400,
        retryable: bool = False,
    ) -> None:
        self.error_code = error_code
        self.detail = detail
        self.status_code = status_code
        self.retryable = retryable
        super().__init__(detail)


class SqlAlchemyNslApprovalDecisionAdmission:
    """Compose existing protected request, wait, evidence, and resume services."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        event_service: SqlAlchemyNslApprovalEventService,
    ) -> None:
        self._requests = SqlAlchemyProtectedApprovalRequestStore(session_factory)
        self._waits = SqlAlchemyWaitRegistrationRepository(session_factory)
        self._evidence = SqlAlchemyPlatformApprovalEvidenceRepository(session_factory)
        self._events = event_service

    def ingest(self, delivery: Mapping[str, Any]) -> dict[str, Any]:
        outbox_id, work_item, decision, event = _delivery(delivery)
        if work_item.get("approval_domain") != "NSL_WRITE":
            raise _invalid("Approval event is not an NSL_WRITE decision.")
        tenant_id = _required(event.get("tenant_id"), "tenant_id")
        approval_request_id = _required(
            work_item.get("approval_request_id"), "approval_request_id"
        )
        request = self._requests.load_request(
            tenant_id=tenant_id,
            approval_request_id=approval_request_id,
        )
        protected = self._requests.get(
            tenant_id=tenant_id,
            approval_request_id=approval_request_id,
        )
        wait = self._waits.get(
            tenant_id=tenant_id,
            agent_execution_id=_required(
                work_item.get("agent_execution_id"), "agent_execution_id"
            ),
            executable_step_id=_required(
                work_item.get("executable_step_id"), "executable_step_id"
            ),
            wait_type="NSL_APPROVAL",
        )
        if request is None or protected is None or wait is None:
            raise ApprovalDecisionEventError(
                "ae.approval_decision_lineage_missing",
                "Persisted NSL approval lineage is incomplete.",
                status_code=409,
            )
        evidence = build_platform_approval_evidence(
            approval_request=request,
            protected_request=protected,
            wait_registration=wait,
            approval_work_item=work_item,
            approval_decision=decision,
            created_at=_datetime(decision.get("decided_at")),
        )
        saved = self._evidence.create_or_get(evidence)
        acceptance = self._events.ingest(
            {
                "schema_version": "ae_nsl_approval_decided_event.v1",
                "event_id": _required(event.get("event_id"), "event_id"),
                "event_name": "NSL_APPROVAL_DECIDED",
                "tenant_id": tenant_id,
                "approval_work_item_ref": _required(
                    work_item.get("approval_work_item_id"),
                    "approval_work_item_id",
                ),
                "approval_request_id": approval_request_id,
                "nsl_execution_id": saved["nsl_execution_id"],
                "business_operation_id": saved["business_operation_id"],
                "decision": saved["decision"],
                "approval_evidence_ref": (
                    f"ae-approval-evidence:{approval_request_id}"
                ),
                "evidence_integrity": saved["evidence_integrity"],
                "correlation_id": _required(
                    event.get("correlation_id"), "correlation_id"
                ),
                "causation_id": _required(decision.get("decision_id"), "decision_id"),
                "occurred_at": _required(decision.get("decided_at"), "decided_at"),
            }
        )
        return {
            "schema_version": "ae_approval_decision_receipt.v1",
            "outbox_id": outbox_id,
            "event_id": event["event_id"],
            "approval_domain": "NSL_WRITE",
            "disposition": acceptance["inbox_state"],
            "resume_runtime_job_id": acceptance.get("resume_runtime_job_id"),
        }


class HttpEosBusinessApprovalDecisionClient:
    def __init__(
        self,
        *,
        base_url: str,
        service_token: str,
        timeout_seconds: float = 15.0,
        opener: Callable[..., Any] = urlopen,
    ) -> None:
        if not isinstance(base_url, str) or not base_url.strip():
            raise _invalid("EOS base URL is required.")
        if not isinstance(service_token, str) or not service_token.strip():
            raise _invalid("AE to EOS service token is required.")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not 0 < timeout_seconds <= 120
        ):
            raise _invalid("EOS approval delivery timeout is invalid.")
        self._url = f"{base_url.rstrip('/')}/internal/v1/approval-decision-events"
        self._service_token = service_token
        self._timeout_seconds = float(timeout_seconds)
        self._opener = opener

    def ingest(self, delivery: Mapping[str, Any]) -> dict[str, Any]:
        request = UrlRequest(
            self._url,
            method="POST",
            data=json.dumps(dict(delivery), sort_keys=True).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._service_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with self._opener(request, timeout=self._timeout_seconds) as response:
                result = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            problem = _http_problem(exc)
            source_code = problem.get("error_code")
            raise ApprovalDecisionEventError(
                "ae.business_approval_delivery_failed",
                f"EOS business approval delivery failed with HTTP {exc.code}"
                f"{f' ({source_code})' if source_code else ''}.",
                status_code=503 if exc.code >= 500 else 409,
                retryable=exc.code >= 500,
            ) from exc
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise ApprovalDecisionEventError(
                "ae.business_approval_delivery_unavailable",
                "EOS business approval delivery is unavailable.",
                status_code=503,
                retryable=True,
            ) from exc
        event = _mapping(delivery.get("event"), "event")
        if not isinstance(result, Mapping):
            raise _invalid("EOS business approval receipt binding is invalid.")
        admitted = _eos_approval_receipt(result)
        if (
            admitted.get("outbox_id") != delivery.get("outbox_id")
            or admitted.get("event_id") != event.get("event_id")
            or admitted.get("approval_domain") != "BUSINESS_FORMAL"
        ):
            raise _invalid("EOS business approval receipt binding is invalid.")
        return admitted


class EosProductApprovalReceiptAdmission:
    """Bind an EOS authority receipt to one registered Product wait."""

    def __init__(
        self,
        *,
        eos_client: ApprovalDecisionEventAdmission,
        wait_contexts: ProductWaitContextSource,
        product_events: ProductAuthorityEventAdmission | None,
    ) -> None:
        self._eos = eos_client
        self._wait_contexts = wait_contexts
        self._product_events = product_events

    def ingest(self, delivery: object) -> dict[str, Any]:
        admitted_delivery = _mapping(delivery, "delivery")
        _outbox_id, work_item, decision, event = _delivery(admitted_delivery)
        receipt = self._eos.ingest(admitted_delivery)
        authority = _product_authority_receipt(
            receipt,
            work_item=work_item,
            decision=decision,
            event=event,
        )
        if authority is None or authority["authority_state"] == "PENDING":
            return dict(receipt)
        if self._product_events is None:
            raise ApprovalDecisionEventError(
                "ae.product_approval_resume_unavailable",
                "The active Product authority event admission is unavailable.",
                status_code=503,
                retryable=True,
            )
        try:
            context = self._wait_contexts.resolve_product_wait_context(
                tenant_id=authority["tenant_id"],
                authority_kind=authority["authority_kind"],
                authority_ref=authority["authority_ref"],
            )
        except Exception as exc:
            raise _product_resume_error(exc) from exc
        if context is None:
            raise ApprovalDecisionEventError(
                "ae.product_approval_wait_not_found",
                "No Product wait matches the EOS approval authority receipt.",
                status_code=409,
            )
        binding = _mapping(context.get("product_binding"), "product_binding")
        checkpoint = _mapping(context.get("checkpoint"), "checkpoint")
        expected_event_type = (
            "BUSINESS_APPROVAL_CHANGED"
            if authority["authority_kind"] == "BUSINESS_FORMAL"
            else "ACCOUNTING_APPROVAL_CHANGED"
        )
        if (
            binding.get("expected_event_type") != expected_event_type
            or binding.get("authority_ref") != authority["authority_ref"]
            or binding.get("checkpoint_id") != checkpoint.get("checkpoint_id")
        ):
            raise ApprovalDecisionEventError(
                "ae.product_approval_wait_drifted",
                "The Product wait binding differs from the EOS authority receipt.",
                status_code=409,
            )
        try:
            resumed = self._product_events.ingest(
                {
                    "tenant_id": authority["tenant_id"],
                    "coordinator_id": binding["coordinator_id"],
                    "coordinator_version": binding["coordinator_version"],
                    "coordinator_registration_hash": binding[
                        "coordinator_registration_hash"
                    ],
                    "checkpoint_id": binding["checkpoint_id"],
                    "event_id": authority["event_id"],
                    "notification_ref": authority["notification_ref"],
                    "authority_evidence_ref": authority["authority_evidence_ref"],
                    "authority_state": authority["authority_state"],
                    "received_at": authority["received_at"],
                }
            )
        except Exception as exc:
            raise _product_resume_error(exc) from exc
        return {**dict(receipt), "product_resume": dict(resumed)}


class ApprovalDecisionEventRouter:
    def __init__(
        self,
        *,
        nsl_admission: ApprovalDecisionEventAdmission,
        business_admission: ApprovalDecisionEventAdmission,
    ) -> None:
        self._nsl = nsl_admission
        self._business = business_admission

    def ingest(self, delivery: object) -> dict[str, Any]:
        normalized = _mapping(delivery, "delivery")
        _outbox_id, work_item, _decision, _event = _delivery(normalized)
        domain = work_item.get("approval_domain")
        if domain == "NSL_WRITE":
            return self._nsl.ingest(normalized)
        if domain == "BUSINESS_FORMAL":
            return self._business.ingest(normalized)
        raise ApprovalDecisionEventError(
            "ae.approval_decision_domain_unsupported",
            "The installed Demo runtime does not consume this approval domain.",
            status_code=409,
        )


def register_approval_decision_event_routes(
    app: FastAPI, *, admission: ApprovalDecisionEventAdmission | None
) -> None:
    @app.post("/internal/v1/approval-decision-events", response_model=None)
    def ingest_approval_decision_event(
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        admitted = authorize_ae_internal_service_request(
            request,
            authorization,
            allowed_service_ids=("nex-wc",),
            error_code="AE_APPROVAL_DECISION_CALLER_DENIED",
            title="AE approval decision caller denied",
            detail="Only nex-wc may deliver approval decision events.",
        )
        if isinstance(admitted, JSONResponse):
            return admitted
        if admission is None:
            return problem_response(
                request,
                status_code=503,
                error_code="AE_APPROVAL_DECISION_UNAVAILABLE",
                title="AE approval decision admission unavailable",
                detail="AE approval decision dependencies are not configured.",
                retryable=True,
            )
        try:
            result = admission.ingest(payload)
        except ApprovalDecisionEventError as exc:
            return problem_response(
                request,
                status_code=exc.status_code,
                error_code=exc.error_code,
                title="AE approval decision admission failed",
                detail=exc.detail,
                retryable=exc.retryable,
            )
        except (
            DelegatedWorkError,
            NslApprovalEventError,
            PlatformApprovalEvidenceError,
            ProtectedApprovalRequestError,
        ) as exc:
            return problem_response(
                request,
                status_code=getattr(exc, "status_code", 409),
                error_code=getattr(exc, "error_code", "ae.approval_decision_failed"),
                title="AE approval decision admission failed",
                detail=str(exc),
                retryable=bool(getattr(exc, "retryable", False)),
            )
        return JSONResponse(result, status_code=200)


def _delivery(
    value: Mapping[str, Any],
) -> tuple[str, dict[str, Any], dict[str, Any], dict[str, Any]]:
    if value.get("schema_version") != "wc_approval_delivery.v1":
        raise _invalid("WC approval delivery schema is invalid.")
    outbox_id = _required(value.get("outbox_id"), "outbox_id")
    work_item = dict(_mapping(value.get("work_item"), "work_item"))
    decision = dict(_mapping(value.get("decision"), "decision"))
    event = dict(_mapping(value.get("event"), "event"))
    ids = {
        "tenant_id": event.get("tenant_id"),
        "approval_work_item_id": event.get("approval_work_item_id"),
        "decision_id": event.get("decision_id"),
    }
    if any(
        work_item.get(name) != item
        for name, item in ids.items()
        if name != "decision_id"
    ):
        raise _invalid("WC approval delivery work-item lineage differs.")
    if any(decision.get(name) != item for name, item in ids.items()):
        raise _invalid("WC approval delivery decision lineage differs.")
    return outbox_id, work_item, decision, event


def _eos_approval_receipt(value: Mapping[str, Any]) -> dict[str, Any]:
    receipt = dict(value)
    schema_version = _required(receipt.get("schema_version"), "schema_version")
    if schema_version not in {
        "eos_approval_decision_receipt.v1",
        "eos_document_signoff_decision_receipt.v1",
        "eos_accounting_approval_decision_receipt.v2",
    }:
        raise _invalid("EOS business approval receipt schema is unsupported.")
    _required(receipt.get("outbox_id"), "outbox_id")
    _required(receipt.get("event_id"), "event_id")
    if receipt.get("approval_domain") != "BUSINESS_FORMAL":
        raise _invalid("EOS business approval receipt domain is invalid.")
    if schema_version == "eos_approval_decision_receipt.v1":
        if receipt.get("transition_state") not in {
            "PENDING",
            "APPROVED",
            "REJECTED",
        }:
            raise _invalid("EOS approval transition state is invalid.")
        _required(receipt.get("approval_instance_id"), "approval_instance_id")
        return receipt
    purpose = (
        "DOCUMENT_SIGNOFF"
        if schema_version == "eos_document_signoff_decision_receipt.v1"
        else "ACCOUNTING_POSTING"
    )
    if receipt.get("purpose") != purpose:
        raise _invalid("EOS scoped approval receipt purpose is invalid.")
    _required(receipt.get("case_id"), "case_id")
    if receipt.get("case_state") not in {"PENDING", "APPROVED", "REJECTED"}:
        raise _invalid("EOS scoped approval receipt state is invalid.")
    return receipt


def _product_authority_receipt(
    receipt: Mapping[str, Any],
    *,
    work_item: Mapping[str, Any],
    decision: Mapping[str, Any],
    event: Mapping[str, Any],
) -> dict[str, str] | None:
    schema_version = receipt.get("schema_version")
    profiles = {
        "eos_document_signoff_decision_receipt.v1": (
            "DOCUMENT_SIGNOFF",
            "BUSINESS_FORMAL",
            "approved_document_envelope",
            "envelope_id",
        ),
        "eos_accounting_approval_decision_receipt.v2": (
            "ACCOUNTING_POSTING",
            "ACCOUNTING_REVIEW",
            "accounting_approval_evidence",
            "evidence_id",
        ),
    }
    profile = profiles.get(str(schema_version))
    if profile is None:
        return None
    purpose, authority_kind, evidence_field, evidence_id_field = profile
    case_id = _required(receipt.get("case_id"), "case_id")
    resume_target = _required(work_item.get("resume_target_ref"), "resume_target_ref")
    expected_prefix = f"eos.scoped-approval-case:{case_id}:stage:"
    if not resume_target.startswith(expected_prefix):
        raise _invalid("EOS scoped approval receipt authority binding differs.")
    authority_state = str(receipt.get("case_state") or "")
    decision_state = decision.get("decision")
    if (
        authority_state == "APPROVED"
        and decision_state != "APPROVE"
        or authority_state == "REJECTED"
        and decision_state != "REJECT"
    ):
        raise _invalid("EOS scoped approval receipt decision differs.")
    evidence = receipt.get(evidence_field)
    if authority_state == "APPROVED":
        evidence_ref = _required(
            _mapping(evidence, evidence_field).get(evidence_id_field),
            evidence_id_field,
        )
        if evidence_id_field == "envelope_id":
            evidence_ref = _approved_document_envelope_ref(evidence_ref)
    elif authority_state == "REJECTED":
        if evidence is not None:
            raise _invalid("Rejected EOS authority receipt contains approval evidence.")
        evidence_ref = (
            "eos.scoped-approval-decision:"
            f"{_required(decision.get('decision_id'), 'decision_id')}"
        )
    else:
        if evidence is not None:
            raise _invalid("Pending EOS authority receipt contains terminal evidence.")
        evidence_ref = f"eos.scoped-approval-case:{case_id}:pending"
    decided_at = _datetime(decision.get("decided_at"))
    if event.get("occurred_at") != decision.get("decided_at"):
        raise _invalid("EOS authority receipt event time differs.")
    return {
        "tenant_id": _required(event.get("tenant_id"), "tenant_id"),
        "authority_kind": authority_kind,
        "authority_ref": case_id,
        "authority_state": authority_state,
        "event_id": _required(event.get("event_id"), "event_id"),
        "notification_ref": (
            f"eos.{purpose.lower()}:{case_id}:{authority_state.lower()}"
        ),
        "authority_evidence_ref": evidence_ref,
        "received_at": decided_at.isoformat().replace("+00:00", "Z"),
    }


def _product_resume_error(exc: Exception) -> ApprovalDecisionEventError:
    if isinstance(exc, ApprovalDecisionEventError):
        return exc
    error_code = getattr(exc, "error_code", None)
    detail = getattr(exc, "detail", None)
    retryable = bool(getattr(exc, "retryable", False))
    if not isinstance(error_code, str) or not isinstance(detail, str):
        error_code = "ae.product_approval_resume_failed"
        detail = "Product approval resume admission failed."
        retryable = True
    return ApprovalDecisionEventError(
        error_code,
        detail,
        status_code=503 if retryable else 409,
        retryable=retryable,
    )


def _approved_document_envelope_ref(value: object) -> str:
    candidate = _required(value, "envelope_id")
    try:
        admitted = str(UUID(candidate))
    except ValueError as exc:
        raise _invalid("EOS ApprovedDocument envelope reference is invalid.") from exc
    if candidate != admitted:
        raise _invalid("EOS ApprovedDocument envelope reference is not canonical.")
    return admitted


def _mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid(f"Approval delivery {field} must be an object.")
    return value


def _required(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _invalid(f"Approval delivery {field} is invalid.")
    return value.strip()


def _datetime(value: object) -> datetime:
    raw = _required(value, "decided_at")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _invalid("Approval delivery decided_at is invalid.") from exc
    if parsed.tzinfo is None:
        raise _invalid("Approval delivery decided_at must be timezone-aware.")
    return parsed.astimezone(UTC)


def _http_problem(exc: HTTPError) -> dict[str, str]:
    try:
        payload = json.loads(exc.read().decode("utf-8"))
    except (AttributeError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, Mapping):
        return {}
    value = payload.get("error_code")
    if not isinstance(value, str) or not re.fullmatch(
        r"[A-Za-z][A-Za-z0-9_.-]{0,95}", value
    ):
        return {}
    return {"error_code": value}


def _invalid(detail: str) -> ApprovalDecisionEventError:
    return ApprovalDecisionEventError("ae.approval_decision_invalid", detail)
