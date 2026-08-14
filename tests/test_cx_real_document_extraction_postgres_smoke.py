from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import text

import run_cx_real_document_extraction_postgres_smoke as smoke
from nex_runtime import build_engine
from run_migrations import MigrationError
from test_cx_uploaded_source_extraction_postgres_smoke import (
    _sqlite_cx_repository_url,
)


def test_real_document_extraction_postgres_smoke_skips_by_default() -> None:
    evidence = smoke.run_cx_real_document_extraction_postgres_smoke({})

    assert evidence["status"] == "SKIPPED"
    assert smoke.SMOKE_ENV in evidence["skip_reason"]
    assert smoke.summary_line(evidence).startswith(
        "cx_real_document_extraction_postgres_smoke=skipped"
    )


def test_real_document_extraction_postgres_smoke_rejects_non_test_profile() -> None:
    evidence = smoke.run_cx_real_document_extraction_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            smoke.SMOKE_PROFILE_ENV: "dev",
        }
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "profile_not_allowed"
    assert "reason=profile_not_allowed" in smoke.summary_line(evidence)


def test_real_document_extraction_postgres_smoke_reports_migration_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_migration_error(*args: object, **kwargs: object) -> None:
        raise MigrationError("boom")

    monkeypatch.setattr(smoke, "run_service_migrations", raise_migration_error)

    evidence = smoke.run_cx_real_document_extraction_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            "NEX_CX_TEST_DATABASE_URL": (
                "postgresql+psycopg://nex_cx_user:secret@127.0.0.1/nex_cx_test"
            ),
        }
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "configuration_invalid"
    assert evidence["detail"] == "boom"


def test_real_document_extraction_postgres_smoke_high_level_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = SimpleNamespace(
        service_id="nex-cx",
        profile="test",
        planned=("001", "002", "003"),
        applied=(),
        skipped=("001", "002", "003"),
        dry_run=False,
    )
    execution = {
        "format_count": 4,
        "formats": [
            {
                "source_format": "pdf",
                "extractor_mode": "pdf_to_markdown",
                "artifact_count": 1,
                "markdown_char_count": 42,
            }
        ],
        "db_observations": {
            "extraction_artifact_count": 4,
            "source_checksum_verified_count": 4,
        },
        "checks": {"all_good": True},
    }
    seen: dict[str, object] = {}

    monkeypatch.setattr(
        smoke,
        "run_service_migrations",
        lambda *args, **kwargs: migration,
    )

    def fake_execute(**kwargs: object) -> dict[str, object]:
        seen.update(kwargs)
        return execution

    monkeypatch.setattr(smoke, "_execute_real_document_extraction_smoke", fake_execute)

    evidence = smoke.run_cx_real_document_extraction_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            "NEX_CX_TEST_DATABASE_URL": (
                "postgresql+psycopg://nex_cx_user:secret@127.0.0.1/nex_cx_test"
            ),
        }
    )

    assert evidence["status"] == "PASS"
    assert evidence["redacted_database_url"].endswith("@127.0.0.1/nex_cx_test")
    assert evidence["migration"]["skipped_count"] == 3
    assert seen["database_env"] == "NEX_CX_TEST_DATABASE_URL"
    assert seen["runtime_environ"]["NEX_CX_PERSISTENCE_MODE"] == "postgres"
    assert smoke.summary_line(evidence).endswith("formats=4 artifacts=4")


