from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/smoke/run_mybee_w40_ca02_s04_protected_acceptance.py"
PROTECTED = os.getenv("NEX_MYBEE_W40_CA02_S04_PROTECTED") == "1"


def test_s04_runner_is_product_bound_and_fixture_independent() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "create_eos_app" in source
    assert "HttpOaProjectEntitlementTransport" in source
    assert "HttpVoucherCandidateProviderTransport" in source
    assert "SqlAlchemyEosOutboxPublisher" in source
    assert "ServiceTokenAdmissionRuntime" in source
    assert 'rollout_profile="SIGNED_ONLY"' in source
    assert "run_service_migrations" in source
    assert "mybee_w40ca02s04_eos_" in source
    assert "mybee_w40ca02s04_oa_" in source
    assert "tests." not in source
    assert "p8_demo" not in source.lower()
    assert "remote_provider_required" in source


def test_s04_runner_has_standalone_operator_surface() -> None:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "--report" in completed.stdout
    assert "--summary" in completed.stdout


@pytest.mark.skipif(
    not PROTECTED,
    reason="Protected W40-CA02-S04 PostgreSQL/HTTP acceptance is disabled",
)
def test_actual_postgres_signed_http_restart_replay_fail_closed(
    tmp_path: Path,
) -> None:
    report = tmp_path / "w40-ca02-s04.json"
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--report",
            str(report),
            "--summary",
        ],
        cwd=ROOT,
        env={**os.environ},
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    evidence = json.loads(report.read_text(encoding="utf-8"))
    assert evidence["status"] == "PASS"
    assert evidence["actual_postgresql"] is True
    assert evidence["actual_loopback_http"] is True
    assert evidence["signed_service_tokens"] is True
    assert evidence["entitlement_restart_recovered"] is True
    assert evidence["entitlement_exact_replay"] is True
    assert evidence["entitlement_tamper_rejected"] is True
    assert evidence["voucher_candidate_created"] is True
    assert evidence["voucher_candidate_validated"] is True
    assert evidence["service_restart_replay"] is True
    assert evidence["changed_replay_conflict"] is True
    assert len(evidence["fail_closed_matrix"]) == 4
    assert evidence["zero_residue"] is True
    assert evidence["secret_included"] is False
    assert evidence["content_included"] is False
    assert evidence["next_slice"] == "W40-S4-01"
