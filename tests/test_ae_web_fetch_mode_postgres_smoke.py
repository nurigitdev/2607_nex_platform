from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import run_ae_web_fetch_mode_postgres_smoke as smoke
import validate_contracts
from nex_cx.ingestion import ContentIngestionStore
from nex_cx.repository import InMemoryCxContentRepository


def protected_env() -> dict[str, str]:
    return {
        smoke.boundary.SMOKE_ENV: "1",
        smoke.boundary.PROFILE_ENV: smoke.boundary.DEFAULT_PROFILE,
        smoke.boundary.AE_WEB_URL_ENV: "http://127.0.0.1:5227",
        smoke.boundary.AE_API_BASE_URL_ENV: "http://127.0.0.1:8103",
        smoke.boundary.AE_DATABASE_URL_ENV: (
            "postgresql+psycopg://nex_ae_user:secret-pass-0229@127.0.0.1:5432/nex_ae_test"
        ),
        smoke.boundary.CX_DATABASE_URL_ENV: (
            "postgresql+psycopg://nex_cx_user:secret-pass-0229@127.0.0.1:5432/nex_cx_test"
        ),
        smoke.boundary.TENANT_ID_ENV: "tenant-slice-0229",
        smoke.boundary.OWNER_USER_ID_ENV: "owner-slice-0229",
    }


class FakeMigrationResult:
    service_id = "nex-test"
    profile = "test"
    planned = ("001", "002")
    applied = ()
    skipped = ("001", "002")
    dry_run = False


class FakeResponse:
    def __init__(self, status_code: int, payload: object) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> object:
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeClient:
    def __init__(self, *, response: FakeResponse) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def post(self, path: str, **kwargs: object) -> FakeResponse:
        self.calls.append({"method": "POST", "path": path, **kwargs})
        return self.response

    def get(self, path: str, **kwargs: object) -> FakeResponse:
        self.calls.append({"method": "GET", "path": path, **kwargs})
        return self.response


def test_fetch_mode_postgres_smoke_skips_by_default() -> None:
    evidence = smoke.run_ae_web_fetch_mode_postgres_smoke({})

    assert evidence["status"] == "SKIPPED"
    assert smoke.summary_line(evidence) == (
        f"ae_web_fetch_mode_postgres_smoke=skipped reason={smoke.boundary.SMOKE_ENV}"
    )


def test_fetch_mode_postgres_smoke_reports_boundary_issues() -> None:
    evidence = smoke.run_ae_web_fetch_mode_postgres_smoke(
        {smoke.boundary.SMOKE_ENV: "1"}
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "boundary_invalid"
    assert {issue["env"] for issue in evidence["issues"]} == {
        spec.name for spec in smoke.boundary.REQUIRED_ENV_SPECS
    }


def test_fetch_mode_postgres_smoke_rejects_non_test_profile_after_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = protected_env()
    env[smoke.boundary.PROFILE_ENV] = "dev"
    monkeypatch.setattr(
        smoke.boundary,
        "run_ae_web_fetch_mode_protected_smoke_boundary",
        lambda *args, **kwargs: {
            "status": "PASS",
            "evidence_schema_version": "boundary.v1",
            "required_phases": [],
        },
    )

    evidence = smoke.run_ae_web_fetch_mode_postgres_smoke(env)

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "profile_not_allowed"


def test_fetch_mode_postgres_smoke_rejects_non_test_database_url() -> None:
    env = protected_env()
    env[smoke.boundary.AE_DATABASE_URL_ENV] = (
        "postgresql+psycopg://nex_ae_user:secret-pass-0229@127.0.0.1:5432/nex_ae_dev"
    )

    evidence = smoke.run_ae_web_fetch_mode_postgres_smoke(env)

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "configuration_invalid"
    assert "must target a *_test database" in evidence["detail"]


def test_fetch_mode_postgres_smoke_passes_with_fake_db_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = protected_env()

    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: FakeMigrationResult(),
    )
    monkeypatch.setattr(
        smoke,
        "_execute_fetch_mode_postgres_smoke",
        lambda **kwargs: {
            "db_observations": {
                "ae_marker_rows": 1,
                "cx_owner_active_content_count": 1,
                "cx_retrieval_evidence_count": 1,
                "cx_retrieval_status": "READY",
            },
            "checks": {"all_good": True},
        },
    )

    evidence = smoke.run_ae_web_fetch_mode_postgres_smoke(env)

    serialized = json.dumps(evidence, default=str)
    assert evidence["status"] == "PASS"
    assert evidence["migrations"]["ae"]["planned_count"] == 2
    assert "secret-pass-0229" not in serialized
    assert env[smoke.boundary.AE_DATABASE_URL_ENV] not in serialized
    assert "ae_web_fetch_mode_postgres_smoke=pass profile=test" in (
        smoke.summary_line(evidence)
    )


