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
SCHEMA_VERSION = "ae_artifact_retention_history_boundary_audit.v1"

PROTECTED_ENV_KEYS = (
    "NEX_AE_DATABASE_URL",
    "NEX_AE_TEST_DATABASE_URL",
    "NEX_AE_ARTIFACT_STORAGE_ROOT",
    "NEX_SERVICE_TOKEN",
)

RETENTION_HISTORY_TABLE = "ae_artifact_retention_executions"
RETENTION_EXECUTION_SCHEMA = "ae_artifact_retention_execution.v1"
RETENTION_HISTORY_SCHEMA = "ae_artifact_retention_execution_history.v1"


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
S47_CLOSURE = ROOT / "scripts" / "smoke" / "run_s47_ae_artifact_retention_purge_closure.py"
RETENTION_PURGE_SMOKE = (
    ROOT / "scripts" / "smoke" / "run_ae_artifact_retention_purge_postgres_smoke.py"
)
QUALITY_GATE = ROOT / "scripts" / "quality" / "run_quality_gate.sh"
DOCS_INDEX = ROOT / "docs" / "README.md"
S47_CLOSURE_DOC = ROOT / "docs" / "slices" / "0470_s47_ae_artifact_retention_purge_closure.md"

REQUIRED_PATHS = (
    RequiredPath("ae_api_artifacts", AE_API_ARTIFACTS, "AE artifact retention runtime."),
    RequiredPath("ae_api_readme", AE_API_README, "AE artifact retention notes."),
    RequiredPath("s47_closure", S47_CLOSURE, "S47 retention purge closure checkpoint."),
    RequiredPath(
        "retention_purge_smoke",
        RETENTION_PURGE_SMOKE,
        "Latest protected purge smoke with physical deletion evidence.",
    ),
    RequiredPath("quality_gate", QUALITY_GATE, "Default regression gate."),
    RequiredPath("docs_index", DOCS_INDEX, "Slice index."),
    RequiredPath("s47_closure_doc", S47_CLOSURE_DOC, "S48 input baseline."),
)

REQUIRED_SOURCE_TOKENS = (
    TokenRequirement(
        "execution_contract",
        AE_API_ARTIFACTS,
        "execution_schema",
        "AE_ARTIFACT_RETENTION_EXECUTION_SCHEMA_VERSION",
        "Execution history must persist the existing execution contract.",
    ),
    TokenRequirement(
        "execution_contract",
        AE_API_ARTIFACTS,
        "execution_builder",
        "build_artifact_retention_execution",
        "History records should be derived from validated execution evidence.",
    ),
    TokenRequirement(
        "purge_guardrail",
        AE_API_ARTIFACTS,
        "purge_store_method",
        "purge_retention_candidates",
        "The history boundary starts after guarded purge execution is available.",
    ),
    TokenRequirement(
        "purge_guardrail",
        AE_API_ARTIFACTS,
        "purge_route",
        '"/api/v1/artifact-retention/purge"',
        "The purge API is the first writer of retention execution history.",
    ),
    TokenRequirement(
        "purge_guardrail",
        AE_API_ARTIFACTS,
        "three_flag_guard",
        "database_row_delete_enabled",
        "Successful physical delete remains guarded by explicit flags.",
    ),
    TokenRequirement(
        "postgres_evidence",
        RETENTION_PURGE_SMOKE,
        "direct_db_after_execute",
        "db_after_execute",
        "The latest smoke checks direct DB state after guarded purge.",
    ),
    TokenRequirement(
        "postgres_evidence",
        RETENTION_PURGE_SMOKE,
        "live_db_marker",
        "live_db",
        "The latest purge smoke can prove live test DB execution.",
    ),
    TokenRequirement(
        "s47_closure",
        S47_CLOSURE,
        "s47_slice_range",
        "0461-0470",
        "Execution history starts after S47 is closed.",
    ),
)

PLANNED_GAPS = (
    PlannedGap(
        "retention_execution_history_schema_migration",
        "Slice_0472",
        "Create the AE-owned PostgreSQL history table and indexes.",
    ),
    PlannedGap(
        "retention_execution_history_repository",
        "Slice_0473",
        "Add in-memory and SQLAlchemy stores with SQLite regression.",
    ),
    PlannedGap(
        "purge_api_history_wiring",
        "Slice_0474",
        "Persist purge route executions and reuse idempotent history evidence.",
    ),
    PlannedGap(
        "retention_execution_history_postgres_smoke",
        "Slice_0475",
        "Prove persisted history against nex_ae_test with direct DB checks.",
    ),
)

