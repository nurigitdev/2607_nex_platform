from __future__ import annotations

from pathlib import Path

import pytest
import run_p8_demo_external_dependencies as runner
from nex_runtime.demo_external_dependencies import (
    DemoExternalDependencyError,
    admit_demo_external_dependencies,
)
from run_p8_demo_external_dependencies import (
    _assert_redacted,
    run_p8_demo_external_dependencies,
    summary_line,
)


def _provider_evidence() -> dict:
    return {
        "status": "PASS",
        "canonical_admission": {
            "schema_version": "model_provider_admission.v1",
            "admission_status": "ADMITTED",
            "readiness_status": "READY",
            "profile": "rag",
            "dependency_readiness": [],
            "failure_code": None,
        },
        "checks": [
            {
                "capability": "embedding",
                "status": "PASS",
                "configured": True,
                "authorization_configured": True,
                "authorized": True,
                "model_identity_admitted": True,
                "bounded_request_succeeded": True,
                "timeout_policy_valid": True,
                "response_observed": True,
                "request_shape": "openai_embeddings",
                "expected_models": ["embedding-model"],
                "timeout_seconds": 30,
            },
            {
                "capability": "reranking",
                "status": "PASS",
                "configured": True,
                "authorization_configured": True,
                "authorized": True,
                "model_identity_admitted": True,
                "bounded_request_succeeded": True,
                "timeout_policy_valid": True,
                "response_observed": True,
                "request_shape": "rerank",
                "expected_models": ["reranker-model"],
                "timeout_seconds": 30.0,
            },
            {
                "capability": "generation",
                "status": "PASS",
                "configured": True,
                "authorization_configured": True,
                "authorized": True,
                "model_identity_admitted": True,
                "bounded_request_succeeded": True,
                "timeout_policy_valid": True,
                "response_observed": True,
                "request_shape": "openai_models",
                "expected_models": ["generation-model"],
                "timeout_seconds": 60,
            },
        ],
    }


def _object_evidence() -> dict:
    receipt = {
        "status": "VERIFIED",
        "versioning_enabled": True,
        "encryption_algorithm": "AES256",
    }
    return {
        "status": "PASS",
        "rustfs": {
            "bucket_receipts": [dict(receipt), dict(receipt)],
            "container_posture": {
                "health_status": "healthy",
                "non_root_user": True,
                "durable_volume_mounted": True,
            },
            "tls_route": {"status": "PASS", "managed_tls_verified": True},
            "cross_bucket_denied": {
                "ae_to_cx_denied": True,
                "cx_to_ae_denied": True,
            },
            "restart_recovery_verified": True,
        },
        "adapters": {
            "status": "PASS",
            "postgres_payload_bytes_written": False,
        },
        "cleanup": {"status": "PASS", "named_volume_removed": True},
        "decision": {"production_contacted": False},
    }


def test_admission_combines_actual_provider_and_rustfs_evidence() -> None:
    result = admit_demo_external_dependencies(
        _provider_evidence(), _object_evidence()
    )

    assert result["status"] == "PASS"
    assert result["provider"]["capability_count"] == 3
    assert result["object_storage"] == {
        "status": "PASS",
        "backend": "rustfs-s3-compatible",
        "bucket_count": 2,
        "managed_tls": True,
        "owner_isolation": True,
        "restart_recovery": True,
        "zero_payload_bytes_in_postgres": True,
        "runtime_residue_retained": False,
    }
    assert result["dependency_identity_digest"].startswith("sha256:")
    assert result["next_slice"] == "P8-DEMO-S10"


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        (lambda value: value.update(status="FAIL"), "did not pass"),
        (lambda value: value.update(checks="bad"), "checks are invalid"),
        (
            lambda value: value["checks"].append("bad"),
            "check is invalid",
        ),
        (
            lambda value: value["checks"].append(dict(value["checks"][0])),
            "coverage is invalid",
        ),
        (
            lambda value: value["checks"].reverse(),
            "coverage drift",
        ),
        (
            lambda value: value["checks"][0].update(timeout_seconds=True),
            "embedding provider admission failed",
        ),
        (
            lambda value: value["checks"][2].update(expected_models=[""]),
            "generation provider admission failed",
        ),
    ),
)
def test_provider_admission_fails_closed(mutation, message: str) -> None:
    evidence = _provider_evidence()
    mutation(evidence)
    with pytest.raises(DemoExternalDependencyError, match=message):
        admit_demo_external_dependencies(evidence, _object_evidence())


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        (lambda value: value.update(status="FAIL"), "did not pass"),
        (lambda value: value["rustfs"].update(bucket_receipts="bad"), "did not pass"),
        (
            lambda value: value["rustfs"]["bucket_receipts"][0].update(
                versioning_enabled=False
            ),
            "bucket admission failed",
        ),
        (
            lambda value: value["rustfs"]["container_posture"].update(
                non_root_user=False
            ),
            "runtime boundary drift",
        ),
        (
            lambda value: value.pop("cleanup"),
            "cleanup evidence is invalid",
        ),
    ),
)
def test_object_storage_admission_fails_closed(mutation, message: str) -> None:
    evidence = _object_evidence()
    mutation(evidence)
    with pytest.raises(DemoExternalDependencyError, match=message):
        admit_demo_external_dependencies(_provider_evidence(), evidence)


