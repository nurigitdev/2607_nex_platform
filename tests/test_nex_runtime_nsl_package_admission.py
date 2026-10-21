from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import shutil
import subprocess
import tarfile
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZIP_DEFLATED, ZipFile

import admit_nsl_wheel as command
import nex_runtime.nsl_package_admission as package_admission
import pytest
from nex_runtime.nsl_package_admission import (
    NslPackageAdmissionError,
    build_nsl_wheel_admission,
    inspect_nsl_wheel,
    nsl_wheel_lock_projection,
    validate_nsl_wheel_lock,
)

REVISION = "a" * 40
LOCK_DIGEST = "sha256:" + "b" * 64
PUBLIC_API = (
    "RuntimeEngine",
    "RuntimeResultEnvelope",
    "SkillExecutionJob",
    "SkillExecutionWorker",
)


def test_valid_wheel_inspection_admission_and_lock(tmp_path: Path) -> None:
    wheel = _wheel(tmp_path)

    inspection = inspect_nsl_wheel(wheel)
    admission = _admit(inspection)
    lock = nsl_wheel_lock_projection(admission, repository="nurigitdev/2608_nsl")

    assert inspection.distribution == "nex-skill-language"
    assert inspection.version == "0.1.0"
    assert inspection.record_integrity_count == inspection.record_file_count - 1
    assert inspection.wheel_sha256.startswith("sha256:")
    assert admission["decision"] == {
        "dependency_compatible": True,
        "wheel_integrity_verified": True,
        "public_api_imported_from_wheel": True,
        "in_process_profile_admissible": True,
    }
    validate_nsl_wheel_lock(admission, lock, repository="nurigitdev/2608_nsl")
    with_extra_dependency = replace(
        inspection,
        requirements=(
            *inspection.requirements,
            "typing-extensions>=4",
        ),
    )
    assert _admit(with_extra_dependency)["status"] == "PASS"

    changed = dict(lock)
    changed["wheel_sha256"] = "sha256:" + "c" * 64
    with pytest.raises(NslPackageAdmissionError, match="does not match"):
        validate_nsl_wheel_lock(admission, changed, repository="nurigitdev/2608_nsl")
    changed = dict(lock)
    changed["repository"] = "other/repository"
    with pytest.raises(NslPackageAdmissionError, match="does not match"):
        validate_nsl_wheel_lock(admission, changed, repository="nurigitdev/2608_nsl")
    with pytest.raises(NslPackageAdmissionError, match="passing admission"):
        nsl_wheel_lock_projection({"status": "FAIL"}, repository="nurigitdev/2608_nsl")


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"distribution": "other"}, "distribution"),
        ({"version": "0.2.0"}, "package version"),
        ({"requires_python": ">=3.11"}, "Python requirement"),
        ({"requirements": ()}, "one cryptography"),
        ({"requirements": ("cryptography>=49,<50",)}, "outside NSL"),
    ],
)
def test_admission_fails_closed_for_metadata_drift(
    tmp_path: Path, change: dict[str, object], message: str
) -> None:
    inspection = inspect_nsl_wheel(_wheel(tmp_path))
    changed = replace(inspection, **change)

    with pytest.raises(NslPackageAdmissionError, match=message):
        _admit(changed)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"source_revision": "bad"}, "source revision"),
        ({"source_tree_clean": False}, "not clean"),
        (
            {"platform_cryptography_requirement": "not a requirement"},
            "invalid Platform",
        ),
        (
            {"platform_cryptography_requirement": "cryptography>=49,<50"},
            "outside Platform",
        ),
        ({"locked_cryptography_version": "bad"}, "invalid locked"),
        ({"platform_lock_sha256": "bad"}, "lock digest"),
        ({"public_api_symbols": ()}, "import evidence"),
    ],
)
def test_admission_fails_closed_for_source_and_platform_drift(
    tmp_path: Path, overrides: dict[str, object], message: str
) -> None:
    inspection = inspect_nsl_wheel(_wheel(tmp_path))
    arguments = {
        "source_revision": REVISION,
        "source_tree_clean": True,
        "expected_version": "0.1.0",
        "platform_cryptography_requirement": "cryptography>=46,<47",
        "locked_cryptography_version": "46.0.7",
        "platform_lock_sha256": LOCK_DIGEST,
        "public_api_symbols": PUBLIC_API,
    }
    arguments.update(overrides)

    with pytest.raises(NslPackageAdmissionError, match=message):
        build_nsl_wheel_admission(inspection, **arguments)


