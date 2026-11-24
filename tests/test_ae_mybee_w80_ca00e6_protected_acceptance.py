from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/smoke/run_mybee_w80_ca00e6_protected_acceptance.py"
SPEC = importlib.util.spec_from_file_location("w80_ca00e6_acceptance", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
runner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runner
SPEC.loader.exec_module(runner)


def _environment() -> dict[str, str]:
    return {
        "NEX_AE_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_ae_user:secret@127.0.0.1/nex_ae_test"
        ),
        "NEX_WC_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_wc_user:secret@127.0.0.1/nex_wc_test"
        ),
        "NEX_OA_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_oa_user:secret@127.0.0.1/nex_oa_test"
        ),
        "NEX_EOS_TEST_DATABASE_URL": (
            "postgresql+psycopg://nex_eos_user:secret@127.0.0.1/nex_eos_test"
        ),
        runner.LIVE_CONFIRMATION_ENV: "1",
    }


def _diagnostic_event(event_type: str, payload: dict) -> str:
    return json.dumps({"event_type": event_type, "payload": payload})


def _write_live_evidence(root: Path, relative: str) -> None:
    evidence = root / relative
    evidence.mkdir(parents=True)
    semantic = []
    for _ in range(4):
        semantic.append(_diagnostic_event("semantic.admission.requested", {}))
    for stage, count in runner.EXPECTED_SEMANTIC_STAGE_COUNTS.items():
        for _ in range(count):
            semantic.append(
                _diagnostic_event(
                    "semantic.candidate.admitted", {"semantic_stage": stage}
                )
            )
    (evidence / "nex-ae-api--semantic-candidate-admission--1.jsonl").write_text(
        "\n".join(semantic) + "\n", encoding="utf-8"
    )
    mo = [
        _diagnostic_event(
            "http.exchange",
            {"path": "/api/v1/generations", "duration_ms": 10_000 + index},
        )
        for index in range(runner.TARGET_GENERATION_REQUEST_COUNT)
    ]
    (evidence / "nex-mo--http-api--1.jsonl").write_text(
        "\n".join(mo) + "\n", encoding="utf-8"
    )


def _seed_source_admission(root: Path) -> None:
    required = (
        *runner.MATRIX_SELECTORS,
        str(runner.POSTGRES_SCRIPT.relative_to(runner.ROOT)),
        str(runner.LIVE_SCRIPT.relative_to(runner.ROOT)),
    )
    for relative in required:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("admitted\n", encoding="utf-8")


def test_source_admission_and_matrix_are_generalized(tmp_path: Path) -> None:
    observed: list[list[str]] = []

    def command_runner(command, **_values):
        observed.append(command)
        return subprocess.CompletedProcess(command, 0)

    result = runner.run_acceptance(
        {},
        report_path=tmp_path / "report.json",
        command_runner=command_runner,
    )

    assert result["status"] == "PARTIAL_PASS"
    assert result["source_admission"]["scenario_specific_product_runtime_added"] is False
    assert result["source_admission"]["installed_live_runner_reused"] is True
    assert result["acceptance_matrix"]["target_agent_types"] == ["PA", "CA", "EA"]
    assert observed[0][-len(runner.MATRIX_SELECTORS) :] == list(
        runner.MATRIX_SELECTORS
    )


