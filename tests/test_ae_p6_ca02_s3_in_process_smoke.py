from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts/smoke"))

import run_p6_ca02_s3_in_process_smoke as smoke


def _record(attempt_no: int) -> dict[str, Any]:
    request = smoke._example("p6-golden-skill-execution-request-v1.json")
    return {
        "attempt_no": attempt_no,
        "backend_profile": "NSL_V01_IN_PROCESS",
        "isolation_status": "COMPLETED",
        "runtime_status": "COMPLETED",
        "nsl_execution_id": request["nsl_execution_id"],
        "business_operation_id": request["business_operation_id"],
        "progress_events": [
            {"state": state}
            for state in ("STARTED", "SKILL_RESOLVED", "RUNNING", "COMPLETED")
        ],
        "evidence_refs": ["NSL:SNAPSHOT:test"],
    }


class _Factory:
    def __init__(self, *_args: object) -> None:
        self.session_count = 0


class _Adapter:
    backend_profile = "NSL_V01_IN_PROCESS"
    timeout_semantics = "NSL_COOPERATIVE_DEADLINE"

    def __init__(self, factory: _Factory) -> None:
        self.factory = factory

    def execute(self, **values: Any) -> dict[str, Any]:
        self.factory.session_count += 1
        return _record(values["attempt_no"])


def test_smoke_is_protected_and_requires_source() -> None:
    skipped = smoke.run_p6_ca02_s3_in_process_smoke({})
    missing = smoke.run_p6_ca02_s3_in_process_smoke({smoke.SMOKE_ENV: "1"})

    assert skipped["status"] == "SKIPPED"
    assert skipped["actual_installed_wheel"] is False
    assert missing["failure_code"] == "nsl_source_missing"


