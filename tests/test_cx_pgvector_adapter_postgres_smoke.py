from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "smoke" / "run_cx_pgvector_adapter_postgres_smoke.py"


def _module():
    spec = importlib.util.spec_from_file_location("cx_pgvector_adapter_smoke", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_smoke_is_protected_by_default_and_uses_process_environment(monkeypatch):
    module = _module()
    assert module.run_cx_pgvector_adapter_postgres_smoke({})["status"] == "SKIPPED"
    monkeypatch.delenv(module.SMOKE_ENV, raising=False)
    assert module.run_cx_pgvector_adapter_postgres_smoke()["status"] == "SKIPPED"


def test_smoke_rejects_profile_and_target(monkeypatch):
    module = _module()
    profile = module.run_cx_pgvector_adapter_postgres_smoke(
        {module.SMOKE_ENV: "1", module.PROFILE_ENV: "dev"}
    )
    assert profile["error"]["code"] == "profile_not_allowed"

    monkeypatch.setattr(module, "service_database_env", lambda *_a, **_k: "DB")
    monkeypatch.setattr(
        module,
        "service_database_url",
        lambda *_a, **_k: "postgresql://wrong:secret@localhost/wrong",
    )
    target = module.run_cx_pgvector_adapter_postgres_smoke(
        {module.SMOKE_ENV: "1", module.PROFILE_ENV: "test"}
    )
    assert target["error"]["code"] == "target_not_allowed"


def test_smoke_success_failed_checks_and_exception_paths(monkeypatch):
    module = _module()
    url = "postgresql://nex_cx_user:secret@localhost/nex_cx_test"
    migration = SimpleNamespace(applied=(), skipped=("0933",))
    monkeypatch.setattr(module, "service_database_env", lambda *_a, **_k: "DB")
    monkeypatch.setattr(module, "service_database_url", lambda *_a, **_k: url)
    monkeypatch.setattr(module, "run_service_migrations", lambda *_a, **_k: migration)
    monkeypatch.setattr(
        module,
        "_execute_smoke",
        lambda *_a, **_k: {
            "failed_checks": [],
            "checks": {"round_trip": True},
            "check_count": 1,
            "vector_dimension": 2560,
        },
    )
    passing = module.run_cx_pgvector_adapter_postgres_smoke(
        {module.SMOKE_ENV: "1", module.PROFILE_ENV: "test"}
    )
    assert passing["status"] == "PASS"
    assert passing["remote_embedding_required"] is False
    assert "secret" not in passing["redacted_database_url"]

    monkeypatch.setattr(
        module,
        "_execute_smoke",
        lambda *_a, **_k: {"failed_checks": ["round_trip"]},
    )
    failed = module.run_cx_pgvector_adapter_postgres_smoke(
        {module.SMOKE_ENV: "1", module.PROFILE_ENV: "test"}
    )
    assert failed["error"]["code"] == "pgvector_adapter_smoke_failed"

    monkeypatch.setattr(
        module,
        "run_service_migrations",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("secret")),
    )
    error = module.run_cx_pgvector_adapter_postgres_smoke(
        {module.SMOKE_ENV: "1", module.PROFILE_ENV: "test"}
    )
    assert error["error"] == {"code": "execution_failed", "detail": "RuntimeError"}


def test_target_guard_summary_digest_and_main_paths(monkeypatch, capsys):
    module = _module()
    assert module._target_url_allowed(
        "postgresql+psycopg://nex_cx_user:secret@localhost/nex_cx_test"
    )
    assert not module._target_url_allowed("postgresql://nex_cx_user@localhost/nex_cx_dev")
    assert len(module._digest("value")) == 64
    assert "skipped" in module._summary({"status": "SKIPPED"})
    assert "checks=2/2" in module._summary({"status": "PASS", "check_count": 2})
    assert "error=boom" in module._summary(
        {"status": "FAIL", "error": {"code": "boom"}}
    )

    monkeypatch.setattr(
        module,
        "run_cx_pgvector_adapter_postgres_smoke",
        lambda: {"status": "SKIPPED"},
    )
    assert module.main(["--summary"]) == 0
    assert "skipped" in capsys.readouterr().out
    monkeypatch.setattr(
        module,
        "run_cx_pgvector_adapter_postgres_smoke",
        lambda: {"status": "FAIL", "error": {"code": "boom"}},
    )
    assert module.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out
