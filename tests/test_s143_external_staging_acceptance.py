from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import run_s143_external_staging_acceptance as smoke
import yaml


ROOT = Path(__file__).resolve().parents[1]


def _protected_environment() -> dict[str, str]:
    return {
        "NEX_OA_TEST_DATABASE_URL": (
            "postgresql+psycopg://user:password@127.0.0.1:5432/nex_oa_test"
        ),
        "NEX_AG_TEST_DATABASE_URL": (
            "postgresql+psycopg://user:password@127.0.0.1:5432/nex_ag_test"
        ),
        "NEX_AE_TEST_DATABASE_URL": (
            "postgresql+psycopg://user:password@127.0.0.1:5432/nex_ae_test"
        ),
        "NEX_CX_TEST_DATABASE_URL": (
            "postgresql+psycopg://user:password@127.0.0.1:5432/nex_cx_test"
        ),
        "NEX_MO_TEST_DATABASE_URL": (
            "postgresql+psycopg://user:password@127.0.0.1:5432/nex_mo_test"
        ),
        "NEX_MO_REMOTE_EMBEDDING_API_KEY": "provider-key-embedding",
        "NEX_MO_REMOTE_RERANKER_API_KEY": "provider-key-reranker",
        "NEX_MO_VLLM_API_KEY": "provider-key-generation",
    }


def test_protected_acceptance_is_opt_in() -> None:
    result = smoke.run_s143_external_staging_acceptance({}, execute=False)
    assert result["status"] == "SKIPPED"
    assert smoke.summary_line(result) == "s143_external_staging_acceptance=skipped"


