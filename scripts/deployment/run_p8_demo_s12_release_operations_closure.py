#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "_shared"))

from nex_runtime.production_release import canonical_digest
from nex_runtime.release_candidate_closure import (
    load_full_regression_evidence,
)

ACTIVATION_ENV = "NEX_P8_DEMO_S12_RELEASE_CLOSURE"
DEFAULT_JUNIT = ROOT / "reports/coverage/junit.xml"
DEFAULT_COVERAGE = ROOT / "reports/coverage/coverage.json"
DEFAULT_OUTPUT = ROOT / "reports/deployment/p8-demo-s12-release-closure.json"
RUNBOOK_PATH = ROOT / "docs/runbooks/p8_chairman_demo_release.md"
QUALITY_GATE_PATH = ROOT / "scripts/quality/run_quality_gate.sh"
RUNNER_NAME = "run_p8_demo_s12_release_operations_closure.py"
EXPECTED_ARTIFACTS = {
    "nex-oa-runtime",
    "nex-ag-runtime",
    "nex-ae-runtime",
    "nex-cx-runtime",
    "nex-mo-runtime",
    "nex-wc-runtime",
    "nex-eos-runtime",
    "nex-ae-web",
}
REPORT_SPECS = {
    "oci": (
        ROOT / "reports/deployment/p8-demo-oci-image-build.json",
        "p8_demo_oci_release.v1",
    ),
    "ae_image": (
        ROOT / "reports/deployment/p8-demo-ae-runtime-image.json",
        "p8_demo_ae_runtime_image.v1",
    ),
    "compose": (
        ROOT / "reports/deployment/p8-demo-compose-render.json",
        "p8_demo_compose.v1",
    ),
    "database": (
        ROOT / "reports/deployment/p8-demo-database-guardrails.json",
        "p8_demo_database_guardrail_evidence.v1",
    ),
    "migrations": (
        ROOT / "reports/deployment/p8-demo-migrations.json",
        "p8_demo_migration_execution.v1",
    ),
    "dependencies": (
        ROOT / "reports/deployment/p8-demo-external-dependencies.json",
        "p8_demo_external_dependencies.v1",
    ),
    "trust": (
        ROOT / "reports/deployment/p8-demo-trust-admission.json",
        "p8_demo_trust_admission.v1",
    ),
    "s10": (
        ROOT / "reports/deployment/p8-demo-s10-installed-domain.json",
        "p8_demo_s10_installed_domain_acceptance.v1",
    ),
    "s10b": (
        ROOT / "reports/deployment/p8-demo-s10b-installed-runtime.json",
        "p8_demo_s10b_installed_runtime.v1",
    ),
    "s10c": (
        ROOT / "reports/deployment/p8-demo-s10c-installed-result-closure.json",
        "p8_demo_s10c_installed_result_closure.v1",
    ),
    "s11": (
        ROOT / "reports/deployment/p8-demo-s11-chairman-golden-journey.json",
        "p8_demo_s11_chairman_golden_journey.v1",
    ),
}
RUNBOOK_TOKENS = (
    "Release Boundary",
    "Prerequisites",
    "Backup And Database Admission",
    "Build And Compose Admission",
    "Trust And External Dependencies",
    "Installed Acceptance",
    "Chairman Golden Journey",
    "Start And Readiness",
    "Stop And Restart",
    "Failure Triage",
    "Cleanup And Zero Residue",
    "Evidence And Release Closure",
)
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_REVISION = re.compile(r"[0-9a-f]{40}\Z")


def run_p8_demo_s12_release_operations_closure(
    environ: Mapping[str, str] | None = None,
    *,
    execute: bool = False,
    report_paths: Mapping[str, Path] | None = None,
    junit_path: Path = DEFAULT_JUNIT,
    coverage_path: Path = DEFAULT_COVERAGE,
    output_path: Path = DEFAULT_OUTPUT,
    root: Path = ROOT,
) -> dict[str, Any]:
    env = os.environ if environ is None else environ
    if not execute or env.get(ACTIVATION_ENV) != "1":
        return {
            "schema_version": "p8_demo_s12_release_closure.v1",
            "slice": "P8-DEMO-S12",
            "status": "SKIPPED",
            "reason": f"--execute and {ACTIVATION_ENV}=1 are required",
        }
    paths = {
        name: path for name, (path, _schema) in REPORT_SPECS.items()
    }
    if report_paths is not None:
        paths.update(report_paths)
    try:
        reports = {name: _load_object(path) for name, path in paths.items()}
        report_mtimes = {name: path.stat().st_mtime for name, path in paths.items()}
        regression = load_full_regression_evidence(
            junit_path,
            coverage_path,
            statement_min=96.0,
            branch_min=94.0,
        )
        result = _evaluate(
            reports,
            regression,
            report_mtimes=report_mtimes,
            junit_mtime=junit_path.stat().st_mtime,
            coverage_mtime=coverage_path.stat().st_mtime,
            root=root,
        )
        _write_json(output_path, result)
        return result
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        TypeError,
        ValueError,
        ET.ParseError,
    ) as exc:
        return _failure(
            "p8_demo_s12_input_failed",
            {"exception_type": exc.__class__.__name__},
        )


