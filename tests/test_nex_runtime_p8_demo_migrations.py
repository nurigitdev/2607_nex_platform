from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from nex_runtime.demo_database import (
    DEMO_DATABASE_TARGETS,
    DemoDatabaseGuardError,
    DemoDatabaseInspection,
    resolve_demo_database_targets,
)
from nex_runtime.demo_migrations import (
    DEMO_MIGRATION_CONFIRMATION,
    execute_demo_migration_closure,
)
from nex_runtime.semantic_hashes import semantic_sha256_hash_ref

ROOT = Path(__file__).resolve().parents[1]


def _environment() -> dict[str, str]:
    return {
        target.database_env: (
            "postgresql+psycopg://"
            f"{target.expected_role_name}:secret@127.0.0.1:5432/"
            f"{target.expected_database_name}"
        )
        for target in DEMO_DATABASE_TARGETS
    }


def _inspections(*, state: str = "MIGRATION_REQUIRED"):
    records = []
    for target in DEMO_DATABASE_TARGETS:
        records.append(
            DemoDatabaseInspection(
                service_id=target.service_id,
                database_name=target.expected_database_name,
                role_name=target.expected_role_name,
                identity_state="ADMITTED",
                migration_state=state,
                expected_migrations=("0001",),
                applied_migrations=("0001",) if state == "CURRENT" else (),
                missing_migrations=() if state == "CURRENT" else ("0001",),
                extra_migrations=("9999",) if state == "DRIFT" else (),
                source_inventory_hash=f"sha256:{target.service_id.encode().hex():0<64}"[
                    :71
                ],
            )
        )
    return tuple(records)


def _manifest(inspections) -> dict:
    payload = {
        "schema_version": "p8_demo_pre_migration_backup_set.v1",
        "backup_id": "20261025T010203Z-abcdef12",
        "state": "CREATED",
        "service_count": 7,
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


class _Connect:
    def __init__(self, inspections):
        self.inspections = iter(inspections)

    def __call__(self, _url, **_kwargs):
        inspection = next(self.inspections)
        return _Connection(inspection)


class _Connection:
    def __init__(self, inspection):
        self.inspection = inspection

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def cursor(self):
        return _Cursor(self.inspection)


class _Cursor:
    def __init__(self, inspection):
        self.inspection = inspection
        self.query = ""

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, query):
        self.query = str(query)

    def fetchone(self):
        return (
            self.inspection.database_name,
            self.inspection.role_name,
            False,
            "schema_migrations",
        )

    def fetchall(self):
        return [(item,) for item in self.inspection.applied_migrations]


def test_demo_migration_execution_is_ordered_current_and_redacted(
    tmp_path: Path,
) -> None:
    targets = resolve_demo_database_targets(_environment())
    before = _inspections()
    after = _inspections(state="CURRENT")
    calls = []

    def runner(service_id, **kwargs):
        calls.append((service_id, kwargs))
        return SimpleNamespace(
            planned=("0001",), applied=("0001",), skipped=(), dry_run=False
        )

    report = execute_demo_migration_closure(
        targets,
        before,
        _manifest(before),
        confirmation=DEMO_MIGRATION_CONFIRMATION,
        database_root=tmp_path,
        migration_runner=runner,
        connect=_Connect(after),
        inspector=lambda *_args, **_kwargs: after,
    )
    assert report["status"] == "PASS"
    assert report["migration_current_count"] == 7
    assert report["resumed_service_count"] == 0
    assert [item[0] for item in calls] == [
        target.service_id for target in DEMO_DATABASE_TARGETS
    ]
    assert all(item[1]["profile"] == "dev" for item in calls)
    assert "secret" not in json.dumps(report)
    assert report["evidence_hash"].startswith("sha256:")


@pytest.mark.parametrize(
    ("mutation", "code"),
    (
        (lambda values: values.update(confirmation="wrong"), "confirmation_invalid"),
        (
            lambda values: values.update(targets=values["targets"][:-1]),
            "database_set_incomplete",
        ),
        (
            lambda values: values.update(inspections=values["inspections"][:-1]),
            "inspection_set_incomplete",
        ),
    ),
)
def test_demo_migration_admission_fails_closed(
    tmp_path: Path, mutation, code: str
) -> None:
    before = _inspections()
    values = {
        "targets": resolve_demo_database_targets(_environment()),
        "inspections": before,
        "backup_manifest": _manifest(before),
        "confirmation": DEMO_MIGRATION_CONFIRMATION,
    }
    mutation(values)
    with pytest.raises(DemoDatabaseGuardError, match=code):
        execute_demo_migration_closure(
            **values,
            database_root=tmp_path,
            migration_runner=lambda *_args, **_kwargs: None,
            connect=_Connect(()),
        )


