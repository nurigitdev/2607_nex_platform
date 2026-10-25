from __future__ import annotations

import importlib.util
import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest
from nex_runtime.demo_database import (
    DEMO_DATABASE_BACKUP_CONFIRMATION,
    DEMO_DATABASE_TARGETS,
    DemoBackupSetResult,
    DemoDatabaseGuardError,
    DemoDatabaseInspection,
    ResolvedDemoDatabaseTarget,
    admit_demo_tenant_fixture_plan,
    build_demo_tenant_fixture_plan,
    demo_backup_set_public_projection,
    demo_database_admission_public_projection,
    demo_tenant_fixture_plan_public_projection,
    execute_demo_pre_migration_backup_set,
    inspect_demo_database_targets,
    load_demo_backup_set_manifest,
    resolve_demo_database_targets,
    validate_demo_backup_set_manifest,
    write_demo_backup_credentials,
)
from nex_runtime.postgres_backup import (
    PostgresBackupError,
    build_service_logical_backup_plan,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "scripts/smoke/data/p8_golden_a_fixture.v1.json"
BACKUP_ID = "20261025T010203Z-abcdef12"


def _environment() -> dict[str, str]:
    return {
        target.database_env: (
            "postgresql+psycopg://"
            f"{target.expected_role_name}:demo-secret@127.0.0.1:5432/"
            f"{target.expected_database_name}"
        )
        for target in DEMO_DATABASE_TARGETS
    }


def _fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _inspection(target, *, migration_state: str = "CURRENT"):
    missing = () if migration_state == "CURRENT" else ("0001",)
    extra = ("9999",) if migration_state == "DRIFT" else ()
    return DemoDatabaseInspection(
        service_id=target.service_id,
        database_name=target.expected_database_name,
        role_name=target.expected_role_name,
        identity_state="ADMITTED",
        migration_state=migration_state,
        expected_migrations=("0001",),
        applied_migrations=("0001",) if migration_state == "CURRENT" else (),
        missing_migrations=missing,
        extra_migrations=extra,
        source_inventory_hash="sha256:" + "a" * 64,
    )


class _Cursor:
    def __init__(self, response, queries):
        self.response = response
        self.queries = queries
        self.query = ""

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, query):
        self.query = " ".join(str(query).split())
        self.queries.append(self.query)

    def fetchone(self):
        return self.response["identity"]

    def fetchall(self):
        return [(item,) for item in self.response.get("applied", ())]


class _Connection:
    def __init__(self, response, queries):
        self.response = response
        self.queries = queries

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def cursor(self):
        return _Cursor(self.response, self.queries)


class _Connect:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.queries: list[str] = []
        self.urls: list[str] = []

    def __call__(self, url, **kwargs):
        self.urls.append(url)
        assert kwargs == {"autocommit": True}
        return _Connection(next(self.responses), self.queries)


def test_demo_targets_resolve_exact_seven_dev_identities_without_exposure() -> None:
    resolved = resolve_demo_database_targets(_environment())
    assert [item.target.service_id for item in resolved] == [
        "nex-oa",
        "nex-ag",
        "nex-ae-api",
        "nex-cx",
        "nex-mo",
        "nex-wc",
        "nex-eos",
    ]
    assert all(item.host == "127.0.0.1" and item.port == 5432 for item in resolved)
    assert "demo-secret" not in repr(resolved)


@pytest.mark.parametrize(
    ("mutator", "error_code"),
    (
        (
            lambda env: env.pop("NEX_OA_DATABASE_URL"),
            "demo_database_url_missing_or_invalid",
        ),
        (
            lambda env: env.update(
                NEX_OA_DATABASE_URL="postgresql://nex_oa_user:<password>@localhost/nex_oa_dev"
            ),
            "demo_database_url_missing_or_invalid",
        ),
        (
            lambda env: env.update(NEX_OA_DATABASE_URL="sqlite:///nex_oa_dev"),
            "demo_database_driver_invalid",
        ),
        (
            lambda env: env.update(
                NEX_OA_DATABASE_URL="postgresql://nex_oa_user:x@localhost/nex_oa_test"
            ),
            "demo_database_name_mismatch",
        ),
        (
            lambda env: env.update(
                NEX_OA_DATABASE_URL="postgresql://wrong:x@localhost/nex_oa_dev"
            ),
            "demo_database_role_mismatch",
        ),
        (
            lambda env: env.update(
                NEX_OA_DATABASE_URL="postgresql://nex_oa_user:x@/nex_oa_dev"
            ),
            "demo_database_host_missing",
        ),
    ),
)
def test_demo_target_resolution_fails_closed(mutator, error_code: str) -> None:
    environment = _environment()
    mutator(environment)
    with pytest.raises(DemoDatabaseGuardError, match=error_code):
        resolve_demo_database_targets(environment)


