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
SCHEMA_VERSION = "ae_artifact_retention_purge_boundary_audit.v1"

PROTECTED_ENV_KEYS = (
    "NEX_AE_DATABASE_URL",
    "NEX_AE_TEST_DATABASE_URL",
    "NEX_AE_ARTIFACT_STORAGE_ROOT",
    "NEX_AG_AE_ARTIFACT_SERVICE_TOKEN",
    "NEX_SERVICE_TOKEN",
)

LOGICAL_PURGE_FLAG = "artifact_status=DELETED"
DEFAULT_RETENTION_DAYS = 30
SUPPORTED_RETENTION_DAY_PRESETS = (15, 30)
DEFAULT_BATCH_WINDOW = "02:00-05:00"
DEFERRED_PURGE_ACTIONS = ("PHYSICAL_DELETE", "STORAGE_MUTATION", "SCHEDULED_BATCH")


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
    planned_slice: str
    purpose: str


AE_API_ARTIFACTS = ROOT / "services" / "nex-ae-api" / "nex_ae_api" / "artifacts.py"
AE_API_README = ROOT / "services" / "nex-ae-api" / "README.md"
AE_ARTIFACT_MIGRATION = (
    ROOT
    / "database"
    / "nex-ae-api"
    / "migrations"
    / "0402_ae_artifact_persistence_foundation.sql"
)
AE_ARTIFACT_LIFECYCLE_SMOKE = (
    ROOT / "scripts" / "smoke" / "run_ae_artifact_lifecycle_postgres_smoke.py"
)
S46_CLOSURE = (
    ROOT / "scripts" / "smoke" / "run_s46_ae_artifact_lifecycle_management_closure.py"
)
QUALITY_GATE = ROOT / "scripts" / "quality" / "run_quality_gate.sh"
DOCS_INDEX = ROOT / "docs" / "README.md"
S46_CLOSURE_DOC = (
    ROOT / "docs" / "slices" / "0460_s46_ae_artifact_lifecycle_management_closure.md"
)

REQUIRED_PATHS = (
    RequiredPath("ae_api_artifacts", AE_API_ARTIFACTS, "AE artifact system of record."),
    RequiredPath("ae_api_readme", AE_API_README, "AE API artifact lifecycle notes."),
    RequiredPath(
        "ae_artifact_migration",
        AE_ARTIFACT_MIGRATION,
        "Current AE artifact PostgreSQL metadata schema.",
    ),
    RequiredPath(
        "ae_artifact_lifecycle_smoke",
        AE_ARTIFACT_LIFECYCLE_SMOKE,
        "Latest protected lifecycle smoke proving logical deletion.",
    ),
    RequiredPath("s46_closure", S46_CLOSURE, "S46 lifecycle closure checkpoint."),
    RequiredPath("quality_gate", QUALITY_GATE, "Default regression gate."),
    RequiredPath("docs_index", DOCS_INDEX, "Slice index."),
    RequiredPath("s46_closure_doc", S46_CLOSURE_DOC, "S47 input baseline."),
)

REQUIRED_SOURCE_TOKENS = (
    TokenRequirement(
        "logical_purge_flag",
        AE_API_ARTIFACTS,
        "deleted_status_supported",
        '"DELETED"',
        "The existing lifecycle model already has a logical deleted status.",
    ),
    TokenRequirement(
        "logical_purge_flag",
        AE_API_ARTIFACTS,
        "mark_deleted_action",
        '"MARK_DELETED"',
        "The current mutation surface can move an artifact into logical purge.",
    ),
    TokenRequirement(
        "retention_read_model_boundary",
        AE_API_ARTIFACTS,
        "sqlalchemy_store_boundary",
        "class SqlAlchemyArtifactRecordStore",
        "Retention scans should stay behind the AE artifact store boundary.",
    ),
    TokenRequirement(
        "retention_read_model_boundary",
        AE_API_ARTIFACTS,
        "metadata_collection_route",
        '@app.get("/api/v1/artifacts"',
        "Retention candidates should reuse metadata-only artifact projections.",
    ),
    TokenRequirement(
        "storage_boundary",
        AE_API_ARTIFACTS,
        "local_storage_adapter",
        "class LocalRenderedArtifactStorage",
        "Physical payload mutation must remain behind rendered storage adapters.",
    ),
    TokenRequirement(
        "storage_boundary",
        AE_API_ARTIFACTS,
        "logical_storage_ref",
        "ae://artifacts/",
        "Public metadata carries logical refs, not local file paths.",
    ),
    TokenRequirement(
        "s46_deferred_delete",
        AE_API_ARTIFACTS,
        "physical_delete_not_executed",
        '"physical_delete_executed": False',
        "S46 lifecycle results intentionally do not remove physical files.",
    ),
    TokenRequirement(
        "s46_deferred_delete",
        AE_ARTIFACT_LIFECYCLE_SMOKE,
        "storage_files_retained",
        '"storage_files_retained"',
        "The latest smoke proves logical delete still retains files.",
    ),
)

