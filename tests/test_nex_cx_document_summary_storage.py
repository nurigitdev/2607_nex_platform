from __future__ import annotations

import json
from pathlib import Path
import runpy
import sys

import pytest

from nex_cx.access_context import CxAccessContext
from nex_cx.document_summary_storage import (
    load_document_summary_text,
    persist_document_summary_text,
)
from nex_cx.ingestion import (
    ContentIngestionStore,
    CxStorageConfig,
    build_upload_registration,
    sha256_text,
)
from nex_cx.private_content import CxPrivateContentError
from nex_cx.private_text_store import FileSystemCxPrivateTextStore
import run_cx_document_summary_storage_smoke as smoke


def _context(subject_id: str = "employee-0953") -> CxAccessContext:
    return CxAccessContext(
        caller_service_id="nex-cx",
        tenant_id="tenant-0953",
        subject_id=subject_id,
        request_id="request-0953",
        trace_id="95300000000000000000000000000001",
        scopes=("service:call",),
    )


def _summary(text: str = "Owner-private durable summary") -> dict[str, object]:
    return {
        "document_summary_id": "summary-0953",
        "document_id": "document-0953",
        "summary_text_sha256": sha256_text(text),
        "summary_storage_uri": "memory://cx/document-summaries/summary-0953.md",
    }


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


def _content_store_with_document(
    tmp_path: Path,
) -> tuple[ContentIngestionStore, dict[str, object]]:
    store = ContentIngestionStore(
        private_summary_text_store=FileSystemCxPrivateTextStore(
            tmp_path / "private-text"
        )
    )
    document = build_upload_registration(
        {
            "filename": "source.md",
            "content_type": "text/markdown",
            "source_sha256": "a" * 64,
            "size_bytes": 42,
            "tenant_id": "tenant-0953",
            "owner_user_id": "employee-0953",
        },
        storage_config=_storage_config(tmp_path),
        request_id="request-0953",
        trace_id="95300000000000000000000000000001",
    )
    store.save_upload_registration(document)
    return store, document


def test_summary_storage_persists_and_reloads_after_adapter_restart(tmp_path: Path) -> None:
    text = "Owner-private durable summary"
    record = persist_document_summary_text(
        private_text_store=FileSystemCxPrivateTextStore(tmp_path),
        access_context=_context(),
        summary=_summary(text),
        summary_text=text,
    )

    reloaded = load_document_summary_text(
        private_text_store=FileSystemCxPrivateTextStore(tmp_path),
        access_context=_context(),
        summary=record,
    )

    assert reloaded == text
    assert record["summary_storage_uri"].startswith(
        "cx-private://filesystem-text-v1/"
    )
    assert text not in json.dumps(record)


def test_summary_storage_cross_owner_lookup_is_indistinguishable_from_missing(
    tmp_path: Path,
) -> None:
    text = "Owner-private durable summary"
    record = persist_document_summary_text(
        private_text_store=FileSystemCxPrivateTextStore(tmp_path),
        access_context=_context(),
        summary=_summary(text),
        summary_text=text,
    )

    assert load_document_summary_text(
        private_text_store=FileSystemCxPrivateTextStore(tmp_path),
        access_context=_context("employee-other"),
        summary=record,
    ) is None


def test_summary_storage_rejects_text_hash_mismatch(tmp_path: Path) -> None:
    with pytest.raises(CxPrivateContentError) as exc:
        persist_document_summary_text(
            private_text_store=FileSystemCxPrivateTextStore(tmp_path),
            access_context=_context(),
            summary=_summary("expected"),
            summary_text="different",
        )

    assert exc.value.error_code == "CX_SUMMARY_TEXT_HASH_MISMATCH"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("document_summary_id", ""),
        ("summary_text_sha256", "not-a-hash"),
    ],
)
def test_summary_storage_rejects_invalid_metadata(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    summary = _summary()
    summary[field] = value

    with pytest.raises(CxPrivateContentError) as exc:
        persist_document_summary_text(
            private_text_store=FileSystemCxPrivateTextStore(tmp_path),
            access_context=_context(),
            summary=summary,
            summary_text="Owner-private durable summary",
        )

    assert exc.value.error_code == "CX_SUMMARY_STORAGE_METADATA_INVALID"


def test_summary_storage_rejects_non_private_reload_reference(tmp_path: Path) -> None:
    with pytest.raises(CxPrivateContentError) as exc:
        load_document_summary_text(
            private_text_store=FileSystemCxPrivateTextStore(tmp_path),
            access_context=_context(),
            summary=_summary(),
        )

    assert exc.value.error_code == "CX_SUMMARY_STORAGE_REFERENCE_INVALID"


def test_content_store_uses_durable_summary_port_and_refills_cache(
    tmp_path: Path,
) -> None:
    private_root = tmp_path / "private-text"
    store, document = _content_store_with_document(tmp_path)
    text = "Owner-private durable summary"
    summary = {
        **_summary(text),
        "document_id": document["document_id"],
        "request_id": "request-0953",
        "trace_id": "95300000000000000000000000000001",
    }

    stored = store.save_document_summary(summary, summary_text=text)
    store.summary_texts.clear()
    store.private_summary_text_store = FileSystemCxPrivateTextStore(private_root)

    assert stored["summary_storage_uri"].startswith("cx-private://")
    assert store.get_summary_text("summary-0953") == text
    assert store.summary_texts["summary-0953"] == text


def test_content_store_durable_reload_handles_missing_metadata_and_payload(
    tmp_path: Path,
) -> None:
    store, document = _content_store_with_document(tmp_path)

    assert store.get_summary_text("missing-summary") is None

    summary = {
        **_summary(),
        "document_id": document["document_id"],
        "summary_storage_uri": (
            "cx-private://filesystem-text-v1/redacted/summary_text/redacted"
        ),
    }
    store.document_summaries[str(document["document_id"])] = summary

    assert store.get_summary_text("summary-0953") is None


def test_content_store_requires_owner_lineage_for_durable_summary(
    tmp_path: Path,
) -> None:
    store = ContentIngestionStore(
        private_summary_text_store=FileSystemCxPrivateTextStore(tmp_path)
    )

    with pytest.raises(CxPrivateContentError) as exc:
        store.save_document_summary(_summary(), summary_text="Owner-private durable summary")

    assert exc.value.error_code == "CX_SUMMARY_OWNER_LINEAGE_MISSING"


def test_document_summary_storage_smoke_and_cli(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = smoke.run_cx_document_summary_storage_smoke(tmp_path / "direct")
    assert result["status"] == "PASS"
    assert result["passed_checks"] == 8
    assert result["remote_provider_required"] is False
    assert "summary_text" not in json.dumps(result)

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_cx_document_summary_storage_smoke.py",
            "--summary",
            "--storage-root",
            str(tmp_path / "cli"),
        ],
    )
    with pytest.raises(SystemExit) as exited:
        runpy.run_module("run_cx_document_summary_storage_smoke", run_name="__main__")

    assert exited.value.code == 0
    assert "cx_document_summary_storage=pass" in capsys.readouterr().out


def test_document_summary_storage_smoke_main_reports_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_cx_document_summary_storage_smoke",
        lambda _root: {
            "status": "FAIL",
            "passed_checks": 7,
            "checks_total": 8,
            "restart_reload": False,
            "postgres_required": False,
            "remote_provider_required": False,
        },
    )

    assert smoke.main(["--summary"]) == 1
    assert "cx_document_summary_storage=fail" in capsys.readouterr().out
