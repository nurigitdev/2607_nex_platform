from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import PurePosixPath
from typing import Any, Mapping
from uuid import NAMESPACE_URL, uuid5


SOURCE_SCHEMA_VERSION = "cx_summary_source_snapshot.v1"
PROFILE_SCHEMA_VERSION = "cx_summary_generation_profile.v1"
MANIFEST_SCHEMA_VERSION = "cx_document_intelligence_summary_manifest.v1"
FRESHNESS_SCHEMA_VERSION = "cx_summary_freshness_evaluation.v1"
SUMMARY_HARD_LIMIT_CHARS = 1000
SUMMARY_STATES = frozenset({"PENDING", "RUNNING", "READY", "STALE", "FAILED"})


@dataclass(frozen=True)
class DocumentIntelligenceContractError(Exception):
    error_code: str
    detail: str


def build_summary_source_snapshot(
    *,
    document_id: str,
    content_object_id: str,
    extraction_artifact_id: str,
    source_markdown_sha256: str,
) -> dict[str, Any]:
    payload = {
        "source_schema_version": SOURCE_SCHEMA_VERSION,
        "document_id": _required_text(document_id, "document_id"),
        "content_object_id": _required_text(content_object_id, "content_object_id"),
        "extraction_artifact_id": _required_text(
            extraction_artifact_id,
            "extraction_artifact_id",
        ),
        "source_markdown_sha256": _sha256(
            source_markdown_sha256,
            "source_markdown_sha256",
        ),
    }
    payload["source_fingerprint"] = _fingerprint(payload)
    return payload


def build_summary_generation_profile(
    *,
    provider_alias: str,
    model_profile_id: str,
    model_revision: str,
    deployment_id: str,
    prompt_template_version_id: str | None,
    summary_max_chars: int = 900,
    summary_hard_limit_chars: int = SUMMARY_HARD_LIMIT_CHARS,
) -> dict[str, Any]:
    if (
        isinstance(summary_max_chars, bool)
        or not isinstance(summary_max_chars, int)
        or summary_max_chars <= 0
    ):
        raise DocumentIntelligenceContractError(
            "cx.summary_profile_invalid",
            "summary_max_chars must be a positive integer.",
        )
    if (
        isinstance(summary_hard_limit_chars, bool)
        or not isinstance(summary_hard_limit_chars, int)
        or not 1 <= summary_hard_limit_chars <= SUMMARY_HARD_LIMIT_CHARS
    ):
        raise DocumentIntelligenceContractError(
            "cx.summary_profile_invalid",
            "summary_hard_limit_chars must be between 1 and 1000.",
        )
    if summary_max_chars > summary_hard_limit_chars:
        raise DocumentIntelligenceContractError(
            "cx.summary_profile_invalid",
            "summary_max_chars must not exceed the hard limit.",
        )
    prompt_version = (
        _required_text(prompt_template_version_id, "prompt_template_version_id")
        if prompt_template_version_id is not None
        else None
    )
    payload = {
        "profile_schema_version": PROFILE_SCHEMA_VERSION,
        "provider_alias": _required_text(provider_alias, "provider_alias"),
        "model_profile_id": _required_text(model_profile_id, "model_profile_id"),
        "model_revision": _required_text(model_revision, "model_revision"),
        "deployment_id": _required_text(deployment_id, "deployment_id"),
        "prompt_template_version_id": prompt_version,
        "summary_max_chars": summary_max_chars,
        "summary_hard_limit_chars": summary_hard_limit_chars,
        "output_format": "markdown_plain_text",
    }
    payload["profile_fingerprint"] = _fingerprint(payload)
    return payload


def build_summary_manifest(
    *,
    source: Mapping[str, Any],
    profile: Mapping[str, Any],
    summary_text_sha256: str,
    summary_char_count: int,
    summary_storage_key: str,
    status: str = "READY",
) -> dict[str, Any]:
    source_record = _validated_source(source)
    profile_record = _validated_profile(profile)
    if isinstance(summary_char_count, bool) or not isinstance(summary_char_count, int):
        raise DocumentIntelligenceContractError(
            "cx.summary_manifest_invalid",
            "summary_char_count must be an integer.",
        )
    if not 0 <= summary_char_count <= profile_record["summary_hard_limit_chars"]:
        raise DocumentIntelligenceContractError(
            "cx.summary_manifest_invalid",
            "summary_char_count exceeds the generation profile hard limit.",
        )
    if status not in SUMMARY_STATES:
        raise DocumentIntelligenceContractError(
            "cx.summary_manifest_invalid",
            "Summary manifest status is invalid.",
        )
    storage_key = _safe_storage_key(summary_storage_key)
    summary_hash = _sha256(summary_text_sha256, "summary_text_sha256")
    manifest_identity = ":".join(
        (
            source_record["source_fingerprint"],
            profile_record["profile_fingerprint"],
            summary_hash,
        )
    )
    return {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "document_summary_id": str(
            uuid5(NAMESPACE_URL, f"cx-summary-manifest:{manifest_identity}")
        ),
        "document_id": source_record["document_id"],
        "content_object_id": source_record["content_object_id"],
        "source": source_record,
        "generation_profile": profile_record,
        "summary_text_sha256": summary_hash,
        "summary_char_count": summary_char_count,
        "summary_storage_backend": "local_filesystem",
        "summary_storage_key": storage_key,
        "status": status,
    }


