from __future__ import annotations

import pytest

import nex_runtime.postgres_restoration as restoration
from nex_runtime.postgres_restoration import (
    PlatformPostgresRestorationStore,
    PostgresRestorationError,
    PostgresRestorationSentinel,
    _execute_postgres_sentinel_operation,
)
from nex_runtime.postgres_targets import POSTGRES_TEST_TARGETS, resolve_postgres_test_targets


def valid_environment() -> dict[str, str]:
    return {
        target.test_database_env: (
            f"postgresql://{target.expected_role_name}:secret@127.0.0.1/"
            f"{target.expected_database_name}"
        )
        for target in POSTGRES_TEST_TARGETS
    }


def test_roundtrip_uses_all_service_targets_and_projects_safe_counts() -> None:
    rows: dict[str, PostgresRestorationSentinel] = {}
    calls: list[tuple[str, str]] = []

    def operator(target, phase, sentinel):
        calls.append((phase, sentinel.service_id))
        if phase == "WRITE":
            if sentinel.event_id in rows:
                return False
            rows[sentinel.event_id] = sentinel
            return True
        if phase == "RESTORE":
            return rows.get(sentinel.event_id) == sentinel
        if phase == "CLEANUP":
            return rows.pop(sentinel.event_id, None) is not None
        return sentinel.event_id not in rows

    store = PlatformPostgresRestorationStore.build(
        valid_environment(), operator=operator
    )

    written = store.write("s133-roundtrip-1")
    restored = store.restore("s133-roundtrip-1")
    cleaned = store.cleanup("s133-roundtrip-1")
    absent = store.confirm_absence("s133-roundtrip-1")

    assert [item.phase for item in (written, restored, cleaned, absent)] == [
        "WRITE",
        "RESTORE",
        "CLEANUP",
        "ABSENCE",
    ]
    assert all(item.service_count == 5 for item in (written, restored, cleaned, absent))
    assert all(item.record_count == 5 for item in (written, restored, cleaned, absent))
    assert written.to_public_projection() == {
        "schema_version": "platform_postgres_restoration_batch.v1",
        "requirement": "S133",
        "profile": "test",
        "phase": "WRITE",
        "service_count": 5,
        "record_count": 5,
    }
    assert len(calls) == 20
    assert not rows
    assert "secret" not in str(written.to_public_projection())


@pytest.mark.parametrize("run_id", ["", "S133-UPPER", "other-run", None])
def test_run_id_validation_fails_closed(run_id) -> None:
    store = PlatformPostgresRestorationStore.build(
        valid_environment(), operator=lambda *args: True
    )

    with pytest.raises(PostgresRestorationError, match="run_id_invalid"):
        store.write(run_id)


def test_configuration_failure_is_normalized() -> None:
    with pytest.raises(PostgresRestorationError, match="configuration_invalid"):
        PlatformPostgresRestorationStore.build({})


def test_partial_write_failure_cleans_completed_rows_best_effort() -> None:
    rows: set[str] = set()
    calls: list[tuple[str, str]] = []

    def operator(target, phase, sentinel):
        calls.append((phase, sentinel.service_id))
        if phase == "WRITE":
            if sentinel.service_id == "nex-cx":
                raise RuntimeError("private write detail")
            rows.add(sentinel.event_id)
            return True
        if sentinel.service_id == "nex-mo":
            raise RuntimeError("private cleanup detail")
        rows.discard(sentinel.event_id)
        return True

    store = PlatformPostgresRestorationStore.build(
        valid_environment(), operator=operator
    )

    with pytest.raises(PostgresRestorationError) as raised:
        store.write("s133-partial-write")

    assert raised.value.failure_code == "sentinel_write_failed"
    assert raised.value.service_id == "nex-cx"
    assert ("CLEANUP", "nex-mo") in calls
    assert ("CLEANUP", "nex-oa") in calls
    assert "s133-partial-write:nex-mo" in rows
    assert "private" not in str(raised.value)


def test_false_write_result_is_rejected_and_prior_row_is_cleaned() -> None:
    rows: set[str] = set()

    def operator(target, phase, sentinel):
        if phase == "WRITE":
            if sentinel.service_id == "nex-mo":
                return False
            rows.add(sentinel.event_id)
            return True
        rows.discard(sentinel.event_id)
        return True

    store = PlatformPostgresRestorationStore.build(
        valid_environment(), operator=operator
    )

    with pytest.raises(PostgresRestorationError) as raised:
        store.write("s133-false-write")

    assert raised.value.service_id == "nex-mo"
    assert not rows


