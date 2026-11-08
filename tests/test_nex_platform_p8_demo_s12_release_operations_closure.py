from __future__ import annotations

import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest
import run_p8_demo_s12_release_operations_closure as closure

DIGEST = "sha256:" + "a" * 64
AE_IMAGE_ID = "sha256:" + "b" * 64
REVISION = "c" * 40


def _reports() -> dict[str, dict]:
    artifacts = [
        {
            "artifact_id": artifact_id,
            "image_id": "sha256:" + f"{index:064x}",
            "manifest_digest": "sha256:" + f"{index:064x}",
            "runtime_user": "node" if artifact_id == "nex-ae-web" else "65532:65532",
        }
        for index, artifact_id in enumerate(sorted(closure.EXPECTED_ARTIFACTS), 1)
    ]
    return {
        "oci": {
            "schema_version": "p8_demo_oci_release.v1",
            "status": "PASS",
            "source_revision": REVISION,
            "image_build": {
                "status": "RELEASE_SET_BUILT",
                "source_tree_clean": True,
                "artifacts": artifacts,
            },
            "release_manifest": {
                "status": "RELEASE_SET_READY",
                "release_set_digest": DIGEST,
            },
            "summary": {
                "non_root_image_count": 8,
                "manifest_digest_count": 8,
                "background_check_count": 3,
            },
            "decision": {"registry_push_performed": False},
        },
        "ae_image": {
            "schema_version": "p8_demo_ae_runtime_image.v1",
            "status": "PASS",
            "registry_push_performed": False,
            "secret_included": False,
            "image": {
                "runtime_user": "65532:65532",
                "image_id": AE_IMAGE_ID,
            },
            "bundle": {
                "status": "PASS",
                "skill_version": "1.1.0",
                "bundle_id": "p8-demo-nsl-v0.2.1-golden-a-v1",
            },
        },
        "compose": {
            "schema_version": "p8_demo_compose.v1",
            "status": "PASS",
            "rendered": True,
            "image_release_set_digest": DIGEST,
            "overlay_digest": "sha256:" + "d" * 64,
            "dynamic_digest": "sha256:" + "e" * 64,
            "secret_included": False,
            "database_url_included": False,
            "render": {"image_count": 8, "service_count": 16},
        },
        "database": {
            "schema_version": "p8_demo_database_guardrail_evidence.v1",
            "status": "PASS",
            "actual_postgres": True,
            "admission": {
                "profile": "dev",
                "state": "ADMITTED",
                "service_count": 7,
                "migration_current_count": 7,
            },
            "redaction": {
                "confirmation_values_included": False,
                "credentials_included": False,
                "database_urls_included": False,
            },
        },
        "migrations": {
            "schema_version": "p8_demo_migration_execution.v1",
            "status": "PASS",
            "actual_postgres": True,
            "profile": "dev",
            "service_count": 7,
            "migration_current_count": 7,
        },
        "dependencies": {
            "schema_version": "p8_demo_external_dependencies.v1",
            "status": "PASS",
            "actual_provider_execution": True,
            "actual_rustfs_execution": True,
            "dependency_identity_digest": "sha256:" + "f" * 64,
            "raw_secret_values_included": False,
            "private_payloads_included": False,
            "provider": {
                "status": "PASS",
                "capability_count": 3,
                "responses_observed": 3,
            },
            "object_storage": {
                "status": "PASS",
                "owner_isolation": True,
                "restart_recovery": True,
            },
        },
        "trust": {
            "schema_version": "p8_demo_trust_admission.v1",
            "status": "PASS",
            "executed": True,
            "inventory": {
                "owner_count": 7,
                "trust_grant_count": 16,
                "raw_secret_values_included": False,
                "token_values_included": False,
            },
            "pki": {"wc_eos_hosts_present": True},
            "runtime_residue_retained": False,
        },
        "s10": {
            "schema_version": "p8_demo_s10_installed_domain_acceptance.v1",
            "status": "PASS",
            "executed": True,
            "release_set_digest": DIGEST,
            "ae_runtime_image_id": AE_IMAGE_ID,
            "post_restart_queue_counts": {
                "ae_runtime_jobs": 0,
                "eos_outbox_rows": 0,
                "wc_delivery_rows": 0,
            },
        },
        "s10b": {
            "schema_version": "p8_demo_s10b_installed_runtime.v1",
            "status": "PASS",
            "actual_postgres": True,
            "checks": {"compiled": True, "signed": True},
        },
        "s10c": {
            "schema_version": "p8_demo_s10c_installed_result_closure.v1",
            "status": "PASS",
            "actual_postgres": True,
            "checks": {"published": True, "replayed": True},
        },
        "s11": {
            "schema_version": "p8_demo_s11_chairman_golden_journey.v1",
            "status": "PASS",
            "executed": True,
            "release_set_digest": DIGEST,
            "ae_runtime_image_id": AE_IMAGE_ID,
            "actual_postgres": True,
            "actual_compose": True,
            "actual_openbao": True,
            "actual_rustfs": True,
            "actual_remote_generation": True,
            "actual_playwright": True,
            "secret_included": False,
            "token_value_included": False,
            "extended_acceptance": {
                "checks": {"journey": True, "voucher": True}
            },
            "post_restart_acceptance": {
                "authoritative_recovery": True,
                "checks": {"recovered": True, "stable": True},
            },
            "post_restart_queue_counts": {
                "ae_runtime_jobs": 0,
                "eos_outbox_rows": 0,
                "wc_delivery_rows": 0,
            },
        },
    }


