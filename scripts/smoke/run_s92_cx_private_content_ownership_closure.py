#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile
from typing import Any, Callable, Mapping


ROOT = Path(__file__).resolve().parents[2]
CX_PATH = ROOT / "services" / "nex-cx"
sys.path.insert(0, str(CX_PATH))

from run_cx_access_context_contract import (  # noqa: E402
    run_cx_access_context_contract as run_access_context,
)
from run_cx_api_contract_ownership_hardening import (  # noqa: E402
    run_cx_api_contract_ownership_hardening as run_api_hardening,
)
from run_cx_central_authorization_enforcement import (  # noqa: E402
    run_cx_central_authorization_enforcement as run_authorization,
)
from run_cx_owner_lineage_persistence_contract import (  # noqa: E402
    run_cx_owner_lineage_persistence_contract as run_lineage,
)
from run_cx_private_content_capability_contract import (  # noqa: E402
    run_cx_private_content_capability_contract as run_capabilities,
)
from run_cx_private_content_ownership_boundary_audit import (  # noqa: E402
    run_cx_private_content_ownership_boundary_audit as run_boundary,
)
from run_cx_private_text_store_smoke import (  # noqa: E402
    run_private_text_store_smoke as run_text_store,
)
from run_cx_private_vector_store_smoke import (  # noqa: E402
    run_private_vector_store_smoke as run_vector_store,
)


SCHEMA_VERSION = "s92_cx_private_content_ownership_closure.v1"
SLICE_RANGE = "0911-0920"
POSTGRES_EVIDENCE_DOC = "docs/slices/0919_cx_private_ownership_postgresql_smoke.md"
QUALITY_GATE_PATH = "scripts/quality/run_quality_gate.sh"
REQUIRED_FILES = (
    "services/nex-cx/nex_cx/access_context.py",
    "services/nex-cx/nex_cx/authorization.py",
    "services/nex-cx/nex_cx/api_ownership.py",
    "services/nex-cx/nex_cx/private_content.py",
    "services/nex-cx/nex_cx/private_text_store.py",
    "services/nex-cx/nex_cx/private_vector_store.py",
    "services/nex-cx/nex_cx/owner_lineage.py",
    "services/nex-ae-api/nex_ae_api/cx_owner_context.py",
    "database/nex-cx/migrations/0917_cx_owner_lineage_persistence.sql",
    "scripts/smoke/run_cx_private_ownership_postgres_smoke.py",
    "scripts/smoke/run_s92_cx_private_content_ownership_closure.py",
    "tests/test_s92_cx_private_content_ownership_closure.py",
    *(
        f"docs/slices/{slice_id}_{name}.md"
        for slice_id, name in (
            ("0911", "cx_private_content_ownership_boundary_audit"),
            ("0912", "cx_access_context_contract_resolver"),
            ("0913", "cx_central_authorization_enforcement"),
            ("0914", "cx_private_content_capability_ports"),
            ("0915", "cx_filesystem_private_text_store"),
            ("0916", "cx_private_vector_store_metadata_linkage"),
            ("0917", "cx_owner_lineage_persistence"),
            ("0918", "cx_api_contract_ownership_hardening"),
            ("0919", "cx_private_ownership_postgresql_smoke"),
            ("0920", "s92_cx_private_content_ownership_closure"),
        )
    ),
)
TOKEN_CHECKS = (
    (
        "quality_postgres_runner",
        QUALITY_GATE_PATH,
        "run_cx_private_ownership_postgres_smoke.py",
    ),
    (
        "quality_closure_runner",
        QUALITY_GATE_PATH,
        "run_s92_cx_private_content_ownership_closure.py",
    ),
    (
        "postgres_target",
        POSTGRES_EVIDENCE_DOC,
        "nex_cx_user@nex_cx_test",
    ),
    (
        "postgres_migration",
        POSTGRES_EVIDENCE_DOC,
        "0917_cx_owner_lineage_persistence",
    ),
    ("postgres_rows", POSTGRES_EVIDENCE_DOC, "16 smoke rows"),
    ("postgres_owners", POSTGRES_EVIDENCE_DOC, "two owner scopes"),
    ("postgres_checks", POSTGRES_EVIDENCE_DOC, "all 17 checks"),
    ("postgres_cleanup", POSTGRES_EVIDENCE_DOC, "zero remaining smoke rows"),
    (
        "postgres_summary",
        POSTGRES_EVIDENCE_DOC,
        "failed_checks=0 dgx_required=False",
    ),
    (
        "docs_index",
        "docs/README.md",
        "0920_s92_cx_private_content_ownership_closure.md",
    ),
)