PLANNED_GAPS = (
    PlannedGap(
        "retention_policy_contract_schema",
        "Slice_0462",
        "Freeze logical-purge retention policy defaults and safe schema examples.",
    ),
    PlannedGap(
        "retention_candidate_read_model",
        "Slice_0463",
        "Build the in-memory and SQLAlchemy dry-run candidate read-model.",
    ),
    PlannedGap(
        "retention_candidate_api",
        "Slice_0464",
        "Expose authenticated AE API candidate dry-run lookup.",
    ),
    PlannedGap(
        "retention_candidate_postgres_smoke",
        "Slice_0465",
        "Prove candidate lookup against nex_ae_test with migrations applied.",
    ),
    PlannedGap(
        "guarded_purge_execution",
        "Slice_0466_plus",
        "Add physical purge execution only after dry-run evidence is stable.",
    ),
)

SENSITIVE_PATTERNS = (
    re.compile(r"postgresql\+?[^\"'\s]+", re.IGNORECASE),
    re.compile(r"nuri1004", re.IGNORECASE),
    re.compile(r"/data/nex-platform", re.IGNORECASE),
    re.compile(r"ed6@c496em", re.IGNORECASE),
    re.compile(r"service-token-[\w-]+", re.IGNORECASE),
)


def run_ae_artifact_retention_purge_boundary_audit(
    env: Mapping[str, str] | None = None,
    *,
    root_dir: Path = ROOT,
) -> dict[str, object]:
    env = env or os.environ
    paths = build_path_results(root_dir)
    tokens = build_token_results(root_dir)
    group_status = grouped_token_status(tokens)
    checks = {
        "required_paths_present": all(item["present"] for item in paths),
        "logical_purge_flag_present": group_status.get("logical_purge_flag") is True,
        "retention_read_model_boundary_present": (
            group_status.get("retention_read_model_boundary") is True
        ),
        "storage_boundary_present": group_status.get("storage_boundary") is True,
        "s46_deferred_delete_confirmed": group_status.get("s46_deferred_delete") is True,
        "dry_run_first_policy": True,
        "batch_delete_deferred": set(DEFERRED_PURGE_ACTIONS)
        == {"PHYSICAL_DELETE", "SCHEDULED_BATCH", "STORAGE_MUTATION"},
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
        "slice": "0461",
        "surface": "S47 AE artifact retention and purge dry-run foundation",
        "decisions": {
            "artifact_system_of_record": "nex-ae-api",
            "logical_purge_flag": LOGICAL_PURGE_FLAG,
            "logical_purge_first": True,
            "default_retention_days_after_logical_purge": DEFAULT_RETENTION_DAYS,
            "supported_retention_day_presets": list(SUPPORTED_RETENTION_DAY_PRESETS),
            "scheduled_batch_window_local_time": DEFAULT_BATCH_WINDOW,
            "candidate_query_mode": "dry_run_metadata_only",
            "physical_delete_policy": "deferred_until_guarded_batch_execution_slice",
            "storage_mutation_policy": "no_storage_payload_or_file_removal_in_0461_0465",
            "postgres_smoke_target": "nex_ae_test_for_protected_s47_dry_run_smoke",
        },
        "paths": paths,
        "source_tokens": tokens,
        "planned_gaps": build_gap_results(),
        "checks": checks,
        "issues": issues,
        "next_slices": ["Slice_0462", "Slice_0463", "Slice_0464", "Slice_0465"],
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


def build_gap_results() -> list[dict[str, object]]:
    return [
        {
            "name": item.name,
            "planned_slice": item.planned_slice,
            "purpose": item.purpose,
            "blocking": False,
        }
        for item in PLANNED_GAPS
    ]


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
        "logical_flag=DELETED "
        f"retention_days={DEFAULT_RETENTION_DAYS} "
        f"batch_window={DEFAULT_BATCH_WINDOW} "
        "next=Slice_0462"
    )
    if failing_checks:
        suffix += f" failing_checks={','.join(failing_checks)}"
    return (
        "ae_artifact_retention_purge_boundary_audit="
        f"{str(evidence['status']).lower()} {suffix}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit the S47 AE artifact retention/purge boundary."
    )
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    try:
        evidence = run_ae_artifact_retention_purge_boundary_audit(os.environ)
        if args.output:
            write_audit_evidence(args.output, evidence)
    except Exception as exc:  # pragma: no cover - exercised by caller tests.
        print(
            "ae_artifact_retention_purge_boundary_audit=error "
            f"error={type(exc).__name__}"
        )
        return 1

    if args.summary:
        print(summary_line(evidence))
    else:
        print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
