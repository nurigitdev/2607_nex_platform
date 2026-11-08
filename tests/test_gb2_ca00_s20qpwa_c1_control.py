from __future__ import annotations

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
import run_gb2_s20qpwa_c1_control as smoke
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from test_gb2_ca00_s20qpw_sync_capacity import ENDPOINT, REVISION
from test_nex_cx_retrieval_answer_support_sync_capacity_control import (
    _fixtures,
    _profile,
)


def test_control_runner_requires_explicit_idle_confirmation(tmp_path) -> None:
    assert smoke.run_gb2_s20qpwa_c1_control({})["status"] == "SKIPPED"
    assert "=skipped" in smoke.summary_line({"status": "SKIPPED"})
    assert (
        smoke.run_gb2_s20qpwa_c1_control({smoke.SMOKE_ENV: "1"})["failure_code"]
        == "operator_approval_required"
    )
    env = _env()
    env.pop(smoke.IDLE_ENV)
    assert (
        smoke.run_gb2_s20qpwa_c1_control(env)["failure_code"]
        == "dgx_idle_confirmation_required"
    )
    used = tmp_path / "used.json"
    used.write_text("{}", encoding="utf-8")
    assert (
        smoke.run_gb2_s20qpwa_c1_control(_env(), receipt_path=used)["failure_code"]
        == "c1_control_already_consumed"
    )

    invalid = _env()
    invalid.pop("NEX_MO_VLLM_API_KEY")
    assert (
        smoke.run_gb2_s20qpwa_c1_control(
            invalid, receipt_path=tmp_path / "unused.json"
        )["failure_code"]
        == "configuration_invalid"
    )


@pytest.mark.parametrize("collector", [None, object()])
def test_control_runner_executes_exactly_thirty_requests(
    tmp_path, monkeypatch, collector
) -> None:
    fixtures = _fixtures()
    calls = 0

    def requester(_method: str, _url: str, **_kwargs):
        nonlocal calls
        calls += 1
        return object()

    def run_profile(*, concurrency, cases, requester, **_kwargs):
        assert concurrency == 1
        for _case in cases:
            requester("POST", ENDPOINT)
        return _profile(1, "SYNCHRONOUS_LIVE_REPLAY", 11_000.0, 0.09)

    monkeypatch.setattr(smoke, "_run_profile", run_profile)
    monkeypatch.setattr(
        smoke,
        "_provider_binding",
        lambda *_args: {
            "model_revision": REVISION,
            "deployment_id": "dgx-qwen3-5-9b-9116",
        },
    )
    target = tmp_path / "receipt.json"
    result = smoke.run_gb2_s20qpwa_c1_control(
        _env(),
        requester=requester,
        collector=collector,
        port_probe=lambda _host, ports: {str(port): True for port in ports},
        control_design=fixtures["control_design"],
        capacity_design=fixtures["capacity_design"],
        capacity_receipt=fixtures["capacity_receipt"],
        cases_document=fixtures["cases_document"],
        signal_design=fixtures["signal_design"],
        request_profile=fixtures["request_profile"],
        artifact_evidence=fixtures["artifact_evidence"],
        receipt_path=target,
    )
    assert result["status"] == "PASS"
    assert result["provider_http_requests"] == 30
    assert calls == 30
    assert result["execution_mode_selected"] is False
    assert result["causal_concurrency_attribution_permitted"] is False
    assert target.stat().st_mode & 0o777 == 0o600
    assert json.loads(target.read_text())["status"] == "PASS"
    assert "mode_selected=false" in smoke.summary_line(result)


def test_control_runner_fails_closed_before_requests_on_probe_failure(
    tmp_path, monkeypatch
) -> None:
    fixtures = _fixtures()
    monkeypatch.setattr(
        smoke,
        "_provider_binding",
        lambda *_args: {
            "model_revision": REVISION,
            "deployment_id": "dgx-qwen3-5-9b-9116",
        },
    )
    result = smoke.run_gb2_s20qpwa_c1_control(
        _env(),
        requester=lambda *_args, **_kwargs: None,
        port_probe=lambda _host, ports: {str(port): port != 9113 for port in ports},
        control_design=fixtures["control_design"],
        capacity_design=fixtures["capacity_design"],
        capacity_receipt=fixtures["capacity_receipt"],
        cases_document=fixtures["cases_document"],
        signal_design=fixtures["signal_design"],
        request_profile=fixtures["request_profile"],
        artifact_evidence=fixtures["artifact_evidence"],
        receipt_path=tmp_path / "receipt.json",
    )
    assert result["status"] == "FAIL"
    assert result["failure_code"] == "c1_control_observation_failed"
    assert result["provider_http_requests"] == 0
    assert "=fail" in smoke.summary_line(result)


