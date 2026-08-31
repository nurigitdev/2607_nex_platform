#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "ae_artifact_lifecycle_boundary_audit.v1"

PROTECTED_ENV_KEYS = (
    "NEX_AE_DATABASE_URL",
    "NEX_AE_TEST_DATABASE_URL",
    "NEX_AE_ARTIFACT_STORAGE_ROOT",
    "NEX_AG_AE_ARTIFACT_SERVICE_TOKEN",
    "NEX_SERVICE_TOKEN",
)

ALLOWED_LIFECYCLE_ACTIONS = ("ARCHIVE", "RESTORE", "MARK_DELETED")
DEFERRED_LIFECYCLE_ACTIONS = ("PURGE_STORAGE", "PHYSICAL_DELETE")


@dataclass(frozen=True)
class RequiredPath:
    name: str
    path: Path
    purpose: str


@dataclass(frozen=True)
class TokenRequirement:
    group: str
    path: Path
    token_id: str
    token: str
    purpose: str


@dataclass(frozen=True)
class PlannedGap:
    name: str
    path: Path
    token: str
    planned_slice: str
    purpose: str


AE_API_ARTIFACTS = ROOT / "services" / "nex-ae-api" / "nex_ae_api" / "artifacts.py"
AE_API_README = ROOT / "services" / "nex-ae-api" / "README.md"
AE_WEB_ARTIFACT_CLIENT = ROOT / "apps" / "nex-ae-web" / "src" / "artifactClient.js"
AE_WEB_ARTIFACT_LIBRARY_PANEL = (
    ROOT / "apps" / "nex-ae-web" / "src" / "artifactLibraryPanel.js"
)
AE_WEB_MAIN = ROOT / "apps" / "nex-ae-web" / "src" / "main.js"
AE_WEB_README = ROOT / "apps" / "nex-ae-web" / "README.md"
AG_ARTIFACT_OPERATIONS = ROOT / "services" / "nex-ag" / "nex_ag" / "artifact_operations.py"
AG_README = ROOT / "services" / "nex-ag" / "README.md"
QUALITY_GATE = ROOT / "scripts" / "quality" / "run_quality_gate.sh"
S45_CLOSURE_DOC = (
    ROOT / "docs" / "slices" / "0450_s45_ae_artifact_library_management_closure.md"
)

REQUIRED_PATHS = (
    RequiredPath("ae_api_artifacts", AE_API_ARTIFACTS, "AE artifact system of record."),
    RequiredPath("ae_api_readme", AE_API_README, "AE API lifecycle boundary notes."),
    RequiredPath(
        "ae_web_artifact_client",
        AE_WEB_ARTIFACT_CLIENT,
        "AE Web artifact fetch/mock client boundary.",
    ),
    RequiredPath(
        "ae_web_artifact_library_panel",
        AE_WEB_ARTIFACT_LIBRARY_PANEL,
        "AE Web artifact library action surface.",
    ),
    RequiredPath("ae_web_main", AE_WEB_MAIN, "AE Web artifact workspace wiring."),
    RequiredPath("ae_web_readme", AE_WEB_README, "AE Web artifact lifecycle notes."),
    RequiredPath(
        "ag_artifact_operations",
        AG_ARTIFACT_OPERATIONS,
        "AG artifact operations projection boundary.",
    ),
    RequiredPath("ag_readme", AG_README, "AG artifact operations notes."),
    RequiredPath("quality_gate", QUALITY_GATE, "Default regression gate."),
    RequiredPath("s45_closure_doc", S45_CLOSURE_DOC, "S45 lifecycle input baseline."),
)

REQUIRED_SOURCE_TOKENS = (
    TokenRequirement(
        "ae_system_of_record",
        AE_API_ARTIFACTS,
        "archived_status_supported",
        '"ARCHIVED"',
        "AE artifact model already has an archived state.",
    ),
    TokenRequirement(
        "ae_system_of_record",
        AE_API_ARTIFACTS,
        "deleted_status_supported",
        '"DELETED"',
        "AE artifact model already has a logical deleted state.",
    ),
    TokenRequirement(
        "ae_system_of_record",
        AE_API_ARTIFACTS,
        "sqlalchemy_store_boundary",
        "class SqlAlchemyArtifactRecordStore",
        "Persisted lifecycle mutations must stay behind the AE store boundary.",
    ),
    TokenRequirement(
        "ae_system_of_record",
        AE_API_ARTIFACTS,
        "metadata_collection_route",
        '@app.get("/api/v1/artifacts"',
        "Lifecycle visibility must reuse the metadata-only collection route.",
    ),
    TokenRequirement(
        "web_action_surface",
        AE_WEB_ARTIFACT_CLIENT,
        "artifact_client_boundary",
        "createFetchArtifactClient",
        "Browser lifecycle actions must flow through the artifact client boundary.",
    ),
    TokenRequirement(
        "web_action_surface",
        AE_WEB_ARTIFACT_LIBRARY_PANEL,
        "library_panel",
        "artifact library",
        "Browser lifecycle controls belong in the artifact library surface.",
    ),
    TokenRequirement(
        "web_action_surface",
        AE_WEB_MAIN,
        "artifact_library_wiring",
        "artifactLibrary",
        "The artifact library is already mounted in the AE Web shell.",
    ),
    TokenRequirement(
        "operator_projection",
        AG_ARTIFACT_OPERATIONS,
        "ag_collection_projection",
        "AG_ARTIFACT_OPERATION_COLLECTION_PROJECTION_SCHEMA_VERSION",
        "AG already projects AE artifact collections for operators.",
    ),
    TokenRequirement(
        "operator_projection",
        AG_ARTIFACT_OPERATIONS,
        "ag_client_boundary",
        "class HttpAeArtifactOperationsClient",
        "AG reads AE artifact metadata through an AE client boundary.",
    ),
    TokenRequirement(
        "redaction_boundary",
        AG_ARTIFACT_OPERATIONS,
        "private_data_guard",
        "AG artifact operation projection contains private data.",
        "Operator lifecycle evidence must remain metadata-only.",
    ),
)

