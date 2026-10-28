from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
import run_p8_demo_s10_installed_domain_acceptance as acceptance
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]


def _urls() -> dict[str, str]:
    return {
        "nex-oa": "postgresql+psycopg://nex_oa_user:secret@127.0.0.1:5432/nex_oa_dev",
        "nex-ag": "postgresql+psycopg://nex_ag_user:secret@127.0.0.1:5432/nex_ag_dev",
        "nex-ae-api": "postgresql+psycopg://nex_ae_user:secret@127.0.0.1:5432/nex_ae_dev",
        "nex-cx": "postgresql+psycopg://nex_cx_user:secret@127.0.0.1:5432/nex_cx_dev",
        "nex-mo": "postgresql+psycopg://nex_mo_user:secret@127.0.0.1:5432/nex_mo_dev",
        "nex-wc": "postgresql+psycopg://nex_wc_user:secret@127.0.0.1:5432/nex_wc_dev",
        "nex-eos": "postgresql+psycopg://nex_eos_user:secret@127.0.0.1:5432/nex_eos_dev",
    }


def test_s10_source_admission_is_non_executing_and_business_neutral() -> None:
    result = acceptance.run_p8_demo_s10_installed_domain_acceptance(
        {}, execute=False, root=ROOT
    )

    assert result["status"] == "SOURCE_ADMITTED"
    assert result["executed"] is False
    assert result["domain_activation"]["process_count"] == 3
    assert result["new_business_behavior_added"] is False


def test_s10_source_admission_runs_in_a_standalone_python_process(
    tmp_path: Path,
) -> None:
    report = tmp_path / "standalone.json"

    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/deployment/run_p8_demo_s10_installed_domain_acceptance.py"),
            "--summary",
            "--report",
            str(report),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "p8_demo_s10_installed_domain=source_admitted" in completed.stdout
    assert json.loads(report.read_text(encoding="utf-8"))["source_admitted"] is True


def test_s10_execution_requires_both_switches_and_contains_failures() -> None:
    calls = []

    def runner(*args, **kwargs):
        calls.append((args, kwargs))
        return {
            "status": "PASS",
            "actual_postgres": True,
            "actual_openbao": True,
            "domain_acceptance": {"process_count": 3, "signed_service_count": 4},
        }

    skipped = acceptance.run_p8_demo_s10_installed_domain_acceptance(
        {}, execute=True, root=ROOT, protected_runner=runner
    )
    passed = acceptance.run_p8_demo_s10_installed_domain_acceptance(
        {acceptance.EXECUTION_ENV: "1"},
        execute=True,
        root=ROOT,
        protected_runner=runner,
    )
    failed = acceptance.run_p8_demo_s10_installed_domain_acceptance(
        {acceptance.EXECUTION_ENV: "1"},
        execute=True,
        root=ROOT,
        protected_runner=lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("bounded failure")
        ),
    )

    assert skipped["status"] == "SOURCE_ADMITTED"
    assert passed["status"] == "PASS"
    assert passed["executed"] is True
    assert len(calls) == 1
    assert failed["status"] == "FAIL"
    assert failed["issues"] == ["bounded failure"]
    assert failed["secret_included"] is False
    assert "consumers=3 signed=4" in acceptance.summary_line(passed)


def test_secret_material_covers_base_bindings_without_exposing_urls() -> None:
    values = acceptance._secret_values(
        {},
        urls=_urls(),
        object_credentials={
            "NEX_AE_OBJECT_STORAGE_ACCESS_KEY": "ae-access",
            "NEX_AE_OBJECT_STORAGE_SECRET_KEY": "ae-secret",
            "NEX_CX_OBJECT_STORAGE_ACCESS_KEY": "cx-access",
            "NEX_CX_OBJECT_STORAGE_SECRET_KEY": "cx-secret",
        },
    )

    assert values["NEX_AE_DATABASE_URL"].startswith(
        "postgresql+psycopg://nex_ae_user:secret@host.docker.internal"
    )
    assert len(values) == len(acceptance.DEMO_SECRET_BINDINGS)
    assert values["NEX_MO_VLLM_API_KEY"].startswith("unused-")
    with pytest.raises(acceptance.P8DemoS10AcceptanceError, match="PostgreSQL"):
        acceptance._container_database_url("sqlite:///local.db")


def test_demo_signing_key_window_honors_production_publication_lead() -> None:
    window = acceptance._signing_key_window(1_000_000)

    assert window["activate_at"] - window["published_at"] == 330
    assert window["sign_until"] > window["activate_at"]
    assert window["verify_until"] > window["sign_until"]


