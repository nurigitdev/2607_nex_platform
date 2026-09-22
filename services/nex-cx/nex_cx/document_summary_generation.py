from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
from typing import Any

from nex_cx.generation import MoGenerationClient


DEFAULT_SUMMARY_GENERATION_ALIAS = "general-llm-default"
DEFAULT_SUMMARY_MODEL_PROFILE = "Qwen3.5-122B-A10B-NVFP4"
DEFAULT_SUMMARY_MAX_OUTPUT_TOKENS = 512
DEFAULT_SUMMARY_TIMEOUT_MS = 60_000


@dataclass(frozen=True)
class DocumentSummaryGenerationError(Exception):
    status_code: int
    error_code: str
    detail: str
    retryable: bool = False


def build_document_summary_generation_payload(
    *,
    markdown_text: str,
    source_markdown_sha256: str,
    system_prompt: str,
    trace_id: str,
    summary_max_chars: int,
    summary_hard_limit_chars: int,
    alias: str = DEFAULT_SUMMARY_GENERATION_ALIAS,
    model_profile_id: str = DEFAULT_SUMMARY_MODEL_PROFILE,
) -> dict[str, Any]:
    source_hash = _sha256(source_markdown_sha256, "source_markdown_sha256")
    prompt = _required_text(system_prompt, "system_prompt")
    markdown = _required_text(markdown_text, "markdown_text")
    _summary_limits(summary_max_chars, summary_hard_limit_chars)
    prompt_package_hash = hashlib.sha256(
        json.dumps(
            {
                "system_prompt": prompt,
                "source_markdown_sha256": source_hash,
                "summary_max_chars": summary_max_chars,
                "summary_hard_limit_chars": summary_hard_limit_chars,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return {
        "request_schema_version": "cx_document_summary_generation_request.v1",
        "trace_id": _required_text(trace_id, "trace_id"),
        "provider_prompt_package_hash": prompt_package_hash,
        "alias": _required_text(alias, "alias"),
        "provider_capability": "generation",
        "workload_class": "LLM_BATCH",
        "generation_profile": "document-summary",
        "messages": [
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": f"Extracted Markdown:\n\n{markdown}",
            },
        ],
        "response_format": {"type": "text"},
        "max_output_tokens": DEFAULT_SUMMARY_MAX_OUTPUT_TOKENS,
        "temperature": 0.0,
        "stream": False,
        "timeout_ms": DEFAULT_SUMMARY_TIMEOUT_MS,
        "metadata": {
            "purpose": "document_summary",
            "model_profile_id": _required_text(model_profile_id, "model_profile_id"),
            "source_markdown_sha256": source_hash,
            "summary_max_chars": summary_max_chars,
            "summary_hard_limit_chars": summary_hard_limit_chars,
        },
    }


def generate_document_summary(
    *,
    client: MoGenerationClient,
    markdown_text: str,
    source_markdown_sha256: str,
    system_prompt: str,
    request_id: str,
    trace_id: str,
    summary_max_chars: int,
    summary_hard_limit_chars: int,
    alias: str = DEFAULT_SUMMARY_GENERATION_ALIAS,
    model_profile_id: str = DEFAULT_SUMMARY_MODEL_PROFILE,
) -> dict[str, Any]:
    payload = build_document_summary_generation_payload(
        markdown_text=markdown_text,
        source_markdown_sha256=source_markdown_sha256,
        system_prompt=system_prompt,
        trace_id=trace_id,
        summary_max_chars=summary_max_chars,
        summary_hard_limit_chars=summary_hard_limit_chars,
        alias=alias,
        model_profile_id=model_profile_id,
    )
    response = client.create_generation(
        payload,
        request_id=_required_text(request_id, "request_id"),
        trace_id=trace_id,
    )
    return normalize_document_summary_generation_response(
        response,
        request_payload=payload,
        summary_hard_limit_chars=summary_hard_limit_chars,
    )


def normalize_document_summary_generation_response(
    response: object,
    *,
    request_payload: Mapping[str, Any],
    summary_hard_limit_chars: int,
) -> dict[str, Any]:
    if not isinstance(response, Mapping):
        raise _invalid_response("MO summary generation response must be an object.")
    output = response.get("output")
    if not isinstance(output, Mapping) or output.get("type") != "text":
        raise _invalid_response("MO summary generation output must be text.")
    summary_text = output.get("text")
    if not isinstance(summary_text, str) or not summary_text.strip():
        raise _invalid_response("MO summary generation output text must not be empty.")
    normalized_text = summary_text.strip()
    if len(normalized_text) > summary_hard_limit_chars:
        raise DocumentSummaryGenerationError(
            status_code=502,
            error_code="cx.summary_generation_hard_limit_exceeded",
            detail="Generated summary exceeded the configured hard limit.",
            retryable=True,
        )
    finish_reason = _required_text(response.get("finish_reason"), "finish_reason")
    if finish_reason.upper() in {"LENGTH", "MAX_TOKENS"}:
        raise DocumentSummaryGenerationError(
            status_code=502,
            error_code="cx.summary_generation_incomplete",
            detail="Generated summary stopped before completion.",
            retryable=True,
        )
    metadata = request_payload.get("metadata")
    model_profile_id = (
        metadata.get("model_profile_id") if isinstance(metadata, Mapping) else None
    )
    return {
        "summary_text": normalized_text,
        "provider": {
            "provider": _required_text(response.get("alias"), "alias"),
            "mode": "mo_generation",
            "model_profile_id": _required_text(
                model_profile_id,
                "model_profile_id",
            ),
            "model_revision": _required_text(
                response.get("model_revision"),
                "model_revision",
            ),
            "deployment_id": _required_text(
                response.get("deployment_id"),
                "deployment_id",
            ),
            "provider_type": _required_text(
                response.get("provider_type"),
                "provider_type",
            ),
            "mo_generation_id": _required_text(
                response.get("mo_generation_id"),
                "mo_generation_id",
            ),
            "finish_reason": finish_reason,
            "usage": _safe_usage(response.get("usage")),
            "provider_prompt_package_hash": _sha256(
                request_payload.get("provider_prompt_package_hash"),
                "provider_prompt_package_hash",
            ),
        },
    }


def _safe_usage(value: object) -> dict[str, int]:
    if not isinstance(value, Mapping):
        return {}
    return {
        key: item
        for key in ("input_tokens", "output_tokens", "total_tokens")
        if isinstance((item := value.get(key)), int)
        and not isinstance(item, bool)
        and item >= 0
    }


def _summary_limits(max_chars: int, hard_limit_chars: int) -> None:
    if (
        isinstance(max_chars, bool)
        or not isinstance(max_chars, int)
        or max_chars <= 0
        or isinstance(hard_limit_chars, bool)
        or not isinstance(hard_limit_chars, int)
        or not 1 <= hard_limit_chars <= 1000
        or max_chars > hard_limit_chars
    ):
        raise DocumentSummaryGenerationError(
            status_code=500,
            error_code="cx.summary_generation_policy_invalid",
            detail="Summary generation limits are invalid.",
        )


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DocumentSummaryGenerationError(
            status_code=502,
            error_code="cx.summary_generation_response_invalid",
            detail=f"Summary generation field {field} is invalid.",
            retryable=True,
        )
    return value.strip()


def _sha256(value: object, field: str) -> str:
    text = _required_text(value, field).lower()
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise DocumentSummaryGenerationError(
            status_code=502,
            error_code="cx.summary_generation_response_invalid",
            detail=f"Summary generation field {field} is not a SHA-256 value.",
            retryable=True,
        )
    return text


def _invalid_response(detail: str) -> DocumentSummaryGenerationError:
    return DocumentSummaryGenerationError(
        status_code=502,
        error_code="cx.summary_generation_response_invalid",
        detail=detail,
        retryable=True,
    )
