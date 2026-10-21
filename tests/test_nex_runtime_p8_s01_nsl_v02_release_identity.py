from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import admit_nsl_wheel as command
import pytest
from nex_runtime.nsl_package_admission import (
    NslPackageAdmissionError,
    NslWheelInspection,
)
from nex_runtime.nsl_release_identity import (
    NSL_RELEASE_IDENTITY_SCHEMA_VERSION,
    build_nsl_release_identity,
)

REVISION = command.P8_V02_SOURCE_REVISION
TREE = command.P8_V02_SOURCE_TREE
WHEEL_DIGEST = command.P8_V02_WHEEL_SHA256


def _admission() -> dict[str, object]:
    return {
        "schema_version": "nsl_wheel_admission.v1",
        "status": "PASS",
        "distribution": "nex-skill-language",
        "package_version": "0.2.0",
        "source_revision": REVISION,
        "source_tree_clean": True,
        "wheel_filename": "nex_skill_language-0.2.0-py3-none-any.whl",
        "wheel_sha256": WHEEL_DIGEST,
        "wheel_size": 194308,
        "requires_python": ">=3.12",
        "requirements": ["cryptography<47.0.0,>=46.0.7"],
        "record_file_count": 70,
        "record_integrity_count": 69,
        "platform_lock_sha256": "sha256:" + "b" * 64,
        "public_api_symbols": list(command.P8_V02_PUBLIC_API_SYMBOLS),
    }


def _identity(
    admission: dict[str, object] | None = None, **overrides: object
) -> dict[str, object]:
    arguments = {
        "repository": command.REPOSITORY,
        "source_tree": TREE,
        "expected_source_revision": REVISION,
        "expected_source_tree": TREE,
        "expected_wheel_sha256": WHEEL_DIGEST,
        "certification_reference": command.P8_V02_CERTIFICATION_REFERENCE,
    }
    arguments.update(overrides)
    return build_nsl_release_identity(admission or _admission(), **arguments)


def test_release_identity_closes_exact_v02_source_wheel_and_api() -> None:
    identity = _identity()

    assert identity == {
        "schema_version": NSL_RELEASE_IDENTITY_SCHEMA_VERSION,
        "status": "PASS",
        "repository": "nurigitdev/2608_nsl",
        "source_revision": REVISION,
        "source_tree": TREE,
        "distribution": "nex-skill-language",
        "package_version": "0.2.0",
        "wheel_filename": "nex_skill_language-0.2.0-py3-none-any.whl",
        "wheel_sha256": WHEEL_DIGEST,
        "wheel_size": 194308,
        "requires_python": ">=3.12",
        "requirements": ["cryptography<47.0.0,>=46.0.7"],
        "public_api_symbols": list(command.P8_V02_PUBLIC_API_SYMBOLS),
        "platform_lock_sha256": "sha256:" + "b" * 64,
        "certification_reference": command.P8_V02_CERTIFICATION_REFERENCE,
        "record_file_count": 70,
        "record_integrity_count": 69,
    }


@pytest.mark.parametrize(
    ("admission_change", "argument_change", "message"),
    [
        ({"status": "FAIL"}, {}, "passing wheel admission"),
        ({}, {"repository": "other/repository"}, "repository"),
        ({"source_revision": "bad"}, {}, "source revision"),
        ({}, {"source_tree": "bad"}, "source tree"),
        ({}, {"expected_source_revision": "bad"}, "expected NSL source revision"),
        (
            {},
            {"expected_source_revision": "c" * 40},
            "source revision does not match",
        ),
        ({}, {"expected_source_tree": "bad"}, "expected NSL source tree"),
        ({}, {"expected_source_tree": "c" * 40}, "source tree does not match"),
        ({}, {"expected_wheel_sha256": "bad"}, "expected NSL wheel digest"),
        (
            {},
            {"expected_wheel_sha256": "sha256:" + "c" * 64},
            "wheel digest does not match",
        ),
        ({"source_tree_clean": False}, {}, "clean source tree"),
        ({}, {"certification_reference": ""}, "certification reference"),
        ({}, {"certification_reference": "x" * 513}, "certification reference"),
        ({"requirements": "invalid"}, {}, "dependency inventory"),
        ({"requirements": [""]}, {}, "dependency inventory"),
        ({"public_api_symbols": []}, {}, "public API inventory"),
        ({"public_api_symbols": ["A", "A"]}, {}, "public API inventory"),
    ],
)
def test_release_identity_fails_closed_on_provenance_drift(
    admission_change: dict[str, object],
    argument_change: dict[str, object],
    message: str,
) -> None:
    admission = deepcopy(_admission())
    admission.update(admission_change)

    with pytest.raises(NslPackageAdmissionError, match=message):
        _identity(admission, **argument_change)


