from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import run_ae_web_authenticated_upload_fetch_smoke as smoke


def node_payload(
    *,
    status: str = "PASS",
    checks_passed: bool = True,
    live_network_used: bool = False,
    route: str = "/api/v1/uploads",
    fetch_call_count: int = 4,
) -> dict[str, object]:
    return {
        "smoke_schema_version": smoke.NODE_SMOKE_SCHEMA_VERSION,
        "status": status,
        "runner": {
            "mode": "deterministic_fake_fetch",
            "live_network_used": live_network_used,
            "postgresql_used": False,
            "browser_api_path": "/ae-api",
        },
        "workflow": {
            "schema_version": "ae_web_authenticated_upload_workflow.v1",
            "summary": {
                "checks_passed": checks_passed,
                "route": route,
                "upload_status": "QUEUED",
                "dedupe_status": "CREATED",
                "owner_scope_source": "oa_session_claims",
                "document_id_present": True,
            },
        },
        "request_observations": {
            "fetch_call_count": fetch_call_count,
            "upload_body_summary": {
                "filename": "slice-0273-upload.md",
                "owner_user_id": "user-slice-0273",
                "raw_source_included": False,
            },
            "routes": [
                {
                    "method": "GET",
                    "url": "/ae-api/api/v1/auth/session",
                    "credentials": "same-origin",
                },
                {
                    "method": "POST",
                    "url": "/ae-api/api/v1/auth/session/login",
                    "credentials": "same-origin",
                },
                {
                    "method": "POST",
                    "url": "/ae-api/api/v1/uploads",
                    "credentials": "same-origin",
                },
                {
                    "method": "POST",
                    "url": "/ae-api/api/v1/auth/session/logout",
                    "credentials": "same-origin",
                },
            ],
        },
        "checks": {
            "same_origin_sequence_matches": True,
            "upload_body_owner_from_session_claims": True,
            "upload_body_metadata_only": True,
            "live_network_not_used": True,
        },
    }


def completed(payload: object, returncode: int = 0) -> subprocess.CompletedProcess[str]:
    stdout = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.CompletedProcess(["node"], returncode, stdout=stdout, stderr="")


def protected_env() -> dict[str, str]:
    return {
        "NEX_AE_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_ae_user:secret-0273@127.0.0.1:5432/nex_ae_test"
        ),
        "NEX_CX_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_cx_user:secret-0273@127.0.0.1:5432/nex_cx_test"
        ),
        "NEX_OA_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_oa_user:secret-0273@127.0.0.1:5432/nex_oa_test"
        ),
        "NEX_AE_WEB_CREDENTIAL_LOGIN_PLAYWRIGHT_SMOKE_PASSWORD": "upload-secret-0273",
    }


def test_authenticated_upload_fetch_smoke_wraps_node_pass() -> None:
    calls: list[dict[str, object]] = []

    def fake_runner(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append({"cmd": cmd, **kwargs})
        return completed(node_payload())

    evidence = smoke.run_ae_web_authenticated_upload_fetch_smoke(
        {},
        runner=fake_runner,
    )

    assert evidence["status"] == "PASS"
    assert evidence["workflow"]["mode"] == "deterministic_fake_fetch"
    assert evidence["workflow"]["route"] == "/api/v1/uploads"
    assert evidence["workflow"]["fetch_call_count"] == 4
    assert evidence["checks"]["node_smoke_passed"] is True
    assert evidence["checks"]["upload_body_metadata_only"] is True
    assert calls[0]["cmd"] == ["node", str(smoke.NODE_SCRIPT)]
    assert calls[0]["cwd"] == smoke.ROOT
    assert smoke.summary_line(evidence) == (
        "ae_web_authenticated_upload_fetch_smoke=pass "
        "mode=deterministic_fake_fetch route=/api/v1/uploads "
        "status=QUEUED fetch_calls=4"
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
                node_payload(checks_passed=False)
            ),
            "node_evidence_invalid",
        ),
        (
            lambda *args, **kwargs: completed(node_payload(live_network_used=True)),
            "node_evidence_invalid",
        ),
        (
            lambda *args, **kwargs: completed(node_payload(route="/wrong")),
            "node_evidence_invalid",
        ),
        (
            lambda *args, **kwargs: completed(node_payload(fetch_call_count=3)),
            "node_evidence_invalid",
        ),
        (lambda *args, **kwargs: completed([]), "node_evidence_invalid"),
    ],
)
def test_authenticated_upload_fetch_smoke_maps_node_failures(
    runner: smoke.Runner,
    error: str,
) -> None:
    evidence = smoke.run_ae_web_authenticated_upload_fetch_smoke({}, runner=runner)

    assert evidence["status"] == "FAIL"
    assert evidence["reason"] == error
    assert evidence["node"]["error"] == error
    assert smoke.summary_line(evidence) == (
        f"ae_web_authenticated_upload_fetch_smoke=fail reason={error}"
    )


