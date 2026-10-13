#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any, Callable, Mapping


ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "nex-ae-api",
    ROOT / "scripts" / "smoke",
):
    sys.path.insert(0, str(path))

from nex_ae_api.agent_results import execution_destination  # noqa: E402
from run_p4_agent_runtime_postgres_smoke import (  # noqa: E402
    DATABASE_ENV,
    SMOKE_ENV as POSTGRES_SMOKE_ENV,
    run_p4_agent_runtime_postgres_smoke,
)
from run_p4_ca01_project_neutral_prompt_closure import (  # noqa: E402
    run_p4_ca01_project_neutral_prompt_closure,
)
from run_s139_ae_web_protected_acceptance import (  # noqa: E402
    _run_two_viewport_browser,
)


SCHEMA_VERSION = "p4_agent_runtime_foundation_closure.v1"
SMOKE_ENV = "NEX_AE_P4_CLOSURE"
FROZEN_MANIFESTS = (
    (
        Path(
            "docs/frozen/v2.1/00_FINAL_FREEZE/"
            "SHA256SUMS_FINAL_FREEZE_v1.0.txt"
        ),
        12,
    ),
    (
        Path(
            "docs/frozen/v2.1/10_PLATFORM_v2.1/"
            "SHA256SUMS_FINAL_v1.8.txt"
        ),
        269,
    ),
    (
        Path("docs/frozen/v2.1/20_AGENT_NSL_FROZEN/SHA256SUMS.txt"),
        31,
    ),
)
P4_MIGRATIONS = tuple(
    Path(f"database/nex-ae-api/migrations/200{number}_{name}.sql")
    for number, name in (
        (1, "ae_agent_identity"),
        (2, "ae_conversation_journal"),
        (3, "ae_agent_execution"),
        (4, "ae_runtime_job"),
        (5, "ae_executable_step"),
        (6, "ae_agent_result"),
    )
)
P4_RUNTIME_SOURCES = tuple(
    Path(f"services/nex-ae-api/nex_ae_api/{name}.py")
    for name in (
        "agent_identity",
        "conversation_journal",
        "agent_execution",
        "runtime_jobs",
        "executable_steps",
        "agent_results",
        "agent_runtime_foundation",
    )
)
P4_DESIGN_SOURCES = (
    Path("docs/transition/P4/P4_Agent_Runtime_Foundation_SRS_v1.1.md"),
    Path("docs/transition/P4/P4_Source_Audit_and_Implementation_Plan_v1.1.md"),
    Path("docs/transition/P4/P4_CA01_Project_Neutral_PROMPT_ReFreeze_Addendum_v1.0.md"),
    Path("docs/transition/P4/P4_ISSUE_026_AgentResult_State_Mapping_Closure_v1.0.md"),
)
FORBIDDEN_TABLES = (
    "ae_ia_identities",
    "ae_ia_personal_scopes",
    "ae_ia_chat_runs",
    "ae_ia_runtime_jobs",
    "ae_ia_runtime_steps",
    "ae_conversation_week_summaries",
    "ae_conversation_week_heads",
)
FORBIDDEN_IMPLEMENTATION_TOKENS = (
    "DEFAULT_PROJECT",
    "MOCK_ENTERPRISE_OS",
    "PUBLISH_RESULT",
    "ProjectAuthority",
    "WC_WORK_RESULT",
)
FORBIDDEN_PROVIDER_IMPORTS = (
    "import httpx",
    "import requests",
    "import urllib.request",
    "from httpx",
    "from requests",
    "from urllib.request",
)

EvidenceRunner = Callable[[Mapping[str, str]], dict[str, Any]]


