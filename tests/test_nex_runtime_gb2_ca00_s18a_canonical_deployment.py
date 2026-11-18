from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import nex_runtime.current_platform_installation as installation
import pytest
from nex_runtime.current_platform_installation import (
    CURRENT_COMPOSE_PATHS,
    CurrentPlatformInstallationError,
    admit_current_platform_installation,
)
from nex_runtime.runtime_package_admission import (
    RUNTIME_CHECK_MODE_ENV,
    RUNTIME_PACKAGE_CHECK_MODE,
)
from nex_wa import consumer_main
from run_product_runtime_deployment_audit import (
    CANONICAL_DEPLOYMENT_ENTRYPOINTS,
    LEGACY_DEPLOYMENT_WRAPPERS,
    audit_product_runtime_deployment,
)

ROOT = Path(__file__).resolve().parents[1]


def test_canonical_entrypoints_and_compatibility_wrappers_are_exact() -> None:
    for relative in CANONICAL_DEPLOYMENT_ENTRYPOINTS:
        assert (ROOT / relative).is_file()
    for relative, target in LEGACY_DEPLOYMENT_WRAPPERS.items():
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert f'_TARGET = "{target}"' in source
        assert "sys.modules[__name__] = importlib.import_module(_TARGET)" in source

    audit = audit_product_runtime_deployment(ROOT)
    assert audit["status"] == "PASS"
    assert audit["canonical_deployment_entrypoints"] == list(
        CANONICAL_DEPLOYMENT_ENTRYPOINTS
    )
    assert audit["legacy_deployment_wrappers"] == LEGACY_DEPLOYMENT_WRAPPERS


def test_current_installation_uses_canonical_nine_image_topology() -> None:
    result = admit_current_platform_installation(ROOT)

    assert result["status"] == "ADMITTED"
    assert result["artifact_count"] == 9
    assert result["process_count"] == 21
    assert "deployment/compose/canonical-platform.override.yaml" in (
        CURRENT_COMPOSE_PATHS
    )
    assert not any("p8-demo.override" in path for path in CURRENT_COMPOSE_PATHS)


def test_assignment_dispatch_profile_rejects_each_deployment_drift() -> None:
    services, _digests = installation._merged_compose_services(ROOT)
    canonical = services["nex-wc-assignment-dispatch-worker"]

    def changed(*path_and_value):
        *path, value = path_and_value
        result = deepcopy(canonical)
        target = result
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value
        return result

    missing_dependency = deepcopy(canonical)
    missing_dependency["depends_on"].pop("nex-oa")
    invalid_dependency = deepcopy(canonical)
    invalid_dependency["depends_on"]["nex-oa"] = "started"
    wrong_condition = deepcopy(canonical)
    wrong_condition["depends_on"]["nex-oa"]["condition"] = "service_started"
    residue = deepcopy(canonical)
    residue["environment"]["NEX_WC_M1_FIXTURE"] = "enabled"

    rejected = (
        None,
        changed("command", ["python", "-m", "nex_wc.other"]),
        changed("entrypoint", ["python"]),
        changed("restart", "no"),
        changed("read_only", False),
        changed("ports", ["9000:9000"]),
        changed("healthcheck", []),
        changed("healthcheck", "test", ["CMD", "false"]),
        changed("cap_drop", []),
        changed("security_opt", []),
        changed("environment", []),
        changed("environment", "NEX_DEPLOYMENT_BOUNDARY", "OTHER"),
        changed(
            "environment",
            "NEX_WC_ASSIGNMENT_DISPATCH_WORKER_ID",
            "wrong-worker",
        ),
        changed("depends_on", []),
        missing_dependency,
        invalid_dependency,
        wrong_condition,
        residue,
    )

    assert installation._product_wc_assignment_dispatch_profile(canonical) is True
    assert all(
        installation._product_wc_assignment_dispatch_profile(item) is False
        for item in rejected
    )


def test_current_installation_fails_closed_for_dispatcher_profile_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        installation, "_product_wc_assignment_dispatch_profile", lambda _: False
    )

    with pytest.raises(
        CurrentPlatformInstallationError,
        match="product_wc_assignment_dispatch_profile",
    ):
        admit_current_platform_installation(ROOT)


def test_canonical_environment_contract_rejects_residue_and_missing_names(
    tmp_path: Path,
) -> None:
    services, _digests = installation._merged_compose_services(ROOT)
    overlay = tmp_path / "deployment/compose/canonical-platform.override.yaml"
    overlay.parent.mkdir(parents=True)
    overlay.write_text("NEX_P8_DEMO_ACTIVE: true\n", encoding="utf-8")
    assert (
        installation._canonical_environment_contract(services, root=tmp_path)
        is False
    )

    overlay.write_text(
        "NEX_SERVICE_TOKEN_BOOTSTRAP_PROFILE: STARTUP_24H\n", encoding="utf-8"
    )
    assert (
        installation._canonical_environment_contract(services, root=tmp_path)
        is False
    )
    assert installation._product_ae_image_contract_not_overridden({}) is False


def test_compose_command_matching_covers_web_and_invalid_shapes() -> None:
    assert installation._compose_command_matches(
        ("npm", "start", "--silent"), None
    )
    assert installation._compose_command_matches(
        ("npm", "start", "--silent"), ["npm", "start"]
    )
    assert not installation._compose_command_matches(
        ("python", "-m", "worker"), None
    )
    assert not installation._compose_command_matches(
        ("python", "-m", "worker"), ["python", 1]
    )


def test_wa_consumer_package_check_does_not_open_persistence(capsys) -> None:
    def forbidden_persistence(**_kwargs):
        raise AssertionError("package check must not open persistence")

    assert (
        consumer_main.main(
            ["--check"],
            environ={RUNTIME_CHECK_MODE_ENV: RUNTIME_PACKAGE_CHECK_MODE},
            persistence_builder=forbidden_persistence,
        )
        == 0
    )
    output = capsys.readouterr().out
    assert '"process_id": "nex-wa-evidence-consumer"' in output
    assert '"package_ready": true' in output
    assert '"runtime_ready": false' in output
