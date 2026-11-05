from __future__ import annotations

import json
import time
from copy import deepcopy
from pathlib import Path
from threading import Event, Lock
from types import SimpleNamespace

import httpx
import pytest
import run_gb2_s20qpy_sync_runtime_e2e as smoke
from nex_cx.retrieval_answer_support_interactive_slo_policy import (
    build_interactive_slo_operator_decision,
    decide_interactive_slo_runtime_policy,
)
from nex_cx.retrieval_answer_support_synchronous_runtime import (
    validate_synchronous_runtime_e2e_design,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from test_gb2_ca00_s20qpt_shadow_canary_operations import (
    ENDPOINT,
    _artifact,
)
from test_gb2_ca00_s20qpt_shadow_canary_operations import (
    _fixtures as shadow_fixtures,
)
from test_gb2_ca00_s20qpw_sync_capacity import _env as capacity_env
from test_nex_cx_retrieval_answer_support_interactive_slo_policy import (
    NOW,
)
from test_nex_cx_retrieval_answer_support_interactive_slo_policy import (
    _fixtures as policy_fixtures,
)

ROOT = Path(__file__).resolve().parents[1]


def test_protected_sync_runtime_accepts_c4_feedback_provider_and_e2e_slos(
    tmp_path,
) -> None:
    fixtures = _runner_fixtures()
    active = 0
    peak_active = 0
    calls = 0
    lock = Lock()
    first_wave_ready = Event()

    def requester(method: str, url: str, **kwargs):
        nonlocal active, peak_active, calls
        with lock:
            active += 1
            calls += 1
            call_number = calls
            peak_active = max(peak_active, active)
            if active == 4:
                first_wave_ready.set()
        try:
            if call_number <= 4:
                if not first_wave_ready.wait(timeout=2):
                    raise TimeoutError("first c4 test wave did not become ready")
            else:
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
    result = smoke.run_gb2_s20qpy_sync_runtime_e2e(
        _env(),
        requester=requester,
        port_probe=lambda _host, ports: {str(port): True for port in ports},
        receipt_path=target,
        **fixtures,
    )
    assert result["status"] == "PASS"
    assert result["decision"].startswith("SYNCHRONOUS_RUNTIME_E2E_ACCEPTED")
    assert result["provider_http_requests"] == 30
    assert result["execution"]["accepted_count"] == 30
    assert result["execution"]["peak_in_flight"] == 4
    assert result["execution"]["overload_probe_retryable"] is True
    assert result["metrics"]["feedback_p95_latency_ms"] <= 2_000
    assert result["metrics"]["provider_p95_latency_ms"] <= 15_000
    assert result["metrics"]["e2e_p95_latency_ms"] <= 20_000
    assert result["runtime_activation_permitted"] is False
    assert calls == 30
    assert peak_active == 4
    assert target.stat().st_mode & 0o777 == 0o600
    assert json.loads(target.read_text())["status"] == "PASS"
    assert "activation=pending_operator_decision" in smoke.summary_line(result)


def test_runner_requires_enablement_approval_configuration_and_one_shot(
    tmp_path,
) -> None:
    assert smoke.run_gb2_s20qpy_sync_runtime_e2e({})["status"] == "SKIPPED"
    assert smoke.summary_line({"status": "SKIPPED"}).endswith("=skipped")
    assert (
        smoke.run_gb2_s20qpy_sync_runtime_e2e({smoke.SMOKE_ENV: "1"})["failure_code"]
        == "operator_approval_required"
    )
    assert (
        smoke.run_gb2_s20qpy_sync_runtime_e2e(
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
        smoke.run_gb2_s20qpy_sync_runtime_e2e(_env(), receipt_path=used)["failure_code"]
        == "runtime_e2e_acceptance_already_consumed"
    )


def test_runner_rejects_source_or_provider_route_drift_before_calls(tmp_path) -> None:
    fixtures = _runner_fixtures()
    drifted = deepcopy(fixtures["design"])
    drifted["source_binding"]["case_set_hash"] = "sha256:" + "f" * 64
    result = smoke.run_gb2_s20qpy_sync_runtime_e2e(
        _env(),
        requester=lambda *_args, **_kwargs: None,
        port_probe=lambda _host, ports: {str(port): True for port in ports},
        receipt_path=tmp_path / "source.json",
        **{**fixtures, "design": drifted},
    )
    assert result["status"] == "FAIL"
    assert result["provider_http_requests"] == 0

    result = smoke.run_gb2_s20qpy_sync_runtime_e2e(
        _env(),
        requester=lambda *_args, **_kwargs: None,
        port_probe=lambda _host, ports: {str(port): False for port in ports},
        receipt_path=tmp_path / "route.json",
        **fixtures,
    )
    assert result["status"] == "FAIL"
    assert result["failure_detail"] == {"exception": "ValueError"}


def test_runner_rejects_provider_route_without_explicit_port(
    tmp_path, monkeypatch
) -> None:
    fixtures = _runner_fixtures()
    monkeypatch.setattr(
        smoke.remote_provider,
        "build_remote_generation_execution_config",
        lambda _environ: SimpleNamespace(
            url="http://generation-provider/v1/chat/completions"
        ),
    )
    result = smoke.run_gb2_s20qpy_sync_runtime_e2e(
        _env(),
        requester=lambda *_args, **_kwargs: None,
        port_probe=lambda _host, ports: {str(port): True for port in ports},
        receipt_path=tmp_path / "incomplete-route.json",
        **fixtures,
    )
    assert result["status"] == "FAIL"
    assert result["failure_detail"] == {"exception": "ValueError"}
    assert result["provider_http_requests"] == 0


def test_runner_helpers_cover_overload_percentile_redaction_and_cli(
    tmp_path, monkeypatch, capsys
) -> None:
    assert smoke._overload_probe() is True
    assert smoke._p95([]) == 0.0
    assert smoke._p95([1.0, 3.0, 2.0]) == 3.0
    with pytest.raises(TypeError):
        smoke._mapping([], "bad")
    with pytest.raises(ValueError):
        smoke._assert_redacted(
            {"leak": "secret-key"}, {"NEX_MO_VLLM_API_KEY": "secret-key"}, []
        )

    value = tmp_path / "value.json"
    value.write_text('{"ok": true}', encoding="utf-8")
    assert smoke._load(value) == {"ok": True}
    value.write_text("[]", encoding="utf-8")
    with pytest.raises(TypeError):
        smoke._load(value)

    output = tmp_path / "output.json"
    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpy_sync_runtime_e2e",
        lambda: {
            "status": "PASS",
            "metrics": {
                "feedback_p95_latency_ms": 1,
                "provider_p95_latency_ms": 2,
                "e2e_p95_latency_ms": 3,
            },
        },
    )
    assert smoke.main(["--output", str(output), "--summary"]) == 0
    assert "=pass" in capsys.readouterr().out
    output.write_text('{"status":"PASS"}\n', encoding="utf-8")
    monkeypatch.setattr(
        smoke, "run_gb2_s20qpy_sync_runtime_e2e", lambda: {"status": "SKIPPED"}
    )
    assert smoke.main(["--output", str(output)]) == 0
    assert json.loads(output.read_text())["status"] == "PASS"
    monkeypatch.setattr(
        smoke,
        "run_gb2_s20qpy_sync_runtime_e2e",
        lambda: {"status": "FAIL", "failure_code": "forced"},
    )
    assert smoke.main(["--output", str(output)]) == 1
    assert "=fail" in smoke.summary_line({"status": "FAIL", "failure_code": "x"})


def _runner_fixtures() -> dict:
    shadow = shadow_fixtures()
    policy_source = policy_fixtures()
    operator = build_interactive_slo_operator_decision(
        operator_id="operator",
        decided_at=NOW,
        design=policy_source["design"],
        capacity_manifest=policy_source["capacity_manifest"],
        control_manifest=policy_source["control_manifest"],
    )
    policy_manifest = decide_interactive_slo_runtime_policy(
        design=policy_source["design"],
        capacity_manifest=policy_source["capacity_manifest"],
        control_manifest=policy_source["control_manifest"],
        operator_decision=operator,
    )
    policy_decision = {
        "status": "PASS",
        "design_hash": policy_manifest["design_hash"],
        "manifest_hash": policy_manifest["manifest_hash"],
        "selected_policy": policy_manifest["selected_policy"],
    }
    policy_receipt = {
        "receipt_schema_version": (
            "cx_answer_support_interactive_slo_policy_decision_receipt.v1"
        ),
        "status": "PASS",
        "decision": policy_manifest["decision"],
        "design_hash": policy_manifest["design_hash"],
        "operator_decision_hash": operator["decision_hash"],
        "manifest_hash": policy_manifest["manifest_hash"],
        "selected_policy_hash": policy_manifest["selected_policy"]["policy_hash"],
        "capacity_receipt_hash": policy_source["capacity_receipt"]["receipt_hash"],
        "control_receipt_hash": policy_source["control_receipt"]["receipt_hash"],
        "decided_at": NOW,
        "runtime_activation_permitted": False,
        "production_cutover_permitted": False,
    }
    _rehash(policy_receipt)
    cases = _load(
        "scripts/smoke/data/s136_answer_support_extended_shadow_v1_cases.json"
    )
    artifact = _artifact()
    manifest = shadow["readiness_report"]["manifest"]
    design = _load(
        "scripts/smoke/data/s136_answer_support_sync_runtime_e2e_v1_design.json"
    )
    design["source_binding"].update(
        {
            "artifact_evidence_hash": semantic_sha256_hash_ref(artifact),
            "case_set_hash": semantic_sha256_hash_ref(cases),
            "interactive_slo_decision_receipt_document_hash": (
                semantic_sha256_hash_ref(policy_receipt)
            ),
            "interactive_slo_decision_receipt_hash": policy_receipt["receipt_hash"],
            "interactive_slo_design_hash": policy_manifest["design_hash"],
            "interactive_slo_manifest_hash": policy_manifest["manifest_hash"],
            "provider_binding_hash": semantic_sha256_hash_ref(
                manifest["candidate_profile"]["provider_binding"]
            ),
            "readiness_manifest_hash": manifest["manifest_hash"],
            "request_profile_hash": semantic_sha256_hash_ref(shadow["request_profile"]),
            "runtime_profile_hash": manifest["candidate_profile"]["profile_hash"],
            "selected_policy_hash": policy_manifest["selected_policy"]["policy_hash"],
            "signal_design_hash": semantic_sha256_hash_ref(shadow["signal_design"]),
        }
    )
    validate_synchronous_runtime_e2e_design(design)
    return {
        "design": design,
        "cases_document": cases,
        "signal_design": shadow["signal_design"],
        "request_profile": shadow["request_profile"],
        "readiness_report": shadow["readiness_report"],
        "artifact_evidence": artifact,
        "policy_decision": policy_decision,
        "policy_receipt": policy_receipt,
    }


def _env() -> dict[str, str]:
    env = capacity_env()
    env.pop("NEX_GB2_S20QPW_SYNC_CAPACITY")
    env.pop("NEX_GB2_S20QPW_OPERATOR_APPROVED")
    env.pop("NEX_GB2_S20QPW_OPERATOR_ID")
    env.update(
        {
            smoke.SMOKE_ENV: "1",
            smoke.APPROVED_ENV: "1",
            smoke.OPERATOR_ENV: "operator-one",
            "NEX_MO_VLLM_CHAT_COMPLETIONS_URL": ENDPOINT,
        }
    )
    return env


def _load(path: str) -> dict:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def _rehash(value: dict) -> None:
    value.pop("receipt_hash", None)
    value["receipt_hash"] = semantic_sha256_hash_ref(value)