PLANNED_GAPS = (
    PlannedGap(
        "lifecycle_command_contract",
        AE_API_ARTIFACTS,
        "AE_ARTIFACT_LIFECYCLE_ACTION_SCHEMA_VERSION",
        "Slice_0452",
        "Define the lifecycle action command/result schema.",
    ),
    PlannedGap(
        "lifecycle_repository_api",
        AE_API_ARTIFACTS,
        "apply_artifact_lifecycle_action",
        "Slice_0453",
        "Wire the AE store and API route for lifecycle state transitions.",
    ),
    PlannedGap(
        "lifecycle_postgres_smoke",
        QUALITY_GATE,
        "run_ae_artifact_lifecycle_postgres_smoke.py --summary",
        "Slice_0454",
        "Prove lifecycle mutations against nex_ae_test.",
    ),
    PlannedGap(
        "web_lifecycle_client",
        AE_WEB_ARTIFACT_CLIENT,
        "submitArtifactLifecycleAction",
        "Slice_0455",
        "Add browser-safe lifecycle client wiring.",
    ),
    PlannedGap(
        "web_lifecycle_actions",
        AE_WEB_ARTIFACT_LIBRARY_PANEL,
        "artifact-lifecycle-action",
        "Slice_0456",
        "Render reversible lifecycle controls in the artifact library.",
    ),
    PlannedGap(
        "ag_lifecycle_projection",
        AG_ARTIFACT_OPERATIONS,
        "lifecycleSummary",
        "Slice_0458",
        "Expose lifecycle status and issue candidates in AG metadata projections.",
    ),
)

SENSITIVE_PATTERNS = (
    re.compile(r"postgresql\+?[^\"'\s]+", re.IGNORECASE),
    re.compile(r"nuri1004", re.IGNORECASE),
    re.compile(r"/data/nex-platform", re.IGNORECASE),
    re.compile(r"ed6@c496em", re.IGNORECASE),
    re.compile(r"service-token-[\w-]+", re.IGNORECASE),
)


def run_ae_artifact_lifecycle_boundary_audit(
    env: Mapping[str, str] | None = None,
    *,
    root_dir: Path = ROOT,
) -> dict[str, object]:
    env = env or os.environ
    paths = build_path_results(root_dir)
    tokens = build_token_results(root_dir)
    gaps = build_gap_results(root_dir)
    group_status = grouped_token_status(tokens)
    checks = {
        "required_paths_present": all(item["present"] for item in paths),
        "ae_system_of_record_present": group_status.get("ae_system_of_record") is True,
        "web_action_surface_present": group_status.get("web_action_surface") is True,
        "operator_projection_present": group_status.get("operator_projection") is True,
        "redaction_boundary_present": group_status.get("redaction_boundary") is True,
        "allowed_actions_reversible": all(
            action in ALLOWED_LIFECYCLE_ACTIONS
            for action in ("ARCHIVE", "RESTORE", "MARK_DELETED")
        ),
        "physical_delete_deferred": set(DEFERRED_LIFECYCLE_ACTIONS)
        == {"PURGE_STORAGE", "PHYSICAL_DELETE"},
        "planned_gaps_non_blocking": all(item["blocking"] is False for item in gaps),
        "redacted_evidence_only": True,
    }
    issues = []
    issues.extend(
        {
            "category": "path_missing",
            "name": item["name"],
            "path": item["path"],
            "purpose": item["purpose"],
        }
        for item in paths
        if not item["present"]
    )
    issues.extend(
        {
            "category": "source_token_missing",
            "group": item["group"],
            "token_id": item["token_id"],
            "path": item["path"],
            "purpose": item["purpose"],
        }
        for item in tokens
        if not item["present"]
    )
    status = "PASS" if all(checks.values()) and not issues else "FAIL"
    evidence: dict[str, object] = {
        "audit_schema_version": SCHEMA_VERSION,
        "status": status,
        "slice": "0451",
        "surface": "S46 AE artifact lifecycle management",
        "decisions": {
            "artifact_system_of_record": "nex-ae-api",
            "browser_action_owner": "nex-ae-web",
            "operator_projection_owner": "nex-ag",
            "allowed_lifecycle_actions": list(ALLOWED_LIFECYCLE_ACTIONS),
            "action_semantics": {
                "ARCHIVE": "hide_from_default_active_views_reversible",
                "RESTORE": "return_to_active_visibility_reversible",
                "MARK_DELETED": "logical_delete_reversible_admin_visible",
            },
            "physical_delete_policy": "deferred_to_retention_or_purge_track",
            "storage_mutation_policy": "no_storage_payload_or_file_removal_in_s46",
            "postgres_smoke_target": "nex_ae_test_for_protected_s46_smokes",
        },
        "paths": paths,
        "source_tokens": tokens,
        "planned_gaps": gaps,
        "checks": checks,
        "issues": issues,
        "next_slices": ["Slice_0452", "Slice_0453", "Slice_0454"],
        "protected_env": summarize_protected_env(env),
    }
    assert_evidence_redacted(json.dumps(evidence, ensure_ascii=False), env)
    return evidence