def evaluate_summary_freshness(
    manifest: Mapping[str, Any] | None,
    *,
    current_source: Mapping[str, Any],
    current_profile: Mapping[str, Any],
) -> dict[str, Any]:
    source_record = _validated_source(current_source)
    profile_record = _validated_profile(current_profile)
    reasons: list[str] = []
    if not isinstance(manifest, Mapping):
        reasons.append("SUMMARY_MISSING")
    else:
        if manifest.get("manifest_schema_version") != MANIFEST_SCHEMA_VERSION:
            reasons.append("MANIFEST_SCHEMA_MISMATCH")
        if manifest.get("status") != "READY":
            reasons.append("SUMMARY_NOT_READY")
        stored_source = manifest.get("source")
        if not isinstance(stored_source, Mapping):
            reasons.append("SOURCE_SNAPSHOT_MISSING")
        elif stored_source.get("source_fingerprint") != source_record.get(
            "source_fingerprint"
        ):
            reasons.append("SOURCE_CHANGED")
        stored_profile = manifest.get("generation_profile")
        if not isinstance(stored_profile, Mapping):
            reasons.append("GENERATION_PROFILE_MISSING")
        elif stored_profile.get("profile_fingerprint") != profile_record.get(
            "profile_fingerprint"
        ):
            reasons.append("GENERATION_PROFILE_CHANGED")
        try:
            _sha256(str(manifest.get("summary_text_sha256") or ""), "summary_text_sha256")
        except DocumentIntelligenceContractError:
            reasons.append("SUMMARY_HASH_INVALID")
        try:
            _safe_storage_key(str(manifest.get("summary_storage_key") or ""))
        except DocumentIntelligenceContractError:
            reasons.append("PRIVATE_PAYLOAD_REFERENCE_MISSING")
    unique_reasons = sorted(set(reasons))
    return {
        "freshness_schema_version": FRESHNESS_SCHEMA_VERSION,
        "state": "READY" if not unique_reasons else "STALE",
        "usable": not unique_reasons,
        "reasons": unique_reasons,
        "source_fingerprint": source_record["source_fingerprint"],
        "profile_fingerprint": profile_record["profile_fingerprint"],
    }


def public_summary_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    if manifest.get("manifest_schema_version") != MANIFEST_SCHEMA_VERSION:
        raise DocumentIntelligenceContractError(
            "cx.summary_manifest_invalid",
            "Summary manifest schema is invalid.",
        )
    return {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "document_summary_id": manifest.get("document_summary_id"),
        "document_id": manifest.get("document_id"),
        "status": manifest.get("status"),
        "summary_text_sha256": manifest.get("summary_text_sha256"),
        "summary_char_count": manifest.get("summary_char_count"),
        "generation_profile": {
            key: value
            for key, value in _mapping(manifest.get("generation_profile")).items()
            if key not in {"deployment_id"}
        },
    }


def _validated_source(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise DocumentIntelligenceContractError(
            "cx.summary_source_invalid",
            "Summary source snapshot must be an object.",
        )
    rebuilt = build_summary_source_snapshot(
        document_id=value.get("document_id"),
        content_object_id=value.get("content_object_id"),
        extraction_artifact_id=value.get("extraction_artifact_id"),
        source_markdown_sha256=value.get("source_markdown_sha256"),
    )
    if value.get("source_schema_version") != SOURCE_SCHEMA_VERSION:
        raise DocumentIntelligenceContractError(
            "cx.summary_source_invalid",
            "Summary source snapshot schema is invalid.",
        )
    if value.get("source_fingerprint") != rebuilt["source_fingerprint"]:
        raise DocumentIntelligenceContractError(
            "cx.summary_source_invalid",
            "Summary source fingerprint is invalid.",
        )
    return rebuilt


def _validated_profile(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise DocumentIntelligenceContractError(
            "cx.summary_profile_invalid",
            "Summary generation profile must be an object.",
        )
    rebuilt = build_summary_generation_profile(
        provider_alias=value.get("provider_alias"),
        model_profile_id=value.get("model_profile_id"),
        model_revision=value.get("model_revision"),
        deployment_id=value.get("deployment_id"),
        prompt_template_version_id=value.get("prompt_template_version_id"),
        summary_max_chars=value.get("summary_max_chars"),
        summary_hard_limit_chars=value.get("summary_hard_limit_chars"),
    )
    if value.get("profile_schema_version") != PROFILE_SCHEMA_VERSION:
        raise DocumentIntelligenceContractError(
            "cx.summary_profile_invalid",
            "Summary generation profile schema is invalid.",
        )
    if value.get("profile_fingerprint") != rebuilt["profile_fingerprint"]:
        raise DocumentIntelligenceContractError(
            "cx.summary_profile_invalid",
            "Summary generation profile fingerprint is invalid.",
        )
    return rebuilt


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DocumentIntelligenceContractError(
            "cx.document_intelligence_contract_invalid",
            f"{field} must be a non-empty string.",
        )
    return value.strip()


def _sha256(value: Any, field: str) -> str:
    text = _required_text(value, field).lower()
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise DocumentIntelligenceContractError(
            "cx.document_intelligence_contract_invalid",
            f"{field} must be a lowercase SHA-256 value.",
        )
    return text


def _safe_storage_key(value: Any) -> str:
    key = _required_text(value, "summary_storage_key")
    path = PurePosixPath(key)
    if path.is_absolute() or ".." in path.parts or key.startswith("./"):
        raise DocumentIntelligenceContractError(
            "cx.summary_storage_key_invalid",
            "summary_storage_key must be a safe relative path.",
        )
    return path.as_posix()


def _fingerprint(value: Mapping[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}
