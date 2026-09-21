from __future__ import annotations

import json
import math
import runpy
import sys

import pytest

from nex_cx.access_context import CxAccessContext
from nex_cx.private_content import (
    CX_PRIVATE_PAYLOAD_KEY_SCHEMA_VERSION,
    CX_PRIVATE_PAYLOAD_RECEIPT_SCHEMA_VERSION,
    CxPrivateContentError,
    CxPrivateTextStore,
    CxVectorStore,
    assert_private_payload_access,
    build_private_payload_key,
    build_private_payload_receipt,
    normalize_private_vector,
    sha256_private_text,
    sha256_private_vector,
    validate_private_text,
)
import run_cx_private_content_capability_contract as contract


def _context(
    *, tenant_id: str = "tenant-a", subject_id: str = "employee-1004"
) -> CxAccessContext:
    return CxAccessContext(
        caller_service_id="nex-ae-api",
        tenant_id=tenant_id,
        subject_id=subject_id,
        request_id="request-0914",
        trace_id="91400000000000000000000000000001",
        scopes=("service:call",),
    )


def _key(payload_kind: str = "summary_text"):
    return build_private_payload_key(
        _context(), payload_kind=payload_kind, content_id="content-0914"
    )


def test_private_payload_key_is_owner_scoped_and_metadata_only() -> None:
    key = _key()

    assert key.to_wire() == {
        "key_schema_version": CX_PRIVATE_PAYLOAD_KEY_SCHEMA_VERSION,
        "tenant_ref": {"type": "oa.tenant", "id": "tenant-a"},
        "owner_subject_ref": {"type": "oa.user", "id": "employee-1004"},
        "payload_kind": "summary_text",
        "content_id": "content-0914",
    }
    assert_private_payload_access(_context(), key)


@pytest.mark.parametrize("payload_kind", ["", "source_text", "raw_prompt"])
def test_private_payload_key_rejects_unsupported_kind(payload_kind: str) -> None:
    with pytest.raises(CxPrivateContentError) as caught:
        build_private_payload_key(
            _context(), payload_kind=payload_kind, content_id="content-0914"
        )

    assert caught.value.error_code == "CX_PRIVATE_PAYLOAD_KIND_INVALID"


@pytest.mark.parametrize(
    ("context", "content_id"),
    [
        (_context(tenant_id="tenant with spaces"), "content-0914"),
        (_context(subject_id="../employee"), "content-0914"),
        (_context(), "../content"),
        (_context(), None),
    ],
)
def test_private_payload_key_rejects_unsafe_segments(
    context: CxAccessContext,
    content_id: object,
) -> None:
    with pytest.raises(CxPrivateContentError) as caught:
        build_private_payload_key(
            context, payload_kind="chunk_text", content_id=content_id  # type: ignore[arg-type]
        )

    assert caught.value.error_code == "CX_PRIVATE_PAYLOAD_KEY_INVALID"


@pytest.mark.parametrize(
    "other_context",
    [_context(tenant_id="tenant-b"), _context(subject_id="employee-2000")],
)
def test_private_payload_access_hides_cross_owner_data(
    other_context: CxAccessContext,
) -> None:
    with pytest.raises(CxPrivateContentError) as caught:
        assert_private_payload_access(other_context, _key())

    assert caught.value.status_code == 404
    assert caught.value.error_code == "CX_PRIVATE_PAYLOAD_NOT_FOUND"


def test_private_text_contract_verifies_integrity() -> None:
    text = "Confidential text"
    expected = sha256_private_text(text)

    assert validate_private_text(key=_key(), text=text, expected_sha256=expected) == text


def test_private_text_contract_rejects_wrong_kind_and_type() -> None:
    with pytest.raises(CxPrivateContentError) as kind_error:
        validate_private_text(
            key=_key("chunk_embedding"), text="text", expected_sha256="0" * 64
        )
    with pytest.raises(CxPrivateContentError) as type_error:
        validate_private_text(key=_key(), text=b"text", expected_sha256="0" * 64)

    assert kind_error.value.error_code == "CX_PRIVATE_TEXT_KIND_INVALID"
    assert type_error.value.error_code == "CX_PRIVATE_TEXT_INVALID"