def test_demo_migration_rejects_drift_backup_mismatch_and_bad_runner(
    tmp_path: Path,
) -> None:
    targets = resolve_demo_database_targets(_environment())
    before = list(_inspections())
    drifted = DemoDatabaseInspection(
        **{
            **before[0].__dict__,
            "migration_state": "DRIFT",
            "extra_migrations": ("9999",),
        }
    )
    with pytest.raises(DemoDatabaseGuardError, match="drift_not_admitted"):
        execute_demo_migration_closure(
            targets,
            (drifted, *before[1:]),
            _manifest(before),
            confirmation=DEMO_MIGRATION_CONFIRMATION,
            database_root=tmp_path,
            migration_runner=lambda *_args, **_kwargs: None,
            connect=_Connect(()),
        )

    blocked = DemoDatabaseInspection(
        **{**before[0].__dict__, "identity_state": "BLOCKED"}
    )
    with pytest.raises(DemoDatabaseGuardError, match="identity_not_admitted"):
        execute_demo_migration_closure(
            targets,
            (blocked, *before[1:]),
            _manifest(before),
            confirmation=DEMO_MIGRATION_CONFIRMATION,
            database_root=tmp_path,
            migration_runner=lambda *_args, **_kwargs: None,
            connect=_Connect(()),
        )

    manifest = _manifest(before)
    manifest["targets"][0]["source_inventory_hash"] = "sha256:" + "f" * 64
    payload = {key: value for key, value in manifest.items() if key != "set_hash"}
    manifest["set_hash"] = semantic_sha256_hash_ref(payload)
    with pytest.raises(DemoDatabaseGuardError, match="source_inventory_changed"):
        execute_demo_migration_closure(
            targets,
            before,
            manifest,
            confirmation=DEMO_MIGRATION_CONFIRMATION,
            database_root=tmp_path,
            migration_runner=lambda *_args, **_kwargs: None,
            connect=_Connect(()),
        )

    manifest = _manifest(before)
    manifest["targets"][0]["database_name"] = "wrong"
    payload = {key: value for key, value in manifest.items() if key != "set_hash"}
    manifest["set_hash"] = semantic_sha256_hash_ref(payload)
    with pytest.raises(DemoDatabaseGuardError, match="backup_identity_mismatch"):
        execute_demo_migration_closure(
            targets,
            before,
            manifest,
            confirmation=DEMO_MIGRATION_CONFIRMATION,
            database_root=tmp_path,
            migration_runner=lambda *_args, **_kwargs: None,
            connect=_Connect(()),
        )

    manifest = _manifest(before)
    manifest["targets"][0]["applied_migrations"] = ["0000"]
    payload = {key: value for key, value in manifest.items() if key != "set_hash"}
    manifest["set_hash"] = semantic_sha256_hash_ref(payload)
    with pytest.raises(DemoDatabaseGuardError, match="database_changed_after_backup"):
        execute_demo_migration_closure(
            targets,
            before,
            manifest,
            confirmation=DEMO_MIGRATION_CONFIRMATION,
            database_root=tmp_path,
            migration_runner=lambda *_args, **_kwargs: None,
            connect=_Connect(()),
        )

    with pytest.raises(DemoDatabaseGuardError, match="dry_run_not_admitted"):
        execute_demo_migration_closure(
            targets,
            before,
            _manifest(before),
            confirmation=DEMO_MIGRATION_CONFIRMATION,
            database_root=tmp_path,
            migration_runner=lambda *_args, **_kwargs: SimpleNamespace(dry_run=True),
            connect=_Connect(()),
        )


def test_demo_migration_rejects_non_current_post_state(tmp_path: Path) -> None:
    targets = resolve_demo_database_targets(_environment())
    before = _inspections()
    with pytest.raises(DemoDatabaseGuardError, match="post_state_not_current"):
        execute_demo_migration_closure(
            targets,
            before,
            _manifest(before),
            confirmation=DEMO_MIGRATION_CONFIRMATION,
            database_root=tmp_path,
            migration_runner=lambda *_args, **_kwargs: SimpleNamespace(
                planned=("0001",), applied=("0001",), skipped=(), dry_run=False
            ),
            connect=_Connect(before),
            inspector=lambda *_args, **_kwargs: before,
        )


def test_demo_migration_allows_canonical_partial_resume(tmp_path: Path) -> None:
    targets = resolve_demo_database_targets(_environment())
    before = _inspections(state="CURRENT")
    backed_up = _inspections()
    report = execute_demo_migration_closure(
        targets,
        before,
        _manifest(backed_up),
        confirmation=DEMO_MIGRATION_CONFIRMATION,
        database_root=tmp_path,
        migration_runner=lambda *_args, **_kwargs: SimpleNamespace(
            planned=("0001",), applied=(), skipped=("0001",), dry_run=False
        ),
        connect=_Connect(before),
        inspector=lambda *_args, **_kwargs: before,
    )
    assert report["resumed_service_count"] == 7


def _load_script():
    path = ROOT / "scripts/deployment/run_canonical_platform_migrations.py"
    spec = importlib.util.spec_from_file_location("canonical_platform_migrations", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_demo_migration_cli_summary_report_and_error(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    module = _load_script()
    report = {
        "status": "PASS",
        "service_count": 7,
        "migration_current_count": 7,
        "backup_id": "backup",
        "services": [{"applied": ["0001"]}],
    }
    monkeypatch.setattr(
        module,
        "run_canonical_platform_migrations",
        lambda *_args, **_kwargs: report,
    )
    output = tmp_path / "report.json"
    assert (
        module.main(
            [
                "--backup-manifest",
                str(tmp_path / "backup.json"),
                "--confirmation",
                DEMO_MIGRATION_CONFIRMATION,
                "--report",
                str(output),
                "--summary",
            ]
        )
        == 0
    )
    assert json.loads(output.read_text(encoding="utf-8")) == report
    assert "current=7" in capsys.readouterr().out

    monkeypatch.setattr(
        module,
        "run_canonical_platform_migrations",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            DemoDatabaseGuardError("safe_failure")
        ),
    )
    assert (
        module.main(
            [
                "--backup-manifest",
                str(tmp_path / "backup.json"),
                "--confirmation",
                DEMO_MIGRATION_CONFIRMATION,
            ]
        )
        == 1
    )
    assert "safe_failure" in capsys.readouterr().err
