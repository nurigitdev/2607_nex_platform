from __future__ import annotations

import json

import admit_nsl_wheel as command
import pytest
from nex_runtime.nsl_package_admission import NslPackageAdmissionError
from nex_runtime.nsl_release_identity import build_nsl_release_identity
from nex_runtime.nsl_v02_wheel_lock import (
    NSL_V02_WHEEL_LOCK_SCHEMA_VERSION,
    normalize_nsl_v02_wheel_lock,
    nsl_v02_wheel_lock_projection,
    validate_nsl_v02_wheel_lock,
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
        "platform_cryptography_requirement": "cryptography<47,>=46",
        "locked_cryptography_version": "46.0.7",
        "platform_lock_sha256": "sha256:" + "b" * 64,
        "public_api_symbols": list(command.P8_V02_PUBLIC_API_SYMBOLS),
    }


def _identity(admission: dict[str, object] | None = None) -> dict[str, object]:
    return build_nsl_release_identity(
        admission or _admission(),
        repository=command.REPOSITORY,
        source_tree=TREE,
        expected_source_revision=REVISION,
        expected_source_tree=TREE,
        expected_wheel_sha256=WHEEL_DIGEST,
        certification_reference=command.P8_V02_CERTIFICATION_REFERENCE,
    )


def _lock() -> dict[str, object]:
    return nsl_v02_wheel_lock_projection(_identity(), _admission())


def test_v02_lock_contains_exact_release_and_platform_dependency_identity() -> None:
    lock = _lock()

    assert lock["schema_version"] == NSL_V02_WHEEL_LOCK_SCHEMA_VERSION
    assert lock["repository"] == "nurigitdev/2608_nsl"
    assert lock["source_revision"] == REVISION
    assert lock["source_tree"] == TREE
    assert lock["wheel_sha256"] == WHEEL_DIGEST
    assert lock["package_version"] == "0.2.0"
    assert lock["locked_cryptography_version"] == "46.0.7"
    assert lock["public_api_symbols"] == list(command.P8_V02_PUBLIC_API_SYMBOLS)
    assert normalize_nsl_v02_wheel_lock(lock) == lock
    validate_nsl_v02_wheel_lock(_identity(), _admission(), lock)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_revision", "c" * 40),
        ("source_tree", "d" * 40),
        ("wheel_filename", "nex_skill_language-0.2.1-py3-none-any.whl"),
        ("wheel_sha256", "sha256:" + "e" * 64),
        ("package_version", "0.2.1"),
        ("requirements", ["cryptography>=46.0.8,<47"]),
        ("public_api_symbols", list(command.P8_V02_PUBLIC_API_SYMBOLS[:-1])),
    ],
)
def test_v02_lock_fails_closed_on_required_release_drift(
    field: str, value: object
) -> None:
    lock = _lock()
    lock[field] = value

    with pytest.raises(NslPackageAdmissionError):
        validate_nsl_v02_wheel_lock(_identity(), _admission(), lock)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("schema_version", "other", "schema"),
        ("repository", "other/repository", "repository"),
        ("distribution", "other", "distribution"),
        ("package_version", "bad", "version"),
        ("source_revision", "bad", "source_revision"),
        ("source_tree", "bad", "source_tree"),
        ("wheel_sha256", "bad", "wheel_sha256"),
        ("platform_lock_sha256", "bad", "platform_lock_sha256"),
        ("wheel_filename", "not-a-wheel", "filename"),
        ("wheel_filename", "../nex_skill_language-0.2.0-py3-none-any.whl", "filename"),
        ("wheel_filename", "other-0.2.0-py3-none-any.whl", "filename"),
        ("requires_python", ">=3.11", "Python requirement"),
        ("requirements", [], "dependency inventory"),
        ("requirements", ["not a requirement @"], "dependency inventory"),
        ("requirements", ["pytest>=8"], "one cryptography"),
        (
            "requirements",
            ["cryptography>=46", "cryptography<47"],
            "one cryptography",
        ),
        ("platform_cryptography_requirement", "pytest>=8", "must be cryptography"),
        ("locked_cryptography_version", "bad", "locked cryptography"),
        ("locked_cryptography_version", "45.0.0", "incompatible"),
        ("public_api_symbols", [], "public API"),
        ("public_api_symbols", ["A", "A"], "public API"),
        ("wheel_size", 0, "wheel_size"),
        ("record_file_count", True, "record_file_count"),
        ("record_integrity_count", 68, "RECORD counts"),
        ("certification_reference", "wrong", "certification"),
    ],
)
def test_v02_lock_shape_rejects_invalid_values(
    field: str, value: object, message: str
) -> None:
    lock = _lock()
    lock[field] = value

    with pytest.raises(NslPackageAdmissionError, match=message):
        normalize_nsl_v02_wheel_lock(lock)


def test_v02_lock_requires_exact_fields_and_passing_inputs() -> None:
    lock = _lock()
    lock.pop("source_tree")
    with pytest.raises(NslPackageAdmissionError, match="fields"):
        normalize_nsl_v02_wheel_lock(lock)

    identity = _identity()
    identity["status"] = "FAIL"
    with pytest.raises(NslPackageAdmissionError, match="release identity"):
        nsl_v02_wheel_lock_projection(identity, _admission())

    admission = _admission()
    admission["status"] = "FAIL"
    with pytest.raises(NslPackageAdmissionError, match="wheel admission"):
        nsl_v02_wheel_lock_projection(_identity(), admission)

    identity = _identity()
    identity.pop("source_tree")
    with pytest.raises(NslPackageAdmissionError, match="incomplete"):
        nsl_v02_wheel_lock_projection(identity, _admission())

    identity = _identity()
    identity["wheel_size"] = 1
    with pytest.raises(NslPackageAdmissionError, match="disagree on wheel_size"):
        nsl_v02_wheel_lock_projection(identity, _admission())


def test_v02_cli_selects_committed_lock_and_s02_evidence(
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
        ["admit_nsl_wheel.py", "--release-profile", "v0.2", "--write-lock"],
    )

    assert command.main() == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"
    assert captured["lock"] == command.P8_V02_LOCK
    assert captured["report"] == command.P8_V02_LOCK_REPORT
    assert captured["write_lock"] is True
    assert captured["release_slice"] == "P8-S02"


def test_v02_lock_runner_preserves_lock_evidence_schema(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setattr(
        command,
        "_execute",
        lambda **kwargs: (_ for _ in ()).throw(ValueError("lock drift")),
    )
    result = command.run_nsl_wheel_admission(
        {command.EXECUTION_ENV: "1"},
        execute=True,
        source=tmp_path,
        report=tmp_path / "lock.json",
        lock=tmp_path / "nsl-v0.2-wheel.json",
        expected_source_tree=TREE,
    )

    assert result["schema_version"] == "p8_nsl_v02_wheel_lock_evidence.v1"
    assert result["status"] == "FAIL"
