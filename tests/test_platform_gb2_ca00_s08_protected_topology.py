from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest
import run_gb2_ca00_s08_current_process_topology as smoke


def _database_environment() -> dict[str, str]:
    return {
        target.test_database_env: (
            "postgresql+psycopg://"
            f"{target.expected_role_name}:private@127.0.0.1:5432/"
            f"{target.expected_database_name}"
        )
        for target in smoke.CURRENT_POSTGRES_TEST_TARGETS
    }


def test_protected_topology_smoke_is_opt_in_and_fails_closed() -> None:
    skipped = smoke.run_gb2_ca00_s08_current_process_topology({})
    missing = smoke.run_gb2_ca00_s08_current_process_topology({smoke.SMOKE_ENV: "1"})

    assert skipped["status"] == "SKIPPED"
    assert skipped["actual_postgres"] is False
    assert missing["status"] == "FAIL"
    assert missing["failure_code"] == "execution_failed"


@pytest.mark.skipif(
    os.environ.get(smoke.SMOKE_ENV) != "1"
    or not os.environ.get(smoke.DATABASE_ENV_FILE_ENV),
    reason=(
        f"{smoke.SMOKE_ENV}=1 and {smoke.DATABASE_ENV_FILE_ENV} are required "
        "for protected PostgreSQL topology"
    ),
)
def test_actual_postgres_current_topology_acceptance() -> None:
    environment = dict(os.environ)
    environment.update(
        smoke.read_env_file(Path(environment[smoke.DATABASE_ENV_FILE_ENV]))
    )
    result = smoke.run_gb2_ca00_s08_current_process_topology(environment)

    assert result["status"] == "PASS", result
    assert result["evidence_classification"] == "PROTECTED_TOPOLOGY"
    assert result["actual_postgres"] is True
    assert result["artifact_count"] == 9
    assert result["process_count"] == 20
    assert result["database_count"] == 8
    assert result["cleanup_remaining"] == 0
    assert all(result["checks"].values())


def test_protected_topology_projects_sanitized_evidence(monkeypatch) -> None:
    environment = _database_environment()
    targets = tuple(
        SimpleNamespace(
            target=target,
            database_url=environment[target.test_database_env],
        )
        for target in smoke.CURRENT_POSTGRES_TEST_TARGETS
    )
    monkeypatch.setattr(
        smoke, "resolve_postgres_test_targets", lambda *_a, **_k: targets
    )
    monkeypatch.setattr(
        smoke,
        "_execute_protected_topology",
        lambda *_a, **_k: {
            "status": "PASS",
            "checks": {"closure": True, "postgres": True},
            "artifact_count": 9,
            "process_count": 20,
            "database_count": 8,
            "cleanup_remaining": 0,
        },
    )

    result = smoke.run_gb2_ca00_s08_current_process_topology(
        {**environment, smoke.SMOKE_ENV: "1"}
    )

    assert result["status"] == "PASS"
    assert result["evidence_classification"] == "PROTECTED_TOPOLOGY"
    assert result["actual_postgres"] is True
    assert len(result["database_targets"]) == 8
    assert "private@" not in str(result)
    assert result["secret_included"] is False
    assert smoke.summary_line(result) == (
        "gb2_ca00_s08_topology=pass classification=PROTECTED_TOPOLOGY "
        "checks=2/2 artifacts=9 processes=20 databases=8 remaining=0"
    )


def test_protected_topology_marks_failed_checks(monkeypatch) -> None:
    environment = _database_environment()
    targets = tuple(
        SimpleNamespace(
            target=target,
            database_url=environment[target.test_database_env],
        )
        for target in smoke.CURRENT_POSTGRES_TEST_TARGETS
    )
    monkeypatch.setattr(
        smoke, "resolve_postgres_test_targets", lambda *_a, **_k: targets
    )
    monkeypatch.setattr(
        smoke,
        "_execute_protected_topology",
        lambda *_a, **_k: {"status": "FAIL", "checks": {"closure": False}},
    )

    result = smoke.run_gb2_ca00_s08_current_process_topology(
        {**environment, smoke.SMOKE_ENV: "1"}
    )

    assert result["status"] == "FAIL"
    assert result["failure_code"] == "gb2_s08_topology_acceptance_failed"
    assert smoke.summary_line({"status": "FAIL"}).endswith(
        "artifacts=0 processes=0 databases=0 remaining=0"
    )


def test_command_and_redaction_helpers(monkeypatch) -> None:
    monkeypatch.setattr(
        smoke.subprocess,
        "run",
        lambda *_a, **_k: SimpleNamespace(
            returncode=0,
            stdout='noise\n{"status":"PASS"}\n',
            stderr="",
        ),
    )
    assert smoke._run_json_command(("python", "-m", "module"), {}) == {"status": "PASS"}

    monkeypatch.setattr(
        smoke.subprocess,
        "run",
        lambda *_a, **_k: SimpleNamespace(returncode=2, stdout="", stderr="private"),
    )
    try:
        smoke._run_checked(("python",), {})
    except RuntimeError as exc:
        assert "rc=2" in str(exc)
    else:
        raise AssertionError("non-zero command must fail")

    environment = _database_environment()
    first = smoke.CURRENT_POSTGRES_TEST_TARGETS[0]
    raw = environment[first.test_database_env]
    assert "private@" not in smoke._redact_detail(raw, environment)
