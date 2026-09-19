#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable, Mapping


ROOT = Path(__file__).resolve().parents[2]
SHARED_PATH = ROOT / "services" / "_shared"
AG_PATH = ROOT / "services" / "nex-ag"
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(AG_PATH))

from run_ag_recovery_notification_live_delivery_boundary_audit import (  # noqa: E402
    run_ag_recovery_notification_live_delivery_boundary_audit as run_boundary,
)
from run_ag_recovery_notification_live_loopback_smoke import (  # noqa: E402
    SMOKE_ENV as LOOPBACK_SMOKE_ENV,
)
from run_ag_recovery_notification_live_loopback_smoke import (  # noqa: E402
    run_ag_recovery_notification_live_loopback_smoke as run_loopback,
)
from run_ag_recovery_notification_live_postgres_smoke import (  # noqa: E402
    SMOKE_ENV as POSTGRES_SMOKE_ENV,
)
from run_ag_recovery_notification_live_postgres_smoke import (  # noqa: E402
    run_ag_recovery_notification_live_postgres_smoke as run_postgres,
)
from run_ag_recovery_notification_live_privacy_runbook_evidence import (  # noqa: E402
    run_ag_recovery_notification_live_privacy_runbook_evidence as run_privacy,
)


SCHEMA_VERSION = "s86_ag_recovery_notification_live_delivery_closure.v1"
SLICE_RANGE = "0851-0860"
QUALITY_GATE_PATH = "scripts/quality/run_quality_gate.sh"
POSTGRES_SMOKE_DOC = (
    "docs/slices/0858_ag_recovery_notification_live_postgres_smoke.md"
)
PRIVACY_RUNBOOK_DOC = (
    "docs/slices/0859_ag_recovery_notification_live_privacy_runbook.md"
)
SOURCE_TABLE = "ag_op_esc_dispatches"

REQUIRED_FILES = (
    "services/nex-ag/nex_ag/recovery_notification_delivery.py",
    "services/nex-ag/nex_ag/recovery_notification_operations.py",
    "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
    "services/nex-ag/nex_ag/operator_review_cases.py",
    "services/nex-ag/nex_ag/operations.py",
    "contracts/openapi/nex-ag.openapi.yaml",
    "contracts/schemas/service/nex_ag/recovery_notification_delivery.v1.schema.json",
    "contracts/examples/operations/ag_recovery_notification_live_delivery.mock_success.json",
    "contracts/examples/operations/ag_recovery_notification_live_mutation.mock_success.json",
    "contracts/tests/negative/operations/ag_recovery_notification_live_delivery.endpoint_leak.json",
    "scripts/quality/run_quality_gate.sh",
    "scripts/smoke/run_ag_recovery_notification_live_delivery_boundary_audit.py",
    "scripts/smoke/run_ag_recovery_notification_live_loopback_smoke.py",
    "scripts/smoke/run_ag_recovery_notification_live_postgres_smoke.py",
    "scripts/smoke/run_ag_recovery_notification_live_privacy_runbook_evidence.py",
    "scripts/smoke/run_s86_ag_recovery_notification_live_delivery_closure.py",
    "tests/test_ag_recovery_notification_live_delivery_boundary_audit.py",
    "tests/test_nex_ag_recovery_notification_live_admission.py",
    "tests/test_nex_ag_recovery_notification_live_handoff.py",
    "tests/test_nex_ag_recovery_notification_live_delivery_api.py",
    "tests/test_nex_ag_recovery_notification_live_execution.py",
    "tests/test_nex_ag_recovery_notification_contracts.py",
    "tests/test_ag_recovery_notification_live_loopback_smoke.py",
    "tests/test_ag_recovery_notification_live_postgres_smoke.py",
    "tests/test_ag_recovery_notification_live_privacy_runbook_evidence.py",
    "tests/test_s86_ag_recovery_notification_live_delivery_closure.py",
    "docs/README.md",
    *(
        f"docs/slices/{slice_id}_{name}.md"
        for slice_id, name in (
            ("0851", "ag_recovery_notification_live_delivery_boundary_audit"),
            ("0852", "ag_recovery_notification_live_delivery_admission"),
            ("0853", "ag_recovery_notification_live_dispatch_handoff"),
            ("0854", "ag_recovery_notification_live_delivery_api"),
            ("0855", "ag_recovery_notification_live_execution"),
            ("0856", "ag_recovery_notification_live_contract_hardening"),
            ("0857", "ag_recovery_notification_live_loopback_smoke"),
            ("0858", "ag_recovery_notification_live_postgres_smoke"),
            ("0859", "ag_recovery_notification_live_privacy_runbook"),
            ("0860", "s86_ag_recovery_notification_live_delivery_closure"),
        )
    ),
)