def test_wheel_inspection_rejects_invalid_archives(tmp_path: Path) -> None:
    missing = tmp_path / "missing.whl"
    with pytest.raises(NslPackageAdmissionError, match="missing"):
        inspect_nsl_wheel(missing)

    invalid = tmp_path / "invalid.whl"
    invalid.write_bytes(b"not-a-zip")
    with pytest.raises(NslPackageAdmissionError, match="filename"):
        inspect_nsl_wheel(invalid)

    broken_archive = tmp_path / "nex_skill_language-0.1.0-py3-none-any.whl"
    broken_archive.write_bytes(b"not-a-zip")
    with pytest.raises(NslPackageAdmissionError, match="archive"):
        inspect_nsl_wheel(broken_archive)

    unsafe = _wheel(tmp_path, extra_member="../escape")
    with pytest.raises(NslPackageAdmissionError, match="unsafe path"):
        inspect_nsl_wheel(unsafe)


def test_wheel_inspection_rejects_record_and_metadata_drift(tmp_path: Path) -> None:
    bad_record = _wheel(tmp_path / "record", corrupt_record=True)
    with pytest.raises(NslPackageAdmissionError, match="digest mismatch"):
        inspect_nsl_wheel(bad_record)

    no_api = _wheel(tmp_path / "api", include_api=False)
    with pytest.raises(NslPackageAdmissionError, match="public API"):
        inspect_nsl_wheel(no_api)

    bad_requirement = _wheel(
        tmp_path / "requirement", requirement="not a requirement @"
    )
    with pytest.raises(NslPackageAdmissionError, match="invalid dependency"):
        inspect_nsl_wheel(bad_requirement)

    wrong_name = _wheel(tmp_path / "name", distribution="other")
    with pytest.raises(NslPackageAdmissionError, match="name does not match"):
        inspect_nsl_wheel(wrong_name)

    wrong_version = _wheel(tmp_path / "version", version="0.2.0")
    with pytest.raises(NslPackageAdmissionError, match="version does not match"):
        inspect_nsl_wheel(wrong_version)

    with pytest.raises(NslPackageAdmissionError, match="member inventory"):
        package_admission._validate_member_paths(())
    with pytest.raises(NslPackageAdmissionError, match="requires one"):
        package_admission._single_member((), ".dist-info/METADATA")


def test_protected_command_skip_failure_and_pass_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    assert command.run_nsl_wheel_admission({}, execute=True)["status"] == "SKIPPED"

    report = tmp_path / "report.json"
    monkeypatch.setattr(
        command,
        "_execute",
        lambda **kwargs: {"status": "PASS", "source": str(kwargs["source"])},
    )
    passed = command.run_nsl_wheel_admission(
        {command.EXECUTION_ENV: "1"},
        execute=True,
        source=tmp_path,
        report=report,
    )
    assert passed["status"] == "PASS"
    assert json.loads(report.read_text(encoding="utf-8")) == passed

    monkeypatch.setattr(
        command,
        "_execute",
        lambda **kwargs: (_ for _ in ()).throw(ValueError("blocked")),
    )
    failed = command.run_nsl_wheel_admission(
        {command.EXECUTION_ENV: "1"},
        execute=True,
        source=tmp_path,
        report=report,
    )
    assert failed["status"] == "FAIL"
    assert failed["issues"] == ["blocked"]
    assert failed["decision"]["in_process_profile_admissible"] is False