def test_demo_target_selection_rejects_empty_duplicate_and_unknown() -> None:
    environment = _environment()
    for service_ids, code in (
        ([], "demo_service_selection_empty"),
        (["nex-oa", "nex-oa"], "demo_service_selection_duplicate"),
        (["unknown"], "demo_service_unknown"),
    ):
        with pytest.raises(DemoDatabaseGuardError, match=code):
            resolve_demo_database_targets(environment, service_ids=service_ids)


def test_read_only_inspection_reports_current_pending_and_drift(tmp_path: Path) -> None:
    database_root = tmp_path / "database"
    selected = resolve_demo_database_targets(
        _environment(), service_ids=("nex-oa", "nex-ag", "nex-eos")
    )
    for item in selected:
        directory = database_root / item.target.service_id / "migrations"
        directory.mkdir(parents=True)
        (directory / "0001_baseline.sql").write_text("BEGIN; COMMIT;", encoding="utf-8")
    connect = _Connect(
        (
            {
                "identity": ("nex_oa_dev", "nex_oa_user", False, "schema_migrations"),
                "applied": ("0001_baseline",),
            },
            {"identity": ("nex_ag_dev", "nex_ag_user", False, None)},
            {
                "identity": ("nex_eos_dev", "nex_eos_user", False, "schema_migrations"),
                "applied": ("9999_unknown",),
            },
        )
    )
    inspected = inspect_demo_database_targets(
        selected, database_root=database_root, connect=connect
    )
    assert [item.migration_state for item in inspected] == [
        "CURRENT",
        "MIGRATION_REQUIRED",
        "DRIFT",
    ]
    projection = demo_database_admission_public_projection(inspected)
    assert projection["state"] == "ADMITTED"
    assert projection["migration_current_count"] == 1
    assert projection["database_urls_exposed"] is False
    assert all(query.upper().startswith("SELECT") for query in connect.queries)
    assert "demo-secret" not in json.dumps(projection)


@pytest.mark.parametrize(
    ("identity", "code"),
    (
        (("wrong", "nex_oa_user", False, None), "demo_database_live_identity_mismatch"),
        (
            ("nex_oa_dev", "nex_oa_user", True, None),
            "demo_database_replica_not_admitted",
        ),
        (None, "demo_database_identity_unreadable"),
    ),
)
def test_inspection_rejects_wrong_live_identity_replica_and_bad_row(
    tmp_path: Path, identity, code: str
) -> None:
    directory = tmp_path / "nex-oa" / "migrations"
    directory.mkdir(parents=True)
    (directory / "0001.sql").write_text("BEGIN; COMMIT;", encoding="utf-8")
    target = resolve_demo_database_targets(_environment(), service_ids=("nex-oa",))
    with pytest.raises(DemoDatabaseGuardError, match=code):
        inspect_demo_database_targets(
            target,
            database_root=tmp_path,
            connect=_Connect(({"identity": identity},)),
        )


def test_inspection_rejects_empty_or_missing_source_inventory(tmp_path: Path) -> None:
    target = resolve_demo_database_targets(_environment(), service_ids=("nex-oa",))
    with pytest.raises(DemoDatabaseGuardError, match="migration_directory_missing"):
        inspect_demo_database_targets(
            target, database_root=tmp_path, connect=_Connect(())
        )
    (tmp_path / "nex-oa" / "migrations").mkdir(parents=True)
    with pytest.raises(DemoDatabaseGuardError, match="migration_inventory_empty"):
        inspect_demo_database_targets(
            target, database_root=tmp_path, connect=_Connect(())
        )
    with pytest.raises(DemoDatabaseGuardError, match="targets_empty"):
        inspect_demo_database_targets((), database_root=tmp_path, connect=_Connect(()))
    with pytest.raises(DemoDatabaseGuardError, match="inspections_empty"):
        demo_database_admission_public_projection(())