def test_protected_acceptance_orchestrates_rotation_tls_and_rollback(
    tmp_path,
    monkeypatch,
) -> None:
    environment = {**_protected_environment(), smoke.ENABLE_ENV: "1"}
    secret_values = smoke._staging_secret_values(environment, root=ROOT)
    report_path = tmp_path / "acceptance.json"
    serials = iter(("222", "111"))

    monkeypatch.setattr(
        smoke,
        "validate_s143_compose_assets",
        lambda root: {
            "status": "VALID",
            "tls_route_count": 9,
            "raw_secret_values_included": False,
        },
    )
    monkeypatch.setattr(smoke, "_staging_secret_values", lambda *args, **kwargs: secret_values)
    monkeypatch.setattr(
        smoke,
        "run_platform_test_migration_readiness",
        lambda env: {"status": "PASS", "summary": {"service_count": 5}},
    )
    monkeypatch.setattr(
        smoke,
        "_image_environment",
        lambda root: (
            {name: f"local/image@sha256:{index:064x}" for index, name in enumerate(smoke.IMAGE_ENV_BY_ARTIFACT.values(), 1)},
            "sha256:" + "f" * 64,
        ),
    )
    monkeypatch.setattr(smoke, "_compose", lambda *args, **kwargs: None)
    monkeypatch.setattr(smoke, "_wait_for_tls", lambda *args, **kwargs: None)
    monkeypatch.setattr(smoke, "OpenBaoAdminClient", lambda *args, **kwargs: object())
    monkeypatch.setattr(
        smoke,
        "initialize_openbao",
        lambda *args, **kwargs: type(
            "Bootstrap",
            (),
            {"root_token": "root-token-12345678"},
        )(),
    )
    monkeypatch.setattr(
        smoke,
        "configure_openbao_staging",
        lambda *args, **kwargs: {
            "owner_count": 5,
            "secret_count": 20,
            "certificate_serial": "01:11",
        },
    )
    monkeypatch.setattr(smoke, "_compose_up_platform", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        smoke,
        "_service_acceptance",
        lambda *args, **kwargs: list(smoke.API_HOSTS) + ["ae.nex-staging.test"],
    )
    monkeypatch.setattr(
        smoke,
        "_provider_acceptance",
        lambda *args, **kwargs: {
            "status": "PASS",
            "capabilities": {
                "embedding": {},
                "reranking": {},
                "generation": {},
            },
            "provider_api_key_included": False,
        },
    )
    monkeypatch.setattr(
        smoke,
        "refresh_openbao_approle_credentials",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(smoke, "_verify_openbao_owner_isolation", lambda *args: True)
    monkeypatch.setattr(
        smoke,
        "write_openbao_secret_generation",
        lambda *args, **kwargs: {name: 2 for name in secret_values},
    )
    monkeypatch.setattr(
        smoke,
        "_compose_recreate_python",
        lambda *args, **kwargs: None,
    )

    def issue(*args, runtime_dir, **kwargs):
        (runtime_dir / "tls/platform.crt").write_bytes(b"renewed-certificate")
        (runtime_dir / "tls/platform.key").write_bytes(b"renewed-key")
        return {"serial_number": "02:22"}

    monkeypatch.setattr(smoke, "issue_openbao_platform_certificate", issue)
    monkeypatch.setattr(smoke, "_wait_compose_healthy", lambda *args, **kwargs: None)
    monkeypatch.setattr(smoke, "_peer_certificate_serial", lambda *args: next(serials))

    result = smoke.run_s143_external_staging_acceptance(
        environment,
        execute=True,
        root=ROOT,
        report_path=report_path,
    )

    assert result["status"] == "PASS"
    assert result["openbao"]["generations_verified"] == [1, 2, 1]
    assert result["tls"]["observed_renewed_serial"] == "222"
    assert result["tls"]["rollback_serial"] == "111"
    assert json.loads(report_path.read_text(encoding="utf-8"))["status"] == "PASS"


def test_protected_acceptance_sanitizes_preflight_failure(monkeypatch) -> None:
    environment = {**_protected_environment(), smoke.ENABLE_ENV: "1"}
    monkeypatch.setattr(
        smoke,
        "validate_s143_compose_assets",
        lambda root: {"status": "VALID"},
    )
    monkeypatch.setattr(
        smoke,
        "run_platform_test_migration_readiness",
        lambda env: {"status": "FAIL", "service_count": 5},
    )

    result = smoke.run_s143_external_staging_acceptance(
        environment,
        execute=True,
    )

    assert result["status"] == "FAIL"
    assert result["decision"]["external_staging_acceptance_passed"] is False


def test_secret_input_mapping_is_complete_owner_scoped_and_container_routable() -> None:
    values = smoke._staging_secret_values(_protected_environment(), root=ROOT)
    rotated = smoke._rotated_secret_values(values)

    assert len(values) == 20
    assert "@host.docker.internal:5432/" in values["NEX_CX_DATABASE_URL"]
    assert values["NEX_MO_VLLM_API_KEY"] == "provider-key-generation"
    assert rotated["NEX_CX_DATABASE_URL"] == values["NEX_CX_DATABASE_URL"]
    assert rotated["NEX_MO_VLLM_API_KEY"] == values["NEX_MO_VLLM_API_KEY"]
    assert rotated["NEX_AE_TO_CX_SERVICE_TOKEN"] != values[
        "NEX_AE_TO_CX_SERVICE_TOKEN"
    ]


def test_secret_input_mapping_fails_closed() -> None:
    environment = _protected_environment()
    environment.pop("NEX_CX_TEST_DATABASE_URL")
    with pytest.raises(smoke.ExternalStagingAcceptanceError, match="missing"):
        smoke._staging_secret_values(environment, root=ROOT)
    with pytest.raises(smoke.ExternalStagingAcceptanceError, match="local"):
        smoke._container_database_url(
            "postgresql+psycopg://user:password@db.example:5432/nex"
        )
    assert smoke._container_database_url("") == ""


def test_base_compose_tracks_current_object_storage_manifest() -> None:
    compose = yaml.safe_load(smoke.COMPOSE_FILE.read_text(encoding="utf-8"))
    environment = compose["x-platform-environment"]

    assert {
        "NEX_CX_OBJECT_STORAGE_ACCESS_KEY_REF",
        "NEX_CX_OBJECT_STORAGE_SECRET_KEY_REF",
        "NEX_AE_OBJECT_STORAGE_ACCESS_KEY_REF",
        "NEX_AE_OBJECT_STORAGE_SECRET_KEY_REF",
        "NEX_CX_OBJECT_STORAGE_ENDPOINT",
        "NEX_AE_OBJECT_STORAGE_ENDPOINT",
    }.issubset(environment)


def test_migration_projection_accepts_runtime_result_and_rejects_drift() -> None:
    projection = {"status": "PASS", "summary": {"service_count": 5}}
    result = type(
        "MigrationResult",
        (),
        {"to_public_projection": lambda self: projection},
    )()
    assert smoke._migration_projection(result) == projection
    assert smoke._migration_projection(projection) == projection
    top_level = smoke._migration_projection({"status": "PASS", "service_count": 5})
    assert top_level["summary"] == {"service_count": 5}
    with pytest.raises(smoke.ExternalStagingAcceptanceError, match="coverage"):
        smoke._migration_projection({"status": "PASS", "service_count": 4})
    with pytest.raises(smoke.ExternalStagingAcceptanceError, match="result"):
        smoke._migration_projection(object())
    invalid = type(
        "MigrationResult",
        (),
        {"to_public_projection": lambda self: []},
    )()
    with pytest.raises(smoke.ExternalStagingAcceptanceError, match="projection"):
        smoke._migration_projection(invalid)


def test_current_release_set_is_projected_to_compose_environment(
    tmp_path,
    monkeypatch,
) -> None:
    artifacts = [
        {
            "artifact_id": artifact,
            "image_reference": f"local/{artifact}@sha256:{index:064x}",
        }
        for index, artifact in enumerate(smoke.IMAGE_ENV_BY_ARTIFACT, start=1)
    ]
    report = {
        "image_build": {
            "status": "RELEASE_SET_BUILT",
            "source_revision": "a" * 40,
            "release_set_digest": "sha256:" + "f" * 64,
            "artifacts": artifacts,
        }
    }
    path = tmp_path / "reports/deployment/s142-oci-image-build.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(report), encoding="utf-8")
    monkeypatch.setattr(
        smoke,
        "_git",
        lambda _root, *args: "a" * 40
        if args[:2] == ("rev-parse", "HEAD")
        else "",
    )

    environment, digest = smoke._image_environment(tmp_path)

    assert set(environment) == set(smoke.IMAGE_ENV_BY_ARTIFACT.values())
    assert digest == "sha256:" + "f" * 64


def test_release_set_projection_admits_non_runtime_changes(
    tmp_path, monkeypatch
) -> None:
    artifacts = [
        {
            "artifact_id": artifact,
            "image_reference": f"local/{artifact}@sha256:{index:064x}",
        }
        for index, artifact in enumerate(smoke.IMAGE_ENV_BY_ARTIFACT, start=1)
    ]
    report = {
        "image_build": {
            "status": "RELEASE_SET_BUILT",
            "source_revision": "a" * 40,
            "release_set_digest": "sha256:" + "f" * 64,
            "artifacts": artifacts,
        }
    }
    path = tmp_path / "reports/deployment/s142-oci-image-build.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(report), encoding="utf-8")

    def git_output(_root, *args):
        if args[:2] == ("rev-parse", "HEAD"):
            return "b" * 40
        if args[0] == "merge-base":
            return "a" * 40
        if args[0] == "diff":
            return "docs/slices/1500.md\nscripts/smoke/run_s150.py\ntests/test_s150.py"
        return ""

    monkeypatch.setattr(smoke, "_git", git_output)

    environment, digest = smoke._image_environment(tmp_path)

    assert set(environment) == set(smoke.IMAGE_ENV_BY_ARTIFACT.values())
    assert digest == "sha256:" + "f" * 64


@pytest.mark.parametrize(
    ("changed_paths", "status", "message"),
    [
        ("services/nex-cx/src/nex_cx/api.py", "", "stale"),
        ("docs/slices/1500.md", " M docs/slices/1500.md", "worktree"),
    ],
)
def test_release_set_projection_rejects_runtime_or_dirty_changes(
    tmp_path, monkeypatch, changed_paths, status, message
) -> None:
    artifacts = [
        {
            "artifact_id": artifact,
            "image_reference": f"local/{artifact}@sha256:{index:064x}",
        }
        for index, artifact in enumerate(smoke.IMAGE_ENV_BY_ARTIFACT, start=1)
    ]
    path = tmp_path / "reports/deployment/s142-oci-image-build.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "image_build": {
                    "status": "RELEASE_SET_BUILT",
                    "source_revision": "a" * 40,
                    "release_set_digest": "sha256:" + "f" * 64,
                    "artifacts": artifacts,
                }
            }
        ),
        encoding="utf-8",
    )

    def git_output(_root, *args):
        if args[:2] == ("rev-parse", "HEAD"):
            return "b" * 40
        if args[0] == "merge-base":
            return "a" * 40
        if args[0] == "diff":
            return changed_paths
        if args[0] == "status":
            return status
        return ""

    monkeypatch.setattr(smoke, "_git", git_output)

    with pytest.raises(smoke.ExternalStagingAcceptanceError, match=message):
        smoke._image_environment(tmp_path)


