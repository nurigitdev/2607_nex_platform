from __future__ import annotations

import hashlib

import pytest

from nex_cx.document_intelligence import (
    DocumentIntelligenceContractError,
    build_summary_generation_profile,
    build_summary_manifest,
    build_summary_source_snapshot,
    evaluate_summary_freshness,
    public_summary_manifest,
)


def _hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _source(label: str = "a"):
    return build_summary_source_snapshot(
        document_id="document-a",
        content_object_id="content-a",
        extraction_artifact_id=f"artifact-{label}",
        source_markdown_sha256=_hex(f"source-{label}"),
    )


def _profile(revision: str = "v1", *, prompt: str | None = "prompt-v1"):
    return build_summary_generation_profile(
        provider_alias="generation",
        model_profile_id="Qwen3.5-122B-A10B-NVFP4",
        model_revision=revision,
        deployment_id="deployment-a",
        prompt_template_version_id=prompt,
    )


def _manifest(**overrides):
    values = {
        "source": _source(),
        "profile": _profile(),
        "summary_text_sha256": _hex("summary"),
        "summary_char_count": 500,
        "summary_storage_key": "20260922/aa/summary.md",
        "status": "READY",
    }
    values.update(overrides)
    return build_summary_manifest(**values)


def test_builds_deterministic_source_profile_and_manifest() -> None:
    first = _manifest()
    second = _manifest()

    assert first == second
    assert first["source"]["source_fingerprint"] == _source()["source_fingerprint"]
    assert first["generation_profile"]["profile_fingerprint"] == _profile()[
        "profile_fingerprint"
    ]
    assert first["summary_storage_backend"] == "local_filesystem"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("document_id", ""),
        ("content_object_id", None),
        ("extraction_artifact_id", "  "),
        ("source_markdown_sha256", "bad"),
    ],
)
def test_source_snapshot_rejects_invalid_values(field, value) -> None:
    values = {
        "document_id": "document-a",
        "content_object_id": "content-a",
        "extraction_artifact_id": "artifact-a",
        "source_markdown_sha256": _hex("source"),
    }
    values[field] = value
    with pytest.raises(DocumentIntelligenceContractError):
        build_summary_source_snapshot(**values)


@pytest.mark.parametrize(
    ("max_chars", "hard_limit"),
    [(True, 1000), (0, 1000), (900, True), (900, 1001), (901, 900)],
)
def test_profile_rejects_invalid_limits(max_chars, hard_limit) -> None:
    with pytest.raises(DocumentIntelligenceContractError):
        build_summary_generation_profile(
            provider_alias="generation",
            model_profile_id="model",
            model_revision="v1",
            deployment_id="deployment",
            prompt_template_version_id=None,
            summary_max_chars=max_chars,
            summary_hard_limit_chars=hard_limit,
        )


def test_profile_accepts_absent_prompt_version() -> None:
    assert _profile(prompt=None)["prompt_template_version_id"] is None


@pytest.mark.parametrize(
    ("overrides", "error_code"),
    [
        ({"summary_char_count": True}, "cx.summary_manifest_invalid"),
        ({"summary_char_count": 1001}, "cx.summary_manifest_invalid"),
        ({"status": "UNKNOWN"}, "cx.summary_manifest_invalid"),
        ({"summary_text_sha256": "bad"}, "cx.document_intelligence_contract_invalid"),
        ({"summary_storage_key": "/absolute.md"}, "cx.summary_storage_key_invalid"),
        ({"summary_storage_key": "../private.md"}, "cx.summary_storage_key_invalid"),
        ({"summary_storage_key": "./private.md"}, "cx.summary_storage_key_invalid"),
    ],
)
def test_manifest_rejects_invalid_values(overrides, error_code) -> None:
    with pytest.raises(DocumentIntelligenceContractError) as captured:
        _manifest(**overrides)
    assert captured.value.error_code == error_code


