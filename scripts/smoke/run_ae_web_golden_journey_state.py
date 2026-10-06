#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "ae_web_golden_journey_state_audit.v1"
STATE_PATH = "apps/nex-ae-web/src/goldenJourneyState.js"
MAIN_PATH = "apps/nex-ae-web/src/main.js"

EXPECTED_STAGES = (
    "SESSION_AUTHENTICATED",
    "UPLOAD_ACCEPTED",
    "INGESTION_INDEXED",
    "RETRIEVAL_READY",
    "GENERATION_COMPLETED",
    "GROUNDING_ACCEPTED",
    "ARTIFACT_READY",
    "PREVIEW_READY",
    "DOWNLOAD_READY",
)

FORBIDDEN_EVIDENCE_FIELDS = (
    "raw_prompt",
    "document_text",
    "generated_text",
    "source_bytes",
    "storage_ref",
    "provider_url",
    "database_url",
)


def run_ae_web_golden_journey_state(root: Path = ROOT) -> dict[str, Any]:
    source = _read_text(root / STATE_PATH)
    main = _read_text(root / MAIN_PATH)
    declared_stages = _declared_stages(source)
    checks = {
        "state_module_present": bool(source),
        "ordered_stage_contract_exact": declared_stages == EXPECTED_STAGES,
        "strict_transition_present": "stage !== expectedStage" in source,
        "terminal_guard_present": source.count('state.status === "FAILED"') >= 2,
        "opaque_reference_allowlist_present": "SAFE_REF_KEYS" in source,
        "bounded_detail_allowlist_present": "SAFE_DETAIL_KEYS" in source,
        "monotonic_timestamp_guard_present": "assertMonotonicTimestamp" in source,
        "browser_evidence_redaction_present": all(
            field in source for field in FORBIDDEN_EVIDENCE_FIELDS
        ),
        "main_composition_initializes_journey": all(
            token in main
            for token in (
                'from "./goldenJourneyState.js"',
                "goldenJourney: createGoldenJourneyState({",
                'journeyId: "journey-local-001"',
            )
        ),
        "node_contract_test_present": (
            root / "apps/nex-ae-web/test/goldenJourneyState.test.mjs"
        ).is_file(),
    }
    issues = [name for name, passed in checks.items() if not passed]
    passed = not issues
    return {
        "evidence_schema_version": SCHEMA_VERSION,
        "slice": "1384",
        "requirement": "S139",
        "status": "PASS" if passed else "FAIL",
        "journey_state_readiness": "CORRELATED_STATE_READY" if passed else "BLOCKED",
        "checks": checks,
        "issues": issues,
        "declared_stages": list(declared_stages),
        "summary": {
            "stage_count": len(declared_stages),
            "safe_ref_key_count": _set_literal_item_count(source, "SAFE_REF_KEYS"),
            "safe_detail_key_count": _set_literal_item_count(source, "SAFE_DETAIL_KEYS"),
            "forbidden_evidence_field_count": len(FORBIDDEN_EVIDENCE_FIELDS),
            "issue_count": len(issues),
        },
        "decision": {
            "private_payload_allowed": False,
            "out_of_order_transition_allowed": False,
            "new_table_required": False,
            "remote_provider_required": False,
            "next_slice": "1385" if passed else "blocked",
        },
    }


def _declared_stages(source: str) -> tuple[str, ...]:
    match = re.search(
        r"GOLDEN_JOURNEY_STAGES\s*=\s*Object\.freeze\(\[(.*?)\]\)",
        source,
        re.DOTALL,
    )
    return tuple(re.findall(r'"([A-Z][A-Z0-9_]*)"', match.group(1))) if match else ()


def _set_literal_item_count(source: str, constant: str) -> int:
    match = re.search(
        rf"{re.escape(constant)}\s*=\s*new Set\(\[(.*?)\]\)",
        source,
        re.DOTALL,
    )
    return len(re.findall(r'"[a-z][a-z0-9_]*"', match.group(1))) if match else 0


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") != "PASS":
        return (
            "ae_web_golden_journey_state=fail "
            f"issues={len(result.get('issues') or [])}"
        )
    summary = dict(result.get("summary") or {})
    decision = dict(result.get("decision") or {})
    return (
        "ae_web_golden_journey_state=pass "
        f"stages={summary.get('stage_count', 0)} "
        f"refs={summary.get('safe_ref_key_count', 0)} "
        f"details={summary.get('safe_detail_key_count', 0)} "
        f"private=false next={decision.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_ae_web_golden_journey_state()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