def _regression() -> dict:
    return {
        "status": "PASS",
        "evidence_digest": "sha256:" + "1" * 64,
        "metrics": {
            "passed_test_count": 14_000,
            "failed_test_count": 0,
            "skipped_test_count": 30,
            "statement_coverage": 97.5,
            "branch_coverage": 96.1,
        },
    }


def _write_repository(root: Path) -> None:
    runbook = root / closure.RUNBOOK_PATH.relative_to(closure.ROOT)
    quality = root / closure.QUALITY_GATE_PATH.relative_to(closure.ROOT)
    runbook.parent.mkdir(parents=True, exist_ok=True)
    quality.parent.mkdir(parents=True, exist_ok=True)
    runbook.write_text("\n".join(closure.RUNBOOK_TOKENS), encoding="utf-8")
    quality.write_text(closure.RUNNER_NAME + "\n", encoding="utf-8")


def _evaluate(root: Path, reports: dict[str, dict] | None = None) -> dict:
    _write_repository(root)
    values = _reports() if reports is None else reports
    return closure._evaluate(
        values,
        _regression(),
        report_mtimes={name: 1.0 for name in closure.REPORT_SPECS},
        junit_mtime=2.0,
        coverage_mtime=2.0,
        root=root,
    )


def test_s12_accepts_complete_release_and_builds_stable_identity(tmp_path: Path) -> None:
    first = _evaluate(tmp_path)
    second = _evaluate(tmp_path)

    assert first["status"] == "PASS", first
    assert first["closure_status"] == "P8_DEMO_CLOSED"
    assert first["release_candidate_id"] == second["release_candidate_id"]
    assert first["release_candidate_id"].startswith("p8-demo-rc:")
    assert len(first["source_evidence_digests"]) == 11
    assert all(first["checks"].values())
    assert first["summary"] == {
        "check_count": 12,
        "passed_check_count": 12,
        "image_count": 8,
        "database_count": 7,
        "live_provider_capability_count": 3,
    }
    assert first["production_deployment_performed"] is False
    assert first["registry_push_performed"] is False
    assert first["runtime_residue_retained"] is False


