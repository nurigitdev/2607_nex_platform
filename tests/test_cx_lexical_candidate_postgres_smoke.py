from __future__ import annotations

import json
from types import SimpleNamespace

import run_cx_lexical_candidate_postgres_smoke as smoke


def test_smoke_is_opt_in() -> None:
    result = smoke.run_cx_lexical_candidate_postgres_smoke({})

    assert result["status"] == "SKIPPED"
    assert smoke.SMOKE_ENV in result["skip_reason"]


def test_smoke_rejects_non_test_profile() -> None:
    result = smoke.run_cx_lexical_candidate_postgres_smoke(
        {smoke.SMOKE_ENV: "1", smoke.PROFILE_ENV: "dev"}
    )

    assert result["status"] == "FAIL"
    assert result["error"]["code"] == "profile_not_allowed"


def test_smoke_rejects_non_test_database(monkeypatch) -> None:
    monkeypatch.setattr(
        smoke,
        "service_database_url",
        lambda *_args, **_kwargs: "postgresql://nex_cx_user:x@localhost/nex_cx_dev",
    )

    result = smoke.run_cx_lexical_candidate_postgres_smoke({smoke.SMOKE_ENV: "1"})

    assert result["status"] == "FAIL"
    assert result["error"]["code"] == "target_not_allowed"


def test_smoke_wraps_success_and_failed_checks(monkeypatch) -> None:
    url = "postgresql://nex_cx_user:x@localhost/nex_cx_test"
    monkeypatch.setattr(smoke, "service_database_url", lambda *_a, **_k: url)
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *_a, **_k: SimpleNamespace(applied=("0943",), skipped=("old",)),
    )
    monkeypatch.setattr(smoke, "service_database_env", lambda *_a, **_k: "CX_TEST")
    monkeypatch.setattr(
        smoke,
        "_execute_smoke",
        lambda _url: {
            "checks": {"ok": True},
            "failed_checks": [],
            "check_count": 1,
            "candidate_count": 2,
        },
    )

    result = smoke.run_cx_lexical_candidate_postgres_smoke({smoke.SMOKE_ENV: "1"})

    assert result["status"] == "PASS"
    assert result["database_env"] == "CX_TEST"
    assert result["migration"] == {"applied": ["0943"], "skipped": ["old"]}

    monkeypatch.setattr(
        smoke,
        "_execute_smoke",
        lambda _url: {"failed_checks": ["owner_filter"]},
    )
    failed = smoke.run_cx_lexical_candidate_postgres_smoke({smoke.SMOKE_ENV: "1"})
    assert failed["error"]["code"] == "lexical_candidate_smoke_failed"


def test_smoke_redacts_execution_exception(monkeypatch) -> None:
    monkeypatch.setattr(
        smoke,
        "service_database_url",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("secret")),
    )

    result = smoke.run_cx_lexical_candidate_postgres_smoke({smoke.SMOKE_ENV: "1"})

    assert result["status"] == "FAIL"
    assert result["error"] == {"code": "execution_failed", "detail": "RuntimeError"}
    assert result["redacted_database_url"] is None


def test_target_guard_and_helpers() -> None:
    assert smoke._target_url_allowed(
        "postgresql+psycopg://nex_cx_user:secret@127.0.0.1/nex_cx_test"
    )
    assert not smoke._target_url_allowed(
        "postgresql://other:secret@127.0.0.1/nex_cx_test"
    )
    assert not smoke._target_url_allowed(
        "postgresql://nex_cx_user:secret@127.0.0.1/nex_cx_dev"
    )
    assert len(smoke._digest("value")) == 64
    fixture = smoke._fixture(owner_id="owner", lifecycle_status="ACTIVE", counts=(2, 1))
    assert fixture.owner_id == "owner"
    assert len(fixture.chunks) == 2


def test_summary_lines() -> None:
    assert "skipped" in smoke.summary_line({"status": "SKIPPED"})
    assert "checks=9/9" in smoke.summary_line(
        {"status": "PASS", "check_count": 9, "candidate_count": 2}
    )
    assert "error=bad" in smoke.summary_line(
        {"status": "FAIL", "error": {"code": "bad"}}
    )
    assert "error=unknown" in smoke.summary_line({})


def test_main_paths(monkeypatch, capsys) -> None:
    skipped = {"status": "SKIPPED"}
    monkeypatch.setattr(
        smoke,
        "run_cx_lexical_candidate_postgres_smoke",
        lambda: skipped,
    )
    assert smoke.main(["--summary"]) == 0
    assert "skipped" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "SKIPPED"

    monkeypatch.setattr(
        smoke,
        "run_cx_lexical_candidate_postgres_smoke",
        lambda: {"status": "FAIL"},
    )
    assert smoke.main([]) == 1
