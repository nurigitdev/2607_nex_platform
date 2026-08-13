from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import run_ae_web_credential_login_browser_harness_smoke as smoke
import run_ae_web_credential_login_browser_smoke_boundary as boundary


def node_payload(
    *,
    status: str = "PASS",
    route_guard_status: str = "allowed",
    live_network_used: bool = False,
) -> dict[str, object]:
    return {
        "smoke_schema_version": smoke.NODE_SMOKE_SCHEMA_VERSION,
        "status": status,
        "runner": {
            "mode": "deterministic_fake_fetch",
            "live_network_used": live_network_used,
            "postgresql_used": False,
        },
        "harness": {
            "summary": {
                "route_guard_status": route_guard_status,
                "fetch_call_count": 3,
                "login_route": "/api/v1/auth/session/login",
                "current_session_status": "anonymous",
                "authenticated_session_status": "authenticated",
                "logout_session_status": "anonymous",
            },
            "fetch_calls": [
                {
                    "url": "/ae-api/api/v1/auth/session",
                    "method": "GET",
                    "credentials": "same-origin",
                    "request_body_redacted": False,
                },
                {
                    "url": "/ae-api/api/v1/auth/session/login",
                    "method": "POST",
                    "credentials": "same-origin",
                    "request_body_redacted": True,
                },
                {
                    "url": "/ae-api/api/v1/auth/session/logout",
                    "method": "POST",
                    "credentials": "same-origin",
                    "request_body_redacted": False,
                },
            ],
        },
        "checks": {
            "route_guard_allowed": route_guard_status == "allowed",
            "login_body_redacted": True,
            "logout_returns_anonymous": True,
        },
    }


def completed(payload: object, returncode: int = 0) -> subprocess.CompletedProcess[str]:
    stdout = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.CompletedProcess(["node"], returncode, stdout=stdout, stderr="")


def protected_env() -> dict[str, str]:
    return {
        boundary.SMOKE_ENV: "1",
        boundary.PROFILE_ENV: boundary.DEFAULT_PROFILE,
        boundary.AE_WEB_URL_ENV: "http://127.0.0.1:5227",
        boundary.AE_API_BASE_URL_ENV: "http://127.0.0.1:8003",
        boundary.AE_DATABASE_URL_ENV: (
            "postgresql+psycopg://nex_ae_user:secret-pass-0263@127.0.0.1:5432/nex_ae_test"
        ),
        boundary.OA_DATABASE_URL_ENV: (
            "postgresql+psycopg://nex_oa_user:secret-pass-0263@127.0.0.1:5432/nex_oa_test"
        ),
        boundary.TENANT_ID_ENV: "tenant-slice-0263",
        boundary.EMPLOYEE_ID_ENV: "EMP-0263",
        boundary.PASSWORD_ENV: "browser-secret-0263",
    }


