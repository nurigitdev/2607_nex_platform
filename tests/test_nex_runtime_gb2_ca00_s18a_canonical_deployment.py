from __future__ import annotations

from pathlib import Path

from nex_runtime.current_platform_installation import (
    CURRENT_COMPOSE_PATHS,
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
    assert result["process_count"] == 20
    assert "deployment/compose/canonical-platform.override.yaml" in (
        CURRENT_COMPOSE_PATHS
    )
    assert not any("p8-demo.override" in path for path in CURRENT_COMPOSE_PATHS)


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
