from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import NAMESPACE_URL, uuid5

from nex_mo.provider_registry import ProviderRouteError


class ExecutionConfigView(Protocol):
    model_revision: str
    deployment_id: str


def normalize_remote_generation_response(
    *,
    provider_payload: Any,
    alias: str,
    route_id: str,
    config: ExecutionConfigView,
    request_id: str,
    trace_id: str,
    input_texts: list[str],
) -> dict[str, Any]:
    if not isinstance(provider_payload, dict):
        raise _response_invalid(
            error_code_prefix="mo.remote_generation",
            detail="Remote generation response must be a JSON object.",
        )
    choices = provider_payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise _response_invalid(
            error_code_prefix="mo.remote_generation",
            detail="Remote generation response must include non-empty choices.",
        )
    first_choice = choices[0]
    output_text = _choice_output_text(first_choice)
    finish_reason = _finish_reason_from_choice(first_choice)
    provider_request_id = provider_payload.get("id")
    if not isinstance(provider_request_id, str) or not provider_request_id:
        provider_request_id = str(
            uuid5(
                NAMESPACE_URL,
                _stable_json(
                    {
                        "alias": alias,
                        "trace_id": trace_id,
                        "output_text": output_text,
                    }
                ),
            )
        )
    now = _utc_now()
    return {
        "mo_generation_id": provider_request_id,
        "alias": alias,
        "model_revision": config.model_revision,
        "deployment_id": config.deployment_id,
        "provider_type": "vllm",
        "output": {"type": "text", "text": output_text},
        "finish_reason": finish_reason,
        "usage": _normalize_usage(provider_payload.get("usage"), input_texts),
        "runtime_metadata": {
            "request_id": request_id,
            "trace_id": trace_id,
            "queue_ms": 0,
            "provider_ms": 0,
            "total_ms": 0,
            "route_id": route_id,
            "admission_decision": "ACCEPTED",
            "provider_request_id": provider_request_id,
        },
        "created_at": now,
        "updated_at": now,
    }


def normalize_remote_embedding_response(
    *,
    provider_payload: Any,
    alias: str,
    config: ExecutionConfigView,
    input_count: int,
    input_texts: list[str],
) -> dict[str, Any]:
    if not isinstance(provider_payload, dict):
        raise _response_invalid(
            error_code_prefix="mo.remote_embedding",
            detail="Remote embedding response must be a JSON object.",
        )
    response_items = _embedding_response_items(provider_payload)
    if not isinstance(response_items, list) or len(response_items) != input_count:
        raise _response_invalid(
            error_code_prefix="mo.remote_embedding",
            detail="Remote embedding response count did not match request count.",
        )
    normalized_items = [
        {
            "object": "embedding",
            "index": _embedding_item_index(item, index),
            "embedding": _embedding_vector_from_item(item),
        }
        for index, item in enumerate(response_items)
    ]
    return {
        "object": provider_payload.get("object", "list"),
        "alias": alias,
        "model_revision": config.model_revision,
        "deployment_id": config.deployment_id,
        "data": normalized_items,
        "usage": _normalize_usage(provider_payload.get("usage"), input_texts),
    }


def normalize_remote_rerank_response(
    *,
    provider_payload: Any,
    alias: str,
    config: ExecutionConfigView,
    documents: list[str],
    query: str,
) -> dict[str, Any]:
    if not isinstance(provider_payload, dict):
        raise _response_invalid(
            error_code_prefix="mo.remote_reranker",
            detail="Remote reranker response must be a JSON object.",
        )
    response_items = provider_payload.get("results", provider_payload.get("data"))
    if not isinstance(response_items, list) or not response_items:
        raise _response_invalid(
            error_code_prefix="mo.remote_reranker",
            detail="Remote reranker response must include non-empty results.",
        )
    normalized_items = [
        _normalize_rerank_item(item, rank=index, documents=documents)
        for index, item in enumerate(response_items)
    ]
    normalized_items.sort(key=lambda item: item["score"], reverse=True)
    return {
        "alias": alias,
        "model_revision": config.model_revision,
        "deployment_id": config.deployment_id,
        "results": normalized_items,
        "usage": _normalize_usage(provider_payload.get("usage"), [query, *documents]),
    }


def _choice_output_text(choice: Any) -> str:
    if not isinstance(choice, dict):
        raise _response_invalid(
            error_code_prefix="mo.remote_generation",
            detail="Remote generation choice must be an object.",
        )
    message = choice.get("message")
    content = message.get("content") if isinstance(message, dict) else choice.get("text")
    if not isinstance(content, str) or not content:
        raise _response_invalid(
            error_code_prefix="mo.remote_generation",
            detail="Remote generation output text was missing.",
        )
    return content


