from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/smoke"))

import run_p8_s06_nsl_compatibility as smoke


def _result(*, status: str = "COMPLETED", version: str = "1.1") -> dict:
    return {
        "command": "run",
        "result": {
            "schema_version": version,
            "skill_id": "FINANCE.TEST",
            "status": status,
            "error": None,
            "outputs": [{"fields": []}] if status == "COMPLETED" else [],
            "resources": {"tool_calls": 2},
            "write": None,
            "validation": {"status": "ALL_PASS"},
        },
    }


def _controlled() -> dict:
    value = _result(status="WAITING_FOR_APPROVAL")
    value["result"].update(
        {
            "outputs": [],
            "pre_write_eligibility": "REQUIRES_APPROVAL",
            "resources": {"tool_calls": 3},
        }
    )
    return value


def _adapter() -> dict:
    return {
        "readiness_status": "PASS",
        "readiness_schema_version": "nsl_installed_package_readiness.v2",
        "adapter_schema_version": "ae_nsl_v02_public_api_adapter.v1",
        "release_admission_hash": "sha256:" + "a" * 64,
        "api_contract_hash": "sha256:" + "b" * 64,
        "public_api_symbols": list(smoke._load_object(smoke.DEFAULT_V02_LOCK, "lock")["public_api_symbols"]),
    }


def test_smoke_is_explicitly_protected() -> None:
    assert smoke.run_p8_s06_nsl_compatibility({}, execute=False)["status"] == "SKIPPED"
    assert (
        smoke.run_p8_s06_nsl_compatibility({}, execute=True)["status"]
        == "SKIPPED"
    )


def test_compatibility_checks_accept_dual_read_and_suspended_prefix() -> None:
    v01_lock = {"package_version": "0.1.0"}
    v02_lock = smoke._load_object(smoke.DEFAULT_V02_LOCK, "lock")
    release = {
        "source_revision": v02_lock["source_revision"],
        "source_tree": v02_lock["source_tree"],
        "wheel_sha256": v02_lock["wheel_sha256"],
    }

    checks = smoke._compatibility_checks(
        v01_lock=v01_lock,
        v02_lock=v02_lock,
        release=release,
        host_version_before="0.1.0",
        host_version_after="0.1.0",
        v01_read=_result(version="1.0"),
        adapter=_adapter(),
        v02_read=_result(),
        controlled=_controlled(),
        protected_artifacts={
            "checkpoint_created": True,
            "approval_request_created": True,
        },
        audit_summary={
            "event_types": ["EXECUTION_STARTED", "CLI_APPROVAL_SUSPENDED"],
            "tool_ids": ["ACCOUNT.GET_ACCOUNT"],
        },
    )

    assert all(checks.values())
    assert "ResumeToken" in _adapter()["public_api_symbols"]
    assert "RuntimePolicyPort" in _adapter()["public_api_symbols"]
    assert "PolicyDecision" in _adapter()["public_api_symbols"]


@pytest.mark.parametrize(
    "mutation",
    (
        {"host_version_after": "0.2.0"},
        {"v01_read": _result(status="FAILED", version="1.0")},
        {"adapter": {**_adapter(), "readiness_status": "FAIL"}},
        {"v02_read": _result(status="FAILED")},
        {"controlled": _result(status="COMPLETED")},
        {"protected_artifacts": {"checkpoint_created": False}},
        {
            "audit_summary": {
                "event_types": ["CLI_APPROVAL_SUSPENDED", "WRITE_REQUESTED"],
                "tool_ids": ["FINANCE.CREATE_VOUCHER_DRAFT"],
            }
        },
    ),
)
def test_compatibility_checks_fail_closed_on_drift(mutation: dict) -> None:
    v02_lock = smoke._load_object(smoke.DEFAULT_V02_LOCK, "lock")
    values = {
        "v01_lock": {"package_version": "0.1.0"},
        "v02_lock": v02_lock,
        "release": {
            "source_revision": v02_lock["source_revision"],
            "source_tree": v02_lock["source_tree"],
            "wheel_sha256": v02_lock["wheel_sha256"],
        },
        "host_version_before": "0.1.0",
        "host_version_after": "0.1.0",
        "v01_read": _result(version="1.0"),
        "adapter": _adapter(),
        "v02_read": _result(),
        "controlled": _controlled(),
        "protected_artifacts": {
            "checkpoint_created": True,
            "approval_request_created": True,
        },
        "audit_summary": {
            "event_types": ["CLI_APPROVAL_SUSPENDED"],
            "tool_ids": ["ACCOUNT.GET_ACCOUNT"],
        },
    }
    values.update(mutation)

    assert not all(smoke._compatibility_checks(**values).values())


