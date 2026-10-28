from __future__ import annotations

import json
from pathlib import Path

import pytest
import run_golden_journey_transition_audit as audit

ROOT = Path(__file__).resolve().parents[1]


def _contract_literal() -> str:
    return repr(audit.EVIDENCE_CONTRACT)


def _runner_source(body: str = "") -> str:
    return (
        f"{audit.EVIDENCE_CONTRACT_NAME} = {_contract_literal()}\n\n"
        "def run():\n"
        f"    evidence = {{**{audit.EVIDENCE_CONTRACT_NAME}}}\n"
        f"{body or '    return evidence'}\n"
    )


def _write_runner(root: Path, source: str, *, name: str = "run_golden_journey.py") -> str:
    relative = f"scripts/smoke/{name}"
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return relative


def _write_registry(
    root: Path,
    paths: list[str],
    *,
    schema_version: str = audit.REGISTRY_SCHEMA_VERSION,
    rows: list[object] | None = None,
) -> Path:
    registry = root / audit.DEFAULT_REGISTRY
    registry.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": schema_version,
        "runners": rows
        if rows is not None
        else [
            {
                "path": path,
                "evidence_class": "GOLDEN_JOURNEY",
                "enforce_transition_boundary": True,
            }
            for path in sorted(paths)
        ],
    }
    registry.write_text(json.dumps(payload), encoding="utf-8")
    return audit.DEFAULT_REGISTRY


def _audit_source(tmp_path: Path, source: str) -> dict:
    path = _write_runner(tmp_path, source)
    registry = _write_registry(tmp_path, [path])
    return audit.audit_repository(tmp_path, registry)


def test_repository_registry_and_canonical_runner_pass() -> None:
    evidence = audit.audit_repository(ROOT)

    assert evidence["status"] == "PASS"
    assert evidence["registered_runner_count"] == 7
    assert evidence["discovered_runner_count"] == 7
    assert evidence["enforced_runner_count"] == 1
    assert evidence["evidence_contract"] == audit.EVIDENCE_CONTRACT
    assert evidence["findings"] == []
    assert evidence["secret_included"] is False


def test_allowed_assertion_cleanup_and_business_seed_sql_pass(tmp_path: Path) -> None:
    source = _runner_source(
        "    statements = (\n"
        "        \"SELECT state FROM ae_agent_execution\",\n"
        "        \"DELETE FROM ae_runtime_job WHERE tenant_id=:tenant\",\n"
        "        \"INSERT INTO eos_project (project_id) VALUES (:project_id)\",\n"
        "    )\n"
        "    return {**evidence, 'statements': statements}"
    )

    evidence = _audit_source(tmp_path, source)

    assert evidence["status"] == "PASS"
    assert audit.summary_line(evidence) == (
        "golden_journey_transition_audit=pass registered=1 enforced=1 findings=0"
    )


@pytest.mark.parametrize(
    ("source", "code", "detail"),
    (
        (
            "from nex_ae_api.multi_step_engine import SqlAlchemyMultiStepEngine\n"
            + _runner_source(),
            "FORBIDDEN_DOMAIN_IMPORT",
            "SqlAlchemyMultiStepEngine",
        ),
        (
            "from nex_wc.work_results import SqlAlchemyWorkResultRepository\n"
            + _runner_source(),
            "FORBIDDEN_DOMAIN_IMPORT",
            "SqlAlchemyWorkResultRepository",
        ),
        (
            _runner_source("    engine.schedule_next()\n    return evidence"),
            "FORBIDDEN_TRANSITION_CALL",
            "schedule_next",
        ),
        (
            _runner_source(
                "    statement = \"INSERT INTO ae_runtime_job (job_id) VALUES ('1')\"\n"
                "    return {**evidence, 'statement': statement}"
            ),
            "FORBIDDEN_TRANSITION_SQL",
            "ae_runtime_job",
        ),
        (
            _runner_source(
                "    statement = \"UPDATE public.wc_approval_decision SET decision='APPROVE'\"\n"
                "    return {**evidence, 'statement': statement}"
            ),
            "FORBIDDEN_TRANSITION_SQL",
            "wc_approval_decision",
        ),
    ),
)
def test_forbidden_transition_patterns_fail(
    tmp_path: Path, source: str, code: str, detail: str
) -> None:
    evidence = _audit_source(tmp_path, source)

    assert evidence["status"] == "FAIL"
    assert any(
        item["code"] == code and detail in item["detail"]
        for item in evidence["findings"]
    )


@pytest.mark.parametrize(
    ("source", "code"),
    (
        ("def run():\n    return {}\n", "EVIDENCE_CONTRACT_INVALID"),
        (
            f"{audit.EVIDENCE_CONTRACT_NAME} = {{'platform_integrated': False}}\n",
            "EVIDENCE_CONTRACT_INVALID",
        ),
        (
            (
                f"{audit.EVIDENCE_CONTRACT_NAME} = {_contract_literal()}\n"
                "def run():\n    return {'status': 'PASS'}\n"
            ),
            "EVIDENCE_CONTRACT_NOT_EXPOSED",
        ),
        ("def broken(:\n", "RUNNER_PARSE_FAILED"),
    ),
)
def test_missing_malformed_or_unexposed_evidence_contract_fails(
    tmp_path: Path, source: str, code: str
) -> None:
    evidence = _audit_source(tmp_path, source)

    assert evidence["status"] == "FAIL"
    assert code in {item["code"] for item in evidence["findings"]}


