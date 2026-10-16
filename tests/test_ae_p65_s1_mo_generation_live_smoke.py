from __future__ import annotations

import json

import pytest

from nex_ae_api.mo_generation_client import (
    AeMoGenerationClientError,
    AeMoGenerationReadiness,
    AeMoGenerationResult,
)
import run_p65_s1_ae_mo_generation_live_smoke as smoke


class FakeClient:
    def __init__(
        self,
        *,
        readiness_error: Exception | None = None,
        generation_error: Exception | None = None,
        output_text: str = '{"status":"ok","contract":"p65-s1"}',
    ) -> None:
        self.readiness_error = readiness_error
        self.generation_error = generation_error
        self.output_text = output_text

    def check_required_mode_readiness(self, **kwargs) -> AeMoGenerationReadiness:
        if self.readiness_error is not None:
            raise self.readiness_error
        return AeMoGenerationReadiness(
            provider_mode="live",
            readiness_status="READY",
            model_profile="general-llm-default",
            model_ref="Qwen3.5-4B",
            deployment_id="vllm-generation-http",
            route_id="route-general-llm-default",
            checked_at="2026-10-16T01:00:00Z",
            expires_at="2026-10-16T01:00:30Z",
            cache_status="FRESH",
            source="active_preflight",
        )

    def generate_candidate(self, **kwargs) -> AeMoGenerationResult:
        if self.generation_error is not None:
            raise self.generation_error
        output_bytes = self.output_text.encode()
        import hashlib

        return AeMoGenerationResult(
            mo_generation_id="mo-generation-live",
            model_profile="general-llm-default",
            model_ref="Qwen3.5-4B",
            deployment_id="vllm-generation-http",
            provider_type="vllm-openai-compatible",
            output_text=self.output_text,
            provider_output_sha256=hashlib.sha256(output_bytes).hexdigest(),
            provider_output_size_bytes=len(output_bytes),
            finish_reason="STOP",
            input_tokens=10,
            output_tokens=5,
            total_tokens=15,
            request_id=kwargs["request_id"],
            trace_id=kwargs["trace_id"],
            route_id="route-general-llm-default",
            provider_request_id="provider-request-live",
            queue_ms=0,
            provider_ms=12,
            total_ms=12,
            created_at="2026-10-16T01:00:00Z",
            updated_at="2026-10-16T01:00:01Z",
        )


def _client_error(code: str) -> AeMoGenerationClientError:
    return AeMoGenerationClientError(503, code, "safe", True)


def test_protected_live_smoke_is_skipped_by_default() -> None:
    evidence = smoke.run_p65_s1_ae_mo_generation_live_smoke({})

    assert evidence["status"] == "SKIPPED"
    assert evidence["next_slice"] == "blocked"
    assert smoke.ACTIVATION_ENV in smoke.summary_line(evidence)


def test_protected_live_smoke_passes_with_safe_lineage_only() -> None:
    evidence = smoke.run_p65_s1_ae_mo_generation_live_smoke(
        {smoke.ACTIVATION_ENV: "1"},
        client=FakeClient(),
    )

    assert evidence["status"] == "PASS"
    assert evidence["next_slice"] == "P6.5-S2"
    assert all(evidence["checks"].values())
    assert evidence["generation"]["model_ref"] == "Qwen3.5-4B"
    serialized = json.dumps(evidence)
    assert '"status":"ok"' not in serialized
    assert "raw_output" in evidence["redaction"]["excluded"]
    assert "pass" in smoke.summary_line(evidence)


@pytest.mark.parametrize(
    ("client", "stage", "error_code"),
    [
        (FakeClient(readiness_error=_client_error("PROVIDER_NOT_READY")), "readiness", "PROVIDER_NOT_READY"),
        (FakeClient(generation_error=_client_error("PROVIDER_TIMEOUT")), "generation", "PROVIDER_TIMEOUT"),
        (FakeClient(readiness_error=RuntimeError("private")), "readiness", "UNEXPECTED_READINESS_FAILURE"),
        (FakeClient(generation_error=RuntimeError("private")), "generation", "UNEXPECTED_GENERATION_FAILURE"),
    ],
)
def test_protected_live_smoke_normalizes_failures(
    client: FakeClient,
    stage: str,
    error_code: str,
) -> None:
    evidence = smoke.run_p65_s1_ae_mo_generation_live_smoke(
        {smoke.ACTIVATION_ENV: "1"},
        client=client,
    )

    assert evidence["status"] == "FAIL"
    assert evidence["stages"][stage] == "FAIL"
    assert evidence["issues"] == [{"stage": stage, "error_code": error_code}]
    assert "private" not in json.dumps(evidence)


@pytest.mark.parametrize(
    "output_text",
    ["not-json", '{"status":"wrong","contract":"p65-s1"}'],
)
def test_protected_live_smoke_rejects_invalid_golden_output(output_text: str) -> None:
    evidence = smoke.run_p65_s1_ae_mo_generation_live_smoke(
        {smoke.ACTIVATION_ENV: "1"},
        client=FakeClient(output_text=output_text),
    )

    assert evidence["status"] == "FAIL"
    assert evidence["stages"]["assertions"] == "FAIL"


def test_protected_live_smoke_configuration_failure_is_safe(monkeypatch) -> None:
    def fail(environ):
        from nex_ae_api.mo_generation_client import AeMoGenerationConfigurationError

        raise AeMoGenerationConfigurationError("CONFIG_INVALID", "private")

    monkeypatch.setattr(smoke, "build_default_ae_mo_generation_client", fail)
    evidence = smoke.run_p65_s1_ae_mo_generation_live_smoke(
        {smoke.ACTIVATION_ENV: "1"}
    )

    assert evidence["status"] == "FAIL"
    assert evidence["issues"][0]["error_code"] == "CONFIG_INVALID"
    assert "private" not in json.dumps(evidence)


def test_evidence_writer_allows_only_tmp(tmp_path) -> None:
    evidence = smoke.run_p65_s1_ae_mo_generation_live_smoke({})
    output = tmp_path / "evidence.json"

    smoke.write_evidence(output, evidence)
    assert json.loads(output.read_text())["status"] == "SKIPPED"

    with pytest.raises(ValueError):
        smoke.write_evidence(smoke.ROOT / "evidence.json", evidence)


def test_main_writes_summary_and_returns_success(monkeypatch, tmp_path, capsys) -> None:
    run_smoke = smoke.run_p65_s1_ae_mo_generation_live_smoke
    monkeypatch.setattr(
        smoke,
        "run_p65_s1_ae_mo_generation_live_smoke",
        lambda: run_smoke({}),
    )
    output = tmp_path / "main-evidence.json"

    assert smoke.main(["--summary", "--output", str(output)]) == 0
    assert "skipped" in capsys.readouterr().out
    assert output.exists()
