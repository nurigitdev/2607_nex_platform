from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import build_p8_demo_ae_runtime_image as build

ROOT = Path(__file__).resolve().parents[1]


def test_demo_ae_runtime_containerfile_admits_every_embedded_asset_path() -> None:
    source = (ROOT / "deployment/oci/p8-demo-ae-runtime.Containerfile").read_text(
        encoding="utf-8"
    )

    assert (
        "NEX_AE_DEMO_PLATFORM_LOCK=/app/deployment/p8-demo/locks/python-production.lock"
    ) in source
    assert (
        "install -d -o 65532 -g 65532 -m 0700 /var/lib/nex-platform/ae-runtime/nsl"
    ) in source
    assert source.index("install -d -o 65532") < source.index("USER 65532:65532")
    assert "COPY --chown=65532:65532 config" in source
    assert "NEX_AE_FINANCE_GOLDEN_A_AUTHORITY_PROFILE_PATH=" in source
    assert "NEX_AE_PRODUCT_CAPABILITY_REGISTRY_PATH=" in source
    assert "assert all(Path(os.environ[name]).exists() for name in names)" in source


def test_demo_ae_runtime_image_dry_run_requires_locked_bundle() -> None:
    result = build.build_p8_demo_ae_runtime_image(
        base_image="nex-platform-demo/nex-ae-runtime:prior",
        output_image="nex-platform-demo/nex-ae-runtime:p8-demo-s10b",
        execute=False,
    )

    assert result["status"] == "READY"
    assert result["bundle"]["status"] == "PASS"
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
