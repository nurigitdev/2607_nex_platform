from __future__ import annotations

from pathlib import Path

import run_service_token_rollout_observability as runner


def test_service_token_rollout_observability_passes() -> None:
    evidence = runner.run_service_token_rollout_observability()

    assert evidence["status"] == "PASS"
    assert all(evidence["checks"].values())
    assert evidence["consumer_count"] == 4
    assert evidence["runtime_schema_version"] == "service_token_runtime.v1"
    assert evidence["next_slice"] == "1280"


def test_observability_fails_closed_for_empty_repository(tmp_path: Path) -> None:
    evidence = runner.run_service_token_rollout_observability(tmp_path)

    assert evidence["status"] == "FAIL"
    assert evidence["checks"]["projection_contract_valid"] is False
    assert evidence["checks"]["all_consumers_wire_shared_admission"] is False


def test_summary_and_main(capsys, monkeypatch) -> None:
    evidence = runner.run_service_token_rollout_observability()
    assert runner.summary_line(evidence) == (
        "service_token_rollout_observability=pass consumers=4 "
        "schema=service_token_runtime.v1 next=1280"
    )
    monkeypatch.setattr(
        runner,
        "run_service_token_rollout_observability",
        lambda: evidence,
    )
    assert runner.main(["--summary"]) == 0
    assert "service_token_rollout_observability=pass" in capsys.readouterr().out
    failed = {
        "status": "FAIL",
        "consumer_count": 0,
        "runtime_schema_version": None,
        "next_slice": "blocked",
    }
    monkeypatch.setattr(
        runner,
        "run_service_token_rollout_observability",
        lambda: failed,
    )
    assert runner.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out
