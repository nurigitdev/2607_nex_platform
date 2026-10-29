from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import build_canonical_platform_ae_runtime_image as image_build
import pytest
import run_canonical_platform_golden_journey as golden
import run_canonical_platform_installed_acceptance as installed
import run_canonical_platform_trust_admission as trust


ROOT = Path(__file__).resolve().parents[1]


class _Engine:
    def __init__(self, name: str = "engine") -> None:
        self.name = name
        self.disposed = False

    def dispose(self) -> None:
        self.disposed = True


def _targets() -> tuple[SimpleNamespace, ...]:
    return tuple(
        SimpleNamespace(
            target=SimpleNamespace(service_id=service_id),
            database_url=f"postgresql+psycopg://user:secret@localhost/{service_id}",
        )
        for service_id in (
            "nex-oa",
            "nex-ag",
            "nex-ae-api",
            "nex-cx",
            "nex-mo",
            "nex-wc",
            "nex-eos",
        )
    )


def test_s20_installed_acceptance_orchestrates_live_and_restart_hooks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    compose_calls: list[tuple[str, ...]] = []
    engines: list[_Engine] = []

    class Admin:
        def __init__(self, *_args, **_kwargs) -> None:
            self.requests: list[tuple[str, str]] = []

        def request(self, method: str, path: str, **_kwargs) -> None:
            self.requests.append((method, path))

    class Provisioned:
        materials = (SimpleNamespace(owner="nex-ae-api"),)

        @staticmethod
        def openbao_values_by_owner():
            return {"nex-ae-api": {"NEX_AE_DATABASE_URL": "private-value"}}

        @staticmethod
        def evidence():
            return {"status": "PASS", "principal_count": 1}

    monkeypatch.setattr(
        installed,
        "_load_json",
        lambda path: (
            {"release_manifest": {"release_set_digest": "sha256:release"}}
            if path.name == "images.json"
            else {"image": {"image_id": "sha256:ae"}}
        ),
    )
    monkeypatch.setattr(
        installed,
        "_image_environment_from_installed_runtime_reports",
        lambda *_args: {"NEX_AE_RUNTIME_IMAGE": "example/ae@sha256:ae"},
    )
    monkeypatch.setattr(installed, "resolve_demo_database_targets", lambda _env: _targets())
    monkeypatch.setattr(installed, "inspect_demo_database_targets", lambda *_args, **_kwargs: ())
    monkeypatch.setattr(
        installed,
        "demo_database_admission_public_projection",
        lambda _items: {"migration_current_count": 7, "state": "ADMITTED"},
    )
    monkeypatch.setattr(installed, "_pending_domain_counts", lambda _urls: {"pending": 0})
    monkeypatch.setattr(
        installed,
        "canonical_service_principal_specs",
        lambda: (SimpleNamespace(owner="nex-ae-api"),),
    )
    monkeypatch.setattr(installed, "prepare_staging_runtime_directory", lambda *_a, **_k: None)
    monkeypatch.setattr(
        installed,
        "_compose",
        lambda _env, *, root, arguments, check=True: compose_calls.append(tuple(arguments))
        or subprocess.CompletedProcess(arguments, 0, stdout="production_container_bootstrap=pass"),
    )
    monkeypatch.setattr(installed, "_wait_for_tls", lambda *_a, **_k: None)
    monkeypatch.setattr(installed, "OpenBaoAdminClient", Admin)
    monkeypatch.setattr(
        installed, "initialize_openbao", lambda *_a, **_k: SimpleNamespace(root_token="root")
    )
    monkeypatch.setattr(installed, "_secret_values", lambda *_a, **_k: {})
    monkeypatch.setattr(installed, "configure_openbao_staging", lambda *_a, **_k: None)
    monkeypatch.setattr(
        installed,
        "configure_canonical_runtime_approles",
        lambda *_a, **_k: {"status": "PASS"},
    )
    monkeypatch.setattr(installed, "refresh_openbao_approle_credentials", lambda *_a, **_k: None)
    monkeypatch.setattr(installed, "configure_openbao_s144_trust", lambda *_a, **_k: None)
    monkeypatch.setattr(installed, "refresh_openbao_s144_transit_credentials", lambda *_a, **_k: None)
    monkeypatch.setattr(installed, "_write_secret", lambda *_a, **_k: None)

    def create_engine(url, **_kwargs):
        engine = _Engine(str(url))
        engines.append(engine)
        return engine

    monkeypatch.setattr(installed, "create_engine", create_engine)
    monkeypatch.setattr(
        installed,
        "_provision_oa_trust",
        lambda *_a, **_k: (Provisioned(), "key-1", ("principal-1",)),
    )
    monkeypatch.setattr(
        installed,
        "_provision_demo_object_storage",
        lambda **_kwargs: {"status": "PASS", "bucket_count": 2},
    )
    monkeypatch.setattr(installed, "_service_readiness", lambda _dir: {"nex-oa": "READY"})
    heartbeat_calls = iter(
        (
            {"worker": {"status": "IDLE", "observed_at": "one"}},
            {"worker": {"status": "IDLE", "observed_at": "two"}},
        )
    )
    monkeypatch.setattr(installed, "_wait_for_heartbeats", lambda *_a, **_k: next(heartbeat_calls))
    monkeypatch.setattr(
        installed,
        "_signed_token_runtime_acceptance",
        lambda *_a, **_k: {"nex-oa": {"status": "PASS"}},
    )
    monkeypatch.setattr(installed, "_wait_for_service_readiness", lambda _dir: {"nex-oa": "READY"})
    monkeypatch.setattr(installed, "_bootstrap_log_counts", lambda *_a, **_k: {"worker": 1})
    monkeypatch.setattr(
        installed,
        "admit_demo_domain_runtime_evidence",
        lambda **_kwargs: {"status": "PASS", "process_count": 1, "signed_service_count": 1},
    )
    monkeypatch.setattr(installed, "_assert_redacted", lambda *_a, **_k: None)
    monkeypatch.setattr(installed, "_cleanup_oa_acceptance_rows", lambda *_a, **_k: None)

    live_calls: list[str] = []

    def live_hook(**_kwargs):
        live_calls.append("live")
        return {"status": "PASS", "checks": {"live": True}}

    def restart_hook(**_kwargs):
        live_calls.append("restart")
        return {"status": "PASS", "checks": {"restart": True}}

    result = installed.execute_canonical_platform_acceptance(
        {},
        root=ROOT,
        image_report_path=tmp_path / "images.json",
        ae_image_report_path=tmp_path / "ae.json",
        additional_services=("nex-mo",),
        live_hook=live_hook,
        restart_services=("worker", "worker"),
        post_restart_hook=restart_hook,
        worker_inventory={"worker": ("nex-ae-api", "worker-1", "AE")},
    )

    assert result["status"] == "PASS"
    assert result["extended_acceptance"]["checks"]["live"] is True
    assert result["post_restart_acceptance"]["checks"]["restart"] is True
    assert result["release_set_digest"] == "sha256:release"
    assert live_calls == ["live", "restart"]
    assert ("restart", "worker") in compose_calls
    assert compose_calls[-1] == ("down", "--volumes", "--remove-orphans")
    assert engines and all(engine.disposed for engine in engines)


