from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path

import pytest
import run_gb2_s20qpq_one_shot_holdout as smoke

ENDPOINT = "http://provider.test:9116/v1/chat/completions"


def _env(receipt: Path) -> dict[str, str]:
    return {
        smoke.SMOKE_ENV: "1",
        smoke.RECEIPT_PATH_ENV: str(receipt),
        "NEX_MO_VLLM_CHAT_COMPLETIONS_URL": ENDPOINT,
        "NEX_MO_VLLM_API_KEY": "test-key",
        "NEX_MO_VLLM_MODEL": "Qwen3.5-9B",
        "NEX_MO_VLLM_MODEL_REVISION": (
            "hf:c202236235762e1c871ad0ccb60c8ee5ba337b9a"
        ),
        "NEX_MO_VLLM_DEPLOYMENT_ID": "dgx-qwen3-5-9b-9116",
    }


def _collection(_cases, *, evaluator, **kwargs):
    for index in range(40):
        evaluator({}, f"request-{index}", f"trace-{index}")
    return {
        "dataset": {"package_count": 40, "candidate_count": 160},
        "collection_hash": "sha256:" + "1" * 64,
    }


def _executor(payload, *, request_id, trace_id, environ, requester):
    assert request_id.startswith("request-")
    assert trace_id.startswith("trace-")
    requester("POST", environ["NEX_MO_VLLM_CHAT_COMPLETIONS_URL"], json=payload)
    return {}


def _requester(method, url, **kwargs):
    assert method == "POST"
    assert url == ENDPOINT
    assert "json" in kwargs
    return object()


def _evaluation(status="PASS") -> dict:
    return {
        "status": "HOLDOUT_ADMITTED" if status == "PASS" else "HOLDOUT_REJECTED",
        "terminal_status": status,
        "evaluation_hash": "sha256:" + "2" * 64,
        "metrics": {"false_ready_rate": 0.0, "ready_recall": 1.0},
        "package_auc": 1.0,
        "threshold_reselected": False,
        "profile_reselected": False,
        "runtime_activation_permitted": False,
    }


def test_runner_executes_one_shot_and_persists_terminal_receipt(tmp_path) -> None:
    receipt = tmp_path / "receipt.json"
    times = iter(("start", "complete"))
    result = smoke.run_gb2_s20qpq_one_shot_holdout(
        _env(receipt),
        requester=_requester,
        collector=_collection,
        evaluator=lambda *_args, **_kwargs: _evaluation(),
        executor=_executor,
        clock=lambda: next(times),
    )

    persisted = json.loads(receipt.read_text(encoding="utf-8"))
    assert result["status"] == "PASS"
    assert result["decision"].endswith("SEPARATE_ACTIVATION_REQUIRED")
    assert result["provider_evaluation_count"] == 40
    assert result["provider_http_request_counts"] == {
        "total": 40,
        "generation": 40,
    }
    assert persisted["status"] == "PASS"
    assert oct(receipt.stat().st_mode & 0o777) == "0o600"
    assert "authorization=consumed" in smoke.summary_line(result)


def test_runner_records_complete_rejection_without_execution_retry(tmp_path) -> None:
    receipt = tmp_path / "receipt.json"
    result = smoke.run_gb2_s20qpq_one_shot_holdout(
        _env(receipt),
        requester=_requester,
        collector=_collection,
        evaluator=lambda *_args, **_kwargs: _evaluation("FAIL"),
        executor=_executor,
        clock=lambda: "now",
    )

    assert result["status"] == "PASS"
    assert result["decision"] == "HOLDOUT_EXECUTED_CANDIDATE_REJECTED"
    assert json.loads(receipt.read_text())["status"] == "FAIL"
    replay = smoke.run_gb2_s20qpq_one_shot_holdout(_env(receipt))
    assert replay["failure_code"] == "one_shot_authorization_already_consumed"


def test_post_reservation_failure_is_terminal_inconclusive(tmp_path) -> None:
    receipt = tmp_path / "receipt.json"

    def broken(_cases, *, evaluator, **kwargs):
        evaluator({}, "request-1", "trace-1")
        raise ValueError("provider output invalid")

    result = smoke.run_gb2_s20qpq_one_shot_holdout(
        _env(receipt),
        requester=_requester,
        collector=broken,
        executor=_executor,
        clock=lambda: "now",
    )

    persisted = json.loads(receipt.read_text())
    assert result["status"] == "FAIL"
    assert result["decision"] == "HOLDOUT_INCONCLUSIVE_AUTHORIZATION_CONSUMED"
    assert persisted["status"] == "INCONCLUSIVE"
    assert persisted["terminal_reason"] == "ValueError"
    assert persisted["provider_http_request_count"] == 1


