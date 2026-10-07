from __future__ import annotations

import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

import build_platform_images as build
from nex_runtime.deployment_artifacts import build_default_deployment_artifact_catalog
from nex_runtime.deployment_entrypoints import (
    build_packaged_entrypoint_definitions,
    build_packaged_runtime_manifest,
)
from nex_runtime.deployment_locks import (
    build_deployment_build_inputs,
    deployment_build_inputs_digest,
)
from nex_runtime.deployment_oci import build_default_oci_definitions
from nex_runtime.process_manifest import BACKGROUND_PROCESS_IDS


ROOT = Path(__file__).resolve().parents[1]
REVISION = "a" * 40


def test_protected_command_skips_without_both_opt_ins(tmp_path: Path) -> None:
    assert build.run_platform_image_build({}, execute=True)["status"] == "SKIPPED"
    assert (
        build.run_platform_image_build(
            {build.EXECUTION_ENV: "1"}, execute=False
        )["status"]
        == "SKIPPED"
    )


def test_protected_command_uses_executor_and_contains_failures(tmp_path: Path) -> None:
    passing = {"status": "PASS", "summary": {"artifact_count": 6}}
    result = build.run_platform_image_build(
        {build.EXECUTION_ENV: "1"},
        execute=True,
        root=tmp_path,
        report_path=tmp_path / "report.json",
        executor=lambda root, report: passing,
    )
    assert result == passing

    failed = build.run_platform_image_build(
        {build.EXECUTION_ENV: "1"},
        execute=True,
        root=tmp_path,
        report_path=tmp_path / "report.json",
        executor=lambda root, report: (_ for _ in ()).throw(ValueError("blocked")),
    )
    assert failed["status"] == "FAIL"
    assert failed["issues"] == ["blocked"]
    assert failed["decision"]["registry_push_performed"] is False


def test_full_build_orchestration_with_fake_docker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    catalog = build_default_deployment_artifact_catalog()
    definitions = build_default_oci_definitions(catalog)
    inputs = build_deployment_build_inputs(ROOT, catalog=catalog)
    inputs_digest = deployment_build_inputs_digest(inputs)
    manifest = build_packaged_runtime_manifest(
        "local_mock", environ={}, python_executable="python"
    )
    entries = build_packaged_entrypoint_definitions(manifest, catalog)
    default_commands = {
        entry.artifact_id: entry.command
        for entry in entries
        if entry.kind in {"api", "web"}
    }
    definitions_by_id = {item.artifact_id: item for item in definitions}
    inspections: dict[str, dict] = {}

    monkeypatch.setattr(build, "_git_metadata", lambda root: (REVISION, True))
    monkeypatch.setattr(
        build,
        "_docker_preflight",
        lambda root: {
            "version": "29.4.3",
            "api_version": "1.54",
            "os": "linux",
            "architecture": "amd64",
        },
    )

    def fake_build_image(**kwargs) -> None:
        definition = kwargs["definition"]
        index = definitions.index(definition) + 1
        manifest_digest = f"sha256:{index + 100:064x}"
        config_digest = f"sha256:{index + 200:064x}"
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
            item for item in catalog.artifacts if item.artifact_id == definition.artifact_id
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
        del cwd, operation
        process_id = next(
            (item for item in BACKGROUND_PROCESS_IDS if item in command), None
        )
        assert process_id is not None
        return subprocess.CompletedProcess(
            command,
            0,
            json.dumps(
                {
                    "process_id": process_id,
                    "profile": "local_mock",
                    "persistence_mode": "memory",
                    "lifecycle_ready": True,
                    "work_claiming_enabled": False,
                }
            )
            + "\n",
            "",
        )

    monkeypatch.setattr(build, "_build_image", fake_build_image)
    monkeypatch.setattr(
        build, "_inspect_image", lambda tag, root: inspections[tag]
    )
    monkeypatch.setattr(build, "_run_capture", fake_capture)

    result = build._execute_image_build(ROOT, tmp_path / "report.json")

    assert result["status"] == "PASS"
    assert result["summary"] == {
        "artifact_count": 6,
        "manifest_digest_count": 6,
        "non_root_image_count": 6,
        "background_check_count": 7,
        "release_set_ready": True,
    }
    assert result["release_manifest"]["status"] == "RELEASE_SET_READY"
    assert result["decision"]["registry_push_performed"] is False
    assert set(result["build_logs"]) == set(definitions_by_id)


