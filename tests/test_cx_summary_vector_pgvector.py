from __future__ import annotations

import runpy
import sys

import pytest
from sqlalchemy import text

import run_cx_summary_vector_pgvector as smoke


def test_summary_vector_pgvector_smoke_passes() -> None:
    result = smoke.run_cx_summary_vector_pgvector()
    assert result == {
        "status": "PASS",
        "checks": {
            "table_short": True,
            "owner_columns": True,
            "lineage_trigger": True,
            "dimension_guard": True,
            "hnsw_2560": True,
            "backend_pgvector": True,
            "private_uri": True,
            "round_trip": True,
            "fresh_ready": True,
            "no_provider_needed": True,
        },
        "check_count": 10,
        "failed_checks": [],
        "table": "cx_summary_vectors",
        "postgres_required": False,
        "remote_required": False,
    }


def test_summary_vector_pgvector_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = smoke.run_cx_summary_vector_pgvector()
    assert smoke._format_summary(passing) == (
        "cx_summary_vector_pgvector=pass checks=10/10 table=cx_summary_vectors "
        "postgres_required=False remote_required=False"
    )

    monkeypatch.setattr(sys, "argv", ["summary-vector", "--summary"])
    with pytest.raises(SystemExit) as caught:
        runpy.run_module("run_cx_summary_vector_pgvector", run_name="__main__")
    assert caught.value.code == 0
    assert "cx_summary_vector_pgvector=pass" in capsys.readouterr().out


def test_summary_vector_pgvector_main_failure(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        smoke,
        "run_cx_summary_vector_pgvector",
        lambda: {
            "status": "FAIL",
            "check_count": 1,
            "failed_checks": ["round_trip"],
            "table": "cx_summary_vectors",
        },
    )
    monkeypatch.setattr(sys, "argv", ["summary-vector"])
    assert smoke.main() == 1
    assert '"status": "FAIL"' in capsys.readouterr().out


def test_summary_vector_smoke_session_delete_and_unknown_statement() -> None:
    session = smoke._Session({"embedding-id": {"summary_vector_id": "vector-id"}})
    result = session.execute(
        text("DELETE FROM cx_summary_vectors"),
        {"summary_embedding_id": "embedding-id"},
    )
    assert result.rowcount == 0
    with pytest.raises(AssertionError):
        session.execute(text("UPDATE unknown"), {"summary_embedding_id": "embedding-id"})