def test_s20_golden_journey_runs_live_and_restart_projections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engines: list[_Engine] = []
    monkeypatch.setattr(golden, "resolve_demo_database_targets", lambda _env: _targets())

    def create_engine(url, **_kwargs):
        engine = _Engine(str(url))
        engines.append(engine)
        return engine

    monkeypatch.setattr(golden, "create_engine", create_engine)
    monkeypatch.setattr(golden, "_prepare_screenshot_directory", lambda _path: None)
    monkeypatch.setattr(golden, "_cleanup_dynamic_rows", lambda *_a, **_k: {})
    monkeypatch.setattr(golden, "_rotate_demo_credentials", lambda *_a, **_k: [{"credential_id": "one"}])
    monkeypatch.setattr(
        golden,
        "_fixture_visibility",
        lambda _engines: {
            "active_employee_count": 2,
            "nvt_project_count": 1,
            "project_count": 2,
            "project_membership_count": 2,
            "account_count": 2,
            "organization_unit_count": 4,
        },
    )
    monkeypatch.setattr(
        golden,
        "_activate_golden_a_capability",
        lambda *_a, **_k: {"status": "ACTIVE"},
    )
    browser_calls: list[str] = []

    def browser(_env, **kwargs):
        browser_calls.append("restart" if kwargs.get("recovery_interaction_id") else "live")
        return {
            "status": "PASS",
            "checks": {"browser": True},
            "runtime": {
                "interaction_id": "interaction-1",
                "result_projection": {
                    "result": {
                        "status": "SUCCEEDED",
                        "result_hash": "sha256:result",
                        "business_refs": ["EOS:VOUCHER:one"],
                        "delivery": {"state": "ACKNOWLEDGED"},
                    }
                },
            },
        }

    monkeypatch.setattr(golden, "_run_playwright", browser)
    projection = {
        "execution_state": "SUCCEEDED",
        "execution_phase": "FINALIZE",
        "agent_result_count": 1,
        "result_delivery_count": 1,
        "acknowledged_delivery_count": 1,
        "approval_decision_count": 1,
        "business_operation_count": 1,
        "voucher_count": 1,
        "voucher_line_count": 2,
    }
    monkeypatch.setattr(golden, "_database_acceptance_projection", lambda *_a, **_k: dict(projection))
    monkeypatch.setattr(golden, "_restore_demo_credentials", lambda *_a, **_k: None)
    monkeypatch.setattr(golden, "_delete_demo_sessions", lambda *_a, **_k: None)
    monkeypatch.setattr(golden, "_assert_zero_journey_residue", lambda *_a, **_k: None)
    monkeypatch.setattr(golden.installed, "_assert_redacted", lambda *_a, **_k: None)

    def installed_acceptance(_env, **kwargs):
        live = kwargs["live_hook"]()
        restarted = kwargs["post_restart_hook"]()
        return {
            "status": "PASS",
            "actual_postgres": True,
            "actual_compose": True,
            "actual_openbao": True,
            "actual_rustfs": True,
            "pre_activation_queue_counts": {"pending": 0},
            "post_restart_queue_counts": {"pending": 0},
            "extended_acceptance": live,
            "post_restart_acceptance": restarted,
        }

    monkeypatch.setattr(
        golden.installed,
        "execute_canonical_platform_acceptance",
        installed_acceptance,
    )

    result = golden.execute_canonical_platform_golden_journey({}, root=ROOT)

    assert result["status"] == "PASS"
    assert result["actual_remote_generation"] is True
    assert result["extended_acceptance"]["checks"]["one_voucher"] is True
    assert result["post_restart_acceptance"]["checks"]["one_voucher_after_restart"] is True
    assert browser_calls == ["live", "restart"]
    assert engines and all(engine.disposed for engine in engines)