def _evaluate(
    reports: Mapping[str, Mapping[str, Any]],
    regression: Mapping[str, Any],
    *,
    report_mtimes: Mapping[str, float],
    junit_mtime: float,
    coverage_mtime: float,
    root: Path,
) -> dict[str, Any]:
    oci = _mapping(reports.get("oci"))
    image_build = _mapping(oci.get("image_build"))
    release_manifest = _mapping(oci.get("release_manifest"))
    image_summary = _mapping(oci.get("summary"))
    artifacts = _records(image_build.get("artifacts"))
    artifact_ids = {str(item.get("artifact_id") or "") for item in artifacts}
    source_revision = str(oci.get("source_revision") or "")
    release_set_digest = str(release_manifest.get("release_set_digest") or "")

    ae_image = _mapping(reports.get("ae_image"))
    ae_image_detail = _mapping(ae_image.get("image"))
    ae_bundle = _mapping(ae_image.get("bundle"))
    ae_runtime_image_id = str(ae_image_detail.get("image_id") or "")
    compose = _mapping(reports.get("compose"))
    compose_render = _mapping(compose.get("render"))
    database = _mapping(reports.get("database"))
    database_admission = _mapping(database.get("admission"))
    database_redaction = _mapping(database.get("redaction"))
    migrations = _mapping(reports.get("migrations"))
    dependencies = _mapping(reports.get("dependencies"))
    provider = _mapping(dependencies.get("provider"))
    object_storage = _mapping(dependencies.get("object_storage"))
    trust = _mapping(reports.get("trust"))
    trust_inventory = _mapping(trust.get("inventory"))
    trust_pki = _mapping(trust.get("pki"))
    s10 = _mapping(reports.get("s10"))
    s10b = _mapping(reports.get("s10b"))
    s10c = _mapping(reports.get("s10c"))
    s11 = _mapping(reports.get("s11"))
    s11_extended = _mapping(s11.get("extended_acceptance"))
    s11_restart = _mapping(s11.get("post_restart_acceptance"))
    regression_metrics = _mapping(regression.get("metrics"))
    runbook = _read_text(root / RUNBOOK_PATH.relative_to(ROOT))
    quality_gate = _read_text(root / QUALITY_GATE_PATH.relative_to(ROOT))

    schemas_valid = all(
        _mapping(reports.get(name)).get("schema_version") == expected
        for name, (_path, expected) in REPORT_SPECS.items()
    )
    latest_protected_mtime = max(
        report_mtimes.get(name, 0.0)
        for name in ("dependencies", "trust", "s10", "s10b", "s10c", "s11")
    )
    checks = {
        "evidence_schemas_exact": schemas_valid,
        "eight_image_release_set_complete": (
            oci.get("status") == "PASS"
            and image_build.get("status") == "RELEASE_SET_BUILT"
            and release_manifest.get("status") == "RELEASE_SET_READY"
            and image_build.get("source_tree_clean") is True
            and _REVISION.fullmatch(source_revision) is not None
            and _DIGEST.fullmatch(release_set_digest) is not None
            and artifact_ids == EXPECTED_ARTIFACTS
            and len(artifacts) == 8
            and image_summary.get("non_root_image_count") == 8
            and image_summary.get("manifest_digest_count") == 8
            and image_summary.get("background_check_count") == 3
            and _mapping(oci.get("decision")).get("registry_push_performed")
            is False
        ),
        "ae_runtime_bundle_admitted": (
            ae_image.get("status") == "PASS"
            and ae_image.get("registry_push_performed") is False
            and ae_image.get("secret_included") is False
            and ae_image_detail.get("runtime_user") == "65532:65532"
            and _DIGEST.fullmatch(ae_runtime_image_id) is not None
            and ae_bundle.get("status") == "PASS"
            and ae_bundle.get("bundle_id")
            == "p8-demo-nsl-v0.2.1-golden-a-v1"
            and ae_bundle.get("skill_version") == "1.1.0"
        ),
        "compose_render_matches_release": (
            compose.get("status") == "PASS"
            and compose.get("rendered") is True
            and compose.get("image_release_set_digest") == release_set_digest
            and int(compose_render.get("image_count") or 0) >= 8
            and int(compose_render.get("service_count") or 0) >= 8
            and compose.get("secret_included") is False
            and compose.get("database_url_included") is False
        ),
        "seven_demo_databases_current": (
            database.get("status") == "PASS"
            and database.get("actual_postgres") is True
            and database_admission.get("profile") == "dev"
            and database_admission.get("state") == "ADMITTED"
            and database_admission.get("service_count") == 7
            and database_admission.get("migration_current_count") == 7
            and database_redaction
            and not any(database_redaction.values())
            and migrations.get("status") == "PASS"
            and migrations.get("actual_postgres") is True
            and migrations.get("profile") == "dev"
            and migrations.get("service_count") == 7
            and migrations.get("migration_current_count") == 7
        ),
        "external_dependencies_live": (
            dependencies.get("status") == "PASS"
            and dependencies.get("actual_provider_execution") is True
            and dependencies.get("actual_rustfs_execution") is True
            and provider.get("status") == "PASS"
            and provider.get("capability_count") == 3
            and provider.get("responses_observed") == 3
            and object_storage.get("status") == "PASS"
            and object_storage.get("owner_isolation") is True
            and object_storage.get("restart_recovery") is True
            and dependencies.get("raw_secret_values_included") is False
            and dependencies.get("private_payloads_included") is False
        ),
        "trust_and_tls_live": (
            trust.get("status") == "PASS"
            and trust.get("executed") is True
            and trust_inventory.get("owner_count") == 7
            and trust_inventory.get("trust_grant_count") == 16
            and trust_inventory.get("raw_secret_values_included") is False
            and trust_inventory.get("token_values_included") is False
            and trust_pki.get("wc_eos_hosts_present") is True
            and trust.get("runtime_residue_retained") is False
        ),
        "installed_runtime_acceptance_passed": (
            s10.get("status") == "PASS"
            and s10.get("executed") is True
            and s10.get("release_set_digest") == release_set_digest
            and s10.get("ae_runtime_image_id") == ae_runtime_image_id
            and _zero_counts(s10.get("post_restart_queue_counts"))
            and s10b.get("status") == "PASS"
            and s10b.get("actual_postgres") is True
            and _all_true(s10b.get("checks"))
            and s10c.get("status") == "PASS"
            and s10c.get("actual_postgres") is True
            and _all_true(s10c.get("checks"))
        ),
        "chairman_journey_protected_and_recoverable": (
            s11.get("status") == "PASS"
            and s11.get("executed") is True
            and s11.get("release_set_digest") == release_set_digest
            and s11.get("ae_runtime_image_id") == ae_runtime_image_id
            and all(
                s11.get(name) is True
                for name in (
                    "actual_postgres",
                    "actual_compose",
                    "actual_openbao",
                    "actual_rustfs",
                    "actual_remote_generation",
                    "actual_playwright",
                )
            )
            and _all_true(s11_extended.get("checks"))
            and _all_true(s11_restart.get("checks"))
            and s11_restart.get("authoritative_recovery") is True
            and _zero_counts(s11.get("post_restart_queue_counts"))
            and s11.get("secret_included") is False
            and s11.get("token_value_included") is False
        ),
        "repository_full_gate_passed_and_fresh": (
            regression.get("status") == "PASS"
            and regression_metrics.get("failed_test_count") == 0
            and float(regression_metrics.get("statement_coverage") or 0) >= 96.0
            and float(regression_metrics.get("branch_coverage") or 0) >= 94.0
            and junit_mtime >= latest_protected_mtime
            and coverage_mtime >= latest_protected_mtime
        ),
        "operator_runbook_complete": bool(runbook)
        and all(token in runbook for token in RUNBOOK_TOKENS),
        "closure_runner_registered_once": quality_gate.count(RUNNER_NAME) == 1,
    }
    failed_checks = sorted(name for name, passed in checks.items() if not passed)
    identity_payload = {
        "source_revision": source_revision,
        "release_set_digest": release_set_digest,
        "ae_runtime_image_id": ae_runtime_image_id,
        "compose_overlay_digest": compose.get("overlay_digest"),
        "compose_dynamic_digest": compose.get("dynamic_digest"),
        "nsl_bundle_id": ae_bundle.get("bundle_id"),
        "dependency_identity_digest": dependencies.get(
            "dependency_identity_digest"
        ),
    }
    identity_digest = canonical_digest(identity_payload)
    passed = not failed_checks
    return {
        "schema_version": "p8_demo_s12_release_closure.v1",
        "slice": "P8-DEMO-S12",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "p8_demo_s12_closure_failed",
        "closure_status": "P8_DEMO_CLOSED" if passed else "BLOCKED",
        "release_candidate_id": f"p8-demo-rc:{identity_digest[7:23]}",
        "release_identity_digest": identity_digest,
        "release_identity": identity_payload,
        "checks": checks,
        "failed_checks": failed_checks,
        "full_regression": {
            "status": regression.get("status"),
            "passed_test_count": regression_metrics.get("passed_test_count"),
            "failed_test_count": regression_metrics.get("failed_test_count"),
            "skipped_test_count": regression_metrics.get("skipped_test_count"),
            "statement_coverage": regression_metrics.get("statement_coverage"),
            "branch_coverage": regression_metrics.get("branch_coverage"),
            "evidence_digest": regression.get("evidence_digest"),
        },
        "source_evidence_digests": {
            name: canonical_digest(_mapping(report))
            for name, report in sorted(reports.items())
        },
        "summary": {
            "check_count": len(checks),
            "passed_check_count": sum(checks.values()),
            "image_count": len(artifacts),
            "database_count": int(database_admission.get("service_count") or 0),
            "live_provider_capability_count": int(
                provider.get("capability_count") or 0
            ),
        },
        "production_deployment_performed": False,
        "registry_push_performed": False,
        "runtime_residue_retained": False,
        "next_action": "DEMO_OPERATOR_HANDOFF" if passed else "BLOCKED",
    }


