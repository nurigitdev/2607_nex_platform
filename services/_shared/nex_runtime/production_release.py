from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import UTC, datetime
from hashlib import sha256
import json
import re
from typing import Any


RELEASE_MANIFEST_SCHEMA_VERSION = "s150_release_evidence_manifest.v1"
SAFE_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
SAFE_RAW_DIGEST = re.compile(r"^[0-9a-f]{64}$")
SAFE_REVISION = re.compile(r"^[0-9a-f]{40}$")
SAFE_RELEASE_ID = re.compile(r"^rc:s149:[0-9a-f]{16}$")
FORBIDDEN_KEY_PARTS = (
    "api_key",
    "authorization",
    "cookie",
    "database_url",
    "password",
    "private_key",
    "private_payload",
    "prompt_content",
    "provider_endpoint",
    "secret",
    "source_document",
    "storage_path",
    "token",
)


def build_release_evidence_manifest(
    closure: Mapping[str, Any],
    *,
    source_revision: str,
    observed_at: datetime,
) -> dict[str, Any]:
    if closure.get("status") != "PASS":
        raise ValueError("S149 closure must pass")
    if not SAFE_REVISION.fullmatch(source_revision):
        raise ValueError("source_revision must be a full Git revision")
    if observed_at.tzinfo is None:
        raise ValueError("observed_at must be timezone-aware")

    binding = _mapping(closure.get("release_binding"))
    regression = _mapping(closure.get("full_regression"))
    handoff = _mapping(closure.get("s150_handoff"))
    summary = _mapping(closure.get("summary"))
    manifest = {
        "manifest_schema_version": RELEASE_MANIFEST_SCHEMA_VERSION,
        "requirement": "S150",
        "release_candidate_id": binding.get("release_candidate_id"),
        "release_set_digest": binding.get("release_set_digest"),
        "source_revision": source_revision,
        "observed_at": observed_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "dependency_evidence": [
            {
                "kind": "s149_admission",
                "digest": binding.get("admission_evidence_digest"),
            },
            {
                "kind": "full_regression",
                "digest": _normalized_digest(
                    binding.get("full_regression_evidence_digest")
                ),
            },
            {
                "kind": "s149_closure",
                "digest": canonical_digest(closure),
            },
        ],
        "full_regression": {
            "status": regression.get("status"),
            "passed_test_count": regression.get("passed_test_count"),
            "failed_test_count": regression.get("failed_test_count"),
            "statement_coverage": regression.get("statement_coverage"),
            "branch_coverage": regression.get("branch_coverage"),
        },
        "single_host_backlog_count": summary.get("backlog_count"),
        "external_notification_waiver": handoff.get(
            "external_notification_waiver"
        ),
        "production_go_eligible": handoff.get("production_go_eligible"),
        "production_deployment_approved": closure.get(
            "production_deployment_approved"
        ),
    }
    manifest["manifest_digest"] = canonical_digest(manifest)
    return manifest


def validate_release_evidence_manifest(
    manifest: Mapping[str, Any],
) -> dict[str, Any]:
    dependencies = manifest.get("dependency_evidence")
    records = (
        [dict(item) for item in dependencies if isinstance(item, Mapping)]
        if isinstance(dependencies, Sequence)
        and not isinstance(dependencies, (str, bytes))
        else []
    )
    kinds = [item.get("kind") for item in records]
    regression = _mapping(manifest.get("full_regression"))
    privacy_violations = _privacy_violations(manifest)
    expected_digest = canonical_digest(
        {key: value for key, value in manifest.items() if key != "manifest_digest"}
    )
    checks = {
        "schema_and_requirement_valid": (
            manifest.get("manifest_schema_version")
            == RELEASE_MANIFEST_SCHEMA_VERSION
            and manifest.get("requirement") == "S150"
        ),
        "release_identity_valid": bool(
            SAFE_RELEASE_ID.fullmatch(str(manifest.get("release_candidate_id") or ""))
        )
        and bool(
            SAFE_SHA256.fullmatch(str(manifest.get("release_set_digest") or ""))
        ),
        "source_revision_valid": bool(
            SAFE_REVISION.fullmatch(str(manifest.get("source_revision") or ""))
        ),
        "observed_at_valid": _parse_timestamp(manifest.get("observed_at")) is not None,
        "dependency_inventory_exact": kinds
        == ["s149_admission", "full_regression", "s149_closure"],
        "dependency_digests_valid": len(records) == 3
        and all(SAFE_SHA256.fullmatch(str(item.get("digest") or "")) for item in records),
        "full_regression_passed": (
            regression.get("status") == "PASS"
            and int(regression.get("passed_test_count") or 0) > 0
            and regression.get("failed_test_count") == 0
            and float(regression.get("statement_coverage") or 0) >= 95.0
            and float(regression.get("branch_coverage") or 0) >= 94.0
        ),
        "single_host_backlog_preserved": manifest.get(
            "single_host_backlog_count"
        )
        == 5,
        "go_guard_preserved": (
            manifest.get("external_notification_waiver")
            == "REQUIRED_NOT_GRANTED"
            and manifest.get("production_go_eligible") is False
            and manifest.get("production_deployment_approved") is False
        ),
        "privacy_clean": not privacy_violations,
        "manifest_digest_valid": manifest.get("manifest_digest") == expected_digest,
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    return {
        "status": "PASS" if not failed_checks else "FAIL",
        "checks": checks,
        "failed_checks": failed_checks,
        "privacy_violations": privacy_violations,
        "summary": {
            "check_count": len(checks),
            "passed_check_count": sum(checks.values()),
            "dependency_count": len(records),
            "backlog_count": int(manifest.get("single_host_backlog_count") or 0),
        },
    }


def canonical_digest(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{sha256(encoded).hexdigest()}"


def _normalized_digest(value: object) -> str:
    candidate = str(value or "")
    if SAFE_SHA256.fullmatch(candidate):
        return candidate
    if SAFE_RAW_DIGEST.fullmatch(candidate):
        return f"sha256:{candidate}"
    return candidate


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else None


def _privacy_violations(value: object, *, path: str = "$") -> list[str]:
    violations: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            name = str(key)
            child = f"{path}.{name}"
            if any(part in name.lower() for part in FORBIDDEN_KEY_PARTS):
                violations.append(child)
            violations.extend(_privacy_violations(item, path=child))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for index, item in enumerate(value):
            violations.extend(_privacy_violations(item, path=f"{path}[{index}]"))
    return violations


def _mapping(value: object) -> dict[str, Any]:
    return deepcopy(dict(value)) if isinstance(value, Mapping) else {}
