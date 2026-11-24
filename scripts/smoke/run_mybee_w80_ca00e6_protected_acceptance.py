#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from statistics import mean
from typing import Any

from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "mybee.w80_ca00e6_protected_acceptance.v1"
LIVE_CONFIRMATION_ENV = "NEX_MYBEE_W80_CA00E6_LIVE_CONFIRMATION"
DEFAULT_REPORT = ROOT / "reports/quality/mybee-w80-ca00e6-protected-acceptance.json"
DEFAULT_POSTGRES_REPORT = (
    ROOT / "reports/quality/mybee-w80-ca00e6-postgres-gate.json"
)
DEFAULT_LIVE_REPORT = (
    ROOT / "reports/deployment/mybee-w80-ca00e6-live-journey.json"
)

POSTGRES_SCRIPT = ROOT / "scripts/smoke/run_mybee_w70_cp_m1_01b6b5a5_closure.py"
LIVE_SCRIPT = (
    ROOT / "scripts/deployment/run_mybee_w70_cp_m1_product_golden_journey.py"
)

DATABASE_IDENTITIES = {
    "NEX_AE_TEST_DATABASE_URL": ("nex_ae_user", "nex_ae_test"),
    "NEX_WC_TEST_DATABASE_URL": ("nex_wc_user", "nex_wc_test"),
    "NEX_OA_TEST_DATABASE_URL": ("nex_oa_user", "nex_oa_test"),
    "NEX_EOS_TEST_DATABASE_URL": ("nex_eos_user", "nex_eos_test"),
}

MATRIX_SELECTORS = (
    "tests/test_ae_mybee_w80_ca00e1_semantic_handoff_contract.py",
    "tests/test_wc_mybee_w80_ca00e1_semantic_handoff_contract.py",
    "tests/test_ae_mybee_w80_ca00e2_semantic_handoff_reuse.py",
    "tests/test_ae_mybee_w80_ca00e4_role_scoped_plan_profiles.py",
    "tests/test_ae_p65_s5_candidate_admission_compile.py",
    "tests/test_ae_wc_p7_s5_delegate_wait.py",
    "tests/test_ae_wc_p7_s7_background_runtime.py",
)

ACCEPTANCE_MATRIX = {
    "prompt_work_classes": (
        "GENERAL_ANSWER",
        "GROUNDED_ANSWER",
        "DOCUMENT_SUMMARY",
        "DOCUMENT_GENERATION",
    ),
    "delegation_forms": ("STRUCTURED", "UNSTRUCTURED"),
    "target_agent_types": ("PA", "CA", "EA"),
    "conversation_mutations": (
        "FOLLOW_UP",
        "CORRECTION",
        "SUPERSESSION",
        "MULTI_INTENT",
    ),
    "reuse_denial_reasons": (
        "MISSING",
        "STALE",
        "LOW_CONFIDENCE",
        "AUTHORITY_CHANGED",
        "SCHEMA_DRIFT",
        "CONFLICT",
    ),
    "scope_denials": (
        "CROSS_TENANT",
        "CROSS_REQUESTER",
        "CROSS_PROJECT",
        "HASH_TAMPER",
    ),
    "authority_denials": (
        "OA_REVOKED",
        "PROJECT_INACTIVE",
        "TARGET_AGENT_INACTIVE",
    ),
    "recovery": ("EXACT_REPLAY", "RESTART", "EVENT_REDELIVERY", "ACK_LOSS"),
}

EXPECTED_SEMANTIC_STAGE_COUNTS = {"INTENT": 2, "CONTEXT": 2, "PLAN": 4}
PREVIOUS_GENERATION_REQUEST_COUNT = 12
TARGET_GENERATION_REQUEST_COUNT = 8


class W80Ca00e6AcceptanceError(RuntimeError):
    pass


CommandRunner = Callable[..., subprocess.CompletedProcess[Any]]


