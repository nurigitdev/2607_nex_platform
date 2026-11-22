from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
import run_canonical_platform_database_guardrails as guardrail_script
import run_canonical_platform_migrations as migration_script
from nex_runtime.demo_database import (
    CURRENT_PLATFORM_BACKUP_SET_SCHEMA_VERSION,
    CURRENT_PLATFORM_DATABASE_BACKUP_CONFIRMATION,
    CURRENT_PLATFORM_DEVELOPMENT_DATABASE_TARGETS,
    DemoDatabaseGuardError,
    DemoDatabaseInspection,
    current_platform_backup_set_public_projection,
    execute_current_platform_pre_migration_backup_set,
    load_current_platform_backup_set_manifest,
    resolve_current_platform_database_targets,
    validate_current_platform_backup_set_manifest,
)
from nex_runtime.demo_migrations import (
    CURRENT_PLATFORM_MIGRATION_CONFIRMATION,
    execute_current_platform_migration_closure,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

BACKUP_ID = "20261118T010203Z-abcdef12"


def _environment() -> dict[str, str]:
    return {
        target.database_env: (
            "postgresql+psycopg://"
            f"{target.expected_role_name}:secret@127.0.0.1:5432/"
            f"{target.expected_database_name}"
        )
        for target in CURRENT_PLATFORM_DEVELOPMENT_DATABASE_TARGETS
    }


def _inspections(*, state: str = "MIGRATION_REQUIRED"):
    return tuple(
        DemoDatabaseInspection(
            service_id=target.service_id,
            database_name=target.expected_database_name,
            role_name=target.expected_role_name,
            identity_state="ADMITTED",
            migration_state=state,
            expected_migrations=("0001",),
            applied_migrations=("0001",) if state == "CURRENT" else (),
            missing_migrations=() if state == "CURRENT" else ("0001",),
            extra_migrations=(),
            source_inventory_hash=(
                f"sha256:{target.service_id.encode().hex():0<64}"[:71]
            ),
        )
        for target in CURRENT_PLATFORM_DEVELOPMENT_DATABASE_TARGETS
    )


def _manifest(inspections) -> dict:
    payload = {
        "schema_version": CURRENT_PLATFORM_BACKUP_SET_SCHEMA_VERSION,
        "backup_id": BACKUP_ID,
        "state": "CREATED",
        "service_count": 8,
        "targets": [
            {
                "service_id": item.service_id,
                "database_name": item.database_name,
                "role_name": item.role_name,
                "source_inventory_hash": item.source_inventory_hash,
                "applied_migrations": list(item.applied_migrations),
            }
            for item in inspections
        ],
    }
    return {**payload, "set_hash": semantic_sha256_hash_ref(payload)}


def test_current_platform_backup_is_exactly_eight_services_and_redacted(
    tmp_path: Path,
) -> None:
    targets = resolve_current_platform_database_targets(_environment())
    inspections = _inspections()
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs["env"]))
        kwargs["stdout"].write(b"current-platform-backup")
        return SimpleNamespace(returncode=0, stderr=b"")

    result = execute_current_platform_pre_migration_backup_set(
        targets,
        inspections,
        backup_id=BACKUP_ID,
        backup_root=tmp_path / "backups",
        pg_dump_bin=Path("/usr/bin/pg_dump"),
        confirmation=CURRENT_PLATFORM_DATABASE_BACKUP_CONFIRMATION,
        runner=runner,
        parent_environ={"PATH": "/usr/bin", "UNSAFE_SECRET": "blocked"},
    )

    assert result.schema_version == CURRENT_PLATFORM_BACKUP_SET_SCHEMA_VERSION
    assert len(result.targets) == len(calls) == 8
    assert result.manifest_path.stat().st_mode & 0o777 == 0o600
    assert all("current-platform-" in command[1] for command, _env in calls)
    assert all("UNSAFE_SECRET" not in environment for _command, environment in calls)
    projection = current_platform_backup_set_public_projection(result)
    assert projection["service_count"] == 8
    assert "secret" not in json.dumps(projection)
    manifest = load_current_platform_backup_set_manifest(result.manifest_path)
    assert manifest["set_hash"] == result.set_hash
    assert manifest["targets"][-1]["service_id"] == "nex-wa"


def test_current_platform_backup_rejects_old_or_incomplete_release_set() -> None:
    manifest = _manifest(_inspections())
    old_schema = dict(manifest)
    old_schema["schema_version"] = "p8_demo_pre_migration_backup_set.v1"
    old_schema["set_hash"] = semantic_sha256_hash_ref(
        {key: value for key, value in old_schema.items() if key != "set_hash"}
    )
    with pytest.raises(DemoDatabaseGuardError, match="manifest_invalid"):
        validate_current_platform_backup_set_manifest(old_schema)

    incomplete = _manifest(_inspections())
    incomplete["targets"] = incomplete["targets"][:-1]
    incomplete["service_count"] = 7
    incomplete["set_hash"] = semantic_sha256_hash_ref(
        {key: value for key, value in incomplete.items() if key != "set_hash"}
    )
    with pytest.raises(DemoDatabaseGuardError, match="services_incomplete"):
        validate_current_platform_backup_set_manifest(incomplete)