def test_s20_trust_admission_orchestrates_rotation_and_restart(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    image_report = tmp_path / "images.json"
    image_report.write_text(
        json.dumps({"release_manifest": {"release_set_digest": "sha256:release"}}),
        encoding="utf-8",
    )
    compose_calls: list[tuple[str, ...]] = []
    owners = tuple(trust.CANONICAL_PLATFORM_OWNERS)
    provisioning = SimpleNamespace(root_token="root", owners=owners, secret_count=37)
    monkeypatch.setattr(
        trust,
        "canonical_platform_trust_projection",
        lambda: {"owner_count": len(owners), "secret_binding_count": 37},
    )
    monkeypatch.setattr(
        trust,
        "_source_admission",
        lambda _root, *, inventory: {
            "schema_version": trust.SCHEMA_VERSION,
            "inventory": dict(inventory),
            "source_admitted": True,
        },
    )
    monkeypatch.setattr(trust, "_image_environment_from_release_report", lambda _report: {})
    monkeypatch.setattr(trust, "prepare_staging_runtime_directory", lambda *_a, **_k: None)
    monkeypatch.setattr(
        trust,
        "_compose",
        lambda _env, *, root, arguments, check=True: compose_calls.append(tuple(arguments))
        or subprocess.CompletedProcess(arguments, 0, stdout="pass"),
    )
    monkeypatch.setattr(trust, "OpenBaoAdminClient", lambda *_a, **_k: object())
    monkeypatch.setattr(trust, "_synthetic_secret_values", lambda: {"ONE": "secret-one"})
    monkeypatch.setattr(trust, "provision_openbao_environment", lambda *_a, **_k: provisioning)
    generations = iter(
        (
            {"resolved_owner_count": len(owners), "dependency_readiness": {"state": "READY"}},
            {"resolved_owner_count": len(owners), "dependency_readiness": {"state": "READY"}},
        )
    )
    monkeypatch.setattr(trust, "_resolve_generation", lambda *_a, **_k: next(generations))
    monkeypatch.setattr(
        trust,
        "reactivate_openbao_after_restart",
        lambda *_a, **_k: {"status": "PASS"},
    )
    monkeypatch.setattr(trust, "refresh_openbao_approle_credentials", lambda *_a, **_k: None)
    monkeypatch.setattr(trust, "_cross_owner_denied", lambda _dir: True)
    monkeypatch.setattr(
        trust,
        "write_openbao_secret_generation",
        lambda *_a, **_k: {"ONE": 2},
    )
    monkeypatch.setattr(
        trust,
        "_certificate_hosts",
        lambda _dir: set(trust.CANONICAL_PLATFORM_TLS_HOSTS) | {"nex-staging.test"},
    )
    monkeypatch.setattr(trust, "_assert_redacted", lambda *_a, **_k: None)

    result = trust.run_canonical_platform_trust_admission(
        {trust.EXECUTION_ENV: "1"},
        execute=True,
        root=ROOT,
        image_report_path=image_report,
    )

    assert result["status"] == "PASS"
    assert result["openbao"]["generations_verified"] == [1, 2]
    assert result["openbao"]["restart_recovery"]["status"] == "PASS"
    assert result["pki"]["wc_eos_hosts_present"] is True
    assert result["release_set_digest"] == "sha256:release"
    assert ("restart", "openbao") in compose_calls
    assert compose_calls[-1] == ("down", "--volumes", "--remove-orphans")


def test_s20_canonical_ae_runtime_image_executes_bounded_build(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    bundle = SimpleNamespace(skill_source_directory="skill")
    report = tmp_path / "image.json"
    commands: list[list[str]] = []
    monkeypatch.setattr(image_build, "load_nsl_runtime_bundle", lambda _path: bundle)
    monkeypatch.setattr(image_build, "verify_nsl_runtime_bundle", lambda *_a, **_k: {"status": "PASS"})
    monkeypatch.setattr(
        image_build,
        "_build_current_ae_base",
        lambda *_a, **_k: ("example/ae:source", {"source_revision": "a" * 40}),
    )
    monkeypatch.setattr(image_build, "_stage_context", lambda *_a, **_k: None)
    monkeypatch.setattr(
        image_build.subprocess,
        "run",
        lambda command, **_kwargs: commands.append(list(command)),
    )
    image_id = "sha256:" + "a" * 64
    monkeypatch.setattr(
        image_build,
        "_json_command",
        lambda _command: [
            {
                "Id": image_id,
                "RepoDigests": [f"example/ae@{image_id}"],
                "Config": {"User": "65532:65532"},
            }
        ],
    )

    result = image_build.build_canonical_platform_ae_runtime_image(
        base_image="example/ae:base",
        output_image="example/ae:current",
        wheel_path=tmp_path / "nsl.whl",
        nsl_source=tmp_path,
        manifest_path=tmp_path / "manifest.json",
        report_path=report,
        build_current_base=True,
        execute=True,
    )

    assert result["status"] == "PASS"
    assert result["source_base"]["source_revision"] == "a" * 40
    assert result["image"]["runtime_user"] == "65532:65532"
    assert commands and "NEX_AE_BASE_RUNTIME_IMAGE=example/ae:source" in commands[0]
    assert json.loads(report.read_text(encoding="utf-8"))["status"] == "PASS"


class _ScalarResult:
    def __init__(self, scalar=0, mapping=None, row=None, rowcount=1) -> None:
        self.scalar = scalar
        self.mapping = mapping
        self.row = row
        self.rowcount = rowcount

    def scalar_one(self):
        return self.scalar

    def scalar_one_or_none(self):
        return self.scalar

    def mappings(self):
        return self

    def one_or_none(self):
        return self.mapping

    def one(self):
        return self.row


class _ConnectionContext:
    def __init__(self, connection) -> None:
        self.connection = connection

    def __enter__(self):
        return self.connection

    def __exit__(self, *_args) -> None:
        return None


def test_s20_installed_runtime_helpers_cover_network_queue_and_image_contracts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    materials = {
        "nex-ae-api": SimpleNamespace(credential_id="ae-cred", client_secret="ae-secret"),
        "nex-wc": SimpleNamespace(credential_id="wc-cred", client_secret="wc-secret"),
    }
    https_calls: list[tuple[str, str]] = []

    def https(host, path, **_kwargs):
        https_calls.append((host, path))
        if path == "/api/v1/auth/service-token":
            return 200, {"access_token": f"token-{len(https_calls)}"}
        return 200, {"status": "SIGNED_ONLY", "readiness_status": "READY"}

    monkeypatch.setattr(installed, "_https_json", https)
    runtimes = installed._signed_token_runtime_acceptance(tmp_path, materials=materials)
    readiness = installed._service_readiness(tmp_path)
    assert set(runtimes) == {"nex-oa", "nex-ae-api", "nex-wc", "nex-eos"}
    assert set(readiness) == {"nex-oa", "nex-ae-api", "nex-wc", "nex-eos"}

    heartbeat_row = {
        "service_id": "nex-ae-api",
        "worker_id": "worker-1",
        "worker_type": "AE",
        "status": "IDLE",
        "last_seen_at": "2026-10-29T00:00:00Z",
    }

    class Connection:
        def execute(self, statement, _params=None):
            sql = str(statement)
            if "service_worker_heartbeats" in sql:
                return _ScalarResult(mapping=heartbeat_row)
            return _ScalarResult(scalar=0)

    class Engine:
        def connect(self):
            return _ConnectionContext(Connection())

        def dispose(self):
            return None

    monkeypatch.setattr(installed, "create_engine", lambda *_a, **_k: Engine())
    urls = {"nex-ae-api": "postgresql://ae", "nex-wc": "postgresql://wc", "nex-eos": "postgresql://eos"}
    inventory = {"worker": ("nex-ae-api", "worker-1", "AE")}
    assert installed._pending_domain_counts(urls) == {
        "ae_runtime_jobs": 0,
        "wc_delivery_rows": 0,
        "eos_outbox_rows": 0,
    }
    observed = installed._heartbeats(urls, worker_inventory=inventory)
    assert observed["worker"]["status"] == "IDLE"
    assert installed._wait_for_heartbeats(
        urls, timeout_seconds=0.1, worker_inventory=inventory
    ) == observed

    monkeypatch.setattr(
        installed,
        "_compose",
        lambda *_a, **_k: subprocess.CompletedProcess([], 0, stdout="production_container_bootstrap=pass\n"),
    )
    assert all(value == 1 for value in installed._bootstrap_log_counts({}, root=ROOT).values())

    image_id = "sha256:" + "a" * 64
    artifacts = []
    for artifact_id in installed.CURRENT_ARTIFACT_REFERENCE_ENVIRONMENTS:
        artifacts.append(
            {
                "artifact_id": artifact_id,
                "local_tag": f"example/{artifact_id}:current",
                "image_id": image_id,
                "manifest_digest": image_id,
                "image_reference": f"example/{artifact_id}@{image_id}",
            }
        )
    release = {"status": "PASS", "image_build": {"artifacts": artifacts}}
    ae_release = next(item for item in artifacts if item["artifact_id"] == "nex-ae-runtime")
    ae_report = {
        "status": "PASS",
        "slice": "GB2-CA00-S18A",
        "base_image": ae_release["local_tag"],
        "image": {
            "image_id": image_id,
            "repo_digests": [f"example/nex-ae-runtime-product@{image_id}"],
        },
    }
    environment = installed._image_environment_from_installed_runtime_reports(
        release, ae_report
    )
    assert environment["NEX_AE_RUNTIME_IMAGE"].endswith(image_id)
    assert len(environment) == len(installed.CURRENT_ARTIFACT_REFERENCE_ENVIRONMENTS)


def test_s20_installed_transport_file_and_cli_helpers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    completed_commands: list[list[str]] = []
    monkeypatch.setattr(
        installed.subprocess,
        "run",
        lambda command, **_kwargs: completed_commands.append(list(command))
        or subprocess.CompletedProcess(command, 0, stdout="ok"),
    )
    completed = installed._compose({}, root=ROOT, arguments=("config",))
    assert completed.returncode == 0
    assert completed_commands[0][:3] == ["docker", "compose", "--project-name"]

    class Response:
        status = 200

        @staticmethod
        def read(_size):
            return b'{"status":"PASS"}'

    class Https:
        def __init__(self, *_args, **_kwargs) -> None:
            self.request_args = None

        def request(self, *args, **kwargs):
            self.request_args = (args, kwargs)

        @staticmethod
        def getresponse():
            return Response()

        @staticmethod
        def close():
            return None

    monkeypatch.setattr(installed.ssl, "create_default_context", lambda **_kwargs: object())
    monkeypatch.setattr(installed, "_ResolvedHttpsConnection", Https)
    status, payload = installed._https_json(
        "oa.nex-staging.test",
        "/ready",
        ca_file=tmp_path / "ca.crt",
        method="POST",
        body={"probe": True},
    )
    assert status == 200 and payload == {"status": "PASS"}

    secret = tmp_path / "secret"
    installed._write_secret(secret, "value")
    assert secret.read_text(encoding="utf-8") == "value\n"
    assert oct(secret.stat().st_mode & 0o777) == "0o644"
    report = tmp_path / "report.json"
    report.write_text('{"status":"PASS"}', encoding="utf-8")
    assert installed._load_json(report) == {"status": "PASS"}

    cli_report = tmp_path / "cli.json"
    monkeypatch.setattr(
        installed,
        "run_canonical_platform_installed_acceptance",
        lambda *_a, **_k: {"status": "PASS", "domain_acceptance": {}},
    )
    assert installed.main(["--summary", "--report", str(cli_report)]) == 0
    assert "canonical_platform_installed_acceptance=pass" in capsys.readouterr().out
    assert json.loads(cli_report.read_text(encoding="utf-8"))["status"] == "PASS"


def test_s20_golden_browser_credential_and_cleanup_helpers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    browser_evidence = {
        "status": "PASS",
        "checks": {"browser": True},
        "runtime": {"interaction_id": "interaction-1"},
    }
    monkeypatch.setattr(
        golden.subprocess,
        "run",
        lambda *_a, **_k: subprocess.CompletedProcess(
            [], 0, stdout=json.dumps(browser_evidence) + "\n", stderr=""
        ),
    )
    assert golden._run_playwright(
        {}, requester_password="requester", approver_password="approver"
    )["status"] == "PASS"
    assert golden._run_playwright(
        {},
        requester_password="requester",
        approver_password="approver",
        recovery_interaction_id="interaction-1",
    )["runtime"]["interaction_id"] == "interaction-1"
    assert golden._result_payload({"result_payload": {"state": "PASS"}}) == {
        "state": "PASS"
    }
    assert golden._result_payload({"result_payload": '{"state":"PASS"}'}) == {
        "state": "PASS"
    }
    assert golden._result_payload({"result_payload": "not-json"}) == {}

    executed: list[tuple[str, dict | None]] = []

    class CredentialConnection:
        def execute(self, statement, params=None):
            sql = str(statement)
            executed.append((sql, params))
            if sql.lstrip().startswith("SELECT credential_id"):
                return _ScalarResult(
                    mapping={
                        "credential_id": "credential-1",
                        "password_hash": "old",
                        "password_hash_algorithm": "argon2id",
                        "status": "ACTIVE",
                        "failed_attempt_count": 0,
                        "locked_at": None,
                        "password_changed_at": None,
                        "updated_at": None,
                    }
                )
            return _ScalarResult()

    class CredentialEngine:
        def begin(self):
            return _ConnectionContext(CredentialConnection())

    monkeypatch.setattr(golden, "hash_password", lambda password: f"hash:{password}")
    monkeypatch.setattr(golden, "password_hash_algorithm", lambda _value: "argon2id")
    engine = CredentialEngine()
    snapshots = golden._rotate_demo_credentials(engine, passwords={"1001": "new"})
    golden._restore_demo_credentials(engine, snapshots)
    golden._delete_demo_sessions(engine)
    assert snapshots[0]["credential_id"] == "credential-1"
    assert any("UPDATE oa_local_credentials" in sql for sql, _ in executed)
    assert any("DELETE FROM oa_user_sessions" in sql for sql, _ in executed)


def test_s20_trust_helpers_cover_source_image_compose_and_cli(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert trust._synthetic_secret_values()
    assert trust._resolver_environment(tmp_path, "nex-ae-api")[
        "NEX_OPENBAO_ROLE_ID_FILE"
    ].endswith("nex-ae-api.role-id")
    assert trust._reference("nex-ae-api", "VALUE", "v1").endswith("/VALUE@v1")

    image_id = "sha256:" + "b" * 64
    artifacts = [
        {"artifact_id": artifact_id, "image_reference": f"example/{artifact_id}@{image_id}"}
        for artifact_id in trust.CURRENT_ARTIFACT_REFERENCE_ENVIRONMENTS
    ]
    environment = trust._image_environment_from_release_report(
        {"status": "PASS", "image_build": {"artifacts": artifacts}}
    )
    assert "NEX_OA_RUNTIME_IMAGE" in environment
    assert "NEX_WA_RUNTIME_IMAGE" not in environment

    commands: list[list[str]] = []
    monkeypatch.setattr(
        trust.subprocess,
        "run",
        lambda command, **_kwargs: commands.append(list(command))
        or subprocess.CompletedProcess(command, 0, stdout="ok"),
    )
    assert trust._compose({}, root=ROOT, arguments=("config",)).returncode == 0
    assert commands[0][:4] == ["docker", "compose", "-p", trust.PROJECT_NAME]

    report = tmp_path / "trust.json"
    monkeypatch.setattr(
        trust,
        "run_canonical_platform_trust_admission",
        lambda **_kwargs: {
            "status": "PASS",
            "inventory": {"owner_count": 8, "secret_binding_count": 37},
        },
    )
    assert trust.main(["--summary", "--report", str(report)]) == 0
    assert "canonical_platform_trust=pass" in capsys.readouterr().out
    assert json.loads(report.read_text(encoding="utf-8"))["status"] == "PASS"


def test_s20_image_builder_cli_and_command_helpers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        image_build,
        "build_canonical_platform_ae_runtime_image",
        lambda **_kwargs: {"status": "PASS", "secret_included": False},
    )
    report = tmp_path / "image.json"
    assert (
        image_build.main(
            [
                "--base-image",
                "example/base:one",
                "--output-image",
                "example/output:one",
                "--report",
                str(report),
                "--execute",
            ]
        )
        == 0
    )
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        image_build.subprocess,
        "run",
        lambda *_a, **_k: subprocess.CompletedProcess([], 0, stdout='[{"Id":"one"}]'),
    )
    assert image_build._json_command(["docker", "inspect"]) == [{"Id": "one"}]
    monkeypatch.setattr(
        image_build.subprocess,
        "run",
        lambda *_a, **_k: subprocess.CompletedProcess([], 0, stdout="revision\n"),
    )
    assert image_build._text_command(["git", "rev-parse", "HEAD"]) == "revision\n"


def test_s20_installed_oa_trust_provisioning_uses_fresh_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    specs = (
        SimpleNamespace(principal_id="principal-existing"),
        SimpleNamespace(principal_id="principal-new"),
    )
    key_states: list[tuple[str, str]] = []
    provisioned = SimpleNamespace(materials=())

    class Keys:
        @staticmethod
        def list_keys():
            return {"items": []}

        @staticmethod
        def set_key_state(key_id, *, target_state, **_kwargs):
            key_states.append((key_id, target_state))

    monkeypatch.setattr(installed, "sessionmaker", lambda **_kwargs: object())
    monkeypatch.setattr(installed, "SqlAlchemyOaServicePrincipalRepository", lambda _factory: object())
    monkeypatch.setattr(installed, "OaServicePrincipalService", lambda _repository: object())
    monkeypatch.setattr(installed, "canonical_service_principal_specs", lambda: specs)
    monkeypatch.setattr(
        installed,
        "_existing_demo_principal_ids",
        lambda _engine, *, specs: {"principal-existing"},
    )
    monkeypatch.setattr(installed, "SqlAlchemyOaSignedTokenRepository", lambda _factory: object())
    monkeypatch.setattr(installed, "OaSigningKeyService", lambda **_kwargs: Keys())
    monkeypatch.setattr(installed.time, "time", lambda: 1_000_000)
    monkeypatch.setattr(
        installed,
        "provision_canonical_service_principals",
        lambda *_a, **_k: provisioned,
    )
    monkeypatch.setattr(installed, "OpenBaoTransitKeyProvisioner", lambda *_a, **_k: object())
    monkeypatch.setattr(installed, "register_openbao_transit_key_version", lambda *_a, **_k: None)

    result, key_id, created = installed._provision_oa_trust(
        object(),
        admin=object(),
        root_token="root",
        generation="v1",
        client_secrets={"nex-ae-api": "secret"},
    )

    assert result is provisioned
    assert key_id.startswith("canonical-platform-s10-")
    assert created == ("principal-new",)
    assert key_states == [(key_id, "ACTIVE")]


def test_s20_golden_cleanup_projection_and_zero_residue_contracts() -> None:
    class Connection:
        def __init__(self, owner: str) -> None:
            self.owner = owner

        def execute(self, statement, _params=None):
            sql = str(statement)
            if sql.lstrip().startswith("DELETE"):
                return _ScalarResult(rowcount=1)
            if self.owner == "nex-ae-api":
                if "execution.state" in sql:
                    return _ScalarResult(row=("SUCCEEDED", "FINALIZE", 1, 1, 1))
                return _ScalarResult(row=(0, 0, 0, 0, 0))
            if self.owner == "nex-wc":
                return _ScalarResult(scalar=1 if "decision='APPROVE'" in sql else 0)
            if "eos_voucher_draft_line" in sql:
                return _ScalarResult(row=(1, 1, 2))
            return _ScalarResult(scalar=0)

    class Engine:
        def __init__(self, owner: str) -> None:
            self.owner = owner

        def begin(self):
            return _ConnectionContext(Connection(self.owner))

        def connect(self):
            return _ConnectionContext(Connection(self.owner))

    engines = {
        owner: Engine(owner) for owner in ("nex-ae-api", "nex-wc", "nex-eos")
    }
    deleted = golden._cleanup_dynamic_rows(engines, tenant_id="VO00")
    projection = golden._database_acceptance_projection(
        engines, interaction_id="interaction-1"
    )
    golden._assert_zero_journey_residue(engines)

    assert deleted["ae:ae_workspace_activities"] == 1
    assert deleted["wc:wc_approval_work_item"] == 1
    assert any(key.startswith("eos:") for key in deleted)
    assert projection == {
        "execution_state": "SUCCEEDED",
        "execution_phase": "FINALIZE",
        "agent_result_count": 1,
        "result_delivery_count": 1,
        "acknowledged_delivery_count": 1,
        "approval_decision_count": 1,
        "business_operation_count": 1,
        "voucher_count": 1,
        "voucher_line_count": 2,
    }


def test_s20_trust_cross_owner_and_certificate_helpers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class Resolver:
        revoked = False

        def resolve(self, *_args, **_kwargs):
            raise trust.OpenBaoSecretResolverError("denied")

        def revoke(self):
            self.revoked = True

    resolver = Resolver()
    monkeypatch.setattr(trust, "build_openbao_secret_resolver", lambda _env: resolver)
    assert trust._cross_owner_denied(tmp_path) is True
    assert resolver.revoked is True

    class Names:
        @staticmethod
        def get_values_for_type(_kind):
            return ["oa.nex-staging.test", "wc.nex-staging.test"]

    class Extensions:
        @staticmethod
        def get_extension_for_class(_kind):
            return SimpleNamespace(value=Names())

    certificate = SimpleNamespace(extensions=Extensions())
    monkeypatch.setattr(
        trust.x509,
        "load_pem_x509_certificate",
        lambda _data: certificate,
    )
    cert_path = tmp_path / "tls/platform.crt"
    cert_path.parent.mkdir(parents=True)
    cert_path.write_bytes(b"certificate")
    assert trust._certificate_hosts(tmp_path) == {
        "oa.nex-staging.test",
        "wc.nex-staging.test",
    }


def test_s20_image_builder_stages_product_runtime_bundle(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source_root = tmp_path / "source"
    context = tmp_path / "context"
    context.mkdir()
    skill_root = tmp_path / "skills"
    (skill_root / "nested").mkdir(parents=True)
    (skill_root / "nested/skill.ns").write_text("skill", encoding="utf-8")
    wheel = tmp_path / "nsl.whl"
    wheel.write_bytes(b"wheel")
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    files = {
        "deployment/oci/canonical-platform-ae-runtime.Containerfile": "FROM scratch\n",
        "deployment/environments/finance-golden-a-vo00.v1.json": "{}\n",
        "deployment/environments/ae-product-capability-registry.v1.json": "{}\n",
        "deployment/locks/nsl-v0.2.1-wheel.json": "{}\n",
        "deployment/locks/python-production.lock": "lock\n",
    }
    for relative, content in files.items():
        path = source_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    monkeypatch.setattr(image_build, "ROOT", source_root)
    bundle = SimpleNamespace(
        wheel_filename="nsl.whl",
        skill_files=("nested/skill.ns",),
        admission_lock="deployment/locks/nsl-v0.2.1-wheel.json",
    )

    image_build._stage_context(
        context,
        bundle=bundle,
        wheel_path=wheel,
        skill_root=skill_root,
        manifest_path=manifest,
    )

    assert (context / "wheel/nsl.whl").read_bytes() == b"wheel"
    assert (context / "skill/nested/skill.ns").read_text(encoding="utf-8") == "skill"
    assert (context / "config/finance-golden-a-vo00.v1.json").is_file()
    assert (context / "locks/ae-product-nsl-runtime-bundle.v1.json").is_file()


def test_s20_installed_cleanup_lookup_and_loopback_helpers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Connection:
        def execute(self, _statement, params=None):
            value = params["principal_id"]
            return _ScalarResult(scalar=value if value == "existing" else None)

    class Engine:
        def connect(self):
            return _ConnectionContext(Connection())

    specs = (
        SimpleNamespace(principal_id="existing"),
        SimpleNamespace(principal_id="new"),
    )
    assert installed._existing_demo_principal_ids(Engine(), specs=specs) == {
        "existing"
    }

    cleanup_calls: list[dict] = []
    monkeypatch.setattr(
        installed,
        "_delete_oa_acceptance_rows",
        lambda _engine, **kwargs: cleanup_calls.append(kwargs),
    )
    installed._cleanup_oa_acceptance_rows(
        object(), provisioned=None, key_id=None, created_principal_ids=()
    )
    provisioned = SimpleNamespace(
        materials=(SimpleNamespace(credential_id="credential-1"),)
    )
    installed._cleanup_oa_acceptance_rows(
        object(),
        provisioned=provisioned,
        key_id="key-1",
        created_principal_ids=("principal-1",),
    )
    assert cleanup_calls[0]["credential_ids"] == ("credential-1",)

    observed_hosts: list[str] = []

    def resolver(host, port, *_args, **_kwargs):
        observed_hosts.append(host)
        return [(host, port)]

    monkeypatch.setattr(installed.socket, "getaddrinfo", resolver)
    monkeypatch.setenv("NO_PROXY", "localhost")
    monkeypatch.delenv("no_proxy", raising=False)
    with installed._object_hostname_loopback():
        installed.socket.getaddrinfo("object.nex-staging.test", 8443)
        assert "object.nex-staging.test" in os.environ["NO_PROXY"]
    assert observed_hosts == ["127.0.0.1"]
    assert os.environ["NO_PROXY"] == "localhost"
    assert "no_proxy" not in os.environ


def test_s20_installed_tls_wait_and_invalid_report_fail_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class SocketContext:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    class TlsContext:
        @staticmethod
        def wrap_socket(connection, **_kwargs):
            return connection

    monkeypatch.setattr(installed.ssl, "create_default_context", lambda **_k: TlsContext())
    monkeypatch.setattr(installed.socket, "create_connection", lambda *_a, **_k: SocketContext())
    installed._wait_for_tls(
        "127.0.0.1",
        8443,
        server_hostname="oa.nex-staging.test",
        ca_file=tmp_path / "ca.crt",
        timeout_seconds=0.1,
    )

    invalid = tmp_path / "invalid.json"
    invalid.write_text("[]", encoding="utf-8")
    with pytest.raises(installed.CanonicalPlatformInstalledAcceptanceError, match="object"):
        installed._load_json(invalid)


def test_s20_trust_resolution_redaction_and_image_fail_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict = {}

    def verify(provisioning, **kwargs):
        captured.update(kwargs)
        return {"resolved_owner_count": 8}

    monkeypatch.setattr(trust, "verify_openbao_runtime_resolution", verify)
    result = trust._resolve_generation(object(), tmp_path, version="v2")
    assert result["resolved_owner_count"] == 8
    assert captured["reference_version"] == "v2"
    assert captured["secret_generation"] == "secret:canonical-platform.2"

    with pytest.raises(trust.CanonicalPlatformTrustAdmissionError, match="raw secret"):
        trust._assert_redacted({"value": "private"}, {"one": "private"})
    with pytest.raises(trust.CanonicalPlatformTrustAdmissionError, match="not passing"):
        trust._image_environment_from_release_report({"status": "FAIL"})


def test_s20_direct_golden_cli_and_image_inspection_branches(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    report = tmp_path / "golden.json"
    monkeypatch.setattr(
        golden,
        "run_canonical_platform_golden_journey",
        lambda **_kwargs: {"status": "PASS", "executed": True},
    )
    monkeypatch.setattr(sys, "argv", ["golden", "--summary", "--report", str(report)])
    assert golden.main() == 0
    assert "canonical_platform_golden_journey=pass" in capsys.readouterr().out
    assert json.loads(report.read_text(encoding="utf-8"))["status"] == "PASS"

    monkeypatch.setattr(
        image_build,
        "_json_command",
        lambda _command: [{"Id": "sha256:one", "Config": {}}],
    )
    assert image_build._single_image_inspection("example/image:one")["Id"] == "sha256:one"
    monkeypatch.setattr(image_build, "_json_command", lambda _command: [])
    with pytest.raises(image_build.CanonicalPlatformAeImageBuildError, match="invalid"):
        image_build._single_image_inspection("example/image:missing")
    monkeypatch.setattr(image_build, "_json_command", lambda _command: ["not-a-map"])
    with pytest.raises(image_build.CanonicalPlatformAeImageBuildError, match="invalid"):
        image_build._single_image_inspection("example/image:invalid")


def test_s20_installed_transport_and_image_identity_fail_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        installed.subprocess,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(
            command, 2, stdout="compose failed safely"
        ),
    )
    with pytest.raises(installed.CanonicalPlatformInstalledAcceptanceError, match="compose failed"):
        installed._compose({}, root=ROOT, arguments=("up",))

    class Response:
        status = 200

        def __init__(self, body: bytes) -> None:
            self.body = body

        def read(self, _size):
            return self.body

    responses = iter((b"x" * 2_097_153, b"not-json", b"[]"))

    class Https:
        def __init__(self, *_args, **_kwargs) -> None:
            self.response = Response(next(responses))

        @staticmethod
        def request(*_args, **_kwargs):
            return None

        def getresponse(self):
            return self.response

        @staticmethod
        def close():
            return None

    monkeypatch.setattr(installed.ssl, "create_default_context", lambda **_kwargs: object())
    monkeypatch.setattr(installed, "_ResolvedHttpsConnection", Https)
    for message in ("too large", "invalid", "invalid"):
        with pytest.raises(installed.CanonicalPlatformInstalledAcceptanceError, match=message):
            installed._https_json("oa.nex-staging.test", "/ready", ca_file=tmp_path / "ca")

    image_id = "sha256:" + "a" * 64
    valid_artifacts = [
        {
            "artifact_id": artifact_id,
            "local_tag": f"example/{artifact_id}:current",
            "image_id": image_id,
            "manifest_digest": image_id,
        }
        for artifact_id in installed.CURRENT_ARTIFACT_REFERENCE_ENVIRONMENTS
    ]
    with pytest.raises(installed.CanonicalPlatformInstalledAcceptanceError, match="not passing"):
        installed._image_environment_from_installed_runtime_reports({}, {})
    with pytest.raises(installed.CanonicalPlatformInstalledAcceptanceError, match="coverage drift"):
        installed._image_environment_from_installed_runtime_reports(
            {"status": "PASS", "image_build": {"artifacts": valid_artifacts[:-1]}},
            {},
        )
    invalid_identity = [dict(item) for item in valid_artifacts]
    invalid_identity[0]["local_tag"] = "missing-tag"
    with pytest.raises(installed.CanonicalPlatformInstalledAcceptanceError, match="identity drift"):
        installed._image_environment_from_installed_runtime_reports(
            {"status": "PASS", "image_build": {"artifacts": invalid_identity}},
            {},
        )
    with pytest.raises(installed.CanonicalPlatformInstalledAcceptanceError, match="report is not passing"):
        installed._image_environment_from_installed_runtime_reports(
            {"status": "PASS", "image_build": {"artifacts": valid_artifacts}},
            {"status": "FAIL"},
        )


def test_s20_runtime_readiness_and_token_failures_are_bounded(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        installed,
        "_https_json",
        lambda *_a, **_k: (503, {"readiness_status": "BLOCKED"}),
    )
    with pytest.raises(installed.CanonicalPlatformInstalledAcceptanceError, match="not ready"):
        installed._service_readiness(tmp_path)

    materials = {
        "nex-ae-api": SimpleNamespace(credential_id="ae", client_secret="secret"),
        "nex-wc": SimpleNamespace(credential_id="wc", client_secret="secret"),
    }
    monkeypatch.setattr(installed, "_https_json", lambda *_a, **_k: (401, {}))
    with pytest.raises(installed.CanonicalPlatformInstalledAcceptanceError, match="exchange failed"):
        installed._signed_token_runtime_acceptance(tmp_path, materials=materials)

    calls = iter(((200, {"access_token": "token"}), (403, {"error_code": "denied"})))
    monkeypatch.setattr(installed, "_https_json", lambda *_a, **_k: next(calls))
    with pytest.raises(installed.CanonicalPlatformInstalledAcceptanceError, match="runtime admission"):
        installed._signed_token_runtime_acceptance(tmp_path, materials=materials)


def test_s20_golden_invalid_browser_output_and_residue_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        golden.subprocess,
        "run",
        lambda *_a, **_k: subprocess.CompletedProcess([], 0, stdout="not-json\n", stderr=""),
    )
    with pytest.raises(golden.CanonicalPlatformGoldenJourneyError, match="output is invalid"):
        golden._run_playwright(
            {}, requester_password="requester", approver_password="approver"
        )

    class Connection:
        def __init__(self, owner: str) -> None:
            self.owner = owner

        def execute(self, *_args, **_kwargs):
            if self.owner == "nex-ae-api":
                return _ScalarResult(row=(1, 0, 0, 0, 0))
            return _ScalarResult(scalar=0)

    class Engine:
        def __init__(self, owner: str) -> None:
            self.owner = owner

        def connect(self):
            return _ConnectionContext(Connection(self.owner))

    engines = {owner: Engine(owner) for owner in ("nex-ae-api", "nex-wc", "nex-eos")}
    with pytest.raises(golden.CanonicalPlatformGoldenJourneyError, match="durable residue"):
        golden._assert_zero_journey_residue(engines)


def test_s20_remaining_runtime_failure_branches_are_explicit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    failure = {"status": "FAIL", "failure_code": "browser_failed"}
    monkeypatch.setattr(
        golden.subprocess,
        "run",
        lambda *_a, **_k: subprocess.CompletedProcess(
            [], 1, stdout=json.dumps(failure) + "\n", stderr=""
        ),
    )
    assert golden._run_playwright(
        {}, requester_password="requester", approver_password="approver"
    ) == failure
    assert golden._result_payload({"result_payload": "[]"}) == {}

    class MissingCredentialConnection:
        @staticmethod
        def execute(*_args, **_kwargs):
            return _ScalarResult(mapping=None)

    class MissingCredentialEngine:
        @staticmethod
        def begin():
            return _ConnectionContext(MissingCredentialConnection())

    with pytest.raises(golden.CanonicalPlatformGoldenJourneyError, match="credential is missing"):
        golden._rotate_demo_credentials(
            MissingCredentialEngine(), passwords={"1001": "secret"}
        )

    monotonic = iter((0.0, 0.0, 2.0))
    monkeypatch.setattr(installed.time, "monotonic", lambda: next(monotonic))
    monkeypatch.setattr(installed.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        installed.ssl, "create_default_context", lambda **_kwargs: SimpleNamespace()
    )
    monkeypatch.setattr(
        installed.socket,
        "create_connection",
        lambda *_a, **_k: (_ for _ in ()).throw(OSError("offline")),
    )
    with pytest.raises(installed.CanonicalPlatformInstalledAcceptanceError, match="did not become ready"):
        installed._wait_for_tls(
            "127.0.0.1",
            8443,
            server_hostname="oa.nex-staging.test",
            ca_file=tmp_path / "ca.crt",
            timeout_seconds=1,
        )


def test_s20_ae_runtime_image_evidence_and_trust_compose_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image_id = "sha256:" + "c" * 64
    artifacts = [
        {
            "artifact_id": artifact_id,
            "local_tag": f"example/{artifact_id}:current",
            "image_reference": f"example/{artifact_id}@{image_id}",
            "image_id": image_id,
            "manifest_digest": image_id,
        }
        for artifact_id in installed.CURRENT_ARTIFACT_REFERENCE_ENVIRONMENTS
    ]
    release = {"status": "PASS", "image_build": {"artifacts": artifacts}}
    ae_release = next(item for item in artifacts if item["artifact_id"] == "nex-ae-runtime")
    cases = (
        (
            {
                "status": "PASS",
                "slice": "GB2-CA00-S18A",
                "base_image": "wrong/base:one",
                "image": {},
            },
            "base image drift",
        ),
        (
            {
                "status": "PASS",
                "slice": "GB2-CA00-S18A",
                "base_image": ae_release["local_tag"],
            },
            "evidence is unavailable",
        ),
        (
            {
                "status": "PASS",
                "slice": "GB2-CA00-S18A",
                "base_image": ae_release["local_tag"],
                "image": {"image_id": "bad", "repo_digests": []},
            },
            "identity is invalid",
        ),
    )
    for ae_report, message in cases:
        with pytest.raises(installed.CanonicalPlatformInstalledAcceptanceError, match=message):
            installed._image_environment_from_installed_runtime_reports(
                release, ae_report
            )

    monkeypatch.setattr(
        trust.subprocess,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(
            command, 2, stdout="trust compose failed"
        ),
    )
    with pytest.raises(trust.CanonicalPlatformTrustAdmissionError, match="trust compose failed"):
        trust._compose({}, root=ROOT, arguments=("up",))
    with pytest.raises(trust.CanonicalPlatformTrustAdmissionError, match="coverage drift"):
        trust._image_environment_from_release_report(
            {"status": "PASS", "image_build": {"artifacts": []}}
        )


def test_s20_image_builder_main_contains_build_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        image_build,
        "build_canonical_platform_ae_runtime_image",
        lambda **_kwargs: (_ for _ in ()).throw(ValueError("bounded build failure")),
    )
    assert (
        image_build.main(
            [
                "--base-image",
                "example/base:one",
                "--output-image",
                "example/output:one",
                "--execute",
            ]
        )
        == 2
    )
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "FAIL"
    assert output["registry_push_performed"] is False
