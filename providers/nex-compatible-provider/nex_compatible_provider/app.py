from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator


DEFAULT_EMBEDDING_MODEL = "Qwen3-embedding-4B"
DEFAULT_RERANKER_MODEL = "Qwen3-Reranker-0.6B"
DEFAULT_RERANKER_PROVIDER_MODEL_ID = "Qwen/Qwen3-Reranker-0.6B"
DEFAULT_MODEL_ROOT = "/data/nex-platform/models"
DEFAULT_MOCK_DIMENSIONS = 8
PRIVATE_RUNTIME_KEY_PATTERN = re.compile(r"(path|dir|url|token|secret|password|key)")


class EmbeddingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str = Field(min_length=1)
    input: str | list[str]
    encoding_format: Literal["float", "base64"] | None = None
    dimensions: int | None = Field(default=None, ge=1)
    user: str | None = Field(default=None, min_length=1)

    @field_validator("input")
    @classmethod
    def input_must_not_be_empty(cls, value: str | list[str]) -> str | list[str]:
        if isinstance(value, str):
            if not value:
                raise ValueError("input must not be empty")
            return value
        if not value:
            raise ValueError("input must not be empty")
        if any(not item for item in value):
            raise ValueError("input items must not be empty")
        return value

    def texts(self) -> list[str]:
        return [self.input] if isinstance(self.input, str) else list(self.input)


class RerankRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str = Field(min_length=1)
    query: str = Field(min_length=1)
    documents: list[str] = Field(min_length=1)
    top_n: int | None = Field(default=None, ge=1)
    return_documents: bool = False

    @field_validator("documents")
    @classmethod
    def documents_must_not_be_empty(cls, value: list[str]) -> list[str]:
        if any(not document for document in value):
            raise ValueError("documents must not contain empty strings")
        return value


