from __future__ import annotations

import json
from pathlib import Path

import pytest

import run_ae_web_credential_login_browser_postgres_evidence_hardening as smoke
import run_ae_web_credential_login_browser_smoke_boundary as boundary


ROOT = Path(__file__).parents[1]
EXAMPLE_PATH = (
    ROOT
    / "contracts"
    / "examples"
    / "operations"
    / "ae_web_credential_login_browser_live_smoke_evidence.postgres_success.json"
)
NEGATIVE_PATH = (
    ROOT
    / "contracts"
    / "tests"
    / "negative"
    / "operations"
    / "ae_web_credential_login_browser_live_smoke_evidence.raw_database_url.json"
)


def protected_env() -> dict[str, str]:
    return {
        boundary.SMOKE_ENV: "1",
        boundary.PROFILE_ENV: boundary.DEFAULT_PROFILE,
        boundary.AE_WEB_URL_ENV: "http://127.0.0.1:5227",
        boundary.AE_API_BASE_URL_ENV: "http://127.0.0.1:8003",
        boundary.AE_DATABASE_URL_ENV: (
            "postgresql+psycopg://nex_ae_user:secret-pass-0266@127.0.0.1:5432/nex_ae_test"
        ),
        boundary.OA_DATABASE_URL_ENV: (
            "postgresql+psycopg://nex_oa_user:secret-pass-0266@127.0.0.1:5432/nex_oa_test"
        ),
        boundary.TENANT_ID_ENV: "tenant-slice-0266",
        boundary.EMPLOYEE_ID_ENV: "EMP-0266",
        boundary.PASSWORD_ENV: "browser-secret-0266",
    }


def live_pass_evidence() -> dict[str, object]:
    return json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))


def test_postgres_evidence_hardening_skips_by_default() -> None:
    evidence = smoke.run_ae_web_credential_login_browser_postgres_evidence_hardening({})

    assert evidence["status"] == "SKIPPED"
    assert smoke.summary_line(evidence) == (
        "ae_web_credential_login_browser_postgres_evidence_hardening=skipped "
        f"reason={boundary.SMOKE_ENV}"
    )


def test_postgres_evidence_hardening_passes_with_contract_and_invariants(
    tmp_path: Path,
) -> None:
    env = protected_env()
    evidence = smoke.run_ae_web_credential_login_browser_postgres_evidence_hardening(
        env,
        live_runner=lambda environ: live_pass_evidence(),
    )
    serialized = json.dumps(evidence, ensure_ascii=False, default=str)

    assert evidence["status"] == "PASS"
    assert evidence["contract"]["validated"] is True
    assert evidence["contract"]["schema_path"].endswith(
        "credential_login_browser_live_smoke_evidence.v1.schema.json"
    )
    assert evidence["postgres_evidence"]["database_envs"] == {
        "ae": boundary.AE_DATABASE_URL_ENV,
        "oa": boundary.OA_DATABASE_URL_ENV,
    }
    assert evidence["checks"]["contract_schema_valid"] is True
    assert evidence["checks"]["db_readback_proven"] is True
    assert evidence["checks"]["credential_password_verified"] is True
    assert evidence["checks"]["session_revocation_readback"] is True
    assert "secret-pass-0266" not in serialized
    assert "browser-secret-0266" not in serialized
    assert smoke.summary_line(evidence) == (
        "ae_web_credential_login_browser_postgres_evidence_hardening=pass "
        "profile=test "
        "schema=ae_web_credential_login_browser_live_smoke.v1 "
        "route_guard=allowed "
        "oa_session_status=REVOKED "
        "issues=0"
    )

    output_path = tmp_path / "hardening.json"
    smoke.write_hardening_evidence(output_path, evidence)
    assert json.loads(output_path.read_text(encoding="utf-8"))["status"] == "PASS"


