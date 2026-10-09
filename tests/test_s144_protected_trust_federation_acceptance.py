from __future__ import annotations

import base64
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import run_s144_protected_trust_federation_acceptance as runner


def _jwt(**claims: object) -> str:
    kid = str(claims.pop("kid", "oidc-key-1"))
    header = base64.urlsafe_b64encode(
        json.dumps({"alg": "RS256", "kid": kid}).encode()
    ).rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(
        json.dumps({"sub": "external-subject", **claims}).encode()
    ).rstrip(b"=").decode()
    return f"{header}.{payload}.signature"


def test_protected_acceptance_requires_explicit_opt_in(tmp_path: Path) -> None:
    result = runner.run_s144_protected_acceptance(
        {}, execute=False, report_path=tmp_path / "report.json"
    )
    assert result["status"] == "SKIPPED"
    assert runner.ENABLE_ENV in result["skip_reason"]


def test_protected_acceptance_writes_only_value_free_pass_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    evidence = {
        "evidence_schema_version": runner.SCHEMA_VERSION,
        "status": "PASS",
        "transit": {"versions_verified": [1, 2]},
        "federation": {"oidc_jwks_count": 2},
    }
    monkeypatch.setattr(
        runner, "_execute_protected_acceptance", lambda *_args, **_kwargs: evidence
    )
    report = tmp_path / "report.json"
    result = runner.run_s144_protected_acceptance(
        {
            runner.ENABLE_ENV: "1",
            "NEX_OA_TEST_DATABASE_URL": "postgresql://private-value",
        },
        execute=True,
        report_path=report,
    )
    assert result == evidence
    assert json.loads(report.read_text()) == evidence
    assert "private-value" not in report.read_text()


def test_protected_acceptance_redacts_failures_and_secret_leaks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def leaked(*_args, **_kwargs):
        return {"status": "PASS", "detail": "private-database-value"}

    monkeypatch.setattr(runner, "_execute_protected_acceptance", leaked)
    result = runner.run_s144_protected_acceptance(
        {
            runner.ENABLE_ENV: "1",
            "NEX_OA_TEST_DATABASE_URL": "private-database-value",
        },
        execute=True,
        report_path=tmp_path / "not-written.json",
    )
    assert result["status"] == "FAIL"
    assert result["issues"] == ["S144ProtectedAcceptanceError"]
    assert "private-database-value" not in json.dumps(result)

    monkeypatch.setattr(
        runner,
        "_execute_protected_acceptance",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("private")),
    )
    failed = runner.run_s144_protected_acceptance(
        {runner.ENABLE_ENV: "1"}, execute=True
    )
    assert failed["status"] == "FAIL"
    assert failed["issues"] == ["RuntimeError"]