def test_requirement_reader_requires_one_named_package(tmp_path: Path) -> None:
    requirements = tmp_path / "requirements.txt"
    requirements.write_text(
        "# comment\ncryptography>=46,<47\npytest>=8,<9\n", encoding="utf-8"
    )
    assert command._requirement_from_file(requirements, "cryptography") == (
        "cryptography>=46,<47"
    )

    requirements.write_text("pytest>=8,<9\n", encoding="utf-8")
    with pytest.raises(command.NslWheelBuildError, match="expected one"):
        command._requirement_from_file(requirements, "cryptography")

    requirements.write_text("not a requirement @\n", encoding="utf-8")
    with pytest.raises(command.NslWheelBuildError, match="invalid entry"):
        command._requirement_from_file(requirements, "cryptography")


def test_execute_builds_reproducible_wheel_and_revalidates_lock(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "platform"
    root.mkdir()
    (root / "requirements.txt").write_text("cryptography>=46,<47\n", encoding="utf-8")
    template = _wheel(tmp_path / "template")
    lock_record = SimpleNamespace(lock_id="python-production", sha256="b" * 64)

    monkeypatch.setattr(command, "ROOT", root)
    monkeypatch.setattr(command, "_git_metadata", lambda source: (REVISION, True, "1"))
    monkeypatch.setattr(
        command, "_materialize_git_archive", lambda source, destination: None
    )

    def fake_build(source, output, uv_bin, epoch, *, release_tool=False):
        del source, uv_bin, epoch
        assert release_tool is False
        output.mkdir(parents=True)
        wheel = output / template.name
        shutil.copyfile(template, wheel)
        return wheel

    monkeypatch.setattr(command, "_build_wheel", fake_build)
    monkeypatch.setattr(
        command, "_install_and_import", lambda wheel, target, symbols: PUBLIC_API
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

    lock = root / "deployment" / "locks" / "nsl.json"
    output = root / "reports" / "wheel"
    first = command._execute(
        source=tmp_path / "nsl",
        output=output,
        lock=lock,
        write_lock=True,
        uv_bin="uv",
    )
    second = command._execute(
        source=tmp_path / "nsl",
        output=output,
        lock=lock,
        write_lock=False,
        uv_bin="uv",
    )

    assert first == second
    assert first["status"] == "PASS"
    assert first["reproducible_build_count"] == 2
    assert json.loads(lock.read_text(encoding="utf-8"))["source_revision"] == REVISION

    lock.unlink()
    with pytest.raises(command.NslWheelBuildError, match="wheel lock is missing"):
        command._execute(
            source=tmp_path / "nsl",
            output=output,
            lock=lock,
            write_lock=False,
            uv_bin="uv",
        )

    monkeypatch.setattr(command, "python_lock_package_versions", lambda path: {})
    with pytest.raises(command.NslWheelBuildError, match="contain cryptography"):
        command._execute(
            source=tmp_path / "nsl",
            output=output,
            lock=lock,
            write_lock=True,
            uv_bin="uv",
        )

    monkeypatch.setattr(
        command,
        "python_lock_package_versions",
        lambda path: {"cryptography": "46.0.7"},
    )
    monkeypatch.setattr(command, "installed_version", lambda name: "49.0.0")
    with pytest.raises(command.NslWheelBuildError, match="does not match"):
        command._execute(
            source=tmp_path / "nsl",
            output=output,
            lock=lock,
            write_lock=True,
            uv_bin="uv",
        )

    real_inspection = inspect_nsl_wheel
    digests = iter(("sha256:" + "1" * 64, "sha256:" + "2" * 64))

    def drifting_inspection(path):
        return replace(real_inspection(path), wheel_sha256=next(digests))

    monkeypatch.setattr(command, "inspect_nsl_wheel", drifting_inspection)
    with pytest.raises(command.NslWheelBuildError, match="not reproducible"):
        command._execute(
            source=tmp_path / "nsl",
            output=output,
            lock=lock,
            write_lock=True,
            uv_bin="uv",
        )


def test_execute_fails_closed_for_dirty_source(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(command, "_git_metadata", lambda source: (REVISION, False, "1"))
    with pytest.raises(command.NslWheelBuildError, match="clean source"):
        command._execute(
            source=tmp_path,
            output=tmp_path / "output",
            lock=tmp_path / "lock.json",
            write_lock=False,
            uv_bin="uv",
        )


def test_git_metadata_and_archive_helpers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    outputs = iter((REVISION + "\n", "", "123\n"))
    monkeypatch.setattr(command, "_capture", lambda *args, **kwargs: next(outputs))
    assert command._git_metadata(tmp_path) == (REVISION, True, "123")

    tar_buffer = io.BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode="w:") as archive:
        payload = b"content"
        info = tarfile.TarInfo("pyproject.toml")
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))
    completed = subprocess.CompletedProcess(
        ("git", "archive"), 0, stdout=tar_buffer.getvalue(), stderr=b""
    )
    monkeypatch.setattr(command.subprocess, "run", lambda *args, **kwargs: completed)
    destination = tmp_path / "archive"
    command._materialize_git_archive(tmp_path, destination)
    assert (destination / "pyproject.toml").read_bytes() == b"content"

    failed = subprocess.CompletedProcess(
        ("git", "archive"), 1, stdout=b"", stderr=b"archive failed"
    )
    monkeypatch.setattr(command.subprocess, "run", lambda *args, **kwargs: failed)
    with pytest.raises(command.NslWheelBuildError, match="archive failed"):
        command._materialize_git_archive(tmp_path, tmp_path / "failed")


