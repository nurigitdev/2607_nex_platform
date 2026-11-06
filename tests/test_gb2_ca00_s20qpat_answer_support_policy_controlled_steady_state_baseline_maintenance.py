from __future__ import annotations

import json
from datetime import datetime, timezone

import run_gb2_s20qpat_answer_support_policy_controlled_steady_state_baseline_maintenance as smoke
from nex_cx.retrieval_answer_support_policy_controlled_steady_state_baseline_maintenance import (
    DECISION,
)
from test_nex_cx_retrieval_answer_support_policy_controlled_steady_state_baseline_maintenance import (
    _closure,
    _policy,
)

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)


def test_protected_maintenance_activates_passive_guardrail() -> None:
    result = smoke.run_gb2_s20qpat_controlled_steady_state_baseline_maintenance(
        _env(), policy=_policy(), closure_report=_closure(), now=NOW
    )

    assert result["status"] == "PASS"
    assert result["decision"] == DECISION
    assert result["maintenance_status"] == "ACTIVE_CONTROLLED_BASELINE_MAINTENANCE"
    assert result["admission_status"] == "ADMITTED_CONTROLLED_BASELINE"
    assert result["provider_calls"] == result["database_calls"] == 0
    assert result["holdout_accessed"] is False
    assert result["runtime_changed"] is False
    assert result["rollback_contract_preserved"] is True
    assert result["production_cutover_permitted"] is False
    assert "maintenance=ACTIVE_CONTROLLED_BASELINE_MAINTENANCE" in (
        smoke.summary_line(result)
    )


def test_runner_skip_and_integrity_failure_are_bounded() -> None:
    skipped = smoke.run_gb2_s20qpat_controlled_steady_state_baseline_maintenance({})
    assert skipped["status"] == "SKIPPED"
    assert smoke.summary_line(skipped).endswith("=skipped")

    closure = _closure()
    closure["status"] = "FAIL"
    result = smoke.run_gb2_s20qpat_controlled_steady_state_baseline_maintenance(
        _env(), policy=_policy(), closure_report=closure, now=NOW
    )
    assert result["status"] == "FAIL"
    assert result["failure_code"] == (
        "controlled_steady_state_baseline_maintenance_failed"
    )
    assert result["failure_detail"] == {
        "exception": "ControlledSteadyStateBaselineMaintenanceError"
    }
    assert result["provider_calls"] == result["database_calls"] == 0
    assert result["runtime_changed"] is False
    assert "=fail" in smoke.summary_line(result)
    assert "failure_detail" not in smoke._failure("without_detail")

    empty_policy = smoke.run_gb2_s20qpat_controlled_steady_state_baseline_maintenance(
        _env(), policy={}, closure_report=_closure(), now=NOW
    )
    empty_report = smoke.run_gb2_s20qpat_controlled_steady_state_baseline_maintenance(
        _env(), policy=_policy(), closure_report={}, now=NOW
    )
    assert empty_policy["status"] == empty_report["status"] == "FAIL"


def test_runner_requires_owner_private_closure_report(tmp_path) -> None:
    path = tmp_path / "closure.json"
    path.write_text(json.dumps(_closure()), encoding="utf-8")
    path.chmod(0o644)
    result = smoke.run_gb2_s20qpat_controlled_steady_state_baseline_maintenance(
        {**_env(), smoke.CLOSURE_REPORT_ENV: str(path)},
        policy=_policy(),
        now=NOW,
    )
    assert result["status"] == "FAIL"
    assert result["failure_detail"] == {"exception": "PermissionError"}

    path.chmod(0o600)
    result = smoke.run_gb2_s20qpat_controlled_steady_state_baseline_maintenance(
        {**_env(), smoke.CLOSURE_REPORT_ENV: str(path)},
        policy=_policy(),
        now=NOW,
    )
    assert result["status"] == "PASS"


def test_runner_accepts_explicit_cadence_and_reopen_signals() -> None:
    result = smoke.run_gb2_s20qpat_controlled_steady_state_baseline_maintenance(
        {
            **_env(),
            smoke.LAST_REVIEWED_AT_ENV: "2026-09-01T00:00:00Z",
            smoke.EVALUATED_AT_ENV: "2026-11-06T00:00:00Z",
        },
        policy=_policy(),
        closure_report=_closure(),
        observed_reopen_events=("MODEL_OR_PROVIDER_REVISION_CHANGED",),
        now=NOW,
    )
    assert result["maintenance_status"] == "BASELINE_REOPEN_REQUIRED"
    assert result["review_due"] is True
    assert result["triggered_reopen_conditions"] == [
        "MODEL_OR_PROVIDER_REVISION_CHANGED"
    ]


def test_load_rejects_non_object_and_cli_writes_private_evidence(
    tmp_path, monkeypatch, capsys
) -> None:
    value = tmp_path / "value.json"
    value.write_text("[]", encoding="utf-8")
    try:
        smoke._load(value)
    except TypeError:
        pass
    else:
        raise AssertionError("list JSON must fail")

    output = tmp_path / "output.json"
    passing = {
        "status": "PASS",
        "maintenance_status": "ACTIVE_CONTROLLED_BASELINE_MAINTENANCE",
        "admission_status": "ADMITTED_CONTROLLED_BASELINE",
        "next_boundary": "periodic-review",
    }
    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpat_controlled_steady_state_baseline_maintenance",
        lambda: passing,
    )
    assert smoke.main(["--output", str(output), "--summary"]) == 0
    assert "=pass" in capsys.readouterr().out
    assert output.stat().st_mode & 0o777 == 0o600

    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpat_controlled_steady_state_baseline_maintenance",
        lambda: {"status": "SKIPPED"},
    )
    assert smoke.main(["--output", str(output)]) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "PASS"

    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpat_controlled_steady_state_baseline_maintenance",
        lambda: {"status": "FAIL", "failure_code": "forced"},
    )
    assert smoke.main(["--output", str(output)]) == 1


def _env() -> dict[str, str]:
    return {smoke.SMOKE_ENV: "1"}
