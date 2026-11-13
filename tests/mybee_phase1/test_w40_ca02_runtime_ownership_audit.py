from __future__ import annotations

import json
import ast
from pathlib import Path

import pytest

import run_mybee_w40_ca02_runtime_ownership_audit as audit

ROOT = Path(__file__).resolve().parents[2]


def test_current_repository_freezes_runtime_ownership_and_known_gaps() -> None:
    result = audit.audit_runtime_ownership(ROOT)

    assert result["status"] == "PASS", result
    assert result["ownership_decision"] == {
        "domain_library_owner": "mybee",
        "execution_process_owner": "nex-ae-api",
        "business_state_owner": "nex-eos",
        "authorization_owner": "nex-oa",
        "approval_owner": "nex-wc",
        "entitlement_delivery_owner": "nex-eos-outbox-publisher",
        "new_mybee_service_required": False,
    }
    assert all(result["checks"].values())
    assert result["current_composition"]["forbidden_mybee_runtime_entrypoints"] == []
    assert result["current_composition"]["mybee_service_imports"] == []
    assert set(result["integration_gaps"]) == {
        "MYBEE_PRODUCT_CAPABILITY_NOT_ADMITTED",
        "MYBEE_PRODUCT_ACTIVATOR_NOT_ADMITTED",
    }
    assert result["integration_readiness"] == "NOT_READY"
    assert result["next_slice"] == "W40-CA02-S03"
    assert result["remote_provider_required"] is False
    assert result["database_migration_required"] is False
    assert result["issues"] == []


def test_second_runtime_and_non_ae_import_fail_closed(tmp_path: Path) -> None:
    _write_minimal_repository(tmp_path)
    runtime = tmp_path / "domains/mybee/mybee_ax/runtime_process.py"
    runtime.write_text("pass\n", encoding="utf-8")
    eos_import = tmp_path / "services/nex-eos/nex_eos/forbidden.py"
    eos_import.write_text("from mybee_ax import integrations\n", encoding="utf-8")

    result = audit.audit_runtime_ownership(tmp_path)

    assert result["status"] == "FAIL"
    assert result["checks"]["no_second_mybee_runtime"] is False
    assert result["checks"]["no_non_ae_service_import"] is False
    assert set(result["issues"]) >= {
        "MyBee defines a forbidden second product runtime",
        "a non-AE service imports the MyBee domain package",
    }


def test_ae_import_and_package_admission_close_only_their_gaps(tmp_path: Path) -> None:
    _write_minimal_repository(tmp_path, package_admitted=True)
    ae_import = tmp_path / "services/nex-ae-api/nex_ae_api/mybee_product.py"
    ae_import.parent.mkdir(parents=True, exist_ok=True)
    ae_import.write_text("from mybee_ax import integrations\n", encoding="utf-8")

    result = audit.audit_runtime_ownership(tmp_path)

    assert result["status"] == "PASS", result
    assert result["checks"]["no_non_ae_service_import"] is True
    assert result["current_composition"]["ae_package_admitted"] is True
    assert result["integration_gaps"] == [
        "MYBEE_PRODUCT_CAPABILITY_NOT_ADMITTED",
        "MYBEE_PRODUCT_ACTIVATOR_NOT_ADMITTED",
    ]


def test_complete_ae_admission_advances_to_consumer_integration(tmp_path: Path) -> None:
    _write_minimal_repository(tmp_path, package_admitted=True)
    (tmp_path / audit.AE_ACTIVATORS).write_text(
        "VoucherCandidate = 'MYBEE'\n", encoding="utf-8"
    )
    (tmp_path / audit.AE_CAPABILITIES).write_text(
        '{"registrations": [{"capability_id": "MYBEE.VOUCHER_CANDIDATE"}]}\n',
        encoding="utf-8",
    )

    result = audit.audit_runtime_ownership(tmp_path)

    assert result["status"] == "PASS"
    assert result["integration_readiness"] == "READY"
    assert result["integration_gaps"] == []
    assert result["next_slice"] == "W40-CA02-S03"


