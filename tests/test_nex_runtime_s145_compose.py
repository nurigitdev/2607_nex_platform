from __future__ import annotations

from pathlib import Path
import shutil

import pytest
import yaml

import nex_runtime.s145_compose as compose_module
from nex_runtime.postgres_backup_catalog import BackupCatalog
from nex_runtime.s145_compose import (
    S145ComposeError,
    run_deterministic_backup_rehearsal,
    validate_s145_compose_assets,
)


ROOT = Path(".")


def _assets(tmp_path: Path) -> Path:
    compose_target = tmp_path / "deployment/compose"
    oci_target = tmp_path / "deployment/oci"
    postgres_target = tmp_path / "deployment/postgres"
    compose_target.mkdir(parents=True)
    oci_target.mkdir(parents=True)
    postgres_target.mkdir(parents=True)
    shutil.copy(
        ROOT / "deployment/compose/s145-postgres-operations.override.yaml",
        compose_target,
    )
    shutil.copy(ROOT / "deployment/oci/postgres-operator.Containerfile", oci_target)
    shutil.copy(ROOT / "deployment/postgres/s145-policy.yaml", postgres_target)
    return tmp_path


def _mutate_compose(tmp_path: Path, mutate) -> Path:
    root = _assets(tmp_path)
    path = root / "deployment/compose/s145-postgres-operations.override.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    mutate(document)
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    return root


def test_canonical_compose_assets_and_rehearsal_pass() -> None:
    assets = validate_s145_compose_assets(ROOT)
    assert assets["state"] == "VALID"
    assert assets["profile"] == "postgres-operations"
    assert assets["application_release_set_changed"] is False
    rehearsal = run_deterministic_backup_rehearsal(ROOT)
    assert rehearsal == {
        "schema_version": "s145_deterministic_backup_rehearsal.v1",
        "state": "PASS",
        "service_count": 5,
        "archive_count": 5,
        "attempt_count": 1,
        "credential_values_persisted": False,
        "actual_postgres_contacted": False,
    }


def test_compose_assets_reject_missing_and_non_mapping(tmp_path: Path) -> None:
    with pytest.raises(S145ComposeError, match="unreadable"):
        validate_s145_compose_assets(tmp_path)
    root = _assets(tmp_path / "invalid")
    (root / "deployment/compose/s145-postgres-operations.override.yaml").write_text("[]\n")
    with pytest.raises(S145ComposeError, match="document is invalid"):
        validate_s145_compose_assets(root)


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda d: d.update(services={}), "service coverage drift"),
        (lambda d: d["services"].update(**{"postgres-backup-operator": []}), "service is invalid"),
        (lambda d: d["services"]["postgres-backup-operator"].update(profiles=[]), "hardening drift"),
        (lambda d: d["services"]["postgres-backup-operator"].update(image="mutable:latest"), "immutable-gated"),
        (lambda d: d["services"]["postgres-backup-operator"].update(environment={}), "environment drift"),
        (lambda d: d["services"]["postgres-backup-operator"].update(volumes=[]), "storage mount drift"),
        (lambda d: d["services"]["postgres-backup-operator"]["volumes"][0].update(target="/wrong"), "storage mount drift"),
        (lambda d: d["services"]["postgres-backup-operator"].update(secrets=[]), "credential mount drift"),
        (lambda d: d.update(secrets={}), "secret definition drift"),
        (lambda d: d.update(networks={}), "network definition drift"),
    ],
)
def test_compose_assets_reject_contract_drift(tmp_path: Path, mutate, code: str) -> None:
    root = _mutate_compose(tmp_path, mutate)
    with pytest.raises(S145ComposeError, match=code):
        validate_s145_compose_assets(root)


def test_compose_assets_reject_privilege_and_containerfile_drift(tmp_path: Path) -> None:
    root = _assets(tmp_path / "privilege")
    path = root / "deployment/compose/s145-postgres-operations.override.yaml"
    path.write_text(path.read_text() + "\n# /var/run/docker.sock\n", encoding="utf-8")
    with pytest.raises(S145ComposeError, match="privilege boundary drift"):
        validate_s145_compose_assets(root)

    root = _assets(tmp_path / "containerfile")
    path = root / "deployment/oci/postgres-operator.Containerfile"
    path.write_text(path.read_text().replace("USER 65532:65532", "USER 0:0"))
    with pytest.raises(S145ComposeError, match="Containerfile drift"):
        validate_s145_compose_assets(root)


def test_rehearsal_fails_closed_on_catalog_issue(monkeypatch) -> None:
    original = compose_module.build_backup_catalog

    def invalid(*args, **kwargs):
        catalog = original(*args, **kwargs)
        return BackupCatalog(catalog.service_id, catalog.entries, ("drift",), catalog.partials)

    monkeypatch.setattr(compose_module, "build_backup_catalog", invalid)
    with pytest.raises(S145ComposeError, match="rehearsal failed"):
        run_deterministic_backup_rehearsal(ROOT)
