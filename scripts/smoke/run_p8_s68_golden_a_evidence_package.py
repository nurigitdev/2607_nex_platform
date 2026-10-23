#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "_shared",
    ROOT / "services" / "nex-ae-api",
    ROOT / "services" / "nex-eos",
    ROOT / "services" / "nex-oa",
    ROOT / "scripts" / "db",
    ROOT / "scripts" / "smoke",
):
    sys.path.insert(0, str(path))

import run_p8_s67_golden_a_exactly_once as p8_s67
from nex_runtime.golden_a_evidence import build_golden_a_evidence_package
from nex_runtime.release_candidate_closure import load_full_regression_evidence
from nex_runtime.semantic_hashes import hash_ref_from_sha256, semantic_sha256_hash_ref

SMOKE_ENV = "NEX_P8_S68_GOLDEN_A_EVIDENCE_LIVE"
DEFAULT_JUNIT = ROOT / "reports/coverage/junit.xml"
DEFAULT_COVERAGE = ROOT / "reports/coverage/coverage.json"
DEFAULT_REPORT = ROOT / "reports/quality/p8-s68-golden-a-evidence.json"


def run_p8_s68_golden_a_evidence_package(
    environ: Mapping[str, str] | None = None,
    *,
    execute: bool,
    junit_path: Path = DEFAULT_JUNIT,
    coverage_path: Path = DEFAULT_COVERAGE,
    root: Path = ROOT,
    source: Path = p8_s67.p8_s65.DEFAULT_SOURCE,
    lock_path: Path = p8_s67.p8_s65.DEFAULT_LOCK,
    wheel_directory: Path = p8_s67.p8_s65.DEFAULT_WHEEL_DIRECTORY,
    python_bin: str = sys.executable,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if not execute or env.get(SMOKE_ENV) != "1":
        return {
            "schema_version": "p8_golden_a_evidence_package.v1",
            "slice": "P8-S68",
            "status": "SKIPPED",
            "skip_reason": f"--execute and {SMOKE_ENV}=1 are required",
        }
    database_urls = {
        key: env.get(key, "") for key in p8_s67.EXPECTED_DATABASES
    }
    try:
        s67 = p8_s67.run_p8_s67_golden_a_exactly_once(
            {**env, p8_s67.SMOKE_ENV: "1"},
            execute=True,
            source=source,
            lock_path=lock_path,
            wheel_directory=wheel_directory,
            python_bin=python_bin,
        )
        if s67.get("status") != "PASS":
            raise ValueError("P8-S67 protected Golden A evidence did not pass")
        full_gate = load_full_regression_evidence(
            junit_path,
            coverage_path,
            statement_min=95.0,
            branch_min=94.0,
        )
        if full_gate.get("status") != "PASS":
            raise ValueError("Full Gate evidence did not pass")
        commit, tree = _git_identity(root)
        protected_digest = semantic_sha256_hash_ref(s67)
        full_gate_digest = hash_ref_from_sha256(full_gate["evidence_digest"])
        metrics = dict(full_gate["metrics"])
        release = dict(s67["nsl_release"])
        package = build_golden_a_evidence_package(
            platform={"commit": commit, "tree": tree},
            nsl_release={
                "source_revision": release["source_revision"],
                "source_tree": release["source_tree"],
                "wheel_sha256": release["wheel_sha256"],
                "release_admission_hash": s67["nsl_release_admission_hash"],
            },
            migration_heads=s67["migration_heads"],
            test_evidence={
                "protected_gate_id": "P8-S67",
                "protected_run_id": _run_id("p8-s67", protected_digest),
                "protected_evidence_digest": protected_digest,
                "actual_postgres": s67["actual_postgres"],
                "actual_remote_provider": s67["actual_remote_provider"],
                "full_gate_id": full_gate["gate_id"],
                "full_gate_run_id": _run_id("full-gate", full_gate_digest),
                "full_gate_evidence_digest": full_gate_digest,
                "passed_test_count": metrics["passed_test_count"],
                "failed_test_count": metrics["failed_test_count"],
                "skipped_test_count": metrics["skipped_test_count"],
                "statement_coverage": metrics["statement_coverage"],
                "branch_coverage": metrics["branch_coverage"],
            },
            lineage={
                "business_operation_id": s67["business_operation_id"],
                "nsl_execution_id": s67["nsl_execution_id"],
                "approval_request_id": s67["approval_request_id"],
                "approval_work_item_id": s67["approval_work_item_id"],
                "voucher_ref": s67["voucher_ref"],
            },
            outcome={
                "commit_state": s67["commit_state"],
                "verification_status": s67["verification_status"],
                "business_mutation_count": s67["decision"][
                    "business_mutation_count"
                ],
                "residue_count": s67["residue_count"],
            },
        )
        p8_s67.p8_s65._assert_redacted(package, env)
        return package
    except Exception as exc:  # noqa: BLE001 - protected gate emits safe failure.
        detail = p8_s67.p8_s65._redact(str(exc), *database_urls.values())
        result = {
            "schema_version": "p8_golden_a_evidence_package.v1",
            "slice": "P8-S68",
            "status": "FAIL",
            "failure_code": type(exc).__name__,
            "detail": detail,
        }
        p8_s67.p8_s65._assert_redacted(result, env)
        return result


def _git_identity(root: Path) -> tuple[str, str]:
    values = []
    for revision in ("HEAD", "HEAD^{tree}"):
        completed = subprocess.run(
            ("git", "rev-parse", revision),
            cwd=root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=10,
        )
        if completed.returncode != 0:
            raise ValueError("Platform Git identity is unavailable")
        values.append(completed.stdout.strip())
    return values[0], values[1]


def _run_id(prefix: str, digest: str) -> str:
    return f"{prefix}:{digest.removeprefix('sha256:')[:16]}"


def summary_line(evidence: Mapping[str, Any]) -> str:
    if evidence.get("status") == "SKIPPED":
        return "p8_s68_golden_a_evidence=skipped"
    if evidence.get("status") != "PASS":
        return "p8_s68_golden_a_evidence=fail"
    tests = dict(evidence.get("test_evidence") or {})
    outcome = dict(evidence.get("outcome") or {})
    return (
        "p8_s68_golden_a_evidence=pass "
        f"tests={tests.get('passed_test_count', 0)} "
        f"statement={tests.get('statement_coverage', 0)} "
        f"branch={tests.get('branch_coverage', 0)} "
        f"mutations={outcome.get('business_mutation_count', '-')} "
        f"residue={outcome.get('residue_count', '-')}"
    )


def write_report(path: Path, evidence: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the protected metadata-only P8-S68 Golden A evidence package."
    )
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--junit", type=Path, default=DEFAULT_JUNIT)
    parser.add_argument("--coverage", type=Path, default=DEFAULT_COVERAGE)
    parser.add_argument("--source", type=Path, default=p8_s67.p8_s65.DEFAULT_SOURCE)
    parser.add_argument("--lock", type=Path, default=p8_s67.p8_s65.DEFAULT_LOCK)
    parser.add_argument(
        "--wheel-directory",
        type=Path,
        default=p8_s67.p8_s65.DEFAULT_WHEEL_DIRECTORY,
    )
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    evidence = run_p8_s68_golden_a_evidence_package(
        execute=args.execute,
        junit_path=args.junit,
        coverage_path=args.coverage,
        source=args.source,
        lock_path=args.lock,
        wheel_directory=args.wheel_directory,
        python_bin=args.python,
    )
    if evidence["status"] == "PASS":
        write_report(args.report, evidence)
    print(summary_line(evidence) if args.summary else json.dumps(evidence, indent=2))
    return 0 if evidence["status"] in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
