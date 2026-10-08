#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))

from nex_runtime.s146_compose import validate_s146_compose_assets  # noqa: E402


def run_object_storage_compose(root: Path = ROOT) -> dict[str, Any]:
    assets = validate_s146_compose_assets(root)
    checks = {
        "single_host_compose": assets["orchestrator"] == "docker-compose-single-host",
        "immutable_rustfs_image": "@sha256:" in assets["rustfs_image"],
        "non_root_runtime": assets["runtime_user"] == "10001:10001",
        "private_tls_route": assets["tls_route_count"] == 1,
        "no_host_port": assets["host_port_count"] == 0,
        "console_disabled": assets["console_enabled"] is False,
        "separate_owner_buckets": assets["application_bucket_count"] == 2,
        "separate_owner_credentials": assets["application_credential_pair_count"] == 2,
        "openbao_secret_references": assets["secret_reference_count"] == 20,
        "durable_non_root_volume": assets["durable_volume_count"] == 1,
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": "s146_object_storage_compose_audit.v1",
        "slice": "1460",
        "requirement": "S146",
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "metrics": {
            "bucket_count": assets["application_bucket_count"],
            "credential_pair_count": assets["application_credential_pair_count"],
            "secret_reference_count": assets["secret_reference_count"],
            "host_port_count": assets["host_port_count"],
        },
        "raw_secret_values_included": False,
        "next_slice": "1461" if passed else "blocked",
    }


def summary_line(result: Mapping[str, Any]) -> str:
    checks = dict(result.get("checks") or {})
    metrics = dict(result.get("metrics") or {})
    return (
        f"object_storage_compose={'pass' if result.get('status') == 'PASS' else 'fail'} "
        f"checks={sum(checks.values())}/{len(checks)} "
        f"buckets={metrics.get('bucket_count', 0)} "
        f"credentials={metrics.get('credential_pair_count', 0)} "
        f"host_ports={metrics.get('host_port_count', 0)} next={result.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_object_storage_compose()
    print(summary_line(result) if args.summary else json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