def test_authenticated_upload_fetch_smoke_maps_timeout_and_unavailable() -> None:
    def timeout_runner(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired("node", timeout=1)

    def missing_runner(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise OSError("node missing")

    assert (
        smoke.run_ae_web_authenticated_upload_fetch_smoke(
            {},
            runner=timeout_runner,
        )["reason"]
        == "node_timeout"
    )
    assert (
        smoke.run_ae_web_authenticated_upload_fetch_smoke(
            {},
            runner=missing_runner,
        )["reason"]
        == "node_unavailable"
    )


def test_authenticated_upload_fetch_smoke_redaction_output_and_main(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    env = protected_env()
    evidence = smoke.run_ae_web_authenticated_upload_fetch_smoke(
        env,
        runner=lambda *args, **kwargs: completed(node_payload()),
    )
    serialized = json.dumps(evidence, ensure_ascii=False)

    assert evidence["status"] == "PASS"
    assert "secret-0273" not in serialized
    assert "upload-secret-0273" not in serialized
    with pytest.raises(ValueError, match="NEX_AE_TEST_DATABASE_URL"):
        smoke.assert_smoke_evidence_redacted(env["NEX_AE_TEST_DATABASE_URL"], env)

    output_path = tmp_path / "smoke" / "evidence.json"
    smoke.write_smoke_evidence(output_path, evidence)
    assert json.loads(output_path.read_text(encoding="utf-8"))["status"] == "PASS"

    assert smoke.node_script_label(Path("/outside/node.mjs")) == "node.mjs"
    assert smoke.main(["--summary"]) == 0
    assert "ae_web_authenticated_upload_fetch_smoke=pass" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "write_smoke_evidence",
        lambda *_: (_ for _ in ()).throw(ValueError("redaction failed")),
    )
    assert smoke.main(["--output", str(tmp_path / "blocked.json")]) == 1
    assert "error=ValueError" in capsys.readouterr().out


def test_authenticated_upload_fetch_smoke_is_quality_gate_docs_and_package_wired() -> None:
    root = Path(__file__).parents[1]
    quality_gate = (root / "scripts" / "quality" / "run_quality_gate.sh").read_text(
        encoding="utf-8"
    )
    docs_index = (root / "docs" / "README.md").read_text(encoding="utf-8")
    ae_web_readme = (root / "apps" / "nex-ae-web" / "README.md").read_text(
        encoding="utf-8"
    )
    package = json.loads(
        (root / "apps" / "nex-ae-web" / "package.json").read_text(encoding="utf-8")
    )
    slice_doc = (
        root
        / "docs"
        / "slices"
        / "0273_ae_web_authenticated_upload_fetch_wiring.md"
    )

    assert "run_ae_web_authenticated_upload_fetch_smoke.py --summary" in quality_gate
    assert "0273_ae_web_authenticated_upload_fetch_wiring.md" in docs_index
    assert "Slice 0273" in ae_web_readme
    assert package["scripts"]["smoke:authenticated-upload-fetch"]
    assert slice_doc.exists()