def test_smoke_combines_package_and_execution_evidence(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(smoke, "_InstalledWheelWorkerFactory", _Factory)
    monkeypatch.setattr(
        smoke,
        "build_v01_in_process_backend",
        lambda factory: _Adapter(factory),
    )
    monkeypatch.setattr(
        smoke,
        "_installed_package_evidence",
        lambda *_args: {
            "wheel_sha256": "sha256:290a202f540ec98291842e9281a28288cc7ac112525b6c0f02c10b8721aef21f",
            "package_version": "0.1.0",
            "cryptography_version": "46.0.7",
            "public_api_complete": True,
            "runtime_import_is_not_checkout": True,
        },
    )

    evidence = smoke.run_p6_ca02_s3_in_process_smoke(
        {smoke.SMOKE_ENV: "1", smoke.NSL_SOURCE_ENV: str(tmp_path)}
    )

    assert evidence["status"] == "PASS"
    assert evidence["actual_installed_wheel"] is True
    assert evidence["checks_passed"] == evidence["checks_total"] == 10
    assert evidence["session_count"] == 2
    assert evidence["remote_provider_required"] is False
    assert "p6_ca02_s3_in_process=pass" in smoke.summary_line(evidence)


def test_smoke_reports_failed_check_and_redacts_execution_boundary(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(smoke, "_InstalledWheelWorkerFactory", _Factory)
    monkeypatch.setattr(
        smoke,
        "build_v01_in_process_backend",
        lambda factory: _Adapter(factory),
    )
    monkeypatch.setattr(
        smoke,
        "_installed_package_evidence",
        lambda *_args: {
            "wheel_sha256": "sha256:" + "0" * 64,
            "package_version": "0.1.0",
            "cryptography_version": "46.0.7",
            "public_api_complete": True,
            "runtime_import_is_not_checkout": True,
        },
    )
    failed = smoke.run_p6_ca02_s3_in_process_smoke(
        {smoke.SMOKE_ENV: "1", smoke.NSL_SOURCE_ENV: str(tmp_path)}
    )
    assert failed["status"] == "FAIL"
    assert failed["checks"]["admitted_wheel_digest"] is False

    monkeypatch.setattr(
        smoke,
        "_installed_package_evidence",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("contained detail")),
    )
    errored = smoke.run_p6_ca02_s3_in_process_smoke(
        {smoke.SMOKE_ENV: "1", smoke.NSL_SOURCE_ENV: str(tmp_path)}
    )
    assert errored["failure_code"] == "execution_failed"
    assert errored["actual_installed_wheel"] is False


def test_installed_package_evidence_verifies_lock_wheel_and_public_api(
    monkeypatch, tmp_path
) -> None:
    source = tmp_path / "nsl-source"
    source.mkdir()
    wheel = tmp_path / "nex_skill_language-0.1.0-py3-none-any.whl"
    wheel.write_bytes(b"admitted-wheel")
    lock = json.loads(smoke.DEFAULT_LOCK.read_text(encoding="utf-8"))
    lock["wheel_filename"] = wheel.name
    lock["wheel_sha256"] = smoke._sha256_ref(wheel.read_bytes())
    monkeypatch.setattr(smoke, "DEFAULT_WHEEL", wheel)
    monkeypatch.setattr(
        smoke,
        "_git_output",
        lambda _root, *args: (
            lock["source_revision"] if args == ("rev-parse", "HEAD") else ""
        ),
    )
    monkeypatch.setattr(
        smoke.importlib.metadata,
        "version",
        lambda name: "0.1.0" if name == lock["distribution"] else "46.0.7",
    )
    api = SimpleNamespace(__file__=str(tmp_path / "site-packages/nsl/api/__init__.py"))
    for symbol in lock["public_api_symbols"]:
        setattr(api, symbol, object())
    monkeypatch.setitem(sys.modules, "nsl", SimpleNamespace(api=api))

    evidence = smoke._installed_package_evidence(source, lock)

    assert evidence["wheel_sha256"] == lock["wheel_sha256"]
    assert evidence["public_api_complete"] is True
    assert evidence["runtime_import_is_not_checkout"] is True


def test_installed_package_evidence_fails_closed_on_admission_drift(
    monkeypatch, tmp_path
) -> None:
    source = tmp_path / "nsl-source"
    source.mkdir()
    lock = json.loads(smoke.DEFAULT_LOCK.read_text(encoding="utf-8"))

    with_field_drift = {**lock, "unexpected": True}
    try:
        smoke._installed_package_evidence(source, with_field_drift)
    except RuntimeError as exc:
        assert "fields" in str(exc)
    else:
        raise AssertionError("field drift must fail closed")

    wheel = tmp_path / lock["wheel_filename"]
    monkeypatch.setattr(smoke, "DEFAULT_WHEEL", wheel)
    try:
        smoke._installed_package_evidence(source, lock)
    except RuntimeError as exc:
        assert "unavailable" in str(exc)
    else:
        raise AssertionError("missing wheel must fail closed")

    wheel.write_bytes(b"wheel")
    monkeypatch.setattr(smoke, "_git_output", lambda *_args: "wrong-revision")
    try:
        smoke._installed_package_evidence(source, lock)
    except RuntimeError as exc:
        assert "revision" in str(exc)
    else:
        raise AssertionError("revision drift must fail closed")

    monkeypatch.setattr(
        smoke,
        "_git_output",
        lambda _root, *args: (
            lock["source_revision"] if args == ("rev-parse", "HEAD") else "dirty"
        ),
    )
    try:
        smoke._installed_package_evidence(source, lock)
    except RuntimeError as exc:
        assert "clean" in str(exc)
    else:
        raise AssertionError("dirty source must fail closed")


def test_installed_wheel_factory_uses_public_modules_and_fresh_evidence(
    monkeypatch, tmp_path
) -> None:
    artifact = smoke._example("p6-golden-verified-artifact-v1.json")
    source = tmp_path / "nsl-source"
    examples = source / "examples"
    examples.mkdir(parents=True)
    (examples / "project_budget_check.ns").write_text(
        "language NSL fixture;", encoding="utf-8"
    )
    compile_state: dict[str, bytes | None] = {"nso_bytes": b"nso"}

    class Signer:
        key_id = "publisher.p6-golden-1"
        public_key_bytes = b"public"

        def __init__(self, *_args: object) -> None:
            pass

    class Compiler:
        def __init__(self, _catalog: object) -> None:
            pass

        def compile(self, _source: str) -> object:
            return SimpleNamespace(nso_bytes=compile_state["nso_bytes"])

    class Builder:
        def build(self, _items: object, *, signer: object) -> object:
            assert isinstance(signer, Signer)
            return SimpleNamespace(data=b"package")

    verified = SimpleNamespace(
        package_hash=artifact["package_hash"],
        skills=(
            SimpleNamespace(
                skill=SimpleNamespace(semantic_hash=artifact["skill_semantic_hash"])
            ),
        ),
    )

    class Verifier:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def verify(self, data: bytes) -> object:
            assert data == b"package"
            return verified

    class Audit:
        def __init__(self) -> None:
            self.events: list[object] = []

    class Worker:
        def __init__(self, **values: object) -> None:
            self.values = values

    modules = {
        "nsl": SimpleNamespace(__path__=[]),
        "nsl.adapters": SimpleNamespace(__path__=[]),
        "nsl.adapters.ed25519": SimpleNamespace(
            Ed25519PackageSigner=Signer,
            Ed25519TrustStore=lambda _keys: object(),
        ),
        "nsl.api": SimpleNamespace(
            RuntimeEngine=lambda catalog: ("runtime", catalog),
            SkillExecutionWorker=Worker,
            VerifiedPackageSkillResolver=lambda skills: ("resolver", skills),
            WorkerEvidencePolicy=SimpleNamespace(SNAPSHOT_REQUIRED="required"),
        ),
        "nsl.audit": SimpleNamespace(
            InMemoryAuditSink=Audit,
            InMemorySnapshotStore=lambda: object(),
        ),
        "nsl.compiler": SimpleNamespace(NslCompiler=Compiler),
        "nsl.nsp": SimpleNamespace(NspBuilder=Builder),
        "nsl.nsp_verification": SimpleNamespace(
            NspVerificationPolicy=lambda environment: ("policy", environment),
            NspVerifier=Verifier,
        ),
        "nsl.security": SimpleNamespace(
            RuntimeEnvironment=SimpleNamespace(PRODUCTION="production")
        ),
        "nsl.vertical_slice": SimpleNamespace(
            build_mock_executor=lambda catalog: ("tools", catalog),
            build_tool_catalog=lambda: "catalog",
        ),
    }
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)

    factory = smoke._InstalledWheelWorkerFactory(source, artifact)
    session = factory(artifact["backend_artifact_handle"], "progress")

    assert isinstance(session.worker, Worker)
    assert session.worker.values["progress_sink"] == "progress"
    assert factory.session_count == 1

    compile_state["nso_bytes"] = None
    try:
        factory(artifact["backend_artifact_handle"], "progress")
    except RuntimeError as exc:
        assert "compile" in str(exc)
    else:
        raise AssertionError("missing NSO must fail closed")

    compile_state["nso_bytes"] = b"nso"
    try:
        factory("nsp+sha256://wrong/skill@1", "progress")
    except RuntimeError as exc:
        assert "identity" in str(exc)
    else:
        raise AssertionError("artifact identity drift must fail closed")