def test_unregistered_discovered_runner_fails_inventory(tmp_path: Path) -> None:
    registered = _write_runner(tmp_path, _runner_source())
    _write_runner(tmp_path, _runner_source(), name="run_chairman_journey_extra.py")
    registry = _write_registry(tmp_path, [registered])

    evidence = audit.audit_repository(tmp_path, registry)

    assert evidence["status"] == "FAIL"
    assert evidence["registered_runner_count"] == 0
    assert evidence["discovered_runner_count"] == 2
    assert evidence["findings"][0]["code"] == "REGISTRY_INVALID"
    assert "missing=" in evidence["findings"][0]["detail"]


@pytest.mark.parametrize(
    ("payload", "detail"),
    (
        ({"schema_version": audit.REGISTRY_SCHEMA_VERSION}, "fields"),
        (
            {"schema_version": "unsupported", "runners": [{}]},
            "unsupported",
        ),
        (
            {"schema_version": audit.REGISTRY_SCHEMA_VERSION, "runners": []},
            "must not be empty",
        ),
    ),
)
def test_invalid_registry_shape_fails_closed(
    tmp_path: Path, payload: dict, detail: str
) -> None:
    registry = tmp_path / audit.DEFAULT_REGISTRY
    registry.parent.mkdir(parents=True)
    registry.write_text(json.dumps(payload), encoding="utf-8")

    evidence = audit.audit_repository(tmp_path)

    assert evidence["status"] == "FAIL"
    assert detail in evidence["findings"][0]["detail"]


@pytest.mark.parametrize(
    ("row", "detail"),
    (
        ({"path": "scripts/smoke/run_golden_journey.py"}, "fields"),
        (
            {
                "path": "../run_golden_journey.py",
                "evidence_class": "GOLDEN_JOURNEY",
                "enforce_transition_boundary": True,
            },
            "unsafe",
        ),
        (
            {
                "path": "scripts/smoke/run_golden_journey.py",
                "evidence_class": "UNKNOWN",
                "enforce_transition_boundary": True,
            },
            "evidence class",
        ),
        (
            {
                "path": "scripts/smoke/run_golden_journey.py",
                "evidence_class": "GOLDEN_JOURNEY",
                "enforce_transition_boundary": "yes",
            },
            "flag",
        ),
        (
            {
                "path": "scripts/smoke/run_golden_journey.py",
                "evidence_class": "COMPONENT",
                "enforce_transition_boundary": True,
            },
            "only transition-enforced",
        ),
    ),
)
def test_invalid_registration_fails_closed(
    tmp_path: Path, row: dict, detail: str
) -> None:
    _write_runner(tmp_path, _runner_source())
    _write_registry(tmp_path, [], rows=[row])

    evidence = audit.audit_repository(tmp_path)

    assert evidence["status"] == "FAIL"
    assert detail in evidence["findings"][0]["detail"]


def test_duplicate_and_noncanonical_registry_paths_fail(tmp_path: Path) -> None:
    first = _write_runner(tmp_path, _runner_source(), name="run_golden_journey_b.py")
    second = _write_runner(tmp_path, _runner_source(), name="run_golden_journey_a.py")
    duplicate = [
        {
            "path": first,
            "evidence_class": "GOLDEN_JOURNEY",
            "enforce_transition_boundary": True,
        }
    ] * 2
    _write_registry(tmp_path, [], rows=duplicate)
    assert "unique" in audit.audit_repository(tmp_path)["findings"][0]["detail"]

    rows = [
        {
            "path": path,
            "evidence_class": "GOLDEN_JOURNEY",
            "enforce_transition_boundary": True,
        }
        for path in (first, second)
    ]
    _write_registry(tmp_path, [], rows=rows)
    assert "canonically ordered" in audit.audit_repository(tmp_path)["findings"][0][
        "detail"
    ]


def test_missing_or_malformed_registry_fails_closed(tmp_path: Path) -> None:
    missing = audit.audit_repository(tmp_path)
    assert "unavailable" in missing["findings"][0]["detail"]

    registry = tmp_path / audit.DEFAULT_REGISTRY
    registry.parent.mkdir(parents=True)
    registry.write_text("{", encoding="utf-8")
    malformed = audit.audit_repository(tmp_path)
    assert "unavailable" in malformed["findings"][0]["detail"]


def test_cli_writes_report_and_gate_hooks_are_registered(
    tmp_path: Path, capsys
) -> None:
    runner = _write_runner(tmp_path, _runner_source())
    registry = _write_registry(tmp_path, [runner])

    assert (
        audit.main(
            [
                "--root",
                str(tmp_path),
                "--registry",
                str(registry),
                "--report",
                "reports/quality/result.json",
                "--summary",
            ]
        )
        == 0
    )
    assert "golden_journey_transition_audit=pass" in capsys.readouterr().out
    report = json.loads(
        (tmp_path / "reports/quality/result.json").read_text(encoding="utf-8")
    )
    assert report["status"] == "PASS"

    tiered = (ROOT / "scripts/quality/run_tiered_quality_gate.py").read_text(
        encoding="utf-8"
    )
    full = (ROOT / "scripts/quality/run_quality_gate.sh").read_text(encoding="utf-8")
    command = "scripts/quality/run_golden_journey_transition_audit.py"
    assert tiered.count(command) == 1
    assert full.count(command) == 1


def test_cli_returns_failure_and_discovery_without_runner_roots(
    tmp_path: Path, capsys
) -> None:
    assert audit.discover_journey_runners(tmp_path) == ()
    assert audit.main(["--root", str(tmp_path), "--summary"]) == 1
    assert "golden_journey_transition_audit=fail" in capsys.readouterr().out