@pytest.mark.parametrize("expected", ["bad", "A" * 64])
def test_private_text_contract_rejects_invalid_hash(expected: str) -> None:
    with pytest.raises(CxPrivateContentError) as caught:
        validate_private_text(key=_key(), text="text", expected_sha256=expected)

    assert caught.value.error_code == "CX_PRIVATE_PAYLOAD_HASH_INVALID"


def test_private_text_contract_rejects_hash_mismatch() -> None:
    with pytest.raises(CxPrivateContentError) as caught:
        validate_private_text(key=_key(), text="text", expected_sha256="0" * 64)

    assert caught.value.status_code == 409
    assert caught.value.error_code == "CX_PRIVATE_PAYLOAD_HASH_MISMATCH"


def test_private_vector_contract_normalizes_and_verifies_integrity() -> None:
    vector = [1, -0.5, 0.25]
    expected = sha256_private_vector(vector)

    assert normalize_private_vector(
        key=_key("chunk_embedding"),
        vector=vector,
        expected_sha256=expected,
    ) == (1.0, -0.5, 0.25)


def test_private_vector_contract_rejects_wrong_kind() -> None:
    with pytest.raises(CxPrivateContentError) as caught:
        normalize_private_vector(
            key=_key(), vector=[1.0], expected_sha256="0" * 64
        )

    assert caught.value.error_code == "CX_PRIVATE_VECTOR_KIND_INVALID"


@pytest.mark.parametrize("vector", [None, [], "1,2", b"123"])
def test_private_vector_contract_rejects_invalid_container(vector: object) -> None:
    with pytest.raises(CxPrivateContentError) as caught:
        normalize_private_vector(
            key=_key("summary_embedding"),
            vector=vector,
            expected_sha256="0" * 64,
        )

    assert caught.value.error_code == "CX_PRIVATE_VECTOR_INVALID"


@pytest.mark.parametrize("value", [True, "1", math.inf, math.nan])
def test_private_vector_contract_rejects_invalid_value(value: object) -> None:
    with pytest.raises(CxPrivateContentError) as caught:
        normalize_private_vector(
            key=_key("summary_embedding"),
            vector=[value],
            expected_sha256="0" * 64,
        )

    assert caught.value.error_code == "CX_PRIVATE_VECTOR_INVALID"


def test_private_vector_contract_rejects_hash_mismatch() -> None:
    with pytest.raises(CxPrivateContentError) as caught:
        normalize_private_vector(
            key=_key("summary_embedding"),
            vector=[1.0],
            expected_sha256="0" * 64,
        )

    assert caught.value.error_code == "CX_PRIVATE_PAYLOAD_HASH_MISMATCH"


def test_private_payload_receipt_carries_only_storage_metadata() -> None:
    key = _key("summary_embedding")
    receipt = build_private_payload_receipt(
        key=key,
        storage_backend="memory-contract",
        storage_uri="cx-private://memory-contract/content-0914",
        sha256="a" * 64,
        size_bytes=24,
        vector_dimension=3,
    )

    assert receipt.to_wire() == {
        "receipt_schema_version": CX_PRIVATE_PAYLOAD_RECEIPT_SCHEMA_VERSION,
        "key": key.to_wire(),
        "storage_backend": "memory-contract",
        "storage_uri": "cx-private://memory-contract/content-0914",
        "sha256": "a" * 64,
        "size_bytes": 24,
        "vector_dimension": 3,
    }

    text_receipt = build_private_payload_receipt(
        key=_key(),
        storage_backend="memory-contract",
        storage_uri="cx-private://memory-contract/content-0914",
        sha256="b" * 64,
        size_bytes=4,
    )
    assert text_receipt.vector_dimension is None