def test_build_and_install_helpers_contain_subprocess_failures(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def successful_build(*args, **kwargs):
        output = Path(args[0][args[0].index("--out-dir") + 1])
        _wheel(output)
        assert kwargs["env"]["SOURCE_DATE_EPOCH"] == "123"
        assert kwargs["env"]["UV_CACHE_DIR"] == "/tmp/nex-platform-uv-cache"
        return subprocess.CompletedProcess(args[0], 0, "built", "")

    monkeypatch.setattr(command.subprocess, "run", successful_build)
    wheel = command._build_wheel(tmp_path, tmp_path / "built", "uv", "123")
    assert wheel.suffix == ".whl"

    def successful_release(*args, **kwargs):
        output = Path(args[0][args[0].index("--output-dir") + 1])
        _wheel(output)
        assert kwargs["cwd"] == tmp_path
        assert "SOURCE_DATE_EPOCH" not in kwargs["env"]
        assert "tools/wheel_release.py" in args[0]
        return subprocess.CompletedProcess(args[0], 0, "released", "")

    monkeypatch.setattr(command.subprocess, "run", successful_release)
    released = command._build_wheel(
        tmp_path,
        tmp_path / "released",
        "uv",
        "123",
        release_tool=True,
    )
    assert released.suffix == ".whl"

    failed = subprocess.CompletedProcess(("uv",), 1, "", "build failed")
    monkeypatch.setattr(command.subprocess, "run", lambda *args, **kwargs: failed)
    with pytest.raises(command.NslWheelBuildError, match="build failed"):
        command._build_wheel(tmp_path, tmp_path / "failed-build", "uv", "123")

    built_nothing = subprocess.CompletedProcess(("uv",), 0, "", "")
    monkeypatch.setattr(
        command.subprocess, "run", lambda *args, **kwargs: built_nothing
    )
    with pytest.raises(command.NslWheelBuildError, match="exactly one wheel"):
        command._build_wheel(tmp_path, tmp_path / "empty-build", "uv", "123")

    calls = iter(
        (
            subprocess.CompletedProcess(("pip",), 0, "", ""),
            subprocess.CompletedProcess(
                ("python",), 0, json.dumps(list(PUBLIC_API)), ""
            ),
        )
    )
    monkeypatch.setattr(command.subprocess, "run", lambda *args, **kwargs: next(calls))
    assert command._install_and_import(wheel, tmp_path / "target") == PUBLIC_API

    install_failed = subprocess.CompletedProcess(("pip",), 1, "", "install failed")
    monkeypatch.setattr(
        command.subprocess, "run", lambda *args, **kwargs: install_failed
    )
    with pytest.raises(command.NslWheelBuildError, match="install failed"):
        command._install_and_import(wheel, tmp_path / "target")

    import_calls = iter(
        (
            subprocess.CompletedProcess(("pip",), 0, "", ""),
            subprocess.CompletedProcess(("python",), 1, "", "import failed"),
        )
    )
    monkeypatch.setattr(
        command.subprocess, "run", lambda *args, **kwargs: next(import_calls)
    )
    with pytest.raises(command.NslWheelBuildError, match="import failed"):
        command._install_and_import(wheel, tmp_path / "target")


def test_capture_and_main_exit_codes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    completed = subprocess.CompletedProcess(("cmd",), 0, "ok\n", "")
    monkeypatch.setattr(command.subprocess, "run", lambda *args, **kwargs: completed)
    assert command._capture(("cmd",), cwd=tmp_path, operation="capture") == "ok\n"

    failed = subprocess.CompletedProcess(("cmd",), 1, "", "failed")
    monkeypatch.setattr(command.subprocess, "run", lambda *args, **kwargs: failed)
    with pytest.raises(command.NslWheelBuildError, match="capture failed"):
        command._capture(("cmd",), cwd=tmp_path, operation="capture")

    monkeypatch.setattr(command.sys, "argv", ["admit_nsl_wheel.py"])
    monkeypatch.setattr(
        command,
        "run_nsl_wheel_admission",
        lambda **kwargs: {"status": "SKIPPED"},
    )
    assert command.main() == 0
    assert json.loads(capsys.readouterr().out)["status"] == "SKIPPED"


def _admit(inspection):
    return build_nsl_wheel_admission(
        inspection,
        source_revision=REVISION,
        source_tree_clean=True,
        expected_version="0.1.0",
        platform_cryptography_requirement="cryptography>=46,<47",
        locked_cryptography_version="46.0.7",
        platform_lock_sha256=LOCK_DIGEST,
        public_api_symbols=PUBLIC_API,
    )


def _wheel(
    root: Path,
    *,
    requirement: str = "cryptography>=46.0.0,<50.0.0",
    distribution: str = "nex-skill-language",
    version: str = "0.1.0",
    include_api: bool = True,
    corrupt_record: bool = False,
    extra_member: str | None = None,
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    wheel = root / "nex_skill_language-0.1.0-py3-none-any.whl"
    dist_info = "nex_skill_language-0.1.0.dist-info"
    files = {
        "nsl/__init__.py": b"",
        f"{dist_info}/METADATA": (
            "Metadata-Version: 2.4\n"
            f"Name: {distribution}\n"
            f"Version: {version}\n"
            "Requires-Python: >=3.12\n"
            f"Requires-Dist: {requirement}\n\n"
        ).encode(),
        f"{dist_info}/WHEEL": (
            b"Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\n"
            b"Tag: py3-none-any\n\n"
        ),
    }
    if include_api:
        files["nsl/api/__init__.py"] = b"class RuntimeEngine: pass\n"
    if extra_member is not None:
        files[extra_member] = b"unsafe"
    record_name = f"{dist_info}/RECORD"
    stream = io.StringIO()
    writer = csv.writer(stream, lineterminator="\n")
    for name, payload in files.items():
        digest = base64.urlsafe_b64encode(hashlib.sha256(payload).digest()).rstrip(b"=")
        if corrupt_record and name == "nsl/__init__.py":
            digest = b"bad"
        writer.writerow((name, f"sha256={digest.decode()}", len(payload)))
    writer.writerow((record_name, "", ""))
    with ZipFile(wheel, "w", compression=ZIP_DEFLATED) as archive:
        for name, payload in files.items():
            archive.writestr(name, payload)
        archive.writestr(record_name, stream.getvalue().encode())
    return wheel