def test_docker_metadata_helpers_and_failures(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    digest = "sha256:" + "a" * 64
    assert build._manifest_digest({"containerimage.digest": digest}) == digest
    assert (
        build._manifest_digest(
            {"containerimage.descriptor": {"digest": digest}}
        )
        == digest
    )
    with pytest.raises(build.PlatformImageBuildError, match="manifest digest"):
        build._manifest_digest({})
    with pytest.raises(build.PlatformImageBuildError, match="image ID"):
        build._required_digest("sha256:bad", "image ID")
    assert build._string_tuple(None) == ()
    assert build._string_tuple(["python", "-m"]) == ("python", "-m")
    with pytest.raises(build.PlatformImageBuildError, match="command metadata"):
        build._string_tuple("python")
    with pytest.raises(build.PlatformImageBuildError, match="command metadata"):
        build._string_tuple([1])

    payload = build._last_json_object(
        f"warning\n{json.dumps({'process_id': 'worker'})}\n", "worker"
    )
    assert payload["process_id"] == "worker"
    with pytest.raises(build.PlatformImageBuildError, match="identity drift"):
        build._last_json_object(
            json.dumps({"process_id": "wrong"}), "worker"
        )
    with pytest.raises(build.PlatformImageBuildError, match="output is invalid"):
        build._last_json_object("not-json", "worker")
    with pytest.raises(build.PlatformImageBuildError, match="output is invalid"):
        build._last_json_object("[]", "worker")

    invalid = tmp_path / "invalid.json"
    invalid.write_text("[]", encoding="utf-8")
    with pytest.raises(build.PlatformImageBuildError, match="is invalid"):
        build._read_object(invalid, "metadata")
    with pytest.raises(build.PlatformImageBuildError, match="is unavailable"):
        build._read_object(tmp_path / "missing.json", "metadata")

    monkeypatch.setattr(
        build,
        "_run_capture",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 0, json.dumps({"Version": "29.4.3"}), ""
        ),
    )
    assert build._docker_preflight(tmp_path)["version"] == "29.4.3"

    monkeypatch.setattr(
        build,
        "_run_capture",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 0, "not-json", ""
        ),
    )
    with pytest.raises(build.PlatformImageBuildError, match="metadata is invalid"):
        build._docker_preflight(tmp_path)
    monkeypatch.setattr(
        build,
        "_run_capture",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 0, "{}", ""
        ),
    )
    with pytest.raises(build.PlatformImageBuildError, match="metadata is incomplete"):
        build._docker_preflight(tmp_path)