def test_protected_acceptance_composes_postgres_and_live_without_secrets(
    tmp_path: Path,
) -> None:
    _seed_source_admission(tmp_path)
    relative = "evidence/session-a"
    _write_live_evidence(tmp_path, relative)
    postgres_report = tmp_path / "postgres.json"
    live_report = tmp_path / "live.json"

    def command_runner(command, **_values):
        if str(runner.POSTGRES_SCRIPT) in command:
            postgres_report.write_text(
                json.dumps(
                    {
                        "status": "PASS",
                        "actual_postgresql": True,
                        "protected_test_selector_count": 12,
                        "zero_residue": True,
                    }
                ),
                encoding="utf-8",
            )
        if str(runner.LIVE_SCRIPT) in command:
            live_report.write_text(
                json.dumps(
                    {
                        "status": "PASS",
                        "actual_postgres": True,
                        "actual_remote_generation": True,
                        "actual_playwright": True,
                        "zero_residue": True,
                        "release_set_digest": "sha256:" + "1" * 64,
                        "finalization_evidence": {
                            "relative_path": relative,
                            "session_id": "session-a",
                        },
                    }
                ),
                encoding="utf-8",
            )
        return subprocess.CompletedProcess(command, 0)

    result = runner.run_acceptance(
        _environment(),
        execute_postgres=True,
        execute_live=True,
        report_path=tmp_path / "report.json",
        postgres_report_path=postgres_report,
        live_report_path=live_report,
        command_runner=command_runner,
        root=tmp_path,
    )

    assert result["status"] == "PASS"
    assert result["diagnostics"]["generation_request_count"] == 8
    assert result["diagnostics"]["provider_request_reduction"] == 4
    assert result["diagnostics"]["semantic_stage_counts"] == {
        "CONTEXT": 2,
        "INTENT": 2,
        "PLAN": 4,
    }
    serialized = (tmp_path / "report.json").read_text(encoding="utf-8")
    assert ":secret@" not in serialized
    assert "request_body" not in serialized


def test_live_execution_requires_postgres_and_explicit_confirmation(
    tmp_path: Path,
) -> None:
    with pytest.raises(runner.W80Ca00e6AcceptanceError, match="PostgreSQL"):
        runner.run_acceptance(
            {},
            execute_live=True,
            report_path=tmp_path / "missing-postgres.json",
        )

    with pytest.raises(runner.W80Ca00e6AcceptanceError, match="confirmation"):
        runner.run_acceptance(
            _environment() | {runner.LIVE_CONFIRMATION_ENV: "0"},
            execute_postgres=True,
            execute_live=True,
            report_path=tmp_path / "missing-confirmation.json",
        )


def test_live_diagnostics_fail_closed_on_call_or_stage_drift(tmp_path: Path) -> None:
    relative = "evidence/session-b"
    _write_live_evidence(tmp_path, relative)
    report = {
        "status": "PASS",
        "actual_postgres": True,
        "actual_remote_generation": True,
        "actual_playwright": True,
        "zero_residue": True,
        "finalization_evidence": {"relative_path": relative},
    }
    diagnostics = runner.analyze_live_diagnostics(tmp_path, report)
    runner._require_live_acceptance(report, diagnostics)

    with pytest.raises(runner.W80Ca00e6AcceptanceError, match="call count"):
        runner._require_live_acceptance(
            report, diagnostics | {"generation_request_count": 12}
        )
    with pytest.raises(runner.W80Ca00e6AcceptanceError, match="stage counts"):
        runner._require_live_acceptance(
            report, diagnostics | {"semantic_stage_counts": {"PLAN": 8}}
        )
    with pytest.raises(runner.W80Ca00e6AcceptanceError, match="unrelated"):
        runner._require_live_acceptance(
            report, diagnostics | {"embedding_request_count": 1}
        )


def test_database_and_diagnostic_boundaries_reject_invalid_inputs(
    tmp_path: Path,
) -> None:
    wrong = _environment()
    wrong["NEX_EOS_TEST_DATABASE_URL"] = wrong[
        "NEX_EOS_TEST_DATABASE_URL"
    ].replace("nex_eos_user", "postgres")
    with pytest.raises(runner.W80Ca00e6AcceptanceError, match="nex_eos_user"):
        runner._database_identities(wrong)

    outside = {
        "finalization_evidence": {"relative_path": "../outside-evidence"}
    }
    with pytest.raises(runner.W80Ca00e6AcceptanceError, match="escaped"):
        runner.analyze_live_diagnostics(tmp_path, outside)

    malformed = tmp_path / "evidence/malformed"
    malformed.mkdir(parents=True)
    (malformed / "nex-ae-api--semantic-candidate-admission--1.jsonl").write_text(
        "{not-json}\n", encoding="utf-8"
    )
    (malformed / "nex-mo--http-api--1.jsonl").write_text("{}\n", encoding="utf-8")
    with pytest.raises(runner.W80Ca00e6AcceptanceError, match="malformed"):
        runner.analyze_live_diagnostics(
            tmp_path,
            {"finalization_evidence": {"relative_path": "evidence/malformed"}},
        )