def test_release_set_and_evidence_redaction_fail_closed(tmp_path, monkeypatch) -> None:
    path = tmp_path / "reports/deployment/s142-oci-image-build.json"
    path.parent.mkdir(parents=True)
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(smoke.ExternalStagingAcceptanceError, match="not ready"):
        smoke._image_environment(tmp_path)
    with pytest.raises(smoke.ExternalStagingAcceptanceError, match="leaked"):
        smoke._assert_evidence_redacted(
            {"detail": "private-value"},
            {"secret": "private-value"},
        )
    smoke._assert_evidence_redacted({"status": "PASS"}, {"secret": "private"})
    assert smoke._normalize_serial("01:AB") == "1ab"
    assert smoke._normalize_serial("00") == "0"


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda build: build.update(source_revision="b" * 40), "stale"),
        (lambda build: build.update(artifacts={}), "artifact list"),
        (lambda build: build.update(artifacts=[]), "coverage"),
        (
            lambda build: build["artifacts"][0].update(image_reference="latest"),
            "immutable",
        ),
    ],
)
def test_release_set_projection_rejects_identity_drift(
    tmp_path, monkeypatch, change, message
) -> None:
    artifacts = [
        {
            "artifact_id": artifact,
            "image_reference": f"local/{artifact}@sha256:{index:064x}",
        }
        for index, artifact in enumerate(smoke.IMAGE_ENV_BY_ARTIFACT, start=1)
    ]
    image_build = {
        "status": "RELEASE_SET_BUILT",
        "source_revision": "a" * 40,
        "release_set_digest": "sha256:" + "f" * 64,
        "artifacts": artifacts,
    }
    change(image_build)
    path = tmp_path / "reports/deployment/s142-oci-image-build.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"image_build": image_build}), encoding="utf-8")
    monkeypatch.setattr(
        smoke,
        "_git",
        lambda _root, *args: "a" * 40
        if args[:2] == ("rev-parse", "HEAD")
        else "",
    )
    with pytest.raises(smoke.ExternalStagingAcceptanceError, match=message):
        smoke._image_environment(tmp_path)