def test_image_record_inspection_and_release_decision_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    catalog = build_default_deployment_artifact_catalog()
    definition = build_default_oci_definitions(catalog)[0]
    artifact = catalog.artifacts[0]
    inputs = build_deployment_build_inputs(ROOT, catalog=catalog)
    lock = next(item for item in inputs.locks if item.lock_id == artifact.dependency_family)
    context_root = tmp_path / "context"
    from nex_runtime.deployment_oci import materialize_oci_build_context

    context = materialize_oci_build_context(ROOT, context_root, definition)
    image_id = "sha256:" + "1" * 64
    manifest_digest = "sha256:" + "2" * 64
    metadata_path = tmp_path / "metadata.json"
    metadata_path.write_text(
        json.dumps(
            {
                "containerimage.config.digest": image_id,
                "containerimage.digest": manifest_digest,
            }
        ),
        encoding="utf-8",
    )
    valid_inspection = {
        "Id": image_id,
        "Config": {
            "User": "65532:65532",
            "Entrypoint": None,
            "Cmd": [
                "python",
                "-m",
                "uvicorn",
                "nex_oa.main:app",
                "--host",
                "0.0.0.0",
                "--port",
                "8101",
            ],
            "Labels": {
                "org.opencontainers.image.version": REVISION[:12],
                "org.opencontainers.image.revision": REVISION,
                "io.nex-platform.build-inputs-digest": deployment_build_inputs_digest(inputs),
            },
        },
    }
    monkeypatch.setattr(build, "_inspect_image", lambda tag, root: valid_inspection)
    record = build._build_record(
        root=ROOT,
        definition=definition,
        artifact=artifact,
        lock=lock,
        context=context,
        metadata_path=metadata_path,
        tag="nex-platform-local/nex-oa-runtime:aaaaaaaaaaaa",
        source_revision=REVISION,
        build_inputs_digest=deployment_build_inputs_digest(inputs),
    )
    assert record.image_id == image_id
    assert record.manifest_digest == manifest_digest
    assert record.config_digest == image_id

    containerd_inspection = {
        **valid_inspection,
        "Id": manifest_digest,
        "Descriptor": {
            "digest": manifest_digest,
            "annotations": {"config.digest": image_id},
        },
    }
    monkeypatch.setattr(
        build, "_inspect_image", lambda tag, root: containerd_inspection
    )
    containerd_record = build._build_record(
        root=ROOT,
        definition=definition,
        artifact=artifact,
        lock=lock,
        context=context,
        metadata_path=metadata_path,
        tag=record.local_tag,
        source_revision=REVISION,
        build_inputs_digest=deployment_build_inputs_digest(inputs),
    )
    assert containerd_record.image_id == manifest_digest
    assert containerd_record.config_digest == image_id

    invalid_descriptors = (
        ("invalid", "descriptor invalid"),
        ({"annotations": "invalid"}, "descriptor annotations invalid"),
        ({"digest": "sha256:" + "3" * 64}, "manifest digest drift"),
        (
            {"annotations": {"config.digest": "sha256:" + "3" * 64}},
            "config digest drift",
        ),
    )
    for descriptor, message in invalid_descriptors:
        inspection = {**valid_inspection, "Descriptor": descriptor}
        monkeypatch.setattr(
            build,
            "_inspect_image",
            lambda tag, root, inspection=inspection: inspection,
        )
        with pytest.raises(build.PlatformImageBuildError, match=message):
            build._build_record(
                root=ROOT,
                definition=definition,
                artifact=artifact,
                lock=lock,
                context=context,
                metadata_path=metadata_path,
                tag=record.local_tag,
                source_revision=REVISION,
                build_inputs_digest=deployment_build_inputs_digest(inputs),
            )

    metadata_path.write_text(
        json.dumps(
            {
                "containerimage.config.digest": "sha256:" + "3" * 64,
                "containerimage.digest": manifest_digest,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(build.PlatformImageBuildError, match="identity drift"):
        build._build_record(
            root=ROOT,
            definition=definition,
            artifact=artifact,
            lock=lock,
            context=context,
            metadata_path=metadata_path,
            tag=record.local_tag,
            source_revision=REVISION,
            build_inputs_digest=deployment_build_inputs_digest(inputs),
        )

    metadata_path.write_text(
        json.dumps({"containerimage.digest": manifest_digest}), encoding="utf-8"
    )
    monkeypatch.setattr(build, "_inspect_image", lambda tag, root: {"Id": image_id})
    with pytest.raises(build.PlatformImageBuildError, match="image config digest"):
        build._build_record(
            root=ROOT,
            definition=definition,
            artifact=artifact,
            lock=lock,
            context=context,
            metadata_path=metadata_path,
            tag=record.local_tag,
            source_revision=REVISION,
            build_inputs_digest=deployment_build_inputs_digest(inputs),
        )

    metadata_path.write_text(
        json.dumps(
            {
                "containerimage.config.digest": image_id,
                "containerimage.digest": manifest_digest,
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(build.PlatformImageBuildError, match="configuration missing"):
        build._build_record(
            root=ROOT,
            definition=definition,
            artifact=artifact,
            lock=lock,
            context=context,
            metadata_path=metadata_path,
            tag=record.local_tag,
            source_revision=REVISION,
            build_inputs_digest=deployment_build_inputs_digest(inputs),
        )

    invalid_labels = {
        **valid_inspection,
        "Config": {**valid_inspection["Config"], "Labels": "invalid"},
    }
    monkeypatch.setattr(build, "_inspect_image", lambda tag, root: invalid_labels)
    with pytest.raises(build.PlatformImageBuildError, match="labels invalid"):
        build._build_record(
            root=ROOT,
            definition=definition,
            artifact=artifact,
            lock=lock,
            context=context,
            metadata_path=metadata_path,
            tag=record.local_tag,
            source_revision=REVISION,
            build_inputs_digest=deployment_build_inputs_digest(inputs),
        )

    assert build._validated_release_set_digest(
        SimpleNamespace(status="RELEASE_SET_READY", release_set_digest=manifest_digest)
    ) == manifest_digest
    with pytest.raises(build.PlatformImageBuildError, match="was not admitted"):
        build._validated_release_set_digest(
            SimpleNamespace(status="BUILD_INPUTS_READY", release_set_digest=None)
        )
    with pytest.raises(build.PlatformImageBuildError, match="digest is missing"):
        build._validated_release_set_digest(
            SimpleNamespace(status="RELEASE_SET_READY", release_set_digest=None)
        )


def test_image_inspection_git_metadata_and_dirty_execution(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    original_git_metadata = build._git_metadata
    responses = iter(
        (
            subprocess.CompletedProcess((), 0, json.dumps([{"Id": "ok"}]), ""),
            subprocess.CompletedProcess((), 0, REVISION + "\n", ""),
            subprocess.CompletedProcess((), 0, " M changed\n", ""),
        )
    )
    monkeypatch.setattr(build, "_run_capture", lambda *args, **kwargs: next(responses))
    assert build._inspect_image("local/test:tag", root=tmp_path)["Id"] == "ok"
    assert build._git_metadata(tmp_path) == (REVISION, False)

    monkeypatch.setattr(build, "_git_metadata", lambda root: (REVISION, False))
    with pytest.raises(build.PlatformImageBuildError, match="clean source tree"):
        build._execute_image_build(tmp_path, tmp_path / "report.json")
    monkeypatch.setattr(build, "_git_metadata", original_git_metadata)

    for output, message in (
        ("not-json", "inspection is invalid"),
        ("[]", "inspection is incomplete"),
        ("[1]", "object is invalid"),
    ):
        monkeypatch.setattr(
            build,
            "_run_capture",
            lambda *args, output=output, **kwargs: subprocess.CompletedProcess(
                args[0], 0, output, ""
            ),
        )
        with pytest.raises(build.PlatformImageBuildError, match=message):
            build._inspect_image("local/test:tag", root=tmp_path)

    responses = iter(
        (
            subprocess.CompletedProcess((), 0, "short\n", ""),
            subprocess.CompletedProcess((), 0, "", ""),
        )
    )
    monkeypatch.setattr(build, "_run_capture", lambda *args, **kwargs: next(responses))
    with pytest.raises(build.PlatformImageBuildError, match="revision is invalid"):
        build._git_metadata(tmp_path)


def test_build_and_capture_command_errors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    definition = build_default_oci_definitions()[0]
    context = tmp_path / "context"
    context.mkdir()
    (context / "Containerfile").write_text("FROM scratch\n", encoding="utf-8")
    monkeypatch.setattr(
        build.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1, "", ""),
    )
    with pytest.raises(build.PlatformImageBuildError, match="image build failed"):
        build._build_image(
            definition=definition,
            context_root=context,
            metadata_path=tmp_path / "metadata.json",
            log_path=tmp_path / "build.log",
            tag="local/test:tag",
            source_revision=REVISION,
            build_inputs_digest="sha256:" + "b" * 64,
            docker_config=tmp_path / "docker-config",
            root=tmp_path,
        )
    with pytest.raises(build.PlatformImageBuildError, match="operation failed"):
        build._run_capture(("false",), cwd=tmp_path, operation="operation")
    monkeypatch.setattr(
        build.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "ok", ""),
    )
    assert build._run_capture(("true",), cwd=tmp_path, operation="operation").stdout == "ok"
    build._build_image(
        definition=definition,
        context_root=context,
        metadata_path=tmp_path / "metadata.json",
        log_path=tmp_path / "success.log",
        tag="local/test:tag",
        source_revision=REVISION,
        build_inputs_digest="sha256:" + "b" * 64,
        docker_config=tmp_path / "docker-config",
        root=tmp_path,
    )


def test_summary_main_and_atomic_report(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    passing = {
        "status": "PASS",
        "summary": {
            "artifact_count": 6,
            "manifest_digest_count": 6,
            "non_root_image_count": 6,
            "background_check_count": 7,
            "release_set_ready": True,
        },
        "decision": {"registry_push_performed": False},
    }
    assert build.summary_line({"status": "SKIPPED"}) == (
        "platform_oci_image_build=skipped"
    )
    assert build.summary_line({"status": "FAIL", "issues": [1]}) == (
        "platform_oci_image_build=fail issues=1"
    )
    assert "artifacts=6" in build.summary_line(passing)

    report = tmp_path / "report.json"
    build._write_report(report, passing)
    assert json.loads(report.read_text(encoding="utf-8")) == passing
    assert not report.with_suffix(".json.tmp").exists()

    monkeypatch.setattr(build, "run_platform_image_build", lambda **kwargs: passing)
    assert build.main(["--execute", "--report", str(report), "--summary"]) == 0
    assert "platform_oci_image_build=pass" in capsys.readouterr().out

    monkeypatch.setattr(
        build,
        "run_platform_image_build",
        lambda **kwargs: {"status": "FAIL", "issues": ["bad"]},
    )
    assert build.main(["--execute", "--report", str(report)]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out

    skipped_report = tmp_path / "skipped.json"
    monkeypatch.setattr(
        build,
        "run_platform_image_build",
        lambda **kwargs: {"status": "SKIPPED"},
    )
    assert build.main(["--report", str(skipped_report)]) == 0
    assert not skipped_report.exists()
