from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from nex_ae_api import agent_runtime_process
from nex_ae_api import mybee_product_admission as admission
from nex_runtime.canonical_platform_trust import CANONICAL_PLATFORM_TRUST_GRANTS
from nex_runtime.deployment_artifacts import build_default_deployment_artifact_catalog
from nex_runtime.deployment_oci import (
    build_default_oci_definitions,
    materialize_oci_build_context,
)
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[2]
CAPABILITY_REGISTRY = (
    ROOT / "deployment/environments/ae-product-capability-registry.v1.json"
)
AUTHORITY_PROFILE = ROOT / "deployment/environments/finance-golden-a-vo00.v1.json"


def _protected_environment() -> dict[str, str]:
    return {
        "NEX_AE_DATABASE_URL": "sqlite+pysqlite:///:memory:",
        "NEX_AE_PRODUCT_CAPABILITY_REGISTRY_PATH": str(CAPABILITY_REGISTRY),
        "NEX_AE_FINANCE_GOLDEN_A_AUTHORITY_PROFILE_PATH": str(AUTHORITY_PROFILE),
        "NEX_EOS_BASE_URL": "https://eos.example",
        "NEX_AE_TO_EOS_SERVICE_TOKEN": "signed-ae-to-eos-token",
        "NEX_SERVICE_TOKEN_ROLLOUT_PROFILE": "SIGNED_ONLY",
    }


def test_mybee_product_package_is_admitted_from_the_ae_runtime_source() -> None:
    result = admission.require_mybee_product_package()

    assert result["status"] == "PASS"
    assert result["domain_id"] == "mybee"
    assert result["package_version"] == "0.1.0"
    assert result["consumer_exports"] == [
        "HttpVoucherCandidateProviderTransport",
        "NexVoucherCandidateClient",
    ]
    assert set(result["platform_owners"]) == admission.EXPECTED_PLATFORM_OWNERS
    assert result["issues"] == []
    assert result["content_included"] is False
    assert result["secret_included"] is False


def test_ae_oci_context_is_the_only_owner_scoped_mybee_package(
    tmp_path: Path,
) -> None:
    catalog = build_default_deployment_artifact_catalog()
    definitions = build_default_oci_definitions(catalog)
    ae = next(item for item in definitions if item.artifact_id == "nex-ae-runtime")
    oa = next(item for item in definitions if item.artifact_id == "nex-oa-runtime")

    assert "domains/mybee/mybee_ax" in ae.context_paths
    assert "domains/mybee/mybee_ax" not in oa.context_paths
    manifest = materialize_oci_build_context(ROOT, tmp_path / "ae", ae)
    paths = {item.path for item in manifest.files}
    assert "domains/mybee/mybee_ax/metadata.py" in paths
    assert "domains/mybee/mybee_ax/integrations/nex_voucher_candidate_client.py" in paths
    assert not any("__pycache__" in path or path.endswith(".pyc") for path in paths)


def test_ae_containerfiles_require_the_admitted_mybee_package() -> None:
    base = (ROOT / "deployment/oci/python-service.Containerfile").read_text(
        encoding="utf-8"
    )
    product = (
        ROOT / "deployment/oci/canonical-platform-ae-runtime.Containerfile"
    ).read_text(encoding="utf-8")

    assert (
        "COPY --chown=65532:65532 domains/mybee/mybee_ax "
        "/app/domains/mybee/mybee_ax"
    ) in base
    assert "/app/domains/mybee" in base
    assert "find_spec('mybee_ax')" in base
    assert "require_mybee_product_package" in product
    assert "mybee_ax.PACKAGE_VERSION == '0.1.0'" in product


def test_canonical_signed_trust_and_process_wiring_are_reused() -> None:
    grants = {
        item.environment_name: (item.owner, item.audience, item.scopes)
        for item in CANONICAL_PLATFORM_TRUST_GRANTS
    }
    assert grants["NEX_AE_TO_EOS_SERVICE_TOKEN"] == (
        "nex-ae-api",
        "nex-eos",
        ("service:call",),
    )
    assert grants["NEX_EOS_TO_OA_SERVICE_TOKEN"] == (
        "nex-eos",
        "nex-oa",
        (
            "service:call",
            "authorization:read",
            "identity:employee:resolve",
            "project-entitlement:write",
        ),
    )

    compose = yaml.safe_load(
        (ROOT / "deployment/compose/canonical-platform.override.yaml").read_text(
            encoding="utf-8"
        )
    )
    worker = compose["services"]["nex-ae-agent-runtime-worker"]
    assert worker["command"] == [
        "python",
        "-m",
        "nex_ae_api.agent_runtime_process",
        "--profile",
        "staging_live",
    ]
    assert "NEX_AE_TO_EOS_SERVICE_TOKEN_REF" in worker["environment"]
    publisher = compose["services"]["nex-eos-outbox-publisher"]
    assert "NEX_EOS_TO_OA_SERVICE_TOKEN_REF" in publisher["environment"]


