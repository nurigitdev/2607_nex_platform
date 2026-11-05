from __future__ import annotations

import json
import time
from copy import deepcopy
from pathlib import Path
from threading import Lock

import httpx
import run_gb2_s20qpw_sync_capacity as smoke
from nex_cx.retrieval_answer_support_sync_capacity import (
    validate_sync_capacity_design,
)
from nex_runtime.model_artifact_revision import model_artifact_revision_evidence_digest
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from test_gb2_ca00_s20qpt_shadow_canary_operations import (
    ENDPOINT,
    REVISION,
    _artifact,
)
from test_gb2_ca00_s20qpt_shadow_canary_operations import (
    _fixtures as shadow_fixtures,
)

ROOT = Path(__file__).resolve().parents[1]


def test_protected_sync_capacity_characterizes_concurrency_two_and_four(
    tmp_path,
) -> None:
    fixtures = _runner_fixtures()
    active = 0
    peak_active = 0
    calls = 0
    lock = Lock()

    def requester(method: str, url: str, **kwargs):
        nonlocal active, peak_active, calls
        with lock:
            active += 1
            calls += 1
            peak_active = max(peak_active, active)
        try:
            time.sleep(0.002)
            request = json.loads(kwargs["json"]["messages"][1]["content"])
            items = [
                {
                    "candidate_id": row["candidate_id"],
                    "classification": "SUPPORTING_EVIDENCE",
                    "answer_support_score": 0.9,
                    "contradiction_score": 0.05,
                }
                for row in request["candidates"]
            ]
            return httpx.Response(
                200,
                json={
                    "id": f"completion-{calls}",
                    "model": "Qwen3.5-9B",
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": json.dumps({"items": items}),
                            },
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 20,
                        "completion_tokens": 10,
                        "total_tokens": 30,
                    },
                },
                request=httpx.Request(method, url),
            )
        finally:
            with lock:
                active -= 1

    target = tmp_path / "receipt.json"
    result = smoke.run_gb2_s20qpw_sync_capacity(
        _env(),
        requester=requester,
        port_probe=lambda _host, ports: {str(port): True for port in ports},
        receipt_path=target,
        **fixtures,
    )

    assert result["status"] == "PASS"
    assert result["provider_http_requests"] == 60
    assert [row["concurrency"] for row in result["profile_assessments"]] == [
        1,
        2,
        4,
    ]
    assert result["recommended_synchronous_concurrency"] in {2, 4}
    assert result["execution_mode_selected"] is False
    assert result["runtime_activation_permitted"] is False
    assert result["production_cutover_permitted"] is False
    assert calls == 60
    assert peak_active >= 2
    assert target.stat().st_mode & 0o777 == 0o600
    terminal = json.loads(target.read_text())
    assert terminal["status"] == "PASS"
    assert terminal["provider_http_requests"] == 60
    serialized = json.dumps(result, ensure_ascii=False)
    assert "provider.test" not in serialized
    assert "secret-key" not in serialized
    assert "mode_selected=false" in smoke.summary_line(result)


def test_runner_requires_enablement_approval_configuration_and_one_shot(
    tmp_path,
) -> None:
    assert smoke.run_gb2_s20qpw_sync_capacity({})["status"] == "SKIPPED"
    assert smoke.summary_line({"status": "SKIPPED"}).endswith("=skipped")
    assert (
        smoke.run_gb2_s20qpw_sync_capacity({smoke.SMOKE_ENV: "1"})["failure_code"]
        == "operator_approval_required"
    )
    assert (
        smoke.run_gb2_s20qpw_sync_capacity(
            {
                smoke.SMOKE_ENV: "1",
                smoke.APPROVED_ENV: "1",
                smoke.OPERATOR_ENV: "operator",
            }
        )["failure_code"]
        == "configuration_invalid"
    )

    used = tmp_path / "used.json"
    used.write_text("{}", encoding="utf-8")
    assert (
        smoke.run_gb2_s20qpw_sync_capacity(_env(), receipt_path=used)["failure_code"]
        == "capacity_observation_already_consumed"
    )


def test_runner_fails_before_provider_when_co_resident_probe_is_incomplete(
    tmp_path,
) -> None:
    fixtures = _runner_fixtures()
    result = smoke.run_gb2_s20qpw_sync_capacity(
        _env(),
        requester=lambda *_args, **_kwargs: None,
        port_probe=lambda _host, ports: {str(port): port != 9112 for port in ports},
        receipt_path=tmp_path / "receipt.json",
        **fixtures,
    )

    assert result["status"] == "FAIL"
    assert result["failure_code"] == "sync_capacity_observation_failed"
    assert result["provider_http_requests"] == 0
    assert result["failure_detail"] == {"exception": "ValueError"}
    assert "sync_capacity_observation_failed" in smoke.summary_line(result)


