#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SHARED_PATH = ROOT / "services" / "_shared"
CX_PATH = ROOT / "services" / "nex-cx"
sys.path.insert(0, str(SHARED_PATH))
sys.path.insert(0, str(CX_PATH))

from nex_cx.persistence_audit import (  # noqa: E402
    build_cx_persistence_gap_audit,
)


def run_cx_persistence_gap_rebaseline() -> dict[str, Any]:
    audit = build_cx_persistence_gap_audit(persistence_mode="postgres")
    private_boundaries = audit["private_payload_boundaries"]
    deferred = audit["deferred_schema_decisions"]
    checks = {
        "schema_rebaselined": (
            audit["audit_schema_version"] == "cx_persistence_gap_audit.v2"
            and audit["checkpoint_slice"] == "0903"
            and audit["checkpoint_status"] == "REBASELINED"
        ),
        "metadata_surfaces_closed": (
            audit["summary"]["surface_count"] == 10
            and audit["summary"]["durable_metadata_surface_count"] == 10
            and audit["summary"]["durable_metadata_gap_count"] == 0
        ),
        "private_payloads_separated": (
            len(private_boundaries) == 6
            and all(
                item["decision_status"]
                in {"PENDING_SLICE_0904", "FROZEN_SLICE_0904"}
                for item in private_boundaries
            )
        ),
        "only_optional_headers_deferred": (
            {item["decision_id"] for item in deferred}
            == {"lexical_index_header", "chunk_embedding_index_header"}
        ),
    }
    passed = all(checks.values())
    return {
        "evidence_schema_version": "cx_persistence_gap_rebaseline.v1",
        "slice": "0903",
        "requirement": "S91",
        "status": "PASS" if passed else "FAIL",
        "failure_code": (
            None if passed else "cx_persistence_gap_rebaseline_failed"
        ),
        "checks": checks,
        "summary": audit["summary"],
        "gap_classification": audit["gap_classification"],
        "next_slice": "0904",
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    summary = evidence.get("summary") or {}
    return (
        "cx_persistence_gap_rebaseline="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"metadata_closed={summary.get('durable_metadata_surface_count', 0)} "
        f"metadata_gaps={summary.get('durable_metadata_gap_count', 0)} "
        f"private_boundaries={summary.get('private_payload_boundary_count', 0)} "
        f"deferred_headers={summary.get('deferred_schema_decision_count', 0)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_cx_persistence_gap_rebaseline()
    print(
        summary_line(evidence)
        if args.summary
        else json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    )
    return 0 if evidence["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