@pytest.mark.parametrize(
    ("relative", "replacement", "expected_issue"),
    (
        (
            audit.MYBEE_README,
            "ownership omitted\n",
            "MyBee ownership boundary is not documented",
        ),
        (
            audit.MYBEE_PROJECT,
            "[project]\nname = 'wrong'\n",
            "MyBee package identity is unavailable",
        ),
        (
            audit.CANONICAL_COMPOSE,
            "services: {}\n",
            "canonical accounting process topology is incomplete",
        ),
        (
            audit.EOS_OUTBOX_PROCESS,
            "pass\n",
            "installed EOS outbox does not own the OA route",
        ),
        (
            audit.EOS_DEPENDENCIES,
            "pass\n",
            "EOS product composition is incomplete",
        ),
        (
            audit.MYBEE_CONSUMER,
            "pass\n",
            "MyBee installed HTTP consumer contract is incomplete",
        ),
    ),
)
def test_required_product_boundary_drift_fails_closed(
    tmp_path: Path,
    relative: str,
    replacement: str,
    expected_issue: str,
) -> None:
    _write_minimal_repository(tmp_path)
    (tmp_path / relative).write_text(replacement, encoding="utf-8")

    result = audit.audit_runtime_ownership(tmp_path)

    assert result["status"] == "FAIL"
    assert expected_issue in result["issues"]


def test_missing_and_malformed_inventory_is_reported(tmp_path: Path) -> None:
    missing = audit.audit_runtime_ownership(tmp_path)
    assert missing["status"] == "FAIL"
    assert "service source inventory is unavailable" in missing["issues"]
    assert missing["current_composition"]["forbidden_mybee_runtime_entrypoints"] == []

    _write_minimal_repository(tmp_path)
    (tmp_path / audit.AE_CAPABILITIES).write_text("{", encoding="utf-8")
    (tmp_path / audit.CANONICAL_COMPOSE).write_text("[", encoding="utf-8")
    (tmp_path / audit.ARTIFACT_CATALOG).write_text("def broken(:\n", encoding="utf-8")
    broken = tmp_path / "services/nex-eos/nex_eos/broken.py"
    broken.write_text("def broken(:\n", encoding="utf-8")
    cached = tmp_path / "services/nex-eos/nex_eos/__pycache__/ignored.py"
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_text("def broken(:\n", encoding="utf-8")

    malformed = audit.audit_runtime_ownership(tmp_path)

    assert malformed["status"] == "FAIL"
    assert set(malformed["issues"]) >= {
        f"required JSON is malformed: {audit.AE_CAPABILITIES}",
        f"required YAML is malformed: {audit.CANONICAL_COMPOSE}",
        "deployment artifact catalog cannot be parsed",
        "service source cannot be parsed: services/nex-eos/nex_eos/broken.py",
    }


def test_helper_fail_closed_branches() -> None:
    issues: list[str] = []
    assert audit._artifact_source_roots("pass\n", "missing", issues) == ()
    assert issues == ["deployment artifact is unavailable: missing"]
    assert audit._compose_environment([], "service") == {}
    assert audit._compose_environment({"service": "wrong"}, "service") == {}
    assert audit._compose_environment({"service": {"environment": []}}, "service") == {}
    assert audit._imports_mybee(ast.parse("import json").body[0]) is False
    assert audit._imports_mybee(ast.parse("from mybee_ax.sub import value").body[0]) is True
    assert audit._imports_mybee(ast.parse("from . import value").body[0]) is False
    assert audit._capability_admitted({"name": "voucher_candidate"}) is True
    assert audit.summary_line({"status": "FAIL"}) == (
        "mybee_w40_ca02_runtime_ownership_audit=fail "
        "readiness=UNKNOWN gaps=0 next=blocked"
    )


