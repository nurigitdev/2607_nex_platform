from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import build_canonical_platform_ae_runtime_image as build

ROOT = Path(__file__).resolve().parents[1]


def test_demo_ae_runtime_containerfile_admits_every_embedded_asset_path() -> None:
    source = (
        ROOT / "deployment/oci/canonical-platform-ae-runtime.Containerfile"
    ).read_text(encoding="utf-8")

    assert "NEX_AE_PRODUCT_RUNTIME_PROFILE=VERIFIED_PRODUCT_RELEASE" in source
    assert (
        "NEX_AE_NSL_PLATFORM_LOCK=/app/deployment/product/repository/"
        "deployment/locks/python-production.lock"
    ) in source
    assert "ae-mybee-m1-runtime-activation.v1.json" in source
    assert "mybee-m1-d04-d12.v1.nsp" in source
    assert (
        "install -d -o 65532 -g 65532 -m 0700 /var/lib/nex-platform/ae-runtime/nsl"
    ) in source
    assert source.index("install -d -o 65532") < source.index("USER 65532:65532")
    assert "COPY --chown=65532:65532 config" in source
    assert "NEX_AE_FINANCE_GOLDEN_A_AUTHORITY_PROFILE_PATH=" in source
    assert "NEX_AE_PRODUCT_CAPABILITY_REGISTRY_PATH=" in source
    assert "NEX_AE_PRODUCT_CAPABILITY_RETIREMENT_PATH=" in source
    assert "assert all(Path(os.environ[name]).exists() for name in names)" in source
    assert "nex_ae_api.agent_runtime_process" in source
    assert "nex_ae_api.demo_runtime" not in source
    assert "NEX_AE_DEMO_" not in source
    assert "COPY --chown=65532:65532 fixtures" not in source


def test_demo_ae_runtime_image_dry_run_requires_locked_bundle() -> None:
    result = build.build_canonical_platform_ae_runtime_image(
        base_image="nex-platform-demo/nex-ae-runtime:prior",
        output_image="nex-platform-demo/nex-ae-runtime:p8-demo-s10b",
        execute=False,
    )

    assert result["status"] == "READY"
    assert result["bundle"]["status"] == "PASS"
    assert result["bundle_role"] == "BOUNDED_ROLLBACK_UNTIL_CP_M1_GA_RET_02"
    assert result["active_runtime_profile"] == "VERIFIED_PRODUCT_RELEASE"
    assert result["verified_product_release"] == {
        "activation_state": "ACTIVE_WITH_BOUNDED_ROLLBACK",
        "activation_hash": "sha256:6a1aa2a44eaf25e52afa33ed09ad0ea69f351ea8a309e5614b6f6162c096f3af",
        "admission_hash": "sha256:3b561a8bd71f2702dd1020c096e0936efd49818200e3a8248dcb842395dd280d",
        "release_id": "nex-mybee-m1-d04-d12-checkpoint",
        "release_hash": "sha256:0034adc847aedc5d4fe99a446f7b60dfaef5db218ebbed96ba0f96bf32feecf4",
        "package_hash": "sha256:96888a02ee4924b6ac1f46bf7031627afc4d4a53d04bc77e13acd1940ea25348",
        "skill_catalog_hash": "sha256:1c15866db200efb8db4807869f48c49737fe4c18f1d3ef657bed7a456721801d",
        "runtime_selectable_capabilities": [
            "FINANCE.VOUCHER.APPROVE_AND_POST",
            "PROJECT.WORK_CODE_SET.GET",
        ],
        "bounded_rollback": {
            "profile": "GOLDEN_A_ROLLBACK",
            "receipt_ref": "deployment/retirement/golden-a-rollback-receipt.v1.json",
            "receipt_sha256": "sha256:94326deafc88e0d8d7613c8078de9847fb078ecf578fc77496e0eee7445d44bd",
            "retirement_boundary": "CP-M1-GA-RET-02",
        },
    }
    assert result["source_base"] is None
    assert result["image"] is None
    assert result["secret_included"] is False


def test_current_ae_source_base_uses_standard_owner_scoped_context(
    monkeypatch, tmp_path: Path
) -> None:
    definition = SimpleNamespace(
        artifact_id="nex-ae-runtime",
        target="ae-runtime",
    )
    commands: list[list[str]] = []

    monkeypatch.setattr(build, "build_default_deployment_artifact_catalog", object)
    monkeypatch.setattr(
        build,
        "build_default_oci_definitions",
        lambda _catalog: (definition,),
    )

    def materialize(root, context, observed):
        assert root == build.ROOT
        assert observed is definition
        context.mkdir(parents=True)
        (context / "Containerfile").write_text("FROM scratch\n", encoding="utf-8")
        return "context-manifest"

    monkeypatch.setattr(build, "materialize_oci_build_context", materialize)
    monkeypatch.setattr(
        build, "oci_build_context_digest", lambda value: "sha256:source-context"
    )
    monkeypatch.setattr(
        build, "build_deployment_build_inputs", lambda *_args, **_kwargs: "locks"
    )
    monkeypatch.setattr(
        build, "deployment_build_inputs_digest", lambda value: "sha256:locks"
    )
    monkeypatch.setattr(build, "_text_command", lambda _command: "a" * 40 + "\n")
    monkeypatch.setattr(
        build.subprocess,
        "run",
        lambda command, **_kwargs: commands.append(list(command)),
    )
    monkeypatch.setattr(
        build,
        "_single_image_inspection",
        lambda _image: {"Id": "sha256:source-image"},
    )

    image, evidence = build._build_current_ae_base(
        tmp_path / "context",
        output_image="nex-platform-demo/nex-ae-runtime:p8-demo-s10b",
    )

    assert image == "nex-platform-demo/nex-ae-runtime:p8-demo-s10b-source"
    assert evidence == {
        "image": image,
        "image_id": "sha256:source-image",
        "source_revision": "a" * 40,
        "source_context_digest": "sha256:source-context",
        "build_inputs_digest": "sha256:locks",
        "artifact_id": "nex-ae-runtime",
        "target": "ae-runtime",
    }
    assert commands[0][commands[0].index("--target") + 1] == "ae-runtime"
    assert commands[0][-1] == str(tmp_path / "context")
