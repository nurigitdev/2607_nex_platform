#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SHARED_PATH = ROOT / "services" / "_shared"
DB_SCRIPT_PATH = ROOT / "scripts" / "db"
SMOKE_PATH = ROOT / "scripts" / "smoke"
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(DB_SCRIPT_PATH))
sys.path.insert(0, str(SMOKE_PATH))

import run_ae_web_repaired_response_decision_postgres_smoke as decision_smoke  # noqa: E402
from nex_runtime import load_env_file  # noqa: E402
from run_migrations import service_database_env  # noqa: E402


SCHEMA_VERSION = "ae_web_repaired_response_review_diagnostics_postgres_smoke.v1"
SMOKE_ENV = "NEX_AE_WEB_REPAIRED_RESPONSE_REVIEW_DIAGNOSTICS_POSTGRES_SMOKE"
SMOKE_PROFILE_ENV = (
    "NEX_AE_WEB_REPAIRED_RESPONSE_REVIEW_DIAGNOSTICS_POSTGRES_SMOKE_PROFILE"
)
SERVICE_ID = decision_smoke.SERVICE_ID
DEFAULT_PROFILE = decision_smoke.DEFAULT_PROFILE

WEB_DIAGNOSTICS_FILES = {
    "main": ROOT / "apps" / "nex-ae-web" / "src" / "main.js",
    "runtime_diagnostics": ROOT
    / "apps"
    / "nex-ae-web"
    / "src"
    / "runtimeDiagnostics.js",
    "read_model": ROOT
    / "apps"
    / "nex-ae-web"
    / "src"
    / "repairedResponseReviewReadModel.js",
}
WEB_DIAGNOSTICS_ANCHORS = {
    "main": (
        "buildWorkspaceRepairedResponseReviewReadModel",
        "repairedResponseReviewReadModel:",
        "summary.repaired_response_review_count",
        "summary.repaired_response_actionable_count",
        "summary.repaired_response_failed_count",
    ),
    "runtime_diagnostics": (
        "buildRepairedResponseReviewReadModelSummary",
        "repaired_response_reviews",
        "repaired_response_review_count",
        "repaired_response_actionable_count",
        "repaired_response_failed_count",
    ),
    "read_model": (
        "ae_web_repaired_response_review_read_model.v1",
        "buildRepairedResponseReviewReadModel",
        "buildRepairedResponseReviewReadModelSummary",
        "actionable_count",
        "failed_count",
    ),
}


def run_ae_web_repaired_response_review_diagnostics_postgres_smoke(
    environ: dict[str, str] | None = None,
) -> dict[str, Any]:
    env = environ if environ is not None else os.environ
    if env.get(SMOKE_ENV) != "1":
        return {
            "smoke_schema_version": SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
        }

    profile = env.get(SMOKE_PROFILE_ENV, DEFAULT_PROFILE)
    if profile != DEFAULT_PROFILE:
        return _failure(
            "profile_not_allowed",
            f"{SMOKE_PROFILE_ENV} must be test for write smoke execution.",
            profile=profile,
        )

    diagnostics_boundary = inspect_ae_web_repaired_review_diagnostics_boundary()
    if not diagnostics_boundary["ok"]:
        return _failure(
            "diagnostics_boundary_invalid",
            "AE Web repaired response diagnostics anchors are missing.",
            profile=profile,
            diagnostics_boundary=diagnostics_boundary,
        )

    decision_env = dict(env)
    decision_env[decision_smoke.SMOKE_ENV] = "1"
    decision_env[decision_smoke.SMOKE_PROFILE_ENV] = profile
    decision_evidence = (
        decision_smoke.run_ae_web_repaired_response_decision_postgres_smoke(
            decision_env
        )
    )
    if decision_evidence["status"] != "PASS":
        return _failure(
            "decision_postgres_smoke_failed",
            _safe_decision_failure_detail(decision_evidence),
            profile=profile,
            decision_status=decision_evidence.get("status"),
            decision_failure_code=decision_evidence.get("failure_code"),
        )

    decision_checks = {
        "diagnostics_boundary": diagnostics_boundary["ok"],
        "decision_postgres_smoke": decision_evidence["status"] == "PASS",
        "decision_web_boundary": decision_evidence.get("web_boundary", {}).get("ok")
        is True,
        "decision_api_route": decision_evidence.get("checks", {}).get(
            "api_route_created_decision"
        )
        is True,
        "decision_row_count": decision_evidence.get("db_observations", {}).get(
            "row_count"
        )
        == 1,
        "decision_cleanup": decision_evidence.get("cleanup", {}).get(
            "deleted_decisions"
        )
        == 1
        and decision_evidence.get("cleanup", {}).get("deleted_handoffs") == 1,
    }
    failed_checks = [
        check_id for check_id, passed in decision_checks.items() if not passed
    ]
    if failed_checks:
        return _failure(
            "evidence_checks_failed",
            ",".join(failed_checks),
            profile=profile,
            diagnostics_boundary=diagnostics_boundary,
        )

    evidence = {
        "smoke_schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "service_id": SERVICE_ID,
        "profile": profile,
        "database_env": decision_evidence["database_env"],
        "redacted_database_url": decision_evidence["redacted_database_url"],
        "diagnostics_boundary": diagnostics_boundary,
        "decision_smoke": summarize_decision_smoke_evidence(decision_evidence),
        "repaired_response_handoff_id": decision_evidence[
            "repaired_response_handoff_id"
        ],
        "repaired_response_decision_id": decision_evidence[
            "repaired_response_decision_id"
        ],
        "db_observations": dict(decision_evidence["db_observations"]),
        "cleanup": dict(decision_evidence["cleanup"]),
        "checks": decision_checks,
        "redaction_summary": {
            "database_url_included": False,
            "service_token_included": False,
            "provider_api_key_included": False,
            "raw_prompt_included": False,
            "raw_generation_output_included": False,
            "raw_source_document_text_included": False,
            "storage_path_included": False,
        },
    }
    assert_smoke_evidence_redacted(json.dumps(evidence, default=str), env)
    return evidence


