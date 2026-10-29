from __future__ import annotations

import json
from pathlib import Path

import run_demo_product_dependency_audit as audit

ROOT = Path(__file__).resolve().parents[1]


def test_current_repository_has_no_product_owned_demo_dependency() -> None:
    evidence = audit.audit_repository(ROOT)

    assert evidence["status"] == "PASS"
    assert evidence["canonical_product_paths_clean"] is True
    assert evidence["current_platform_components_authoritative"] is True
    assert evidence["explicit_demo_wrapper_count"] == 5
    assert evidence["canonical_product_file_count"] > 0
    assert all(evidence["historical_p8_demo_regressions"].values())
    assert set(evidence["compatibility_edges"].values()) == {"PASS"}
    assert evidence["findings"] == []
    assert evidence["content_included"] is False
    assert evidence["secret_included"] is False


def test_forbidden_product_imports_fail_closed(tmp_path: Path) -> None:
    _write_valid_repository(tmp_path)
    product = tmp_path / "services/nex-ae-api/nex_ae_api/product.py"
    product.write_text(
        "import nex_runtime.demo_fixture\n"
        "from nex_ae_api import p8_demo_runtime_composition\n",
        encoding="utf-8",
    )

    evidence = audit.audit_repository(tmp_path)

    assert evidence["status"] == "FAIL"
    findings = [
        item
        for item in evidence["findings"]
        if item["code"] == "FORBIDDEN_DEMO_DEPENDENCY"
    ]
    assert {item["detail"].rsplit(": ", 1)[-1] for item in findings} == {
        "demo_fixture",
        "p8_demo_runtime_composition",
    }


def test_explicit_demo_wrapper_may_retain_historical_import(tmp_path: Path) -> None:
    _write_valid_repository(tmp_path)
    wrapper = tmp_path / next(iter(sorted(audit.EXPLICIT_DEMO_WRAPPERS)))
    wrapper.write_text(
        "from nex_runtime.demo_processes import manifest\n", encoding="utf-8"
    )

    evidence = audit.audit_repository(tmp_path)

    assert evidence["status"] == "PASS"
    assert evidence["canonical_product_paths_clean"] is True


def test_missing_wrapper_and_compatibility_edge_fail_closed(tmp_path: Path) -> None:
    _write_valid_repository(tmp_path)
    (tmp_path / min(audit.EXPLICIT_DEMO_WRAPPERS)).unlink()
    edge = audit.COMPATIBILITY_EDGES[0]
    (tmp_path / edge.path).unlink()

    evidence = audit.audit_repository(tmp_path)

    assert evidence["status"] == "FAIL"
    assert {item["code"] for item in evidence["findings"]} >= {
        "DEMO_WRAPPER_MISSING",
        "COMPATIBILITY_SOURCE_MISSING",
    }
    assert evidence["compatibility_edges"][edge.edge_id] == "FAIL"


def test_missing_canonical_import_and_parse_failure_are_reported(
    tmp_path: Path,
) -> None:
    _write_valid_repository(tmp_path)
    edge = audit.COMPATIBILITY_EDGES[-1]
    (tmp_path / edge.path).write_text("import unrelated\n", encoding="utf-8")
    broken = tmp_path / "services/nex-ae-api/nex_ae_api/broken.py"
    broken.write_text("def broken(:\n", encoding="utf-8")

    evidence = audit.audit_repository(tmp_path)

    assert evidence["status"] == "FAIL"
    assert {item["code"] for item in evidence["findings"]} >= {
        "CANONICAL_COMPATIBILITY_EDGE_MISSING",
        "SOURCE_PARSE_FAILED",
    }
    assert evidence["compatibility_edges"][edge.edge_id] == "FAIL"


def test_missing_product_inventory_and_unparseable_edge_fail_closed(
    tmp_path: Path,
) -> None:
    evidence = audit.audit_repository(tmp_path)
    assert evidence["status"] == "FAIL"
    assert evidence["canonical_product_file_count"] == 0
    assert any(
        item["code"] == "PRODUCT_SOURCE_INVENTORY_MISSING"
        for item in evidence["findings"]
    )

    _write_valid_repository(tmp_path)
    edge = audit.COMPATIBILITY_EDGES[0]
    (tmp_path / edge.path).write_text("from invalid import\n", encoding="utf-8")
    malformed = audit.audit_repository(tmp_path)
    assert malformed["status"] == "FAIL"
    assert malformed["compatibility_edges"][edge.edge_id] == "FAIL"
    assert any(item["code"] == "SOURCE_PARSE_FAILED" for item in malformed["findings"])


def test_cli_writes_report_and_gate_hooks_are_registered(
    tmp_path: Path, capsys
) -> None:
    _write_valid_repository(tmp_path)

    assert (
        audit.main(
            [
                "--root",
                str(tmp_path),
                "--report",
                "reports/quality/result.json",
                "--summary",
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    assert "demo_product_dependency_audit=pass" in output
    report = json.loads(
        (tmp_path / "reports/quality/result.json").read_text(encoding="utf-8")
    )
    assert report["status"] == "PASS"

    command = "scripts/quality/run_demo_product_dependency_audit.py"
    tiered = (ROOT / "scripts/quality/run_tiered_quality_gate.py").read_text(
        encoding="utf-8"
    )
    full = (ROOT / "scripts/quality/run_quality_gate.sh").read_text(encoding="utf-8")
    assert tiered.count(command) == 1
    assert full.count(command) == 1


def test_cli_returns_failure_and_supports_absolute_report(
    tmp_path: Path, capsys
) -> None:
    report = tmp_path / "absolute.json"
    assert (
        audit.main(
            [
                "--root",
                str(tmp_path),
                "--report",
                str(report),
                "--summary",
            ]
        )
        == 1
    )
    assert "demo_product_dependency_audit=fail" in capsys.readouterr().out
    assert json.loads(report.read_text(encoding="utf-8"))["status"] == "FAIL"


def _write_valid_repository(root: Path) -> None:
    product = root / "services/nex-ae-api/nex_ae_api/product.py"
    product.parent.mkdir(parents=True, exist_ok=True)
    product.write_text("import json\n", encoding="utf-8")
    cached = product.parent / "__pycache__/ignored.py"
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_text("this is not parsed\n", encoding="utf-8")

    imports_by_path: dict[str, set[str]] = {
        path: set() for path in audit.EXPLICIT_DEMO_WRAPPERS
    }
    for edge in audit.COMPATIBILITY_EDGES:
        imports_by_path.setdefault(edge.path, set()).update(edge.required_imports)
    for relative, imports in imports_by_path.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "".join(_import_statement(item) for item in sorted(imports)) or "pass\n",
            encoding="utf-8",
        )


def _import_statement(qualified: str) -> str:
    module, separator, name = qualified.rpartition(".")
    if not separator or name.startswith("run_p8_demo_"):
        return f"import {qualified}\n"
    return f"from {module} import {name}\n"