def test_provider_evaluation_budget_overflow_is_consumed(tmp_path) -> None:
    receipt = tmp_path / "receipt.json"

    def overflow(_cases, *, evaluator, **kwargs):
        for index in range(41):
            evaluator({}, f"request-{index}", f"trace-{index}")
        raise AssertionError("unreachable")

    result = smoke.run_gb2_s20qpq_one_shot_holdout(
        _env(receipt),
        requester=_requester,
        collector=overflow,
        executor=_executor,
        clock=lambda: "now",
    )

    assert result["decision"] == "HOLDOUT_INCONCLUSIVE_AUTHORIZATION_CONSUMED"
    assert result["provider_evaluation_count"] == 40
    assert result["provider_http_request_counts"]["generation"] == 40
    assert json.loads(receipt.read_text())["status"] == "INCONCLUSIVE"


def test_skip_profile_configuration_and_existing_receipt_guards(tmp_path) -> None:
    assert smoke.run_gb2_s20qpq_one_shot_holdout({})["status"] == "SKIPPED"
    result = smoke.run_gb2_s20qpq_one_shot_holdout(
        {smoke.SMOKE_ENV: "1", smoke.PROFILE_ENV: "prod"}
    )
    assert result["failure_code"] == "profile_not_allowed"
    result = smoke.run_gb2_s20qpq_one_shot_holdout({smoke.SMOKE_ENV: "1"})
    assert result["failure_code"] == "configuration_invalid"
    receipt = tmp_path / "receipt.json"
    receipt.write_text("{}")
    result = smoke.run_gb2_s20qpq_one_shot_holdout(_env(receipt))
    assert result["failure_code"] == "one_shot_authorization_already_consumed"


def test_pre_execution_and_reservation_failures_do_not_call_provider(
    tmp_path, monkeypatch
) -> None:
    receipt = tmp_path / "receipt.json"
    monkeypatch.setattr(
        smoke,
        "_load_execution_context",
        lambda _env: (_ for _ in ()).throw(ValueError("drift")),
    )
    result = smoke.run_gb2_s20qpq_one_shot_holdout(_env(receipt))
    assert result["failure_code"] == "pre_execution_admission_failed"
    assert not receipt.exists()

    monkeypatch.undo()

    def exists(_path, _value):
        raise FileExistsError

    result = smoke.run_gb2_s20qpq_one_shot_holdout(
        _env(receipt), reservation_writer=exists
    )
    assert result["failure_code"] == "one_shot_authorization_already_consumed"


def test_provider_binding_configuration_and_budget_guards(tmp_path) -> None:
    binding = {
        "model_revision": "hf:" + "1" * 40,
        "deployment_id": "deployment",
    }
    env = {"NEX_MO_VLLM_MODEL_REVISION": "hf:" + "2" * 40}
    with pytest.raises(ValueError, match="revision"):
        smoke._bind_effective_provider(env, binding)
    env = {"NEX_MO_VLLM_DEPLOYMENT_ID": "other"}
    with pytest.raises(ValueError, match="deployment"):
        smoke._bind_effective_provider(env, binding)

    counts = {"total": 0, "generation": 0}
    guarded = smoke._budgeted_requester(
        _requester,
        environ=_env(tmp_path / "receipt"),
        counts=counts,
        maximum_requests=1,
    )
    guarded("POST", ENDPOINT, json={})
    with pytest.raises(ValueError, match="budget"):
        guarded("POST", ENDPOINT, json={})
    other_counts = {"total": 0, "generation": 0}
    guarded = smoke._budgeted_requester(
        _requester,
        environ=_env(tmp_path / "receipt"),
        counts=other_counts,
        maximum_requests=1,
    )
    with pytest.raises(ValueError, match="unbound"):
        guarded("POST", "http://other", json={})
    assert other_counts == {"total": 0, "generation": 0}


