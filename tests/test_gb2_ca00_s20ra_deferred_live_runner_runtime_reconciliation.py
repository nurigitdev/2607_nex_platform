from __future__ import annotations

import json

import pytest
import run_gb2_s20ra_deferred_live_runner_runtime_reconciliation as smoke
from test_nex_cx_retrieval_deferred_live_runner_reconciliation import (
    _s136,
    _s137,
)


def _env(**overrides: str) -> dict[str, str]:
    return {
        smoke.SMOKE_ENV: "1",
        smoke.PROFILE_ENV: "test",
        smoke.LIVE_ENV: "1",
        "NEX_CX_TEST_DATABASE_URL": "cx-db-secret",
        "NEX_AE_TEST_DATABASE_URL": "ae-db-secret",
        "NEX_MO_REMOTE_EMBEDDING_URL": "http://embedding.invalid/v1/embeddings",
        "NEX_MO_REMOTE_EMBEDDING_API_KEY": "embedding-secret",
        "NEX_MO_REMOTE_RERANKER_URL": "http://reranker.invalid/v1/rerank",
        "NEX_MO_REMOTE_RERANKER_API_KEY": "reranker-secret",
        "NEX_MO_VLLM_BASE_URL": "http://generation.invalid",
        "NEX_MO_VLLM_API_KEY": "generation-secret",
        **overrides,
    }


def test_runner_is_opt_in_test_only_and_can_freeze_without_live() -> None:
    skipped = smoke.run_gb2_s20ra_deferred_live_runner_runtime_reconciliation({})
    blocked = smoke.run_gb2_s20ra_deferred_live_runner_runtime_reconciliation(
        _env(**{smoke.PROFILE_ENV: "dev"})
    )
    ready = smoke.run_gb2_s20ra_deferred_live_runner_runtime_reconciliation(
        {smoke.SMOKE_ENV: "1", smoke.PROFILE_ENV: "test"}
    )

    assert skipped["status"] == "SKIPPED"
    assert blocked["failure_code"] == "profile_not_allowed"
    assert ready["status"] == "READY"
    assert ready["provider_binding"]["generation"]["model"] == "Qwen3.5-9B"


def test_runner_executes_current_replays_in_dependency_order() -> None:
    calls: list[tuple[str, dict[str, str]]] = []

    result = smoke.run_gb2_s20ra_deferred_live_runner_runtime_reconciliation(
        _env(),
        s136_runner=lambda env: calls.append(("S136", dict(env))) or _s136(),
        s137_runner=lambda env: calls.append(("S137", dict(env))) or _s137(),
    )

    assert result["status"] == "PASS"
    assert result["failed_checks"] == []
    assert [name for name, _ in calls] == ["S136", "S137"]
    assert calls[0][1]["NEX_MO_VLLM_MODEL"] == "Qwen3.5-9B"
    assert calls[1][1]["NEX_MO_VLLM_MODEL_REVISION"] == (
        "hf:c202236235762e1c871ad0ccb60c8ee5ba337b9a"
    )
    assert calls[1][1]["NEX_MO_VLLM_DEPLOYMENT_ID"] == (
        "dgx-qwen3-5-9b-9116"
    )
    assert calls[1][1]["NEX_CX_ANSWER_SUPPORT_STEADY_STATE_MODE"] == (
        "CONTROLLED"
    )


def test_runner_fails_before_s137_when_s136_fails() -> None:
    calls: list[str] = []
    result = smoke.run_gb2_s20ra_deferred_live_runner_runtime_reconciliation(
        _env(),
        s136_runner=lambda _env: {
            "status": "FAIL",
            "failure_code": "repeatability",
            "failed_checks": ["vector"],
        },
        s137_runner=lambda _env: calls.append("S137") or _s137(),
    )

    assert result["failure_code"] == "s136_current_replay_failed"
    assert result["source_status"]["failed_check_count"] == 1
    assert calls == []


def test_runner_reuses_fresh_s136_evidence_after_restart(
    monkeypatch, tmp_path
) -> None:
    live_root = tmp_path / "reports" / "live"
    live_root.mkdir(parents=True)
    evidence_path = live_root / "s136.json"
    evidence_path.write_text(json.dumps(_s136()), encoding="utf-8")
    monkeypatch.setattr(smoke, "ROOT", tmp_path)

    result = smoke.run_gb2_s20ra_deferred_live_runner_runtime_reconciliation(
        _env(**{smoke.S136_EVIDENCE_PATH_ENV: str(evidence_path)}),
        s136_runner=lambda _env: (_ for _ in ()).throw(
            AssertionError("fresh S136 evidence must be reused")
        ),
        s137_runner=lambda _env: _s137(),
    )

    assert result["status"] == "PASS"
    assert result["source_status"]["s136"]["failed_checks"] == []


def test_s136_replay_evidence_path_is_owner_scoped_to_reports_live(
    tmp_path,
) -> None:
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError):
        smoke._load_replay_evidence(outside)


def test_runner_requires_complete_protected_configuration() -> None:
    result = smoke.run_gb2_s20ra_deferred_live_runner_runtime_reconciliation(
        {
            smoke.SMOKE_ENV: "1",
            smoke.PROFILE_ENV: "test",
            smoke.LIVE_ENV: "1",
        }
    )

    assert result["failure_code"] == "protected_configuration_incomplete"
    assert set(result["detail"]) == set(smoke.PROTECTED_ENV_KEYS)


def test_runner_preserves_safe_contract_error_code(monkeypatch) -> None:
    class ContractError(ValueError):
        error_code = "contract.field_invalid"
        detail = "Invalid contract field: safe_field."

    monkeypatch.setattr(
        smoke,
        "evaluate_deferred_live_runner_replay",
        lambda **_kwargs: (_ for _ in ()).throw(ContractError()),
    )

    result = smoke.run_gb2_s20ra_deferred_live_runner_runtime_reconciliation(
        _env(),
        s136_runner=lambda _env: _s136(),
        s137_runner=lambda _env: _s137(),
    )

    assert result["failure_code"] == "live_replay_execution_failed"
    assert result["detail"] == "contract.field_invalid"
    assert result["contract_error_detail"] == "Invalid contract field: safe_field."
    assert result["source_status"]["s137"]["status"] == "PASS"


def test_runner_redaction_summary_and_cli(monkeypatch, tmp_path, capsys) -> None:
    passing = smoke.run_gb2_s20ra_deferred_live_runner_runtime_reconciliation(
        _env(),
        s136_runner=lambda _env: _s136(),
        s137_runner=lambda _env: _s137(),
    )
    serialized = json.dumps(passing)
    assert "generation-secret" not in serialized
    assert "generation.invalid" not in serialized
    assert "qwen35=9b" in smoke.summary_line(passing)
    assert "live=not_requested" in smoke.summary_line({"status": "READY"})
    assert "skipped" in smoke.summary_line({"status": "SKIPPED"})
    assert "code=broken" in smoke.summary_line(
        {"status": "FAIL", "failure_code": "broken"}
    )
    with pytest.raises(AssertionError):
        smoke._assert_redacted({"value": "generation-secret"}, _env())

    output = tmp_path / "evidence.json"
    monkeypatch.setattr(
        smoke,
        "run_gb2_s20ra_deferred_live_runner_runtime_reconciliation",
        lambda: passing,
    )
    assert smoke.main(["--output", str(output), "--summary"]) == 0
    assert "qwen35=9b" in capsys.readouterr().out
    assert output.stat().st_mode & 0o777 == 0o600
