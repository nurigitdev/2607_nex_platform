from __future__ import annotations

import json
from pathlib import Path
import runpy
import sys
from typing import Any

import pytest

from nex_cx.document_summary_generation import (
    DEFAULT_SUMMARY_MODEL_PROFILE,
    DocumentSummaryGenerationError,
    build_document_summary_generation_payload,
    generate_document_summary,
    normalize_document_summary_generation_response,
)
from nex_cx.generation import GenerationFacadeError
from nex_cx.ingestion import (
    ContentIngestionStore,
    CxStorageConfig,
    build_upload_registration,
    run_text_extraction_job,
    sha256_text,
)
from nex_cx.prompts import seed_cx_prompt_registry
from nex_cx.summaries import SummaryError, build_and_store_document_summary
from nex_runtime.prompts import PromptRegistryStore
import run_cx_document_summary_generation_adapter as smoke


REQUEST_ID = "request-0954"
TRACE_ID = "95400000000000000000000000000001"
MARKDOWN = "# Architecture\n\nThe approved deployment date is 2026-10-01."


class FakeSummaryGenerationClient:
    def __init__(self, response: object | None = None) -> None:
        self.response = response if response is not None else _response()
        self.calls: list[dict[str, Any]] = []

    def create_generation(
        self,
        payload: dict[str, Any],
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        self.calls.append(
            {"payload": payload, "request_id": request_id, "trace_id": trace_id}
        )
        return self.response  # type: ignore[return-value]


class FailingSummaryGenerationClient:
    def create_generation(
        self,
        payload: dict[str, Any],
        *,
        request_id: str,
        trace_id: str,
    ) -> dict[str, Any]:
        raise GenerationFacadeError(
            status_code=504,
            error_code="mo.provider_timeout",
            detail="Provider timed out.",
            retryable=True,
        )


def _response(text: str = "Deployment is approved for 2026-10-01.") -> dict[str, Any]:
    return {
        "mo_generation_id": "mo-summary-0954",
        "alias": "general-llm-default",
        "model_revision": "Qwen3.5-4B",
        "deployment_id": "mock-generation-local",
        "provider_type": "mock-generation",
        "output": {"type": "text", "text": text},
        "finish_reason": "STOP",
        "usage": {"input_tokens": 20, "output_tokens": 8, "total_tokens": 28},
    }


def _payload(**overrides: Any) -> dict[str, Any]:
    values = {
        "markdown_text": MARKDOWN,
        "source_markdown_sha256": sha256_text(MARKDOWN),
        "system_prompt": "Summarize under 900 characters.",
        "trace_id": TRACE_ID,
        "summary_max_chars": 900,
        "summary_hard_limit_chars": 1000,
    }
    values.update(overrides)
    return build_document_summary_generation_payload(**values)


def _storage_config(tmp_path: Path) -> CxStorageConfig:
    return CxStorageConfig(
        data_root=tmp_path,
        source_root=tmp_path / "source",
        extracted_markdown_root=tmp_path / "markdown",
        extraction_temp_root=tmp_path / "temp",
        chunk_policy="chunk_1000_100",
        chunk_size=1000,
        chunk_overlap=100,
        bm25_tokenizer="mecab_ko",
        bm25_tokenizer_fallback="korean_mixed_v1",
    )


def _store_with_extraction(tmp_path: Path) -> tuple[ContentIngestionStore, str]:
    store = ContentIngestionStore()
    config = _storage_config(tmp_path)
    document = build_upload_registration(
        {
            "filename": "source.md",
            "content_type": "text/markdown",
            "content_text": MARKDOWN,
        },
        storage_config=config,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    store.save_upload_registration(document, source_text=MARKDOWN)
    extraction = run_text_extraction_job(
        document["extraction"]["job_id"],
        store=store,
        storage_config=config,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )
    return store, str(extraction["document_id"])


def test_summary_generation_payload_keeps_raw_markdown_out_of_metadata() -> None:
    payload = _payload()

    assert payload["alias"] == "general-llm-default"
    assert payload["generation_profile"] == "document-summary"
    assert payload["reasoning_mode"] == "disabled"
    assert payload["timeout_ms"] == 60_000
    assert payload["messages"][1]["content"].endswith(MARKDOWN)
    assert payload["metadata"]["model_profile_id"] == DEFAULT_SUMMARY_MODEL_PROFILE
    assert MARKDOWN not in json.dumps(payload["metadata"])
    assert len(payload["provider_prompt_package_hash"]) == 64


@pytest.mark.parametrize(
    "overrides",
    [
        {"markdown_text": " "},
        {"system_prompt": ""},
        {"source_markdown_sha256": "bad"},
        {"trace_id": ""},
        {"summary_max_chars": 0},
        {"summary_hard_limit_chars": 1001},
        {"summary_max_chars": 901, "summary_hard_limit_chars": 900},
        {"alias": ""},
        {"model_profile_id": ""},
    ],
)
def test_summary_generation_payload_rejects_invalid_contract(
    overrides: dict[str, Any],
) -> None:
    with pytest.raises(DocumentSummaryGenerationError):
        _payload(**overrides)


def test_generate_document_summary_calls_mo_and_returns_safe_lineage() -> None:
    client = FakeSummaryGenerationClient()

    result = generate_document_summary(
        client=client,
        markdown_text=MARKDOWN,
        source_markdown_sha256=sha256_text(MARKDOWN),
        system_prompt="Summarize under 900 characters.",
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
        summary_max_chars=900,
        summary_hard_limit_chars=1000,
    )

    assert result["summary_text"] == "Deployment is approved for 2026-10-01."
    assert result["provider"]["model_profile_id"] == DEFAULT_SUMMARY_MODEL_PROFILE
    assert result["provider"]["usage"]["total_tokens"] == 28
    assert client.calls[0]["request_id"] == REQUEST_ID
    assert client.calls[0]["trace_id"] == TRACE_ID
    assert "runtime_metadata" not in result["provider"]


@pytest.mark.parametrize(
    ("response", "error_code"),
    [
        ([], "cx.summary_generation_response_invalid"),
        ({**_response(), "output": []}, "cx.summary_generation_response_invalid"),
        (
            {**_response(), "output": {"type": "json", "text": "summary"}},
            "cx.summary_generation_response_invalid",
        ),
        (
            {**_response(), "output": {"type": "text", "text": " "}},
            "cx.summary_generation_response_invalid",
        ),
        (
            {**_response(), "output": {"type": "text", "text": "x" * 1001}},
            "cx.summary_generation_hard_limit_exceeded",
        ),
        (
            {**_response(), "finish_reason": "LENGTH"},
            "cx.summary_generation_incomplete",
        ),
        (
            {**_response(), "model_revision": ""},
            "cx.summary_generation_response_invalid",
        ),
    ],
)
def test_summary_generation_response_fails_closed(
    response: object,
    error_code: str,
) -> None:
    with pytest.raises(DocumentSummaryGenerationError) as exc:
        normalize_document_summary_generation_response(
            response,
            request_payload=_payload(),
            summary_hard_limit_chars=1000,
        )

    assert exc.value.error_code == error_code
    assert exc.value.retryable is True


def test_summary_generation_response_filters_invalid_usage_values() -> None:
    response = _response()
    response["usage"] = {
        "input_tokens": 2,
        "output_tokens": True,
        "total_tokens": -1,
        "private": 99,
    }

    result = normalize_document_summary_generation_response(
        response,
        request_payload=_payload(),
        summary_hard_limit_chars=1000,
    )

    assert result["provider"]["usage"] == {"input_tokens": 2}

    response["usage"] = None
    without_usage = normalize_document_summary_generation_response(
        response,
        request_payload=_payload(),
        summary_hard_limit_chars=1000,
    )
    assert without_usage["provider"]["usage"] == {}


def test_summary_service_uses_generation_adapter_and_prompt_registry(
    tmp_path: Path,
) -> None:
    store, document_id = _store_with_extraction(tmp_path)
    prompt_store = PromptRegistryStore()
    seed_cx_prompt_registry(prompt_store)
    client = FakeSummaryGenerationClient()

    summary = build_and_store_document_summary(
        document_id,
        store=store,
        prompt_store=prompt_store,
        generation_client=client,
        request_id=REQUEST_ID,
        trace_id=TRACE_ID,
    )

    event = prompt_store.get_render_event(summary["prompt_render_event_id"])
    assert summary["summary_preview"] == "Deployment is approved for 2026-10-01."
    assert summary["summarizer"]["mode"] == "mo_generation"
    assert summary["summarizer"]["model_profile_id"] == DEFAULT_SUMMARY_MODEL_PROFILE
    assert event is not None
    assert event["output_hash"] == sha256_text(summary["summary_preview"])
    assert client.calls[0]["payload"]["messages"][0]["role"] == "system"


@pytest.mark.parametrize(
    ("client", "error_code"),
    [
        (
            FakeSummaryGenerationClient(response={"output": None}),
            "cx.summary_generation_response_invalid",
        ),
        (FailingSummaryGenerationClient(), "mo.provider_timeout"),
    ],
)
def test_summary_service_maps_generation_failures(
    tmp_path: Path,
    client: object,
    error_code: str,
) -> None:
    store, document_id = _store_with_extraction(tmp_path)

    with pytest.raises(SummaryError) as exc:
        build_and_store_document_summary(
            document_id,
            store=store,
            generation_client=client,  # type: ignore[arg-type]
            request_id=REQUEST_ID,
            trace_id=TRACE_ID,
        )

    assert exc.value.error_code == error_code
    assert exc.value.retryable is True


def test_summary_generation_adapter_smoke_and_cli(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = smoke.run_cx_document_summary_generation_adapter()
    assert result["status"] == "PASS"
    assert result["passed_checks"] == 10
    assert result["live_provider_required"] is False
    assert MARKDOWN not in json.dumps(result)

    monkeypatch.setattr(
        sys,
        "argv",
        ["run_cx_document_summary_generation_adapter.py", "--summary"],
    )
    with pytest.raises(SystemExit) as exited:
        runpy.run_module(
            "run_cx_document_summary_generation_adapter",
            run_name="__main__",
        )

    assert exited.value.code == 0
    assert "cx_document_summary_generation_adapter=pass" in capsys.readouterr().out


def test_summary_generation_adapter_smoke_main_reports_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_cx_document_summary_generation_adapter",
        lambda: {
            "status": "FAIL",
            "passed_checks": 9,
            "checks_total": 10,
            "model_profile_id": DEFAULT_SUMMARY_MODEL_PROFILE,
            "live_provider_required": False,
        },
    )

    assert smoke.main(["--summary"]) == 1
    assert "cx_document_summary_generation_adapter=fail" in capsys.readouterr().out
