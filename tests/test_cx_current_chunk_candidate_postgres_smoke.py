from __future__ import annotations

import json
from types import SimpleNamespace

import run_cx_current_chunk_candidate_postgres_smoke as smoke


def test_smoke_is_opt_in_and_test_profile_only() -> None:
    skipped = smoke.run_cx_current_chunk_candidate_postgres_smoke({})
    denied = smoke.run_cx_current_chunk_candidate_postgres_smoke(
        {smoke.SMOKE_ENV: "1", smoke.PROFILE_ENV: "dev"}
    )

    assert skipped["status"] == "SKIPPED"
    assert smoke.SMOKE_ENV in skipped["skip_reason"]
    assert denied["error"]["code"] == "profile_not_allowed"


def test_smoke_rejects_non_test_database(monkeypatch) -> None:
    monkeypatch.setattr(
        smoke,
        "service_database_url",
        lambda *_args, **_kwargs: "postgresql://nex_cx_user:x@localhost/nex_cx_dev",
    )

    result = smoke.run_cx_current_chunk_candidate_postgres_smoke(
        {smoke.SMOKE_ENV: "1"}
    )

    assert result["error"]["code"] == "target_not_allowed"


def test_smoke_wraps_success_failure_and_exception(monkeypatch) -> None:
    url = "postgresql://nex_cx_user:x@localhost/nex_cx_test"
    monkeypatch.setattr(smoke, "service_database_url", lambda *_a, **_k: url)
    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *_a, **_k: SimpleNamespace(applied=("1354",), skipped=("old",)),
    )
    monkeypatch.setattr(
        smoke,
        "_execute_smoke",
        lambda _url: {
            "checks": {"ok": True},
            "failed_checks": [],
            "check_count": 1,
        },
    )
    passed = smoke.run_cx_current_chunk_candidate_postgres_smoke(
        {smoke.SMOKE_ENV: "1"}
    )
    assert passed["status"] == "PASS"
    assert passed["migration"] == {"applied": ["1354"], "skipped": ["old"]}

    monkeypatch.setattr(
        smoke,
        "_execute_smoke",
        lambda _url: {"failed_checks": ["stale_chunk_set_excluded"]},
    )
    failed = smoke.run_cx_current_chunk_candidate_postgres_smoke(
        {smoke.SMOKE_ENV: "1"}
    )
    assert failed["error"]["code"] == "current_chunk_candidate_smoke_failed"

    monkeypatch.setattr(
        smoke,
        "service_database_url",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("secret")),
    )
    raised = smoke.run_cx_current_chunk_candidate_postgres_smoke(
        {smoke.SMOKE_ENV: "1"}
    )
    assert raised["error"] == {"code": "execution_failed", "detail": "RuntimeError"}
    assert raised["redacted_database_url"] is None


def test_helpers_summary_and_main(monkeypatch, capsys) -> None:
    assert smoke._target_url_allowed(
        "postgresql+psycopg://nex_cx_user:secret@localhost/nex_cx_test"
    )
    assert not smoke._target_url_allowed(
        "postgresql://other:secret@localhost/nex_cx_test"
    )
    assert not smoke._target_url_allowed(
        "postgresql://nex_cx_user:secret@localhost/nex_cx_dev"
    )
    assert len(smoke._digest("value")) == 64
    assert smoke._context(owner_id="owner").subject_id == "owner"
    assert "skipped" in smoke.summary_line({"status": "SKIPPED"})
    assert "checks=5/5" in smoke.summary_line({"status": "PASS", "check_count": 5})
    assert "error=bad" in smoke.summary_line(
        {"status": "FAIL", "error": {"code": "bad"}}
    )
    assert "error=unknown" in smoke.summary_line({})

    monkeypatch.setattr(
        smoke,
        "run_cx_current_chunk_candidate_postgres_smoke",
        lambda: {"status": "SKIPPED"},
    )
    assert smoke.main(["--summary"]) == 0
    assert "skipped" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "SKIPPED"
    monkeypatch.setattr(
        smoke,
        "run_cx_current_chunk_candidate_postgres_smoke",
        lambda: {"status": "FAIL"},
    )
    assert smoke.main([]) == 1
