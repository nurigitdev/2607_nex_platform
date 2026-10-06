#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
for path in (
    ROOT / "services" / "_shared",
    ROOT / "scripts" / "quality",
    ROOT / "scripts" / "smoke",
):
    sys.path.insert(0, str(path))

from nex_runtime.release_candidate_assurance import (  # noqa: E402
    DEPLOYMENT_DEFERRALS,
    RELEASE_CANDIDATE_ASSURANCE_SCHEMA_VERSION,
    build_release_candidate_assurance_evidence,
)
from run_platform_ag_trace_postgres_smoke import (  # noqa: E402
    SMOKE_ENV as AG_SMOKE_ENV,
    run_platform_ag_trace_postgres_smoke,
)
from run_platform_generation_golden_scenarios import (  # noqa: E402
    run_platform_generation_golden_scenarios,
)
from run_platform_local_mock_process_smoke import (  # noqa: E402
    run_platform_local_mock_process_smoke,
)
from validate_contracts import validate_contract_tree  # noqa: E402


ENABLE_ENV = "NEX_S140_RELEASE_CANDIDATE_ASSURANCE"
SourceRunner = Callable[..., Mapping[str, Any]]


def run_platform_release_candidate_assurance(
    environ: Mapping[str, str] | None = None,
    *,
    contract_runner: SourceRunner = validate_contract_tree,
    golden_runner: SourceRunner = run_platform_generation_golden_scenarios,
    database_runner: SourceRunner = run_platform_ag_trace_postgres_smoke,
    process_runner: SourceRunner = run_platform_local_mock_process_smoke,
    file_runner: SourceRunner | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    if env.get(ENABLE_ENV) != "1":
        return {
            "schema_version": RELEASE_CANDIDATE_ASSURANCE_SCHEMA_VERSION,
            "status": "SKIPPED",
            "skip_reason": f"{ENABLE_ENV} is not enabled.",
            "actual_protected_execution": False,
            "next_slice": "1399",
        }

    try:
        contract_source = _contract_projection(contract_runner(ROOT / "contracts"))
        golden_source = dict(golden_runner())
        database_source = dict(database_runner({**env, AG_SMOKE_ENV: "1"}))
        process_source = dict(process_runner())
        file_source = dict((file_runner or _run_file_cleanup_probe)())
        residue_source = _residue_projection(
            database_source,
            process_source,
            file_source,
        )
        evidence = build_release_candidate_assurance_evidence(
            contract_source,
            golden_source,
            residue_source,
        )
    except Exception:
        contract_source = locals().get("contract_source", {})
        golden_source = locals().get("golden_source", {})
        residue_source = {}
        evidence = build_release_candidate_assurance_evidence(
            contract_source,
            golden_source,
            residue_source,
        )
        evidence["failure_code"] = "release_candidate_assurance_execution_failed"

    evidence.update(
        actual_protected_execution=residue_source.get("actual_execution") is True,
        source_projection={
            "contract_status": "PASS" if contract_source.get("ok") is True else "FAIL",
            "golden_status": golden_source.get("status", "NOT_RUN"),
            "database_status": database_source.get("status", "NOT_RUN")
            if "database_source" in locals()
            else "NOT_RUN",
            "process_status": process_source.get("status", "NOT_RUN")
            if "process_source" in locals()
            else "NOT_RUN",
            "file_status": file_source.get("status", "NOT_RUN")
            if "file_source" in locals()
            else "NOT_RUN",
        },
        next_slice="1400" if evidence["status"] == "PASS" else "blocked",
    )
    return evidence


def _contract_projection(source: object) -> dict[str, Any]:
    if isinstance(source, Mapping):
        return dict(source)
    return {
        "ok": getattr(source, "ok", False) is True,
        "schema_count": getattr(source, "schema_count", 0),
        "example_count": getattr(source, "example_count", 0),
        "negative_example_count": getattr(source, "negative_example_count", 0),
        "openapi_count": getattr(source, "openapi_count", 0),
        "failures": list(getattr(source, "failures", ())),
    }


def _residue_projection(
    database: Mapping[str, Any],
    process: Mapping[str, Any],
    file_probe: Mapping[str, Any],
) -> dict[str, Any]:
    database_summary = dict(database.get("summary") or {})
    stopped_counts = dict(process.get("stopped_process_counts") or {})
    return {
        "actual_execution": (
            database.get("actual_postgresql") is True
            and process.get("status") == "PASS"
            and file_probe.get("status") == "PASS"
        ),
        "database_count": database_summary.get("service_count", 0),
        "database_residue_count": database_summary.get(
            "cleanup_residue_count", -1
        ),
        "file_cleanup_probe": file_probe.get("cleanup_confirmed") is True,
        "file_residue_count": file_probe.get("residue_count", -1),
        "stopped_process_count": stopped_counts.get("STOPPED", 0),
        "running_process_count": sum(
            value
            for state, value in stopped_counts.items()
            if state != "STOPPED" and isinstance(value, int)
        ),
        "deployment_deferrals": list(DEPLOYMENT_DEFERRALS),
        "production_deployment_approved": False,
        "release_scope": "MVP_RELEASE_CANDIDATE",
    }


def _run_file_cleanup_probe() -> dict[str, Any]:
    path: Path
    with TemporaryDirectory(prefix="nex-s140-residue-") as directory:
        path = Path(directory)
        probe = path / "owned" / "probe.bin"
        probe.parent.mkdir(parents=True)
        probe.write_bytes(b"s140-owned-cleanup-probe")
        created = probe.is_file()
    cleanup_confirmed = created and not path.exists()
    return {
        "status": "PASS" if cleanup_confirmed else "FAIL",
        "cleanup_confirmed": cleanup_confirmed,
        "residue_count": 0 if cleanup_confirmed else 1,
    }


def summary_line(result: Mapping[str, Any]) -> str:
    status = str(result.get("status") or "FAIL")
    if status == "SKIPPED":
        return "platform_release_candidate_assurance=skip next=1399"
    gates = {
        item.get("gate_id"): item
        for item in result.get("gate_evidence", [])
        if isinstance(item, Mapping)
    }
    contract = dict(gates.get("contract_privacy", {}).get("metrics") or {})
    residue = dict(gates.get("zero_residue", {}).get("metrics") or {})
    deferrals = dict(gates.get("deployment_deferrals", {}).get("metrics") or {})
    return (
        "platform_release_candidate_assurance="
        f"{status.lower()} contracts={contract.get('schema_count', 0)} "
        f"recovery={contract.get('recovery_scenario_count', 0)} "
        f"residue={residue.get('database_residue_count', 0) + residue.get('file_residue_count', 0) + residue.get('running_process_count', 0)} "
        f"deferrals={deferrals.get('deferral_count', 0)} "
        f"next={result.get('next_slice', 'blocked')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_platform_release_candidate_assurance()
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 1 if result["status"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
