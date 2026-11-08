from __future__ import annotations

import json

import pytest
import run_gb2_s20qpn_fresh_answer_support_collection as smoke

ENDPOINT = "http://provider.test:9116/v1/chat/completions"


def _env() -> dict[str, str]:
    return {
        smoke.SMOKE_ENV: "1",
        "NEX_MO_VLLM_CHAT_COMPLETIONS_URL": ENDPOINT,
        "NEX_MO_VLLM_API_KEY": "test-key",
        "NEX_MO_VLLM_MODEL": "Qwen3.5-9B",
    }


def _binding() -> dict:
    source = json.loads(smoke.P_I_SOURCE_PATH.read_text(encoding="utf-8"))
    return source["collection"]["provider_binding"]


def _normalized(dataset_hash: str) -> dict:
    return {
        "dataset": {
            "dataset_sha256": dataset_hash,
            "package_count": 200,
            "candidate_count": 800,
            "holdout_status": "SEALED_NOT_ACCESSED",
        },
        "provider_binding": _binding(),
        "privacy": {"candidate_truth_persisted": False},
        "safety": {"runtime_activation_permitted": False},
    }


def _collector(cases, *, evaluator, dataset_sha256, **kwargs):
    assert len(cases) == 200
    assert kwargs["request_namespace"] == "s20qpn"
    for index in range(200):
        evaluator({}, f"request-{index}", f"trace-{index}")
    return _normalized(dataset_sha256)


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


def test_skip_profile_and_configuration_guards() -> None:
    assert smoke.run_gb2_s20qpn_fresh_answer_support_collection({})["status"] == (
        "SKIPPED"
    )
    assert smoke.run_gb2_s20qpn_fresh_answer_support_collection(
        {smoke.SMOKE_ENV: "1", smoke.PROFILE_ENV: "prod"}
    )["failure_code"] == "profile_not_allowed"
    result = smoke.run_gb2_s20qpn_fresh_answer_support_collection(
        {smoke.SMOKE_ENV: "1"}
    )
    assert result["failure_code"] == "configuration_invalid"
    assert "generation_endpoint" in result["failure_detail"]


def test_runner_accepts_complete_fresh_provider_collection() -> None:
    result = smoke.run_gb2_s20qpn_fresh_answer_support_collection(
        _env(),
        requester=_requester,
        collector=_collector,
        validator=lambda value: value,
        executor=_executor,
    )

    assert result["status"] == "PASS"
    assert result["provider_evaluation_count"] == 200
    assert result["provider_http_request_counts"] == {
        "total": 200,
        "generation": 200,
    }
    assert "provider_calls=200" in smoke.summary_line(result)


def test_runner_reports_failed_check_and_collection_exception() -> None:
    def incomplete(cases, *, dataset_sha256, **kwargs):
        value = _normalized(dataset_sha256)
        value["dataset"]["package_count"] = 199
        return value

    result = smoke.run_gb2_s20qpn_fresh_answer_support_collection(
        _env(),
        requester=_requester,
        collector=incomplete,
        validator=lambda value: value,
        executor=_executor,
    )
    assert result["status"] == "FAIL"
    assert "package_count_complete" in result["failed_checks"]

    result = smoke.run_gb2_s20qpn_fresh_answer_support_collection(
        _env(),
        requester=_requester,
        collector=lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError()),
    )
    assert result["failure_code"] == "fresh_collection_failed"
    assert result["failure_detail"] == {"exception": "ValueError"}


def test_runner_rejects_p_m_and_p_i_binding_drift(tmp_path) -> None:
    for source_path, env_key in (
        (smoke.P_M_SOURCE_PATH, smoke.P_M_SOURCE_ENV),
        (smoke.P_I_SOURCE_PATH, smoke.P_I_SOURCE_ENV),
    ):
        source = json.loads(source_path.read_text(encoding="utf-8"))
        source["status"] = "FAIL"
        changed = tmp_path / source_path.name
        changed.write_text(json.dumps(source), encoding="utf-8")
        env = {**_env(), env_key: str(changed)}
        result = smoke.run_gb2_s20qpn_fresh_answer_support_collection(env)
        assert result["failure_code"] == "fresh_collection_failed"
        assert result["failure_detail"] == {"exception": "ValueError"}


def test_provider_binding_and_primitive_guards(tmp_path, monkeypatch, capsys) -> None:
    binding = _binding()
    env = _env()
    env["NEX_MO_VLLM_MODEL_REVISION"] = "hf:" + "0" * 40
    with pytest.raises(ValueError, match="revision"):
        smoke._bind_effective_provider(env, binding, binding["model_revision"])
    env = _env()
    env["NEX_MO_VLLM_DEPLOYMENT_ID"] = "other"
    with pytest.raises(ValueError, match="deployment"):
        smoke._bind_effective_provider(env, binding, binding["model_revision"])
    assert smoke._configuration_issues(
        {
            "NEX_MO_VLLM_BASE_URL": "http://provider.test:9116",
            "NEX_MO_VLLM_API_KEY": "key",
            "NEX_MO_VLLM_MODEL": "model",
        }
    ) == []

    guarded, counts = smoke._counting_requester(
        lambda *_args, **_kwargs: object(), environ=_env()
    )
    guarded("POST", "http://not-generation.test", json={})
    assert counts == {"total": 1, "generation": 0}

    invalid = tmp_path / "invalid.json"
    invalid.write_text("[]", encoding="utf-8")
    with pytest.raises(TypeError, match="object"):
        smoke._load(invalid)
    with pytest.raises(TypeError, match="mapping"):
        smoke._mapping([], "mapping")
    with pytest.raises(ValueError, match="text"):
        smoke._required_text(" ", "text")
    assert "=skipped" in smoke.summary_line({"status": "SKIPPED"})
    assert "bad" in smoke.summary_line(
        {"status": "FAIL", "failure_code": "bad"}
    )

    output = tmp_path / "output.json"
    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpn_fresh_answer_support_collection",
        lambda: {"status": "PASS", "collection": {}},
    )
    assert smoke.main(["--output", str(output), "--summary"]) == 0
    assert '"status": "PASS"' in output.read_text()
    assert "=pass" in capsys.readouterr().out


def test_redaction_rejects_secret_and_source_text() -> None:
    env = {"NEX_MO_VLLM_API_KEY": "secret-value"}
    with pytest.raises(ValueError, match="protected"):
        smoke._assert_redacted({"leak": "secret-value"}, env)
    dataset = {"cases": [{"query": "private query", "candidates": []}]}
    with pytest.raises(ValueError, match="protected"):
        smoke._assert_redacted({"leak": "private query"}, {}, dataset=dataset)