def test_cli_writes_machine_readable_evidence(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    passing = audit.audit_runtime_ownership(ROOT)
    monkeypatch.setattr(audit, "audit_runtime_ownership", lambda root: passing)
    report = tmp_path / "result.json"

    assert audit.main(["--root", str(tmp_path), "--report", str(report), "--summary"]) == 0
    assert "runtime_ownership_audit=pass" in capsys.readouterr().out
    assert json.loads(report.read_text(encoding="utf-8"))["slice"] == "W40-CA02-S01"

    failing = dict(passing, status="FAIL", issues=["drift"])
    monkeypatch.setattr(audit, "audit_runtime_ownership", lambda root: failing)
    assert audit.main(["--root", str(tmp_path), "--report", str(report)]) == 1


def _write_minimal_repository(root: Path, *, package_admitted: bool = False) -> None:
    files = {
        "domains/mybee/README.md": (
            "does not own or duplicate Agent Runtime or NSL execution; "
            "accounting, GL, Project, allocation, or P&L state; "
            "a second MyBee runtime are forbidden\n"
        ),
        "domains/mybee/pyproject.toml": (
            '[project]\nname = "nex-mybee-ax"\n'
            '[tool.setuptools.packages.find]\ninclude = ["mybee_ax*"]\n'
        ),
        "services/_shared/nex_runtime/deployment_artifacts.py": (
            "DeploymentArtifactDefinition(\n"
            '    "nex-ae-runtime", "nex-ae-api", "python-service",\n'
            '    "ae-runtime", "python-production",\n'
            f'    ("services/nex-ae-api/nex_ae_api"{", \"domains/mybee\"" if package_admitted else ""},),\n'
            ")\n"
        ),
        "services/nex-ae-api/nex_ae_api/domain_intent_products.py": "pass\n",
        "deployment/oci/canonical-platform-ae-runtime.Containerfile": "FROM base\n",
        "scripts/deployment/build_canonical_platform_ae_runtime_image.py": "pass\n",
        "services/nex-eos/nex_eos/dependencies.py": (
            "SqlAlchemyEosVoucherCandidateRepository\n"
            "EosProjectAuthorizationGate\n"
            "HttpOaProjectAuthorizationDecisionSource\n"
        ),
        "services/nex-eos/nex_eos/outbox_publisher_process.py": (
            "RoutingEosOutboxTransport\n"
            "HttpOaProjectEntitlementTransport\n"
            "NEX_EOS_TO_OA_SERVICE_TOKEN\n"
        ),
        "domains/mybee/mybee_ax/integrations/nex_voucher_candidate_client.py": (
            "class NexVoucherCandidateClient: pass\n"
            "class HttpVoucherCandidateProviderTransport: pass\n"
            "Authorization = 'Bearer'\n"
        ),
    }
    for relative, value in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")
    (root / "domains/mybee/mybee_ax/__init__.py").write_text("", encoding="utf-8")
    registry = root / "deployment/environments/ae-product-capability-registry.v1.json"
    registry.parent.mkdir(parents=True, exist_ok=True)
    registry.write_text('{"registrations": []}\n', encoding="utf-8")
    compose = root / "deployment/compose/canonical-platform.override.yaml"
    compose.parent.mkdir(parents=True, exist_ok=True)
    compose.write_text(
        "services:\n"
        "  nex-ae-api: {}\n"
        "  nex-ae-agent-runtime-worker: {}\n"
        "  nex-oa: {}\n"
        "  nex-wc: {}\n"
        "  nex-eos:\n"
        "    environment:\n"
        "      NEX_OA_BASE_URL: https://oa.example\n"
        "      NEX_EOS_TO_OA_SERVICE_TOKEN_REF: secret://token\n"
        "  nex-eos-outbox-publisher:\n"
        "    environment:\n"
        "      NEX_OA_BASE_URL: https://oa.example\n"
        "      NEX_EOS_TO_OA_SERVICE_TOKEN_REF: secret://token\n",
        encoding="utf-8",
    )
