from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts/deployment"))

import nex_runtime.current_platform_installation as installation
import run_gb2_ca00_s18_installed_current_platform_golden_journey as acceptance
from nex_runtime.current_platform_installation import (
    CurrentPlatformInstallationError,
    admit_current_platform_installation,
)

ROOT = Path(__file__).resolve().parents[1]


def _passing_protected_evidence() -> dict:
    return {
        "status": "PASS",
        "actual_postgres": True,
        "actual_compose": True,
        "actual_openbao": True,
        "actual_rustfs": True,
        "actual_remote_generation": True,
        "actual_playwright": True,
        "extended_acceptance": {"checks": {"one_result": True}},
        "post_restart_acceptance": {"checks": {"result_stable": True}},
        "pre_activation_queue_counts": {"pending": 0},
        "post_restart_queue_counts": {"pending": 0},
    }


def test_current_installation_admits_current_manifest_and_compose_layers() -> None:
    result = admit_current_platform_installation(ROOT)

    assert result["status"] == "ADMITTED"
    assert result["artifact_count"] == 9
    assert result["process_count"] == 20
    assert result["journey_process_count"] == 9
    assert result["additive_process_count"] == 2
    assert result["compose_layer_count"] == 4
    assert all(result["checks"].values())
    assert result["p8_demo_process_manifest_used"] is False
    assert result["manual_component_composition"] is False
    assert {
        item[1] for item in installation.CURRENT_JOURNEY_WORKERS.values()
    } == {
        "ae-product-agent-runtime-1",
        "wc-event-delivery-worker-1",
        "eos-outbox-publisher-1",
    }


def test_current_installation_fails_closed_for_missing_compose_source(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        CurrentPlatformInstallationError, match="Compose source is unavailable"
    ):
        admit_current_platform_installation(tmp_path)


def test_current_installation_rejects_invalid_compose_and_profile_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = tmp_path / installation.CURRENT_COMPOSE_PATHS[0]
    first.parent.mkdir(parents=True)
    first.write_text("services: []\n", encoding="utf-8")
    with pytest.raises(
        CurrentPlatformInstallationError, match="Compose services are invalid"
    ):
        installation._merged_compose_services(tmp_path)

    monkeypatch.setattr(installation, "_product_ae_worker_profile", lambda _: False)
    with pytest.raises(
        CurrentPlatformInstallationError, match="product_ae_worker_profile"
    ):
        admit_current_platform_installation(ROOT)


def test_compose_command_matching_is_fail_closed_and_profile_aware() -> None:
    assert installation._compose_command_matches(
        ("npm", "start", "--silent"), ["npm", "start"]
    )
    assert installation._compose_command_matches(
        ("python", "-m", "worker", "--profile", "local_mock"),
        ["python", "-m", "worker", "--profile", "staging_live"],
    )
    assert not installation._compose_command_matches(
        ("python", "-m", "worker"), None
    )
    assert not installation._compose_command_matches(
        ("python", "-m", "worker"), ["python", 1]
    )
    assert not installation._compose_command_matches(
        ("python", "-m", "uvicorn", "service.main:app"),
        ["python", "-m", "uvicorn", "other.main:app"],
    )


def test_product_ae_image_contract_cannot_be_overridden_by_compose() -> None:
    assert installation._product_ae_image_contract_not_overridden(
        {
            "environment": {
                "NEX_AE_FINANCE_GOLDEN_A_AUTHORITY_PROFILE_PATH": (
                    "/app/deployment/product/config/finance-golden-a-vo00.v1.json"
                ),
                "NEX_AE_PRODUCT_CAPABILITY_REGISTRY_PATH": (
                    "/app/deployment/product/config/"
                    "ae-product-capability-registry.v1.json"
                ),
            }
        }
    )
    assert not installation._product_ae_image_contract_not_overridden(
        {
            "environment": {
                "NEX_AE_PRODUCT_CAPABILITY_REGISTRY_PATH": (
                    "/app/deployment/p8-demo/config/registry.json"
                )
            }
        }
    )
    assert not installation._product_ae_image_contract_not_overridden({})


def test_s18_source_admission_is_current_and_nonexecuting() -> None:
    result = acceptance.run_installed_current_platform_continuity(
        {}, execute=False, root=ROOT
    )

    assert result["status"] == "SOURCE_ADMITTED"
    assert result["executed"] is False
    assert result["current_artifact_count"] == 9
    assert result["current_process_count"] == 20
    assert result["platform_integrated"] is True
    assert result["runtime_transition_fixture"] is False
    assert result["manual_domain_transition"] is False
    assert result["installed_process_continuity"] is True


def test_s18_execution_is_double_opt_in_and_fail_closed() -> None:
    calls = []

    def runner(environment):
        calls.append(dict(environment))
        return _passing_protected_evidence()

    skipped = acceptance.run_installed_current_platform_continuity(
        {}, execute=True, root=ROOT, protected_runner=runner
    )
    passed = acceptance.run_installed_current_platform_continuity(
        {acceptance.EXECUTION_ENV: "1"},
        execute=True,
        root=ROOT,
        protected_runner=runner,
    )
    failed = acceptance.run_installed_current_platform_continuity(
        {acceptance.EXECUTION_ENV: "1"},
        execute=True,
        root=ROOT,
        protected_runner=lambda _: {
            **_passing_protected_evidence(),
            "actual_postgres": False,
        },
    )

    assert skipped["status"] == "SOURCE_ADMITTED"
    assert passed["status"] == "PASS"
    assert passed["executed"] is True
    assert all(passed["continuity_checks"].values())
    assert len(calls) == 1
    assert failed["status"] == "FAIL"
    assert failed["secret_included"] is False


def test_s18_cli_writes_bounded_source_report(tmp_path: Path) -> None:
    report = tmp_path / "s18.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(
                ROOT
                / "scripts/deployment/"
                "run_gb2_ca00_s18_installed_current_platform_golden_journey.py"
            ),
            "--summary",
            "--report",
            str(report),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "source_admitted" in completed.stdout
    evidence = json.loads(report.read_text(encoding="utf-8"))
    assert evidence["status"] == "SOURCE_ADMITTED"
    assert evidence["secret_included"] is False


def test_s18_summary_is_bounded() -> None:
    assert acceptance.summary_line(
        {
            "status": "PASS",
            "executed": True,
            "current_process_count": 20,
            "actual_postgres": True,
            "actual_remote_generation": True,
            "actual_playwright": True,
        }
    ) == (
        "gb2_ca00_s18_installed_current_platform=pass executed=true "
        "processes=20 postgres=true provider=true playwright=true"
    )
