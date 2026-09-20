#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
CX_PATH = ROOT / "services" / "nex-cx"
sys.path.insert(0, str(CX_PATH))

from nex_cx.private_payload_boundary import (  # noqa: E402
    build_cx_private_payload_boundary_decision,
)


def run_cx_private_payload_boundary_decision() -> dict[str, Any]:
    decision = build_cx_private_payload_boundary_decision()
    payloads = decision["payloads"]
    payload_ids = [item["payload_id"] for item in payloads]
    checks = {
        "decision_frozen": decision["decision_status"] == "FROZEN",
        "payload_set_complete": payload_ids
        == [
            "source_bytes",
            "source_texts",
            "chunk_texts",
            "embedding_vectors",
            "summary_texts",
            "summary_embedding_vectors",
        ],
        "restart_policy_complete": all(item["restart_policy"] for item in payloads),
        "durability_classified": (
            decision["summary"]["durable_count"] == 1
            and decision["summary"]["reconstructable_count"] == 1
            and decision["summary"]["adapter_required_count"] == 4
        ),
        "public_database_remains_metadata_only": (
            decision["policies"]["public_postgres_payload_policy"]
            == "metadata_hash_uri_dimension_only"
        ),
    }
    passed = all(checks.values())
    return {
        **decision,
        "status": "PASS" if passed else "FAIL",
        "failure_code": (
            None if passed else "cx_private_payload_boundary_decision_failed"
        ),
        "checks": checks,
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "cx_private_payload_boundary="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"payloads={summary.get('payload_count', 0)} "
        f"durable={summary.get('durable_count', 0)} "
        f"reconstructable={summary.get('reconstructable_count', 0)} "
        f"adapter_required={summary.get('adapter_required_count', 0)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_cx_private_payload_boundary_decision()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