def test_release_set_projection_rejects_unreadable_report(tmp_path) -> None:
    with pytest.raises(smoke.ExternalStagingAcceptanceError, match="unavailable"):
        smoke._image_environment(tmp_path)


def test_summary_lines_are_bounded() -> None:
    assert smoke.summary_line({"status": "FAIL"}) == (
        "s143_external_staging_acceptance=fail"
    )
    result = {
        "status": "PASS",
        "services": {"initial_ready_count": 6},
        "openbao": {"secret_count": 20},
        "tls": {"route_count": 9},
    }
    line = smoke.summary_line(result)
    assert line == (
        "s143_external_staging_acceptance=pass services=6 secrets=20 "
        "tls_routes=9 provider_capabilities=3 next=1432"
    )


def test_rotation_invariants_fail_closed() -> None:
    smoke._require_secret_generation({"a": 2, "b": 2}, expected=2)
    smoke._require_tls_rotation("111", "222")
    smoke._require_tls_rollback("111", "111")
    with pytest.raises(smoke.ExternalStagingAcceptanceError, match="generation"):
        smoke._require_secret_generation({"a": 1, "b": 2}, expected=2)
    with pytest.raises(smoke.ExternalStagingAcceptanceError, match="did not rotate"):
        smoke._require_tls_rotation("111", "111")
    with pytest.raises(smoke.ExternalStagingAcceptanceError, match="rollback"):
        smoke._require_tls_rollback("111", "222")


def test_compose_and_git_helpers_fail_closed(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        smoke.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "ok", ""),
    )
    completed = smoke._compose({}, root=tmp_path, arguments=("config",))
    assert completed.returncode == 0
    assert smoke._git(tmp_path, "rev-parse", "HEAD") == "ok"

    monkeypatch.setattr(
        smoke.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1, "", "bad"),
    )
    with pytest.raises(smoke.ExternalStagingAcceptanceError, match="Compose"):
        smoke._compose({}, root=tmp_path, arguments=("up",))
    assert smoke._compose(
        {}, root=tmp_path, arguments=("down",), check=False
    ).returncode == 1
    with pytest.raises(smoke.ExternalStagingAcceptanceError, match="git"):
        smoke._git(tmp_path, "status")

    calls = []
    monkeypatch.setattr(
        smoke,
        "_compose",
        lambda *args, **kwargs: calls.append(kwargs["arguments"]),
    )
    smoke._compose_up_platform({}, root=tmp_path)
    smoke._compose_recreate_python({}, root=tmp_path)
    assert calls[0][0] == "up"
    assert "--force-recreate" in calls[1]