def test_freshness_accepts_exact_ready_manifest() -> None:
    result = evaluate_summary_freshness(
        _manifest(),
        current_source=_source(),
        current_profile=_profile(),
    )
    assert result["state"] == "READY"
    assert result["usable"] is True
    assert result["reasons"] == []


def test_freshness_reports_missing_and_changed_inputs() -> None:
    missing = evaluate_summary_freshness(
        None,
        current_source=_source(),
        current_profile=_profile(),
    )
    assert missing["reasons"] == ["SUMMARY_MISSING"]

    changed = evaluate_summary_freshness(
        _manifest(status="RUNNING"),
        current_source=_source("b"),
        current_profile=_profile("v2"),
    )
    assert changed["usable"] is False
    assert changed["reasons"] == [
        "GENERATION_PROFILE_CHANGED",
        "SOURCE_CHANGED",
        "SUMMARY_NOT_READY",
    ]


def test_freshness_fails_closed_for_malformed_manifest() -> None:
    manifest = _manifest()
    manifest.update(
        {
            "manifest_schema_version": "old",
            "source": None,
            "generation_profile": None,
            "summary_text_sha256": "bad",
            "summary_storage_key": "",
        }
    )
    result = evaluate_summary_freshness(
        manifest,
        current_source=_source(),
        current_profile=_profile(),
    )
    assert result["reasons"] == [
        "GENERATION_PROFILE_MISSING",
        "MANIFEST_SCHEMA_MISMATCH",
        "PRIVATE_PAYLOAD_REFERENCE_MISSING",
        "SOURCE_SNAPSHOT_MISSING",
        "SUMMARY_HASH_INVALID",
    ]


def test_contract_rejects_tampered_source_and_profile() -> None:
    source = _source()
    source["source_fingerprint"] = _hex("tampered")
    with pytest.raises(DocumentIntelligenceContractError):
        build_summary_manifest(
            source=source,
            profile=_profile(),
            summary_text_sha256=_hex("summary"),
            summary_char_count=10,
            summary_storage_key="summary.md",
        )

    source = _source()
    source["source_schema_version"] = "old"
    with pytest.raises(DocumentIntelligenceContractError):
        build_summary_manifest(
            source=source,
            profile=_profile(),
            summary_text_sha256=_hex("summary"),
            summary_char_count=10,
            summary_storage_key="summary.md",
        )

    profile = _profile()
    profile["profile_schema_version"] = "old"
    with pytest.raises(DocumentIntelligenceContractError):
        build_summary_manifest(
            source=_source(),
            profile=profile,
            summary_text_sha256=_hex("summary"),
            summary_char_count=10,
            summary_storage_key="summary.md",
        )

    profile = _profile()
    profile["profile_fingerprint"] = _hex("tampered")
    with pytest.raises(DocumentIntelligenceContractError):
        build_summary_manifest(
            source=_source(),
            profile=profile,
            summary_text_sha256=_hex("summary"),
            summary_char_count=10,
            summary_storage_key="summary.md",
        )


def test_contract_rejects_non_mapping_source_and_profile() -> None:
    with pytest.raises(DocumentIntelligenceContractError):
        build_summary_manifest(
            source=None,
            profile=_profile(),
            summary_text_sha256=_hex("summary"),
            summary_char_count=10,
            summary_storage_key="summary.md",
        )
    with pytest.raises(DocumentIntelligenceContractError):
        build_summary_manifest(
            source=_source(),
            profile=None,
            summary_text_sha256=_hex("summary"),
            summary_char_count=10,
            summary_storage_key="summary.md",
        )


def test_public_manifest_excludes_private_storage_and_deployment() -> None:
    public = public_summary_manifest(_manifest())
    assert "summary_storage_key" not in public
    assert "source" not in public
    assert "deployment_id" not in public["generation_profile"]

    with pytest.raises(DocumentIntelligenceContractError):
        public_summary_manifest({})