@pytest.mark.parametrize("source_status", ["FAIL", "SKIPPED"])
def test_postgres_evidence_hardening_maps_live_non_pass(source_status: str) -> None:
    env = protected_env()
    evidence = smoke.run_ae_web_credential_login_browser_postgres_evidence_hardening(
        env,
        live_runner=lambda environ: {
            "smoke_schema_version": smoke.LIVE_SMOKE_SCHEMA_VERSION,
            "status": source_status,
        },
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "live_smoke_not_passed"
    assert evidence["source_smoke"]["status"] == source_status
    assert evidence["issue_count"] == 1


def test_postgres_evidence_hardening_reports_contract_errors_without_raw_values() -> None:
    env = protected_env()
    bad_evidence = live_pass_evidence()
    bad_evidence["redacted_database_urls"]["ae"] = (
        "postgresql+psycopg://nex_ae_user:secret-pass-0266@127.0.0.1:5432/nex_ae_test"
    )

    evidence = smoke.run_ae_web_credential_login_browser_postgres_evidence_hardening(
        env,
        live_runner=lambda environ: bad_evidence,
    )
    serialized = json.dumps(evidence, ensure_ascii=False, default=str)

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "evidence_hardening_failed"
    assert any(issue["category"] == "contract_schema" for issue in evidence["issues"])
    assert "secret-pass-0266" not in serialized


def test_postgres_evidence_hardening_reports_invariant_errors() -> None:
    env = protected_env()
    bad_evidence = live_pass_evidence()
    bad_evidence["migrations"]["ae"]["planned_count"] = 0
    bad_evidence["migrations"]["ae"]["skipped_count"] = 2
    bad_evidence["checks"]["route_guard_allowed"] = False

    evidence = smoke.run_ae_web_credential_login_browser_postgres_evidence_hardening(
        env,
        live_runner=lambda environ: bad_evidence,
    )

    assert evidence["status"] == "FAIL"
    assert evidence["issue_count"] >= 2
    assert {"migration_counts", "checks"}.issubset(
        {issue["category"] for issue in evidence["issues"]}
    )


def test_postgres_evidence_hardening_contract_fixtures_validate() -> None:
    schema = smoke.load_contract_schema()
    positive = live_pass_evidence()
    negative = json.loads(NEGATIVE_PATH.read_text(encoding="utf-8"))

    assert smoke.schema_issues(positive, schema) == []
    assert smoke.postgres_invariant_issues(positive) == []
    assert smoke.schema_issues(negative, schema)


def test_postgres_evidence_hardening_redaction_and_helpers(
    tmp_path: Path,
) -> None:
    env = protected_env()

    with pytest.raises(ValueError, match=boundary.PASSWORD_ENV):
        smoke.assert_hardening_evidence_redacted(
            f"leaked {env[boundary.PASSWORD_ENV]}",
            env,
        )

    assert smoke._json_path([]) == "$"
    assert smoke._json_path(["outer", 0, "inner"]) == "$.outer[0].inner"
    assert smoke._mapping([]) == {}
    assert smoke._int_value("not-int") == 0
    assert smoke._status({}) == "UNKNOWN"
    assert smoke.relative_label(Path("/tmp/outside-schema.json")) == "outside-schema.json"
    assert smoke.postgres_invariant_issues({})

    bad_schema = tmp_path / "schema.json"
    bad_schema.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON object schema"):
        smoke.load_contract_schema(bad_schema)


def test_postgres_evidence_hardening_main_summary_output_and_failures(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "evidence.json"
    monkeypatch.setattr(smoke, "load_env_file", lambda path: None)
    monkeypatch.setattr(
        smoke,
        "run_ae_web_credential_login_browser_postgres_evidence_hardening",
        lambda: {"smoke_schema_version": smoke.SCHEMA_VERSION, "status": "SKIPPED"},
    )

    assert smoke.main(["--summary", "--output", str(output_path)]) == 0
    assert "postgres_evidence_hardening=skipped" in capsys.readouterr().out
    assert json.loads(output_path.read_text(encoding="utf-8"))["status"] == "SKIPPED"

    monkeypatch.setattr(
        smoke,
        "run_ae_web_credential_login_browser_postgres_evidence_hardening",
        lambda: {
            "smoke_schema_version": smoke.SCHEMA_VERSION,
            "status": "FAIL",
            "failure_code": "evidence_hardening_failed",
            "issue_count": 2,
        },
    )
    assert smoke.main(["--summary"]) == 1
    assert "issues=2" in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_ae_web_credential_login_browser_postgres_evidence_hardening",
        lambda: (_ for _ in ()).throw(ValueError("redaction failed")),
    )
    assert smoke.main([]) == 1
    assert "error=ValueError" in capsys.readouterr().out


def test_postgres_evidence_hardening_is_quality_gate_and_docs_wired() -> None:
    quality_gate = (ROOT / "scripts" / "quality" / "run_quality_gate.sh").read_text(
        encoding="utf-8"
    )
    docs_index = (ROOT / "docs" / "README.md").read_text(encoding="utf-8")
    ae_web_readme = (ROOT / "apps" / "nex-ae-web" / "README.md").read_text(
        encoding="utf-8"
    )
    slice_doc = (
        ROOT
        / "docs"
        / "slices"
        / "0266_ae_web_credential_login_browser_postgres_evidence_hardening.md"
    )

    assert (
        "run_ae_web_credential_login_browser_postgres_evidence_hardening.py --summary"
        in quality_gate
    )
    assert "0266_ae_web_credential_login_browser_postgres_evidence_hardening.md" in (
        docs_index
    )
    assert "Slice 0266" in ae_web_readme
    assert slice_doc.exists()