def test_pre_migration_backup_set_is_complete_atomic_and_redacted(
    tmp_path: Path,
) -> None:
    targets = resolve_demo_database_targets(_environment())
    inspections = tuple(_inspection(target) for target in DEMO_DATABASE_TARGETS)
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs["env"]))
        kwargs["stdout"].write(b"demo-backup")
        return SimpleNamespace(returncode=0, stderr=b"")

    result = execute_demo_pre_migration_backup_set(
        targets,
        inspections,
        backup_id=BACKUP_ID,
        backup_root=tmp_path / "backups",
        pg_dump_bin=Path("/usr/bin/pg_dump"),
        confirmation=DEMO_DATABASE_BACKUP_CONFIRMATION,
        runner=runner,
        parent_environ={"PATH": "/usr/bin", "UNSAFE_SECRET": "not-forwarded"},
    )
    assert result.state == "CREATED"
    assert len(result.targets) == 7 == len(calls)
    assert result.manifest_path.is_file()
    assert oct(result.manifest_path.stat().st_mode & 0o777) == "0o600"
    assert all(item.archive_bytes == len(b"demo-backup") for item in result.targets)
    assert all("UNSAFE_SECRET" not in environment for _, environment in calls)
    assert all("demo-secret" not in " ".join(command) for command, _ in calls)
    projection = demo_backup_set_public_projection(result)
    serialized = json.dumps(projection)
    assert projection["service_count"] == 7
    assert projection["credential_material_exposed"] is False
    assert "demo-secret" not in serialized
    manifest = load_demo_backup_set_manifest(result.manifest_path)
    assert manifest["set_hash"] == result.set_hash
    assert manifest["targets"][0]["migration_state"] == "CURRENT"
    assert manifest["targets"][0]["archive_name"] == f"{BACKUP_ID}.dump"


def test_backup_guard_rejects_bad_confirmation_incomplete_set_and_existing_set(
    tmp_path: Path,
) -> None:
    targets = resolve_demo_database_targets(_environment())
    inspections = tuple(_inspection(target) for target in DEMO_DATABASE_TARGETS)
    values = {
        "targets": targets,
        "inspections": inspections,
        "backup_id": BACKUP_ID,
        "backup_root": tmp_path / "backups",
        "pg_dump_bin": Path("/usr/bin/pg_dump"),
        "confirmation": "wrong",
        "runner": lambda *_args, **_kwargs: None,
    }
    with pytest.raises(DemoDatabaseGuardError, match="confirmation_invalid"):
        execute_demo_pre_migration_backup_set(**values)
    values.update(confirmation=DEMO_DATABASE_BACKUP_CONFIRMATION, targets=targets[:-1])
    with pytest.raises(DemoDatabaseGuardError, match="database_set_incomplete"):
        execute_demo_pre_migration_backup_set(**values)
    values.update(targets=targets, backup_id="bad")
    with pytest.raises(DemoDatabaseGuardError, match="backup_id_invalid"):
        execute_demo_pre_migration_backup_set(**values)
    values.update(backup_id=BACKUP_ID, backup_root=Path("relative"))
    with pytest.raises(DemoDatabaseGuardError, match="backup_root_invalid"):
        execute_demo_pre_migration_backup_set(**values)


def test_backup_credential_files_are_private_and_escape_password(
    tmp_path: Path,
) -> None:
    environment = _environment()
    environment["NEX_OA_DATABASE_URL"] = (
        "postgresql://nex_oa_user:p%3Aa%5Css@127.0.0.1:5432/nex_oa_dev?sslmode=require"
    )
    targets = resolve_demo_database_targets(environment, service_ids=("nex-oa",))
    service_file = tmp_path / "pg_service.conf"
    passfile = tmp_path / ".pgpass"
    names = write_demo_backup_credentials(
        targets, service_file=service_file, passfile=passfile
    )
    assert names == {"nex-oa": "p8-demo-nex-oa"}
    assert "sslmode=require" in service_file.read_text(encoding="utf-8")
    assert r"p\:a\\ss" in passfile.read_text(encoding="utf-8")
    assert oct(service_file.stat().st_mode & 0o777) == "0o600"
    assert oct(passfile.stat().st_mode & 0o777) == "0o600"
    with pytest.raises(DemoDatabaseGuardError, match="credential_file_exists"):
        write_demo_backup_credentials(
            targets, service_file=service_file, passfile=passfile
        )
    with pytest.raises(DemoDatabaseGuardError, match="credential_path_invalid"):
        write_demo_backup_credentials(
            targets, service_file=Path("relative"), passfile=tmp_path / "new"
        )


