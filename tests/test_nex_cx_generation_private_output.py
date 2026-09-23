from __future__ import annotations

import json
from pathlib import Path

import pytest

from nex_cx.access_context import CxAccessContext
from nex_cx.generation_private_output import (
    DEFAULT_GENERATION_OUTPUT_STORAGE_ROOT,
    GENERATION_OUTPUT_STORAGE_ROOT_ENV,
    build_generation_output_store,
    load_generation_output,
    persist_generation_output,
)
from nex_cx.private_content import CxPrivateContentError, sha256_private_text
from nex_cx.private_text_store import FileSystemCxPrivateTextStore


def _context(subject_id: str = "employee-0964") -> CxAccessContext:
    return CxAccessContext(
        caller_service_id="nex-cx",
        tenant_id="tenant-0964",
        subject_id=subject_id,
        request_id="request-0964",
        trace_id="96400000000000000000000000000001",
        scopes=("service:call",),
    )


def _persist(tmp_path: Path, text: str = "Grounded private output [1]."):
    return persist_generation_output(
        private_text_store=FileSystemCxPrivateTextStore(tmp_path),
        access_context=_context(),
        cx_generation_id="generation-0964",
        output_text=text,
        expected_sha256=sha256_private_text(text),
    )


def test_generation_output_persists_and_reloads_after_adapter_restart(
    tmp_path: Path,
) -> None:
    text = "Grounded private output with 한국어 evidence [1]."
    metadata = _persist(tmp_path, text)

    reloaded = load_generation_output(
        private_text_store=FileSystemCxPrivateTextStore(tmp_path),
        access_context=_context(),
        cx_generation_id="generation-0964",
        metadata=metadata,
    )

    serialized = json.dumps(metadata, sort_keys=True)
    assert reloaded == text
    assert metadata["output_storage_uri"].startswith(
        "cx-private://filesystem-text-v1/"
    )
    assert metadata["output_size_bytes"] == len(text.encode("utf-8"))
    assert text not in serialized
    assert "tenant-0964" not in serialized
    assert "employee-0964" not in serialized
    assert "generation-0964" not in serialized


def test_generation_output_cross_owner_lookup_is_indistinguishable_from_missing(
    tmp_path: Path,
) -> None:
    metadata = _persist(tmp_path)

    assert load_generation_output(
        private_text_store=FileSystemCxPrivateTextStore(tmp_path),
        access_context=_context("employee-other"),
        cx_generation_id="generation-0964",
        metadata=metadata,
    ) is None


@pytest.mark.parametrize("output_text", ["", "   ", None])
def test_generation_output_rejects_empty_or_non_text_payload(
    tmp_path: Path,
    output_text: object,
) -> None:
    with pytest.raises(CxPrivateContentError) as caught:
        persist_generation_output(
            private_text_store=FileSystemCxPrivateTextStore(tmp_path),
            access_context=_context(),
            cx_generation_id="generation-0964",
            output_text=output_text,  # type: ignore[arg-type]
            expected_sha256="0" * 64,
        )

    assert caught.value.error_code == "CX_GENERATION_OUTPUT_INVALID"


def test_generation_output_rejects_hash_mismatch(tmp_path: Path) -> None:
    with pytest.raises(CxPrivateContentError) as caught:
        persist_generation_output(
            private_text_store=FileSystemCxPrivateTextStore(tmp_path),
            access_context=_context(),
            cx_generation_id="generation-0964",
            output_text="private",
            expected_sha256="0" * 64,
        )

    assert caught.value.error_code == "CX_GENERATION_OUTPUT_HASH_MISMATCH"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("private_output_schema_version", "old.v1"),
        ("output_storage_backend", ""),
        ("output_storage_backend", None),
        ("output_storage_uri", "file:///private"),
        ("output_storage_uri", None),
        ("output_sha256", "bad"),
        ("output_sha256", "A" * 64),
        ("output_sha256", None),
        ("output_size_bytes", True),
        ("output_size_bytes", 0),
        ("output_size_bytes", None),
    ],
)
def test_generation_output_rejects_invalid_reload_metadata(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    metadata = _persist(tmp_path)
    metadata[field] = value

    with pytest.raises(CxPrivateContentError) as caught:
        load_generation_output(
            private_text_store=FileSystemCxPrivateTextStore(tmp_path),
            access_context=_context(),
            cx_generation_id="generation-0964",
            metadata=metadata,
        )

    assert caught.value.error_code == "CX_GENERATION_OUTPUT_METADATA_INVALID"


def test_generation_output_rejects_metadata_size_mismatch(tmp_path: Path) -> None:
    metadata = _persist(tmp_path)
    metadata["output_size_bytes"] += 1

    with pytest.raises(CxPrivateContentError) as caught:
        load_generation_output(
            private_text_store=FileSystemCxPrivateTextStore(tmp_path),
            access_context=_context(),
            cx_generation_id="generation-0964",
            metadata=metadata,
        )

    assert caught.value.error_code == "CX_GENERATION_OUTPUT_SIZE_MISMATCH"


def test_generation_output_store_builder_uses_override_and_default(
    tmp_path: Path,
) -> None:
    overridden = build_generation_output_store(
        {GENERATION_OUTPUT_STORAGE_ROOT_ENV: str(tmp_path)}
    )
    defaulted = build_generation_output_store({})

    assert overridden.root == tmp_path.resolve()
    assert defaulted.root == DEFAULT_GENERATION_OUTPUT_STORAGE_ROOT