def test_harness_smoke_runs_node_evidence_with_boundary_skip() -> None:
    calls: list[dict[str, object]] = []

    def fake_runner(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append({"cmd": cmd, **kwargs})
        return completed(node_payload())

    evidence = smoke.run_ae_web_credential_login_browser_harness_smoke(
        {},
        runner=fake_runner,
        timeout_seconds=2.0,
    )

    assert evidence["status"] == "PASS"
    assert evidence["boundary"]["status"] == "SKIPPED"
    assert evidence["node"]["status"] == "PASS"
    assert evidence["harness"]["route_guard_status"] == "allowed"
    assert evidence["harness"]["fetch_call_count"] == 3
    assert evidence["checks"]["node_harness_passed"] is True
    assert evidence["checks"]["login_body_redacted"] is True
    assert calls[0]["cmd"] == ["node", str(smoke.NODE_SCRIPT)]
    assert calls[0]["cwd"] == smoke.ROOT_DIR
    assert smoke.summary_line(evidence) == (
        "ae_web_credential_login_browser_harness_smoke=pass "
        "boundary=skipped route_guard=allowed fetch_calls=3"
    )


def test_harness_smoke_respects_boundary_fail_without_running_node() -> None:
    def forbidden_runner(**kwargs: object) -> subprocess.CompletedProcess[str]:
        raise AssertionError("node should not run")

    evidence = smoke.run_ae_web_credential_login_browser_harness_smoke(
        {boundary.SMOKE_ENV: "1"},
        runner=forbidden_runner,
    )

    assert evidence["status"] == "FAIL"
    assert evidence["reason"] == "boundary_invalid"
    assert evidence["node"]["status"] == "NOT_RUN"
    assert smoke.summary_line(evidence) == (
        "ae_web_credential_login_browser_harness_smoke=fail "
        "reason=boundary_invalid"
    )


@pytest.mark.parametrize(
    ("runner", "error"),
    [
        (
            lambda *args, **kwargs: completed(node_payload(), returncode=2),
            "node_failed",
        ),
        (lambda *args, **kwargs: completed("{not-json"), "node_json_invalid"),
        (
            lambda *args, **kwargs: completed(
                node_payload(route_guard_status="blocked")
            ),
            "node_evidence_invalid",
        ),
        (
            lambda *args, **kwargs: completed(
                node_payload(live_network_used=True)
            ),
            "node_evidence_invalid",
        ),
    ],
)
def test_harness_smoke_maps_node_failures(
    runner: smoke.Runner,
    error: str,
) -> None:
    evidence = smoke.run_ae_web_credential_login_browser_harness_smoke(
        {},
        runner=runner,
    )

    assert evidence["status"] == "FAIL"
    assert evidence["reason"] == error
    assert evidence["node"]["error"] == error


def test_harness_smoke_maps_node_timeout_and_unavailable() -> None:
    def timeout_runner(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired("node", timeout=1)

    def missing_runner(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise OSError("node missing")

    assert (
        smoke.run_ae_web_credential_login_browser_harness_smoke(
            {},
            runner=timeout_runner,
        )["reason"]
        == "node_timeout"
    )
    assert (
        smoke.run_ae_web_credential_login_browser_harness_smoke(
            {},
            runner=missing_runner,
        )["reason"]
        == "node_unavailable"
    )


def test_harness_smoke_redaction_and_output(tmp_path: Path) -> None:
    env = protected_env()
    evidence = smoke.run_ae_web_credential_login_browser_harness_smoke(
        env,
        runner=lambda *args, **kwargs: completed(node_payload()),
    )
    serialized = json.dumps(evidence, ensure_ascii=False)

    assert evidence["status"] == "PASS"
    assert evidence["boundary"]["status"] == "PASS"
    assert "browser-secret-0263" not in serialized
    assert "secret-pass-0263" not in serialized
    with pytest.raises(ValueError, match=boundary.PASSWORD_ENV):
        smoke.assert_smoke_evidence_redacted(
            f"leaked {env[boundary.PASSWORD_ENV]}",
            env,
        )

    output_path = tmp_path / "smoke" / "evidence.json"
    smoke.write_smoke_evidence(output_path, evidence)
    assert json.loads(output_path.read_text(encoding="utf-8"))["status"] == "PASS"


def test_harness_smoke_local_redaction_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = protected_env()
    monkeypatch.setattr(smoke, "assert_boundary_evidence_redacted", lambda *_: None)

    with pytest.raises(ValueError, match=boundary.EMPLOYEE_ID_ENV):
        smoke.assert_smoke_evidence_redacted(
            f"leaked {env[boundary.EMPLOYEE_ID_ENV]}",
            env,
        )


def test_harness_smoke_main_summary_output_and_failures(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "evidence.json"

    assert (
        smoke.main(
            ["--summary", "--output", str(output_path)],
            runner=lambda *args, **kwargs: completed(node_payload()),
        )
        == 0
    )
    assert "ae_web_credential_login_browser_harness_smoke=pass" in (
        capsys.readouterr().out
    )
    assert json.loads(output_path.read_text(encoding="utf-8"))["status"] == "PASS"

    assert (
        smoke.main(
            ["--summary", "--node-script", str(tmp_path / "custom.mjs")],
            runner=lambda *args, **kwargs: completed(node_payload(), returncode=1),
        )
        == 1
    )
    assert "reason=node_failed" in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "write_smoke_evidence",
        lambda *_: (_ for _ in ()).throw(ValueError("redaction failed")),
    )
    assert (
        smoke.main(
            ["--output", str(tmp_path / "blocked.json")],
            runner=lambda *args, **kwargs: completed(node_payload()),
        )
        == 1
    )
    assert "error=ValueError" in capsys.readouterr().out


def test_harness_smoke_checker_is_quality_gate_and_docs_wired() -> None:
    root = Path(__file__).parents[1]
    quality_gate = (root / "scripts" / "quality" / "run_quality_gate.sh").read_text(
        encoding="utf-8"
    )
    docs_index = (root / "docs" / "README.md").read_text(encoding="utf-8")
    slice_doc = (
        root
        / "docs"
        / "slices"
        / "0263_ae_web_credential_login_browser_harness_smoke.md"
    ).read_text(encoding="utf-8")

    assert "run_ae_web_credential_login_browser_harness_smoke.py --summary" in (
        quality_gate
    )
    assert "0263_ae_web_credential_login_browser_harness_smoke.md" in docs_index
    assert "runCredentialLoginBrowserHarnessSmoke.mjs" in slice_doc
    assert smoke.NODE_SMOKE_SCHEMA_VERSION in slice_doc