def _failure(code: str, diagnostics: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "p8_demo_s12_release_closure.v1",
        "slice": "P8-DEMO-S12",
        "status": "FAIL",
        "failure_code": code,
        "closure_status": "BLOCKED",
        "diagnostics": dict(diagnostics),
        "production_deployment_performed": False,
        "registry_push_performed": False,
        "runtime_residue_retained": False,
        "next_action": "BLOCKED",
    }


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise TypeError("P8 Demo closure evidence must be a JSON object")
    return dict(value)


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _records(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _all_true(value: object) -> bool:
    checks = _mapping(value)
    return bool(checks) and all(item is True for item in checks.values())


def _zero_counts(value: object) -> bool:
    counts = _mapping(value)
    return bool(counts) and all(item == 0 for item in counts.values())


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def summary_line(result: Mapping[str, Any]) -> str:
    if result.get("status") == "SKIPPED":
        return "p8_demo_s12_release_closure=skipped"
    summary = _mapping(result.get("summary"))
    regression = _mapping(result.get("full_regression"))
    return (
        "p8_demo_s12_release_closure="
        f"{str(result.get('status') or 'FAIL').lower()} "
        f"release={result.get('release_candidate_id', 'none')} "
        f"checks={summary.get('passed_check_count', 0)}/"
        f"{summary.get('check_count', 0)} "
        f"tests={regression.get('passed_test_count', 0)} "
        f"coverage={regression.get('statement_coverage', 0)}/"
        f"{regression.get('branch_coverage', 0)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Close the P8 Demo release.")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--junit", type=Path, default=DEFAULT_JUNIT)
    parser.add_argument("--coverage", type=Path, default=DEFAULT_COVERAGE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    result = run_p8_demo_s12_release_operations_closure(
        execute=args.execute,
        junit_path=args.junit,
        coverage_path=args.coverage,
        output_path=args.output,
    )
    print(
        summary_line(result)
        if args.summary
        else json.dumps(result, indent=2, sort_keys=True)
    )
    return 0 if result.get("status") in {"PASS", "SKIPPED"} else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