def run_p4_agent_runtime_foundation_closure(
    environ: Mapping[str, str] | None = None,
    *,
    root: Path = ROOT,
    postgres_runner: EvidenceRunner = run_p4_agent_runtime_postgres_smoke,
    playwright_runner: EvidenceRunner = _run_two_viewport_browser,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(SMOKE_ENV) != "1":
        return {
            "closure_schema_version": SCHEMA_VERSION,
            "slice": "P4-S9",
            "status": "SKIPPED",
            "skip_reason": f"{SMOKE_ENV} is not enabled.",
        }

    static = _static_evidence(root)
    ca01 = run_p4_ca01_project_neutral_prompt_closure(root)
    postgres = postgres_runner({**env, POSTGRES_SMOKE_ENV: "1"})
    playwright = playwright_runner(env)
    postgres_checks = dict(postgres.get("checks") or {})
    playwright_checks = dict(playwright.get("checks") or {})
    redaction = dict(playwright.get("redaction") or {})

    checks = {
        **static["checks"],
        "ca01_contract_and_amendment_integrity_passed": (
            ca01.get("status") == "PASS"
        ),
        "actual_ae_test_postgresql_smoke_passed": (
            postgres.get("status") == "PASS"
            and postgres.get("actual_postgres") is True
            and postgres.get("database") == "nex_ae_test"
        ),
        "postgres_restart_idempotency_privacy_checks_passed": (
            bool(postgres_checks)
            and all(postgres_checks.values())
            and postgres_checks.get("restart_trace_restored") is True
            and postgres_checks.get("result_idempotent") is True
            and postgres_checks.get("runtime_metadata_private") is True
        ),
        "postgres_zero_residue_passed": (
            (postgres.get("cleanup_counts") or {}).get("remaining") == 0
        ),
        "actual_korean_chat_rag_playwright_passed": (
            playwright.get("status") == "PASS"
            and playwright.get("runner", {}).get("browser") == "chromium"
            and len(playwright.get("viewports") or ()) == 2
            and bool(playwright_checks)
            and all(playwright_checks.values())
        ),
        "playwright_evidence_redacted": bool(redaction)
        and not any(redaction.values()),
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    return {
        "closure_schema_version": SCHEMA_VERSION,
        "slice": "P4-S9",
        "requirement": "P4 IA Runtime Foundation",
        "status": "PASS" if not failed_checks else "FAIL",
        "checks": checks,
        "failed_checks": failed_checks,
        "frozen_integrity": static["frozen_integrity"],
        "excluded_scope_hits": static["excluded_scope_hits"],
        "ca01": {
            "status": ca01.get("status"),
            "probe_count": (ca01.get("summary") or {}).get("probe_count", 0),
            "manifest_entry_count": (ca01.get("summary") or {}).get(
                "manifest_entry_count", 0
            ),
        },
        "postgres": _postgres_projection(postgres),
        "playwright": _playwright_projection(playwright),
        "deferred": [
            "result publication preflight and PUBLISH_RESULT job",
            "required delivery ACK and terminal successful finalization",
            "WC delegation and Project Agent runtime",
            "canonical Agent Memory and weekly digest",
        ],
    }


def _static_evidence(root: Path) -> dict[str, Any]:
    frozen = [
        _verify_hash_manifest(root, manifest, expected_count)
        for manifest, expected_count in FROZEN_MANIFESTS
    ]
    runtime_text = _read_sources(root, P4_RUNTIME_SOURCES)
    migration_text = _read_sources(root, P4_MIGRATIONS)
    implementation_hits = _token_hits(runtime_text, FORBIDDEN_IMPLEMENTATION_TOKENS)
    table_hits = _token_hits(migration_text, FORBIDDEN_TABLES)
    provider_hits = _token_hits(runtime_text, FORBIDDEN_PROVIDER_IMPORTS)
    route_hits = _token_hits(
        runtime_text,
        ("@router.", "APIRouter(", "add_api_route("),
    )
    succeeded_destination = execution_destination("SUCCEEDED")
    partial_destination = execution_destination("PARTIAL")
    return {
        "checks": {
            "p4_migration_chain_present": all(
                (root / path).is_file() for path in P4_MIGRATIONS
            ),
            "p4_runtime_modules_present": all(
                (root / path).is_file() for path in P4_RUNTIME_SOURCES
            ),
            "p4_v1_1_design_sources_present": all(
                (root / path).is_file() for path in P4_DESIGN_SOURCES
            ),
            "frozen_sha256_manifests_passed": all(
                item["status"] == "PASS" for item in frozen
            ),
            "fake_project_alternate_runtime_weekly_digest_absent": not (
                implementation_hits or table_hits
            ),
            "new_direct_provider_client_absent": not provider_hits,
            "new_public_route_surface_absent": not route_hits,
            "success_capable_result_waits_for_ack": (
                succeeded_destination == ("RUNNING", "RESULT_PUBLISH", False)
                and partial_destination == ("RUNNING", "RESULT_PUBLISH", False)
            ),
        },
        "frozen_integrity": frozen,
        "excluded_scope_hits": {
            "implementation": implementation_hits,
            "tables": table_hits,
            "provider_imports": provider_hits,
            "public_routes": route_hits,
        },
    }


def _verify_hash_manifest(
    root: Path, manifest_path: Path, expected_count: int
) -> dict[str, Any]:
    manifest = root / manifest_path
    if not manifest.is_file():
        return {
            "manifest": str(manifest_path),
            "status": "FAIL",
            "expected_count": expected_count,
            "entry_count": 0,
            "matched_count": 0,
        }
    entries: list[bool] = []
    for line in manifest.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            entries.append(False)
            continue
        expected_hash, raw_name = parts
        relative = Path(raw_name.strip().lstrip("*"))
        safe = not relative.is_absolute() and ".." not in relative.parts
        target = manifest.parent / relative
        entries.append(
            safe
            and target.is_file()
            and hashlib.sha256(target.read_bytes()).hexdigest() == expected_hash
        )
    matched = sum(entries)
    passed = len(entries) == expected_count and matched == expected_count
    return {
        "manifest": str(manifest_path),
        "status": "PASS" if passed else "FAIL",
        "expected_count": expected_count,
        "entry_count": len(entries),
        "matched_count": matched,
    }


def _read_sources(root: Path, paths: tuple[Path, ...]) -> dict[str, str]:
    return {
        str(path): (root / path).read_text(encoding="utf-8")
        if (root / path).is_file()
        else ""
        for path in paths
    }


def _token_hits(
    sources: Mapping[str, str], tokens: tuple[str, ...]
) -> list[str]:
    return sorted(
        f"{path}:{token}"
        for path, content in sources.items()
        for token in tokens
        if token in content
    )


def _postgres_projection(evidence: Mapping[str, Any]) -> dict[str, Any]:
    checks = dict(evidence.get("checks") or {})
    return {
        "status": evidence.get("status"),
        "actual_postgres": evidence.get("actual_postgres") is True,
        "database": evidence.get("database"),
        "check_count": len(checks),
        "passed_check_count": sum(value is True for value in checks.values()),
        "cleanup_remaining": (evidence.get("cleanup_counts") or {}).get(
            "remaining"
        ),
    }


def _playwright_projection(evidence: Mapping[str, Any]) -> dict[str, Any]:
    checks = dict(evidence.get("checks") or {})
    return {
        "status": evidence.get("status"),
        "browser": (evidence.get("runner") or {}).get("browser"),
        "viewport_count": len(evidence.get("viewports") or ()),
        "check_count": len(checks),
        "passed_check_count": sum(value is True for value in checks.values()),
        "issue_count": len(evidence.get("issues") or ()),
    }


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") == "SKIPPED":
        return "p4_agent_runtime_foundation_closure=skipped"
    checks = dict(evidence.get("checks") or {})
    frozen = evidence.get("frozen_integrity") or ()
    return (
        "p4_agent_runtime_foundation_closure="
        f"{str(evidence.get('status') or 'FAIL').lower()} "
        f"checks={sum(value is True for value in checks.values())}/{len(checks)} "
        f"frozen={sum(item.get('matched_count', 0) for item in frozen)}/312 "
        f"postgres={str((evidence.get('postgres') or {}).get('status') or 'not-run').lower()} "
        f"playwright={str((evidence.get('playwright') or {}).get('status') or 'not-run').lower()}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    evidence = run_p4_agent_runtime_foundation_closure()
    rendered = json.dumps(evidence, ensure_ascii=True, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(summary_line(evidence) if args.summary else rendered)
    return 0 if evidence["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
