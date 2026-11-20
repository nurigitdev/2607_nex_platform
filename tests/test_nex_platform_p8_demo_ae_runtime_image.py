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
    assert "ae-mybee-m1-runtime-activation.v3.json" in source
    assert "mybee-m1-d04-d12.v2.nsp" in source
    assert (
        "install -d -o 65532 -g 65532 -m 0700 /var/lib/nex-platform/ae-runtime/nsl"
    ) in source
    assert source.index("install -d -o 65532") < source.index("USER 65532:65532")
    assert (
        "COPY --chown=65532:65532 config /app/deployment/product/config"
        in source
    )
    assert (
        "NEX_AE_PROJECT_AGENT_PROFILE_POLICY_PATH=/app/deployment/product/"
        "config/project-agent-profile-policy.v1.json"
    ) in source
    assert (
        "COPY --chown=65532:65532 repository/domains/mybee/config "
        "/app/domains/mybee/config"
    ) in source
    assert "NEX_AE_FINANCE_GOLDEN_A_AUTHORITY_PROFILE_PATH=" not in source
    assert "NEX_AE_PRODUCT_CAPABILITY_REGISTRY_PATH=" in source
    assert "NEX_AE_PRODUCT_CAPABILITY_RETIREMENT_PATH=" not in source
    assert "NEX_AE_NSL_BUNDLE_MANIFEST=" not in source
    assert "NEX_AE_NSL_SKILL_ROOT=" not in source
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
    assert result["bundle_role"] == "GENERALIZED_M1_RELEASE"
    assert result["active_runtime_profile"] == "VERIFIED_PRODUCT_RELEASE"
    assert result["verified_product_release"] == {
        "activation_state": "ACTIVE_GENERALIZED",
        "activation_hash": "sha256:bef2cb2f4314b0fd177fce1195c2bdd93c833330b3d7b00cd8908ce4cd0974f3",
        "admission_hash": "sha256:812f68e387069654f7598bb891d14626107631008d8520f75bf3aa26612a905a",
        "release_id": "nex-mybee-m1-d04-d12-checkpoint-v2",
        "release_hash": "sha256:df57c14d1693dc5469f18a09a1e9bdaeef404b23d601263d533c3c38cb92c234",
        "package_hash": "sha256:ac99192443b315699f33adc7430f0a064ad0913e5c26e268538e6bd4468e9bed",
        "skill_catalog_hash": "sha256:6f17db256b58fbd0cf6ec390564c9c4ca459b7216e10fc3602043bea98b87bf2",
        "runtime_selectable_capabilities": [
            "FINANCE.VOUCHER.APPROVE_AND_POST",
            "PROJECT.WORK_CODE_SET.GET",
        ],
        "rollback_target": {
            "profile": "VERIFIED_PRODUCT_RELEASE",
            "receipt_ref": "deployment/locks/ae-mybee-m1-generalized-rollback.v2.json",
            "receipt_sha256": "sha256:73357d1311a154dea76a74ef673d8cc32a83e8f9a3e9d4548205cba74c654a75",
            "runtime_admission_hash": "sha256:912229dfc42e881e28418af9289c1a58b99677cb4e46b7975677725d2b98edc4",
            "golden_a_dependency": False,
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
