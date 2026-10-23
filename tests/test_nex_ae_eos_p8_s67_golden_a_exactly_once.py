from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/smoke"))

import run_p8_s67_golden_a_exactly_once as smoke


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
        smoke.p8_s66.EOS_DATABASE_ENV: (
            "postgresql+psycopg://nex_eos_user:private@localhost/nex_eos_test"
        ),
    }


def _s65_result() -> dict[str, object]:
    return {
        "status": "PASS",
        "provider": {"model_ref": "model-a"},
        "approval": {
            "payload_hash": "sha256:" + "a" * 64,
            "event_replay": {
                "created": False,
                "resume_runtime_job_id": "resume-a",
            },
            "resume_enqueue_replay": {"runtime_job_id": "resume-a"},
            "resume_job_count": 1,
        },
    }


def _commit_result() -> dict[str, object]:
    return {
        "checks": {
            "ack_loss_reconciled": True,
            "worker_and_publication_retry_reused": True,
            "eos_committed_once": True,
        },
        "payload_hash": "sha256:" + "a" * 64,
        "eos_mutation_counts": {"eos_voucher_draft": 1},
        "retry_variants": {
            "ack_loss_after_commit": {
                "observed_commit_state": "UNKNOWN_COMMIT_STATE",
                "reconciled_commit_state": "COMMITTED",
            }
        },
    }


def test_p8_s67_live_gate_is_explicitly_protected() -> None:
    assert (
        smoke.run_p8_s67_golden_a_exactly_once({}, execute=False)["status"] == "SKIPPED"
    )
    assert (
        smoke.run_p8_s67_golden_a_exactly_once({}, execute=True)["status"] == "SKIPPED"
    )


def test_s67_requires_exact_eos_test_target() -> None:
    env = {**_database_env(), smoke.SMOKE_ENV: "1"}
    env[smoke.p8_s66.EOS_DATABASE_ENV] = (
        "postgresql+psycopg://nex_eos_user:private@localhost/nex_eos_dev"
    )

    result = smoke.run_p8_s67_golden_a_exactly_once(env, execute=True)

    assert result["status"] == "FAIL"
    assert result["failure_code"] == "P8S65SmokeError"
    assert "nex_eos_dev" not in json.dumps(result)
    assert "private" not in json.dumps(result)


def test_s67_composes_all_retry_boundaries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        smoke.p8_s65,
        "run_p8_s65_golden_a_approval_journey",
        lambda *_args, **_kwargs: _s65_result(),
    )
    monkeypatch.setattr(
        smoke.p8_s66,
        "run_service_migrations",
        lambda *_args, **_kwargs: SimpleNamespace(
            planned=("one",), applied=(), skipped=("one",)
        ),
    )
    captured: dict[str, object] = {}

    def execute_commit(**kwargs):
        captured.update(kwargs)
        return _commit_result()

    monkeypatch.setattr(smoke.p8_s66, "_execute_commit", execute_commit)

    result = smoke.run_p8_s67_golden_a_exactly_once(
        {**_database_env(), smoke.SMOKE_ENV: "1"}, execute=True
    )

    assert result["status"] == "PASS"
    assert captured["exactly_once"] is True
    assert result["checks_passed"] == result["checks_total"]
    assert result["decision"] == {
        "p8_s67_closed": True,
        "business_mutation_count": 1,
        "next_slice": "P8-S68",
    }


def test_s67_fails_closed_when_resume_dedup_evidence_differs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s65 = _s65_result()
    s65["approval"]["resume_job_count"] = 2
    monkeypatch.setattr(
        smoke.p8_s65,
        "run_p8_s65_golden_a_approval_journey",
        lambda *_args, **_kwargs: s65,
    )
    monkeypatch.setattr(
        smoke.p8_s66,
        "run_service_migrations",
        lambda *_args, **_kwargs: SimpleNamespace(
            planned=("one",), applied=(), skipped=("one",)
        ),
    )
    monkeypatch.setattr(
        smoke.p8_s66, "_execute_commit", lambda **_kwargs: _commit_result()
    )

    result = smoke.run_p8_s67_golden_a_exactly_once(
        {**_database_env(), smoke.SMOKE_ENV: "1"}, execute=True
    )

    assert result["status"] == "FAIL"
    assert result["checks"]["duplicate_resume_enqueue_idempotent"] is False
    assert result["decision"]["p8_s67_closed"] is False


def test_s67_summary_excludes_lineage_and_secrets(tmp_path: Path) -> None:
    evidence = {
        "status": "PASS",
        "actual_postgres": True,
        "actual_remote_provider": True,
        "checks": {"one": True, "two": True},
        "decision": {"business_mutation_count": 1},
    }
    summary = smoke.summary_line(evidence)
    report = tmp_path / "s67.json"
    smoke.write_report(report, evidence)

    assert "checks=2/2" in summary
    assert "mutations=1" in summary
    assert "approval_request" not in summary
    assert json.loads(report.read_text(encoding="utf-8")) == evidence


@pytest.mark.skipif(
    os.getenv(smoke.SMOKE_ENV) != "1"
    or any(not os.getenv(key) for key in smoke.EXPECTED_DATABASES),
    reason="Protected P8-S67 Golden A exactly-once gate is disabled",
)
def test_actual_postgres_live_provider_golden_a_retry_variants() -> None:
    result = smoke.run_p8_s67_golden_a_exactly_once(execute=True)

    assert result["status"] == "PASS", result
    assert result["decision"]["business_mutation_count"] == 1
    assert result["eos_mutation_counts"]["eos_business_operation"] == 1
    assert result["eos_mutation_counts"]["eos_voucher_draft"] == 1
    assert result["eos_mutation_counts"]["eos_outbox"] == 1
    assert result["ae_evidence_counts"] == {
        "idempotency": 1,
        "write_evidence": 3,
    }
    assert result["retry_variants"]["ack_loss_after_commit"] == {
        "response_status_discarded": 201,
        "observed_commit_state": "UNKNOWN_COMMIT_STATE",
        "reconciled_commit_state": "COMMITTED",
    }