def test_runner_rejects_provider_binding_drift_without_http_calls(tmp_path) -> None:
    fixtures = _runner_fixtures()
    env = _env()
    env["NEX_MO_VLLM_MODEL_REVISION"] = "hf:" + "0" * 40
    result = smoke.run_gb2_s20qpw_sync_capacity(
        env,
        requester=lambda *_args, **_kwargs: None,
        port_probe=lambda _host, ports: {str(port): True for port in ports},
        receipt_path=tmp_path / "receipt.json",
        **fixtures,
    )
    assert result["status"] == "FAIL"
    assert result["provider_http_requests"] == 0


def test_runner_helpers_reject_invalid_cases_timestamps_and_redaction() -> None:
    cases = _load(
        "scripts/smoke/data/s136_answer_support_extended_shadow_v1_cases.json"
    )
    assert len(smoke._capacity_cases(cases)) == 30
    invalid = deepcopy(cases)
    invalid["cases"] = []
    try:
        smoke._capacity_cases(invalid)
    except ValueError:
        pass
    else:
        raise AssertionError("empty capacity cases must fail")

    invalid = deepcopy(cases)
    invalid["cases"][0]["candidates"] = []
    try:
        smoke._capacity_cases(invalid)
    except ValueError:
        pass
    else:
        raise AssertionError("empty candidates must fail")

    try:
        smoke._parse_time("not-a-time")
    except ValueError:
        pass
    else:
        raise AssertionError("invalid timestamp must fail")

    try:
        smoke._assert_redacted({"leak": "secret-key"}, _env(), cases=[])
    except ValueError:
        pass
    else:
        raise AssertionError("protected API key must fail")


def test_budgeted_requester_rejects_route_drift_and_exhaustion() -> None:
    counts = {"total": 0}
    guarded = smoke._budgeted_requester(
        lambda *_args, **_kwargs: "ok",
        expected_url=ENDPOINT,
        counts=counts,
        maximum_requests=1,
    )
    try:
        guarded("POST", "http://wrong.test")
    except ValueError:
        pass
    else:
        raise AssertionError("route drift must fail")
    assert guarded("POST", ENDPOINT) == "ok"
    try:
        guarded("POST", ENDPOINT)
    except ValueError:
        pass
    else:
        raise AssertionError("request budget exhaustion must fail")


def test_profile_and_baseline_helpers_reject_incomplete_metrics(monkeypatch) -> None:
    monkeypatch.setattr(
        smoke.remote_provider,
        "execute_remote_generation_request",
        lambda *_args, **_kwargs: {"usage": {"total_tokens": True}},
    )
    monkeypatch.setattr(
        smoke, "validate_answer_support_calibration_collection", lambda _value: {}
    )

    def complete_collector(cases, *, evaluator, **_kwargs):
        for index, _case in enumerate(cases):
            evaluator({}, f"request-{index}", f"trace-{index}")
        return {}

    result = smoke._run_profile(
        concurrency=2,
        cases=[{"case_id": "one"}, {"case_id": "two"}],
        collector=complete_collector,
        requester=lambda *_args, **_kwargs: None,
        environ={},
        design={},
        request_profile={},
        artifact_revision=REVISION,
        artifact_hash="sha256:" + "a" * 64,
        case_set_hash="sha256:" + "b" * 64,
    )
    assert result["total_tokens"] == 0
    assert result["latency_sample_count"] == 2

    def incomplete_collector(cases, *, evaluator, **_kwargs):
        evaluator({}, "request-one", "trace-one")
        return {}

    try:
        smoke._run_profile(
            concurrency=2,
            cases=[{"case_id": "one"}, {"case_id": "two"}],
            collector=incomplete_collector,
            requester=lambda *_args, **_kwargs: None,
            environ={},
            design={},
            request_profile={},
            artifact_revision=REVISION,
            artifact_hash="sha256:" + "a" * 64,
            case_set_hash="sha256:" + "b" * 64,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("incomplete latency samples must fail")

    baseline = _runner_fixtures()["baseline_receipt"]
    baseline["completed_at"] = baseline["started_at"]
    try:
        smoke._baseline_profile(baseline)
    except ValueError:
        pass
    else:
        raise AssertionError("nonpositive baseline duration must fail")


def test_provider_binding_and_mapping_helpers_fail_closed() -> None:
    binding = {
        "model_revision": REVISION,
        "deployment_id": "dgx-qwen3-5-9b-9116",
    }
    for artifact, environment in (
        ("hf:" + "0" * 40, {}),
        (REVISION, {"NEX_MO_VLLM_MODEL_REVISION": "different"}),
        (REVISION, {"NEX_MO_VLLM_DEPLOYMENT_ID": "different"}),
    ):
        try:
            smoke._bind_provider(environment, binding, artifact)
        except ValueError:
            pass
        else:
            raise AssertionError("provider binding drift must fail")

    environment = {}
    smoke._bind_provider(environment, binding, REVISION)
    assert environment["NEX_MO_VLLM_MODEL_REVISION"] == REVISION
    try:
        smoke._mapping([], "bad")
    except TypeError:
        pass
    else:
        raise AssertionError("non-mapping must fail")


def test_runner_load_probe_and_cli_helpers(tmp_path, monkeypatch, capsys) -> None:
    value = tmp_path / "value.json"
    value.write_text('{"ok": true}', encoding="utf-8")
    assert smoke._load(value) == {"ok": True}
    value.write_text("[]", encoding="utf-8")
    try:
        smoke._load(value)
    except TypeError:
        pass
    else:
        raise AssertionError("list JSON must fail")

    monkeypatch.setattr(
        smoke.socket,
        "create_connection",
        lambda *_args, **_kwargs: _Context(),
    )
    assert smoke._probe_ports("provider.test", [9112]) == {"9112": True}

    def fail(*_args, **_kwargs):
        raise OSError("closed")

    monkeypatch.setattr(smoke.socket, "create_connection", fail)
    assert smoke._probe_ports("provider.test", [9112]) == {"9112": False}

    output = tmp_path / "output.json"
    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpw_sync_capacity",
        lambda: {
            "status": "PASS",
            "profile_assessments": [],
            "recommended_synchronous_concurrency": 4,
        },
    )
    assert smoke.main(["--output", str(output), "--summary"]) == 0
    assert "=pass" in capsys.readouterr().out

    output.write_text('{"status":"PASS"}\n', encoding="utf-8")
    monkeypatch.setattr(
        smoke, "run_gb2_s20qpw_sync_capacity", lambda: {"status": "SKIPPED"}
    )
    assert smoke.main(["--output", str(output)]) == 0
    assert json.loads(output.read_text())["status"] == "PASS"

    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpw_sync_capacity",
        lambda: {"status": "FAIL", "failure_code": "forced"},
    )
    assert smoke.main(["--output", str(output)]) == 1