@dataclass(frozen=True)
class CompatibleProviderSettings:
    provider_capability: Literal["embedding", "reranking"] = "embedding"
    provider_backend: str = "mock"
    model_root: str = DEFAULT_MODEL_ROOT
    embedding_model: str = DEFAULT_EMBEDDING_MODEL
    reranker_model: str = DEFAULT_RERANKER_MODEL
    provider_model_id: str | None = None
    model_revision: str | None = None
    precision_policy: Literal["bf16_required", "fp16_allowed", "mock_no_model"] = (
        "mock_no_model"
    )
    requested_torch_dtype: Literal["bfloat16", "float16", "float32", "mock"] = "mock"
    loaded_parameter_dtype: Literal["bfloat16", "float16", "float32", "mock"] = "mock"
    device: str = "mock"
    embedding_dimensions: int = DEFAULT_MOCK_DIMENSIONS

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> CompatibleProviderSettings:
        env = environ if environ is not None else os.environ
        capability = _env_choice(
            env,
            "NEX_COMPAT_PROVIDER_CAPABILITY",
            {"embedding", "reranking"},
            "embedding",
        )
        backend = env.get("NEX_COMPAT_PROVIDER_BACKEND", "mock")
        mock_backend = backend == "mock"
        model_name = _model_name_for_capability(env, capability)
        return cls(
            provider_capability=capability,  # type: ignore[arg-type]
            provider_backend=backend,
            model_root=env.get("NEX_COMPAT_PROVIDER_MODEL_ROOT", DEFAULT_MODEL_ROOT),
            embedding_model=env.get("NEX_COMPAT_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL),
            reranker_model=env.get("NEX_COMPAT_RERANKER_MODEL", DEFAULT_RERANKER_MODEL),
            provider_model_id=env.get(
                "NEX_COMPAT_PROVIDER_MODEL_ID",
                _default_provider_model_id(capability, model_name),
            ),
            model_revision=env.get("NEX_COMPAT_MODEL_REVISION", model_name),
            precision_policy=_env_choice(
                env,
                "NEX_COMPAT_PRECISION_POLICY",
                {"bf16_required", "fp16_allowed", "mock_no_model"},
                "mock_no_model" if mock_backend else "bf16_required",
            ),
            requested_torch_dtype=_env_choice(
                env,
                "NEX_COMPAT_REQUESTED_TORCH_DTYPE",
                {"bfloat16", "float16", "float32", "mock"},
                "mock" if mock_backend else "bfloat16",
            ),
            loaded_parameter_dtype=_env_choice(
                env,
                "NEX_COMPAT_LOADED_PARAMETER_DTYPE",
                {"bfloat16", "float16", "float32", "mock"},
                "mock" if mock_backend else "bfloat16",
            ),
            device=env.get("NEX_COMPAT_PROVIDER_DEVICE", "mock" if mock_backend else "cuda"),
            embedding_dimensions=_positive_int(
                env.get("NEX_COMPAT_EMBEDDING_DIMENSIONS"),
                DEFAULT_MOCK_DIMENSIONS,
            ),
        )

    @property
    def model_name(self) -> str:
        if self.provider_capability == "embedding":
            return self.embedding_model
        return self.reranker_model

    @property
    def resolved_provider_model_id(self) -> str:
        return self.provider_model_id or _default_provider_model_id(
            self.provider_capability,
            self.model_name,
        )

    @property
    def resolved_model_revision(self) -> str:
        return self.model_revision or self.model_name

    @property
    def dtype_match(self) -> bool:
        return self.requested_torch_dtype == self.loaded_parameter_dtype

    @property
    def ready(self) -> bool:
        if self.precision_policy == "mock_no_model":
            return self.provider_backend == "mock" and self.dtype_match
        if self.precision_policy == "bf16_required":
            return (
                self.requested_torch_dtype == "bfloat16"
                and self.loaded_parameter_dtype == "bfloat16"
                and self.dtype_match
            )
        return self.dtype_match


def create_app(settings: CompatibleProviderSettings | None = None) -> FastAPI:
    resolved_settings = settings or CompatibleProviderSettings.from_env()
    app = FastAPI(
        title="NeX Compatible Provider",
        version="0.0.0-slice0065",
        description="Mock-first compatible provider source skeleton.",
    )

    @app.get("/healthz")
    def healthz(response: Response) -> dict[str, Any]:
        payload = build_health_payload(resolved_settings)
        if payload["status"] != "READY":
            response.status_code = 503
        return payload

    @app.post("/v1/embeddings")
    def create_embeddings(payload: EmbeddingRequest) -> dict[str, Any]:
        _require_capability(resolved_settings, "embedding")
        _require_model(payload.model, resolved_settings.embedding_model)
        texts = payload.texts()
        dimensions = payload.dimensions or resolved_settings.embedding_dimensions
        prompt_tokens = sum(_token_count(text) for text in texts)
        return {
            "object": "list",
            "model": resolved_settings.embedding_model,
            "data": [
                {
                    "object": "embedding",
                    "embedding": _deterministic_vector(
                        f"{resolved_settings.embedding_model}\n{text}",
                        dimensions,
                    ),
                    "index": index,
                }
                for index, text in enumerate(texts)
            ],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "total_tokens": prompt_tokens,
            },
        }

    @app.post("/v1/rerank")
    def create_rerank(payload: RerankRequest) -> dict[str, Any]:
        _require_capability(resolved_settings, "reranking")
        _require_model(payload.model, resolved_settings.reranker_model)
        ranked = _rank_documents(payload.query, payload.documents)
        selected = ranked[: payload.top_n or len(ranked)]
        prompt_tokens = _token_count(payload.query) + sum(
            _token_count(document) for document in payload.documents
        )
        return {
            "model": resolved_settings.reranker_model,
            "results": [
                _rerank_result(
                    index=item["index"],
                    score=item["score"],
                    document=item["document"],
                    return_document=payload.return_documents,
                )
                for item in selected
            ],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "total_tokens": prompt_tokens,
            },
        }

    return app