def test_fetch_mode_postgres_smoke_reports_generic_execution_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = protected_env()
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: FakeMigrationResult(),
    )

    def raise_execution_error(**kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(smoke, "_execute_fetch_mode_postgres_smoke", raise_execution_error)

    evidence = smoke.run_ae_web_fetch_mode_postgres_smoke(env)

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "execution_failed"
    assert evidence["detail"] == "RuntimeError"


def test_execute_fetch_mode_postgres_smoke_runs_facade_flow_with_fake_db(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = protected_env()
    marker = "marker-slice-0229"

    monkeypatch.setattr(smoke, "build_engine", lambda database_url: object())
    monkeypatch.setattr(
        smoke,
        "attach_service_persistence_runtime",
        lambda *args, **kwargs: SimpleNamespace(
            mode="postgres",
            api_session_factory=object(),
        ),
    )
    monkeypatch.setattr(
        smoke,
        "SqlAlchemyCxContentRepository",
        lambda *args, **kwargs: InMemoryCxContentRepository(),
    )
    monkeypatch.setattr(smoke, "_write_ae_smoke_marker", lambda *args, **kwargs: marker)
    monkeypatch.setattr(smoke, "_count_ae_marker_rows", lambda *args, **kwargs: 1)
    monkeypatch.setattr(smoke, "_delete_ae_smoke_marker", lambda *args, **kwargs: 0)
    monkeypatch.setattr(
        smoke,
        "_delete_retrieval_package_rows",
        lambda *args, **kwargs: {
            "evidence_rows_after_delete": 0,
            "package_rows_after_delete": 0,
        },
    )
    monkeypatch.setattr(smoke, "_count_active_owner_documents", lambda *args, **kwargs: 1)
    monkeypatch.setattr(smoke, "_count_current_document_rows", lambda *args, **kwargs: 1)

    def fake_read_retrieval(engine: object, *, retrieval_package_id: str) -> dict[str, object]:
        return {
            "retrieval_package_id": retrieval_package_id,
            "status": "READY",
            "evidence_count": 1,
            "stored_evidence_count": 1,
        }

    monkeypatch.setattr(smoke, "_read_persisted_retrieval_package", fake_read_retrieval)
    monkeypatch.setattr(
        smoke,
        "_delete_document_library_smoke_rows",
        lambda *args, **kwargs: [
            {
                "label": "ae_web_fetch_mode",
                "content_rows_before_delete": 1,
                "content_rows_after_delete": 0,
            }
        ],
    )

    evidence = smoke._execute_fetch_mode_postgres_smoke(
        env=env,
        ae_database_url=env[smoke.boundary.AE_DATABASE_URL_ENV],
        cx_database_url=env[smoke.boundary.CX_DATABASE_URL_ENV],
    )

    assert evidence["checks"]["upload_status_accepted"] is True
    assert evidence["checks"]["detail_status_ok"] is True
    assert evidence["checks"]["retrieval_status_ok"] is True
    assert evidence["checks"]["browser_claim_owner_scope_enforced"] is True
    assert evidence["checks"]["retrieval_actor_scope_claim_derived"] is True
    assert evidence["checks"]["current_document_persisted"] is True
    assert evidence["checks"]["retrieval_package_persisted"] is True
    assert evidence["auth_observations"] == {
        "ae_facade_auth_mode": "browser_user",
        "ae_facade_transport": "authorization_header",
        "owner_scope_authority": "claim",
        "browser_token_redacted": True,
        "service_token_used_for_ae_facade": False,
    }
    assert evidence["db_observations"]["cx_retrieval_evidence_count"] == 1
    assert evidence["cleanup_observations"]["ae_marker_rows_after_delete"] == 0
    assert (
        evidence["cleanup_observations"]["cx_retrieval_rows"][
            "evidence_rows_after_delete"
        ]
        == 0
    )


def test_execute_fetch_mode_postgres_smoke_reports_missing_cx_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = protected_env()
    monkeypatch.setattr(smoke, "build_engine", lambda database_url: object())
    monkeypatch.setattr(smoke, "_write_ae_smoke_marker", lambda *args, **kwargs: "marker")
    monkeypatch.setattr(
        smoke,
        "attach_service_persistence_runtime",
        lambda *args, **kwargs: SimpleNamespace(
            mode="postgres",
            api_session_factory=None,
        ),
    )
    monkeypatch.setattr(smoke, "_delete_ae_smoke_marker", lambda *args, **kwargs: 0)
    monkeypatch.setattr(
        smoke,
        "_delete_retrieval_package_rows",
        lambda *args, **kwargs: {
            "evidence_rows_after_delete": 0,
            "package_rows_after_delete": 0,
        },
    )
    monkeypatch.setattr(
        smoke,
        "_delete_document_library_smoke_rows",
        lambda *args, **kwargs: [],
    )

    with pytest.raises(RuntimeError, match="CX PostgreSQL session factory"):
        smoke._execute_fetch_mode_postgres_smoke(
            env=env,
            ae_database_url=env[smoke.boundary.AE_DATABASE_URL_ENV],
            cx_database_url=env[smoke.boundary.CX_DATABASE_URL_ENV],
        )


def test_execute_fetch_mode_postgres_smoke_raises_failed_check_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = protected_env()

    monkeypatch.setattr(smoke, "build_engine", lambda database_url: object())
    monkeypatch.setattr(
        smoke,
        "attach_service_persistence_runtime",
        lambda *args, **kwargs: SimpleNamespace(
            mode="postgres",
            api_session_factory=object(),
        ),
    )
    monkeypatch.setattr(
        smoke,
        "SqlAlchemyCxContentRepository",
        lambda *args, **kwargs: InMemoryCxContentRepository(),
    )
    monkeypatch.setattr(smoke, "_write_ae_smoke_marker", lambda *args, **kwargs: "marker")
    monkeypatch.setattr(smoke, "_count_ae_marker_rows", lambda *args, **kwargs: 1)
    monkeypatch.setattr(smoke, "_delete_ae_smoke_marker", lambda *args, **kwargs: 0)
    monkeypatch.setattr(smoke, "_count_active_owner_documents", lambda *args, **kwargs: 1)
    monkeypatch.setattr(smoke, "_count_current_document_rows", lambda *args, **kwargs: 1)
    monkeypatch.setattr(
        smoke,
        "_read_persisted_retrieval_package",
        lambda *args, retrieval_package_id, **kwargs: {
            "retrieval_package_id": retrieval_package_id,
            "status": "READY",
            "evidence_count": 1,
            "stored_evidence_count": 1,
        },
    )
    monkeypatch.setattr(smoke, "_redaction_safe", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        smoke,
        "_delete_retrieval_package_rows",
        lambda *args, **kwargs: {
            "evidence_rows_after_delete": 0,
            "package_rows_after_delete": 0,
        },
    )
    monkeypatch.setattr(
        smoke,
        "_delete_document_library_smoke_rows",
        lambda *args, **kwargs: [],
    )

    with pytest.raises(RuntimeError, match="raw_payload_absent"):
        smoke._execute_fetch_mode_postgres_smoke(
            env=env,
            ae_database_url=env[smoke.boundary.AE_DATABASE_URL_ENV],
            cx_database_url=env[smoke.boundary.CX_DATABASE_URL_ENV],
        )


def test_client_adapters_raise_safe_service_errors() -> None:
    upload_client = smoke.TestClientCxUploadClient(
        FakeClient(response=FakeResponse(503, {"error_code": "cx.unavailable"}))  # type: ignore[arg-type]
    )
    document_client = smoke.TestClientCxDocumentLibraryClient(
        FakeClient(response=FakeResponse(404, {"error_code": "cx.missing"}))  # type: ignore[arg-type]
    )
    retrieval_client = smoke.TestClientCxRetrievalClient(
        FakeClient(response=FakeResponse(500, ValueError("not json")))  # type: ignore[arg-type]
    )

    with pytest.raises(smoke.UploadHandoffError) as upload_error:
        upload_client.register_upload({}, request_id="req", trace_id="a" * 32)
    with pytest.raises(smoke.DocumentLibraryError) as detail_error:
        document_client.get_document(
            "doc",
            tenant_id="tenant",
            owner_user_id="owner",
            request_id="req",
            trace_id="a" * 32,
        )
    with pytest.raises(smoke.RetrievalInteractionError) as retrieval_error:
        retrieval_client.create_retrieval_context(
            {},
            request_id="req",
            trace_id="a" * 32,
        )

    assert upload_error.value.error_code == "cx.unavailable"
    assert detail_error.value.error_code == "cx.missing"
    assert retrieval_error.value.error_code == "cx.retrieval_request_failed"


def test_document_client_optional_summary_methods_return_none() -> None:
    client = smoke.TestClientCxDocumentLibraryClient(
        FakeClient(response=FakeResponse(200, {}))  # type: ignore[arg-type]
    )

    assert client.get_summary("doc", request_id="req", trace_id="a" * 32) is None
    assert client.get_summary_embedding("doc", request_id="req", trace_id="a" * 32) is None


def test_db_marker_helpers_use_expected_sql_shape() -> None:
    executed: list[tuple[str, dict[str, object]]] = []

    class FakeScalarResult:
        def scalar_one(self) -> int:
            return 1

    class FakeConnection:
        def __enter__(self) -> "FakeConnection":
            return self

        def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
            return None

        def execute(self, statement: object, params: dict[str, object]) -> FakeScalarResult:
            executed.append((str(statement), params))
            return FakeScalarResult()

    class FakeEngine:
        def begin(self) -> FakeConnection:
            return FakeConnection()

    event_id = smoke._write_ae_smoke_marker(
        FakeEngine(),
        request_id="request-1",
        trace_id="a" * 32,
        owner_user_id="owner-1",
    )

    assert event_id
    assert smoke._count_ae_marker_rows(FakeEngine(), event_id=event_id) == 1
    assert smoke._delete_ae_smoke_marker(FakeEngine(), event_id=event_id) == 1
    assert smoke._count_ae_marker_rows(FakeEngine(), event_id=None) == 0
    assert smoke._delete_ae_smoke_marker(FakeEngine(), event_id=None) == 0
    assert smoke._count_current_document_rows(FakeEngine(), document_id="doc-1") == 1
    assert smoke._count_current_document_rows(FakeEngine(), document_id=None) == 0
    assert any("service_operational_events" in sql for sql, _ in executed)
    assert any("cx_content_objects" in sql for sql, _ in executed)


def test_delete_retrieval_package_rows_uses_safe_order() -> None:
    executed: list[str] = []

    class FakeScalarResult:
        def scalar_one(self) -> int:
            return 0

    class FakeConnection:
        def __enter__(self) -> "FakeConnection":
            return self

        def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
            return None

        def execute(self, statement: object, params: dict[str, object]) -> FakeScalarResult:
            executed.append(str(statement))
            return FakeScalarResult()

    class FakeEngine:
        def begin(self) -> FakeConnection:
            return FakeConnection()

    assert smoke._delete_retrieval_package_rows(
        FakeEngine(),
        retrieval_package_id=None,
    ) == {"evidence_rows_after_delete": 0, "package_rows_after_delete": 0}
    assert smoke._delete_retrieval_package_rows(
        FakeEngine(),
        retrieval_package_id="package-1",
    ) == {"evidence_rows_after_delete": 0, "package_rows_after_delete": 0}

    delete_statements = [sql for sql in executed if sql.strip().startswith("DELETE")]
    assert "cx_retrieval_evidence_items" in delete_statements[0]
    assert "cx_retrieval_packages" in delete_statements[1]


def test_read_persisted_retrieval_package_and_missing_row() -> None:
    class FakeRows:
        def __init__(self, row: dict[str, object] | None) -> None:
            self.row = row

        def mappings(self) -> "FakeRows":
            return self

        def first(self) -> dict[str, object] | None:
            return self.row

    class FakeConnection:
        def __init__(self, row: dict[str, object] | None) -> None:
            self.row = row

        def __enter__(self) -> "FakeConnection":
            return self

        def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
            return None

        def execute(self, statement: object, params: dict[str, object]) -> FakeRows:
            return FakeRows(self.row)

    class FakeEngine:
        def __init__(self, row: dict[str, object] | None) -> None:
            self.row = row

        def begin(self) -> FakeConnection:
            return FakeConnection(self.row)

    row = {
        "retrieval_package_id": "package-1",
        "status": "READY",
        "evidence_count": 1,
        "stored_evidence_count": 1,
    }

    assert smoke._read_persisted_retrieval_package(
        FakeEngine(row),
        retrieval_package_id="package-1",
    ) == row
    with pytest.raises(RuntimeError):
        smoke._read_persisted_retrieval_package(
            FakeEngine(None),
            retrieval_package_id="missing",
        )


def test_helpers_validate_test_db_urls_and_redaction() -> None:
    env = protected_env()

    smoke._require_test_database_url(
        env[smoke.boundary.AE_DATABASE_URL_ENV],
        env_name=smoke.boundary.AE_DATABASE_URL_ENV,
    )
    with pytest.raises(ValueError):
        smoke._require_test_database_url("not-a-url", env_name="BAD_URL")
    with pytest.raises(ValueError):
        smoke._required_env({}, "MISSING_ENV")
    with pytest.raises(ValueError, match=smoke.boundary.AE_DATABASE_URL_ENV):
        smoke.assert_smoke_evidence_redacted(
            env[smoke.boundary.AE_DATABASE_URL_ENV],
            env,
        )

    assert smoke.safe_fetch_mode_browser_config()["client_mode"] == "fetch"
    with pytest.raises(RuntimeError, match="uploaded CX document"):
        smoke._seed_retrieval_indexes(
            ContentIngestionStore(),
            document_id="missing",
            storage_config=object(),
            request_id="req",
            trace_id="a" * 32,
        )


def test_main_reports_summary_and_failures(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        smoke,
        "run_ae_web_fetch_mode_postgres_smoke",
        lambda: {"smoke_schema_version": smoke.SCHEMA_VERSION, "status": "SKIPPED"},
    )

    assert smoke.main(["--summary"]) == 0
    assert "ae_web_fetch_mode_postgres_smoke=skipped" in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_ae_web_fetch_mode_postgres_smoke",
        lambda: {
            "smoke_schema_version": smoke.SCHEMA_VERSION,
            "status": "FAIL",
            "failure_code": "boom",
        },
    )

    assert smoke.main([]) == 1
    assert "\"status\": \"FAIL\"" in capsys.readouterr().out
    assert smoke.summary_line({"status": "FAIL", "failure_code": "boom"}) == (
        "ae_web_fetch_mode_postgres_smoke=fail reason=boom"
    )


def test_fetch_mode_postgres_smoke_contract_fixtures_validate() -> None:
    contracts_root = smoke.ROOT / "contracts"
    schema = validate_contracts.load_structured_file(
        contracts_root
        / "schemas"
        / "service"
        / "nex_ae_web"
        / "fetch_mode_smoke_evidence.v1.schema.json"
    )
    positive = validate_contracts.load_structured_file(
        contracts_root
        / "examples"
        / "operations"
        / "ae_web_fetch_mode_smoke_evidence.postgres_success.json"
    )
    negative = validate_contracts.load_structured_file(
        contracts_root
        / "tests"
        / "negative"
        / "operations"
        / "ae_web_fetch_mode_smoke_evidence.raw_database_url.json"
    )

    validate_contracts.validate_payload(schema, positive)
    with pytest.raises(validate_contracts.ValidationError):
        validate_contracts.validate_payload(schema, negative)


def test_fetch_mode_postgres_smoke_generated_pass_matches_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contracts_root = smoke.ROOT / "contracts"
    schema = validate_contracts.load_structured_file(
        contracts_root
        / "schemas"
        / "service"
        / "nex_ae_web"
        / "fetch_mode_smoke_evidence.v1.schema.json"
    )
    example = validate_contracts.load_structured_file(
        contracts_root
        / "examples"
        / "operations"
        / "ae_web_fetch_mode_smoke_evidence.postgres_success.json"
    )
    execution_keys = {
        "request_id",
        "trace_id",
        "workspace_id",
        "document_id",
        "upload_handoff_id",
        "retrieval_interaction_id",
        "retrieval_package_id",
        "db_observations",
        "adapter_observations",
        "auth_observations",
        "cleanup_observations",
        "checks",
    }

    def fake_migration(service_id: str, **kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(
            service_id=service_id,
            profile="test",
            planned=("001",),
            applied=(),
            skipped=("001",),
            dry_run=False,
        )

    monkeypatch.setattr(smoke, "run_service_migrations", fake_migration)
    monkeypatch.setattr(
        smoke,
        "_execute_fetch_mode_postgres_smoke",
        lambda **kwargs: {key: example[key] for key in execution_keys},
    )

    evidence = smoke.run_ae_web_fetch_mode_postgres_smoke(protected_env())

    validate_contracts.validate_payload(schema, evidence)
    serialized = json.dumps(evidence, default=str)
    assert "secret-pass-0229" not in serialized
    assert evidence["redacted_database_urls"]["ae"].endswith("/nex_ae_test")


def test_fetch_mode_postgres_smoke_is_quality_gate_and_docs_wired() -> None:
    root = smoke.ROOT
    quality_gate = (root / "scripts" / "quality" / "run_quality_gate.sh").read_text(
        encoding="utf-8"
    )
    docs_index = (root / "docs" / "README.md").read_text(encoding="utf-8")
    slice_doc = (
        root
        / "docs"
        / "slices"
        / "0229_ae_web_fetch_mode_postgresql_smoke_evidence_execution.md"
    ).read_text(encoding="utf-8")
    contracts_readme = (root / "contracts" / "README.md").read_text(encoding="utf-8")
    examples_index = json.loads(
        (root / "contracts" / "examples" / "index.json").read_text(encoding="utf-8")
    )
    negative_index = json.loads(
        (root / "contracts" / "tests" / "negative" / "index.json").read_text(
            encoding="utf-8"
        )
    )
    example_paths = {entry["path"] for entry in examples_index["examples"]}
    negative_paths = {
        entry["path"] for entry in negative_index["negative_examples"]
    }

    assert "run_ae_web_fetch_mode_postgres_smoke.py --summary" in quality_gate
    assert "0229_ae_web_fetch_mode_postgresql_smoke_evidence_execution.md" in docs_index
    assert "0230_ae_web_fetch_mode_smoke_evidence_contract_closure.md" in docs_index
    assert smoke.boundary.AE_DATABASE_URL_ENV in slice_doc
    assert smoke.boundary.CX_DATABASE_URL_ENV in slice_doc
    assert "nex_ae_web/" in contracts_readme
    assert (
        "examples/operations/ae_web_fetch_mode_smoke_evidence.postgres_success.json"
        in example_paths
    )
    assert (
        "tests/negative/operations/ae_web_fetch_mode_smoke_evidence.raw_database_url.json"
        in negative_paths
    )
