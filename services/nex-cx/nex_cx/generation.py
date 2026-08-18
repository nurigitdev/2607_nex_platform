from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import NAMESPACE_URL, uuid5

import httpx
from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

from nex_runtime.compatibility import (
    GenerationCompatibilityError,
    select_generation_compatibility_rule,
)
from nex_runtime.recovery import (
    GenerationRecoveryPolicyError,
    recovery_policy_hash,
    select_generation_recovery_policy,
)
from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    issue_mock_service_token,
    problem_response,
    request_id_from_headers,
    trace_id_from_headers,
    validate_authorization_header,
)
from nex_cx.drafts import build_structured_draft
from nex_cx.progress import (
    build_cx_generation_failure_progress_events,
    build_cx_generation_progress_events,
)

FORBIDDEN_PROVIDER_FIELDS = {"provider_url", "model_path", "provider_endpoint", "api_key"}
FAILED_STAGE_BY_ERROR_CODE = {
    "mo.provider_timeout": "GENERATING",
    "mo.request_failed": "MO_ADMISSION_WAITING",
    "cx.citation_validation_failed": "CITATION_VALIDATING",
}
CX_GROUNDED_GENERATION_BOUNDARY_AUDIT_SCHEMA_VERSION = (
    "cx_grounded_generation_boundary_audit.v1"
)
CX_RETRIEVAL_PACKAGE_QUALITY_GUARD_SCHEMA_VERSION = (
    "cx_retrieval_package_quality_guard.v1"
)
DEFAULT_GENERATION_LOW_CONFIDENCE_THRESHOLD = 0.2
BLOCKED_RETRIEVAL_CONFIDENCE_BUCKETS = {"LOW_CONFIDENCE", "NO_ANSWER"}
BLOCKING_RETRIEVAL_QUALITY_FLAGS = {
    "low_confidence",
    "low_source_confidence",
    "permission_denied",
    "source_unavailable",
    "stale_bm25",
    "stale_embedding",
}
GROUNDING_BOUNDARY_STAGES = (
    "compatibility_rule",
    "retrieval_package_ref",
    "retrieval_package_store",
    "retrieval_package_lookup",
    "package_hash",
    "package_status",
    "selected_evidence",
    "retrieval_package_quality",
)
FORBIDDEN_AUDIT_RAW_KEYS = {
    "prompt",
    "messages",
    "content",
    "query_text",
    "text",
    "chunk_text",
    "source_text",
    "raw_prompt",
    "raw_output",
    "provider_url",
    "provider_endpoint",
    "model_path",
    "api_key",
}