SENSITIVE_PATTERNS = (
    re.compile(r"postgresql\+?[^\"'\s]+", re.IGNORECASE),
    re.compile(r"nuri1004", re.IGNORECASE),
    re.compile(r"/data/nex-platform", re.IGNORECASE),
    re.compile(r"ed6@c496em", re.IGNORECASE),
    re.compile(r"service-token-[\w-]+", re.IGNORECASE),
)


def run_ae_artifact_retention_history_boundary_audit(
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
        "execution_contract_present": group_status.get("execution_contract") is True,
        "purge_guardrail_present": group_status.get("purge_guardrail") is True,
        "postgres_evidence_present": group_status.get("postgres_evidence") is True,
        "s47_closure_confirmed": group_status.get("s47_closure") is True,
        "metadata_only_history_policy": True,
        "idempotency_history_policy": True,
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
        "slice": "0471",
        "surface": "S48 AE artifact retention execution history",
        "decisions": {
            "artifact_system_of_record": "nex-ae-api",
            "history_table": RETENTION_HISTORY_TABLE,
            "execution_schema": RETENTION_EXECUTION_SCHEMA,
            "history_schema": RETENTION_HISTORY_SCHEMA,
            "history_scope": "tenant_workspace_owner",
            "history_writer": "POST /api/v1/artifact-retention/purge",
            "idempotency_scope": "tenant_id, workspace_id, owner_user_id, idempotency_key",
            "history_payload_policy": "metadata_only_execution_evidence",
            "raw_artifact_content_allowed": False,
            "storage_ref_allowed": False,
            "database_url_allowed": False,
            "handoff_lineage_retained_after_purge": True,
        },
        "paths": paths,
        "source_tokens": tokens,
        "planned_gaps": build_gap_results(),
        "checks": checks,
        "issues": issues,
        "next_slices": ["Slice_0472", "Slice_0473", "Slice_0474", "Slice_0475"],
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
            "present": item.path.is_file() or item.path.is_dir(),
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


def build_gap_results() -> list[dict[str, str | bool]]:
    return [
        {
            "name": item.name,
            "planned_slice": item.planned_slice,
            "purpose": item.purpose,
            "blocking": False,
        }
        for item in PLANNED_GAPS
    ]


def grouped_token_status(tokens: list[dict[str, object]]) -> dict[str, bool]:
    groups = sorted({str(item["group"]) for item in tokens})
    return {
        group: all(item["present"] is True for item in tokens if item["group"] == group)
        for group in groups
    }


def summarize_protected_env(env: Mapping[str, str]) -> dict[str, bool]:
    return {key: bool(env.get(key)) for key in PROTECTED_ENV_KEYS}


def write_audit_evidence(path: Path, evidence: dict[str, object]) -> None:
    serialized = json.dumps(evidence, indent=2, ensure_ascii=False)
    assert_evidence_redacted(serialized, os.environ)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(serialized + "\n", encoding="utf-8")


def assert_evidence_redacted(serialized_evidence: str, env: Mapping[str, str]) -> None:
    for key in PROTECTED_ENV_KEYS:
        value = env.get(key)
        if value and value in serialized_evidence:
            raise ValueError(f"Sensitive environment value leaked: {key}")
    for pattern in SENSITIVE_PATTERNS:
        if pattern.search(serialized_evidence):
            raise ValueError("Sensitive value leaked in audit evidence.")


def relative_label(path: Path, root_dir: Path = ROOT) -> str:
    try:
        return str(path.relative_to(root_dir))
    except ValueError:
        return path.name


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def present_count(items: list[dict[str, object]]) -> int:
    return sum(1 for item in items if item.get("present") is True)


def summary_line(evidence: dict[str, object]) -> str:
    if evidence["status"] == "PASS":
        return (
            "ae_artifact_retention_history_boundary_audit=pass "
            f"paths={present_count(evidence['paths'])}/{len(evidence['paths'])} "
            f"token_groups={present_count(evidence['source_tokens'])}/"
            f"{len(evidence['source_tokens'])} "
            f"history_table={RETENTION_HISTORY_TABLE} "
            "next=Slice_0472"
        )
    failing_checks = [
        key for key, passed in evidence.get("checks", {}).items() if passed is not True
    ]
    return (
        "ae_artifact_retention_history_boundary_audit=fail "
        f"failing_checks={','.join(failing_checks)}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run AE artifact retention execution history boundary audit."
    )
    parser.add_argument("--summary", action="store_true", help="Print a short result line.")
    parser.add_argument("--output", type=Path, help="Optional JSON evidence output path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        evidence = run_ae_artifact_retention_history_boundary_audit()
        if args.output:
            write_audit_evidence(args.output, evidence)
        print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2))
        return 0 if evidence["status"] == "PASS" else 1
    except Exception as exc:
        print(
            "ae_artifact_retention_history_boundary_audit=fail "
            f"error={exc.__class__.__name__}"
        )
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