def test_backup_credentials_allow_passwordless_url_and_reject_line_breaks(
    tmp_path: Path,
) -> None:
    environment = _environment()
    environment["NEX_OA_DATABASE_URL"] = (
        "postgresql://nex_oa_user@127.0.0.1:5432/nex_oa_dev?ignored=value"
    )
    target = resolve_demo_database_targets(environment, service_ids=("nex-oa",))[0]
    write_demo_backup_credentials(
        (target,),
        service_file=tmp_path / "service.conf",
        passfile=tmp_path / ".pgpass",
    )
    assert (tmp_path / ".pgpass").read_text(encoding="utf-8") == ""
    assert "ignored" not in (tmp_path / "service.conf").read_text(encoding="utf-8")

    invalid = ResolvedDemoDatabaseTarget(
        target=target.target,
        database_url=target.database_url,
        drivername=target.drivername,
        host="bad\nhost",
        port=target.port,
    )
    with pytest.raises(DemoDatabaseGuardError, match="credential_value_invalid"):
        write_demo_backup_credentials(
            (invalid,),
            service_file=tmp_path / "invalid.conf",
            passfile=tmp_path / "invalid.pgpass",
        )


def test_fixture_seed_and_reset_plans_are_tenant_only_and_backup_bound() -> None:
    fixture = _fixture()
    for action, confirmation in (
        ("SEED", "SEED_P8_GOLDEN_A_TENANT"),
        ("reset", "RESET_P8_GOLDEN_A_TENANT"),
    ):
        plan = build_demo_tenant_fixture_plan(
            fixture,
            action=action,
            confirmation=confirmation,
            backup_id=BACKUP_ID,
        )
        projection = demo_tenant_fixture_plan_public_projection(plan)
        assert plan.tenant_id == "p8-golden-a"
        assert plan.mutation_scope == "TENANT_ONLY"
        assert plan.tenant_predicate_required is True
        assert plan.service_ids == tuple(
            target.service_id for target in DEMO_DATABASE_TARGETS
        )
        assert plan.fixture_owner_service_ids == ("nex-oa", "nex-eos")
        assert projection["whole_database_reset_allowed"] is False
        assert confirmation not in json.dumps(projection)

    inspections = tuple(_inspection(target) for target in DEMO_DATABASE_TARGETS)
    backup = _backup_manifest()
    admitted = admit_demo_tenant_fixture_plan(plan, inspections, backup)
    assert admitted["state"] == "READY"
    assert admitted["migration_current_count"] == 7


@pytest.mark.parametrize(
    ("field", "value", "code"),
    (
        ("action", "PURGE", "action_invalid"),
        ("confirmation", "wrong", "confirmation_invalid"),
        ("backup_id", "bad", "backup_id_invalid"),
    ),
)
def test_fixture_plan_rejects_invalid_control_values(
    field: str, value: str, code: str
) -> None:
    values = {
        "action": "SEED",
        "confirmation": "SEED_P8_GOLDEN_A_TENANT",
        "backup_id": BACKUP_ID,
    }
    values[field] = value
    with pytest.raises(DemoDatabaseGuardError, match=code):
        build_demo_tenant_fixture_plan(_fixture(), **values)


def test_fixture_plan_rejects_cross_tenant_bad_id_and_hash() -> None:
    values = {
        "action": "SEED",
        "confirmation": "SEED_P8_GOLDEN_A_TENANT",
        "backup_id": BACKUP_ID,
    }
    fixture = _fixture()
    fixture["tenant"]["tenant_id"] = "other"
    fixture["fixture_hash"] = semantic_sha256_hash_ref(
        {key: value for key, value in fixture.items() if key != "fixture_hash"}
    )
    with pytest.raises(DemoDatabaseGuardError, match="tenant_invalid"):
        build_demo_tenant_fixture_plan(fixture, **values)

    fixture = _fixture()
    fixture["fixture_id"] = ""
    with pytest.raises(DemoDatabaseGuardError, match="fixture_id_invalid"):
        build_demo_tenant_fixture_plan(fixture, **values)

    fixture = _fixture()
    fixture["fixture_hash"] = "bad"
    with pytest.raises(DemoDatabaseGuardError, match="fixture_hash_invalid"):
        build_demo_tenant_fixture_plan(fixture, **values)

    fixture = _fixture()
    fixture["scenario"]["amount"] = "1.00"
    with pytest.raises(DemoDatabaseGuardError, match="fixture_hash_mismatch"):
        build_demo_tenant_fixture_plan(fixture, **values)
    with pytest.raises(DemoDatabaseGuardError, match="fixture_invalid"):
        build_demo_tenant_fixture_plan([], **values)