def test_current_platform_migration_is_ordered_and_requires_matching_backup(
    tmp_path: Path,
) -> None:
    targets = resolve_current_platform_database_targets(_environment())
    before = _inspections()
    after = _inspections(state="CURRENT")
    calls = []

    def runner(service_id, **kwargs):
        calls.append((service_id, kwargs))
        return SimpleNamespace(
            planned=("0001",), applied=("0001",), skipped=(), dry_run=False
        )

    report = execute_current_platform_migration_closure(
        targets,
        before,
        _manifest(before),
        confirmation=CURRENT_PLATFORM_MIGRATION_CONFIRMATION,
        database_root=tmp_path,
        migration_runner=runner,
        connect=lambda *_args, **_kwargs: None,
        inspector=lambda *_args, **_kwargs: after,
    )

    assert report["service_count"] == report["migration_current_count"] == 8
    assert [service_id for service_id, _kwargs in calls] == [
        target.service_id for target in CURRENT_PLATFORM_DEVELOPMENT_DATABASE_TARGETS
    ]
    assert report["database_urls_exposed"] is False
    assert report["evidence_hash"].startswith("sha256:")

    with pytest.raises(DemoDatabaseGuardError, match="confirmation_invalid"):
        execute_current_platform_migration_closure(
            targets,
            before,
            _manifest(before),
            confirmation="MIGRATE_P8_DEMO_DEV_DATABASES",
            database_root=tmp_path,
            migration_runner=runner,
            connect=lambda *_args, **_kwargs: None,
        )


def test_current_platform_guardrail_script_reports_without_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        guardrail_script,
        "inspect_demo_database_targets",
        lambda *_args, **_kwargs: _inspections(),
    )

    result = guardrail_script.run_current_platform_database_guardrails(
        _environment()
    )

    assert result["admission"]["service_count"] == 8
    assert result["backup"] == {"state": "NOT_REQUESTED"}
    assert result["redaction"]["database_urls_included"] is False
    assert "secret" not in json.dumps(result)
    assert "databases=8" in guardrail_script.summary_line(result)


def test_current_platform_guardrail_script_backup_and_cli_branches(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        guardrail_script,
        "inspect_demo_database_targets",
        lambda *_args, **_kwargs: _inspections(),
    )
    backup = SimpleNamespace(backup_id=BACKUP_ID)
    captured = {}

    def execute_backup(*args, **kwargs):
        captured.update(args=args, kwargs=kwargs)
        return backup

    monkeypatch.setattr(
        guardrail_script,
        "execute_current_platform_pre_migration_backup_set",
        execute_backup,
    )
    monkeypatch.setattr(
        guardrail_script,
        "current_platform_backup_set_public_projection",
        lambda value: {
            "state": "CREATED",
            "backup_id": value.backup_id,
            "service_count": 8,
        },
    )

    result = guardrail_script.run_current_platform_database_guardrails(
        _environment(),
        execute_backup=True,
        backup_root=tmp_path,
        backup_id=BACKUP_ID,
        backup_confirmation=CURRENT_PLATFORM_DATABASE_BACKUP_CONFIRMATION,
    )

    assert result["backup"]["state"] == "CREATED"
    assert captured["kwargs"]["backup_id"] == BACKUP_ID
    assert captured["kwargs"]["confirmation"] == (
        CURRENT_PLATFORM_DATABASE_BACKUP_CONFIRMATION
    )
    report = tmp_path / "guardrail.json"
    guardrail_script.write_report(report, result)
    assert json.loads(report.read_text(encoding="utf-8"))["status"] == "PASS"
    assert guardrail_script.main([]) == 2
    assert "--check is required" in capsys.readouterr().err

    monkeypatch.setattr(
        guardrail_script,
        "run_current_platform_database_guardrails",
        lambda *_args, **_kwargs: result,
    )
    cli_report = tmp_path / "cli-report.json"
    assert (
        guardrail_script.main(
            ["--check", "--summary", "--report", str(cli_report)]
        )
        == 0
    )
    assert "databases=8" in capsys.readouterr().out
    assert cli_report.is_file()

    monkeypatch.setattr(
        guardrail_script,
        "run_current_platform_database_guardrails",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            DemoDatabaseGuardError("blocked")
        ),
    )
    assert guardrail_script.main(["--check", "--report", str(cli_report)]) == 1
    assert "blocked" in capsys.readouterr().err
    assert re.fullmatch(
        r"[0-9]{8}T[0-9]{6}Z-[a-f0-9]{16}",
        guardrail_script._new_backup_id(),
    )


def test_canonical_migration_runner_uses_current_platform_contract(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    targets = resolve_current_platform_database_targets(_environment())
    inspections = _inspections()
    manifest = _manifest(inspections)
    manifest_path = tmp_path / "backup.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    captured = {}

    monkeypatch.setattr(
        migration_script,
        "resolve_current_platform_database_targets",
        lambda environ: targets,
    )
    monkeypatch.setattr(
        migration_script,
        "inspect_demo_database_targets",
        lambda *_args, **_kwargs: inspections,
    )

    def execute(targets_arg, inspections_arg, manifest_arg, **kwargs):
        captured.update(
            targets=targets_arg,
            inspections=inspections_arg,
            manifest=manifest_arg,
            kwargs=kwargs,
        )
        return {"status": "PASS"}

    monkeypatch.setattr(
        migration_script,
        "execute_current_platform_migration_closure",
        execute,
    )

    result = migration_script.run_canonical_platform_migrations(
        _environment(),
        backup_manifest_path=manifest_path,
        confirmation=CURRENT_PLATFORM_MIGRATION_CONFIRMATION,
        database_root=tmp_path,
        connect=object(),
        migration_runner=object(),
    )

    assert result == {"status": "PASS"}
    assert len(captured["targets"]) == len(captured["inspections"]) == 8
    assert captured["manifest"]["service_count"] == 8
    assert captured["kwargs"]["confirmation"] == (
        CURRENT_PLATFORM_MIGRATION_CONFIRMATION
    )
