from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import run_s146_object_storage_acceptance as runner


def test_acceptance_requires_explicit_opt_in(tmp_path: Path) -> None:
    result = runner.run_s146_object_storage_acceptance(
        {}, execute=False, report_path=tmp_path / "report.json"
    )
    assert result["status"] == "SKIPPED"
    assert runner.ENABLE_ENV in result["skip_reason"]


def test_acceptance_writes_only_redacted_pass_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    evidence = {
        "evidence_schema_version": runner.SCHEMA_VERSION,
        "status": "PASS",
        "decision": {"next_slice": "1462"},
    }
    monkeypatch.setattr(
        runner, "_execute_protected_acceptance", lambda *_args, **_kwargs: evidence
    )
    report = tmp_path / "report.json"
    result = runner.run_s146_object_storage_acceptance(
        {
            runner.ENABLE_ENV: "1",
            "NEX_CX_TEST_DATABASE_URL": "postgresql://private-value",
        },
        execute=True,
        report_path=report,
    )
    assert result == evidence
    assert json.loads(report.read_text()) == evidence
    assert "private-value" not in report.read_text()


def test_acceptance_redacts_failure_detail_and_leaks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        runner,
        "_execute_protected_acceptance",
        lambda *_args, **_kwargs: {"status": "PASS", "value": "private-value"},
    )
    leaked = runner.run_s146_object_storage_acceptance(
        {
            runner.ENABLE_ENV: "1",
            "NEX_CX_TEST_DATABASE_URL": "private-value",
        },
        execute=True,
        report_path=tmp_path / "not-written.json",
    )
    assert leaked["status"] == "FAIL"
    assert leaked["failure_code"] == "S146AcceptanceError"
    assert "private-value" not in json.dumps(leaked)

    monkeypatch.setattr(
        runner,
        "_execute_protected_acceptance",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("private")),
    )
    failed = runner.run_s146_object_storage_acceptance(
        {runner.ENABLE_ENV: "1"}, execute=True
    )
    assert failed["status"] == "FAIL"
    assert failed["failure_code"] == "RuntimeError"


