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
    assert "ae-mybee-m1-runtime-activation.v4.json" in source
    assert "mybee-m1-d04-d12.v3.nsp" in source
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
        "activation_hash": "sha256:ce6f8b858b6a432bf661aa1cc0c67b3454b0d8062950203251d805915a481b65",
        "admission_hash": "sha256:7158792d96d7496d7b1ba4091491b053613d68623f32ab39a75c56532a14b309",
        "release_id": "nex-mybee-m1-d04-d12-checkpoint-v3",
        "release_hash": "sha256:7011c13b883137d15c930adc64b62e2cdf6c8ba2e78880d5404c239e1bf12b4c",
        "package_hash": "sha256:a2397cc11559d882e11bfaaa4ecf742ab965158b1cbcebb8dc32bf0eaf477b9c",
        "skill_catalog_hash": "sha256:1bc19745f7a93844e59b70a20bbd7ce28e6a23d0723c4fcff399eef95b9a5a0a",
        "runtime_selectable_capabilities": [
            "FINANCE.VOUCHER.APPROVE_AND_POST",
            "PROJECT.WORK_CODE_SET.GET",
        ],
        "rollback_target": {
            "profile": "VERIFIED_PRODUCT_RELEASE",
            "receipt_ref": "deployment/locks/ae-mybee-m1-generalized-rollback.v3.json",
            "receipt_sha256": "sha256:8be845b058be0b33673b528d64f569c5bd35e42cc819c7ac5d2410a2067397f2",
            "runtime_admission_hash": "sha256:812f68e387069654f7598bb891d14626107631008d8520f75bf3aa26612a905a",
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