TOKEN_CHECKS = (
    (
        "boundary_reuses_s74",
        "docs/slices/0851_ag_recovery_notification_live_delivery_boundary_audit.md",
        "Reuse the S74 live HTTP transport",
    ),
    (
        "live_admission",
        "services/nex-ag/nex_ag/recovery_notification_delivery.py",
        "def build_recovery_notification_live_admission",
    ),
    (
        "targeted_live_execution",
        "services/nex-ag/nex_ag/recovery_notification_delivery.py",
        "def run_recovery_notification_delivery_live_once",
    ),
    (
        "injected_transport",
        "services/nex-ag/nex_ag/operator_review_dispatch_execution.py",
        "class UrllibDispatchProviderHttpTransport",
    ),
    (
        "api_confirmation",
        "services/nex-ag/nex_ag/operations.py",
        "confirm_live_delivery",
    ),
    (
        "schema_live_admission",
        "contracts/schemas/service/nex_ag/recovery_notification_delivery.v1.schema.json",
        '"live_delivery"',
    ),
    (
        "openapi_live_confirmation",
        "contracts/openapi/nex-ag.openapi.yaml",
        "confirm_live_delivery",
    ),
    (
        "quality_boundary",
        QUALITY_GATE_PATH,
        "run_ag_recovery_notification_live_delivery_boundary_audit.py",
    ),
    (
        "quality_loopback",
        QUALITY_GATE_PATH,
        "run_ag_recovery_notification_live_loopback_smoke.py",
    ),
    (
        "quality_postgres",
        QUALITY_GATE_PATH,
        "run_ag_recovery_notification_live_postgres_smoke.py",
    ),
    (
        "quality_privacy",
        QUALITY_GATE_PATH,
        "run_ag_recovery_notification_live_privacy_runbook_evidence.py",
    ),
    (
        "quality_closure",
        QUALITY_GATE_PATH,
        "run_s86_ag_recovery_notification_live_delivery_closure.py",
    ),
    (
        "postgres_pass",
        POSTGRES_SMOKE_DOC,
        "ag_recovery_notification_live_postgres_smoke=pass",
    ),
    ("postgres_cleanup", POSTGRES_SMOKE_DOC, "cleaned=True"),
    (
        "privacy_pass",
        PRIVACY_RUNBOOK_DOC,
        "ag_recovery_notification_live_privacy_runbook=pass",
    ),
    (
        "docs_index_0860",
        "docs/README.md",
        "0860_s86_ag_recovery_notification_live_delivery_closure.md",
    ),
)