def test_controlled_bootstrap_failure_reads_only_controlled_line(
    monkeypatch, tmp_path
) -> None:
    assert (
        smoke._controlled_bootstrap_failure(
            {}, root=tmp_path, compose_output="unrelated failure"
        )
        is None
    )
    monkeypatch.setattr(
        smoke.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0],
            0,
            "private-value\n"
            "nex-ae-api | production_container_bootstrap=fail "
            "owner=nex-ae-api reason=OpenBaoSecretResolverError\n",
            "",
        ),
    )

    detail = smoke._controlled_bootstrap_failure(
        {},
        root=tmp_path,
        compose_output='container nex-platform-s143-nex-ae-api-1 exited (1)',
    )

    assert detail is not None
    assert "reason=OpenBaoSecretResolverError" in detail
    assert "private-value" not in detail


def test_https_projection_and_acceptance_helpers(monkeypatch, tmp_path) -> None:
    ca = tmp_path / "ca.crt"
    ca.write_text("unused", encoding="utf-8")

    class Response:
        status = 200

        def __init__(self, body):
            self.body = body

        def read(self, limit):
            return self.body

    class Connection:
        bodies = [json.dumps({"ok": True}).encode(), b"html"]

        def __init__(self, *args, **kwargs):
            pass

        def request(self, *args, **kwargs):
            pass

        def getresponse(self):
            return Response(self.bodies.pop(0))

        def close(self):
            pass

    monkeypatch.setattr(smoke.ssl, "create_default_context", lambda **kwargs: object())
    monkeypatch.setattr(smoke, "_ResolvedHttpsConnection", Connection)
    status, payload = smoke._https_json("host", "/", ca_file=ca)
    assert status == 200 and payload == {"ok": True}
    status, payload = smoke._https_json(
        "host", "/", ca_file=ca, expect_json=False
    )
    assert status == 200 and payload == {}

    monkeypatch.setattr(
        smoke,
        "_https_json",
        lambda host, path, **kwargs: (
            200,
            {"readiness_status": "READY"} if path == "/ready" else {},
        ),
    )
    assert len(smoke._service_acceptance(tmp_path)) == 6
    monkeypatch.setattr(
        smoke,
        "_https_json",
        lambda *args, **kwargs: (200, {"data": [{"id": "model"}]}),
    )
    result = smoke._provider_acceptance(tmp_path, provider_key="private-key")
    assert set(result["capabilities"]) == {"embedding", "reranking", "generation"}


def test_https_and_acceptance_helpers_reject_invalid_results(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        smoke,
        "_https_json",
        lambda *args, **kwargs: (503, {"readiness_status": "NOT_READY"}),
    )
    with pytest.raises(smoke.ExternalStagingAcceptanceError, match="readiness"):
        smoke._service_acceptance(tmp_path)
    with pytest.raises(smoke.ExternalStagingAcceptanceError, match="provider"):
        smoke._provider_acceptance(tmp_path, provider_key="private-key")
    calls = iter(
        [
            *((200, {"readiness_status": "READY"}) for _ in smoke.API_HOSTS),
            (503, {}),
        ]
    )
    monkeypatch.setattr(smoke, "_https_json", lambda *args, **kwargs: next(calls))
    with pytest.raises(smoke.ExternalStagingAcceptanceError, match="AE Web"):
        smoke._service_acceptance(tmp_path)
    monkeypatch.setattr(smoke.ssl, "create_default_context", lambda **kwargs: object())
    with pytest.raises(smoke.ExternalStagingAcceptanceError, match="ready"):
        smoke._wait_for_tls(
            "127.0.0.1",
            1,
            server_hostname="host",
            ca_file=tmp_path / "missing",
            timeout_seconds=0,
        )


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (b"x" * 2_097_153, "too large"),
        (b"{", "response is invalid"),
        (b"[]", "response is invalid"),
    ],
)
def test_https_json_rejects_invalid_payloads(monkeypatch, tmp_path, body, message) -> None:
    class Response:
        status = 200

        def read(self, limit):
            return body

    class Connection:
        def __init__(self, *args, **kwargs):
            pass

        def request(self, *args, **kwargs):
            pass

        def getresponse(self):
            return Response()

        def close(self):
            pass

    monkeypatch.setattr(smoke.ssl, "create_default_context", lambda **kwargs: object())
    monkeypatch.setattr(smoke, "_ResolvedHttpsConnection", Connection)
    with pytest.raises(smoke.ExternalStagingAcceptanceError, match=message):
        smoke._https_json("host", "/", ca_file=tmp_path / "ca")


