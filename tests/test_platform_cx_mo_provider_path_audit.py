from __future__ import annotations

from pathlib import Path

import run_platform_cx_mo_provider_path_audit as audit


def test_repository_cx_mo_provider_path_passes_with_safe_timeout_policy() -> None:
    result = audit.run_platform_cx_mo_provider_path_audit()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["issues"] == []
    assert len(result["clients"]) == 3
    assert result["direct_provider_references"] == []
    assert result["findings"]["cx_client_timeout_seconds"] == {
        "embedding": 60.0,
        "reranking": 60.0,
        "generation": 130.0,
    }
    assert result["findings"]["mo_upstream_timeout_seconds"] == {
        "embedding": 15.0,
        "reranking": 15.0,
        "generation": 60.0,
    }
    assert result["findings"]["mo_upstream_max_attempts"] == {
        "embedding": 3.0,
        "reranking": 3.0,
        "generation": 2.0,
    }
    assert result["findings"]["minimum_cx_client_timeout_seconds"] == {
        "embedding": 60.0,
        "reranking": 60.0,
        "generation": 130.0,
    }
    assert result["findings"]["timeout_budget_safe"] is True
    assert result["findings"]["mock_named_live_capability_alias_count"] == 2
    assert result["decision"]["s131_timeout_gap_was_recorded"] is True
    assert result["decision"]["current_timeout_budget_is_accepted_live_state"] is True
    assert result["decision"]["next_slice"] == "1308"


def test_audit_fails_closed_for_empty_repository(tmp_path: Path) -> None:
    result = audit.run_platform_cx_mo_provider_path_audit(tmp_path)

    assert result["status"] == "FAIL"
    assert len(result["issues"]) == 7
    assert result["checks"]["provider_hosts_are_not_visible_to_cx"] is True


def test_direct_provider_scanner_detects_cx_endpoint_ownership(
    tmp_path: Path,
) -> None:
    package = tmp_path / "services/nex-cx/nex_cx"
    package.mkdir(parents=True)
    (package / "bad.py").write_text(
        'A = "NEX_MO_REMOTE_RERANKER_URL"\nB = "NEX_MO_VLLM_BASE_URL"\n',
        encoding="utf-8",
    )

    assert audit._direct_provider_references(package, root=tmp_path) == [
        {
            "environment": "NEX_MO_REMOTE_RERANKER_URL",
            "path": "services/nex-cx/nex_cx/bad.py",
        },
        {
            "environment": "NEX_MO_VLLM_BASE_URL",
            "path": "services/nex-cx/nex_cx/bad.py",
        },
    ]
    assert audit._direct_provider_references(tmp_path / "missing", root=tmp_path) == []


def test_timeout_and_env_number_parsers_cover_missing_and_present() -> None:
    assert audit._client_timeout_seconds("timeout_seconds: float = 12.5") == 12.5
    assert audit._client_timeout_seconds("pass") is None
    assert audit._env_number("VALUE=17\n", "VALUE") == 17.0
    assert audit._env_number("VALUE=\n", "VALUE") is None
    assert audit._minimum_timeout(15, 3, 5, 5) == 60
    assert audit._minimum_timeout(None, 3, 5, 5) is None


def test_read_text_and_summary_branches(tmp_path: Path) -> None:
    path = tmp_path / "source.py"
    path.write_text("source", encoding="utf-8")
    assert audit._read_text(path) == "source"
    assert audit._read_text(tmp_path / "missing.py") == ""

    passing = {
        "status": "PASS",
        "findings": {
            "cx_mo_client_count": 3,
            "mo_capability_route_count": 3,
            "direct_provider_reference_count": 0,
            "timeout_budget_safe": True,
        },
        "decision": {"next_slice": "1308"},
    }
    assert audit.summary_line(passing) == (
        "platform_cx_mo_provider_path=pass clients=3 routes=3 direct=0 "
        "timeout_safe=True next=1308"
    )
    assert audit.summary_line({"status": "FAIL", "issues": [1]}) == (
        "platform_cx_mo_provider_path=fail issues=1"
    )


def test_main_prints_summary_json_and_failure(monkeypatch, capsys) -> None:
    passing = {
        "status": "PASS",
        "findings": {},
        "decision": {"next_slice": "1308"},
    }
    monkeypatch.setattr(audit, "run_platform_cx_mo_provider_path_audit", lambda: passing)
    assert audit.main(["--summary"]) == 0
    assert "provider_path=pass" in capsys.readouterr().out
    assert audit.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        audit,
        "run_platform_cx_mo_provider_path_audit",
        lambda: {"status": "FAIL", "issues": []},
    )
    assert audit.main([]) == 1
