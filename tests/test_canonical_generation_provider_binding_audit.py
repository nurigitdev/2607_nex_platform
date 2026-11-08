from __future__ import annotations

import json
from pathlib import Path
import shutil

import run_canonical_generation_provider_binding_audit as audit


def test_repository_canonical_generation_binding_audit_passes() -> None:
    result = audit.audit_canonical_generation_provider_binding()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["canonical_binding"]["model_name"] == "Qwen3.5-9B"
    assert result["canonical_binding"]["provider_port"] == 9111
    assert result["compatibility_policy"] == {
        "qwen3_5_4b": "EXPLICIT_ROLLBACK_OR_LEGACY_ONLY",
        "calibrated_9116_binding": "IMMUTABLE_HISTORICAL_SOURCE",
        "runtime_9111_binding": "APPROVED_ENDPOINT_RELOCATION",
    }
    assert audit.summary_line(result) == (
        "canonical_generation_provider_binding=pass checks=10/10 "
        "model=Qwen3.5-9B port=9111"
    )


def test_audit_rejects_environment_default_regression(tmp_path: Path) -> None:
    root = _copy_audit_inputs(tmp_path)
    env_path = root / ".env.example"
    env_path.write_text(
        env_path.read_text(encoding="utf-8").replace(
            "NEX_MO_GENERATION_PROFILE=qwen3_5_9b_bf16",
            "NEX_MO_GENERATION_PROFILE=qwen3_5_4b_bf16",
        ),
        encoding="utf-8",
    )

    result = audit.audit_canonical_generation_provider_binding(root)

    assert result["status"] == "FAIL"
    assert result["checks"]["environment_defaults_exact"] is False
    assert result["checks"]["four_b_is_not_environment_default"] is False


def test_audit_rejects_compose_or_relocation_drift(tmp_path: Path) -> None:
    root = _copy_audit_inputs(tmp_path)
    compose_path = root / "deployment/compose/canonical-platform.override.yaml"
    compose_path.write_text(
        compose_path.read_text(encoding="utf-8").replace(
            "${NEX_MO_VLLM_MODEL:-Qwen3.5-9B}",
            "${NEX_MO_VLLM_MODEL:-Qwen3.5-4B}",
        ),
        encoding="utf-8",
    )
    relocation_path = (
        root
        / "services/nex-cx/nex_cx/data/answer_support_provider_relocation.v1.json"
    )
    relocation = json.loads(relocation_path.read_text(encoding="utf-8"))
    relocation["target_provider_binding"]["deployment_id"] = "drift"
    relocation_path.write_text(json.dumps(relocation), encoding="utf-8")

    result = audit.audit_canonical_generation_provider_binding(root)

    assert result["status"] == "FAIL"
    assert result["checks"]["compose_generation_defaults_exact"] is False
    assert result["checks"]["calibration_relocation_exact"] is False
    assert "calibration_relocation_invalid:AnswerSupportProviderRelocationError" in (
        result["issues"]
    )


def test_main_writes_report_and_returns_failure(monkeypatch, tmp_path: Path, capsys) -> None:
    report = tmp_path / "binding.json"
    monkeypatch.setattr(
        audit,
        "audit_canonical_generation_provider_binding",
        lambda: {
            "schema_version": audit.SCHEMA_VERSION,
            "slice": audit.SLICE,
            "status": "FAIL",
            "checks": {"example": False},
            "issues": ["check_failed:example"],
            "secret_included": False,
        },
    )

    assert audit.main(["--report", str(report), "--summary"]) == 1
    assert "canonical_generation_provider_binding=fail checks=0/1" in (
        capsys.readouterr().out
    )
    assert json.loads(report.read_text(encoding="utf-8"))["status"] == "FAIL"


def test_audit_io_helpers_fail_closed(tmp_path: Path) -> None:
    issues: list[str] = []
    assert audit._read_env(tmp_path / "missing.env", issues) == {}
    assert issues == ["environment_defaults_unavailable:FileNotFoundError"]

    issues = []
    assert audit._read_compose(tmp_path / "missing.yaml", issues) == {}
    assert issues == ["compose_unavailable:FileNotFoundError"]
    not_mapping = tmp_path / "not-mapping.yaml"
    not_mapping.write_text("- value\n", encoding="utf-8")
    assert audit._read_compose(not_mapping, []) == {}

    assert audit._service_environment({}, "nex-mo") == {}
    assert audit._service_environment({"services": []}, "nex-mo") == {}
    assert audit._service_environment({"services": {"nex-mo": []}}, "nex-mo") == {}
    assert audit._service_environment(
        {"services": {"nex-mo": {"environment": []}}}, "nex-mo"
    ) == {}
    assert audit.summary_line({"status": "FAIL", "checks": []}).endswith(
        "checks=0/0 model=Qwen3.5-9B port=9111"
    )


def test_main_handles_unexpected_audit_failure(monkeypatch, tmp_path: Path, capsys) -> None:
    report = tmp_path / "failure.json"

    def fail() -> dict:
        raise ValueError("unsafe detail")

    monkeypatch.setattr(audit, "audit_canonical_generation_provider_binding", fail)

    assert audit.main(["--report", str(report)]) == 1
    output = json.loads(capsys.readouterr().out)
    assert output["issues"] == ["audit_failed:ValueError"]
    assert "unsafe detail" not in report.read_text(encoding="utf-8")


def _copy_audit_inputs(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    relative_paths = (
        ".env.example",
        "deployment/compose/canonical-platform.override.yaml",
        "services/nex-cx/nex_cx/data/answer_support_provider_relocation.v1.json",
    )
    for relative in relative_paths:
        source = audit.ROOT / relative
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    return root
