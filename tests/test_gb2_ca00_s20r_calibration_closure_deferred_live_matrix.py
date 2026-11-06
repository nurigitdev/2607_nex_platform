from __future__ import annotations

import json

import pytest

import run_gb2_s20r_calibration_closure_deferred_live_matrix as smoke
from test_nex_runtime_calibration_deferred_live_matrix import (
    _s140,
    _s147,
    _s149,
    _s150,
)


def _env(**overrides: str) -> dict[str, str]:
    values = {
        smoke.SMOKE_ENV: "1",
        smoke.PROFILE_ENV: "test",
        smoke.LIVE_ENV: "1",
        "NEX_MO_REMOTE_EMBEDDING_URL": "http://embedding.invalid/v1/embeddings",
        "NEX_MO_REMOTE_EMBEDDING_API_KEY": "embedding-secret",
        "NEX_MO_REMOTE_RERANKER_URL": "http://reranker.invalid/v1/rerank",
        "NEX_MO_REMOTE_RERANKER_API_KEY": "reranker-secret",
        "NEX_MO_VLLM_BASE_URL": "http://generation.invalid",
        "NEX_MO_VLLM_API_KEY": "generation-secret",
    }
    for service in ("OA", "AG", "AE", "CX", "MO", "WC", "EOS"):
        values[f"NEX_{service}_TEST_DATABASE_URL"] = f"{service.lower()}-test-secret"
        values[f"NEX_{service}_DATABASE_URL"] = f"{service.lower()}-dev-secret"
    values.update(overrides)
    return values


def test_runner_is_opt_in_test_only_and_can_freeze_without_live() -> None:
    skipped = smoke.run_gb2_s20r_calibration_closure_deferred_live_matrix({})
    blocked = smoke.run_gb2_s20r_calibration_closure_deferred_live_matrix(
        _env(**{smoke.PROFILE_ENV: "dev"})
    )
    ready = smoke.run_gb2_s20r_calibration_closure_deferred_live_matrix(
        {smoke.SMOKE_ENV: "1", smoke.PROFILE_ENV: "test"}
    )

    assert skipped["status"] == "SKIPPED"
    assert blocked["failure_code"] == "profile_not_allowed"
    assert ready["status"] == "READY"
    assert ready["provider_binding"]["generation"]["model"] == "Qwen3.5-9B"


def test_runner_executes_remaining_stages_in_dependency_order() -> None:
    calls: list[tuple[str, dict[str, str]]] = []

    result = smoke.run_gb2_s20r_calibration_closure_deferred_live_matrix(
        _env(),
        s140_runner=lambda env: calls.append(("S140", dict(env))) or _s140(),
        s147_runner=lambda env: calls.append(("S147", dict(env))) or _s147(),
        s149_runner=lambda env: calls.append(("S149", dict(env))) or _s149(),
        s150_runner=lambda env: calls.append(("S150", dict(env))) or _s150(),
    )

    assert result["status"] == "PASS"
    assert [stage for stage, _ in calls] == ["S140", "S147", "S149", "S150"]
    assert calls[0][1]["NEX_MO_VLLM_MODEL"] == "Qwen3.5-9B"
    assert calls[2][1]["NEX_MO_VLLM_MODEL_REVISION"].startswith("hf:")
    assert calls[2][1]["NEX_MO_VLLM_DEPLOYMENT_ID"] == "dgx-qwen3-5-9b-9116"
    assert result["holdout_reexecuted"] is False


def test_runner_stops_at_first_failed_stage_and_redacts() -> None:
    calls: list[str] = []
    result = smoke.run_gb2_s20r_calibration_closure_deferred_live_matrix(
        _env(),
        s140_runner=lambda _env: {"status": "FAIL", "failure_code": "bounded"},
        s147_runner=lambda _env: calls.append("S147") or _s147(),
        s149_runner=lambda _env: calls.append("S149") or _s149(),
        s150_runner=lambda _env: calls.append("S150") or _s150(),
    )

    assert result["failure_code"] == "s140_current_replay_failed"
    assert calls == []
    assert "generation-secret" not in json.dumps(result)


def test_runner_requires_complete_protected_configuration() -> None:
    result = smoke.run_gb2_s20r_calibration_closure_deferred_live_matrix(
        {smoke.SMOKE_ENV: "1", smoke.PROFILE_ENV: "test", smoke.LIVE_ENV: "1"}
    )

    assert result["failure_code"] == "protected_configuration_incomplete"
    assert set(result["detail"]) == set(smoke.PROTECTED_ENV_KEYS)