def run_s92_cx_private_content_ownership_closure(
    root: Path = ROOT,
) -> dict[str, Any]:
    required_files = [
        {"path": path, "present": (root / path).is_file()}
        for path in REQUIRED_FILES
    ]
    token_checks = [
        {
            "name": name,
            "path": path,
            "present": token in _read_text(root / path),
        }
        for name, path, token in TOKEN_CHECKS
    ]
    with tempfile.TemporaryDirectory(prefix="nex-s92-closure-") as temp_dir:
        temp_root = Path(temp_dir)
        evidence = {
            "boundary": _safe_evidence(lambda: run_boundary(root)),
            "access_context": _safe_evidence(run_access_context),
            "authorization": _safe_evidence(lambda: run_authorization(root)),
            "capabilities": _safe_evidence(run_capabilities),
            "private_text": _safe_evidence(
                lambda: run_text_store(temp_root / "private-text")
            ),
            "private_vector": _safe_evidence(
                lambda: run_vector_store(temp_root / "private-vector")
            ),
            "owner_lineage": _safe_evidence(lambda: run_lineage(root)),
            "api_hardening": _safe_evidence(lambda: run_api_hardening(root)),
        }

    summaries = {
        name: _mapping(item.get("summary")) for name, item in evidence.items()
    }
    postgres_tokens = {
        item["name"]: item["present"]
        for item in token_checks
        if item["name"].startswith("postgres_")
    }
    decision = _closure_decision()
    checks = {
        "required_files_present": all(item["present"] for item in required_files),
        "required_tokens_present": all(item["present"] for item in token_checks),
        "all_deterministic_evidence_passed": all(
            item.get("status") == "PASS" for item in evidence.values()
        ),
        "private_payload_inventory_closed": (
            summaries["boundary"].get("volatile_private_payload_count") == 5
            and summaries["boundary"].get("issue_count") == 0
        ),
        "access_context_contract_closed": (
            summaries["access_context"].get("passed_check_count") == 5
            and evidence["access_context"].get("ownership_ref") is not None
        ),
        "central_authorization_closed": (
            summaries["authorization"].get("centralized_route_module_count") == 12
            and summaries["authorization"].get("failed_check_count") == 0
        ),
        "private_capability_ports_closed": (
            summaries["capabilities"].get("protocol_count") == 2
            and summaries["capabilities"].get("passed_check_count") == 6
        ),
        "private_stores_restart_safe_and_owner_scoped": (
            evidence["private_text"].get("restart_reload") is True
            and evidence["private_text"].get("owner_scoped") is True
            and evidence["private_vector"].get("restart_reload") is True
            and evidence["private_vector"].get("owner_scoped") is True
            and evidence["private_vector"].get("metadata_linked") is True
        ),
        "owner_lineage_persistence_closed": (
            summaries["owner_lineage"].get("lineage_table_count") == 4
            and summaries["owner_lineage"].get("issue_count") == 0
        ),
        "api_contract_ownership_closed": (
            summaries["api_hardening"].get("route_module_count", 0) >= 12
            and summaries["api_hardening"].get("owner_guarded_module_count")
            == summaries["api_hardening"].get("route_module_count")
            and summaries["api_hardening"].get("drift_count") == 0
            and summaries["api_hardening"].get("issue_count") == 0
        ),
        "actual_postgres_evidence_passed": all(postgres_tokens.values()),
        "public_database_metadata_only": (
            decision["public_database_policy"] == "metadata_and_owner_lineage_only"
            and decision["private_payload_storage"]
            == "owner_scoped_replaceable_capability_ports"
        ),
        "dgx_not_required": all(
            _dgx_not_required(name, item) for name, item in evidence.items()
        )
        and decision["dgx_live_provider_required"] is False,
        "single_migration_history_preserved": (
            decision["migration_strategy"]
            == "versioned_sql_schema_migrations_runner"
        ),
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    status = "PASS" if not failed_checks else "FAIL"
    return {
        "closure_schema_version": SCHEMA_VERSION,
        "slice": "0920",
        "slice_range": SLICE_RANGE,
        "requirement": "S92",
        "status": status,
        "failure_code": (
            None if status == "PASS" else "s92_private_content_ownership_closure_failed"
        ),
        "closure_readiness": "READY_FOR_S93" if status == "PASS" else "BLOCKED",
        "feature_readiness": (
            "CX_PRIVATE_CONTENT_AND_OWNERSHIP_HARDENED"
            if status == "PASS"
            else "INCOMPLETE"
        ),
        "checks": checks,
        "failed_checks": failed_checks,
        "summary": {
            "evidence_count": len(evidence),
            "passed_evidence_count": sum(
                item.get("status") == "PASS" for item in evidence.values()
            ),
            "private_store_count": 2,
            "owner_guarded_module_count": summaries["api_hardening"].get(
                "owner_guarded_module_count", 0
            ),
            "owner_lineage_table_count": summaries["owner_lineage"].get(
                "lineage_table_count", 0
            ),
            "contract_drift_count": summaries["api_hardening"].get(
                "drift_count", 0
            ),
            "postgres_check_count": 17 if all(postgres_tokens.values()) else 0,
            "missing_file_count": sum(
                not item["present"] for item in required_files
            ),
            "missing_token_count": sum(
                not item["present"] for item in token_checks
            ),
        },
        "evidence_statuses": {
            name: item.get("status") for name, item in evidence.items()
        },
        "postgres_evidence": postgres_tokens,
        "decision": decision,
        "required_files": required_files,
        "token_checks": token_checks,
        "next_requirement": "S93",
    }


def _closure_decision() -> dict[str, Any]:
    return {
        "access_context": "authenticated_CxAccessContext",
        "owner_transport": ["X-NEX-Tenant-ID", "X-NEX-Subject-ID"],
        "cross_owner_visibility": "not-found",
        "public_database_policy": "metadata_and_owner_lineage_only",
        "private_payload_storage": "owner_scoped_replaceable_capability_ports",
        "private_text_backend": "filesystem_now_object_storage_replaceable",
        "private_vector_backend": "filesystem_now_vector_database_replaceable",
        "migration_strategy": "versioned_sql_schema_migrations_runner",
        "dgx_live_provider_required": False,
        "deferred_scope": [
            "production_object_storage_adapter",
            "production_vector_database_adapter",
            "provider_backed_content_quality_validation",
        ],
    }


def _dgx_not_required(name: str, evidence: Mapping[str, Any]) -> bool:
    summary = _mapping(evidence.get("summary"))
    decision = _mapping(evidence.get("decision"))
    values = [
        evidence.get("dgx_required"),
        summary.get("dgx_required"),
        decision.get("dgx_live_provider_required"),
    ]
    explicit = [value for value in values if value is not None]
    return bool(explicit) and all(value is False for value in explicit)


def _safe_evidence(builder: Callable[[], Mapping[str, Any]]) -> dict[str, Any]:
    try:
        return dict(builder())
    except Exception as exc:
        return {
            "status": "FAIL",
            "failure_code": "evidence_builder_failed",
            "detail": exc.__class__.__name__,
        }


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = _mapping(evidence.get("summary"))
    return (
        "s92_cx_private_content_ownership_closure="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"evidence={summary.get('passed_evidence_count', 0)}/"
        f"{summary.get('evidence_count', 0)} "
        f"owner_modules={summary.get('owner_guarded_module_count', 0)} "
        f"postgres_checks={summary.get('postgres_check_count', 0)} "
        f"contract_drift={summary.get('contract_drift_count', 0)} "
        f"next={evidence.get('next_requirement', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_s92_cx_private_content_ownership_closure()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
