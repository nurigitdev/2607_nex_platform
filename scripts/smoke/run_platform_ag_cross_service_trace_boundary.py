#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "platform_ag_cross_service_trace_boundary.v1"
CANONICAL_DOCUMENT = "docs/45_platform_ag_cross_service_trace_operations_e2e.md"


@dataclass(frozen=True)
class EvidenceToken:
    group: str
    path: str
    token: str


REQUIRED_PATHS = (
    "docs/37_platform_mvp_integration_release_plan.md",
    "docs/38_platform_mvp_vertical_spine_reaudit.md",
    "docs/44_platform_grounded_generation_artifact_e2e.md",
    CANONICAL_DOCUMENT,
    "services/nex-ag/nex_ag/cross_service_trace.py",
    "services/nex-ag/nex_ag/generation_audit.py",
    "services/nex-ag/nex_ag/artifact_operations.py",
    "services/nex-cx/nex_cx/generation.py",
    "services/_shared/nex_runtime/ag_projection_policy.py",
    "services/_shared/nex_runtime/platform_trust_scope_policy.py",
    "scripts/quality/run_quality_gate.sh",
    "docs/slices/1372_platform_ag_cross_service_trace_boundary.md",
)

TOKENS = (
    EvidenceToken(
        "s137_handoff",
        "docs/44_platform_grounded_generation_artifact_e2e.md",
        "S138 receives metadata-safe trace and operations projections only",
    ),
    EvidenceToken(
        "ag_trace_route",
        "services/nex-ag/nex_ag/cross_service_trace.py",
        '"/admin/v1/operations/traces/{trace_id}"',
    ),
    EvidenceToken(
        "ag_generation_http",
        "services/nex-ag/nex_ag/generation_audit.py",
        "class HttpGenerationAuditSourceClient",
    ),
    EvidenceToken(
        "ag_artifact_http",
        "services/nex-ag/nex_ag/artifact_operations.py",
        "class HttpAeArtifactOperationsClient",
    ),
    EvidenceToken(
        "cx_owner_route",
        "services/nex-cx/nex_cx/generation.py",
        "authorize_cx_owner_request(",
    ),
    EvidenceToken(
        "protected_api_mode",
        "services/_shared/nex_runtime/ag_projection_policy.py",
        "legacy_database_adapter_allowed=False",
    ),
    EvidenceToken(
        "legacy_adapter_quarantine",
        "docs/slices/1318_platform_ag_api_projection_policy.md",
        "compatibility adapters are quarantined",
    ),
    EvidenceToken(
        "quality_hook",
        "scripts/quality/run_quality_gate.sh",
        "run_platform_ag_cross_service_trace_boundary.py",
    ),
)

GAPS = {
    "redacted_trace_envelope_contract": "1373",
    "cx_admin_trace_projection": "1374",
    "ae_trace_projection": "1375",
    "oa_mo_trace_projection": "1376",
    "ag_service_api_timeline_aggregation": "1377",
    "ag_durable_audit_operations": "1378",
    "deterministic_trace_e2e": "1379",
    "protected_postgres_trace_e2e": "1380",
}


def run_platform_ag_cross_service_trace_boundary(
    root: Path = ROOT,
) -> dict[str, Any]:
    paths = {path: (root / path).is_file() for path in REQUIRED_PATHS}
    tokens = {
        item.group: item.token in _read_text(root / item.path)
        for item in TOKENS
    }
    canonical = _normalized_text(root / CANONICAL_DOCUMENT)
    gaps = {name: "OPEN" for name in GAPS}
    checks = {
        "required_paths_present": all(paths.values()),
        "required_tokens_present": all(tokens.values()),
        "s137_handoff_bound": tokens.get("s137_handoff") is True,
        "existing_http_foundations_identified": all(
            tokens.get(name) is True
            for name in ("ag_generation_http", "ag_artifact_http")
        ),
        "owner_scoped_cx_gap_visible": tokens.get("cx_owner_route") is True,
        "managed_profiles_are_api_only": all(
            tokens.get(name) is True
            for name in ("protected_api_mode", "legacy_adapter_quarantine")
        ),
        "eight_integration_gaps_frozen": (
            len(gaps) == 8
            and all(slice_id in canonical for slice_id in GAPS.values())
        ),
        "ownership_privacy_and_scope_rules_frozen": all(
            token in canonical
            for token in (
                "AG must not read another service's database",
                "service:call` and `operations:read",
                "prompts, source text, evidence text, generated text",
                "stable opaque digests",
            )
        ),
        "s139_handoff_frozen": (
            "## S139 Handoff" in canonical
            and "may not consume AG database rows" in canonical
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
        "slice": "1372",
        "requirement": "S138",
        "status": "PASS" if passed else "FAIL",
        "boundary_readiness": "BOUNDARY_FROZEN" if passed else "AUDIT_FAILED",
        "checks": checks,
        "issues": issues,
        "required_paths": paths,
        "evidence_tokens": tokens,
        "gap_states": gaps,
        "summary": {
            "required_path_count": sum(paths.values()),
            "evidence_token_count": sum(tokens.values()),
            "integration_gap_count": len(gaps),
            "open_gap_count": len(gaps),
            "missing_path_count": sum(not value for value in paths.values()),
            "missing_token_count": sum(not value for value in tokens.values()),
        },
        "decision": {
            "new_table_required": False,
            "remote_model_provider_required": False,
            "protected_postgres_deferred_to_slice": "1380",
            "legacy_cross_service_database_reads_allowed": False,
            "next_slice": "1373" if passed else "blocked",
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
            "platform_ag_cross_service_trace_boundary=fail "
            f"issues={len(result.get('issues') or [])}"
        )
    summary = dict(result.get("summary") or {})
    decision = dict(result.get("decision") or {})
    return (
        "platform_ag_cross_service_trace_boundary=pass "
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
    result = run_platform_ag_cross_service_trace_boundary()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