def test_staging_secret_values_bind_test_databases_and_owner_credentials(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    bindings = [
        SimpleNamespace(input_kind="external_secret_reference", target_environment_name=name)
        for name in (
            "NEX_CX_DATABASE_URL",
            "NEX_CX_OBJECT_STORAGE_ACCESS_KEY",
            "NEX_CX_OBJECT_STORAGE_SECRET_KEY",
            "NEX_AE_OBJECT_STORAGE_ACCESS_KEY",
            "NEX_AE_OBJECT_STORAGE_SECRET_KEY",
            "NEX_MO_VLLM_API_KEY",
        )
    ]
    monkeypatch.setattr(
        runner,
        "load_production_configuration_manifest",
        lambda _root: SimpleNamespace(bindings=bindings),
    )
    monkeypatch.setattr(runner.s143, "_container_database_url", lambda value: f"container:{value}")
    values = runner._staging_secret_values(
        {"NEX_CX_TEST_DATABASE_URL": "postgresql://test"},
        root=tmp_path,
        cx_access="cx-access",
        cx_secret="cx-secret",
        ae_access="ae-access",
        ae_secret="ae-secret",
    )
    assert values["NEX_CX_DATABASE_URL"] == "container:postgresql://test"
    assert values["NEX_CX_OBJECT_STORAGE_ACCESS_KEY"] == "cx-access"
    assert values["NEX_AE_OBJECT_STORAGE_SECRET_KEY"] == "ae-secret"
    assert values["NEX_MO_VLLM_API_KEY"].startswith("s146-")

    monkeypatch.setattr(runner.s143, "_container_database_url", lambda _value: "")
    with pytest.raises(runner.S146AcceptanceError, match="protected input missing"):
        runner._staging_secret_values(
            {},
            root=tmp_path,
            cx_access="cx-access",
            cx_secret="cx-secret",
            ae_access="ae-access",
            ae_secret="ae-secret",
        )


def test_openbao_root_materialization_round_trip(tmp_path: Path) -> None:
    (tmp_path / "credentials").mkdir()

    class Admin:
        def __init__(self):
            self.value = None

        def request(self, method, _path, **kwargs):
            if method == "POST":
                self.value = kwargs["payload"]["data"]
                return {"data": {"version": 1}}
            return {"data": {"data": self.value}}

    admin = Admin()
    runner._materialize_root_credentials(
        admin,
        root_token="root-token",
        runtime_dir=tmp_path,
        access_key="root-access",
        secret_key="root-secret",
        sse_master_key="c3NlLW1hc3Rlci1rZXktdmFsdWU=",
    )
    assert (tmp_path / "credentials/rustfs-root.access-key").read_text().strip() == "root-access"
    assert (tmp_path / "credentials/rustfs-root.secret-key").stat().st_mode & 0o777 == 0o644
    assert (tmp_path / "credentials/rustfs-sse-s3.master-key").read_text().strip()

    class BrokenAdmin:
        def request(self, *_args, **_kwargs):
            return {}

    with pytest.raises(runner.S146AcceptanceError, match="materialization"):
        runner._materialize_root_credentials(
            BrokenAdmin(),
            root_token="root-token",
            runtime_dir=tmp_path,
            access_key="root-access",
            secret_key="root-secret",
            sse_master_key="c3NlLW1hc3Rlci1rZXktdmFsdWU=",
        )


def test_cross_bucket_admission_requires_two_denials() -> None:
    class Denied(Exception):
        def __init__(self, status=403):
            self.response = {"ResponseMetadata": {"HTTPStatusCode": status}}

    class Client:
        def __init__(self, denied=True):
            self.denied = denied

        def head_bucket(self, **_kwargs):
            if self.denied:
                raise Denied()
            return {}

    isolated = runner._cross_bucket_isolation(
        SimpleNamespace(client=Client()), SimpleNamespace(client=Client())
    )
    assert isolated == {"cx_to_ae_denied": True, "ae_to_cx_denied": True}
    assert runner._access_denied(Client(False), "bucket") is False
    with pytest.raises(runner.S146AcceptanceError, match="cross-bucket"):
        runner._cross_bucket_isolation(
            SimpleNamespace(client=Client(False)), SimpleNamespace(client=Client())
        )


def test_cleanup_removes_every_version_and_bucket() -> None:
    class Paginator:
        def paginate(self, *, Bucket):
            return [
                {
                    "Versions": [{"Key": f"{Bucket}/one", "VersionId": "v1"}],
                    "DeleteMarkers": [{"Key": f"{Bucket}/two", "VersionId": "v2"}],
                }
            ]

    class Client:
        def __init__(self):
            self.deleted = []

        def get_paginator(self, name):
            assert name == "list_object_versions"
            return Paginator()

        def delete_objects(self, **kwargs):
            self.deleted.extend(kwargs["Delete"]["Objects"])
            return {"Errors": []}

        def delete_bucket(self, *, Bucket):
            self.deleted.append(Bucket)

    client = Client()
    result = runner._cleanup_buckets(client, ("bucket-a", "bucket-b"))
    assert result["deleted_version_count"] == 4
    assert result["bucket_count"] == 2


def test_available_loopback_port_and_protected_value_filter() -> None:
    assert runner._available_loopback_port() > 0
    assert runner._protected_values(
        {
            "NEX_CX_TEST_DATABASE_URL": "private-db",
            "NEX_MO_VLLM_API_KEY": "private-key",
            "PUBLIC": "safe",
        }
    ) == {
        "NEX_CX_TEST_DATABASE_URL": "private-db",
        "NEX_MO_VLLM_API_KEY": "private-key",
    }
    with pytest.raises(runner.S146AcceptanceError, match="leaked"):
        runner._assert_redacted({"value": "private-db"}, {"db": "private-db"})
