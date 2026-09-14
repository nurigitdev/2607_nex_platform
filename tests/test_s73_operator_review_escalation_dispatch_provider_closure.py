from __future__ import annotations

from pathlib import Path

import pytest

import run_s73_operator_review_escalation_dispatch_provider_closure as closure


def test_s73_operator_review_escalation_dispatch_provider_closure_passes_repo() -> None:
    evidence = closure.run_s73_operator_review_escalation_dispatch_provider_closure()

    assert evidence["status"] == "PASS"
    assert evidence["slice_range"] == "0721-0730"
    assert evidence["boundary"] == (
        "ag_owned_operator_review_escalation_dispatch_provider_readiness"
    )
    assert evidence["source_table"] == "ag_op_esc_dispatches"
    assert evidence["new_tables"] == []
    assert evidence["provider_modes"] == [
        "mock_first_only",
        "mock_http",
        "guarded_live_http",
    ]
    assert evidence["live_network_delivery"] == (
        "deferred_until_protected_transport"
    )
    assert evidence["privacy_regression"] == "provider_surfaces_redacted"
    assert evidence["postgres_smoke"] == "test_db_protected_provider_router"
    assert evidence["summary"]["missing_file_count"] == 0
    assert evidence["summary"]["missing_token_count"] == 0
    assert "worker_provider_router" in evidence["provider_surfaces"]


def test_s73_operator_review_escalation_dispatch_provider_closure_summary() -> None:
    evidence = closure.run_s73_operator_review_escalation_dispatch_provider_closure()
    summary = closure.summary_line(evidence)

    assert summary.startswith(
        "s73_operator_review_escalation_dispatch_provider_closure=pass"
    )
    assert "slice_range=0721-0730" in summary
    assert "table=ag_op_esc_dispatches" in summary
    assert "mock_http" in summary
    assert "privacy=provider_surfaces_redacted" in summary
    assert "smoke=test_db_protected_provider_router" in summary


def test_s73_operator_review_escalation_dispatch_provider_closure_reports_missing_file(
    tmp_path: Path,
) -> None:
    root = _minimal_root(tmp_path)

    evidence = closure.run_s73_operator_review_escalation_dispatch_provider_closure(
        root
    )

    assert evidence["status"] == "FAIL"
    assert evidence["failure_code"] == "s73_closure_failed"
    assert evidence["summary"]["missing_file_count"] == len(closure.REQUIRED_FILES)
    assert "missing_files=" in closure.summary_line(evidence)


def test_s73_operator_review_escalation_dispatch_provider_closure_reports_token_failure(
    tmp_path: Path,
) -> None:
    root = _minimal_root(tmp_path)
    for relative_path in closure.REQUIRED_FILES:
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("placeholder", encoding="utf-8")

    evidence = closure.run_s73_operator_review_escalation_dispatch_provider_closure(
        root
    )

    assert evidence["status"] == "FAIL"
    assert evidence["summary"]["missing_file_count"] == 0
    assert evidence["summary"]["missing_token_count"] == len(closure.TOKEN_CHECKS)


def test_s73_operator_review_escalation_dispatch_provider_closure_main_summary(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert closure.main(["--summary"]) == 0

    captured = capsys.readouterr()
    assert (
        "s73_operator_review_escalation_dispatch_provider_closure=pass"
        in captured.out
    )


def test_s73_operator_review_escalation_dispatch_provider_closure_main_json(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert closure.main([]) == 0

    captured = capsys.readouterr()
    assert (
        '"closure_schema_version": '
        '"s73_operator_review_escalation_dispatch_provider_closure.v1"'
    ) in captured.out


def _minimal_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    return root