def test_atomic_receipt_writers_and_helpers(tmp_path, monkeypatch, capsys) -> None:
    path = tmp_path / "nested" / "receipt.json"
    smoke._write_exclusive_json(path, {"status": "STARTED"})
    with pytest.raises(FileExistsError):
        smoke._write_exclusive_json(path, {"status": "STARTED"})
    smoke._replace_json(path, {"status": "PASS"})
    assert json.loads(path.read_text()) == {"status": "PASS"}

    invalid = tmp_path / "invalid.json"
    invalid.write_text("[]")
    with pytest.raises(TypeError, match="object"):
        smoke._load(invalid)
    with pytest.raises(TypeError, match="mapping"):
        smoke._mapping([], "mapping")
    with pytest.raises(ValueError, match="name"):
        smoke._required_text(" ", "name")
    assert "=skipped" in smoke.summary_line({"status": "SKIPPED"})
    assert "bad" in smoke.summary_line({"status": "FAIL", "failure_code": "bad"})

    output = tmp_path / "output.json"
    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpq_one_shot_holdout",
        lambda: {"status": "PASS", "evaluation": {}},
    )
    assert smoke.main(["--output", str(output), "--summary"]) == 0
    assert "\"status\": \"PASS\"" in output.read_text()
    assert "=pass" in capsys.readouterr().out


def test_redaction_rejects_secret_and_holdout_text() -> None:
    smoke._assert_redacted({"safe": True}, {})
    smoke._assert_redacted({"safe": True}, {}, dataset={"cases": "invalid"})
    with pytest.raises(ValueError, match="protected"):
        smoke._assert_redacted(
            {"leak": "secret-value"}, {"NEX_MO_VLLM_API_KEY": "secret-value"}
        )
    with pytest.raises(ValueError, match="protected"):
        smoke._assert_redacted(
            {"leak": "private query"},
            {},
            dataset={"cases": [{"query": "private query", "candidates": []}]},
        )


def test_exclusive_writer_removes_partial_file_on_serialization_failure(
    tmp_path,
) -> None:
    path = tmp_path / "receipt.json"
    with pytest.raises(TypeError):
        smoke._write_exclusive_json(path, {"bad": object()})
    assert not path.exists()


def test_configuration_rejects_retry_override() -> None:
    env = {
        "NEX_MO_VLLM_BASE_URL": "http://provider",
        "NEX_MO_VLLM_API_KEY": "key",
        "NEX_MO_VLLM_MODEL": "model",
        "NEX_MO_GENERATION_MAX_ATTEMPTS": "2",
    }
    assert "NEX_MO_GENERATION_MAX_ATTEMPTS" in smoke._configuration_issues(env)


def test_replace_writer_preserves_original_when_replace_fails(
    tmp_path, monkeypatch
) -> None:
    path = tmp_path / "receipt.json"
    path.write_text('{"status":"STARTED"}')
    monkeypatch.setattr(os, "replace", lambda *_args: (_ for _ in ()).throw(OSError()))
    with pytest.raises(OSError):
        smoke._replace_json(path, {"status": "PASS"})
    assert json.loads(path.read_text())["status"] == "STARTED"


def test_execution_context_rejects_every_frozen_source_drift(monkeypatch) -> None:
    original = smoke._load

    def assert_drift(path, mutate, match):
        def changed(candidate):
            value = deepcopy(original(candidate))
            if candidate == path:
                mutate(value)
            return value

        monkeypatch.setattr(smoke, "_load", changed)
        with pytest.raises((TypeError, ValueError), match=match):
            smoke._load_execution_context({})
        monkeypatch.setattr(smoke, "_load", original)

    assert_drift(
        smoke.P_P_SOURCE_PATH,
        lambda value: value.update(status="FAIL"),
        "not admitted",
    )
    assert_drift(
        smoke.P_P_SOURCE_PATH,
        lambda value: value["freeze"].update(runtime_activation_permitted=True),
        "binding drifted",
    )
    assert_drift(
        smoke.P_L_SOURCE_PATH,
        lambda value: value["freeze"]["canonical_profile"].update(
            profile_hash="sha256:" + "0" * 64
        ),
        "profile hash drifted",
    )
    assert_drift(
        smoke.DEFAULT_DATASET_PATH,
        lambda value: value.update(cases="invalid"),
        "cases are invalid",
    )
    assert_drift(
        smoke.DEFAULT_DATASET_PATH,
        lambda value: value["cases"].pop(),
        "scope drifted",
    )