def test_demo_object_storage_bootstrap_provisions_two_private_owners(
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, str]] = []

    class Denied(Exception):
        def __init__(self):
            self.response = {"ResponseMetadata": {"HTTPStatusCode": 403}}

    class Client:
        def __init__(self, bucket):
            self.bucket = bucket

        def head_bucket(self, *, Bucket):
            if Bucket != self.bucket:
                raise Denied()
            return {}

    @dataclass(frozen=True)
    class Receipt:
        bucket: str

        def evidence(self):
            return {
                "schema_version": "private_bucket_bootstrap.v1",
                "status": "VERIFIED",
                "bucket_ref": "b" * 64,
                "created": True,
                "versioning_enabled": True,
                "encryption_algorithm": "AES256",
                "lifecycle_rule_count": 3,
                "policy_digest": "a" * 64,
            }

    class Iam:
        def provision_bucket_owner(self, *, access_key, secret_key, bucket, **_):
            assert access_key.endswith("-access")
            assert secret_key.endswith("-secret-value")
            calls.append((access_key, bucket))
            return {
                "schema_version": "rustfs_bucket_owner_provision.v1",
                "status": "PROVISIONED",
                "policy_name": f"{bucket}-rw",
                "bucket_scope_count": 1,
                "root_credential_reused": False,
            }

    result = acceptance._provision_demo_object_storage(
        runtime_dir=tmp_path,
        root_access="root-access",
        root_secret="root-secret-value",
        object_credentials={
            "NEX_AE_OBJECT_STORAGE_ACCESS_KEY": "ae-access",
            "NEX_AE_OBJECT_STORAGE_SECRET_KEY": "ae-private-secret-value",
            "NEX_CX_OBJECT_STORAGE_ACCESS_KEY": "cx-access",
            "NEX_CX_OBJECT_STORAGE_SECRET_KEY": "cx-private-secret-value",
        },
        client_builder=lambda settings: Client(settings.bucket),
        bucket_bootstrap=lambda _client, *, bucket: Receipt(bucket),
        iam_factory=lambda *_args, **_kwargs: Iam(),
    )

    assert result["status"] == "PASS"
    assert result["bucket_count"] == result["owner_identity_count"] == 2
    assert calls == [
        ("ae-access", "nex-ae-private"),
        ("cx-access", "nex-cx-private"),
    ]
    assert result["secret_included"] is False


def test_partial_oa_trust_cleanup_is_exact_and_residue_free() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE oa_signing_keys (key_id TEXT PRIMARY KEY)"))
        connection.execute(
            text(
                "CREATE TABLE oa_service_principals "
                "(principal_id TEXT PRIMARY KEY)"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE oa_service_creds "
                "(credential_id TEXT PRIMARY KEY, principal_id TEXT)"
            )
        )
        connection.execute(
            text("INSERT INTO oa_signing_keys VALUES ('target-key'), ('keep-key')")
        )
        connection.execute(
            text("INSERT INTO oa_service_principals VALUES ('target'), ('keep')")
        )
        connection.execute(
            text(
                "INSERT INTO oa_service_creds VALUES "
                "('target-cred', 'target'), ('keep-cred', 'keep')"
            )
        )

    acceptance._delete_oa_acceptance_rows(
        engine,
        credential_ids=("target-cred",),
        principal_ids=("target",),
        key_id="target-key",
    )

    with engine.connect() as connection:
        assert connection.execute(text("SELECT key_id FROM oa_signing_keys")).scalar_one() == "keep-key"
        assert connection.execute(
            text("SELECT principal_id FROM oa_service_principals")
        ).scalar_one() == "keep"
        assert connection.execute(
            text("SELECT credential_id FROM oa_service_creds")
        ).scalar_one() == "keep-cred"
    engine.dispose()


def test_evidence_redaction_and_atomic_report(tmp_path: Path) -> None:
    with pytest.raises(acceptance.P8DemoS10AcceptanceError, match="protected"):
        acceptance._assert_redacted(
            {"status": "PASS", "detail": "private-value"}, {"private-value"}
        )

    report = tmp_path / "s10.json"
    acceptance._write_report(report, {"status": "PASS", "secret_included": False})
    assert json.loads(report.read_text(encoding="utf-8"))["status"] == "PASS"


def test_s10_installed_acceptance_requires_restart_targets() -> None:
    with pytest.raises(
        acceptance.P8DemoS10AcceptanceError,
        match="restart services",
    ):
        acceptance._execute_protected_acceptance(
            {},
            root=ROOT,
            image_report_path=Path("images.json"),
            ae_image_report_path=Path("ae.json"),
            restart_services=(),
        )


def test_restart_readiness_waits_for_transient_proxy_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    attempts = iter(
        (
            acceptance.P8DemoS10AcceptanceError("Demo service is not ready"),
            {
                "nex-oa": "READY",
                "nex-ae-api": "READY",
                "nex-wc": "READY",
                "nex-eos": "READY",
            },
        )
    )

    def readiness(_runtime_dir):
        value = next(attempts)
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(acceptance, "_service_readiness", readiness)
    monkeypatch.setattr(acceptance.time, "sleep", lambda _seconds: None)

    assert acceptance._wait_for_service_readiness(tmp_path) == {
        "nex-oa": "READY",
        "nex-ae-api": "READY",
        "nex-wc": "READY",
        "nex-eos": "READY",
    }


def test_restart_readiness_timeout_is_bounded(tmp_path: Path) -> None:
    with pytest.raises(
        acceptance.P8DemoS10AcceptanceError,
        match="did not become ready after restart",
    ):
        acceptance._wait_for_service_readiness(tmp_path, timeout_seconds=0.0)