def test_protected_agent_runtime_requires_mybee_admission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    observed: list[bool] = []
    product_profile = agent_runtime_process.build_deterministic_component_executor_profile()
    monkeypatch.setattr(
        agent_runtime_process,
        "require_mybee_product_package",
        lambda: observed.append(True) or admission.inspect_mybee_product_package(),
    )

    installed = agent_runtime_process.build_installed_agent_runtime_process(
        "staging_live",
        environ=_protected_environment(),
        executor_profile=product_profile,
        engine_factory=lambda *_args, **_kwargs: engine,
        engine_checker=lambda _engine: True,
        session_factory_builder=lambda value: sessionmaker(bind=value),
    )
    try:
        result = installed.readiness()
    finally:
        installed.close()

    assert observed == [True]
    assert result["checks"]["mybee_product_package_admitted"] is True
    assert result["mybee_product_package"]["status"] == "PASS"


def test_product_admission_failures_are_redacted_and_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable(_name: str):
        raise ModuleNotFoundError("private path must not escape")

    monkeypatch.setattr(admission.importlib, "import_module", unavailable)
    result = admission.inspect_mybee_product_package()
    assert result["status"] == "FAIL"
    assert result["issues"] == ["MYBEE_PACKAGE_UNAVAILABLE:ModuleNotFoundError"]
    assert "private path" not in str(result)
    with pytest.raises(admission.MyBeeProductAdmissionError, match="UNAVAILABLE"):
        admission.require_mybee_product_package()


@pytest.mark.parametrize(
    ("package", "integrations", "expected"),
    (
        (
            SimpleNamespace(
                DOMAIN_ID="wrong",
                PACKAGE_VERSION="0.1.0",
                CANONICAL_PLATFORM_OWNERS=tuple(admission.EXPECTED_PLATFORM_OWNERS),
            ),
            SimpleNamespace(
                HttpVoucherCandidateProviderTransport=object(),
                NexVoucherCandidateClient=object(),
            ),
            "MYBEE_DOMAIN_ID_MISMATCH",
        ),
        (
            SimpleNamespace(
                DOMAIN_ID="mybee",
                PACKAGE_VERSION="0.0.0",
                CANONICAL_PLATFORM_OWNERS=tuple(admission.EXPECTED_PLATFORM_OWNERS),
            ),
            SimpleNamespace(
                HttpVoucherCandidateProviderTransport=object(),
                NexVoucherCandidateClient=object(),
            ),
            "MYBEE_PACKAGE_VERSION_MISMATCH",
        ),
        (
            SimpleNamespace(
                DOMAIN_ID="mybee",
                PACKAGE_VERSION="0.1.0",
                CANONICAL_PLATFORM_OWNERS=("nex-ae-api",),
            ),
            SimpleNamespace(
                HttpVoucherCandidateProviderTransport=object(),
                NexVoucherCandidateClient=object(),
            ),
            "MYBEE_PLATFORM_OWNER_SET_MISMATCH",
        ),
        (
            SimpleNamespace(
                DOMAIN_ID="mybee",
                PACKAGE_VERSION="0.1.0",
                CANONICAL_PLATFORM_OWNERS=tuple(admission.EXPECTED_PLATFORM_OWNERS),
            ),
            SimpleNamespace(NexVoucherCandidateClient=object()),
            "MYBEE_VOUCHER_CONSUMER_EXPORT_MISSING",
        ),
    ),
)
def test_product_admission_rejects_identity_and_export_drift(
    monkeypatch: pytest.MonkeyPatch,
    package: SimpleNamespace,
    integrations: SimpleNamespace,
    expected: str,
) -> None:
    monkeypatch.setattr(
        admission.importlib,
        "import_module",
        lambda name: package if name == "mybee_ax" else integrations,
    )

    result = admission.inspect_mybee_product_package()

    assert result["status"] == "FAIL"
    assert expected in result["issues"]
    assert admission.mybee_product_admission_ready(result) is False


def test_non_protected_profile_marks_product_package_not_required() -> None:
    result = admission.not_required_mybee_product_admission()

    assert result["status"] == "NOT_REQUIRED"
    assert admission.mybee_product_admission_ready(result) is True
    assert result["content_included"] is False
    assert result["secret_included"] is False