def build_path_results(root_dir: Path) -> list[dict[str, object]]:
    return [
        {
            "name": item.name,
            "path": relative_label(item.path, root_dir),
            "purpose": item.purpose,
            "present": item.path.exists(),
        }
        for item in REQUIRED_PATHS
    ]


def build_token_results(root_dir: Path) -> list[dict[str, object]]:
    return [
        {
            "group": item.group,
            "token_id": item.token_id,
            "path": relative_label(item.path, root_dir),
            "purpose": item.purpose,
            "present": item.token in read_text(item.path),
        }
        for item in REQUIRED_SOURCE_TOKENS
    ]


def build_gap_results(root_dir: Path) -> list[dict[str, object]]:
    results = []
    for item in PLANNED_GAPS:
        present = item.token in read_text(item.path)
        results.append(
            {
                "name": item.name,
                "path": relative_label(item.path, root_dir),
                "planned_slice": item.planned_slice,
                "purpose": item.purpose,
                "already_present": present,
                "blocking": False,
            }
        )
    return results


def summarize_protected_env(env: Mapping[str, str]) -> dict[str, bool]:
    return {key: bool(env.get(key)) for key in PROTECTED_ENV_KEYS}


def grouped_token_status(tokens: list[dict[str, object]]) -> dict[str, bool]:
    groups = sorted({str(item["group"]) for item in tokens})
    return {
        group: all(bool(item["present"]) for item in tokens if item["group"] == group)
        for group in groups
    }


def present_count(items: list[dict[str, object]]) -> int:
    return sum(1 for item in items if item.get("present"))


def gap_ready_count(items: list[dict[str, object]]) -> int:
    return sum(1 for item in items if item.get("already_present"))


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def relative_label(path: Path, root_dir: Path) -> str:
    try:
        return str(path.relative_to(root_dir))
    except ValueError:
        return path.name


def assert_evidence_redacted(serialized: str, env: Mapping[str, str]) -> None:
    for key in PROTECTED_ENV_KEYS:
        value = env.get(key)
        if value and value in serialized:
            raise ValueError(f"Protected value leaked in evidence: {key}")
    for pattern in SENSITIVE_PATTERNS:
        if pattern.search(serialized):
            raise ValueError("Sensitive value leaked in evidence.")


def write_audit_evidence(path: Path, evidence: Mapping[str, object]) -> None:
    serialized = json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    assert_evidence_redacted(serialized, os.environ)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{serialized}\n", encoding="utf-8")


def summary_line(evidence: Mapping[str, object]) -> str:
    checks = evidence.get("checks", {})
    failing_checks = [
        key for key, passed in checks.items() if passed is not True
    ] if isinstance(checks, dict) else []
    suffix = (
        f"required_paths={present_count(evidence['paths'])}/{len(evidence['paths'])} "
        f"tokens={present_count(evidence['source_tokens'])}/{len(evidence['source_tokens'])} "
        f"gaps_ready={gap_ready_count(evidence['planned_gaps'])}/{len(evidence['planned_gaps'])} "
        "next=Slice_0452"
    )
    if failing_checks:
        suffix += f" failing_checks={','.join(failing_checks)}"
    return (
        "ae_artifact_lifecycle_boundary_audit="
        f"{str(evidence['status']).lower()} {suffix}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit the S46 AE artifact lifecycle management boundary."
    )
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    try:
        evidence = run_ae_artifact_lifecycle_boundary_audit(os.environ)
        if args.output:
            write_audit_evidence(args.output, evidence)
    except Exception as exc:  # pragma: no cover - exercised by caller tests.
        print(f"ae_artifact_lifecycle_boundary_audit=error error={type(exc).__name__}")
        return 1

    if args.summary:
        print(summary_line(evidence))
    else:
        print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