def test_worker_session_requires_audit_and_snapshot_evidence() -> None:
    events = [
        SimpleNamespace(event_hash="audit-1", payload={"snapshot_ref": "snapshot-1"})
    ]
    session = smoke._WorkerSession(object(), SimpleNamespace(events=events))
    assert session.evidence_refs() == [
        "NSL:AUDIT:audit-1",
        "NSL:SNAPSHOT:snapshot-1",
    ]

    for audit in (
        SimpleNamespace(events=[]),
        SimpleNamespace(events=[SimpleNamespace(event_hash="audit-2", payload={})]),
    ):
        try:
            smoke._WorkerSession(object(), audit).evidence_refs()
        except RuntimeError as exc:
            assert "evidence" in str(exc)
        else:
            raise AssertionError("incomplete evidence must fail closed")


def test_smoke_helpers_and_main(monkeypatch, tmp_path, capsys) -> None:
    assert smoke._git_output(ROOT, "rev-parse", "--is-inside-work-tree") == "true"
    assert smoke._sha256_ref(b"payload").startswith("sha256:")
    assert smoke._utc_now().endswith("Z")
    assert smoke._has_complete_evidence(_record(1)) is True
    assert (
        smoke._has_complete_evidence({"progress_events": [], "evidence_refs": []})
        is False
    )

    examples = tmp_path / "examples"
    examples.mkdir()
    (examples / "not-object.json").write_text("[]", encoding="utf-8")
    monkeypatch.setattr(smoke, "EXAMPLES", examples)
    try:
        smoke._example("not-object.json")
    except TypeError as exc:
        assert "object" in str(exc)
    else:
        raise AssertionError("non-object example must fail closed")

    monkeypatch.setattr(smoke, "load_env_file", lambda _path: None)
    monkeypatch.setattr(
        smoke,
        "run_p6_ca02_s3_in_process_smoke",
        lambda: {
            "status": "PASS",
            "actual_installed_wheel": True,
            "checks_passed": 10,
            "checks_total": 10,
            "backend_profile": "NSL_V01_IN_PROCESS",
        },
    )
    assert smoke.main(["--summary"]) == 0
    assert "p6_ca02_s3_in_process=pass" in capsys.readouterr().out
    assert smoke.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_p6_ca02_s3_in_process_smoke",
        lambda: smoke._failure("failed", "detail"),
    )
    assert smoke.main([]) == 1
