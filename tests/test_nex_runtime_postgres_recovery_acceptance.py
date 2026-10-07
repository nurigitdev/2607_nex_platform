from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from nex_runtime.postgres_recovery_acceptance import (
    DatabaseRecoveryFingerprint,
    PostgresRecoveryAcceptanceError,
    compare_recovery_fingerprints,
    read_database_fingerprint,
    recovery_fingerprints_public_projection,
    write_recovery_libpq_files,
)
from nex_runtime.postgres_resilience import load_postgres_resilience_policy
from nex_runtime.postgres_targets import (
    POSTGRES_TEST_TARGETS,
    ResolvedPostgresTestTarget,
)


POLICY = load_postgres_resilience_policy(Path("deployment/postgres/s145-policy.yaml"))


def _resolved() -> tuple[ResolvedPostgresTestTarget, ...]:
    by_service = {target.service_id: target for target in POSTGRES_TEST_TARGETS}
    return tuple(
        ResolvedPostgresTestTarget(
            by_service[target.service_id],
            (
                f"postgresql+psycopg://{by_service[target.service_id].expected_role_name}:"
                f"private-{target.service_id}@127.0.0.1:5432/"
                f"{by_service[target.service_id].expected_database_name}"
            ),
            "postgresql+psycopg",
        )
        for target in POLICY.targets
    )


def test_libpq_files_separate_service_metadata_and_passwords(tmp_path: Path) -> None:
    service, passfile = write_recovery_libpq_files(
        resolved_targets=_resolved(),
        policy=POLICY,
        destination=tmp_path / "credentials",
        recovery_socket=tmp_path / "socket",
        recovery_port=15432,
    )
    service_text = service.read_text(encoding="utf-8")
    pass_text = passfile.read_text(encoding="utf-8")
    assert "private-" not in service_text
    assert service_text.count("connect_timeout=10") == 11
    assert "[nex-platform-cluster-backup]" in service_text
    assert pass_text.count("private-") == 5
    assert oct(service.stat().st_mode & 0o777) == "0o600"
    assert oct(passfile.stat().st_mode & 0o777) == "0o600"
    assert oct(service.parent.stat().st_mode & 0o777) == "0o700"


def test_libpq_files_escape_passfile_values(tmp_path: Path) -> None:
    first = _resolved()[0]
    escaped = replace(
        first,
        database_url=first.database_url.replace("private-nex-oa", "private%3Aback%5Cslash"),
    )
    resolved = (escaped, *_resolved()[1:])
    _service, passfile = write_recovery_libpq_files(
        resolved_targets=resolved,
        policy=POLICY,
        destination=tmp_path / "credentials",
        recovery_socket=tmp_path / "socket",
        recovery_port=15432,
    )
    first_line = passfile.read_text(encoding="utf-8").splitlines()[0]
    assert first_line.endswith(r"private\:back\\slash")


@pytest.mark.parametrize(
    ("values", "code"),
    [
        ({"resolved_targets": ()}, "target_coverage_invalid"),
        ({"recovery_socket": Path("relative")}, "endpoint_invalid"),
        ({"recovery_port": 80}, "endpoint_invalid"),
    ],
)
def test_libpq_files_reject_unsafe_boundary(tmp_path: Path, values: dict, code: str) -> None:
    kwargs = {
        "resolved_targets": _resolved(),
        "policy": POLICY,
        "destination": tmp_path / "credentials",
        "recovery_socket": tmp_path / "socket",
        "recovery_port": 15432,
    }
    kwargs.update(values)
    with pytest.raises(PostgresRecoveryAcceptanceError, match=code):
        write_recovery_libpq_files(**kwargs)


