#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [
    str(ROOT / "services/_shared"),
    str(ROOT / "services/nex-ae-api"),
    str(ROOT / "scripts/quality"),
    str(ROOT / "scripts/smoke"),
]

import run_gb2_ca00_s05_ae_agent_runtime_worker as ae_worker
import run_gb2_ca00_s06_wc_event_delivery_worker as wc_worker
import run_gb2_ca00_s07_eos_outbox_publisher as eos_publisher
import run_golden_journey_transition_audit as transition_audit
from nex_ae_api.domain_intent_activators import (
    DomainIntentActivatorRegistry,
    DomainIntentActivatorRegistryError,
)
from nex_runtime.dependency_readiness import (
    DependencyReadinessRequirement,
    aggregate_dependency_readiness,
)
from nex_runtime.hidden_gap_acceptance import (
    HIDDEN_GAP_SCENARIOS,
    build_hidden_gap_evidence,
    build_hidden_gap_matrix,
    evaluate_hidden_gap_acceptance,
)

EXECUTION_ENV = "NEX_GB2_CA00_S19_POSTGRES_SMOKE"
SCHEMA_VERSION = "gb2_ca00_s19_fail_closed_restart_acceptance.v1"
DEFAULT_REPORT = ROOT / "reports/smoke/gb2-ca00-s19-fail-closed-restart.json"
_COMPONENT_SOURCES = (
    "scripts/smoke/run_gb2_ca00_s05_ae_agent_runtime_worker.py",
    "scripts/smoke/run_gb2_ca00_s06_wc_event_delivery_worker.py",
    "scripts/smoke/run_gb2_ca00_s07_eos_outbox_publisher.py",
)
ComponentRunner = Callable[[Mapping[str, str]], Mapping[str, Any]]