def test_fixture_admission_requires_complete_current_database_set() -> None:
    plan = build_demo_tenant_fixture_plan(
        _fixture(),
        action="RESET",
        confirmation="RESET_P8_GOLDEN_A_TENANT",
        backup_id=BACKUP_ID,
    )
    inspections = tuple(_inspection(target) for target in DEMO_DATABASE_TARGETS)
    backup = _backup_manifest()
    with pytest.raises(DemoDatabaseGuardError, match="database_set_incomplete"):
        admit_demo_tenant_fixture_plan(plan, inspections[:-1], backup)
    pending = list(inspections)
    pending[-1] = _inspection(
        DEMO_DATABASE_TARGETS[-1], migration_state="MIGRATION_REQUIRED"
    )
    with pytest.raises(DemoDatabaseGuardError, match="migrations_not_current"):
        admit_demo_tenant_fixture_plan(plan, pending, backup)


def test_backup_manifest_admission_rejects_tamper_wrong_id_and_incomplete_set() -> None:
    manifest = _backup_manifest()
    assert validate_demo_backup_set_manifest(manifest)["backup_id"] == BACKUP_ID
    with pytest.raises(DemoDatabaseGuardError, match="set_id_mismatch"):
        validate_demo_backup_set_manifest(
            manifest, expected_backup_id="20261025T010203Z-deadbeef"
        )
    tampered = deepcopy(manifest)
    tampered["state"] = "FAILED"
    with pytest.raises(DemoDatabaseGuardError, match="hash_mismatch"):
        validate_demo_backup_set_manifest(tampered)
    incomplete = deepcopy(manifest)
    incomplete["targets"] = incomplete["targets"][:-1]
    incomplete["service_count"] = 6
    incomplete["set_hash"] = semantic_sha256_hash_ref(
        {key: value for key, value in incomplete.items() if key != "set_hash"}
    )
    with pytest.raises(DemoDatabaseGuardError, match="services_incomplete"):
        validate_demo_backup_set_manifest(incomplete)


@pytest.mark.parametrize(
    ("payload", "code"),
    (
        ([], "manifest_invalid"),
        ({}, "hash_invalid"),
    ),
)
def test_backup_manifest_rejects_invalid_document_shapes(payload, code: str) -> None:
    with pytest.raises(DemoDatabaseGuardError, match=code):
        validate_demo_backup_set_manifest(payload)


def test_backup_manifest_rejects_invalid_state_and_target_collection() -> None:
    invalid = _backup_manifest()
    invalid["state"] = "FAILED"
    invalid["set_hash"] = semantic_sha256_hash_ref(
        {key: value for key, value in invalid.items() if key != "set_hash"}
    )
    with pytest.raises(DemoDatabaseGuardError, match="manifest_invalid"):
        validate_demo_backup_set_manifest(invalid)

    invalid = _backup_manifest()
    invalid["targets"] = {}
    invalid["set_hash"] = semantic_sha256_hash_ref(
        {key: value for key, value in invalid.items() if key != "set_hash"}
    )
    with pytest.raises(DemoDatabaseGuardError, match="manifest_invalid"):
        validate_demo_backup_set_manifest(invalid)


