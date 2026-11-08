from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from pathlib import Path

import build_canonical_platform_images as build
import nex_runtime.demo_oci_release as demo_oci
import pytest
from nex_runtime.demo_oci_release import (
    DEMO_APPLICATION_ARTIFACTS,
    DEMO_BACKGROUND_PROCESS_IDS,
    DEMO_PACKAGE_CHECK_MODE,
    DEMO_PACKAGE_CHECK_MODE_ENV,
    DemoBackgroundContainerCheck,
    DemoOciReleaseError,
    DemoPackagedEntrypoint,
    build_demo_deployment_artifact_catalog,
    build_demo_packaged_entrypoints,
    validate_demo_oci_release,
)
from nex_runtime.deployment_artifacts import build_current_deployment_artifact_catalog
from nex_runtime.deployment_entrypoints import (
    build_current_packaged_runtime_manifest,
    build_packaged_entrypoint_definitions,
)
from nex_runtime.deployment_image_build import (
    OciImageBuildRecord,
    packaged_image_default_command,
)
from nex_runtime.deployment_locks import (
    build_deployment_build_inputs,
    deployment_build_inputs_digest,
)
from nex_runtime.deployment_oci import (
    build_current_oci_definitions,
    build_default_oci_definitions,
    validate_oci_containerfiles,
)
from nex_runtime.process_manifest import (
    BACKGROUND_PROCESS_IDS,
    CURRENT_BACKGROUND_PROCESS_IDS,
)
from nex_runtime.runtime_package_admission import (
    RUNTIME_CHECK_MODE_ENV,
    RUNTIME_PACKAGE_CHECK_MODE,
)

ROOT = Path(__file__).resolve().parents[1]
REVISION = "b" * 40


def test_canonical_catalog_and_packaged_entrypoints_cover_exact_release() -> None:
    catalog = build_current_deployment_artifact_catalog()
    manifest = build_current_packaged_runtime_manifest(
        "local_mock", environ={}, python_executable="python"
    )
    entries = build_packaged_entrypoint_definitions(manifest, catalog)

    assert len(catalog.artifacts) == 9
    assert len(entries) == 20
    assert {
        item.process_id for item in entries if item.kind in {"worker", "daemon"}
    } == set(CURRENT_BACKGROUND_PROCESS_IDS)
    assert (
        next(item for item in entries if item.process_id == "nex-wc-api").command[-1]
        == "8106"
    )
    assert (
        next(item for item in entries if item.process_id == "nex-eos-api").command[-1]
        == "8107"
    )

    definitions = build_current_oci_definitions()
    validate_oci_containerfiles(ROOT, definitions)
    assert {item.target for item in definitions} >= {
        "wc-runtime",
        "eos-runtime",
        "wa-runtime",
    }


def test_protected_runner_requires_double_opt_in() -> None:
    assert (
        build.run_canonical_platform_image_build({}, execute=True)["status"]
        == "SKIPPED"
    )
    assert (
        build.run_canonical_platform_image_build(
            {build.EXECUTION_ENV: "1"}, execute=False
        )["status"]
        == "SKIPPED"
    )


def test_protected_runner_contains_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        build,
        "_execute_canonical_platform_image_build",
        lambda *_args: (_ for _ in ()).throw(ValueError("private")),
    )

    result = build.run_canonical_platform_image_build(
        {build.EXECUTION_ENV: "1"}, execute=True
    )

    assert result["status"] == "FAIL"
    assert result["issues"] == ["private"]
    assert result["decision"]["registry_push_performed"] is False