def test_openbao_owner_isolation_requires_actual_denial(monkeypatch, tmp_path) -> None:
    runtime = tmp_path / "runtime"
    (runtime / "tls").mkdir(parents=True)
    (runtime / "credentials").mkdir()
    for name in (
        "tls/openbao-ca.crt",
        "credentials/nex-oa.role-id",
        "credentials/nex-oa.secret-id",
    ):
        (runtime / name).write_text("credential-12345678", encoding="utf-8")

    class DeniedResolver:
        def resolve(self, *args, **kwargs):
            raise smoke.OpenBaoSecretResolverError("denied")

        def revoke(self):
            pass

    monkeypatch.setattr(smoke, "build_openbao_secret_resolver", lambda env: DeniedResolver())
    assert smoke._verify_openbao_owner_isolation(runtime) is True

    class AllowedResolver(DeniedResolver):
        def resolve(self, *args, **kwargs):
            return object()

    monkeypatch.setattr(smoke, "build_openbao_secret_resolver", lambda env: AllowedResolver())
    with pytest.raises(smoke.ExternalStagingAcceptanceError, match="isolation"):
        smoke._verify_openbao_owner_isolation(runtime)


def test_wait_compose_and_cli_projection(monkeypatch, tmp_path, capsys) -> None:
    calls = []
    monkeypatch.setattr(
        smoke,
        "_wait_for_tls",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    smoke._wait_compose_healthy(
        {"NEX_S143_RUNTIME_DIR": str(tmp_path)},
        root=tmp_path,
    )
    assert calls[0][0] == ("127.0.0.1", 8443)

    monkeypatch.setattr(
        smoke,
        "run_s143_external_staging_acceptance",
        lambda **kwargs: {"status": "SKIPPED"},
    )
    assert smoke.main(["--summary"]) == 0
    assert "skipped" in capsys.readouterr().out
    monkeypatch.setattr(
        smoke,
        "run_s143_external_staging_acceptance",
        lambda **kwargs: {"status": "FAIL"},
    )
    assert smoke.main([]) == 1


def test_tls_wait_retries_then_succeeds(monkeypatch, tmp_path) -> None:
    attempts = iter((OSError("not ready"), object()))

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

    class Context:
        def wrap_socket(self, connection, *, server_hostname):
            return Connection()

    def connect(*args, **kwargs):
        value = next(attempts)
        if isinstance(value, Exception):
            raise value
        return Connection()

    ticks = iter((0.0, 0.1, 0.2))
    monkeypatch.setattr(smoke.ssl, "create_default_context", lambda **kwargs: Context())
    monkeypatch.setattr(smoke.socket, "create_connection", connect)
    monkeypatch.setattr(smoke.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(smoke.time, "sleep", lambda value: None)
    smoke._wait_for_tls(
        "host",
        443,
        server_hostname="host",
        ca_file=tmp_path / "ca",
        timeout_seconds=1,
    )


def test_resolved_https_connection_and_peer_serial(monkeypatch, tmp_path) -> None:
    class Socket:
        pass

    class Context:
        def __init__(self):
            self.server_hostname = None

        def wrap_socket(self, connection, *, server_hostname):
            self.server_hostname = server_hostname
            return connection

    context = Context()
    connection = smoke._ResolvedHttpsConnection(
        "oa.nex-staging.test",
        8443,
        connect_host="127.0.0.1",
        context=context,
    )
    monkeypatch.setattr(connection, "_create_connection", lambda *args: Socket())
    connection.connect()
    assert context.server_hostname == "oa.nex-staging.test"

    class Wrapped:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def getpeercert(self, *, binary_form):
            return b"certificate"

    class PeerContext:
        def wrap_socket(self, connection, *, server_hostname):
            return Wrapped()

    monkeypatch.setattr(smoke.ssl, "create_default_context", lambda **kwargs: PeerContext())
    monkeypatch.setattr(smoke.socket, "create_connection", lambda *args, **kwargs: Wrapped())
    monkeypatch.setattr(
        smoke.x509,
        "load_der_x509_certificate",
        lambda value: type("Certificate", (), {"serial_number": 0xABC})(),
    )
    assert smoke._peer_certificate_serial(tmp_path) == "abc"
