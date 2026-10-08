from __future__ import annotations

import json
import ssl
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

import run_platform_production_security_local_rehearsal as smoke
from nex_runtime.production_secret_materialization import SecretResolutionContext


def test_rehearsal_is_opt_in_and_profile_guarded() -> None:
    skipped = smoke.run_platform_production_security_local_rehearsal({})
    assert skipped["status"] == "SKIPPED"
    assert smoke.summary_line(skipped) == "platform_production_security_local_rehearsal=skip"
    blocked = smoke.run_platform_production_security_local_rehearsal(
        {smoke.ENABLE_ENV: "1", "NEX_PROFILE": "production"}
    )
    assert blocked["status"] == "FAIL"
    assert blocked["decision"]["next_slice"] == "blocked"


def test_actual_local_secret_rotation_tls_and_cleanup_rehearsal() -> None:
    result = smoke.run_platform_production_security_local_rehearsal(
        {smoke.ENABLE_ENV: "1", "NEX_PROFILE": "test"}
    )
    assert result["status"] == "PASS", result
    assert all(result["checks"].values())
    assert result["summary"] == {
        "secret_file_count": 40,
        "candidate_owner_process_count": 5,
        "rollback_owner_process_count": 5,
        "tls_probe_count": 3,
        "temporary_residue_count": 0,
    }
    assert result["decision"]["next_slice"] == "1431"
    serialized = json.dumps(result)
    assert "BEGIN PRIVATE KEY" not in serialized
    assert "Bearer " not in serialized


def test_executor_failure_failed_checks_and_main_paths(monkeypatch, capsys) -> None:
    failed = smoke.run_platform_production_security_local_rehearsal(
        {smoke.ENABLE_ENV: "1", "NEX_PROFILE": "test"},
        executor=lambda: (_ for _ in ()).throw(RuntimeError("raw-secret-value")),
    )
    assert failed["status"] == "FAIL"
    assert "raw-secret-value" not in json.dumps(failed)
    failed_check = smoke.run_platform_production_security_local_rehearsal(
        {smoke.ENABLE_ENV: "1", "NEX_PROFILE": "test"},
        executor=lambda: {"checks": {"one": False}, "summary": {}},
    )
    assert failed_check["status"] == "FAIL"
    assert smoke.summary_line(failed_check) == "platform_production_security_local_rehearsal=fail"
    empty = smoke.run_platform_production_security_local_rehearsal(
        {smoke.ENABLE_ENV: "1", "NEX_PROFILE": "test"},
        executor=lambda: {},
    )
    assert empty["status"] == "FAIL"

    monkeypatch.setattr(smoke, "run_platform_production_security_local_rehearsal", lambda: {"status": "SKIPPED"})
    assert smoke.main(["--summary"]) == 0
    assert "=skip" in capsys.readouterr().out
    monkeypatch.setattr(smoke, "run_platform_production_security_local_rehearsal", lambda: {"status": "FAIL"})
    assert smoke.main([]) == 1


def test_summary_and_main_pass_path(monkeypatch, capsys) -> None:
    passing = {
        "status": "PASS",
        "summary": {
            "candidate_owner_process_count": 5,
            "rollback_owner_process_count": 5,
            "tls_probe_count": 3,
            "temporary_residue_count": 0,
        },
    }
    assert smoke.summary_line(passing).endswith("residue=0 next=1431")
    monkeypatch.setattr(
        smoke, "run_platform_production_security_local_rehearsal", lambda: passing
    )
    assert smoke.main(["--summary"]) == 0
    assert "=pass" in capsys.readouterr().out


def test_private_value_evidence_guard_detects_leaks_and_empty_input() -> None:
    assert smoke._evidence_excludes_private_values(
        {"status": "PASS", "generation": "candidate"},
        ("current-private-value", "candidate-private-value"),
    )
    assert not smoke._evidence_excludes_private_values(
        {"status": "PASS", "detail": "candidate-private-value"},
        ("current-private-value", "candidate-private-value"),
    )
    assert not smoke._evidence_excludes_private_values({"status": "PASS"}, ())


def test_file_resolver_and_owner_process_fail_closed(tmp_path, monkeypatch) -> None:
    resolver = smoke._FileSecretResolver(tmp_path)
    context = SecretResolutionContext(
        owner="nex-oa",
        target_environment_name="../../outside",
        secret_generation="secret:test.1",
        reference_version="v1",
    )
    with pytest.raises(smoke.LocalRehearsalError, match="custody"):
        resolver.resolve("secret://local/value@v1", context=context)

    target = tmp_path / "v1" / "TARGET"
    target.parent.mkdir()
    target.write_text("value", encoding="utf-8")
    target.chmod(0o644)
    context = SecretResolutionContext(
        owner="nex-oa",
        target_environment_name="TARGET",
        secret_generation="secret:test.1",
        reference_version="v1",
    )
    with pytest.raises(smoke.LocalRehearsalError, match="custody"):
        resolver.resolve("secret://local/value@v1", context=context)

    class Materialization:
        secret_generation = "secret:test.1"

        @staticmethod
        def environment_for(owner):
            return {"TARGET": "value"}

    monkeypatch.setattr(
        smoke.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="", stderr=""),
    )
    with pytest.raises(smoke.LocalRehearsalError, match="owner process"):
        smoke._run_owner_processes(Materialization(), ("nex-oa",))


def test_tls_server_negative_paths_and_decision_guard(tmp_path, monkeypatch) -> None:
    cert, key = smoke._write_loopback_certificate(tmp_path, "negative")
    server = smoke._TlsHealthServer(cert, key)
    server.stop()

    server = smoke._TlsHealthServer(cert, key)
    try:
        server.start()
        context = ssl.create_default_context(cafile=str(cert))
        port = int(server.server.server_address[1])
        with pytest.raises(HTTPError):
            urlopen(
                f"https://127.0.0.1:{port}/missing",
                context=context,
                timeout=5,
            )
    finally:
        server.stop()

    class Response:
        status = 500

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        @staticmethod
        def read():
            return b'{}'

    server = smoke._TlsHealthServer(cert, key)
    monkeypatch.setattr(smoke, "urlopen", lambda *args, **kwargs: Response())
    with pytest.raises(smoke.LocalRehearsalError, match="TLS probe"):
        server.probe()
    server.stop()

    class FakeServer:
        def __init__(self, *args):
            pass

        def start(self):
            pass

        def probe(self):
            pass

        def stop(self):
            pass

    monkeypatch.setattr(smoke, "_TlsHealthServer", FakeServer)
    monkeypatch.setattr(
        smoke,
        "evaluate_production_tls_lifecycle",
        lambda *args, **kwargs: SimpleNamespace(status="OTHER"),
    )
    with pytest.raises(smoke.LocalRehearsalError, match="decision"):
        smoke._run_tls_rehearsal(tmp_path)
