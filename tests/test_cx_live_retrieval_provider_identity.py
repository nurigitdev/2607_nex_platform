from __future__ import annotations

from pathlib import Path

import run_cx_live_retrieval_provider_identity as identity


def test_repository_provider_identity_evidence_passes() -> None:
    result = identity.run_cx_live_retrieval_provider_identity()

    assert result["status"] == "PASS", result
    assert all(result["checks"].values())
    assert result["provider_profile"] == {
        "embedding_alias": "embedding-default",
        "embedding_model": "Qwen3-Embedding-4B",
        "reranker_alias": "reranker-default",
        "reranker_model": "Qwen3-Reranker-4B",
        "endpoint_persisted": False,
        "credential_persisted": False,
    }


def test_provider_identity_fails_closed_without_sources(tmp_path: Path) -> None:
    result = identity.run_cx_live_retrieval_provider_identity(tmp_path)
    assert result["status"] == "FAIL"
    assert result["issues"]


def test_summary_main_and_read_branches(tmp_path: Path, monkeypatch, capsys) -> None:
    source = tmp_path / "source.py"
    source.write_text("value", encoding="utf-8")
    assert identity._read_text(source) == "value"
    assert identity._read_text(tmp_path / "missing.py") == ""
    passing = {
        "status": "PASS",
        "provider_profile": {
            "embedding_model": "Qwen3-Embedding-4B",
            "reranker_model": "Qwen3-Reranker-4B",
        },
        "next_slice": "1356",
    }
    assert identity.summary_line(passing) == (
        "cx_live_retrieval_provider_identity=pass "
        "embedding=Qwen3-Embedding-4B reranker=Qwen3-Reranker-4B next=1356"
    )
    assert identity.summary_line({"status": "FAIL", "issues": [1]}) == (
        "cx_live_retrieval_provider_identity=fail issues=1"
    )
    monkeypatch.setattr(identity, "run_cx_live_retrieval_provider_identity", lambda: passing)
    assert identity.main(["--summary"]) == 0
    assert "next=1356" in capsys.readouterr().out
    assert identity.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        identity,
        "run_cx_live_retrieval_provider_identity",
        lambda: {"status": "FAIL", "issues": []},
    )
    assert identity.main([]) == 1