@pytest.mark.parametrize(
    ("case", "failed_check"),
    (
        ("schema", "evidence_schemas_exact"),
        ("images", "eight_image_release_set_complete"),
        ("ae_image", "ae_runtime_bundle_admitted"),
        ("compose", "compose_render_matches_release"),
        ("database", "seven_demo_databases_current"),
        ("dependencies", "external_dependencies_live"),
        ("trust", "trust_and_tls_live"),
        ("runtime", "installed_runtime_acceptance_passed"),
        ("journey", "chairman_journey_protected_and_recoverable"),
        ("regression", "repository_full_gate_passed_and_fresh"),
        ("runbook", "operator_runbook_complete"),
        ("registration", "closure_runner_registered_once"),
    ),
)
def test_s12_fails_closed_for_each_release_gate(
    tmp_path: Path, case: str, failed_check: str
) -> None:
    reports = deepcopy(_reports())
    _write_repository(tmp_path)
    regression = _regression()
    junit_mtime = 2.0
    if case == "schema":
        reports["s11"]["schema_version"] = "wrong"
    elif case == "images":
        reports["oci"]["image_build"]["artifacts"].pop()
    elif case == "ae_image":
        reports["ae_image"]["bundle"]["bundle_id"] = "wrong"
    elif case == "compose":
        reports["compose"]["image_release_set_digest"] = "sha256:" + "0" * 64
    elif case == "database":
        reports["database"]["admission"]["migration_current_count"] = 6
    elif case == "dependencies":
        reports["dependencies"]["actual_provider_execution"] = False
    elif case == "trust":
        reports["trust"]["inventory"]["token_values_included"] = True
    elif case == "runtime":
        reports["s10b"]["checks"]["compiled"] = False
    elif case == "journey":
        reports["s11"]["post_restart_acceptance"]["checks"]["stable"] = False
    elif case == "regression":
        junit_mtime = 0.0
    elif case == "runbook":
        (tmp_path / closure.RUNBOOK_PATH.relative_to(closure.ROOT)).write_text("")
    elif case == "registration":
        quality = tmp_path / closure.QUALITY_GATE_PATH.relative_to(closure.ROOT)
        quality.write_text(closure.RUNNER_NAME * 2, encoding="utf-8")

    result = closure._evaluate(
        reports,
        regression,
        report_mtimes={name: 1.0 for name in closure.REPORT_SPECS},
        junit_mtime=junit_mtime,
        coverage_mtime=2.0,
        root=tmp_path,
    )

    assert result["status"] == "FAIL"
    assert result["checks"][failed_check] is False
    assert result["closure_status"] == "BLOCKED"
    assert result["next_action"] == "BLOCKED"


def test_s12_runs_from_files_and_writes_atomic_report(tmp_path: Path) -> None:
    _write_repository(tmp_path)
    paths: dict[str, Path] = {}
    for name, payload in _reports().items():
        path = tmp_path / "evidence" / f"{name}.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
        paths[name] = path
    junit = tmp_path / "junit.xml"
    coverage = tmp_path / "coverage.json"
    junit.write_text(
        '<testsuites tests="100" failures="0" errors="0" skipped="2"/>',
        encoding="utf-8",
    )
    coverage.write_text(
        json.dumps(
            {
                "totals": {
                    "covered_lines": 98,
                    "num_statements": 100,
                    "covered_branches": 97,
                    "num_branches": 100,
                }
            }
        ),
        encoding="utf-8",
    )
    for path in paths.values():
        path.touch()
    junit.touch()
    coverage.touch()
    output = tmp_path / "output/closure.json"

    result = closure.run_p8_demo_s12_release_operations_closure(
        {closure.ACTIVATION_ENV: "1"},
        execute=True,
        report_paths=paths,
        junit_path=junit,
        coverage_path=coverage,
        output_path=output,
        root=tmp_path,
    )

    assert result["status"] == "PASS", result
    assert json.loads(output.read_text(encoding="utf-8")) == result
    assert not output.with_suffix(".json.tmp").exists()


