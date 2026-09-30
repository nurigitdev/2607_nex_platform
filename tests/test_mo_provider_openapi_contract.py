from __future__ import annotations

from pathlib import Path

import run_mo_provider_openapi_contract as runner


def test_repository_provider_openapi_contract_is_hardened() -> None:
    result = runner.run_mo_provider_openapi_contract()

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert result["summary"] == {
        "provider_path_count": 7,
        "canonical_component_count": 9,
        "closed_provider_drift_count": 17,
        "remaining_drift_count": 1,
    }
    assert all(result["components"].values())
    assert result["next_slice"] == "1136"


def test_provider_openapi_contract_fails_closed_for_missing_document(
    tmp_path: Path,
) -> None:
    result = runner.run_mo_provider_openapi_contract(
        tmp_path,
        document={},
        audit={"summary": {}},
    )

    assert result["status"] == "FAIL"
    assert result["checks"]["openapi_document_present"] is False
    assert result["checks"]["provider_security_complete"] is False
    assert result["checks"]["canonical_components_complete"] is False
    assert result["next_slice"] == "blocked"


def test_provider_openapi_helpers_cover_invalid_inputs(tmp_path: Path) -> None:
    invalid = tmp_path / "contracts" / "openapi"
    invalid.mkdir(parents=True)
    (invalid / "nex-mo.openapi.yaml").write_text("paths: [", encoding="utf-8")

    assert runner._read_openapi(tmp_path) == {}
    assert runner._mapping(None) == {}
    assert runner._count({"value": 2}, "value") == 2
    assert runner._count({"value": -1}, "value") == 0
    assert runner._count({"value": "2"}, "value") == 0


def test_provider_openapi_summary_and_main_paths(monkeypatch, capsys) -> None:
    passing = runner.run_mo_provider_openapi_contract()
    assert runner.summary_line(passing) == (
        "mo_provider_openapi_contract=pass paths=7 components=9 "
        "closed=17 remaining=1 next=1136"
    )

    monkeypatch.setattr(runner, "run_mo_provider_openapi_contract", lambda: passing)
    assert runner.main(["--summary"]) == 0
    assert "closed=17" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        runner,
        "run_mo_provider_openapi_contract",
        lambda: {"status": "FAIL", "summary": {}},
    )
    assert runner.main(["--summary"]) == 1
    assert "next=blocked" in capsys.readouterr().out
