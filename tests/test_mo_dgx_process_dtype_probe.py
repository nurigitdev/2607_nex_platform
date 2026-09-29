from __future__ import annotations

import json
import subprocess

import run_mo_dgx_process_dtype_probe as probe


def enabled_env() -> dict[str, str]:
    return {
        probe.ACTIVATION_ENV: "1",
        probe.SSH_TARGET_ENV: "operator@dgx.internal",
    }


def raw_observations(*items: dict[str, object]) -> str:
    return json.dumps(
        {
            "schema_version": probe.RAW_SCHEMA_VERSION,
            "observations": list(items),
        }
    )


def completed(stdout: str, returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr="secret stderr")


def passing_items() -> tuple[dict[str, object], ...]:
    return (
        {
            "port": 9111,
            "dtype": "auto",
            "configured_dtype": "bfloat16",
            "model_reference_source": "model_flag",
            "model_config_status": "dtype_found",
            "task": "generate",
            "expected_model_seen": True,
        },
        {
            "port": 9112,
            "dtype": "bf16",
            "configured_dtype": "bfloat16",
            "model_reference_source": "model_flag",
            "model_config_status": "dtype_found",
            "task": "embed",
            "expected_model_seen": True,
        },
        {
            "port": 9113,
            "dtype": "bfloat16",
            "configured_dtype": "bfloat16",
            "model_reference_source": "model_flag",
            "model_config_status": "dtype_found",
            "task": "score",
            "expected_model_seen": True,
        },
    )


def test_probe_skips_by_default_and_rejects_unsafe_target() -> None:
    skipped = probe.run_mo_dgx_process_dtype_probe({})
    invalid = probe.run_mo_dgx_process_dtype_probe(
        {probe.ACTIVATION_ENV: "1", probe.SSH_TARGET_ENV: "-oProxyCommand=bad"}
    )

    assert skipped["status"] == "SKIPPED"
    assert skipped["target_configured"] is False
    assert invalid["status"] == "FAIL"
    assert invalid["issues"][0]["error_code"] == "ssh_target_invalid"


def test_probe_passes_only_redacted_bf16_observations() -> None:
    calls: list[dict[str, object]] = []

    def runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append({"command": command, **kwargs})
        return completed(raw_observations(*passing_items()))

    evidence = probe.run_mo_dgx_process_dtype_probe(enabled_env(), command_runner=runner)
    serialized = json.dumps(evidence)

    assert evidence["status"] == "PASS"
    assert evidence["stage_status"]["assertions"] == "PASS"
    assert [item["capability"] for item in evidence["observations"]] == [
        "generation",
        "embedding",
        "reranking",
    ]
    assert all(item["bf16_confirmed"] for item in evidence["observations"])
    assert [item["bf16_explicit"] for item in evidence["observations"]] == [
        False,
        True,
        True,
    ]
    assert calls[0]["command"][-2:] == ["python3", "-"]
    assert calls[0]["input"] == probe.REMOTE_PROBE
    assert "operator@dgx.internal" not in serialized
    assert "secret stderr" not in serialized


def test_probe_reports_missing_ambiguous_model_and_dtype_issues() -> None:
    items = (
        {
            "port": 9111,
            "dtype": "float32",
            "configured_dtype": "bfloat16",
            "model_reference_source": "model_flag",
            "model_config_status": "dtype_found",
            "task": "generate",
            "expected_model_seen": False,
        },
        {
            "port": 9112,
            "dtype": "bfloat16",
            "configured_dtype": "bfloat16",
            "model_reference_source": "model_flag",
            "model_config_status": "dtype_found",
            "task": "embed",
            "expected_model_seen": True,
        },
        {
            "port": 9112,
            "dtype": "bfloat16",
            "configured_dtype": "bfloat16",
            "model_reference_source": "model_flag",
            "model_config_status": "dtype_found",
            "task": "embed",
            "expected_model_seen": True,
        },
    )
    evidence = probe.run_mo_dgx_process_dtype_probe(
        enabled_env(),
        command_runner=lambda *args, **kwargs: completed(raw_observations(*items)),
    )
    codes = {item["error_code"] for item in evidence["issues"]}

    assert evidence["status"] == "FAIL"
    assert codes == {
        "expected_model_not_observed",
        "bf16_not_confirmed",
        "provider_process_ambiguous",
        "provider_process_missing",
    }


def test_probe_handles_transport_and_payload_failures_without_leaks() -> None:
    def timeout(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired("ssh secret", 15)

    def unavailable(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise OSError("ssh secret")

    scenarios = (
        (timeout, "ssh_probe_timeout"),
        (unavailable, "ssh_probe_unavailable"),
        (lambda *args, **kwargs: completed("", 255), "ssh_probe_failed"),
        (lambda *args, **kwargs: completed("not-json"), "probe_output_invalid"),
        (lambda *args, **kwargs: completed(json.dumps([])), "provider_process_missing"),
    )

    for runner, expected_code in scenarios:
        evidence = probe.run_mo_dgx_process_dtype_probe(
            enabled_env(), command_runner=runner
        )
        assert evidence["status"] == "FAIL"
        assert evidence["issues"][0]["error_code"] == expected_code
        assert "secret" not in json.dumps(evidence)


def test_probe_normalizes_only_supported_provider_rows() -> None:
    payload = {
        "schema_version": probe.RAW_SCHEMA_VERSION,
        "observations": [
            None,
            {"port": 9999},
            {
                "port": 9111,
                "dtype": None,
                "configured_dtype": None,
                "model_reference_source": None,
                "model_config_status": None,
                "task": None,
                "expected_model_seen": 1,
            },
        ],
    }

    assert probe._normalize_observations(None) == []
    assert probe._normalize_observations({"schema_version": "wrong"}) == []
    assert probe._normalize_observations(
        {"schema_version": probe.RAW_SCHEMA_VERSION, "observations": None}
    ) == []
    normalized = probe._normalize_observations(payload)
    assert normalized == [
        {
            "capability": "generation",
            "port": 9111,
            "dtype": "invalid",
            "configured_dtype": "invalid",
            "model_reference_source": "invalid",
            "model_config_status": "invalid",
            "task": "invalid",
            "expected_model_seen": False,
            "bf16_explicit": False,
            "bf16_confirmed": False,
        }
    ]


def test_probe_summary_output_and_main_skip(monkeypatch, capsys, tmp_path) -> None:
    passed = probe.run_mo_dgx_process_dtype_probe(
        enabled_env(),
        command_runner=lambda *args, **kwargs: completed(
            raw_observations(*passing_items())
        ),
    )
    assert probe.summary_line(passed) == (
        "mo_dgx_process_dtype_probe=pass providers=3/3 bf16=3/3 explicit=2/3"
    )

    monkeypatch.delenv(probe.ACTIVATION_ENV, raising=False)
    output = tmp_path / "dtype.json"
    assert probe.main(["--summary", "--output", str(output)]) == 0
    assert "mo_dgx_process_dtype_probe=skipped" in capsys.readouterr().out
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "SKIPPED"


def test_probe_main_returns_failure_and_prints_json(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        probe,
        "run_mo_dgx_process_dtype_probe",
        lambda: {"status": "FAIL", "observations": [], "issues": []},
    )

    assert probe.main([]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"