def test_audit_summary_counts_tools_and_write_requests(tmp_path: Path) -> None:
    audit = tmp_path / "audit.jsonl"
    audit.write_text(
        "\n".join(
            json.dumps(item)
            for item in (
                {"event_type": "EXECUTION_STARTED", "payload": {}},
                {
                    "event_type": "TOOL_STARTED",
                    "payload": {"tool_id": "ACCOUNT.GET_ACCOUNT"},
                },
                {"event_type": "WRITE_REQUESTED", "payload": {}},
            )
        ),
        encoding="utf-8",
    )

    result = smoke._audit_summary(audit)

    assert result["event_count"] == 3
    assert result["tool_ids"] == ["ACCOUNT.GET_ACCOUNT"]
    assert result["write_requested_count"] == 1


@pytest.mark.parametrize("payload", ("", "[]"))
def test_audit_summary_rejects_missing_or_invalid_audit(
    tmp_path: Path, payload: str
) -> None:
    audit = tmp_path / "audit.jsonl"
    if payload:
        audit.write_text(payload, encoding="utf-8")

    with pytest.raises(smoke.P8S06CompatibilityError):
        smoke._audit_summary(audit)


def test_run_json_and_capture_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    capture = smoke._capture
    monkeypatch.setattr(smoke, "_capture", lambda *_args, **_kwargs: "[]")
    with pytest.raises(smoke.P8S06CompatibilityError):
        smoke._run_json(("python",), operation="probe", env={})

    monkeypatch.setattr(smoke, "_capture", capture)
    monkeypatch.setattr(
        smoke.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 9, "", "secret"),
    )
    with pytest.raises(smoke.P8S06CompatibilityError, match="exit code 9"):
        smoke._capture(("probe",), operation="probe")


def test_run_writes_sanitized_failure_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    report = tmp_path / "report.json"
    monkeypatch.setattr(
        smoke,
        "_load_object",
        lambda *_args: (_ for _ in ()).throw(OSError("unavailable")),
    )

    result = smoke.run_p8_s06_nsl_compatibility(
        {smoke.SMOKE_ENV: "1"}, execute=True, report_path=report
    )

    assert result["status"] == "FAIL"
    assert json.loads(report.read_text(encoding="utf-8")) == result