def test_real_document_extraction_postgres_smoke_reports_execution_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = SimpleNamespace(
        service_id="nex-cx",
        profile="test",
        planned=("001",),
        applied=(),
        skipped=("001",),
        dry_run=False,
    )

    monkeypatch.setattr(smoke, "run_service_migrations", lambda *args, **kwargs: migration)

    def raise_runtime_error(**kwargs: object) -> dict[str, object]:
        raise RuntimeError("unavailable")

    monkeypatch.setattr(smoke, "_execute_real_document_extraction_smoke", raise_runtime_error)

    evidence = smoke.run_cx_real_document_extraction_postgres_smoke(
        {
            smoke.SMOKE_ENV: "1",
            "NEX_CX_TEST_DATABASE_URL": (
                "postgresql+psycopg://nex_cx_user:secret@127.0.0.1/nex_cx_test"
            ),
        }
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "execution_failed"
    assert evidence["detail"] == "RuntimeError"


def test_real_document_extraction_postgres_smoke_requires_session_factory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = _sqlite_cx_repository_url(tmp_path)
    monkeypatch.setattr(
        smoke,
        "attach_service_persistence_runtime",
        lambda *args, **kwargs: SimpleNamespace(mode="postgres", api_session_factory=None),
    )

    with pytest.raises(RuntimeError, match="session factory is unavailable"):
        smoke._execute_real_document_extraction_smoke(
            database_env="NEX_CX_TEST_DATABASE_URL",
            database_url=database_url,
            runtime_environ={
                "NEX_CX_DATABASE_URL": database_url,
                "NEX_CX_TEST_DATABASE_URL": database_url,
                "NEX_CX_PERSISTENCE_MODE": "postgres",
            },
        )


def test_real_document_extraction_postgres_smoke_sqlite_route_path(
    tmp_path: Path,
) -> None:
    database_url = _sqlite_cx_repository_url(tmp_path)

    result = smoke._execute_real_document_extraction_smoke(
        database_env="NEX_CX_TEST_DATABASE_URL",
        database_url=database_url,
        runtime_environ={
            "NEX_CX_DATABASE_URL": database_url,
            "NEX_CX_TEST_DATABASE_URL": database_url,
            "NEX_CX_PERSISTENCE_MODE": "postgres",
        },
    )

    assert all(result["checks"].values())
    assert result["format_count"] == 4
    assert {item["source_format"] for item in result["formats"]} == {
        "pdf",
        "docx",
        "pptx",
        "xlsx",
    }
    assert result["db_observations"] == {
        "extraction_artifact_count": 4,
        "source_checksum_verified_count": 4,
    }
    assert len(result["cleanup_observations"]) == 4
    assert all(
        item["before"]["extraction_artifact_rows"] == 1
        and item["after"]["extraction_artifact_rows"] == 0
        for item in result["cleanup_observations"]
    )
    smoke.assert_evidence_redacted(result)
    assert smoke.SECRET_MARKER_PREFIX not in json.dumps(result, ensure_ascii=False)


def test_real_document_extraction_postgres_smoke_check_failure_cleans_up(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = _sqlite_cx_repository_url(tmp_path)
    monkeypatch.setattr(smoke, "_redaction_safe", lambda *args, **kwargs: False)

    with pytest.raises(RuntimeError, match="smoke checks failed"):
        smoke._execute_real_document_extraction_smoke(
            database_env="NEX_CX_TEST_DATABASE_URL",
            database_url=database_url,
            runtime_environ={
                "NEX_CX_DATABASE_URL": database_url,
                "NEX_CX_TEST_DATABASE_URL": database_url,
                "NEX_CX_PERSISTENCE_MODE": "postgres",
            },
        )

    engine = build_engine(database_url)
    with engine.begin() as connection:
        assert connection.execute(text("SELECT count(*) FROM cx_content_objects")).scalar_one() == 0
        assert connection.execute(text("SELECT count(*) FROM cx_source_files")).scalar_one() == 0


def test_real_document_extraction_postgres_smoke_redaction_guard() -> None:
    smoke.assert_evidence_redacted({"safe": "ok"})

    for forbidden in [
        smoke.SECRET_MARKER_PREFIX,
        "source_storage_path",
        "nex-cx-real-document-extraction-smoke-",
        "/data/nex-platform",
    ]:
        with pytest.raises(ValueError, match="not redacted"):
            smoke.assert_evidence_redacted({"leak": forbidden})


def test_real_document_extraction_postgres_smoke_main_writes_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    evidence = {
        "smoke_schema_version": smoke.SCHEMA_VERSION,
        "status": "SKIPPED",
        "skip_reason": f"{smoke.SMOKE_ENV} is not enabled.",
    }
    output_path = tmp_path / "nested" / "evidence.json"

    monkeypatch.setattr(
        smoke,
        "run_cx_real_document_extraction_postgres_smoke",
        lambda: evidence,
    )

    assert smoke.main(["--summary", "--output", str(output_path)]) == 0
    assert output_path.exists()
    assert json.loads(output_path.read_text(encoding="utf-8")) == evidence
    assert "cx_real_document_extraction_postgres_smoke=skipped" in capsys.readouterr().out


def test_real_document_extraction_postgres_smoke_main_returns_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    evidence = smoke._failure("execution_failed", "RuntimeError", profile="test")

    monkeypatch.setattr(
        smoke,
        "run_cx_real_document_extraction_postgres_smoke",
        lambda: evidence,
    )

    assert smoke.main([]) == 1
    assert '"failure_code": "execution_failed"' in capsys.readouterr().out


def test_real_document_extraction_postgres_smoke_quality_gate_docs_wired() -> None:
    root = Path(__file__).parents[1]
    quality_gate = (root / "scripts" / "quality" / "run_quality_gate.sh").read_text(
        encoding="utf-8"
    )
    docs_index = (root / "docs" / "README.md").read_text(encoding="utf-8")
    slice_doc = (
        root
        / "docs"
        / "slices"
        / "0288_cx_real_document_extraction_postgresql_smoke.md"
    )

    assert "run_cx_real_document_extraction_postgres_smoke.py --summary" in quality_gate
    assert "0288_cx_real_document_extraction_postgresql_smoke.md" in docs_index
    assert slice_doc.exists()
