from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

from nex_runtime import (
    DEFAULT_SERVICE_SCOPE,
    problem_response,
    request_id_from_headers,
    trace_id_from_headers,
    validate_authorization_header,
)
from nex_runtime.prompts import (
    PromptRegistryError,
    PromptRegistryStore,
    render_prompt_from_binding,
)

from nex_cx.ingestion import ContentIngestionStore, sha256_text
from nex_cx.prompts import CX_DOCUMENT_SUMMARY_BINDING


DEFAULT_SUMMARY_CHUNK_POLICY = "summary_1000_0"
DEFAULT_SUMMARY_MAX_CHARS = 900
DEFAULT_SUMMARY_HARD_LIMIT_CHARS = 1000
DEFAULT_SUMMARIZER_PROFILE = "mock-document-summary"


@dataclass(frozen=True)
class SummaryError(Exception):
    status_code: int
    error_code: str
    detail: str
    retryable: bool = False


def register_summary_routes(
    app: FastAPI,
    *,
    store: ContentIngestionStore,
    prompt_store: PromptRegistryStore | None = None,
) -> None:
    @app.post("/api/v1/documents/{document_id}/summary/run", response_model=None)
    def run_summary(
        document_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_cx_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        try:
            return build_and_store_document_summary(
                document_id,
                store=store,
                prompt_store=prompt_store,
                request_id=request_id_from_headers(request),
                trace_id=trace_id_from_headers(request),
            )
        except SummaryError as exc:
            return _summary_problem_response(request, exc)

    @app.get("/api/v1/documents/{document_id}/summary", response_model=None)
    def get_summary(
        document_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        auth_problem = _authorize_cx_request(request, authorization)
        if auth_problem is not None:
            return auth_problem

        summary = store.get_document_summary(document_id)
        if summary is None:
            return _summary_problem_response(
                request,
                SummaryError(
                    status_code=404,
                    error_code="cx.document_summary_not_found",
                    detail=f"Document summary was not found: {document_id}",
                ),
            )
        return summary


def build_and_store_document_summary(
    document_id: str,
    *,
    store: ContentIngestionStore,
    prompt_store: PromptRegistryStore | None = None,
    request_id: str,
    trace_id: str,
    max_chars: int = DEFAULT_SUMMARY_MAX_CHARS,
    hard_limit_chars: int = DEFAULT_SUMMARY_HARD_LIMIT_CHARS,
) -> dict[str, Any]:
    extraction = store.get_extraction_result(document_id)
    if extraction is None:
        raise SummaryError(
            status_code=404,
            error_code="cx.extraction_result_not_found",
            detail=f"Extraction result was not found: {document_id}",
        )

    markdown_path = Path(extraction["extracted_markdown_path"])
    if not markdown_path.exists():
        raise SummaryError(
            status_code=409,
            error_code="cx.extracted_markdown_missing",
            detail=f"Extracted Markdown file was not found: {markdown_path}",
            retryable=True,
        )

    markdown_text = markdown_path.read_text(encoding="utf-8")
    summary_text = summarize_markdown_text(
        markdown_text,
        max_chars=max_chars,
        hard_limit_chars=hard_limit_chars,
    )
    prompt_event = render_summary_prompt_event(
        prompt_store=prompt_store,
        request_id=request_id,
        trace_id=trace_id,
        max_chars=max_chars,
        hard_limit_chars=hard_limit_chars,
        output_text=summary_text,
    )
    record = build_document_summary_record(
        document_id=document_id,
        extraction=extraction,
        summary_text=summary_text,
        prompt_event=prompt_event,
        request_id=request_id,
        trace_id=trace_id,
        max_chars=max_chars,
        hard_limit_chars=hard_limit_chars,
    )
    return store.save_document_summary(record, summary_text=summary_text)


def render_summary_prompt_event(
    *,
    prompt_store: PromptRegistryStore | None,
    request_id: str,
    trace_id: str,
    max_chars: int,
    hard_limit_chars: int,
    output_text: str,
) -> dict[str, Any] | None:
    if prompt_store is None:
        return None

    try:
        result = render_prompt_from_binding(
            prompt_store,
            binding_key=CX_DOCUMENT_SUMMARY_BINDING,
            variables={
                "summary_max_chars": max_chars,
                "summary_hard_limit_chars": hard_limit_chars,
            },
            request_id=request_id,
            trace_id=trace_id,
            output_text=output_text,
        )
    except PromptRegistryError as exc:
        raise SummaryError(
            status_code=exc.status_code,
            error_code=exc.error_code,
            detail=exc.detail,
        ) from exc
    return result["render_event"]


def summarize_markdown_text(
    markdown_text: str,
    *,
    max_chars: int = DEFAULT_SUMMARY_MAX_CHARS,
    hard_limit_chars: int = DEFAULT_SUMMARY_HARD_LIMIT_CHARS,
) -> str:
    validate_summary_limits(max_chars=max_chars, hard_limit_chars=hard_limit_chars)
    normalized = normalize_markdown_for_summary(markdown_text)
    if not normalized:
        normalized = "No extractable text was available for this document."
    if len(normalized) <= max_chars:
        return normalized
    return trim_to_limit(normalized, max_chars)


def validate_summary_limits(*, max_chars: int, hard_limit_chars: int) -> None:
    if max_chars <= 0:
        raise SummaryError(
            status_code=500,
            error_code="cx.summary_policy_invalid",
            detail="summary max_chars must be positive.",
        )
    if hard_limit_chars <= 0 or hard_limit_chars > DEFAULT_SUMMARY_HARD_LIMIT_CHARS:
        raise SummaryError(
            status_code=500,
            error_code="cx.summary_policy_invalid",
            detail="summary hard_limit_chars must be between 1 and 1000.",
        )
    if max_chars > hard_limit_chars:
        raise SummaryError(
            status_code=500,
            error_code="cx.summary_policy_invalid",
            detail="summary max_chars must not exceed hard_limit_chars.",
        )


def normalize_markdown_for_summary(markdown_text: str) -> str:
    lines = []
    for raw_line in markdown_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        lines.append(line.lstrip("#").strip())
    return " ".join(lines)


def trim_to_limit(text: str, max_chars: int) -> str:
    if max_chars <= 3:
        return text[:max_chars]
    return f"{text[: max_chars - 3].rstrip()}..."


def build_document_summary_record(
    *,
    document_id: str,
    extraction: dict[str, Any],
    summary_text: str,
    prompt_event: dict[str, Any] | None = None,
    request_id: str,
    trace_id: str,
    max_chars: int,
    hard_limit_chars: int,
) -> dict[str, Any]:
    if len(summary_text) > hard_limit_chars:
        raise SummaryError(
            status_code=502,
            error_code="cx.summary_hard_limit_exceeded",
            detail="Document summary exceeded the hard limit.",
            retryable=True,
        )

    now = _utc_now()
    summary_hash = sha256_text(summary_text)
    document_summary_id = str(
        uuid5(
            NAMESPACE_URL,
            f"cx-document-summary:{document_id}:{extraction['extracted_markdown_sha256']}:{summary_hash}",
        )
    )
    return {
        "document_summary_schema_version": "cx_document_summary.v1",
        "document_summary_id": document_summary_id,
        "document_id": document_id,
        "extraction_job_id": extraction["job_id"],
        "trace_id": trace_id,
        "request_id": request_id,
        "status": "READY",
        "summary_chunk_policy_id": DEFAULT_SUMMARY_CHUNK_POLICY,
        "summary_text_sha256": summary_hash,
        "summary_char_count": len(summary_text),
        "summary_max_chars": max_chars,
        "summary_hard_limit_chars": hard_limit_chars,
        "summary_preview": summary_text[:240],
        "summary_storage_uri": f"memory://cx/document-summaries/{document_summary_id}.md",
        "source_markdown_sha256": extraction["extracted_markdown_sha256"],
        "prompt_template_version_id": (
            prompt_event["prompt_template_version_id"] if prompt_event else None
        ),
        "prompt_render_event_id": (
            prompt_event["prompt_render_event_id"] if prompt_event else None
        ),
        "provider_prompt_package_hash": (
            prompt_event["rendered_prompt_hash"] if prompt_event else None
        ),
        "summarizer": {
            "provider": "local_mock",
            "mode": "markdown_summary",
            "model_profile_id": DEFAULT_SUMMARIZER_PROFILE,
            "model_revision": "slice-0027",
        },
        "created_at": now,
        "updated_at": now,
    }


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


def _summary_problem_response(request: Request, exc: SummaryError) -> JSONResponse:
    return problem_response(
        request,
        status_code=exc.status_code,
        error_code=exc.error_code,
        title="Document summary request failed",
        detail=exc.detail,
        retryable=exc.retryable,
        type_uri="https://nex-platform.local/problems/document-summary-failed",
    )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