def test_build_rejects_dirty_or_context_contaminated_source(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(build, "_git_metadata", lambda *_args: (REVISION, False, 0))

    with pytest.raises(
        build.image_build.PlatformImageBuildError,
        match="clean tracked and build-context sources",
    ):
        build._execute_canonical_platform_image_build(ROOT, tmp_path / "report.json")


def test_full_canonical_build_orchestration_with_fake_docker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    catalog = build_current_deployment_artifact_catalog()
    definitions = build_current_oci_definitions()
    inputs = build_deployment_build_inputs(ROOT, catalog=catalog)
    inputs_digest = deployment_build_inputs_digest(inputs)
    manifest = build_current_packaged_runtime_manifest(
        "local_mock", environ={}, python_executable="python"
    )
    entries = build_packaged_entrypoint_definitions(manifest, catalog)
    default_commands = {
        item.artifact_id: packaged_image_default_command(item)
        for item in entries
        if item.kind in {"api", "web"}
    }
    inspections: dict[str, dict] = {}

    monkeypatch.setattr(build, "_git_metadata", lambda *_args: (REVISION, True, 1))
    monkeypatch.setattr(
        build.image_build,
        "_docker_preflight",
        lambda _root: {
            "version": "29.4.3",
            "api_version": "1.54",
            "os": "linux",
            "architecture": "amd64",
        },
    )

    def fake_build_image(**kwargs) -> None:
        definition = kwargs["definition"]
        index = definitions.index(definition) + 1
        manifest_digest = f"sha256:{index + 300:064x}"
        config_digest = f"sha256:{index + 400:064x}"
        kwargs["metadata_path"].write_text(
            json.dumps(
                {
                    "containerimage.config.digest": config_digest,
                    "containerimage.digest": manifest_digest,
                }
            ),
            encoding="utf-8",
        )
        artifact = next(
            item
            for item in catalog.artifacts
            if item.artifact_id == definition.artifact_id
        )
        inspections[kwargs["tag"]] = {
            "Id": manifest_digest,
            "Descriptor": {
                "digest": manifest_digest,
                "annotations": {"config.digest": config_digest},
            },
            "Config": {
                "User": "node" if artifact.kind == "node-web" else "65532:65532",
                "Entrypoint": None,
                "Cmd": list(default_commands[artifact.artifact_id]),
                "Labels": {
                    "org.opencontainers.image.version": REVISION[:12],
                    "org.opencontainers.image.revision": REVISION,
                    "io.nex-platform.build-inputs-digest": inputs_digest,
                },
            },
        }

    def fake_capture(command, *, cwd, operation):
        del cwd
        process_id = next(
            (item for item in CURRENT_BACKGROUND_PROCESS_IDS if item in operation),
            None,
        )
        assert process_id is not None
        package_check = process_id not in BACKGROUND_PROCESS_IDS
        if package_check:
            assert f"{RUNTIME_CHECK_MODE_ENV}={RUNTIME_PACKAGE_CHECK_MODE}" in command
            payload = {
                "process_id": process_id,
                "package_ready": True,
                "runtime_ready": False,
                "secret_included": False,
            }
        else:
            payload = {
                "process_id": process_id,
                "profile": "local_mock",
                "persistence_mode": "memory",
                "lifecycle_ready": True,
                "work_claiming_enabled": False,
            }
        return subprocess.CompletedProcess(
            command,
            0,
            json.dumps(payload) + "\n",
            "",
        )

    monkeypatch.setattr(build.image_build, "_build_image", fake_build_image)
    monkeypatch.setattr(
        build.image_build, "_inspect_image", lambda tag, root: inspections[tag]
    )
    monkeypatch.setattr(build.image_build, "_run_capture", fake_capture)

    result = build._execute_canonical_platform_image_build(
        ROOT, tmp_path / "report.json"
    )

    assert result["status"] == "PASS"
    assert result["summary"] == {
        "artifact_count": 9,
        "manifest_digest_count": 9,
        "non_root_image_count": 9,
        "background_check_count": 11,
        "release_set_ready": True,
    }
    assert result["excluded_untracked_count"] == 1
    assert result["release_manifest"]["status"] == "RELEASE_SET_READY"
    assert result["decision"]["registry_push_performed"] is False


def test_demo_release_validation_fails_closed() -> None:
    with pytest.raises(DemoOciReleaseError) as raised:
        validate_demo_oci_release(
            source_revision="bad",
            build_inputs_digest="bad",
            release_set_digest="bad",
            records=(),
            background_checks=(
                DemoBackgroundContainerCheck(
                    "unknown", "unknown", ("bad",), False, True, True
                ),
            ),
        )

    detail = str(raised.value)
    assert "source revision" in detail
    assert "artifact coverage" in detail
    assert "package-check" in detail


def _record(artifact_id: str, index: int) -> OciImageBuildRecord:
    catalog = build_demo_deployment_artifact_catalog()
    entries = build_demo_packaged_entrypoints()
    artifact = next(
        item for item in catalog.artifacts if item.artifact_id == artifact_id
    )
    command = next(
        item.command
        for item in entries
        if item.artifact_id == artifact_id and item.kind in {"api", "web"}
    )
    digest = f"sha256:{index:064x}"
    config = f"sha256:{index + 100:064x}"
    return OciImageBuildRecord(
        artifact_id=artifact_id,
        owner=artifact.owner,
        target=artifact.build_target,
        local_tag=f"local/{artifact_id}:test",
        image_id=digest,
        manifest_digest=digest,
        config_digest=config,
        image_reference=f"local/{artifact_id}@{digest}",
        base_image_reference="python@" + digest,
        builder_image_references=(),
        source_revision=REVISION,
        dependency_lock_id=artifact.dependency_family,
        dependency_lock_digest=digest,
        build_definition_digest=digest,
        build_context_digest=digest,
        platform="linux/amd64",
        runtime_user="65532:65532",
        entrypoint=(),
        command=command,
        labels=(
            ("org.opencontainers.image.revision", REVISION),
            ("io.nex-platform.build-inputs-digest", "sha256:" + "a" * 64),
        ),
    )


def test_demo_release_validation_exercises_record_and_check_guards() -> None:
    artifact_ids = [
        item.artifact_id for item in build_demo_deployment_artifact_catalog().artifacts
    ]
    records = [
        _record(artifact_id, index + 1)
        for index, artifact_id in enumerate(artifact_ids)
    ]
    records[0] = replace(
        records[0],
        source_revision="c" * 40,
        runtime_user="root",
        entrypoint=("bad",),
        command=("bad",),
        image_id="bad",
        dependency_lock_digest="bad",
        build_definition_digest="bad",
        build_context_digest="bad",
        labels=(),
    )
    records[1] = replace(
        records[1],
        manifest_digest=records[0].manifest_digest,
        image_id=records[0].image_id,
    )
    entries = {
        item.process_id: item
        for item in build_demo_packaged_entrypoints()
        if item.kind == "worker"
    }
    checks = [
        DemoBackgroundContainerCheck(
            process_id,
            entry.artifact_id,
            ("bad",),
            False,
            True,
            True,
        )
        for process_id, entry in entries.items()
    ]

    with pytest.raises(DemoOciReleaseError) as raised:
        validate_demo_oci_release(
            source_revision=REVISION,
            build_inputs_digest="sha256:" + "a" * 64,
            release_set_digest="sha256:" + "b" * 64,
            records=records,
            background_checks=checks,
        )

    detail = str(raised.value)
    assert "privileged runtime" in detail
    assert "entrypoint drift" in detail
    assert "command drift" in detail
    assert "image identity drift" in detail
    assert "digest invalid" in detail
    assert "revision label drift" in detail
    assert "inputs label drift" in detail
    assert "background command drift" in detail


def test_demo_catalog_and_entrypoint_internal_guards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(demo_oci, "DEMO_APPLICATION_ARTIFACTS", ())
    with pytest.raises(DemoOciReleaseError, match="catalog coverage"):
        build_demo_deployment_artifact_catalog()

    valid = build_demo_packaged_entrypoints()
    unknown = DemoPackagedEntrypoint("unknown", "unknown", "unknown", "worker", ())
    wrong = DemoPackagedEntrypoint(
        valid[0].process_id,
        valid[0].artifact_id,
        "wrong-owner",
        valid[0].kind,
        ("tests/helper.py",),
    )
    with pytest.raises(DemoOciReleaseError) as raised:
        demo_oci._validate_demo_packaged_entrypoints((unknown, wrong))
    assert "process coverage drift" in str(raised.value)
    assert "ownership drift" in str(raised.value)
    assert "command invalid" in str(raised.value)


@pytest.mark.parametrize(
    ("user", "expected"),
    (
        ("", False),
        ("0", False),
        ("root", False),
        ("0:1", False),
        ("root:root", False),
        ("node", True),
    ),
)
def test_non_root_user_guard(user: str, expected: bool) -> None:
    assert demo_oci._non_root_user(user) is expected
    assert build._non_root_user(user) is expected


def test_git_metadata_allows_only_untracked_outside_build_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    definitions = build_current_oci_definitions()

    def capture(command, *, cwd, operation):
        del cwd, operation
        if command[1:3] == ("rev-parse", "HEAD"):
            output = REVISION + "\n"
        elif "--untracked-files=no" in command:
            output = ""
        else:
            output = "test/local.txt\nservices/nex-wc/nex_wc/private.py\n"
        return subprocess.CompletedProcess(command, 0, output, "")

    monkeypatch.setattr(build.image_build, "_run_capture", capture)
    revision, clean, excluded = build._git_metadata(ROOT, definitions)

    assert revision == REVISION
    assert clean is False
    assert excluded == 1


def test_runner_report_summary_and_main(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = tmp_path / "report.json"
    passing = {
        "status": "PASS",
        "summary": {
            "artifact_count": 9,
            "manifest_digest_count": 9,
            "non_root_image_count": 9,
            "background_check_count": 11,
            "release_set_ready": True,
        },
    }
    assert build.summary_line({"status": "SKIPPED"}).endswith("skipped")
    assert "issues=1" in build.summary_line({"status": "FAIL", "issues": ["x"]})
    assert "artifacts=9" in build.summary_line(passing)

    build._write_report(report, passing)
    assert json.loads(report.read_text(encoding="utf-8")) == passing

    monkeypatch.setattr(
        build, "run_canonical_platform_image_build", lambda **_kwargs: passing
    )
    assert build.main(["--report", str(report), "--summary"]) == 0
    assert "canonical_platform_oci_image_build=pass" in capsys.readouterr().out

    monkeypatch.setattr(
        build,
        "run_canonical_platform_image_build",
        lambda **_kwargs: {"status": "SKIPPED"},
    )
    assert build.main(["--report", str(report)]) == 0
    assert '"status": "SKIPPED"' in capsys.readouterr().out

    monkeypatch.setattr(
        build,
        "run_canonical_platform_image_build",
        lambda **_kwargs: {"status": "FAIL"},
    )
    assert build.main(["--report", str(report)]) == 1