def test_libpq_files_reject_symlink_invalid_url_duplicate_and_newline(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)
    with pytest.raises(PostgresRecoveryAcceptanceError, match="credential_root_symlink"):
        write_recovery_libpq_files(
            resolved_targets=_resolved(), policy=POLICY, destination=linked,
            recovery_socket=tmp_path / "socket", recovery_port=15432,
        )

    first = _resolved()[0]
    missing_password = replace(first, database_url=first.database_url.replace(":private-nex-oa@", "@"))
    with pytest.raises(PostgresRecoveryAcceptanceError, match="source_url_invalid"):
        write_recovery_libpq_files(
            resolved_targets=(missing_password, *_resolved()[1:]), policy=POLICY,
            destination=tmp_path / "missing", recovery_socket=tmp_path / "socket",
            recovery_port=15432,
        )

    destination = tmp_path / "duplicate"
    write_recovery_libpq_files(
        resolved_targets=_resolved(), policy=POLICY, destination=destination,
        recovery_socket=tmp_path / "socket", recovery_port=15432,
    )
    with pytest.raises(PostgresRecoveryAcceptanceError, match="credential_file_exists"):
        write_recovery_libpq_files(
            resolved_targets=_resolved(), policy=POLICY, destination=destination,
            recovery_socket=tmp_path / "socket", recovery_port=15432,
        )

    bad_policy = replace(
        POLICY,
        targets=(replace(POLICY.targets[0], libpq_service="bad\nname"), *POLICY.targets[1:]),
    )
    with pytest.raises(PostgresRecoveryAcceptanceError, match="libpq_value_invalid"):
        write_recovery_libpq_files(
            resolved_targets=_resolved(), policy=bad_policy, destination=tmp_path / "bad",
            recovery_socket=tmp_path / "socket", recovery_port=15432,
        )


class Cursor:
    def __init__(self, *, database="nex_oa_test", migrations=("001", "002"), tables=3, extensions=()):
        self.database = database
        self.migrations = migrations
        self.tables = tables
        self.extensions = extensions
        self.query = ""

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, query):
        self.query = query

    def fetchone(self):
        if "current_database" in self.query:
            return (self.database,)
        if "count(*)" in self.query:
            return (self.tables,)
        return None

    def fetchall(self):
        values = self.extensions if "pg_extension" in self.query else self.migrations
        return [(value,) for value in values]


class Connection:
    def __init__(self, cursor: Cursor):
        self.value = cursor

    def cursor(self):
        return self.value


def test_database_fingerprint_and_public_projection() -> None:
    fingerprint = read_database_fingerprint(
        Connection(Cursor(extensions=("pgcrypto",))),
        service_id="nex-oa",
        expected_database_name="nex_oa_test",
        required_extensions=("pgcrypto",),
    )
    assert fingerprint.migration_count == 2
    assert fingerprint.table_count == 3
    assert len(fingerprint.migration_digest) == 64
    projection = recovery_fingerprints_public_projection({"nex-oa": fingerprint})
    assert projection["database_count"] == 1
    assert projection["required_extension_count"] == 1
    assert projection["database_urls_exposed"] is False
    compare_recovery_fingerprints({"nex-oa": fingerprint}, {"nex-oa": fingerprint})

    policy_shaped = read_database_fingerprint(
        Connection(Cursor(extensions=("pgcrypto",))),
        service_id="nex-oa",
        expected_database_name="nex_oa_test",
        required_extensions=(("pgcrypto", "1.3"),),
    )
    assert policy_shaped.required_extensions == ("pgcrypto",)


@pytest.mark.parametrize(
    ("cursor", "code"),
    [
        (Cursor(database="wrong"), "identity_invalid"),
        (Cursor(migrations=()), "fingerprint_invalid"),
        (Cursor(tables=0), "fingerprint_invalid"),
        (Cursor(extensions=()), "extension_missing"),
    ],
)
def test_database_fingerprint_rejects_invalid_restore(cursor: Cursor, code: str) -> None:
    with pytest.raises(PostgresRecoveryAcceptanceError, match=code):
        read_database_fingerprint(
            Connection(cursor), service_id="nex-oa",
            expected_database_name="nex_oa_test", required_extensions=("pgcrypto",),
        )


def test_fingerprint_comparison_rejects_coverage_and_drift() -> None:
    fingerprint = DatabaseRecoveryFingerprint("nex-oa", "nex_oa_test", "a" * 64, 2, 3, ())
    with pytest.raises(PostgresRecoveryAcceptanceError, match="coverage_invalid"):
        compare_recovery_fingerprints({"nex-oa": fingerprint}, {})
    changed = replace(fingerprint, table_count=4)
    with pytest.raises(PostgresRecoveryAcceptanceError, match="fingerprint_mismatch"):
        compare_recovery_fingerprints({"nex-oa": fingerprint}, {"nex-oa": changed})