def test_runner_rejects_invalid_source_contract(monkeypatch, tmp_path) -> None:
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(smoke, "DESIGN_PATH", invalid)

    result = smoke.run_gb2_s20r_calibration_closure_deferred_live_matrix(
        {smoke.SMOKE_ENV: "1"}
    )

    assert result["failure_code"] == "source_contract_invalid"
    assert result["detail"] == "CalibrationDeferredLiveMatrixError"


def test_default_stage_adapters_activate_current_runners(monkeypatch) -> None:
    observed: dict[str, object] = {}
    monkeypatch.setattr(
        smoke.s140_current,
        "run_platform_release_candidate_protected_matrix",
        lambda env: (observed.__setitem__("s140", dict(env)), _s140())[1],
    )
    monkeypatch.setattr(
        smoke.s147_current,
        "run_s147_model_rollout_live_acceptance",
        lambda env: (observed.__setitem__("s147", dict(env)), _s147())[1],
    )
    monkeypatch.setattr(
        smoke.s149_current,
        "run_installed_current_platform_continuity",
        lambda env, *, execute: (observed.__setitem__("s149", execute), _s149())[1],
    )
    monkeypatch.setattr(
        smoke.s150_current,
        "run_gb2_ca00_s19_fail_closed_restart_acceptance",
        lambda env, *, execute: (observed.__setitem__("s150", execute), _s150())[1],
    )

    assert smoke._run_s140({}) == _s140()
    assert smoke._run_s147({}) == _s147()
    assert smoke._run_s149({}) == _s149()
    assert smoke._run_s150({}) == _s150()
    assert observed["s140"][smoke.s140_current.ENABLE_ENV] == "1"
    assert observed["s147"][smoke.s147_current.PROFILE_ENV] == "test"
    assert observed["s149"] is True
    assert observed["s150"] is True


def test_json_loader_rejects_non_object(tmp_path) -> None:
    path = tmp_path / "list.json"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(TypeError):
        smoke._load_json(path)


def test_runner_contains_exceptions_and_cli_writes_private_evidence(
    monkeypatch, tmp_path, capsys
) -> None:
    failed = smoke.run_gb2_s20r_calibration_closure_deferred_live_matrix(
        _env(),
        s140_runner=lambda _env: _s140(),
        s147_runner=lambda _env: (_ for _ in ()).throw(RuntimeError("secret detail")),
        s149_runner=lambda _env: _s149(),
        s150_runner=lambda _env: _s150(),
    )
    assert failed["failure_code"] == "deferred_live_matrix_execution_failed"
    assert failed["detail"] == "RuntimeError"

    passing = smoke.run_gb2_s20r_calibration_closure_deferred_live_matrix(
        _env(),
        s140_runner=lambda _env: _s140(),
        s147_runner=lambda _env: _s147(),
        s149_runner=lambda _env: _s149(),
        s150_runner=lambda _env: _s150(),
    )
    output = tmp_path / "evidence.json"
    monkeypatch.setattr(
        smoke,
        "run_gb2_s20r_calibration_closure_deferred_live_matrix",
        lambda: passing,
    )
    assert smoke.main(["--output", str(output), "--summary"]) == 0
    assert "next=full_gate" in capsys.readouterr().out
    assert output.stat().st_mode & 0o777 == 0o600

    with pytest.raises(AssertionError):
        smoke._assert_redacted({"value": "generation-secret"}, _env())
    assert "skipped" in smoke.summary_line({"status": "SKIPPED"})
    assert "ready" in smoke.summary_line({"status": "READY"})
    assert "code=broken" in smoke.summary_line(
        {"status": "FAIL", "failure_code": "broken"}
    )


def test_cli_failure_writes_evidence_and_returns_nonzero(
    monkeypatch, tmp_path
) -> None:
    output = tmp_path / "failed.json"
    monkeypatch.setattr(
        smoke,
        "run_gb2_s20r_calibration_closure_deferred_live_matrix",
        lambda: {"status": "FAIL", "failure_code": "bounded"},
    )

    assert smoke.main(["--output", str(output)]) == 1
    assert json.loads(output.read_text(encoding="utf-8"))["failure_code"] == "bounded"