def build_health_payload(settings: CompatibleProviderSettings) -> dict[str, Any]:
    metadata = _safe_runtime_metadata(
        {
            "backend": settings.provider_backend,
            "request_shape": _request_shape_for(settings.provider_capability),
            "embedding_dimensions": settings.embedding_dimensions
            if settings.provider_capability == "embedding"
            else None,
        }
    )
    return {
        "provider_health_schema_version": "compatible_provider_health.v1",
        "status": "READY" if settings.ready else "DEGRADED",
        "provider_capability": settings.provider_capability,
        "provider_type": f"nex-compatible-{settings.provider_backend}",
        "provider_model_id": settings.resolved_provider_model_id,
        "model_name": settings.model_name,
        "model_revision": settings.resolved_model_revision,
        "precision_policy": settings.precision_policy,
        "requested_torch_dtype": settings.requested_torch_dtype,
        "loaded_parameter_dtype": settings.loaded_parameter_dtype,
        "dtype_match": settings.dtype_match,
        "device": settings.device,
        "checked_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "runtime_metadata": metadata,
    }


def _require_capability(
    settings: CompatibleProviderSettings,
    capability: Literal["embedding", "reranking"],
) -> None:
    if settings.provider_capability != capability:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "provider.capability_not_enabled",
                "expected_capability": capability,
                "actual_capability": settings.provider_capability,
            },
        )


def _require_model(requested_model: str, configured_model: str) -> None:
    if requested_model != configured_model:
        raise HTTPException(
            status_code=404,
            detail={
                "error_code": "provider.model_not_available",
                "requested_model": requested_model,
            },
        )


def _rank_documents(query: str, documents: list[str]) -> list[dict[str, Any]]:
    return sorted(
        [
            {
                "index": index,
                "document": document,
                "score": _mock_relevance_score(query, document, index),
            }
            for index, document in enumerate(documents)
        ],
        key=lambda item: (-item["score"], item["index"]),
    )


def _rerank_result(
    *,
    index: int,
    score: float,
    document: str,
    return_document: bool,
) -> dict[str, Any]:
    result: dict[str, Any] = {"index": index, "score": score}
    if return_document:
        result["document"] = document
    return result


def _deterministic_vector(seed: str, dimensions: int) -> list[float]:
    values: list[float] = []
    counter = 0
    while len(values) < dimensions:
        digest = hashlib.sha256(f"{seed}\n{counter}".encode("utf-8")).digest()
        for offset in range(0, len(digest), 4):
            integer = int.from_bytes(digest[offset : offset + 4], "big")
            values.append(round((integer / 2**32) * 2 - 1, 6))
            if len(values) == dimensions:
                break
        counter += 1
    return values


def _mock_relevance_score(query: str, document: str, index: int) -> float:
    query_terms = _terms(query)
    document_terms = _terms(document)
    lexical_score = 0.0
    if query_terms:
        lexical_score = len(query_terms & document_terms) / len(query_terms)
    tie_breaker = _deterministic_tie_breaker(f"{query}\n{document}\n{index}")
    return round(min(1.0, lexical_score * 0.95 + tie_breaker * 0.05), 6)


def _deterministic_tie_breaker(seed: str) -> float:
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    integer = int.from_bytes(digest[:4], "big")
    return integer / 2**32


def _terms(text: str) -> set[str]:
    return {
        term
        for term in re.split(r"[^0-9A-Za-z가-힣]+", text.lower())
        if term
    }


def _token_count(text: str) -> int:
    return max(1, len(text.split()))


def _env_choice(
    env: dict[str, str],
    key: str,
    allowed: set[str],
    default: str,
) -> str:
    value = env.get(key, default)
    if value not in allowed:
        return default
    return value


def _positive_int(raw_value: str | None, default: int) -> int:
    if raw_value is None:
        return default
    try:
        value = int(raw_value)
    except ValueError:
        return default
    return value if value > 0 else default


def _model_name_for_capability(env: dict[str, str], capability: str) -> str:
    if capability == "reranking":
        return env.get("NEX_COMPAT_RERANKER_MODEL", DEFAULT_RERANKER_MODEL)
    return env.get("NEX_COMPAT_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL)


def _default_provider_model_id(capability: str, model_name: str) -> str:
    if capability == "reranking" and model_name == DEFAULT_RERANKER_MODEL:
        return DEFAULT_RERANKER_PROVIDER_MODEL_ID
    return model_name


def _request_shape_for(capability: str) -> str:
    if capability == "reranking":
        return "nex_rerank_v1"
    return "openai_embeddings"


def _safe_runtime_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in metadata.items()
        if value is not None and PRIVATE_RUNTIME_KEY_PATTERN.search(key) is None
    }


app = create_app()