def run_acceptance(
    environ: Mapping[str, str] | None = None,
    *,
    execute_postgres: bool = False,
    execute_live: bool = False,
    report_path: Path = DEFAULT_REPORT,
    postgres_report_path: Path = DEFAULT_POSTGRES_REPORT,
    live_report_path: Path = DEFAULT_LIVE_REPORT,
    command_runner: CommandRunner = subprocess.run,
    root: Path = ROOT,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    source = _source_admission(root)
    if execute_live and not execute_postgres:
        raise W80Ca00e6AcceptanceError(
            "live acceptance requires the actual PostgreSQL gate"
        )
    if execute_live and env.get(LIVE_CONFIRMATION_ENV) != "1":
        raise W80Ca00e6AcceptanceError(
            f"{LIVE_CONFIRMATION_ENV}=1 is required after explicit DGX confirmation"
        )

    matrix = _run_command(
        [sys.executable, "-m", "pytest", "-q", *MATRIX_SELECTORS],
        command_runner=command_runner,
        env=env,
        root=root,
        label="prompt/work-class matrix",
    )
    postgres: dict[str, Any] | None = None
    live: dict[str, Any] | None = None
    diagnostics: dict[str, Any] | None = None

    if execute_postgres:
        identities = _database_identities(env)
        _run_command(
            [
                sys.executable,
                str(POSTGRES_SCRIPT),
                "--report",
                str(postgres_report_path),
            ],
            command_runner=command_runner,
            env=env,
            root=root,
            label="AE/WC/OA/EOS PostgreSQL gate",
        )
        postgres = _load_pass_report(postgres_report_path, "PostgreSQL gate")
        postgres = {
            "status": "PASS",
            "actual_postgresql": bool(postgres.get("actual_postgresql")),
            "database_identities": identities,
            "protected_test_selector_count": postgres.get(
                "protected_test_selector_count"
            ),
            "zero_residue": bool(postgres.get("zero_residue")),
        }

    if execute_live:
        live_env = {**env, "NEX_MYBEE_M1_PRODUCT_GOLDEN_LIVE": "1"}
        _run_command(
            [
                sys.executable,
                str(LIVE_SCRIPT),
                "--execute",
                "--summary",
                "--report",
                str(live_report_path),
            ],
            command_runner=command_runner,
            env=live_env,
            root=root,
            label="installed live journey",
        )
        live_report = _load_pass_report(live_report_path, "installed live journey")
        diagnostics = analyze_live_diagnostics(root, live_report)
        _require_live_acceptance(live_report, diagnostics)
        live = {
            "status": "PASS",
            "actual_postgres": bool(live_report.get("actual_postgres")),
            "actual_remote_generation": bool(
                live_report.get("actual_remote_generation")
            ),
            "actual_playwright": bool(live_report.get("actual_playwright")),
            "zero_residue": bool(live_report.get("zero_residue")),
            "release_set_digest": live_report.get("release_set_digest"),
            "diagnostic_session_id": (
                live_report.get("finalization_evidence") or {}
            ).get("session_id"),
        }

    status = "PASS" if execute_live else "PARTIAL_PASS"
    result = {
        "schema_version": SCHEMA_VERSION,
        "slice": "W80-CA00E.6",
        "status": status,
        "source_admission": source,
        "acceptance_matrix": {
            key: list(values) for key, values in ACCEPTANCE_MATRIX.items()
        },
        "matrix": matrix,
        "postgres": postgres,
        "live": live,
        "diagnostics": diagnostics,
        "live_confirmation_required": True,
        "raw_prompt_included": False,
        "secret_included": False,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result


def analyze_live_diagnostics(
    root: Path, live_report: Mapping[str, Any]
) -> dict[str, Any]:
    finalization = live_report.get("finalization_evidence")
    if not isinstance(finalization, Mapping):
        raise W80Ca00e6AcceptanceError("live diagnostic evidence is missing")
    relative = str(finalization.get("relative_path") or "").strip()
    evidence_root = (root / relative).resolve()
    try:
        evidence_root.relative_to(root.resolve())
    except ValueError as exc:
        raise W80Ca00e6AcceptanceError(
            "live diagnostic evidence escaped repository root"
        ) from exc

    semantic_path = evidence_root / "nex-ae-api--semantic-candidate-admission--1.jsonl"
    mo_path = evidence_root / "nex-mo--http-api--1.jsonl"
    if not semantic_path.is_file() or not mo_path.is_file():
        raise W80Ca00e6AcceptanceError("live diagnostic event files are missing")

    event_counts: Counter[str] = Counter()
    stage_counts: Counter[str] = Counter()
    for event in _read_json_lines(semantic_path):
        event_type = str(event.get("event_type") or "")
        event_counts[event_type] += 1
        payload = event.get("payload")
        if event_type == "semantic.candidate.admitted" and isinstance(
            payload, Mapping
        ):
            stage_counts[str(payload.get("semantic_stage") or "")] += 1

    path_counts: Counter[str] = Counter()
    generation_durations: list[float] = []
    for event in _read_json_lines(mo_path):
        payload = event.get("payload")
        if not isinstance(payload, Mapping):
            continue
        path = str(payload.get("path") or "")
        path_counts[path] += 1
        if path == "/api/v1/generations":
            duration = payload.get("duration_ms")
            if isinstance(duration, (int, float)):
                generation_durations.append(float(duration))

    return {
        "semantic_request_count": event_counts["semantic.admission.requested"],
        "semantic_candidate_count": event_counts["semantic.candidate.admitted"],
        "semantic_stage_counts": dict(sorted(stage_counts.items())),
        "generation_request_count": path_counts["/api/v1/generations"],
        "embedding_request_count": path_counts["/api/v1/embeddings"],
        "reranking_request_count": (
            path_counts["/api/v1/rerank"] + path_counts["/api/v1/reranking"]
        ),
        "generation_latency_ms": _latency_summary(generation_durations),
        "previous_generation_request_count": PREVIOUS_GENERATION_REQUEST_COUNT,
        "target_generation_request_count": TARGET_GENERATION_REQUEST_COUNT,
        "provider_request_reduction": (
            PREVIOUS_GENERATION_REQUEST_COUNT
            - path_counts["/api/v1/generations"]
        ),
        "performance_is_correctness_criterion": False,
        "raw_content_included": False,
    }


def _require_live_acceptance(
    live_report: Mapping[str, Any], diagnostics: Mapping[str, Any]
) -> None:
    required = (
        "actual_postgres",
        "actual_remote_generation",
        "actual_playwright",
        "zero_residue",
    )
    if not all(live_report.get(name) is True for name in required):
        raise W80Ca00e6AcceptanceError(
            "installed live journey omitted a protected acceptance boundary"
        )
    if diagnostics.get("semantic_stage_counts") != EXPECTED_SEMANTIC_STAGE_COUNTS:
        raise W80Ca00e6AcceptanceError(
            "installed semantic-stage counts do not prove role-scoped reuse"
        )
    if diagnostics.get("generation_request_count") != TARGET_GENERATION_REQUEST_COUNT:
        raise W80Ca00e6AcceptanceError(
            "installed provider-call count does not prove IA-to-target reuse"
        )
    if diagnostics.get("embedding_request_count") or diagnostics.get(
        "reranking_request_count"
    ):
        raise W80Ca00e6AcceptanceError(
            "generation-only journey contacted an unrelated provider capability"
        )


def _source_admission(root: Path) -> dict[str, Any]:
    required = (
        *MATRIX_SELECTORS,
        str(POSTGRES_SCRIPT.relative_to(ROOT)),
        str(LIVE_SCRIPT.relative_to(ROOT)),
    )
    missing = [relative for relative in required if not (root / relative).is_file()]
    if missing:
        raise W80Ca00e6AcceptanceError(
            "acceptance source is missing: " + ", ".join(missing)
        )
    return {
        "status": "PASS",
        "selector_count": len(MATRIX_SELECTORS),
        "acceptance_dimension_count": len(ACCEPTANCE_MATRIX),
        "postgres_runner_reused": True,
        "installed_live_runner_reused": True,
        "scenario_specific_product_runtime_added": False,
    }


def _run_command(
    command: Sequence[str],
    *,
    command_runner: CommandRunner,
    env: Mapping[str, str],
    root: Path,
    label: str,
) -> dict[str, Any]:
    completed = command_runner(
        list(command), cwd=root, env=dict(env), check=False
    )
    if completed.returncode != 0:
        raise W80Ca00e6AcceptanceError(
            f"{label} failed with exit code {completed.returncode}"
        )
    return {"status": "PASS", "selector_count": len(MATRIX_SELECTORS)}


def _database_identities(environ: Mapping[str, str]) -> dict[str, dict[str, str]]:
    identities: dict[str, dict[str, str]] = {}
    for name, (expected_user, expected_database) in DATABASE_IDENTITIES.items():
        value = str(environ.get(name) or "").strip()
        if not value:
            raise W80Ca00e6AcceptanceError(f"{name} is required")
        try:
            target = make_url(value)
        except Exception as exc:
            raise W80Ca00e6AcceptanceError(f"{name} is invalid") from exc
        if target.username != expected_user or target.database != expected_database:
            raise W80Ca00e6AcceptanceError(
                f"{name} must target {expected_user}@{expected_database}"
            )
        identities[name] = {"user": expected_user, "database": expected_database}
    return identities


def _load_pass_report(path: Path, label: str) -> dict[str, Any]:
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise W80Ca00e6AcceptanceError(f"{label} report is unavailable") from exc
    if not isinstance(report, dict) or report.get("status") != "PASS":
        raise W80Ca00e6AcceptanceError(f"{label} did not pass")
    return report


def _read_json_lines(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise W80Ca00e6AcceptanceError(
                f"diagnostic event is malformed: {path.name}"
            ) from exc
        if isinstance(event, dict):
            events.append(event)
    return events


def _latency_summary(values: Sequence[float]) -> dict[str, float | int]:
    if not values:
        return {"count": 0, "mean": 0.0, "p95": 0.0, "maximum": 0.0}
    ordered = sorted(values)
    p95_index = min(len(ordered) - 1, max(0, math.ceil(len(ordered) * 0.95) - 1))
    return {
        "count": len(ordered),
        "mean": round(mean(ordered), 3),
        "p95": round(ordered[p95_index], 3),
        "maximum": round(ordered[-1], 3),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the W80-CA00E.6 protected semantic handoff acceptance."
    )
    parser.add_argument("--execute-postgres", action="store_true")
    parser.add_argument("--execute-live", action="store_true")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--postgres-report", type=Path, default=DEFAULT_POSTGRES_REPORT)
    parser.add_argument("--live-report", type=Path, default=DEFAULT_LIVE_REPORT)
    args = parser.parse_args(argv)
    try:
        result = run_acceptance(
            execute_postgres=args.execute_postgres,
            execute_live=args.execute_live,
            report_path=args.report,
            postgres_report_path=args.postgres_report,
            live_report_path=args.live_report,
        )
    except W80Ca00e6AcceptanceError as exc:
        print(f"mybee_w80_ca00e6=fail detail={exc}", file=sys.stderr)
        return 1
    print(
        "mybee_w80_ca00e6="
        f"{str(result['status']).lower()} "
        f"postgres={str(result['postgres'] is not None).lower()} "
        f"live={str(result['live'] is not None).lower()} "
        f"report={args.report}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
