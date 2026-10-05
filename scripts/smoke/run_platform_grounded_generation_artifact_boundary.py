#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "platform_grounded_generation_artifact_boundary.v1"


@dataclass(frozen=True)
class EvidenceToken:
    group: str
    path: str
    token: str


REQUIRED_PATHS = (
    "docs/37_platform_mvp_integration_release_plan.md",
    "docs/43_platform_permission_filtered_hybrid_retrieval.md",
    "docs/44_platform_grounded_generation_artifact_e2e.md",
    "services/nex-cx/nex_cx/generation_runtime.py",
    "services/nex-cx/nex_cx/async_generation_worker.py",
    "services/nex-cx/nex_cx/citation_repair.py",
    "services/nex-ae-api/nex_ae_api/generated_response_handoff.py",
    "services/nex-ae-api/nex_ae_api/async_artifact_rendering.py",
    "services/nex-ae-api/nex_ae_api/artifacts.py",
    "contracts/schemas/service/nex_cx/retrieval_context_package.v1.schema.json",
    "scripts/quality/run_quality_gate.sh",
    "docs/slices/1362_platform_grounded_generation_artifact_boundary.md",
)

TOKENS = (
    EvidenceToken(
        "s136_handoff",
        "docs/43_platform_permission_filtered_hybrid_retrieval.md",
        "S137 is the next active requirement",
    ),
    EvidenceToken(
        "retrieval_states",
        "contracts/schemas/service/nex_cx/retrieval_context_package.v1.schema.json",
        '"LOW_CONFIDENCE"',
    ),
    EvidenceToken(
        "cx_generation_runtime",
        "services/nex-cx/nex_cx/generation_runtime.py",
        "class GroundedGenerationRuntime",
    ),
    EvidenceToken(
        "cx_async_worker",
        "services/nex-cx/nex_cx/async_generation_worker.py",
        "generate_with_bounded_citation_repair",
    ),
    EvidenceToken(
        "citation_repair",
        "services/nex-cx/nex_cx/citation_repair.py",
        "MAX_CITATION_REPAIR_ATTEMPTS = 1",
    ),
    EvidenceToken(
        "ae_response_lineage",
        "services/nex-ae-api/nex_ae_api/generated_response_handoff.py",
        "persist_ready_generated_response",
    ),
    EvidenceToken(
        "artifact_response_binding",
        "services/nex-ae-api/nex_ae_api/async_artifact_rendering.py",
        "validate_async_artifact_response_lineage",
    ),
    EvidenceToken(
        "preview_route",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        '@app.get("/api/v1/artifact-files/{artifact_file_id}/preview"',
    ),
    EvidenceToken(
        "download_route",
        "services/nex-ae-api/nex_ae_api/artifacts.py",
        '@app.get("/api/v1/artifact-files/{artifact_file_id}/download"',
    ),
    EvidenceToken(
        "quality_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_platform_grounded_generation_artifact_boundary.py",
    ),
)

GAPS = {
    "restart_safe_retrieval_materialization": "1363",
    "cx_generation_runtime_composition": "1364",
    "citation_repair_handoff_binding": "1365",
    "ae_generated_response_lineage": "1366",
    "artifact_render_lifecycle_connection": "1367",
    "preview_download_restart_recovery": "1368",
    "contract_operations_deterministic_e2e": "1369",
    "protected_postgres_live_generation_e2e": "1370",
}


def run_platform_grounded_generation_artifact_boundary(
    root: Path = ROOT,
) -> dict[str, Any]:
    paths = {path: (root / path).is_file() for path in REQUIRED_PATHS}
    tokens = {
        item.group: item.token in _read_text(root / item.path)
        for item in TOKENS
    }
    canonical = _normalized_text(
        root / "docs/44_platform_grounded_generation_artifact_e2e.md"
    )
    gap_states = {name: "OPEN" for name in GAPS}
    checks = {
        "required_paths_present": all(paths.values()),
        "required_tokens_present": all(tokens.values()),
        "s136_handoff_bound": tokens.get("s136_handoff") is True,
        "cx_generation_and_repair_foundation_present": all(
            tokens.get(name) is True
            for name in (
                "cx_generation_runtime",
                "cx_async_worker",
                "citation_repair",
            )
        ),
        "ae_response_and_artifact_foundation_present": all(
            tokens.get(name) is True
            for name in (
                "ae_response_lineage",
                "artifact_response_binding",
                "preview_route",
                "download_route",
            )
        ),
        "eight_integration_gaps_frozen": (
            len(gap_states) == 8
            and all(slice_id in canonical for slice_id in GAPS.values())
        ),
        "ownership_and_fail_closed_rules_frozen": all(
            token in canonical
            for token in (
                "AE never calls a model provider directly",
                "LOW_CONFIDENCE and NO_ANSWER packages remain generation-blocking",
                "Citation repair may run once",
                "never expose storage paths",
            )
        ),
        "s138_handoff_frozen": (
            "## S138 Handoff" in canonical
            and "may not read OA, CX, AE, or MO databases" in canonical
        ),
    }
    issues = [
        {"category": "path_missing", "path": path}
        for path, present in paths.items()
        if not present
    ]
    issues.extend(
        {"category": "token_missing", "group": group}
        for group, present in tokens.items()
        if not present
    )
    passed = all(checks.values()) and not issues
    return {
        "audit_schema_version": SCHEMA_VERSION,
        "slice": "1362",
        "requirement": "S137",
        "status": "PASS" if passed else "FAIL",
        "boundary_readiness": "BOUNDARY_FROZEN" if passed else "AUDIT_FAILED",
        "checks": checks,
        "issues": issues,
        "required_paths": paths,
        "evidence_tokens": tokens,
        "gap_states": gap_states,
        "summary": {
            "required_path_count": sum(paths.values()),
            "evidence_token_count": sum(tokens.values()),
            "integration_gap_count": len(gap_states),
            "open_gap_count": len(gap_states),
            "missing_path_count": sum(not value for value in paths.values()),
            "missing_token_count": sum(not value for value in tokens.values()),
        },
        "decision": {
            "new_table_required": False,
            "remote_generation_provider_required": False,
            "protected_live_deferred_to_slice": "1370",
            "next_slice": "1363" if passed else "blocked",
        },
    }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _normalized_text(path: Path) -> str:
    return " ".join(_read_text(path).split())


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") != "PASS":
        return (
            "platform_grounded_generation_artifact_boundary=fail "
            f"issues={len(result.get('issues') or [])}"
        )
    summary = dict(result.get("summary") or {})
    decision = dict(result.get("decision") or {})
    return (
        "platform_grounded_generation_artifact_boundary=pass "
        f"paths={summary.get('required_path_count', 0)}/{len(REQUIRED_PATHS)} "
        f"tokens={summary.get('evidence_token_count', 0)}/{len(TOKENS)} "
        f"gaps={summary.get('open_gap_count', 0)}/"
        f"{summary.get('integration_gap_count', 0)} "
        f"next={decision.get('next_slice')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_platform_grounded_generation_artifact_boundary()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