def inspect_ae_web_repaired_review_diagnostics_boundary(
    file_contents: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    missing: list[str] = []
    anchors_present = 0
    anchors_required = 0
    for label, anchors in WEB_DIAGNOSTICS_ANCHORS.items():
        content = (
            file_contents.get(label, "")
            if file_contents is not None
            else _read_text(WEB_DIAGNOSTICS_FILES[label])
        )
        missing_anchors = [anchor for anchor in anchors if anchor not in content]
        present_count = len(anchors) - len(missing_anchors)
        anchors_present += present_count
        anchors_required += len(anchors)
        missing.extend(f"{label}:{anchor}" for anchor in missing_anchors)
        files.append(
            {
                "label": label,
                "path": _relative_path(WEB_DIAGNOSTICS_FILES[label]),
                "anchors_present": present_count,
                "anchors_required": len(anchors),
                "missing": missing_anchors,
            }
        )
    return {
        "ok": not missing,
        "files_checked": len(files),
        "anchors_present": anchors_present,
        "anchors_required": anchors_required,
        "missing": missing,
        "files": files,
    }


def summarize_decision_smoke_evidence(
    decision_evidence: Mapping[str, Any],
) -> dict[str, Any]:
    web_boundary = decision_evidence.get("web_boundary", {})
    checks = decision_evidence.get("checks", {})
    return {
        "smoke_schema_version": decision_evidence.get("smoke_schema_version"),
        "status": decision_evidence.get("status"),
        "web_boundary": {
            "ok": web_boundary.get("ok") is True,
            "anchors_present": web_boundary.get("anchors_present", 0),
            "anchors_required": web_boundary.get("anchors_required", 0),
        },
        "checks": {
            "api_route_created_decision": checks.get("api_route_created_decision")
            is True,
            "api_store_loaded_decision": checks.get("api_store_loaded_decision")
            is True,
            "api_row_count": checks.get("api_row_count") is True,
            "api_cleanup": checks.get("api_cleanup") is True,
        },
    }


def assert_smoke_evidence_redacted(
    serialized_evidence: str,
    environ: Mapping[str, str],
) -> None:
    database_url = environ.get(service_database_env(SERVICE_ID, profile=DEFAULT_PROFILE))
    if database_url and database_url in serialized_evidence:
        raise ValueError(
            "AE Web repaired response review diagnostics smoke contains raw database URL."
        )
    if "nuri1004" in serialized_evidence:
        raise ValueError(
            "AE Web repaired response review diagnostics smoke contains database password."
        )


def _safe_decision_failure_detail(decision_evidence: Mapping[str, Any]) -> str:
    status = decision_evidence.get("status", "UNKNOWN")
    failure_code = decision_evidence.get("failure_code", "unknown")
    return f"decision_status={status} decision_failure_code={failure_code}"


def _failure(
    failure_code: str,
    detail: str,
    *,
    profile: str,
    **extra: Any,
) -> dict[str, Any]:
    evidence = {
        "smoke_schema_version": SCHEMA_VERSION,
        "status": "FAIL",
        "service_id": SERVICE_ID,
        "profile": profile,
        "failure_code": failure_code,
        "detail": detail,
    }
    evidence.update(extra)
    return evidence


def _relative_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "SKIPPED":
        return (
            "ae_web_repaired_response_review_diagnostics_postgres_smoke=skipped "
            f"reason={SMOKE_ENV}"
        )
    if evidence["status"] == "PASS":
        return (
            "ae_web_repaired_response_review_diagnostics_postgres_smoke=pass "
            f"service={evidence['service_id']} "
            f"db_env={evidence['database_env']} "
            f"decision_id={evidence['repaired_response_decision_id']} "
            f"row_count={evidence['db_observations']['row_count']} "
            f"diagnostics_anchors={evidence['diagnostics_boundary']['anchors_present']}/"
            f"{evidence['diagnostics_boundary']['anchors_required']} "
            f"deleted_decisions={evidence['cleanup']['deleted_decisions']} "
            f"deleted_handoffs={evidence['cleanup']['deleted_handoffs']}"
        )
    return (
        "ae_web_repaired_response_review_diagnostics_postgres_smoke=fail "
        f"service={evidence.get('service_id')} "
        f"reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run optional AE Web repaired response review diagnostics PostgreSQL "
            "smoke."
        )
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print a short result line.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_env_file(ROOT / ".env.local")
    evidence = run_ae_web_repaired_response_review_diagnostics_postgres_smoke()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, default=str))
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