def test_control_runner_rejects_source_drift_and_missing_provider_host(
    tmp_path, monkeypatch
) -> None:
    fixtures = _fixtures()
    monkeypatch.setattr(
        smoke,
        "_provider_binding",
        lambda *_args: {
            "model_revision": REVISION,
            "deployment_id": "dgx-qwen3-5-9b-9116",
        },
    )
    drifted_cases = deepcopy(fixtures["cases_document"])
    drifted_cases["status"] = "DRIFTED"
    result = smoke.run_gb2_s20qpwa_c1_control(
        _env(),
        control_design=fixtures["control_design"],
        capacity_design=fixtures["capacity_design"],
        capacity_receipt=fixtures["capacity_receipt"],
        cases_document=drifted_cases,
        signal_design=fixtures["signal_design"],
        request_profile=fixtures["request_profile"],
        artifact_evidence=fixtures["artifact_evidence"],
        receipt_path=tmp_path / "drift.json",
    )
    assert result["failure_code"] == "c1_control_observation_failed"
    assert result["provider_http_requests"] == 0

    monkeypatch.setattr(
        smoke.remote_provider,
        "build_remote_generation_execution_config",
        lambda _env: SimpleNamespace(url="relative/path"),
    )
    result = smoke.run_gb2_s20qpwa_c1_control(
        _env(),
        control_design=fixtures["control_design"],
        capacity_design=fixtures["capacity_design"],
        capacity_receipt=fixtures["capacity_receipt"],
        cases_document=fixtures["cases_document"],
        signal_design=fixtures["signal_design"],
        request_profile=fixtures["request_profile"],
        artifact_evidence=fixtures["artifact_evidence"],
        receipt_path=tmp_path / "host.json",
    )
    assert result["failure_code"] == "c1_control_observation_failed"


def test_provider_binding_helper_rejects_source_and_hash_drift(monkeypatch) -> None:
    fixtures = _fixtures()
    with pytest.raises(ValueError, match="source binding"):
        smoke._provider_binding(
            fixtures["capacity_design"],
            {**fixtures["capacity_receipt"], "source_binding": {}},
        )

    readiness = {
        "manifest": {
            "candidate_profile": {
                "provider_binding": {
                    "model_revision": REVISION,
                    "deployment_id": "wrong-deployment",
                }
            }
        }
    }
    monkeypatch.setattr(smoke, "_load", lambda _path: readiness)
    with pytest.raises(ValueError, match="provider binding hash"):
        smoke._provider_binding(
            fixtures["capacity_design"], fixtures["capacity_receipt"]
        )

    binding = {
        "model_revision": REVISION,
        "deployment_id": "dgx-qwen3-5-9b-9116",
    }
    fixtures["capacity_design"]["source_binding"]["provider_binding_hash"] = (
        semantic_sha256_hash_ref(binding)
    )
    fixtures["capacity_receipt"]["source_binding"]["provider_binding_hash"] = (
        semantic_sha256_hash_ref(binding)
    )
    monkeypatch.setattr(
        smoke,
        "_load",
        lambda _path: {
            "manifest": {"candidate_profile": {"provider_binding": binding}}
        },
    )
    assert (
        smoke._provider_binding(
            fixtures["capacity_design"], fixtures["capacity_receipt"]
        )
        == binding
    )


def test_control_runner_cli_preserves_terminal_output_on_default_skip(
    tmp_path, monkeypatch, capsys
) -> None:
    output = tmp_path / "output.json"
    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpwa_c1_control",
        lambda: {"status": "PASS", "trailing_control_profile": {}},
    )
    assert smoke.main(["--output", str(output), "--summary"]) == 0
    assert "=pass" in capsys.readouterr().out
    output.write_text('{"status": "PASS"}\n', encoding="utf-8")
    monkeypatch.setattr(
        smoke, "run_gb2_s20qpwa_c1_control", lambda: {"status": "SKIPPED"}
    )
    assert smoke.main(["--output", str(output)]) == 0
    assert json.loads(output.read_text())["status"] == "PASS"
    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpwa_c1_control",
        lambda: {"status": "FAIL", "failure_code": "forced"},
    )
    assert smoke.main(["--output", str(output)]) == 1


def _env() -> dict[str, str]:
    return {
        smoke.SMOKE_ENV: "1",
        smoke.APPROVED_ENV: "1",
        smoke.IDLE_ENV: "1",
        smoke.OPERATOR_ENV: "operator-one",
        "NEX_MO_VLLM_CHAT_COMPLETIONS_URL": ENDPOINT,
        "NEX_MO_VLLM_API_KEY": "secret-key",
        "NEX_MO_VLLM_MODEL": "Qwen3.5-9B",
        "NEX_MO_VLLM_MODEL_REVISION": REVISION,
        "NEX_MO_VLLM_DEPLOYMENT_ID": "dgx-qwen3-5-9b-9116",
    }