@pytest.mark.parametrize("case", ("missing", "list", "json", "junit", "coverage"))
def test_s12_malformed_inputs_fail_closed(tmp_path: Path, case: str) -> None:
    _write_repository(tmp_path)
    paths: dict[str, Path] = {}
    for name, payload in _reports().items():
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        paths[name] = path
    junit = tmp_path / "junit.xml"
    coverage = tmp_path / "coverage.json"
    junit.write_text('<testsuite tests="1" failures="0"/>', encoding="utf-8")
    coverage.write_text(
        json.dumps(
            {
                "totals": {
                    "covered_lines": 1,
                    "num_statements": 1,
                    "covered_branches": 1,
                    "num_branches": 1,
                }
            }
        ),
        encoding="utf-8",
    )
    if case == "missing":
        paths["oci"] = tmp_path / "missing.json"
    elif case == "list":
        paths["oci"].write_text("[]", encoding="utf-8")
    elif case == "json":
        paths["s11"].write_text("{", encoding="utf-8")
    elif case == "junit":
        junit.write_text("<testsuite>", encoding="utf-8")
    elif case == "coverage":
        coverage.write_text("{", encoding="utf-8")

    result = closure.run_p8_demo_s12_release_operations_closure(
        {closure.ACTIVATION_ENV: "1"},
        execute=True,
        report_paths=paths,
        junit_path=junit,
        coverage_path=coverage,
        output_path=tmp_path / "closure.json",
        root=tmp_path,
    )

    assert result["status"] == "FAIL"
    assert result["failure_code"] == "p8_demo_s12_input_failed"
    assert result["next_action"] == "BLOCKED"


def test_s12_skip_summary_and_standalone_cli(tmp_path: Path) -> None:
    skipped = closure.run_p8_demo_s12_release_operations_closure({}, execute=True)
    assert skipped["status"] == "SKIPPED"
    assert closure.summary_line(skipped) == "p8_demo_s12_release_closure=skipped"
    summary = closure.summary_line(_evaluate(tmp_path))
    assert "p8_demo_s12_release_closure=pass" in summary
    assert "checks=12/12" in summary

    completed = subprocess.run(
        [
            sys.executable,
            str(
                closure.ROOT
                / "scripts/deployment/run_p8_demo_s12_release_operations_closure.py"
            ),
            "--summary",
        ],
        cwd=closure.ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    assert completed.stdout.strip() == "p8_demo_s12_release_closure=skipped"


def test_s12_default_paths_fail_closed_and_helpers_cover_empty_values(
    tmp_path: Path,
) -> None:
    result = closure.run_p8_demo_s12_release_operations_closure(
        {closure.ACTIVATION_ENV: "1"},
        execute=True,
        root=tmp_path,
    )

    assert result["failure_code"] == "p8_demo_s12_closure_failed"
    assert closure._records(None) == []
    assert closure._records([{"safe": True}, "ignored"]) == [{"safe": True}]
    assert closure._mapping(None) == {}
    assert closure._all_true(None) is False
    assert closure._zero_counts(None) is False
    assert closure._read_text(tmp_path / "missing.md") == ""


@pytest.mark.parametrize(
    ("result", "argv", "expected_exit", "expected_text"),
    (
        (
            {"status": "SKIPPED"},
            ["--summary"],
            0,
            "p8_demo_s12_release_closure=skipped",
        ),
        (
            {"status": "FAIL", "failure_code": "blocked"},
            [],
            1,
            '"failure_code": "blocked"',
        ),
    ),
)
def test_s12_main_formats_summary_and_json(
    monkeypatch,
    capsys,
    result: dict,
    argv: list[str],
    expected_exit: int,
    expected_text: str,
) -> None:
    monkeypatch.setattr(
        closure,
        "run_p8_demo_s12_release_operations_closure",
        lambda **_kwargs: result,
    )

    assert closure.main(argv) == expected_exit
    assert expected_text in capsys.readouterr().out