@pytest.mark.parametrize(
    ("method", "phase", "failure_code"),
    [
        ("restore", "RESTORE", "sentinel_restore_failed"),
        ("cleanup", "CLEANUP", "sentinel_cleanup_failed"),
        ("confirm_absence", "ABSENCE", "sentinel_cleanup_incomplete"),
    ],
)
def test_phase_failures_are_normalized(method, phase, failure_code) -> None:
    def operator(target, actual_phase, sentinel):
        if actual_phase == phase and sentinel.service_id == "nex-mo":
            return False
        return True

    store = PlatformPostgresRestorationStore.build(
        valid_environment(), operator=operator
    )

    with pytest.raises(PostgresRestorationError) as raised:
        getattr(store, method)("s133-phase-failure")

    assert raised.value.failure_code == failure_code
    assert raised.value.service_id == "nex-mo"


def test_default_operator_is_bound_to_connect_factory(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        restoration,
        "_execute_postgres_sentinel_operation",
        lambda target, phase, sentinel, connect: calls.append(
            (target.target.service_id, phase, connect)
        )
        or True,
    )
    connect = object()
    store = PlatformPostgresRestorationStore.build(
        valid_environment(), connect=connect
    )

    assert store.write("s133-default-operator").record_count == 5
    assert calls[0] == ("nex-oa", "WRITE", connect)


class Cursor:
    def __init__(
        self,
        identity,
        sentinel: PostgresRestorationSentinel,
        *,
        rowcount: int = 1,
        restored: bool = True,
        absent: bool = True,
    ) -> None:
        self.identity = identity
        self.sentinel = sentinel
        self.default_rowcount = rowcount
        self.restored = restored
        self.absent = absent
        self.rowcount = -1
        self._row = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=None):
        compact = " ".join(sql.split()).lower()
        if compact.startswith("select current_database"):
            self._row = self.identity
        elif compact.startswith("insert into"):
            self.rowcount = self.default_rowcount
        elif compact.startswith("select service_id"):
            self._row = (
                self.sentinel.service_id,
                restoration.SENTINEL_EVENT_TYPE,
                "INFO",
                "S133 restart restoration sentinel",
                {"run_id": self.sentinel.run_id, "restart_iteration": 0},
            ) if self.restored else None
        elif compact.startswith("delete from"):
            self.rowcount = self.default_rowcount
        elif compact.startswith("select count"):
            self._row = (0 if self.absent else 1,)

    def fetchone(self):
        return self._row


class Connection:
    def __init__(self, cursor: Cursor) -> None:
        self._cursor = cursor
        self.commit_count = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def cursor(self):
        return self._cursor

    def commit(self):
        self.commit_count += 1


def execute_case(
    phase: str,
    *,
    identity=None,
    rowcount: int = 1,
    restored: bool = True,
    absent: bool = True,
):
    target = resolve_postgres_test_targets(valid_environment())[0]
    sentinel = PostgresRestorationSentinel(
        "s133-execute-case", "nex-oa", "s133-execute-case:nex-oa"
    )
    cursor = Cursor(
        identity
        or (
            target.target.expected_database_name,
            target.target.expected_role_name,
        ),
        sentinel,
        rowcount=rowcount,
        restored=restored,
        absent=absent,
    )
    connection = Connection(cursor)
    calls = []

    def connect(url, *, autocommit):
        calls.append((url, autocommit))
        return connection

    result = _execute_postgres_sentinel_operation(
        target, phase, sentinel, connect=connect
    )
    return result, connection, calls


@pytest.mark.parametrize("phase", restoration.RESTORATION_PHASES)
def test_postgres_operator_executes_every_phase_with_fresh_connection(phase) -> None:
    result, connection, calls = execute_case(phase)

    assert result is True
    assert len(calls) == 1
    assert calls[0][1] is False
    assert connection.commit_count == (1 if phase in {"WRITE", "CLEANUP"} else 0)


@pytest.mark.parametrize(
    ("phase", "kwargs"),
    [
        ("WRITE", {"rowcount": 0}),
        ("RESTORE", {"restored": False}),
        ("CLEANUP", {"rowcount": 0}),
        ("ABSENCE", {"absent": False}),
    ],
)
def test_postgres_operator_returns_false_for_incomplete_operation(phase, kwargs) -> None:
    assert execute_case(phase, **kwargs)[0] is False


def test_postgres_operator_rejects_phase_and_database_identity() -> None:
    with pytest.raises(ValueError, match="restoration_phase_invalid"):
        execute_case("UNKNOWN")
    with pytest.raises(ValueError, match="database_identity_mismatch"):
        execute_case("WRITE", identity=("wrong", "wrong"))