def _finish_reason_from_choice(choice: Any) -> str:
    if not isinstance(choice, dict):
        raise _response_invalid(
            error_code_prefix="mo.remote_generation",
            detail="Remote generation choice must be an object.",
        )
    raw_finish_reason = choice.get("finish_reason", "stop")
    if not isinstance(raw_finish_reason, str) or not raw_finish_reason:
        return "UNKNOWN"
    return {
        "stop": "STOP",
        "length": "LENGTH",
        "content_filter": "CONTENT_FILTER",
        "tool_calls": "TOOL_CALLS",
    }.get(raw_finish_reason, raw_finish_reason.upper())


def _embedding_item_index(item: Any, fallback: int) -> int:
    if isinstance(item, dict) and isinstance(item.get("index"), int):
        return item["index"]
    return fallback


def _embedding_response_items(payload: dict[str, Any]) -> Any:
    data = payload.get("data")
    if isinstance(data, list):
        return data
    embeddings = payload.get("embeddings")
    if isinstance(embeddings, list):
        return [{"embedding": embedding} for embedding in embeddings]
    return data


def _embedding_vector_from_item(item: Any) -> list[float]:
    if not isinstance(item, dict):
        raise _response_invalid(
            error_code_prefix="mo.remote_embedding",
            detail="Remote embedding item must be an object.",
        )
    vector = item.get("embedding")
    if not isinstance(vector, list) or not vector or not all(
        isinstance(value, int | float) and not isinstance(value, bool)
        for value in vector
    ):
        raise _response_invalid(
            error_code_prefix="mo.remote_embedding",
            detail="Remote embedding vector must be a non-empty numeric list.",
        )
    return [float(value) for value in vector]


def _normalize_rerank_item(
    item: Any,
    *,
    rank: int,
    documents: list[str],
) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise _response_invalid(
            error_code_prefix="mo.remote_reranker",
            detail="Remote reranker item must be an object.",
        )
    index = item.get("index", rank)
    if not isinstance(index, int) or isinstance(index, bool) or index < 0:
        raise _response_invalid(
            error_code_prefix="mo.remote_reranker",
            detail="Remote reranker item index must be a non-negative integer.",
        )
    return {
        "index": index,
        "score": _rerank_score_from_item(item),
        "document": _rerank_document_from_item(item, index=index, documents=documents),
    }


def _rerank_score_from_item(item: dict[str, Any]) -> float:
    value = item.get("score", item.get("relevance_score"))
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise _response_invalid(
            error_code_prefix="mo.remote_reranker",
            detail="Remote reranker score must be numeric.",
        )
    return round(float(value), 6)


def _rerank_document_from_item(
    item: dict[str, Any],
    *,
    index: int,
    documents: list[str],
) -> str:
    document = item.get("document")
    if isinstance(document, str):
        return document
    if isinstance(document, dict) and isinstance(document.get("text"), str):
        return document["text"]
    return documents[index] if index < len(documents) else ""


def _normalize_usage(value: Any, input_texts: list[str]) -> dict[str, int]:
    usage = value if isinstance(value, dict) else {}
    input_tokens = _int_usage_value(
        usage,
        "input_tokens",
        "prompt_tokens",
        default=sum(_token_count(text) for text in input_texts),
    )
    output_tokens = _int_usage_value(
        usage,
        "output_tokens",
        "completion_tokens",
        default=0,
    )
    total_tokens = _int_usage_value(
        usage,
        "total_tokens",
        default=input_tokens + output_tokens,
    )
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


def _int_usage_value(
    usage: dict[str, Any],
    key: str,
    fallback_key: str | None = None,
    *,
    default: int,
) -> int:
    value = usage.get(key)
    if value is None and fallback_key is not None:
        value = usage.get(fallback_key)
    if isinstance(value, int) and not isinstance(value, bool):
        return max(0, value)
    return default


def _token_count(text: str) -> int:
    return max(1, len(text.split()))


def _response_invalid(*, error_code_prefix: str, detail: str) -> ProviderRouteError:
    return ProviderRouteError(
        status_code=502,
        error_code=f"{error_code_prefix}_response_invalid",
        detail=detail,
        retryable=True,
        degraded=True,
        failure_kind="malformed_response",
    )


def _stable_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
