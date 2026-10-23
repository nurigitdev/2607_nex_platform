from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/smoke"))

import run_p8_s66_golden_a_eos_commit_journey as smoke


def _database_env() -> dict[str, str]:
    return {
        smoke.p8_s65.AE_DATABASE_ENV: (
            "postgresql+psycopg://nex_ae_user:private@localhost/nex_ae_test"
        ),
        smoke.p8_s65.WC_DATABASE_ENV: (
            "postgresql+psycopg://nex_wc_user:private@localhost/nex_wc_test"
        ),
        smoke.p8_s65.OA_DATABASE_ENV: (
            "postgresql+psycopg://nex_oa_user:private@localhost/nex_oa_test"
        ),
        smoke.EOS_DATABASE_ENV: (
            "postgresql+psycopg://nex_eos_user:private@localhost/nex_eos_test"
        ),
    }


def test_p8_s66_live_gate_is_explicitly_protected() -> None:
    assert (
        smoke.run_p8_s66_golden_a_eos_commit_journey({}, execute=False)["status"]
        == "SKIPPED"
    )
    assert (
        smoke.run_p8_s66_golden_a_eos_commit_journey({}, execute=True)["status"]
        == "SKIPPED"
    )


def test_s66_requires_exact_eos_test_target() -> None:
    env = {**_database_env(), smoke.SMOKE_ENV: "1"}
    env[smoke.EOS_DATABASE_ENV] = (
        "postgresql+psycopg://nex_eos_user:private@localhost/nex_eos_dev"
    )

    result = smoke.run_p8_s66_golden_a_eos_commit_journey(env, execute=True)

    assert result["status"] == "FAIL"
    assert result["failure_code"] == "P8S65SmokeError"
    assert "nex_eos_dev" not in json.dumps(result)
    assert "private" not in json.dumps(result)


def test_s66_composes_s65_hash_with_eos_commit_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload_hash = "sha256:" + "a" * 64
    monkeypatch.setattr(
        smoke.p8_s65,
        "run_p8_s65_golden_a_approval_journey",
        lambda *_args, **_kwargs: {
            "status": "PASS",
            "approval": {
                "payload_hash": payload_hash,
                "approval_status": "APPROVED",
                "resume_state": "DONE",
            },
            "provider": {"model_ref": "model-a"},
        },
    )
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *_args, **_kwargs: SimpleNamespace(
            planned=("one",), applied=(), skipped=("one",)
        ),
    )
    monkeypatch.setattr(
        smoke,
        "_execute_commit",
        lambda **_kwargs: {
            "checks": {"approved_payload_hash_reused": True},
            "payload_hash": payload_hash,
            "commit_state": "COMMITTED",
            "verification_status": "VERIFIED",
        },
    )

    result = smoke.run_p8_s66_golden_a_eos_commit_journey(
        {**_database_env(), smoke.SMOKE_ENV: "1"},
        execute=True,
    )

    assert result["status"] == "PASS"
    assert result["payload_hash"] == result["s65"]["payload_hash"]
    assert result["decision"] == {
        "p8_s66_closed": True,
        "next_slice": "P8-S67",
    }


def test_s66_summary_excludes_lineage_details() -> None:
    summary = smoke.summary_line(
        {
            "status": "PASS",
            "actual_postgres": True,
            "actual_remote_provider": True,
            "checks": {"one": True, "two": True},
            "commit_state": "COMMITTED",
            "verification_status": "VERIFIED",
        }
    )

    assert "checks=2/2" in summary
    assert "commit=COMMITTED" in summary
    assert "verification=VERIFIED" in summary
    assert "approval_request" not in summary


@pytest.mark.skipif(
    os.getenv(smoke.SMOKE_ENV) != "1"
    or any(not os.getenv(key) for key in smoke.EXPECTED_DATABASES),
    reason="Protected P8-S66 Golden A PostgreSQL/provider gate is disabled",
)
def test_actual_postgres_live_provider_golden_a_eos_commit() -> None:
    result = smoke.run_p8_s66_golden_a_eos_commit_journey(execute=True)

    assert result["status"] == "PASS", result
    assert result["payload_hash"] == result["s65"]["payload_hash"]
    assert result["commit_state"] == "COMMITTED"
    assert result["verification_status"] == "VERIFIED"
