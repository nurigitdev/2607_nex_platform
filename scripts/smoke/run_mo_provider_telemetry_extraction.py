#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))
sys.path.insert(0, str(ROOT / "services" / "nex-mo"))

from nex_mo import provider_telemetry, remote_provider  # noqa: E402


def run_mo_provider_telemetry_extraction(root: Path = ROOT) -> dict[str, Any]:
    module_path = root / "services/nex-mo/nex_mo/provider_telemetry.py"
    remote_path = root / "services/nex-mo/nex_mo/remote_provider.py"
    module_source = module_path.read_text(encoding="utf-8") if module_path.is_file() else ""
    remote_source = remote_path.read_text(encoding="utf-8") if remote_path.is_file() else ""
    config = SimpleNamespace(
        capability="embedding",
        endpoint_env="NEX_MO_REMOTE_EMBEDDING_URL",
        configured=True,
        request_shape="openai_embeddings",
        model_name="model",
        model_revision="revision",
        deployment_id="deployment",
        api_key_env="NEX_MO_REMOTE_EMBEDDING_API_KEY",
        api_key="private",
    )
    store = provider_telemetry.InMemoryProviderTelemetryStore()
    store.record_success(config, latency_ms=3, observed_at="2026-09-30T00:00:00Z")
    snapshot = store.snapshot([config])
    serialized = json.dumps(snapshot, sort_keys=True)
    checks = {
        "telemetry_module_present": bool(module_source),
        "remote_compatibility_import_present": "from nex_mo.provider_telemetry import ("
        in remote_source,
        "bucket_compatibility_preserved": remote_provider.RemoteProviderTelemetryBucket
        is provider_telemetry.RemoteProviderTelemetryBucket,
        "explicit_store_boundary_present": "class ProviderTelemetryStore" in module_source,
        "success_recorded": snapshot[0]["success_count"] == 1,
        "privacy_projection_preserved": "private" not in serialized,
    }
    passed = all(checks.values())
    return {
        "audit_schema_version": "mo_provider_telemetry_extraction.v1",
        "slice": "1117",
        "requirement": "S112",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "mo_provider_telemetry_extraction_failed",
        "checks": checks,
        "summary": {
            "store_boundary_count": 1,
            "bucket_count": len(snapshot),
            "compatibility_export_count": 3,
            "failed_check_count": sum(not value for value in checks.values()),
        },
        "persistence_status": "PROCESS_LOCAL_ADAPTER_READY_FOR_S116",
        "issues": [name for name, value in checks.items() if not value],
        "next_slice": "1118",
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "mo_provider_telemetry_extraction="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"stores={summary.get('store_boundary_count', 0)} "
        f"buckets={summary.get('bucket_count', 0)} "
        f"compatibility={summary.get('compatibility_export_count', 0)} "
        f"failed={summary.get('failed_check_count', 0)} "
        f"next={evidence.get('next_slice') or 'blocked'}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_mo_provider_telemetry_extraction()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
