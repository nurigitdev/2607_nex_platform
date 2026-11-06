from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import run_gb2_s20q_multi_signal_live_holdout_acceptance_closure as smoke
from test_nex_cx_retrieval_multisignal_holdout_acceptance_closure import _sources


def test_protected_runner_closes_s20q_without_external_calls() -> None:
    result = smoke.run_gb2_s20q_multi_signal_live_holdout_acceptance_closure(
        _env(), **_sources()
    )

    assert result["status"] == "PASS"
    assert result["slice_id"] == "GB2-CA00-S20Q"
    assert result["decision"] == "MULTI_SIGNAL_LIVE_HOLDOUT_ACCEPTANCE_CLOSED"
    assert result["provider_calls"] == result["database_calls"] == 0
    assert result["holdout_accessed"] is False
    assert result["runtime_changed"] is False
    assert "closure=CLOSED_PASS" in smoke.summary_line(result)


def test_skip_and_integrity_failure_are_bounded() -> None:
    skipped = smoke.run_gb2_s20q_multi_signal_live_holdout_acceptance_closure({})
    assert skipped["status"] == "SKIPPED"
    assert smoke.summary_line(skipped).endswith("=skipped")

    sources = _sources()
    sources["holdout_report"]["status"] = "TAMPERED"
    failed = smoke.run_gb2_s20q_multi_signal_live_holdout_acceptance_closure(
        _env(), **sources
    )
    assert failed["status"] == "FAIL"
    assert failed["failure_code"] == (
        "multi_signal_live_holdout_acceptance_closure_failed"
    )
    assert failed["failure_detail"] == {
        "exception": "MultiSignalHoldoutAcceptanceClosureError"
    }
    assert failed["provider_calls"] == failed["database_calls"] == 0
    assert failed["holdout_accessed"] is False
    assert failed["runtime_changed"] is False
    assert "=fail" in smoke.summary_line(failed)
    assert "failure_detail" not in smoke._failure("without-detail")

    empty = smoke.run_gb2_s20q_multi_signal_live_holdout_acceptance_closure(
        _env(), **{**_sources(), "design": {}}
    )
    assert empty["status"] == "FAIL"


def test_runner_requires_owner_private_control_evidence(tmp_path: Path) -> None:
    sources = _sources()
    for env_name, source_name in (
        (smoke.RECEIPT_ENV, "holdout_receipt"),
        (smoke.OPERATIONS_ENV, "operations_closure_report"),
        (smoke.MAINTENANCE_ENV, "maintenance_report"),
    ):
        path = tmp_path / f"{source_name}.json"
        path.write_text(json.dumps(sources[source_name]), encoding="utf-8")
        path.chmod(0o644)
        kwargs = deepcopy(sources)
        kwargs[source_name] = None
        result = smoke.run_gb2_s20q_multi_signal_live_holdout_acceptance_closure(
            {**_env(), env_name: str(path)}, **kwargs
        )
        assert result["status"] == "FAIL"
        assert result["failure_detail"] == {"exception": "PermissionError"}

        path.chmod(0o600)
        result = smoke.run_gb2_s20q_multi_signal_live_holdout_acceptance_closure(
            {**_env(), env_name: str(path)}, **kwargs
        )
        assert result["status"] == "PASS"


def test_load_guards_and_cli_private_output(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    value = tmp_path / "value.json"
    value.write_text("[]", encoding="utf-8")
    try:
        smoke._load(value)
    except TypeError:
        pass
    else:
        raise AssertionError("list JSON must fail")

    output = tmp_path / "closure.json"
    passing = {
        "status": "PASS",
        "decision": "MULTI_SIGNAL_LIVE_HOLDOUT_ACCEPTANCE_CLOSED",
        "closure_status": "CLOSED_PASS",
        "next_boundary": "S20R",
    }
    monkeypatch.setattr(
        smoke,
        "run_gb2_s20q_multi_signal_live_holdout_acceptance_closure",
        lambda: passing,
    )
    assert smoke.main(["--output", str(output), "--summary"]) == 0
    assert "=pass" in capsys.readouterr().out
    assert output.stat().st_mode & 0o777 == 0o600

    monkeypatch.setattr(
        smoke,
        "run_gb2_s20q_multi_signal_live_holdout_acceptance_closure",
        lambda: {"status": "SKIPPED"},
    )
    assert smoke.main(["--output", str(output)]) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "PASS"

    monkeypatch.setattr(
        smoke,
        "run_gb2_s20q_multi_signal_live_holdout_acceptance_closure",
        lambda: {"status": "FAIL", "failure_code": "forced"},
    )
    assert smoke.main(["--output", str(output)]) == 1


def _env() -> dict[str, str]:
    return {smoke.SMOKE_ENV: "1"}