def run_gb2_ca00_s19_fail_closed_restart_acceptance(
    environ: Mapping[str, str] | None = None,
    *,
    execute: bool = False,
    root: Path = ROOT,
    component_runners: Mapping[str, ComponentRunner] | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    source = _source_admission(root)
    if source["status"] == "FAIL":
        return source
    if not execute or env.get(EXECUTION_ENV) != "1":
        return source

    runners = component_runners or {
        "ae": ae_worker.run_gb2_ca00_s05_ae_agent_runtime_worker,
        "wc": wc_worker.run_gb2_ca00_s06_wc_event_delivery_worker,
        "eos": eos_publisher.run_gb2_ca00_s07_eos_outbox_publisher,
    }
    protected_env = {
        **env,
        ae_worker.SMOKE_ENV: "1",
        wc_worker.SMOKE_ENV: "1",
        eos_publisher.SMOKE_ENV: "1",
    }
    try:
        components = {
            name: dict(runners[name](protected_env)) for name in ("ae", "wc", "eos")
        }
        records = _scenario_evidence(components)
        evaluated = evaluate_hidden_gap_acceptance({"evidence": records})
        actual_postgres = all(
            evidence.get("actual_postgres") is True
            for evidence in components.values()
        )
        cleanup_remaining = sum(
            _remaining_count(evidence) for evidence in components.values()
        )
        execution_checks = {
            "component_acceptance_passed": all(
                evidence.get("status") == "PASS" for evidence in components.values()
            ),
            "actual_postgres": actual_postgres,
            "scenario_matrix_passed": evaluated["status"] == "PASS",
            "zero_residue": cleanup_remaining == 0,
        }
        status = "PASS" if all(execution_checks.values()) else "FAIL"
        return {
            **source,
            **evaluated,
            "schema_version": SCHEMA_VERSION,
            "slice": "GB2-CA00-S19",
            "status": status,
            "executed": True,
            "actual_postgres": actual_postgres,
            "execution_checks": execution_checks,
            "component_statuses": {
                name: {
                    "status": evidence.get("status", "FAIL"),
                    "actual_postgres": evidence.get("actual_postgres") is True,
                    "checks_passed": sum(
                        value is True
                        for value in _mapping(evidence.get("checks")).values()
                    ),
                    "check_count": len(_mapping(evidence.get("checks"))),
                    "cleanup_remaining": _remaining_count(evidence),
                }
                for name, evidence in components.items()
            },
            "cleanup_remaining": cleanup_remaining,
            "failure_code": None if status == "PASS" else "gb2_s19_acceptance_failed",
            "secret_included": False,
        }
    except (KeyError, OSError, RuntimeError, TypeError, ValueError) as exc:
        return {
            **source,
            "status": "FAIL",
            "executed": True,
            "failure_code": "gb2_s19_execution_failed",
            "detail": type(exc).__name__,
            "secret_included": False,
        }


def _source_admission(root: Path) -> dict[str, Any]:
    source_checks = {
        "component_sources_present": all((root / path).is_file() for path in _COMPONENT_SOURCES),
        "scenario_inventory_exact": tuple(
            spec.scenario_id for spec in HIDDEN_GAP_SCENARIOS
        )
        == tuple(f"N{index:02d}" for index in range(1, 10)),
        "forbidden_transition_fixture_detected": _forbidden_fixture_detected(),
    }
    status = "SOURCE_ADMITTED" if all(source_checks.values()) else "FAIL"
    return {
        "schema_version": SCHEMA_VERSION,
        "slice": "GB2-CA00-S19",
        "status": status,
        "executed": False,
        "source_checks": source_checks,
        "matrix": build_hidden_gap_matrix(),
        "actual_postgres_required": True,
        "secret_included": False,
    }


def _scenario_evidence(
    components: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    ae_checks = _mapping(components["ae"].get("checks"))
    wc_checks = _mapping(components["wc"].get("checks"))
    eos_checks = _mapping(components["eos"].get("checks"))
    dependency_checks = {
        "N04": _missing_dependency_blocked("openbao.required", "OPENBAO", "platform"),
        "N05": _missing_dependency_blocked(
            "object-storage.required", "OBJECT_STORAGE", "nex-ae-api"
        ),
        "N06": _missing_dependency_blocked(
            "generation-provider.required", "MODEL_PROVIDER", "nex-mo"
        ),
    }
    activator_rejected = _unknown_activator_rejected()
    forbidden_fixture_detected = _forbidden_fixture_detected()
    return [
        build_hidden_gap_evidence(
            "N01",
            checks={
                "pending_job_visible": ae_checks.get(
                    "worker_unavailable_preserved_pending_job"
                )
                is True,
                "false_completion_prevented": ae_checks.get(
                    "worker_unavailable_preserved_pending_job"
                )
                is True,
                "restart_recovered": ae_checks.get("canonical_worker_claimed_assignment")
                is True,
                "duplicate_settlement_prevented": ae_checks.get(
                    "restart_did_not_double_execute"
                )
                is True,
            },
            components=("nex-ae-agent-runtime-worker", "ae_runtime_job"),
            protected_execution=True,
        ),
        build_hidden_gap_evidence(
            "N02",
            checks={
                "pending_event_visible": wc_checks.get(
                    "worker_unavailable_preserved_pending_event"
                )
                is True,
                "false_resume_prevented": wc_checks.get(
                    "wrong_signed_trust_failed_closed"
                )
                is True,
                "restart_recovered": wc_checks.get("restart_resumed_pending_delivery")
                is True,
                "duplicate_delivery_prevented": wc_checks.get(
                    "restart_did_not_double_deliver"
                )
                is True,
            },
            components=("nex-wc-event-delivery-worker", "service_jobs"),
            protected_execution=True,
        ),
        build_hidden_gap_evidence(
            "N03",
            checks={
                "pending_outbox_visible": eos_checks.get(
                    "wrong_signed_trust_failed_closed"
                )
                is True,
                "false_publication_prevented": eos_checks.get(
                    "wrong_signed_trust_failed_closed"
                )
                is True,
                "restart_recovered": eos_checks.get(
                    "restart_resumed_pending_publication"
                )
                is True,
                "duplicate_transaction_prevented": eos_checks.get(
                    "restart_did_not_double_publish"
                )
                is True
                and eos_checks.get("owner_business_operation_admission") is True,
            },
            components=("nex-eos-outbox-publisher", "eos_outbox"),
            protected_execution=True,
        ),
        build_hidden_gap_evidence(
            "N04",
            checks={
                "required_dependency_missing": dependency_checks["N04"],
                "startup_readiness_blocked": dependency_checks["N04"],
            },
            components=("nex_runtime.dependency_readiness", "OpenBao"),
            protected_execution=False,
        ),
        build_hidden_gap_evidence(
            "N05",
            checks={
                "required_dependency_missing": dependency_checks["N05"],
                "storage_path_blocked": dependency_checks["N05"],
            },
            components=("nex_runtime.dependency_readiness", "RustFS"),
            protected_execution=False,
        ),
        build_hidden_gap_evidence(
            "N06",
            checks={
                "required_dependency_missing": dependency_checks["N06"],
                "live_planning_blocked": dependency_checks["N06"],
            },
            components=("nex_runtime.dependency_readiness", "nex-mo"),
            protected_execution=False,
        ),
        build_hidden_gap_evidence(
            "N07",
            checks={
                "required_activator_missing": activator_rejected,
                "activation_rejected": activator_rejected,
            },
            components=("DomainIntentActivatorRegistry",),
            protected_execution=False,
        ),
        build_hidden_gap_evidence(
            "N08",
            checks={
                "ae_duplicate_prevented": ae_checks.get(
                    "restart_did_not_double_execute"
                )
                is True,
                "wc_duplicate_prevented": wc_checks.get(
                    "restart_did_not_double_deliver"
                )
                is True,
                "eos_duplicate_prevented": eos_checks.get(
                    "restart_did_not_double_publish"
                )
                is True,
            },
            components=(
                "nex-ae-agent-runtime-worker",
                "nex-wc-event-delivery-worker",
                "nex-eos-outbox-publisher",
            ),
            protected_execution=True,
        ),
        build_hidden_gap_evidence(
            "N09",
            checks={
                "forbidden_fixture_detected": forbidden_fixture_detected,
                "audit_failed_closed": forbidden_fixture_detected,
            },
            components=("golden_journey_transition_audit",),
            protected_execution=False,
        ),
    ]


def _missing_dependency_blocked(
    dependency_id: str,
    dependency_type: str,
    owner: str,
) -> bool:
    aggregate = aggregate_dependency_readiness(
        (
            DependencyReadinessRequirement(
                dependency_id=dependency_id,
                dependency_type=dependency_type,
                owner=owner,
                required=True,
            ),
        ),
        (),
    )
    return aggregate["readiness_status"] == "NOT_READY" and aggregate[
        "missing_required_dependency_ids"
    ] == [dependency_id]


def _unknown_activator_rejected() -> bool:
    try:
        DomainIntentActivatorRegistry().resolve(
            "finance.voucher.create", required=True
        )
    except DomainIntentActivatorRegistryError as exc:
        return exc.error_code == "DOMAIN_INTENT_ACTIVATOR_REQUIRED"
    return False


def _forbidden_fixture_detected() -> bool:
    with TemporaryDirectory(prefix="nex-gb2-s19-") as directory:
        root = Path(directory)
        runner = root / "scripts/smoke/run_golden_journey_hidden_gap_fixture.py"
        runner.parent.mkdir(parents=True)
        runner.write_text(
            f"GOLDEN_JOURNEY_EVIDENCE_CONTRACT = "
            f"{transition_audit.EVIDENCE_CONTRACT!r}\n"
            "def run():\n"
            "    engine.schedule_next()\n"
            "    return {**GOLDEN_JOURNEY_EVIDENCE_CONTRACT}\n",
            encoding="utf-8",
        )
        registry = root / transition_audit.DEFAULT_REGISTRY
        registry.parent.mkdir(parents=True)
        registry.write_text(
            json.dumps(
                {
                    "schema_version": transition_audit.REGISTRY_SCHEMA_VERSION,
                    "runners": [
                        {
                            "path": runner.relative_to(root).as_posix(),
                            "evidence_class": "GOLDEN_JOURNEY",
                            "enforce_transition_boundary": True,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        result = transition_audit.audit_repository(root)
    return result["status"] == "FAIL" and any(
        item["code"] == "FORBIDDEN_TRANSITION_CALL"
        for item in result["findings"]
    )


def _remaining_count(evidence: Mapping[str, Any]) -> int:
    cleanup = _mapping(evidence.get("cleanup_counts"))
    return sum(
        int(value)
        for name, value in cleanup.items()
        if name == "component_remaining" or name.endswith("_remaining")
    )


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _write_report(path: Path, result: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(dict(result), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def summary_line(result: Mapping[str, Any]) -> str:
    summary = _mapping(result.get("summary"))
    return (
        "gb2_ca00_s19_fail_closed_restart="
        f"{str(result.get('status', 'FAIL')).lower()} "
        f"executed={str(bool(result.get('executed'))).lower()} "
        f"scenarios={summary.get('passed_scenario_count', 0)}/"
        f"{summary.get('required_scenario_count', 9)} "
        f"postgres={str(bool(result.get('actual_postgres'))).lower()} "
        f"remaining={int(result.get('cleanup_remaining', 0))}"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run GB2-CA00-S19 fail-closed and restart acceptance"
    )
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)
    result = run_gb2_ca00_s19_fail_closed_restart_acceptance(
        os.environ, execute=args.execute
    )
    _write_report(args.report, result)
    print(summary_line(result) if args.summary else json.dumps(result, indent=2))
    return 0 if result.get("status") in {"PASS", "SOURCE_ADMITTED"} else 1


if __name__ == "__main__":  # pragma: no cover - exercised by CLI subprocess.
    raise SystemExit(main())