def test_execute_protected_acceptance_orchestrates_real_boundaries_with_doubles(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    migration = SimpleNamespace(planned=("one", "two"), applied=(), skipped=("one", "two"))
    monkeypatch.setattr(runner, "validate_s144_compose_assets", lambda _root: {"status": "VALID"})
    monkeypatch.setattr(runner, "run_service_migrations", lambda *args, **kwargs: migration)
    monkeypatch.setattr(runner, "_verify_database_identity", lambda _url: None)
    monkeypatch.setattr(
        runner.s143,
        "_image_environment",
        lambda _root: (_ for _ in ()).throw(AssertionError("strict loader used")),
    )
    monkeypatch.setattr(runner, "prepare_staging_runtime_directory", lambda _path: None)
    compose_calls: list[tuple[str, ...]] = []
    compose_environments: list[dict[str, str]] = []
    monkeypatch.setattr(
        runner,
        "_compose",
        lambda env, *, root, arguments, check=True: (
            compose_environments.append(dict(env)),
            compose_calls.append(tuple(arguments)),
        ),
    )
    monkeypatch.setattr(runner.s143, "_wait_for_tls", lambda *args, **kwargs: None)

    class Admin:
        def __init__(self, *args, **kwargs):
            self.requests = []

        def request(self, method, path, **kwargs):
            self.requests.append((method, path))
            return {}

    monkeypatch.setattr(runner, "OpenBaoAdminClient", Admin)
    monkeypatch.setattr(
        runner,
        "initialize_openbao",
        lambda *_args: SimpleNamespace(root_token="root-token-private", unseal_key="unseal-private"),
    )
    monkeypatch.setattr(runner, "_staging_secret_values", lambda *args, **kwargs: {"secret": "hidden-value"})
    monkeypatch.setattr(runner, "configure_openbao_staging", lambda *args, **kwargs: {"status": "CONFIGURED"})
    monkeypatch.setattr(
        runner,
        "configure_openbao_s144_trust",
        lambda *args, **kwargs: {"oidc_client_id": "client-id-public"},
    )
    monkeypatch.setattr(
        runner,
        "refresh_openbao_s144_transit_credentials",
        lambda *args, **kwargs: {"status": "REFRESHED"},
    )
    monkeypatch.setattr(
        runner,
        "refresh_openbao_approle_credentials",
        lambda *args, **kwargs: None,
    )
    issued_hostnames = []
    monkeypatch.setattr(
        runner,
        "issue_openbao_platform_certificate",
        lambda *args, **kwargs: issued_hostnames.extend(kwargs["subject_alt_names"]),
    )

    class Registration:
        provider_id = "openbao-staging"
        client_id = "client-id-public"

    monkeypatch.setattr(runner, "_registration", lambda _env: Registration())
    monkeypatch.setattr(
        runner,
        "_configure_oidc_user",
        lambda *args: {"token": "user-token-private", "client_secret": "client-secret-private"},
    )
    id_jwks_calls = 0

    def https(host, path, *, ca_file):
        nonlocal id_jwks_calls
        if path == "/ready":
            return {"readiness_status": "READY"}
        if host == "id.nex-staging.test" and path.endswith("/.well-known/keys"):
            id_jwks_calls += 1
            return {"keys": [{"kid": "oidc-1"}, {"kid": "oidc-2"}]}
        if path == "/.well-known/jwks.json":
            return {"keys": [{"kid": "oa-v1"}, {"kid": "oa-v2"}]}
        return {"issuer": runner.OIDC_ISSUER}

    monkeypatch.setattr(runner, "_https_json", https)
    monkeypatch.setattr(
        runner,
        "validate_enterprise_oidc_discovery",
        lambda *_args: {"endpoint_origins_match": True},
    )
    oidc_calls = 0

    def issue_oidc(*args, **kwargs):
        nonlocal oidc_calls
        oidc_calls += 1
        return {
            "id_token": _jwt(generation=oidc_calls, kid=f"oidc-{oidc_calls}"),
            "nonce": f"nonce-{oidc_calls}",
        }

    monkeypatch.setattr(runner, "_issue_oidc_authorization_code_token", issue_oidc)
    runtime = SimpleNamespace(api_engine=None, worker_engine=None)
    monkeypatch.setattr(runner, "_seed_oa", lambda *args, **kwargs: runtime)
    oa_tokens = iter(("oa-token-v1-private", "oa-token-v2-private"))
    monkeypatch.setattr(runner, "_issue_oa_token", lambda *args: next(oa_tokens))

    def post(_host, path, **kwargs):
        if path.endswith("/revoke"):
            return {"revocation_id": "revocation-public"}
        return {
            "session": {"session_id": "session-private"},
            "metadata": {"identity_link_verified": True},
        }

    monkeypatch.setattr(runner, "_post_json", post)

    class RotationService:
        def __init__(self):
            self.activated = False

        def activate_rotation(self, *args, **kwargs):
            self.activated = True

    rotation_service = RotationService()
    monkeypatch.setattr(
        runner,
        "_rotate_oa_key",
        lambda *args, **kwargs: {"version": 2, "service": rotation_service},
    )
    introspections = iter(({"active": True}, {"active": False}, {"active": True}))
    monkeypatch.setattr(runner, "_introspect", lambda *args: next(introspections))
    monkeypatch.setattr(runner, "_wait_for_oa_ready", lambda _ca: None)
    monkeypatch.setattr(runner, "_request_json", lambda *args, **kwargs: (503, {}))
    monkeypatch.setattr(runner, "_retry_issue_oa_token", lambda *args: "recovered-private")
    monkeypatch.setattr(runner, "_dispose_runtime", lambda _runtime: None)
    cleanup: list[str] = []
    monkeypatch.setattr(
        runner,
        "_cleanup_database",
        lambda _url, _context, *, run_id: cleanup.append(run_id),
    )

    result = runner._execute_protected_acceptance(
        {runner.OA_DATABASE_ENV: "postgresql://private"},
        root=tmp_path,
        image_environment_loader=lambda _root: (
            {"NEX_OA_RUNTIME_IMAGE": "oa@sha256:x"},
            "release-digest",
        ),
    )

    assert result["status"] == "PASS"
    assert result["postgres"]["actual_connection"] is True
    assert result["transit"]["outage_failed_closed"] is True
    assert result["federation"]["metadata_key_rollover_verified"] is True
    assert result["federation"]["metadata_jwks_overlap_verified"] is True
    assert result["federation"]["browser_callback_route_implemented"] is False
    assert rotation_service.activated is True
    assert issued_hostnames[-1] == "id.nex-staging.test"
    assert len(issued_hostnames) == 10
    assert compose_calls[0][:3] == ("down", "--volumes", "--remove-orphans")
    assert compose_environments[1]["NEX_S144_OIDC_CLIENT_ID"] == "pending-openbao-bootstrap"
    assert compose_environments[3]["NEX_S144_OIDC_CLIENT_ID"] == "client-id-public"
    assert any("--force-recreate" in call for call in compose_calls)
    assert cleanup and compose_calls[-1][:2] == ("down", "--volumes")
    assert "private" not in json.dumps(result)


def test_execute_requires_database_url(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(runner, "validate_s144_compose_assets", lambda _root: {})
    with pytest.raises(runner.S144ProtectedAcceptanceError):
        runner._execute_protected_acceptance({}, root=tmp_path)


def test_jwt_jwks_and_redaction_helpers() -> None:
    assert runner._jwt_claims(_jwt(role="employee"))["role"] == "employee"
    assert runner._jwt_key_id(_jwt(kid="key-2")) == "key-2"
    assert runner._jwk_ids({"keys": [{"kid": "one"}, {"kid": "two"}]}) == {
        "one",
        "two",
    }
    assert runner._base64url(b"test") == "dGVzdA"
    with pytest.raises(runner.S144ProtectedAcceptanceError):
        runner._jwt_claims("invalid")
    with pytest.raises(runner.S144ProtectedAcceptanceError):
        runner._jwt_claims("a.@@@.b")
    with pytest.raises(runner.S144ProtectedAcceptanceError):
        runner._jwt_key_id("invalid")
    with pytest.raises(runner.S144ProtectedAcceptanceError):
        runner._jwt_key_id("@@@.payload.signature")
    without_kid = base64.urlsafe_b64encode(b'{"alg":"RS256"}').rstrip(b"=").decode()
    with pytest.raises(runner.S144ProtectedAcceptanceError):
        runner._jwt_key_id(f"{without_kid}.payload.signature")
    without_subject = base64.urlsafe_b64encode(b'{"role":"employee"}').rstrip(b"=").decode()
    with pytest.raises(runner.S144ProtectedAcceptanceError):
        runner._jwt_claims(f"header.{without_subject}.signature")
    with pytest.raises(runner.S144ProtectedAcceptanceError):
        runner._jwk_ids({"keys": []})
    with pytest.raises(runner.S144ProtectedAcceptanceError):
        runner._jwk_ids({})
    with pytest.raises(runner.S144ProtectedAcceptanceError):
        runner._assert_value_free({"value": "secret-value"}, {"x": "secret-value"})
    assert runner._protected_environment_values(
        {"PATH": "/bin", "DB_PASSWORD": "private", "API_TOKEN": "token"}
    ) == {"DB_PASSWORD": "private", "API_TOKEN": "token"}


def test_federated_session_and_required_acceptance_signals_fail_closed() -> None:
    assert runner._federated_session_issued(
        {"session": {"session_id": "opaque-session"}}
    ) is True
    assert runner._federated_session_issued({"session_id": "legacy-shape"}) is False
    with pytest.raises(runner.S144ProtectedAcceptanceError, match="required signal"):
        runner._require_acceptance_signals(
            {
                "transit": {},
                "federation": {},
            }
        )


def test_registration_seed_context_token_request_and_summaries() -> None:
    registration = runner._registration({"NEX_S144_OIDC_CLIENT_ID": "Client123"})
    assert registration.client_id == "Client123"
    context = runner._seed_context("run-1")
    request = runner._token_request(context)
    assert request["audience"] == "nex-oa"
    assert request["scope"] == "service:call token:introspect token:revoke"
    assert runner.summary_line({"status": "SKIPPED"}).endswith("skipped")
    assert runner.summary_line({"status": "FAIL"}).endswith("fail")
    assert "next=1442" in runner.summary_line(
        {
            "status": "PASS",
            "transit": {"versions_verified": [1, 2]},
            "federation": {"oidc_jwks_count": 2},
        }
    )


def test_staging_secret_values_scope_database_and_generate_others(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    bindings = [
        SimpleNamespace(input_kind="external_secret_reference", target_environment_name=name)
        for name in (
            "NEX_OA_DATABASE_URL",
            "NEX_CX_DATABASE_URL",
            "NEX_MO_VLLM_API_KEY",
        )
    ]
    bindings.append(
        SimpleNamespace(
            input_kind="literal",
            target_environment_name="NEX_IGNORED_LITERAL",
        )
    )
    monkeypatch.setattr(
        runner,
        "load_production_configuration_manifest",
        lambda _root: SimpleNamespace(bindings=bindings),
    )
    monkeypatch.setattr(runner.s143, "_container_database_url", lambda _url: "container-db")
    values = runner._staging_secret_values("host-db", root=tmp_path)
    assert values["NEX_OA_DATABASE_URL"] == "container-db"
    assert "host.docker.internal" in values["NEX_CX_DATABASE_URL"]
    assert values["NEX_MO_VLLM_API_KEY"].startswith("s144-")


def test_compose_and_post_helpers_reject_failures(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="private output"),
    )
    with pytest.raises(runner.S144ProtectedAcceptanceError):
        runner._compose({}, root=tmp_path, arguments=("up",))
    assert runner._compose({}, root=tmp_path, arguments=("down",), check=False).returncode == 1

    monkeypatch.setattr(runner, "_request_json", lambda *args, **kwargs: (401, {"error": "x"}))
    with pytest.raises(runner.S144ProtectedAcceptanceError):
        runner._post_json(
            "host",
            "/path",
            ca_file=tmp_path / "ca",
            payload={},
            expected_status=200,
        )
    monkeypatch.setattr(runner, "_request_json", lambda *args, **kwargs: (200, {"ok": True}))
    assert runner._post_json(
        "host",
        "/path",
        ca_file=tmp_path / "ca",
        payload={},
        expected_status=200,
    ) == {"ok": True}
    monkeypatch.setattr(runner, "_https_json", lambda *args, **kwargs: {"readiness_status": "NO"})
    with pytest.raises(runner.S144ProtectedAcceptanceError):
        runner._require_ready(tmp_path / "ca")


def test_database_identity_and_oidc_user_bootstrap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Cursor:
        row = ("nex_oa_test", "nex_oa_user")

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, _sql):
            return None

        def fetchone(self):
            return self.row

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def cursor(self):
            return Cursor()

    monkeypatch.setattr(runner.psycopg, "connect", lambda *_args, **_kwargs: Connection())
    runner._verify_database_identity("postgresql://private")
    Cursor.row = ("wrong", "role")
    with pytest.raises(runner.S144ProtectedAcceptanceError):
        runner._verify_database_identity("postgresql://private")

    class Admin:
        def __init__(self, valid=True):
            self.valid = valid
            self.requests = []

        def request(self, method, path, **kwargs):
            self.requests.append((method, path, kwargs))
            if "/login/" in path:
                return {"auth": {"client_token": "user-token"}} if self.valid else {}
            if path.endswith("nex-platform-oa-staging"):
                return {"data": {"client_secret": "client-secret"}}
            return {}

    admin = Admin()
    result = runner._configure_oidc_user(admin, "root-token", "run")
    assert result == {"token": "user-token", "client_secret": "client-secret"}
    assert len(admin.requests) == 4
    with pytest.raises(runner.S144ProtectedAcceptanceError):
        runner._configure_oidc_user(Admin(valid=False), "root-token", "run")


def test_oidc_authorization_code_exchange_success_and_failures(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(runner.secrets, "token_urlsafe", lambda size: f"value-{size}")

    class Admin:
        response = {"state": "value-24", "code": "authorization-code"}

        def request(self, *_args, **_kwargs):
            return dict(self.response)

    monkeypatch.setattr(
        runner,
        "_request_json",
        lambda *args, **kwargs: (200, {"id_token": "signed-id-token"}),
    )
    result = runner._issue_oidc_authorization_code_token(
        Admin(),
        user_token="user-token",
        client_id="client-id",
        client_secret="client-secret",
        ca_file=tmp_path / "ca",
    )
    assert result == {"id_token": "signed-id-token", "nonce": "value-24"}

    Admin.response = {"state": "wrong", "code": "authorization-code"}
    with pytest.raises(runner.S144ProtectedAcceptanceError):
        runner._issue_oidc_authorization_code_token(
            Admin(),
            user_token="user-token",
            client_id="client-id",
            client_secret="client-secret",
            ca_file=tmp_path / "ca",
        )
    Admin.response = {"state": "value-24", "code": "authorization-code"}
    monkeypatch.setattr(runner, "_request_json", lambda *args, **kwargs: (400, {}))
    with pytest.raises(runner.S144ProtectedAcceptanceError):
        runner._issue_oidc_authorization_code_token(
            Admin(),
            user_token="user-token",
            client_id="client-id",
            client_secret="client-secret",
            ca_file=tmp_path / "ca",
        )


def test_seed_and_rotate_oa_use_durable_services(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = SimpleNamespace()
    membership_calls = []
    principal_calls = []
    key_calls = []
    federation_calls = []

    class Memberships:
        def ensure_membership(self, payload):
            membership_calls.append(payload)

    class Principals:
        def __init__(self, _repository):
            pass

        def upsert_principal(self, payload):
            principal_calls.append(("principal", payload))

        def issue_credential(self, *args, **kwargs):
            principal_calls.append(("credential", args, kwargs))

    class Keys:
        def __init__(self, **kwargs):
            self.repository = kwargs["repository"]

        def set_key_state(self, *args, **kwargs):
            key_calls.append(("state", args, kwargs))

    class Federation:
        def save_provider(self, value):
            federation_calls.append(("provider", value))

        def save_identity(self, value):
            federation_calls.append(("identity", value))

    class Provisioner:
        def __init__(self, *_args):
            pass

        def rotate_rsa3072(self, *args, **kwargs):
            return 2

    monkeypatch.setattr(runner, "build_service_app", lambda *args, **kwargs: object())
    monkeypatch.setattr(runner, "attach_service_persistence_runtime", lambda *args, **kwargs: runtime)
    monkeypatch.setattr(runner, "build_subject_registry_for_runtime", lambda _runtime: object())
    monkeypatch.setattr(runner, "build_tenant_membership_registry_for_runtime", lambda *args, **kwargs: Memberships())
    monkeypatch.setattr(runner, "build_service_principal_repository_for_runtime", lambda _runtime: object())
    monkeypatch.setattr(runner, "OaServicePrincipalService", Principals)
    monkeypatch.setattr(runner, "build_signed_token_repository_for_runtime", lambda _runtime: "signed-repository")
    monkeypatch.setattr(runner, "OaSigningKeyService", Keys)
    monkeypatch.setattr(runner, "build_federated_identity_repository_for_runtime", lambda _runtime: Federation())
    monkeypatch.setattr(runner, "OpenBaoTransitKeyProvisioner", Provisioner)
    monkeypatch.setattr(
        runner,
        "register_openbao_transit_key_version",
        lambda *args, **kwargs: key_calls.append(("register", kwargs)),
    )
    monkeypatch.setattr(runner, "build_federation_provider", lambda payload: {"provider": payload})
    monkeypatch.setattr(runner, "build_external_identity_link", lambda payload, **kwargs: {"identity": payload})
    monkeypatch.setattr(runner.time, "time", lambda: 1_000)

    class Registration:
        provider_id = "openbao-staging"

        def provider_payload(self, **kwargs):
            return {"display_name": kwargs["display_name"]}

    context = runner._seed_context("run")
    returned = runner._seed_oa(
        "postgresql://private",
        admin=object(),
        root_token="root-token",
        registration=Registration(),
        external_subject="external",
        run_id="run",
        context=context,
    )
    assert returned is runtime
    assert membership_calls and len(principal_calls) == 2
    assert [item[0] for item in key_calls[:2]] == ["register", "state"]
    assert len(federation_calls) == 2
    assert context["signing_keys"].repository == "signed-repository"

    key_calls.clear()
    rotation = runner._rotate_oa_key(
        runtime, admin=object(), root_token="root-token", run_id="run"
    )
    assert rotation["version"] == 2
    assert key_calls[0][0] == "register"


def test_token_retry_readiness_and_introspection_helpers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    context = runner._seed_context("run")
    monkeypatch.setattr(
        runner,
        "_post_json",
        lambda *args, **kwargs: {"access_token": "signed-token"},
    )
    assert runner._issue_oa_token(tmp_path / "ca", context) == "signed-token"
    assert runner._introspect(tmp_path / "ca", "control", "target") == {
        "access_token": "signed-token"
    }
    monkeypatch.setattr(runner, "_post_json", lambda *args, **kwargs: {})
    with pytest.raises(runner.S144ProtectedAcceptanceError):
        runner._issue_oa_token(tmp_path / "ca", context)

    attempts = iter((runner.S144ProtectedAcceptanceError("no"), "recovered"))

    def issue(*_args):
        value = next(attempts)
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(runner, "_issue_oa_token", issue)
    monkeypatch.setattr(runner.time, "sleep", lambda _seconds: None)
    assert runner._retry_issue_oa_token(tmp_path / "ca", context) == "recovered"

    monkeypatch.setattr(runner, "_require_ready", lambda _ca: None)
    runner._wait_for_oa_ready(tmp_path / "ca")
    ticks = iter((0, 61))
    monkeypatch.setattr(runner.time, "monotonic", lambda: next(ticks))
    with pytest.raises(runner.S144ProtectedAcceptanceError):
        runner._wait_for_oa_ready(tmp_path / "ca")
    monkeypatch.setattr(runner, "_request_json", lambda *args, **kwargs: (200, {"ok": True}))
    assert runner._https_json("host", "/path", ca_file=tmp_path / "ca") == {"ok": True}
    monkeypatch.setattr(runner, "_request_json", lambda *args, **kwargs: (503, {}))
    with pytest.raises(runner.S144ProtectedAcceptanceError):
        runner._https_json("host", "/path", ca_file=tmp_path / "ca")


def test_request_json_bounds_and_decoding(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(runner.ssl, "create_default_context", lambda **kwargs: object())

    class Response:
        status = 200

        def __init__(self, body):
            self.body = body

        def read(self, _limit):
            return self.body

    class Connection:
        body = b'{"ok":true}'
        closed = False
        request_args = None

        def __init__(self, *args, **kwargs):
            pass

        def request(self, *args, **kwargs):
            type(self).request_args = (args, kwargs)

        def getresponse(self):
            return Response(type(self).body)

        def close(self):
            type(self).closed = True

    monkeypatch.setattr(runner.s143, "_ResolvedHttpsConnection", Connection)
    status, payload = runner._request_json(
        "host",
        "/path",
        method="POST",
        ca_file=tmp_path / "ca",
        payload={"value": 1},
    )
    assert status == 200 and payload == {"ok": True} and Connection.closed is True
    assert Connection.request_args[1]["headers"]["Content-Type"] == "application/json"

    Connection.body = b""
    assert runner._request_json("host", "/", method="GET", ca_file=tmp_path / "ca")[1] == {}
    for body in (b"not-json", b"[]", b"x" * 2_097_153):
        Connection.body = body
        with pytest.raises(runner.S144ProtectedAcceptanceError):
            runner._request_json("host", "/", method="GET", ca_file=tmp_path / "ca")


def test_cleanup_dispose_retry_timeout_and_main(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    statements = []

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, sql, params):
            statements.append((sql, params))

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def cursor(self):
            return Cursor()

    class Engine:
        def __init__(self):
            self.disposed = False

        def dispose(self):
            self.disposed = True

    monkeypatch.setattr(runner.psycopg, "connect", lambda *args, **kwargs: Connection())
    context = runner._seed_context("run")
    context["revocation_id"] = "revocation"
    cleanup_engine = Engine()
    context["runtime"] = SimpleNamespace(api_engine=cleanup_engine)
    runner._cleanup_database("postgresql://private", context, run_id="run")
    assert len(statements) == 12 and cleanup_engine.disposed is True

    without_revocation = runner._seed_context("run-without-revocation")
    runner._cleanup_database(
        "postgresql://private",
        without_revocation,
        run_id="run-without-revocation",
    )
    assert len(statements) == 23

    first, second = Engine(), Engine()
    runner._dispose_runtime(SimpleNamespace(api_engine=first, worker_engine=second))
    assert first.disposed and second.disposed
    third = Engine()
    runner._dispose_runtime(SimpleNamespace(api_engine=third, worker_engine=None))
    assert third.disposed

    monkeypatch.setattr(
        runner,
        "_issue_oa_token",
        lambda *args: (_ for _ in ()).throw(runner.S144ProtectedAcceptanceError("no")),
    )
    ticks = iter((0, 1, 31))
    monkeypatch.setattr(runner.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(runner.time, "sleep", lambda _seconds: None)
    with pytest.raises(runner.S144ProtectedAcceptanceError):
        runner._retry_issue_oa_token(tmp_path / "ca", context)

    monkeypatch.setattr(runner, "load_env_file", lambda _path: None)
    monkeypatch.setattr(
        runner,
        "run_s144_protected_acceptance",
        lambda **kwargs: {"status": "SKIPPED"},
    )
    assert runner.main(["--summary", "--env-file", str(tmp_path / "env")]) == 0
    assert "skipped" in capsys.readouterr().out
    monkeypatch.setattr(
        runner,
        "run_s144_protected_acceptance",
        lambda **kwargs: {"status": "FAIL"},
    )
    assert runner.main(["--env-file", str(tmp_path / "env")]) == 1