def test_v02_cli_profile_selects_identity_only_boundaries(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    captured: dict[str, object] = {}

    def fake_run(**kwargs: object) -> dict[str, str]:
        captured.update(kwargs)
        return {"status": "PASS"}

    monkeypatch.setattr(command, "run_nsl_wheel_admission", fake_run)
    monkeypatch.setattr(
        command.sys,
        "argv",
        ["admit_nsl_wheel.py", "--release-profile", "v0.2", "--identity-only"],
    )

    assert command.main() == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    assert captured["lock"] is None
    assert captured["expected_version"] == "0.2.0"
    assert captured["expected_source_revision"] == REVISION
    assert captured["expected_source_tree"] == TREE
    assert captured["expected_wheel_sha256"] == WHEEL_DIGEST
    assert captured["public_api_symbols"] == command.P8_V02_PUBLIC_API_SYMBOLS
    assert captured["release_slice"] == "P8-S01"
    assert captured["output"] == command.P8_V02_OUTPUT
    assert captured["report"] == command.P8_V02_REPORT
    assert captured["source"] == Path("/home/tprover/2608_nsl")


def test_v02_runner_preserves_identity_schema_for_skip_and_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    arguments = {
        "execute": True,
        "source": tmp_path,
        "report": tmp_path / "identity.json",
        "lock": None,
        "expected_source_tree": TREE,
    }
    skipped = command.run_nsl_wheel_admission({}, **arguments)
    assert skipped["schema_version"] == "p8_nsl_release_identity_evidence.v1"

    monkeypatch.setattr(
        command,
        "_execute",
        lambda **kwargs: (_ for _ in ()).throw(ValueError("identity drift")),
    )
    failed = command.run_nsl_wheel_admission(
        {command.EXECUTION_ENV: "1"}, **arguments
    )
    assert failed["schema_version"] == "p8_nsl_release_identity_evidence.v1"
    assert failed["issues"] == ["identity drift"]
    assert json.loads(arguments["report"].read_text(encoding="utf-8")) == failed


def test_execute_builds_exact_v02_identity_without_lock(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "platform"
    root.mkdir()
    (root / "requirements.txt").write_text(
        "cryptography>=46,<47\n", encoding="utf-8"
    )
    wheel_name = "nex_skill_language-0.2.0-py3-none-any.whl"
    inspection = NslWheelInspection(
        distribution="nex-skill-language",
        version="0.2.0",
        requires_python=">=3.12",
        requirements=("cryptography<47.0.0,>=46.0.7",),
        wheel_filename=wheel_name,
        wheel_sha256=WHEEL_DIGEST,
        wheel_size=194308,
        record_file_count=70,
        record_integrity_count=69,
    )
    lock_record = SimpleNamespace(lock_id="python-production", sha256="b" * 64)

    monkeypatch.setattr(command, "ROOT", root)
    monkeypatch.setattr(
        command, "_git_metadata", lambda source: (REVISION, True, "1")
    )
    monkeypatch.setattr(
        command, "_materialize_git_archive", lambda source, destination: None
    )

    def fake_build(source, output, uv_bin, epoch, *, release_tool=False):
        del source, uv_bin, epoch
        assert release_tool is True
        output.mkdir(parents=True)
        wheel = output / wheel_name
        wheel.write_bytes(b"certified-wheel")
        return wheel

    monkeypatch.setattr(command, "_build_wheel", fake_build)
    monkeypatch.setattr(command, "inspect_nsl_wheel", lambda path: inspection)
    monkeypatch.setattr(
        command,
        "_install_and_import",
        lambda wheel, target, symbols: command.P8_V02_PUBLIC_API_SYMBOLS,
    )
    monkeypatch.setattr(
        command,
        "build_deployment_build_inputs",
        lambda root: SimpleNamespace(locks=(lock_record,)),
    )
    monkeypatch.setattr(
        command,
        "python_lock_package_versions",
        lambda path: {"cryptography": "46.0.7"},
    )
    monkeypatch.setattr(command, "installed_version", lambda name: "46.0.7")
    monkeypatch.setattr(command, "_capture", lambda *args, **kwargs: TREE + "\n")

    arguments = {
        "source": tmp_path / "nsl",
        "output": root / "reports" / "wheel",
        "lock": None,
        "write_lock": False,
        "uv_bin": "uv",
        "expected_version": "0.2.0",
        "public_api_symbols": command.P8_V02_PUBLIC_API_SYMBOLS,
        "expected_source_revision": REVISION,
        "expected_source_tree": TREE,
        "expected_wheel_sha256": WHEEL_DIGEST,
        "certification_reference": command.P8_V02_CERTIFICATION_REFERENCE,
        "release_slice": "P8-S01",
    }
    evidence = command._execute(**arguments)

    assert evidence["schema_version"] == "p8_nsl_release_identity_evidence.v1"
    assert evidence["release_identity"] == _identity()
    assert evidence["wheel_lock"] is None
    assert evidence["decision"]["runtime_profile_activated"] is False

    arguments["certification_reference"] = None
    with pytest.raises(command.NslWheelBuildError, match="identity is incomplete"):
        command._execute(**arguments)

    arguments["certification_reference"] = command.P8_V02_CERTIFICATION_REFERENCE
    lock = root / "deployment" / "locks" / "nsl-v0.2-wheel.json"
    arguments.update(lock=lock, write_lock=True, release_slice="P8-S02")
    locked = command._execute(**arguments)
    assert locked["schema_version"] == "p8_nsl_v02_wheel_lock_evidence.v1"
    assert locked["decision"]["wheel_admitted"] is True
    assert json.loads(lock.read_text(encoding="utf-8"))["source_tree"] == TREE

    arguments["write_lock"] = False
    assert command._execute(**arguments) == locked

    persisted = json.loads(lock.read_text(encoding="utf-8"))
    persisted["wheel_sha256"] = "sha256:" + "c" * 64
    lock.write_text(json.dumps(persisted), encoding="utf-8")
    with pytest.raises(NslPackageAdmissionError, match="does not match"):
        command._execute(**arguments)
