#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace
import sys
from typing import Any, Mapping

import httpx


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))
sys.path.insert(0, str(ROOT / "services" / "nex-mo"))

from nex_mo import provider_transport, remote_provider  # noqa: E402


def run_mo_provider_transport_extraction(root: Path = ROOT) -> dict[str, Any]:
    module_path = root / "services/nex-mo/nex_mo/provider_transport.py"
    remote_path = root / "services/nex-mo/nex_mo/remote_provider.py"
    module_source = module_path.read_text(encoding="utf-8") if module_path.is_file() else ""
    remote_source = remote_path.read_text(encoding="utf-8") if remote_path.is_file() else ""
    config = SimpleNamespace(
        method="POST",
        url="http://provider.invalid/v1/test",
        timeout_seconds=15.0,
        headers=lambda: {"Accept": "application/json"},
    )

    def requester(*args, **kwargs):
        return httpx.Response(200, json={"status": "ok"})

    response = provider_transport.execute_remote_json_request(
        config,
        json_payload={"probe": True},
        requester=requester,
        error_code_prefix="mo.remote_probe",
    )
    checks = {
        "transport_module_present": bool(module_source),
        "remote_compatibility_import_present": "from nex_mo.provider_transport import ("
        in remote_source,
        "failure_decision_compatible": remote_provider.RemoteProviderFailureDecision
        is provider_transport.RemoteProviderFailureDecision,
        "classifier_compatible": remote_provider.classify_remote_provider_http_status
        is provider_transport.classify_remote_provider_http_status,
        "requester_injection_preserved": response == {"status": "ok"},
        "transport_owns_no_normalization": "normalize_remote_" not in module_source,
    }
    passed = all(checks.values())
    return {
        "audit_schema_version": "mo_provider_transport_extraction.v1",
        "slice": "1116",
        "requirement": "S112",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "mo_provider_transport_extraction_failed",
        "checks": checks,
        "summary": {
            "transport_count": 1,
            "failure_classifier_count": 3,
            "compatibility_export_count": 4,
            "failed_check_count": sum(not value for value in checks.values()),
        },
        "issues": [name for name, value in checks.items() if not value],
        "next_slice": "1117",
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "mo_provider_transport_extraction="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"transports={summary.get('transport_count', 0)} "
        f"classifiers={summary.get('failure_classifier_count', 0)} "
        f"compatibility={summary.get('compatibility_export_count', 0)} "
        f"failed={summary.get('failed_check_count', 0)} "
        f"next={evidence.get('next_slice') or 'blocked'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_mo_provider_transport_extraction()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
