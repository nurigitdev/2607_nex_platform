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

import run_ae_repaired_response_decision_postgres_smoke as api_smoke  # noqa: E402
from nex_runtime import load_env_file  # noqa: E402
from run_migrations import service_database_env  # noqa: E402


SCHEMA_VERSION = "ae_web_repaired_response_decision_postgres_smoke.v1"
SMOKE_ENV = "NEX_AE_WEB_REPAIRED_RESPONSE_DECISION_POSTGRES_SMOKE"
SMOKE_PROFILE_ENV = "NEX_AE_WEB_REPAIRED_RESPONSE_DECISION_POSTGRES_SMOKE_PROFILE"
SERVICE_ID = api_smoke.SERVICE_ID
DEFAULT_PROFILE = api_smoke.DEFAULT_PROFILE

WEB_BOUNDARY_FILES = {
    "main": ROOT / "apps" / "nex-ae-web" / "src" / "main.js",
    "client": ROOT
    / "apps"
    / "nex-ae-web"
    / "src"
    / "repairedResponseDecisionClient.js",
    "state": ROOT / "apps" / "nex-ae-web" / "src" / "repairedResponseDecisionState.js",
    "card": ROOT / "apps" / "nex-ae-web" / "src" / "repairedResponseReviewCard.js",
    "registry": ROOT / "apps" / "nex-ae-web" / "src" / "clientRegistry.js",
}
WEB_BOUNDARY_ANCHORS = {
    "main": (
        "submitRepairedResponseDecision",
        "buildRepairedResponseDecisionRequest",
        "markRepairedResponseDecisionSubmitting",
        "markRepairedResponseDecisionRecorded",
        "markRepairedResponseDecisionFailed",
        "data-repaired-response-decision-action",
        "submittedVia: \"chat_review\"",
    ),
    "client": (
        "ae_web_repaired_response_decision_client.v1",
        "createFetchRepairedResponseDecisionClient",
        "submitRepairedResponseDecision",
        "credentials: \"same-origin\"",
        "\"Content-Type\": \"application/json\"",
        "repairedResponseDecisionRoute",
    ),
    "state": (
        "ae_web_repaired_response_decision_state.v1",
        "READY_FOR_DECISION",
        "SUBMITTING",
        "RECORDED",
        "FAILED",
    ),
    "card": (
        "decisionEnabled",
        "data-repaired-response-decision-action",
        "decisionStateDisplay",
    ),
    "registry": (
        "repairedResponseDecisionClient",
        "createFetchRepairedResponseDecisionClient",
        "createMockRepairedResponseDecisionClient",
    ),
}
API_CHECKS_REPORTED = (
    "route_created_decision",
    "route_listed_decision",
    "route_loaded_decision",
    "store_loaded_decision",
    "store_list_scoped",
    "row_count",
    "raw_sensitive_absent",
)