def test_runner_is_protected_redacted_and_writes_evidence(tmp_path: Path) -> None:
    provider_calls = []
    object_calls = []

    def provider_runner(environment):
        provider_calls.append(environment)
        return _provider_evidence()

    def object_runner(environment):
        object_calls.append(environment)
        return _object_evidence()

    report = tmp_path / "evidence.json"
    result = run_p8_demo_external_dependencies(
        {
            "NEX_P8_DEMO_EXTERNAL_DEPENDENCIES": "1",
            "NEX_MO_VLLM_API_KEY": "private-generation-key",
        },
        execute=True,
        provider_runner=provider_runner,
        object_runner=object_runner,
        report_path=report,
    )

    assert result["status"] == "PASS"
    assert provider_calls[0]["NEX_MO_LIVE_PREFLIGHT"] == "1"
    assert object_calls[0]["NEX_S146_PROTECTED_ACCEPTANCE"] == "1"
    assert "private-generation-key" not in report.read_text(encoding="utf-8")
    assert summary_line(result).startswith("p8_demo_external_dependencies=pass")


def test_runner_skip_failure_and_redaction_guards(tmp_path: Path) -> None:
    skipped = run_p8_demo_external_dependencies({}, report_path=tmp_path / "skip")
    assert skipped["status"] == "SKIPPED"
    assert summary_line(skipped) == "p8_demo_external_dependencies=skipped"

    failed = run_p8_demo_external_dependencies(
        {"NEX_P8_DEMO_EXTERNAL_DEPENDENCIES": "1"},
        execute=True,
        provider_runner=lambda _: (_ for _ in ()).throw(RuntimeError("private")),
        object_runner=lambda _: _object_evidence(),
        report_path=tmp_path / "failure.json",
    )
    assert failed["status"] == "FAIL"
    assert failed["next_slice"] == "blocked"

    with pytest.raises(DemoExternalDependencyError, match="protected material"):
        _assert_redacted(
            {"value": "https://private-provider.example/v1"},
            {
                "NEX_MO_VLLM_BASE_URL": "https://private-provider.example/v1"
            },
        )


def test_default_rustfs_adapter_forwards_protected_execution(monkeypatch) -> None:
    observed = {}

    def source(environ, **kwargs):
        observed.update(environ=environ, kwargs=kwargs)
        return {"status": "PASS"}

    monkeypatch.setattr(runner.rustfs, "run_s146_object_storage_acceptance", source)
    result = runner._run_rustfs({"MARKER": "present"})

    assert result == {"status": "PASS"}
    assert observed["environ"]["MARKER"] == "present"
    assert observed["kwargs"]["execute"] is True
    assert observed["kwargs"]["root"] == runner.ROOT


@pytest.mark.parametrize(
    ("status", "arguments", "expected"),
    (
        ("PASS", ["--execute", "--summary"], 0),
        ("SKIPPED", [], 0),
        ("FAIL", ["--execute"], 1),
    ),
)
def test_cli_main_status_mapping(monkeypatch, capsys, tmp_path, status, arguments, expected) -> None:
    monkeypatch.setattr(
        runner,
        "run_p8_demo_external_dependencies",
        lambda **kwargs: {"status": status},
    )

    assert runner.main([*arguments, "--output", str(tmp_path / "result.json")]) == expected
    assert status.lower() in capsys.readouterr().out.lower()