def test_backup_manifest_loader_and_result_boundary_fail_closed(tmp_path: Path) -> None:
    with pytest.raises(DemoDatabaseGuardError, match="manifest_unreadable"):
        load_demo_backup_set_manifest(tmp_path / "missing.json")

    plan = build_demo_tenant_fixture_plan(
        _fixture(),
        action="SEED",
        confirmation="SEED_P8_GOLDEN_A_TENANT",
        backup_id=BACKUP_ID,
    )
    inspections = tuple(_inspection(target) for target in DEMO_DATABASE_TARGETS)
    missing_result = DemoBackupSetResult(
        schema_version="p8_demo_pre_migration_backup_set.v1",
        backup_id=BACKUP_ID,
        state="CREATED",
        manifest_path=tmp_path / "missing.json",
        targets=(),
        set_hash="sha256:" + "a" * 64,
    )
    with pytest.raises(DemoDatabaseGuardError, match="manifest_unreadable"):
        admit_demo_tenant_fixture_plan(plan, inspections, missing_result)

    blocked = list(inspections)
    blocked[0] = DemoDatabaseInspection(
        **{**blocked[0].__dict__, "identity_state": "BLOCKED"}
    )
    targets = resolve_demo_database_targets(_environment())
    with pytest.raises(DemoDatabaseGuardError, match="identity_not_admitted"):
        execute_demo_pre_migration_backup_set(
            targets,
            blocked,
            backup_id=BACKUP_ID,
            backup_root=tmp_path / "backups",
            pg_dump_bin=Path("/usr/bin/pg_dump"),
            confirmation=DEMO_DATABASE_BACKUP_CONFIRMATION,
            runner=lambda *_args, **_kwargs: None,
        )


def test_generic_backup_plan_builder_preserves_safe_command_contract(
    tmp_path: Path,
) -> None:
    plan = build_service_logical_backup_plan(
        service_id="nex-eos",
        libpq_service="p8-demo-nex-eos",
        backup_id=BACKUP_ID,
        backup_root=tmp_path,
        pg_dump_bin=Path("/usr/bin/pg_dump"),
        service_file=tmp_path / "service.conf",
        passfile=tmp_path / ".pgpass",
        compression="gzip:6",
        postgres_major=16,
        parent_environ={"PATH": "/usr/bin", "SECRET": "hidden"},
    )
    assert plan.command[1] == "--dbname=service=p8-demo-nex-eos"
    assert "SECRET" not in plan.environment
    for overrides, code in (
        ({"service_id": "bad/id"}, "backup_service_id_invalid"),
        ({"compression": "none"}, "backup_compression_invalid"),
        ({"postgres_major": True}, "backup_postgres_major_invalid"),
    ):
        values = {
            "service_id": "nex-eos",
            "libpq_service": "p8-demo-nex-eos",
            "backup_id": BACKUP_ID,
            "backup_root": tmp_path,
            "pg_dump_bin": Path("/usr/bin/pg_dump"),
            "service_file": tmp_path / "service.conf",
            "passfile": tmp_path / ".pgpass",
            "compression": "gzip:6",
            "postgres_major": 16,
        }
        values.update(overrides)
        with pytest.raises(PostgresBackupError, match=code):
            build_service_logical_backup_plan(**values)


def _load_script():
    path = ROOT / "scripts/deployment/run_p8_demo_database_guardrails.py"
    spec = importlib.util.spec_from_file_location("p8_demo_db_guardrails", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _backup_manifest() -> dict:
    payload = {
        "schema_version": "p8_demo_pre_migration_backup_set.v1",
        "backup_id": BACKUP_ID,
        "state": "CREATED",
        "service_count": 7,
        "targets": [
            {"service_id": target.service_id, "state": "CREATED"}
            for target in DEMO_DATABASE_TARGETS
        ],
    }
    return {**payload, "set_hash": semantic_sha256_hash_ref(payload)}


def test_guardrail_runner_reports_read_only_actual_postgres(tmp_path: Path) -> None:
    module = _load_script()
    responses = []
    for target in DEMO_DATABASE_TARGETS:
        responses.append(
            {
                "identity": (
                    target.expected_database_name,
                    target.expected_role_name,
                    False,
                    None,
                )
            }
        )
    result = module.run_demo_database_guardrails(
        _environment(),
        database_root=ROOT / "database",
        connect=_Connect(responses),
    )
    assert result["status"] == "PASS"
    assert result["actual_postgres"] is True
    assert result["migration_executed"] is False
    assert result["backup"]["state"] == "NOT_REQUESTED"
    assert "databases=7" in module.summary_line(result)
    report = tmp_path / "report.json"
    module.write_report(report, result)
    assert json.loads(report.read_text(encoding="utf-8")) == result


def test_guardrail_cli_requires_check_and_returns_safe_error(capsys) -> None:
    module = _load_script()
    assert module.main([]) == 2
    assert "--check is required" in capsys.readouterr().err
    assert module.main(["--check", "--env-file", "/missing"]) == 1
    captured = capsys.readouterr()
    assert "demo-secret" not in captured.err