def run_ae_web_repaired_response_decision_postgres_smoke(
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

    web_boundary = inspect_ae_web_repaired_decision_boundary()
    if not web_boundary["ok"]:
        return _failure(
            "web_boundary_invalid",
            "AE Web repaired response decision wiring anchors are missing.",
            profile=profile,
            web_boundary=web_boundary,
        )

    api_env = dict(env)
    api_env[api_smoke.SMOKE_ENV] = "1"
    api_env[api_smoke.SMOKE_PROFILE_ENV] = profile
    api_evidence = api_smoke.run_ae_repaired_response_decision_postgres_smoke(api_env)
    if api_evidence["status"] != "PASS":
        return _failure(
            "api_decision_smoke_failed",
            _safe_api_failure_detail(api_evidence),
            profile=profile,
            api_status=api_evidence.get("status"),
            api_failure_code=api_evidence.get("failure_code"),
        )

    checks = {
        "web_boundary": web_boundary["ok"],
        "api_route_created_decision": api_evidence["checks"].get(
            "route_created_decision"
        )
        is True,
        "api_store_loaded_decision": api_evidence["checks"].get("store_loaded_decision")
        is True,
        "api_row_count": api_evidence["db_observations"].get("row_count") == 1,
        "api_cleanup": api_evidence["cleanup"].get("deleted_decisions") == 1
        and api_evidence["cleanup"].get("deleted_handoffs") == 1,
    }
    failed_checks = [name for name, passed in checks.items() if not passed]
    if failed_checks:
        return _failure(
            "evidence_checks_failed",
            ", ".join(failed_checks),
            profile=profile,
            web_boundary=web_boundary,
        )

    evidence = {
        "smoke_schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "service_id": SERVICE_ID,
        "profile": profile,
        "database_env": api_evidence["database_env"],
        "redacted_database_url": api_evidence["redacted_database_url"],
        "web_boundary": web_boundary,
        "api_decision": summarize_api_decision_evidence(api_evidence),
        "repaired_response_handoff_id": api_evidence["repaired_response_handoff_id"],
        "repaired_response_decision_id": api_evidence["repaired_response_decision_id"],
        "db_observations": {
            "row_count": api_evidence["db_observations"]["row_count"],
            "handoff_row_count": api_evidence["db_observations"]["handoff_row_count"],
            "decision_schema_version": api_evidence["db_observations"][
                "decision_schema_version"
            ],
            "decision_action": api_evidence["db_observations"]["decision_action"],
        },
        "cleanup": dict(api_evidence["cleanup"]),
        "checks": checks,
    }
    assert_smoke_evidence_redacted(json.dumps(evidence, default=str), env)
    return evidence


def inspect_ae_web_repaired_decision_boundary(
    file_contents: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    missing: list[str] = []
    anchor_count = 0
    required_count = 0
    for label, anchors in WEB_BOUNDARY_ANCHORS.items():
        content = (
            file_contents.get(label, "")
            if file_contents is not None
            else WEB_BOUNDARY_FILES[label].read_text(encoding="utf-8")
        )
        missing_anchors = [anchor for anchor in anchors if anchor not in content]
        found_count = len(anchors) - len(missing_anchors)
        anchor_count += found_count
        required_count += len(anchors)
        missing.extend(f"{label}:{anchor}" for anchor in missing_anchors)
        files.append(
            {
                "label": label,
                "path": _relative_path(WEB_BOUNDARY_FILES[label]),
                "anchors_present": found_count,
                "anchors_required": len(anchors),
                "missing": missing_anchors,
            }
        )
    return {
        "ok": not missing,
        "files_checked": len(files),
        "anchors_present": anchor_count,
        "anchors_required": required_count,
        "missing": missing,
        "files": files,
    }


def summarize_api_decision_evidence(api_evidence: Mapping[str, Any]) -> dict[str, Any]:
    checks = api_evidence.get("checks", {})
    return {
        "smoke_schema_version": api_evidence.get("smoke_schema_version"),
        "status": api_evidence.get("status"),
        "migration": api_evidence.get("migration", {}),
        "checks": {
            name: checks.get(name) is True
            for name in API_CHECKS_REPORTED
            if name in checks
        },
        "request_id": api_evidence.get("request_id"),
        "trace_id": api_evidence.get("trace_id"),
        "decision_request_id": api_evidence.get("decision_request_id"),
    }


def assert_smoke_evidence_redacted(
    serialized_evidence: str,
    environ: Mapping[str, str],
) -> None:
    database_url = environ.get(service_database_env(SERVICE_ID, profile=DEFAULT_PROFILE))
    if database_url and database_url in serialized_evidence:
        raise ValueError(
            "AE Web repaired response decision smoke contains raw database URL."
        )
    if "nuri1004" in serialized_evidence:
        raise ValueError(
            "AE Web repaired response decision smoke contains database password."
        )


def _safe_api_failure_detail(api_evidence: Mapping[str, Any]) -> str:
    status = api_evidence.get("status", "UNKNOWN")
    failure_code = api_evidence.get("failure_code", "unknown")
    return f"api_status={status} api_failure_code={failure_code}"


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


def summary_line(evidence: dict[str, Any]) -> str:
    if evidence["status"] == "SKIPPED":
        return (
            "ae_web_repaired_response_decision_postgres_smoke=skipped "
            f"reason={SMOKE_ENV}"
        )
    if evidence["status"] == "PASS":
        return (
            "ae_web_repaired_response_decision_postgres_smoke=pass "
            f"service={evidence['service_id']} "
            f"db_env={evidence['database_env']} "
            f"handoff_id={evidence['repaired_response_handoff_id']} "
            f"decision_id={evidence['repaired_response_decision_id']} "
            f"row_count={evidence['db_observations']['row_count']} "
            f"web_anchors={evidence['web_boundary']['anchors_present']}/"
            f"{evidence['web_boundary']['anchors_required']} "
            f"deleted_decisions={evidence['cleanup']['deleted_decisions']} "
            f"deleted_handoffs={evidence['cleanup']['deleted_handoffs']}"
        )
    return (
        "ae_web_repaired_response_decision_postgres_smoke=fail "
        f"service={evidence.get('service_id')} "
        f"reason={evidence.get('failure_code')}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run optional AE Web repaired decision PostgreSQL smoke."
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
    evidence = run_ae_web_repaired_response_decision_postgres_smoke()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, default=str))
    return 1 if evidence["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