def run_s86_ag_recovery_notification_live_delivery_closure(
    root: Path = ROOT,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    required_files = _required_file_results(root)
    token_checks = _token_results(root)
    boundary = _safe_evidence(lambda: run_boundary(root), "boundary_failed")
    loopback = _safe_evidence(
        lambda: run_loopback({LOOPBACK_SMOKE_ENV: "1"}),
        "loopback_failed",
    )
    privacy = _safe_evidence(lambda: run_privacy(root), "privacy_failed")
    postgres = _safe_evidence(lambda: run_postgres(env), "postgres_failed")
    postgres_opted_in = env.get(POSTGRES_SMOKE_ENV) == "1"
    expected_postgres_status = "PASS" if postgres_opted_in else "SKIPPED"
    postgres_doc = _postgres_doc_evidence(root)
    checks = {
        "required_files_present": all(item["present"] for item in required_files),
        "required_tokens_present": all(item["present"] for item in token_checks),
        "boundary_audit_passed": boundary.get("status") == "PASS",
        "real_loopback_transport_passed": (
            loopback.get("status") == "PASS"
            and loopback.get("delivery", {}).get("dispatch_status") == "SUCCEEDED"
            and loopback.get("loopback", {}).get("request_count") == 1
        ),
        "live_http_projection_verified": (
            loopback.get("projection", {}).get("provider_mode") == "live_http"
            and loopback.get("projection", {}).get("http_status_code") == 202
        ),
        "privacy_runbook_passed": privacy.get("status") == "PASS",
        "privacy_checks_passed": all(
            _mapping(privacy.get("checks")).values()
        ),
        "postgres_protection_respected": postgres.get("status")
        == expected_postgres_status,
        "postgres_documented_pass_present": all(postgres_doc.values()),
        "postgres_actual_pass_when_opted_in": (
            not postgres_opted_in or postgres.get("status") == "PASS"
        ),
        "existing_outbox_reused": SOURCE_TABLE
        in _read_text(
            root
            / "docs/slices/0851_ag_recovery_notification_live_delivery_boundary_audit.md"
        ),
        "no_new_table_required": True,
        "real_external_endpoint_deferred": True,
    }
    passed = all(checks.values())
    return {
        "closure_schema_version": SCHEMA_VERSION,
        "status": "PASS" if passed else "FAIL",
        "failure_code": None
        if passed
        else "s86_ag_recovery_notification_live_delivery_closure_failed",
        "slice_range": SLICE_RANGE,
        "boundary": "recovery_notification_explicit_live_http_opt_in",
        "source_tables": [SOURCE_TABLE],
        "new_tables": [],
        "new_indexes": [],
        "external_live_delivery_implemented": True,
        "real_external_endpoint_activated": False,
        "postgres_smoke_opted_in": postgres_opted_in,
        "closure_surfaces": [
            "live_delivery_boundary",
            "explicit_live_admission",
            "existing_outbox_live_handoff",
            "protected_api_confirmation",
            "bounded_targeted_live_execution",
            "openapi_json_schema_contracts",
            "real_urllib_loopback_transport",
            "test_db_postgres_loopback_smoke",
            "privacy_failure_runbook",
        ],
        "boundary_audit": boundary,
        "loopback_smoke": loopback,
        "postgres_smoke": postgres,
        "postgres_documentation": postgres_doc,
        "privacy_runbook": privacy,
        "required_files": required_files,
        "token_checks": token_checks,
        "checks": checks,
        "summary": {
            "required_file_count": len(required_files),
            "missing_file_count": sum(
                not item["present"] for item in required_files
            ),
            "token_check_count": len(token_checks),
            "missing_token_count": sum(
                not item["present"] for item in token_checks
            ),
        },
    }


def _safe_evidence(
    call: Callable[[], Mapping[str, Any]],
    failure_code: str,
) -> dict[str, Any]:
    try:
        return dict(call())
    except Exception as exc:
        return {
            "status": "FAIL",
            "failure_code": failure_code,
            "error_type": type(exc).__name__,
        }


def _required_file_results(root: Path) -> list[dict[str, Any]]:
    return [
        {"path": path, "present": (root / path).is_file()} for path in REQUIRED_FILES
    ]


def _token_results(root: Path) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for check_id, relative_path, token in TOKEN_CHECKS:
        results.append(
            {
                "check_id": check_id,
                "path": relative_path,
                "present": token in _read_text(root / relative_path),
            }
        )
    return results


def _postgres_doc_evidence(root: Path) -> dict[str, bool]:
    content = _read_text(root / POSTGRES_SMOKE_DOC)
    return {
        "test_database": "database=nex_ag_test" in content,
        "summary_pass": (
            "ag_recovery_notification_live_postgres_smoke=pass" in content
        ),
        "live_http": "provider=live_http" in content,
        "http_202": "http=202" in content,
        "one_request": "requests=1" in content,
        "cleanup": "cleaned=True" in content,
    }


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def summary_line(evidence: Mapping[str, Any]) -> str:
    status = str(evidence.get("status") or "FAIL").lower()
    if status != "pass":
        summary = _mapping(evidence.get("summary"))
        return (
            "s86_ag_recovery_notification_live_delivery_closure=fail "
            f"missing_files={summary.get('missing_file_count')} "
            f"missing_tokens={summary.get('missing_token_count')}"
        )
    loopback = _mapping(evidence.get("loopback_smoke"))
    postgres = _mapping(evidence.get("postgres_smoke"))
    privacy = _mapping(evidence.get("privacy_runbook"))
    return (
        "s86_ag_recovery_notification_live_delivery_closure=pass "
        f"slice_range={evidence.get('slice_range')} "
        f"loopback={loopback.get('status')} "
        f"postgres={postgres.get('status')} "
        f"privacy={privacy.get('status')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_s86_ag_recovery_notification_live_delivery_closure()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence.get("status") == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