def test_run_executes_complete_compatibility_orchestration(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    v01_lock = tmp_path / "v01.json"
    v02_lock = tmp_path / "v02.json"
    report = tmp_path / "report.json"
    wheel_directory = tmp_path / "wheels"
    wheel_directory.mkdir()
    v01_lock.write_text(
        json.dumps(
            {
                "distribution": "nex-skill-language",
                "package_version": "0.1.0",
            }
        ),
        encoding="utf-8",
    )
    locked = smoke._load_object(smoke.DEFAULT_V02_LOCK, "lock")
    v02_lock.write_text(json.dumps(locked), encoding="utf-8")
    release = {
        "source_revision": locked["source_revision"],
        "source_tree": locked["source_tree"],
        "wheel_sha256": locked["wheel_sha256"],
        "source_tree_clean": True,
    }
    monkeypatch.setattr(smoke, "_verify_v02_release", lambda *_args: release)
    monkeypatch.setattr(smoke, "_install_wheel", lambda *_args: None)
    monkeypatch.setattr(smoke, "_inspect_v02_adapter", lambda **_kwargs: _adapter())
    monkeypatch.setattr(
        smoke, "_installed_distribution_version", lambda _distribution: "0.1.0"
    )

    def execute(command, *, operation, env):
        assert env
        command_text = " ".join(command)
        if "controlled.profile.json" in command_text:
            Path(command[command.index("--checkpoint-out") + 1]).write_bytes(b"cp")
            Path(command[command.index("--approval-request-out") + 1]).write_text(
                "{}", encoding="utf-8"
            )
            Path(command[command.index("--audit-out") + 1]).write_text(
                json.dumps(
                    {"event_type": "CLI_APPROVAL_SUSPENDED", "payload": {}}
                ),
                encoding="utf-8",
            )
            return _controlled()
        if "project_budget_check.profile.json" in command_text:
            return _result(version="1.0")
        assert "--no-isolate" in command
        return _result()

    monkeypatch.setattr(smoke, "_run_json", execute)

    result = smoke.run_p8_s06_nsl_compatibility(
        {smoke.SMOKE_ENV: "1"},
        execute=True,
        source=tmp_path,
        v01_lock_path=v01_lock,
        v02_lock_path=v02_lock,
        wheel_directory=wheel_directory,
        report_path=report,
        python_bin="python",
    )

    assert result["status"] == "PASS"
    assert result["checks_passed"] == result["checks_total"] == 8
    assert result["decision"] == {
        "p8_1_closed": True,
        "eos_adapter_configured": False,
        "eos_mutation_count": 0,
        "remote_provider_required": False,
    }
    assert json.loads(report.read_text(encoding="utf-8")) == result


def test_release_verification_and_drift(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    wheels = tmp_path / "wheels"
    wheels.mkdir()
    wheel = wheels / "nsl.whl"
    wheel.write_bytes(b"wheel")
    digest = smoke._sha256_ref(b"wheel")
    lock = {
        "wheel_filename": wheel.name,
        "wheel_sha256": digest,
        "source_revision": "a" * 40,
        "source_tree": "b" * 40,
    }
    outputs = iter(("a" * 40, "b" * 40, ""))
    monkeypatch.setattr(smoke, "_capture", lambda *_args, **_kwargs: next(outputs))

    assert smoke._verify_v02_release(source, wheels, lock) == {
        "source_revision": "a" * 40,
        "source_tree": "b" * 40,
        "wheel_sha256": digest,
        "source_tree_clean": True,
    }

    outputs = iter(("wrong", "b" * 40, ""))
    monkeypatch.setattr(smoke, "_capture", lambda *_args, **_kwargs: next(outputs))
    with pytest.raises(smoke.P8S06CompatibilityError, match="identity drifted"):
        smoke._verify_v02_release(source, wheels, lock)

    wheel.unlink()
    with pytest.raises(smoke.P8S06CompatibilityError, match="wheel is missing"):
        smoke._verify_v02_release(source, wheels, lock)


def test_install_and_adapter_probe_use_isolated_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}

    def capture(command, *, operation, env=None):
        captured["install"] = (command, operation, env)
        return ""

    monkeypatch.setattr(smoke, "_capture", capture)
    smoke._install_wheel("python", tmp_path / "nsl.whl", tmp_path / "target", {})
    assert "--no-deps" in captured["install"][0]

    def run_json(command, *, operation, env):
        captured["adapter"] = (command, operation, env)
        return _adapter()

    monkeypatch.setattr(smoke, "_run_json", run_json)
    result = smoke._inspect_v02_adapter(
        python_bin="python",
        target=tmp_path / "target",
        lock_path=smoke.DEFAULT_V02_LOCK,
        env={"PYTHONPATH": "target"},
    )
    assert result == _adapter()
    adapter_env = captured["adapter"][2]
    assert str(tmp_path / "target") in adapter_env["PYTHONPATH"]
    assert str(smoke.AE_SOURCE) in adapter_env["PYTHONPATH"]


def test_object_and_installed_version_fail_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    document = tmp_path / "object.json"
    document.write_text("[]", encoding="utf-8")
    with pytest.raises(smoke.P8S06CompatibilityError, match="must be an object"):
        smoke._load_object(document, "document")

    def missing(_distribution: str) -> str:
        raise smoke.importlib.metadata.PackageNotFoundError

    monkeypatch.setattr(smoke.importlib.metadata, "version", missing)
    with pytest.raises(smoke.P8S06CompatibilityError, match="is missing"):
        smoke._installed_distribution_version("missing")


def test_helpers_keep_isolation_and_safe_summaries(tmp_path: Path) -> None:
    env = smoke._isolated_environment({"PYTHONPATH": "untrusted"}, tmp_path)
    read = smoke._read_summary(_result(), "0.2.0")
    controlled = smoke._controlled_summary(
        _controlled(),
        {"checkpoint_created": True},
        {"event_count": 1},
    )

    assert env["PYTHONPATH"] == str(tmp_path)
    assert env["PYTHONDONTWRITEBYTECODE"] == "1"
    assert read == {
        "package_version": "0.2.0",
        "skill_id": "FINANCE.TEST",
        "runtime_status": "COMPLETED",
        "tool_calls": 2,
        "output_count": 1,
    }
    assert controlled["write_result_present"] is False
    assert "approval_request" not in json.dumps(controlled)
    assert smoke.summary_line(
        {
            "status": "PASS",
            "checks_passed": 8,
            "checks_total": 8,
            "decision": {"eos_mutation_count": 0},
        }
    ).endswith("checks=8/8 eos_mutations=0")


def test_main_returns_success_for_skip_and_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_p8_s06_nsl_compatibility",
        lambda **_kwargs: {"status": "SKIPPED"},
    )
    assert smoke.main(["--summary"]) == 0
    assert "p8_s06_nsl_compatibility=skipped" in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_p8_s06_nsl_compatibility",
        lambda **_kwargs: {"status": "FAIL"},
    )
    assert smoke.main([]) == 1