class MoGenerationClient(Protocol):
    def create_generation(
        self,
        payload: dict[str, Any],
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        ...


class RetrievalPackageStore(Protocol):
    def get_retrieval_package(self, retrieval_package_id: str) -> dict[str, Any] | None:
        ...


@dataclass(frozen=True)
class HttpMoGenerationClient:
    base_url: str = "http://127.0.0.1:8105"
    service_token: str | None = None
    timeout_seconds: float = 5.0

    def create_generation(
        self,
        payload: dict[str, Any],
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        token = self.service_token or issue_mock_service_token(
            service_id="nex-cx",
            audience="nex-mo",
        ).access_token
        response = httpx.post(
            f"{self.base_url}/api/v1/generations",
            json=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "X-Request-ID": request_id,
                "traceparent": f"00-{trace_id}-00f067aa0ba902b7-01",
                "X-Service-ID": "nex-cx",
            },
            timeout=self.timeout_seconds,
        )
        if response.status_code >= 400:
            body = _safe_response_json(response)
            raise GenerationFacadeError(
                status_code=response.status_code,
                error_code=body.get("error_code", "mo.request_failed"),
                detail=body.get("detail", "MO generation request failed."),
                retryable=body.get("retryable", False),
            )
        return response.json()


@dataclass
class GenerationExecutionStore:
    records: dict[str, dict[str, Any]] = field(default_factory=dict)
    structured_drafts: dict[str, dict[str, Any]] = field(default_factory=dict)
    progress_events: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    def save(
        self,
        record: dict[str, Any],
        *,
        structured_draft: dict[str, Any] | None = None,
        progress_events: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        self.records[record["cx_generation_id"]] = record
        if structured_draft is not None:
            self.structured_drafts[record["cx_generation_id"]] = structured_draft
        if progress_events is not None:
            self.progress_events[record["cx_generation_id"]] = list(progress_events)
        return record

    def get(self, cx_generation_id: str) -> dict[str, Any] | None:
        return self.records.get(cx_generation_id)

    def get_structured_draft(self, cx_generation_id: str) -> dict[str, Any] | None:
        return self.structured_drafts.get(cx_generation_id)

    def get_progress_events(self, cx_generation_id: str) -> list[dict[str, Any]] | None:
        events = self.progress_events.get(cx_generation_id)
        if events is None:
            return None
        return list(events)


@dataclass(frozen=True)
class GenerationFacadeError(Exception):
    status_code: int
    error_code: str
    detail: str
    retryable: bool = False


@dataclass(frozen=True)
class GroundedGenerationBoundaryDecision:
    admitted: bool
    boundary_status: str
    compatibility_rule: dict[str, Any] | None
    retrieval_package_ref: dict[str, str] | None
    retrieval_package: dict[str, Any] | None
    error: Exception | None
    audit: dict[str, Any]


DEFAULT_GENERATION_STORE = GenerationExecutionStore()


def build_default_mo_client() -> HttpMoGenerationClient:
    return HttpMoGenerationClient(
        base_url=os.getenv("NEX_MO_BASE_URL", "http://127.0.0.1:8105"),
        service_token=os.getenv("NEX_CX_TO_MO_SERVICE_TOKEN"),
    )


def register_generation_routes(
    app: FastAPI,
    *,
    store: GenerationExecutionStore | None = None,
    mo_client: MoGenerationClient | None = None,
    retrieval_store: RetrievalPackageStore | None = None,
) -> None:
    generation_store = store or DEFAULT_GENERATION_STORE
    client = mo_client or build_default_mo_client()

    @app.post("/api/v1/generations", response_model=None)
    def create_generation(
        payload: dict[str, Any],
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_cx_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        request_id = request_id_from_headers(request)
        trace_id = payload.get("trace_id") or trace_id_from_headers(request)
        try:
            compatibility_rule, retrieval_package = validate_generation_request(
                payload,
                retrieval_store=retrieval_store,
            )
            mo_payload = build_mo_generation_payload(payload, trace_id=trace_id)
            try:
                mo_response = client.create_generation(
                    mo_payload,
                    request_id=request_id,
                    trace_id=trace_id,
                )
            except GenerationFacadeError as exc:
                failure_record = build_generation_failure_record(
                    source_payload=payload,
                    mo_payload=mo_payload,
                    failure=exc,
                    compatibility_rule=compatibility_rule,
                    retrieval_package=retrieval_package,
                    request_id=request_id,
                    trace_id=trace_id,
                )
                generation_store.save(
                    failure_record,
                    progress_events=build_cx_generation_failure_progress_events(
                        source_payload=payload,
                        mo_payload=mo_payload,
                        failure_record=failure_record,
                        compatibility_rule=compatibility_rule,
                        retrieval_package=retrieval_package,
                        request_id=request_id,
                        trace_id=trace_id,
                    ),
                )
                return _generation_problem_response(request, exc)
            structured_draft = build_structured_draft(
                cx_generation_id=mo_payload["cx_generation_id"],
                trace_id=trace_id,
                request_id=request_id,
                output_text=output_text_from_mo_response(mo_response),
                compatibility_rule=compatibility_rule,
                retrieval_package=retrieval_package,
                selected_evidence_ids=selected_evidence_ids_from_payload(payload),
            )
            progress_events = build_cx_generation_progress_events(
                source_payload=payload,
                mo_payload=mo_payload,
                mo_response=mo_response,
                compatibility_rule=compatibility_rule,
                retrieval_package=retrieval_package,
                structured_draft=structured_draft,
                request_id=request_id,
                trace_id=trace_id,
            )
            return generation_store.save(
                build_generation_execution_record(
                    source_payload=payload,
                    mo_payload=mo_payload,
                    mo_response=mo_response,
                    compatibility_rule=compatibility_rule,
                    retrieval_package=retrieval_package,
                    structured_draft=structured_draft,
                    request_id=request_id,
                    trace_id=trace_id,
                ),
                structured_draft=structured_draft,
                progress_events=progress_events,
            )
        except GenerationCompatibilityError as exc:
            return _generation_problem_response(
                request,
                GenerationFacadeError(
                    status_code=exc.status_code,
                    error_code=exc.error_code,
                    detail=exc.detail,
                ),
            )
        except GenerationFacadeError as exc:
            return _generation_problem_response(request, exc)

    @app.get("/api/v1/generations/{cx_generation_id}", response_model=None)
    def get_generation(
        cx_generation_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_cx_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        record = generation_store.get(cx_generation_id)
        if record is None:
            return _generation_problem_response(
                request,
                GenerationFacadeError(
                    status_code=404,
                    error_code="cx.generation_not_found",
                    detail=f"Generation record was not found: {cx_generation_id}",
                ),
            )
        return record

    @app.get("/api/v1/generations/{cx_generation_id}/structured-draft", response_model=None)
    def get_structured_draft(
        cx_generation_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_cx_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        draft = generation_store.get_structured_draft(cx_generation_id)
        if draft is None:
            return _generation_problem_response(
                request,
                GenerationFacadeError(
                    status_code=404,
                    error_code="cx.structured_draft_not_found",
                    detail=f"Structured draft was not found: {cx_generation_id}",
                ),
            )
        return draft

    @app.get("/api/v1/generations/{cx_generation_id}/events", response_model=None)
    def get_generation_events(
        cx_generation_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_cx_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        record = generation_store.get(cx_generation_id)
        if record is None:
            return _generation_problem_response(
                request,
                GenerationFacadeError(
                    status_code=404,
                    error_code="cx.generation_not_found",
                    detail=f"Generation record was not found: {cx_generation_id}",
                ),
            )

        events = generation_store.get_progress_events(cx_generation_id) or []
        return {
            "progress_events_schema_version": "generation_progress_event_list.v1",
            "cx_generation_id": cx_generation_id,
            "trace_id": record["trace_id"],
            "request_id": record["request_id"],
            "events": events,
            "pagination": {
                "next_cursor": None,
                "event_count": len(events),
            },
        }


def build_mo_generation_payload(
    source_payload: dict[str, Any],
    *,
    trace_id: str,
) -> dict[str, Any]:
    leaked = sorted(FORBIDDEN_PROVIDER_FIELDS & set(source_payload))
    if leaked:
        raise GenerationFacadeError(
            status_code=422,
            error_code="cx.provider_field_forbidden",
            detail=f"Provider-private field is not allowed: {leaked[0]}",
        )

    prompt_text = prompt_text_from_payload(source_payload)
    provider_prompt_package_hash = source_payload.get(
        "provider_prompt_package_hash",
        sha256_text(prompt_text),
    )
    request_hash = sha256_json(
        {
            "trace_id": trace_id,
            "alias": source_payload.get("alias", "general-llm-default"),
            "provider_capability": source_payload.get("provider_capability", "generation"),
            "provider_prompt_package_hash": provider_prompt_package_hash,
            "response_format": source_payload.get("response_format", {"type": "text"}),
            "metadata": source_payload.get("metadata", {}),
        }
    )
    cx_generation_id = source_payload.get("cx_generation_id") or str(
        uuid5(NAMESPACE_URL, f"cx-generation:{request_hash}")
    )

    return {
        "request_schema_version": "cx_mo_generation_request.v1",
        "client_request_id": source_payload.get("client_request_id", cx_generation_id),
        "trace_id": trace_id,
        "cx_generation_id": cx_generation_id,
        "provider_prompt_package_hash": provider_prompt_package_hash,
        "alias": source_payload.get("alias", "general-llm-default"),
        "provider_capability": source_payload.get("provider_capability", "generation"),
        "workload_class": source_payload.get("workload_class", "LLM_INTERACTIVE"),
        "generation_profile": source_payload.get("generation_profile", "general-answer"),
        "messages": source_payload.get("messages"),
        "prompt": source_payload.get("prompt"),
        "response_format": source_payload.get("response_format", {"type": "text"}),
        "max_output_tokens": source_payload.get("max_output_tokens", 256),
        "temperature": source_payload.get("temperature", 0.0),
        "stream": source_payload.get("stream", False),
        "timeout_ms": source_payload.get("timeout_ms", 5000),
        "metadata": {
            **source_payload.get("metadata", {}),
            "generation_request_hash": request_hash,
        },
    }


def build_generation_execution_record(
    *,
    source_payload: dict[str, Any],
    mo_payload: dict[str, Any],
    mo_response: dict[str, Any],
    compatibility_rule: dict[str, Any] | None = None,
    retrieval_package: dict[str, Any] | None = None,
    structured_draft: dict[str, Any] | None = None,
    request_id: str,
    trace_id: str,
) -> dict[str, Any]:
    now = _utc_now()
    output = mo_response.get("output", {})
    output_text = output.get("text", "") if isinstance(output, dict) else ""
    quality_audit = _structured_draft_quality_audit(structured_draft)
    return {
        "record_schema_version": "cx_generation_execution_record.v1",
        "cx_generation_id": mo_payload["cx_generation_id"],
        "status": "COMPLETED",
        "trace_id": trace_id,
        "request_id": request_id,
        "alias": mo_response["alias"],
        "provider_capability": mo_payload["provider_capability"],
        "mo_generation_id": mo_response["mo_generation_id"],
        "request_metadata": {
            "provider_prompt_package_hash": mo_payload["provider_prompt_package_hash"],
            "generation_request_hash": mo_payload["metadata"]["generation_request_hash"],
            "response_format_type": mo_payload["response_format"]["type"],
            "source_has_messages": bool(source_payload.get("messages")),
            "source_has_prompt": bool(source_payload.get("prompt")),
            "compatibility_rule_id": compatibility_rule["compatibility_rule_id"]
            if compatibility_rule
            else None,
            "grounding_required": compatibility_rule["grounding_required"]
            if compatibility_rule
            else False,
            "retrieval_package_id": retrieval_package["retrieval_package_id"]
            if retrieval_package
            else None,
            "retrieval_package_hash": retrieval_package["package_hash"]
            if retrieval_package
            else None,
            "selected_evidence_count": len(selected_evidence_ids_from_payload(source_payload)),
            "structured_draft_id": structured_draft["structured_draft_id"]
            if structured_draft
            else None,
            "draft_validation_status": structured_draft["validation"]["citation_status"]
            if structured_draft
            else None,
            "grounded_response_quality_audit_schema_version": quality_audit[
                "audit_schema_version"
            ]
            if quality_audit
            else None,
            "grounded_response_quality_status": quality_audit["boundary_status"]
            if quality_audit
            else None,
            "grounded_response_quality_issue_count": len(quality_audit["issues"])
            if quality_audit
            else None,
        },
        "response_metadata": {
            "finish_reason": mo_response.get("finish_reason"),
            "output_hash": sha256_text(output_text) if output_text else None,
            "output_preview": output_text[:120],
        },
        "mo_runtime_metadata": _safe_runtime_metadata(
            mo_response.get("runtime_metadata", {})
        ),
        "usage": mo_response.get("usage", {}),
        "created_at": now,
        "updated_at": now,
    }


def build_generation_failure_record(
    *,
    source_payload: dict[str, Any],
    mo_payload: dict[str, Any],
    failure: GenerationFacadeError,
    compatibility_rule: dict[str, Any] | None = None,
    retrieval_package: dict[str, Any] | None = None,
    request_id: str,
    trace_id: str,
) -> dict[str, Any]:
    now = _utc_now()
    policy = _recovery_policy_for_failure_code(failure.error_code)
    policy_hash = recovery_policy_hash(policy) if policy else None
    return {
        "record_schema_version": "cx_generation_execution_record.v1",
        "cx_generation_id": mo_payload["cx_generation_id"],
        "status": "FAILED",
        "trace_id": trace_id,
        "request_id": request_id,
        "alias": mo_payload["alias"],
        "provider_capability": mo_payload["provider_capability"],
        "mo_generation_id": None,
        "request_metadata": {
            "provider_prompt_package_hash": mo_payload["provider_prompt_package_hash"],
            "generation_request_hash": mo_payload["metadata"]["generation_request_hash"],
            "response_format_type": mo_payload["response_format"]["type"],
            "source_has_messages": bool(source_payload.get("messages")),
            "source_has_prompt": bool(source_payload.get("prompt")),
            "compatibility_rule_id": compatibility_rule["compatibility_rule_id"]
            if compatibility_rule
            else None,
            "grounding_required": compatibility_rule["grounding_required"]
            if compatibility_rule
            else False,
            "retrieval_package_id": retrieval_package["retrieval_package_id"]
            if retrieval_package
            else None,
            "retrieval_package_hash": retrieval_package["package_hash"]
            if retrieval_package
            else None,
            "selected_evidence_count": len(selected_evidence_ids_from_payload(source_payload)),
            "structured_draft_id": None,
            "draft_validation_status": None,
        },
        "response_metadata": {
            "finish_reason": "ERROR",
            "output_hash": None,
            "output_preview": "",
        },
        "mo_runtime_metadata": {},
        "usage": {},
        "failure": _build_failure_summary(
            failure=failure,
            policy=policy,
            policy_hash=policy_hash,
        ),
        "recovery_lineage": _build_recovery_lineage(
            source_payload=source_payload,
            mo_payload=mo_payload,
            failure=failure,
            policy=policy,
            policy_hash=policy_hash,
            has_retrieval_package=retrieval_package is not None,
        ),
        "created_at": now,
        "updated_at": now,
    }


def output_text_from_mo_response(mo_response: dict[str, Any]) -> str:
    output = mo_response.get("output", {})
    if isinstance(output, dict) and isinstance(output.get("text"), str):
        return output["text"]
    return ""


def _structured_draft_quality_audit(
    structured_draft: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not structured_draft:
        return None
    validation = structured_draft.get("validation")
    if not isinstance(validation, dict):
        return None
    audit = validation.get("quality_audit")
    return audit if isinstance(audit, dict) else None


def validate_generation_request(
    source_payload: dict[str, Any],
    *,
    retrieval_store: RetrievalPackageStore | None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    decision = evaluate_grounded_generation_boundary(
        source_payload,
        retrieval_store=retrieval_store,
    )
    if decision.error is not None:
        raise decision.error
    if decision.compatibility_rule is None:
        raise GenerationFacadeError(
            status_code=500,
            error_code="cx.generation_boundary_invalid",
            detail="Generation boundary decision did not include a compatibility rule.",
        )
    return decision.compatibility_rule, decision.retrieval_package


def validate_retrieval_package_quality(retrieval_package: dict[str, Any]) -> None:
    guard = build_retrieval_package_quality_guard(retrieval_package)
    if guard["status"] == "PASS":
        return
    raise GenerationFacadeError(
        status_code=409,
        error_code="cx.retrieval_package_quality_blocked",
        detail=(
            "Retrieval package quality guard blocked grounded generation: "
            f"{guard['blocking_reason']}."
        ),
    )


def build_retrieval_package_quality_guard(
    retrieval_package: dict[str, Any] | None,
) -> dict[str, Any]:
    if retrieval_package is None:
        return _retrieval_package_quality_guard_record(
            status="BLOCKED",
            blocking_reason="retrieval_package_missing",
            failed_checks=["retrieval_package_missing"],
        )

    raw_score_summary = retrieval_package.get("score_summary")
    raw_source_summary = retrieval_package.get("source_summary")
    score_summary = _mapping_value(raw_score_summary)
    source_summary = _mapping_value(raw_source_summary)
    evidence_items = _list_value(retrieval_package.get("evidence_items"))
    best_score = _number_or_none(score_summary.get("best_score"))
    low_confidence_threshold, threshold_source = _low_confidence_threshold(
        retrieval_package
    )
    confidence_bucket = _optional_string(score_summary.get("confidence_bucket"))
    source_count = _number_or_none(source_summary.get("source_count"))
    document_count = _number_or_none(source_summary.get("document_count"))
    chunk_count = _number_or_none(source_summary.get("chunk_count"))
    blocking_quality_flags = _blocking_quality_flags(evidence_items)

    failed_checks: list[str] = []
    if not isinstance(raw_score_summary, dict):
        failed_checks.append("score_summary_missing")
    elif best_score is None:
        failed_checks.append("best_score_missing")
    if not evidence_items:
        failed_checks.append("evidence_items_missing")
    if confidence_bucket in BLOCKED_RETRIEVAL_CONFIDENCE_BUCKETS:
        failed_checks.append("confidence_bucket_blocked")
    if _has_non_empty_string(retrieval_package.get("no_answer_reason")):
        failed_checks.append("no_answer_reason_present")
    if blocking_quality_flags:
        failed_checks.append("blocking_quality_flags_present")
    if best_score is not None and best_score < low_confidence_threshold:
        failed_checks.append("best_score_below_threshold")
    if not isinstance(raw_source_summary, dict):
        failed_checks.append("source_summary_missing")
    elif any(count is None for count in (source_count, document_count, chunk_count)):
        failed_checks.append("source_summary_counts_missing")
    elif min(source_count, document_count, chunk_count) <= 0:
        failed_checks.append("source_summary_empty")

    status = "BLOCKED" if failed_checks else "PASS"
    return _retrieval_package_quality_guard_record(
        status=status,
        blocking_reason=failed_checks[0] if failed_checks else None,
        failed_checks=failed_checks,
        best_score=best_score,
        low_confidence_threshold=low_confidence_threshold,
        low_confidence_threshold_source=threshold_source,
        confidence_bucket=confidence_bucket,
        evidence_item_count=len(evidence_items),
        source_count=source_count,
        document_count=document_count,
        chunk_count=chunk_count,
        no_answer_reason_present=_has_non_empty_string(
            retrieval_package.get("no_answer_reason")
        ),
        blocking_quality_flags=blocking_quality_flags,
        warning_kinds=_warning_kinds(retrieval_package.get("warnings")),
    )


def evaluate_grounded_generation_boundary(
    source_payload: dict[str, Any],
    *,
    retrieval_store: RetrievalPackageStore | None,
) -> GroundedGenerationBoundaryDecision:
    stage_status = {stage: "NOT_RUN" for stage in GROUNDING_BOUNDARY_STAGES}
    compatibility_rule: dict[str, Any] | None = None
    retrieval_ref: dict[str, str] | None = None
    retrieval_package: dict[str, Any] | None = None

    try:
        compatibility_rule = select_generation_compatibility_rule(
            compatibility_payload_from_generation_request(source_payload)
        )
    except GenerationCompatibilityError as exc:
        stage_status["compatibility_rule"] = "FAIL"
        return _grounded_generation_boundary_decision(
            source_payload=source_payload,
            stage_status=stage_status,
            boundary_status="GROUNDED_BLOCKED",
            admitted=False,
            compatibility_rule=None,
            retrieval_package_ref=None,
            retrieval_package=None,
            error=exc,
            failed_stage="compatibility_rule",
        )

    stage_status["compatibility_rule"] = "PASS"
    if not compatibility_rule["grounding_required"]:
        for stage in GROUNDING_BOUNDARY_STAGES[1:]:
            stage_status[stage] = "NOT_REQUIRED"
        return _grounded_generation_boundary_decision(
            source_payload=source_payload,
            stage_status=stage_status,
            boundary_status="GROUNDING_NOT_REQUIRED",
            admitted=True,
            compatibility_rule=compatibility_rule,
            retrieval_package_ref=None,
            retrieval_package=None,
            error=None,
        )

    try:
        retrieval_ref = retrieval_package_ref_from_payload(source_payload)
    except GenerationFacadeError as exc:
        stage_status["retrieval_package_ref"] = "FAIL"
        return _grounded_generation_boundary_decision(
            source_payload=source_payload,
            stage_status=stage_status,
            boundary_status="GROUNDED_BLOCKED",
            admitted=False,
            compatibility_rule=compatibility_rule,
            retrieval_package_ref=None,
            retrieval_package=None,
            error=exc,
            failed_stage="retrieval_package_ref",
        )
    if retrieval_ref is None:
        error = GenerationFacadeError(
            status_code=422,
            error_code="cx.retrieval_package_ref_required",
            detail="Grounded generation requires retrieval_package_ref.",
        )
        stage_status["retrieval_package_ref"] = "FAIL"
        return _grounded_generation_boundary_decision(
            source_payload=source_payload,
            stage_status=stage_status,
            boundary_status="GROUNDED_BLOCKED",
            admitted=False,
            compatibility_rule=compatibility_rule,
            retrieval_package_ref=None,
            retrieval_package=None,
            error=error,
            failed_stage="retrieval_package_ref",
        )
    stage_status["retrieval_package_ref"] = "PASS"

    if retrieval_store is None:
        error = GenerationFacadeError(
            status_code=503,
            error_code="cx.retrieval_package_store_unavailable",
            detail="Grounded generation requires CX retrieval package state.",
            retryable=True,
        )
        stage_status["retrieval_package_store"] = "FAIL"
        return _grounded_generation_boundary_decision(
            source_payload=source_payload,
            stage_status=stage_status,
            boundary_status="GROUNDED_BLOCKED",
            admitted=False,
            compatibility_rule=compatibility_rule,
            retrieval_package_ref=retrieval_ref,
            retrieval_package=None,
            error=error,
            failed_stage="retrieval_package_store",
        )
    stage_status["retrieval_package_store"] = "PASS"

    retrieval_package = retrieval_store.get_retrieval_package(
        retrieval_ref["retrieval_package_id"]
    )
    if retrieval_package is None:
        error = GenerationFacadeError(
            status_code=404,
            error_code="cx.retrieval_package_not_found",
            detail=(
                "Retrieval package was not found: "
                f"{retrieval_ref['retrieval_package_id']}"
            ),
        )
        stage_status["retrieval_package_lookup"] = "FAIL"
        return _grounded_generation_boundary_decision(
            source_payload=source_payload,
            stage_status=stage_status,
            boundary_status="GROUNDED_BLOCKED",
            admitted=False,
            compatibility_rule=compatibility_rule,
            retrieval_package_ref=retrieval_ref,
            retrieval_package=None,
            error=error,
            failed_stage="retrieval_package_lookup",
        )
    stage_status["retrieval_package_lookup"] = "PASS"

    if retrieval_package["package_hash"] != retrieval_ref["package_hash"]:
        error = GenerationFacadeError(
            status_code=409,
            error_code="cx.retrieval_package_hash_mismatch",
            detail="Retrieval package hash does not match CX state.",
        )
        stage_status["package_hash"] = "FAIL"
        return _grounded_generation_boundary_decision(
            source_payload=source_payload,
            stage_status=stage_status,
            boundary_status="GROUNDED_BLOCKED",
            admitted=False,
            compatibility_rule=compatibility_rule,
            retrieval_package_ref=retrieval_ref,
            retrieval_package=retrieval_package,
            error=error,
            failed_stage="package_hash",
        )
    stage_status["package_hash"] = "PASS"

    if retrieval_package["status"] != "READY":
        error = GenerationFacadeError(
            status_code=409,
            error_code="cx.retrieval_package_not_ready",
            detail=f"Retrieval package status is {retrieval_package['status']}.",
        )
        stage_status["package_status"] = "FAIL"
        return _grounded_generation_boundary_decision(
            source_payload=source_payload,
            stage_status=stage_status,
            boundary_status="GROUNDED_BLOCKED",
            admitted=False,
            compatibility_rule=compatibility_rule,
            retrieval_package_ref=retrieval_ref,
            retrieval_package=retrieval_package,
            error=error,
            failed_stage="package_status",
        )
    stage_status["package_status"] = "PASS"

    try:
        validate_selected_evidence_ids(source_payload, retrieval_package)
    except GenerationFacadeError as exc:
        stage_status["selected_evidence"] = "FAIL"
        return _grounded_generation_boundary_decision(
            source_payload=source_payload,
            stage_status=stage_status,
            boundary_status="GROUNDED_BLOCKED",
            admitted=False,
            compatibility_rule=compatibility_rule,
            retrieval_package_ref=retrieval_ref,
            retrieval_package=retrieval_package,
            error=exc,
            failed_stage="selected_evidence",
        )
    stage_status["selected_evidence"] = "PASS"

    try:
        validate_retrieval_package_quality(retrieval_package)
    except GenerationFacadeError as exc:
        stage_status["retrieval_package_quality"] = "FAIL"
        return _grounded_generation_boundary_decision(
            source_payload=source_payload,
            stage_status=stage_status,
            boundary_status="GROUNDED_BLOCKED",
            admitted=False,
            compatibility_rule=compatibility_rule,
            retrieval_package_ref=retrieval_ref,
            retrieval_package=retrieval_package,
            error=exc,
            failed_stage="retrieval_package_quality",
        )
    stage_status["retrieval_package_quality"] = "PASS"

    return _grounded_generation_boundary_decision(
        source_payload=source_payload,
        stage_status=stage_status,
        boundary_status="GROUNDED_ADMITTED",
        admitted=True,
        compatibility_rule=compatibility_rule,
        retrieval_package_ref=retrieval_ref,
        retrieval_package=retrieval_package,
        error=None,
    )


def build_grounded_generation_boundary_audit(
    source_payload: dict[str, Any],
    *,
    retrieval_store: RetrievalPackageStore | None,
) -> dict[str, Any]:
    return evaluate_grounded_generation_boundary(
        source_payload,
        retrieval_store=retrieval_store,
    ).audit


def _grounded_generation_boundary_decision(
    *,
    source_payload: dict[str, Any],
    stage_status: dict[str, str],
    boundary_status: str,
    admitted: bool,
    compatibility_rule: dict[str, Any] | None,
    retrieval_package_ref: dict[str, str] | None,
    retrieval_package: dict[str, Any] | None,
    error: Exception | None,
    failed_stage: str | None = None,
) -> GroundedGenerationBoundaryDecision:
    audit = _build_grounded_generation_boundary_audit(
        source_payload=source_payload,
        stage_status=stage_status,
        boundary_status=boundary_status,
        admitted=admitted,
        compatibility_rule=compatibility_rule,
        retrieval_package_ref=retrieval_package_ref,
        retrieval_package=retrieval_package,
        error=error,
        failed_stage=failed_stage,
    )
    assert_grounded_generation_boundary_audit_redacted(
        audit,
        source_payload=source_payload,
        retrieval_package=retrieval_package,
    )
    return GroundedGenerationBoundaryDecision(
        admitted=admitted,
        boundary_status=boundary_status,
        compatibility_rule=compatibility_rule,
        retrieval_package_ref=retrieval_package_ref,
        retrieval_package=retrieval_package,
        error=error,
        audit=audit,
    )


def _build_grounded_generation_boundary_audit(
    *,
    source_payload: dict[str, Any],
    stage_status: dict[str, str],
    boundary_status: str,
    admitted: bool,
    compatibility_rule: dict[str, Any] | None,
    retrieval_package_ref: dict[str, str] | None,
    retrieval_package: dict[str, Any] | None,
    error: Exception | None,
    failed_stage: str | None,
) -> dict[str, Any]:
    return {
        "audit_schema_version": CX_GROUNDED_GENERATION_BOUNDARY_AUDIT_SCHEMA_VERSION,
        "boundary_id": "cx.grounded_generation.admission",
        "service_id": "nex-cx",
        "route": "POST /api/v1/generations",
        "boundary_status": boundary_status,
        "admitted": admitted,
        "request_summary": _safe_generation_request_summary(source_payload),
        "compatibility_rule": _safe_compatibility_rule_summary(compatibility_rule),
        "retrieval_package_ref": _safe_retrieval_package_ref_summary(
            retrieval_package_ref
        ),
        "retrieval_package": _safe_retrieval_package_summary(
            retrieval_package,
            source_payload=source_payload,
        ),
        "quality_guard": _safe_retrieval_package_quality_guard_summary(
            retrieval_package,
            stage_status=stage_status,
        ),
        "stage_status": dict(stage_status),
        "issues": _boundary_issues(error, failed_stage=failed_stage),
        "refactoring_checkpoint": {
            "validation_entrypoint": "evaluate_grounded_generation_boundary",
            "legacy_entrypoint": "validate_generation_request",
            "active_guard_slot": "retrieval_package_quality",
            "next_guard_slot": "grounded_response_citation_validation",
            "external_api_changed": False,
            "database_schema_changed": False,
        },
        "redaction": {
            "status": "PASS",
            "raw_prompt_included": False,
            "raw_messages_included": False,
            "raw_source_text_included": False,
            "evidence_text_included": False,
            "embedding_vector_included": False,
            "provider_endpoint_included": False,
            "storage_path_included": False,
        },
    }


def _safe_generation_request_summary(payload: dict[str, Any]) -> dict[str, Any]:
    response_format = payload.get("response_format", {"type": "text"})
    response_format_type = (
        response_format.get("type", "text")
        if isinstance(response_format, dict)
        else "text"
    )
    return {
        "source_has_messages": bool(payload.get("messages")),
        "source_has_prompt": bool(payload.get("prompt")),
        "provider_prompt_package_hash_configured": bool(
            payload.get("provider_prompt_package_hash")
        ),
        "selected_evidence_count": _safe_selected_evidence_count(payload),
        "response_format_type": response_format_type,
        "execution_mode": _optional_string(payload.get("execution_mode")),
        "generation_profile": _optional_string(payload.get("generation_profile")),
        "provider_capability": _optional_string(payload.get("provider_capability")),
        "raw_prompt_in_public_record": False,
    }


def _safe_compatibility_rule_summary(
    compatibility_rule: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if compatibility_rule is None:
        return None
    citation_policy = compatibility_rule.get("citation_policy", {})
    return {
        "compatibility_rule_id": compatibility_rule["compatibility_rule_id"],
        "execution_mode": compatibility_rule["execution_mode"],
        "generation_profile": compatibility_rule["generation_profile"],
        "grounding_required": compatibility_rule["grounding_required"],
        "citations_required": bool(citation_policy.get("citations_required")),
        "source_trace_required": bool(citation_policy.get("source_trace_required")),
    }


def _safe_retrieval_package_ref_summary(
    retrieval_package_ref: dict[str, str] | None,
) -> dict[str, Any]:
    if retrieval_package_ref is None:
        return {
            "provided": False,
            "retrieval_package_id": None,
            "package_hash": None,
        }
    return {
        "provided": True,
        "retrieval_package_id": retrieval_package_ref["retrieval_package_id"],
        "package_hash": retrieval_package_ref["package_hash"],
    }


def _safe_retrieval_package_summary(
    retrieval_package: dict[str, Any] | None,
    *,
    source_payload: dict[str, Any],
) -> dict[str, Any] | None:
    if retrieval_package is None:
        return None
    evidence_items = _list_value(retrieval_package.get("evidence_items"))
    score_summary = _mapping_value(retrieval_package.get("score_summary"))
    source_summary = _mapping_value(retrieval_package.get("source_summary"))
    warnings = _string_list_value(retrieval_package.get("warnings"))
    return {
        "retrieval_package_id": retrieval_package.get("retrieval_package_id"),
        "package_hash": retrieval_package.get("package_hash"),
        "status": retrieval_package.get("status"),
        "ready_for_generation": retrieval_package.get("status") == "READY",
        "evidence_item_count": len(evidence_items),
        "selected_evidence_count": _safe_selected_evidence_count(source_payload),
        "score_summary": {
            "best_score": score_summary.get("best_score"),
            "confidence_bucket": score_summary.get("confidence_bucket"),
            "low_confidence_threshold": score_summary.get("low_confidence_threshold"),
            "ranker_mix": score_summary.get("ranker_mix"),
            "rerank_state": score_summary.get("rerank_state"),
            "quality_policy_id": score_summary.get("quality_policy_id"),
        },
        "source_summary": {
            "source_count": source_summary.get("source_count"),
            "document_count": source_summary.get("document_count"),
            "chunk_count": source_summary.get("chunk_count"),
        },
        "no_answer_reason_present": _has_non_empty_string(
            retrieval_package.get("no_answer_reason")
        ),
        "warning_count": len(warnings),
        "warning_kinds": _warning_kinds(warnings),
    }


def _safe_retrieval_package_quality_guard_summary(
    retrieval_package: dict[str, Any] | None,
    *,
    stage_status: dict[str, str],
) -> dict[str, Any]:
    quality_stage = stage_status.get("retrieval_package_quality", "NOT_RUN")
    if quality_stage == "NOT_REQUIRED":
        return _retrieval_package_quality_guard_record(
            status="NOT_APPLICABLE",
            blocking_reason=None,
            failed_checks=[],
        )
    if quality_stage == "NOT_RUN":
        return _retrieval_package_quality_guard_record(
            status="NOT_RUN",
            blocking_reason=None,
            failed_checks=[],
        )
    return build_retrieval_package_quality_guard(retrieval_package)


def _retrieval_package_quality_guard_record(
    *,
    status: str,
    blocking_reason: str | None,
    failed_checks: list[str],
    best_score: float | None = None,
    low_confidence_threshold: float | None = None,
    low_confidence_threshold_source: str | None = None,
    confidence_bucket: str | None = None,
    evidence_item_count: int | None = None,
    source_count: float | None = None,
    document_count: float | None = None,
    chunk_count: float | None = None,
    no_answer_reason_present: bool = False,
    blocking_quality_flags: list[str] | None = None,
    warning_kinds: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "guard_schema_version": CX_RETRIEVAL_PACKAGE_QUALITY_GUARD_SCHEMA_VERSION,
        "status": status,
        "blocking_reason": blocking_reason,
        "failed_checks": list(failed_checks),
        "best_score": best_score,
        "low_confidence_threshold": low_confidence_threshold,
        "low_confidence_threshold_source": low_confidence_threshold_source,
        "confidence_bucket": confidence_bucket,
        "evidence_item_count": evidence_item_count,
        "source_summary": {
            "source_count": source_count,
            "document_count": document_count,
            "chunk_count": chunk_count,
        },
        "no_answer_reason_present": no_answer_reason_present,
        "blocking_quality_flags": sorted(blocking_quality_flags or []),
        "warning_kinds": sorted(warning_kinds or []),
    }


def _low_confidence_threshold(retrieval_package: dict[str, Any]) -> tuple[float, str]:
    score_summary = _mapping_value(retrieval_package.get("score_summary"))
    score_threshold = _number_or_none(score_summary.get("low_confidence_threshold"))
    if score_threshold is not None:
        return score_threshold, "score_summary"

    retrieval_profile = _mapping_value(retrieval_package.get("retrieval_profile"))
    confidence_policy = _mapping_value(retrieval_profile.get("confidence_policy"))
    profile_threshold = _number_or_none(
        confidence_policy.get("low_confidence_threshold")
    )
    if profile_threshold is not None:
        return profile_threshold, "retrieval_profile"

    return DEFAULT_GENERATION_LOW_CONFIDENCE_THRESHOLD, "default"


def _blocking_quality_flags(evidence_items: list[Any]) -> list[str]:
    flags: set[str] = set()
    for item in evidence_items:
        if not isinstance(item, dict):
            continue
        for flag in _string_list_value(item.get("quality_flags")):
            flag_kind = flag.split(":", 1)[0].strip()
            if flag_kind in BLOCKING_RETRIEVAL_QUALITY_FLAGS:
                flags.add(flag_kind)
    return sorted(flags)


def _warning_kinds(value: Any) -> list[str]:
    return sorted({item.split(":", 1)[0] for item in _string_list_value(value)})


def _boundary_issues(
    error: Exception | None,
    *,
    failed_stage: str | None,
) -> list[dict[str, Any]]:
    if error is None:
        return []
    issue: dict[str, Any] = {
        "stage": failed_stage or "unknown",
        "error_code": getattr(error, "error_code", error.__class__.__name__),
        "status_code": getattr(error, "status_code", 500),
        "retryable": bool(getattr(error, "retryable", False)),
    }
    return [issue]


def assert_grounded_generation_boundary_audit_redacted(
    audit: dict[str, Any],
    *,
    source_payload: dict[str, Any],
    retrieval_package: dict[str, Any] | None,
) -> None:
    serialized = json.dumps(audit, ensure_ascii=False, sort_keys=True)
    for value in _forbidden_audit_values(source_payload):
        if _protected_value_leaked(serialized, value):
            raise ValueError("grounded generation boundary audit leaked request payload")
    if retrieval_package is not None:
        for value in _forbidden_audit_values(retrieval_package):
            if _protected_value_leaked(serialized, value):
                raise ValueError(
                    "grounded generation boundary audit leaked retrieval payload"
                )


def _forbidden_audit_values(value: Any, *, parent_key: str | None = None) -> list[str]:
    if isinstance(value, dict):
        collected: list[str] = []
        for key, item in value.items():
            key_string = str(key)
            if key_string in FORBIDDEN_AUDIT_RAW_KEYS or _secretish_key(key_string):
                collected.extend(_string_values(item))
                continue
            collected.extend(_forbidden_audit_values(item, parent_key=key_string))
        return collected
    if isinstance(value, list):
        collected = []
        for item in value:
            collected.extend(_forbidden_audit_values(item, parent_key=parent_key))
        return collected
    return []


def _string_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        collected: list[str] = []
        for item in value.values():
            collected.extend(_string_values(item))
        return collected
    if isinstance(value, list):
        collected = []
        for item in value:
            collected.extend(_string_values(item))
        return collected
    return []


def _protected_value_leaked(serialized: str, value: str) -> bool:
    return len(value) >= 8 and value in serialized


def _secretish_key(key: str) -> bool:
    lowered = key.lower()
    return any(fragment in lowered for fragment in ("secret", "password", "token"))


def _safe_selected_evidence_count(payload: dict[str, Any]) -> int:
    selected = payload.get("selected_evidence_ids")
    if not isinstance(selected, list):
        return 0
    return len([item for item in selected if isinstance(item, str) and item.strip()])


def _mapping_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list_value(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _string_list_value(value: Any) -> list[str]:
    return [item for item in _list_value(value) if isinstance(item, str)]


def _number_or_none(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def _has_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def compatibility_payload_from_generation_request(payload: dict[str, Any]) -> dict[str, Any]:
    if any(field in payload for field in ("execution_mode", "generation_profile")):
        return payload
    if "retrieval_package_ref" in payload:
        return payload
    return {
        **payload,
        "execution_mode": "GENERAL_ANSWER",
        "generation_profile": "general-answer",
    }


def retrieval_package_ref_from_payload(payload: dict[str, Any]) -> dict[str, str] | None:
    ref = payload.get("retrieval_package_ref")
    if ref is None:
        return None
    if not isinstance(ref, dict):
        raise GenerationFacadeError(
            status_code=422,
            error_code="cx.retrieval_package_ref_invalid",
            detail="retrieval_package_ref must be an object.",
        )
    retrieval_package_id = _required_ref_string(ref, "retrieval_package_id")
    package_hash = _required_ref_string(ref, "package_hash")
    if len(package_hash) != 64 or any(char not in "0123456789abcdef" for char in package_hash):
        raise GenerationFacadeError(
            status_code=422,
            error_code="cx.retrieval_package_ref_invalid",
            detail="retrieval_package_ref.package_hash must be a SHA-256 hex string.",
        )
    return {
        "retrieval_package_id": retrieval_package_id,
        "package_hash": package_hash,
    }


def validate_selected_evidence_ids(
    payload: dict[str, Any],
    retrieval_package: dict[str, Any],
) -> None:
    selected_ids = selected_evidence_ids_from_payload(payload)
    if not selected_ids:
        return
    available = {item["evidence_id"] for item in retrieval_package.get("evidence_items", [])}
    missing = sorted(set(selected_ids) - available)
    if missing:
        raise GenerationFacadeError(
            status_code=422,
            error_code="cx.selected_evidence_not_in_package",
            detail=f"Selected evidence is not in retrieval package: {missing[0]}",
        )


def selected_evidence_ids_from_payload(payload: dict[str, Any]) -> list[str]:
    selected = payload.get("selected_evidence_ids", [])
    if selected is None:
        return []
    if not isinstance(selected, list) or any(
        not isinstance(item, str) or not item.strip() for item in selected
    ):
        raise GenerationFacadeError(
            status_code=422,
            error_code="cx.selected_evidence_invalid",
            detail="selected_evidence_ids must be a list of non-empty strings.",
        )
    return [item.strip() for item in selected]


def _required_ref_string(ref: dict[str, Any], field_name: str) -> str:
    value = ref.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise GenerationFacadeError(
            status_code=422,
            error_code="cx.retrieval_package_ref_invalid",
            detail=f"retrieval_package_ref.{field_name} must be a non-empty string.",
        )
    return value.strip()


def prompt_text_from_payload(payload: dict[str, Any]) -> str:
    prompt = payload.get("prompt")
    if isinstance(prompt, str) and prompt:
        return prompt

    messages = payload.get("messages")
    if isinstance(messages, list) and messages:
        parts = [
            str(message.get("content", ""))
            for message in messages
            if isinstance(message, dict) and message.get("content")
        ]
        if parts:
            return "\n".join(parts)

    raise GenerationFacadeError(
        status_code=400,
        error_code="cx.generation_request_invalid",
        detail="prompt or messages are required.",
    )


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_json(value: dict[str, Any]) -> str:
    return sha256_text(json.dumps(value, sort_keys=True, separators=(",", ":")))


def _safe_runtime_metadata(runtime_metadata: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "request_id",
        "trace_id",
        "queue_ms",
        "provider_ms",
        "total_ms",
        "route_id",
        "admission_decision",
        "provider_request_id",
    }
    return {
        key: runtime_metadata[key]
        for key in allowed
        if key in runtime_metadata
    }


def _build_failure_summary(
    *,
    failure: GenerationFacadeError,
    policy: dict[str, Any] | None,
    policy_hash: str | None,
) -> dict[str, Any]:
    return {
        "failure_code": failure.error_code,
        "failure_class": policy["failure_class"] if policy else "unclassified_failure",
        "owner_service": policy["owner_service"] if policy else "nex-cx",
        "failed_stage": FAILED_STAGE_BY_ERROR_CODE.get(failure.error_code, "FAILED"),
        "retryable": bool(failure.retryable or (policy and policy["retryable"])),
        "recovery_policy_id": policy["recovery_policy_id"] if policy else None,
        "recovery_policy_hash": policy_hash,
        "safe_message": "Generation failed before completion.",
    }


def _build_recovery_lineage(
    *,
    source_payload: dict[str, Any],
    mo_payload: dict[str, Any],
    failure: GenerationFacadeError,
    policy: dict[str, Any] | None,
    policy_hash: str | None,
    has_retrieval_package: bool,
) -> dict[str, Any]:
    return {
        "root_generation_id": _optional_string(
            source_payload.get("root_generation_id")
        )
        or mo_payload["cx_generation_id"],
        "parent_generation_id": _optional_string(
            source_payload.get("parent_generation_id")
        ),
        "attempt_no": _attempt_no_from_payload(source_payload),
        "lineage_type": policy["lineage_type"] if policy else "failure",
        "lineage_reason": failure.error_code,
        "default_recovery_action": policy["default_action"] if policy else "cancel",
        "recovery_policy_id": policy["recovery_policy_id"] if policy else None,
        "recovery_policy_hash": policy_hash,
        "retry_after_seconds": policy.get("retry_after_seconds") if policy else None,
        "max_attempts": policy["max_attempts"] if policy else 0,
        "reuse_retrieval_package": bool(
            policy["preserves_retrieval_package"] if policy else has_retrieval_package
        ),
        "changed_fields": [],
    }


def _recovery_policy_for_failure_code(error_code: str) -> dict[str, Any] | None:
    try:
        return select_generation_recovery_policy(error_code)
    except GenerationRecoveryPolicyError:
        return None


def _attempt_no_from_payload(payload: dict[str, Any]) -> int:
    value = payload.get("attempt_no", 1)
    if isinstance(value, int) and value >= 1:
        return value
    return 1


def _optional_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _authorize_cx_request(
    request: Request,
    authorization: str | None,
) -> JSONResponse | None:
    result = validate_authorization_header(
        authorization,
        expected_audience="nex-cx",
        required_scopes=[DEFAULT_SERVICE_SCOPE],
    )
    if result.ok:
        return None

    return problem_response(
        request,
        status_code=401,
        error_code=result.error_code or "SERVICE_CLAIM_INVALID",
        title="Authentication failed",
        detail=result.detail or "CX requires a valid service claim.",
        type_uri="https://nex-platform.local/problems/authentication-failed",
    )


def _generation_problem_response(
    request: Request,
    exc: GenerationFacadeError,
) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="Generation request failed",
        detail=exc.detail,
        retryable=exc.retryable,
        type_uri="https://nex-platform.local/problems/generation-request-failed",
    )


def _safe_response_json(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except json.JSONDecodeError:
        return {}
    if isinstance(payload, dict):
        return payload
    return {}


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