@pytest.mark.parametrize(
    ("overrides", "error_code"),
    [
        ({"storage_backend": "bad backend"}, "CX_PRIVATE_PAYLOAD_KEY_INVALID"),
        ({"storage_uri": "file:///private"}, "CX_PRIVATE_STORAGE_URI_INVALID"),
        ({"sha256": "bad"}, "CX_PRIVATE_PAYLOAD_HASH_INVALID"),
        ({"size_bytes": True}, "CX_PRIVATE_PAYLOAD_SIZE_INVALID"),
        ({"size_bytes": -1}, "CX_PRIVATE_PAYLOAD_SIZE_INVALID"),
        ({"vector_dimension": None}, "CX_PRIVATE_VECTOR_DIMENSION_INVALID"),
        ({"vector_dimension": True}, "CX_PRIVATE_VECTOR_DIMENSION_INVALID"),
        ({"vector_dimension": 0}, "CX_PRIVATE_VECTOR_DIMENSION_INVALID"),
    ],
)
def test_private_vector_receipt_rejects_invalid_metadata(
    overrides: dict[str, object],
    error_code: str,
) -> None:
    values: dict[str, object] = {
        "key": _key("summary_embedding"),
        "storage_backend": "memory-contract",
        "storage_uri": "cx-private://memory-contract/content-0914",
        "sha256": "a" * 64,
        "size_bytes": 8,
        "vector_dimension": 1,
    }
    values.update(overrides)
    with pytest.raises(CxPrivateContentError) as caught:
        build_private_payload_receipt(**values)  # type: ignore[arg-type]

    assert caught.value.error_code == error_code


def test_private_text_receipt_rejects_vector_dimension() -> None:
    with pytest.raises(CxPrivateContentError) as caught:
        build_private_payload_receipt(
            key=_key(),
            storage_backend="memory-contract",
            storage_uri="cx-private://memory-contract/content-0914",
            sha256="a" * 64,
            size_bytes=4,
            vector_dimension=1,
        )

    assert caught.value.error_code == "CX_PRIVATE_TEXT_DIMENSION_INVALID"


def test_private_content_protocols_are_runtime_checkable() -> None:
    probe = contract._CapabilityProbe()

    assert isinstance(probe, CxPrivateTextStore)
    assert isinstance(probe, CxVectorStore)
    assert not isinstance(object(), CxPrivateTextStore)
    assert not isinstance(object(), CxVectorStore)


@pytest.mark.parametrize(
    "method_name",
    [
        "put_text",
        "get_text",
        "delete_text",
        "put_vector",
        "get_vector",
        "delete_vector",
    ],
)
def test_capability_probe_has_no_storage_implementation(method_name: str) -> None:
    with pytest.raises(NotImplementedError):
        getattr(contract._CapabilityProbe(), method_name)()


def test_private_content_contract_evidence_and_cli(monkeypatch, capsys) -> None:
    evidence = contract.run_cx_private_content_capability_contract()
    assert evidence["status"] == "PASS"
    assert evidence["summary"]["passed_check_count"] == 6
    assert evidence["summary"]["check_count"] == 6

    monkeypatch.setattr(
        contract,
        "run_cx_private_content_capability_contract",
        lambda: evidence,
    )
    assert contract.main(["--summary"]) == 0
    assert "checks=6/6" in capsys.readouterr().out
    assert contract.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        contract,
        "run_cx_private_content_capability_contract",
        lambda: {"status": "FAIL"},
    )
    assert contract.main([]) == 1
    assert "checks=0/0" in contract.summary_line({"status": "FAIL"})


def test_private_content_contract_module_entrypoint(monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", [contract.__file__, "--summary"])

    with pytest.raises(SystemExit) as caught:
        runpy.run_path(contract.__file__, run_name="__main__")

    assert caught.value.code == 0
