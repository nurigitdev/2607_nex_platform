#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping

import yaml


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/quality"))
sys.path.insert(0, str(ROOT / "services/_shared"))
sys.path.insert(0, str(ROOT / "services/nex-oa"))
sys.path.insert(0, str(ROOT / "services/nex-ag"))

from nex_ag.federated_operator_authorization import (  # noqa: E402
    AgFederatedAuthorizationTelemetry,
)
from nex_oa.contract_api_drift_audit import (  # noqa: E402
    build_oa_contract_api_drift_audit,
)
from validate_contracts import validate_contract_tree  # noqa: E402


def run_s129_contract_runtime_privacy(root: Path = ROOT) -> dict[str, Any]:
    contracts = validate_contract_tree(root / "contracts")
    oa_openapi = _yaml(root / "contracts/openapi/nex-oa.openapi.yaml")
    ag_openapi = _yaml(root / "contracts/openapi/nex-ag.openapi.yaml")
    oa_main = _text(root / "services/nex-oa/nex_oa/main.py")
    ag_main = _text(root / "services/nex-ag/nex_ag/main.py")
    oa_drift = build_oa_contract_api_drift_audit(root)
    telemetry = AgFederatedAuthorizationTelemetry()
    for outcome in (
        "authorized",
        "denied_caller",
        "denied_context",
        "denied_scope",
        "denied_role",
    ):
        telemetry.record(outcome)
    snapshot = telemetry.public_snapshot()
    checks = {
        "contracts_valid": contracts.ok
        and contracts.schema_count >= 156
        and contracts.example_count >= 214
        and contracts.negative_example_count >= 184,
        "oa_contract_published": (
            "/internal/v1/auth/federated-login" in (oa_openapi.get("paths") or {})
        ),
        "ag_contract_published": (
            "/admin/v1/auth/federated-operator-runtime"
            in (ag_openapi.get("paths") or {})
        ),
        "oa_runtime_wired": "register_federated_login_routes(" in oa_main
        and "build_federated_identity_repository_for_runtime(" in oa_main,
        "ag_runtime_wired": (
            "attach_ag_federated_authorization_telemetry(" in ag_main
            and "register_ag_federated_operator_runtime_routes(" in ag_main
        ),
        "oa_drift_reduced": oa_drift.get("status") == "PASS"
        and oa_drift.get("summary", {}).get("drift_count") == 22
        and oa_drift.get("summary", {}).get("runtime_openapi_covered_count") == 31,
        "telemetry_aggregated": set(snapshot["counts"].values()) == {1},
        "telemetry_privacy_safe": not _contains_key(
            snapshot,
            {
                "tenant_id",
                "subject_id",
                "session_id_digest",
                "provider_id",
                "external_subject",
                "id_token",
                "authorization",
            },
        ),
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": "s129_contract_runtime_privacy_evidence.v1",
        "slice": "1289",
        "requirement": "S129",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "s129_contract_runtime_privacy_failed",
        "checks": checks,
        "contract_counts": {
            "schemas": contracts.schema_count,
            "examples": contracts.example_count,
            "negative_examples": contracts.negative_example_count,
            "openapi": contracts.openapi_count,
        },
        "oa_drift": oa_drift.get("summary", {}),
        "telemetry": snapshot,
        "next_slice": "1290" if passed else "blocked",
    }


def _yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return dict(payload) if isinstance(payload, Mapping) else {}


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def _contains_key(value: object, forbidden: set[str]) -> bool:
    if isinstance(value, Mapping):
        return any(
            str(key).lower() in forbidden or _contains_key(child, forbidden)
            for key, child in value.items()
        )
    if isinstance(value, list):
        return any(_contains_key(item, forbidden) for item in value)
    return False


def summary_line(evidence: Mapping[str, Any]) -> str:
    checks = evidence.get("checks") or {}
    contracts = evidence.get("contract_counts") or {}
    return (
        "s129_contract_runtime_privacy="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"checks={sum(bool(value) for value in checks.values())}/{len(checks)} "
        f"schemas={contracts.get('schemas', 0)} "
        f"drift={(evidence.get('oa_drift') or {}).get('drift_count', 0)} "
        f"next={evidence.get('next_slice', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_s129_contract_runtime_privacy()
    print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