class _Context:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def _runner_fixtures() -> dict:
    shadow = shadow_fixtures()
    cases = _load(
        "scripts/smoke/data/s136_answer_support_extended_shadow_v1_cases.json"
    )
    design = _load(
        "scripts/smoke/data/s136_answer_support_sync_capacity_v1_design.json"
    )
    artifact = _artifact()
    manifest = shadow["readiness_report"]["manifest"]
    profile = manifest["candidate_profile"]
    binding = profile["provider_binding"]
    baseline = {
        "status": "PASS",
        "provider_binding_hash": semantic_sha256_hash_ref(dict(binding)),
        "manifest_hash": manifest["manifest_hash"],
        "profile_hash": profile["profile_hash"],
        "started_at": "2026-11-05T04:00:00Z",
        "completed_at": "2026-11-05T04:15:00Z",
        "provider_http_requests": {"generation": 30, "total": 30},
        "snapshot": {
            "provider_calls": 30,
            "failed_count": 0,
            "latency_sample_count": 30,
            "p95_latency_ms": 40_000.0,
            "maximum_latency_ms": 41_000.0,
            "total_tokens": 9_000,
        },
    }
    _rehash(baseline)
    slo = {
        "status": "PASS",
        "extended_shadow_receipt_hash": baseline["receipt_hash"],
    }
    _rehash(slo)
    source = design["source_binding"]
    source.update(
        {
            "artifact_evidence_hash": model_artifact_revision_evidence_digest(artifact),
            "case_set_hash": semantic_sha256_hash_ref(cases),
            "signal_design_hash": semantic_sha256_hash_ref(shadow["signal_design"]),
            "request_profile_hash": semantic_sha256_hash_ref(shadow["request_profile"]),
            "extended_shadow_receipt_hash": baseline["receipt_hash"],
            "latency_slo_receipt_hash": slo["receipt_hash"],
            "provider_binding_hash": baseline["provider_binding_hash"],
            "readiness_manifest_hash": baseline["manifest_hash"],
            "runtime_profile_hash": baseline["profile_hash"],
        }
    )
    validate_sync_capacity_design(design)
    return {
        "design": design,
        "cases_document": cases,
        "signal_design": shadow["signal_design"],
        "request_profile": shadow["request_profile"],
        "readiness_report": shadow["readiness_report"],
        "artifact_evidence": artifact,
        "baseline_receipt": baseline,
        "latency_slo_receipt": slo,
    }


def _env() -> dict[str, str]:
    return {
        smoke.SMOKE_ENV: "1",
        smoke.APPROVED_ENV: "1",
        smoke.OPERATOR_ENV: "operator-one",
        "NEX_MO_VLLM_CHAT_COMPLETIONS_URL": ENDPOINT,
        "NEX_MO_VLLM_API_KEY": "secret-key",
        "NEX_MO_VLLM_MODEL": "Qwen3.5-9B",
        "NEX_MO_VLLM_MODEL_REVISION": REVISION,
        "NEX_MO_VLLM_DEPLOYMENT_ID": "dgx-qwen3-5-9b-9116",
    }


def _rehash(value: dict) -> None:
    value.pop("receipt_hash", None)
    value["receipt_hash"] = semantic_sha256_hash_ref(value)


def _load(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))
