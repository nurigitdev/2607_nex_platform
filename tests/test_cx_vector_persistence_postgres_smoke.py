from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "smoke" / "run_cx_vector_persistence_postgres_smoke.py"


def _module():
    spec = importlib.util.spec_from_file_location("cx_vector_persistence_smoke", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_schema_audit_covers_manifest_payload_owner_and_ann_index():
    result = _module().audit_vector_persistence_schema()

    assert result["status"] == "PASS"
    assert result["failed_checks"] == []
    assert all(result["checks"].values())
    assert result["table_names"] == ["cx_vector_indexes", "cx_vectors"]
    assert result["default_ann_dimension"] == 2560
    assert result["remote_embedding_required"] is False


def test_postgres_smoke_is_protected_by_default():
    result = _module().run_cx_vector_persistence_postgres_smoke({})

    assert result["status"] == "SKIPPED"
    assert result["skip_reason"].startswith(_module().SMOKE_ENV)
    assert result["schema_audit"]["status"] == "PASS"


def test_postgres_smoke_rejects_non_test_profile_before_database_lookup():
    module = _module()
    result = module.run_cx_vector_persistence_postgres_smoke(
        {module.SMOKE_ENV: "1", module.PROFILE_ENV: "dev"}
    )

    assert result["status"] == "FAIL"
    assert result["error"]["code"] == "profile_not_allowed"


def test_postgres_smoke_rejects_wrong_target(monkeypatch):
    module = _module()
    monkeypatch.setattr(module, "service_database_env", lambda *_args, **_kwargs: "DB")
    monkeypatch.setattr(
        module,
        "service_database_url",
        lambda *_args, **_kwargs: "postgresql://wrong:secret@localhost/not_test",
    )

    result = module.run_cx_vector_persistence_postgres_smoke(
        {module.SMOKE_ENV: "1", module.PROFILE_ENV: "test"}
    )

    assert result["status"] == "FAIL"
    assert result["error"]["code"] == "target_not_allowed"


def test_postgres_smoke_reports_migration_failure_without_credentials(monkeypatch):
    module = _module()
    monkeypatch.setattr(module, "service_database_env", lambda *_args, **_kwargs: "DB")
    monkeypatch.setattr(
        module,
        "service_database_url",
        lambda *_args, **_kwargs: "postgresql://nex_cx_user@localhost/nex_cx_test",
    )
    monkeypatch.setattr(
        module,
        "run_service_migrations",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("secret detail")),
    )

    result = module.run_cx_vector_persistence_postgres_smoke(
        {module.SMOKE_ENV: "1", module.PROFILE_ENV: "test"}
    )

    assert result["status"] == "FAIL"
    assert result["error"] == {"code": "execution_failed", "detail": "RuntimeError"}
    assert "password" not in str(result).lower()


def test_postgres_smoke_reports_schema_audit_failure(monkeypatch):
    module = _module()
    monkeypatch.setattr(
        module,
        "audit_vector_persistence_schema",
        lambda: {"status": "FAIL", "failed_checks": ["payload_table"]},
    )

    result = module.run_cx_vector_persistence_postgres_smoke({})

    assert result["status"] == "FAIL"
    assert result["error"] == {
        "code": "schema_audit_failed",
        "detail": ["payload_table"],
    }


def test_postgres_smoke_success_and_failed_check_paths(monkeypatch):
    module = _module()
    migration = SimpleNamespace(planned=("0933",), applied=(), skipped=("0933",))
    monkeypatch.setattr(module, "service_database_env", lambda *_args, **_kwargs: "DB")
    monkeypatch.setattr(
        module,
        "service_database_url",
        lambda *_args, **_kwargs: "postgresql://nex_cx_user:secret@localhost/nex_cx_test",
    )
    monkeypatch.setattr(module, "run_service_migrations", lambda *_args, **_kwargs: migration)
    monkeypatch.setattr(
        module,
        "_execute_smoke",
        lambda _url: {
            "failed_checks": [],
            "checks": {"round_trip": True},
            "check_count": 1,
            "vector_dimension": 2560,
        },
    )

    result = module.run_cx_vector_persistence_postgres_smoke(
        {module.SMOKE_ENV: "1", module.PROFILE_ENV: "test"}
    )

    assert result["status"] == "PASS"
    assert result["migration"] == {
        "planned": ["0933"],
        "applied": [],
        "skipped": ["0933"],
    }
    assert result["remote_embedding_required"] is False

    monkeypatch.setattr(
        module,
        "_execute_smoke",
        lambda _url: {"failed_checks": ["round_trip"]},
    )
    failed = module.run_cx_vector_persistence_postgres_smoke(
        {module.SMOKE_ENV: "1", module.PROFILE_ENV: "test"}
    )
    assert failed["status"] == "FAIL"
    assert failed["error"]["code"] == "vector_persistence_smoke_failed"


def test_postgres_smoke_uses_process_environment(monkeypatch):
    module = _module()
    monkeypatch.delenv(module.SMOKE_ENV, raising=False)

    assert module.run_cx_vector_persistence_postgres_smoke()["status"] == "SKIPPED"


def test_target_guard_accepts_driver_qualified_test_url_and_summary_shapes():
    module = _module()

    assert module._target_url_allowed(
        "postgresql+psycopg://nex_cx_user:secret@127.0.0.1/nex_cx_test"
    )
    assert not module._target_url_allowed("postgresql://nex_cx_user@localhost/nex_cx_dev")
    assert "skipped" in module._format_summary({"status": "SKIPPED"})
    assert "checks=9/9" in module._format_summary(
        {"status": "PASS", "check_count": 9, "vector_dimension": 2560}
    )
    assert "error=boom" in module._format_summary(
        {"status": "FAIL", "error": {"code": "boom"}}
    )


def test_embedding_fixture_has_expected_dimension_and_hot_coordinate():
    module = _module()
    embedding = module._embedding(1)

    values = embedding.strip("[]").split(",")
    assert len(values) == 2560
    assert values[:3] == ["0", "1", "0"]
    assert len(module._digest(embedding)) == 64


def test_main_supports_summary_and_json_output(monkeypatch, capsys):
    module = _module()
    monkeypatch.setattr(
        module,
        "run_cx_vector_persistence_postgres_smoke",
        lambda: {"status": "SKIPPED"},
    )
    monkeypatch.setattr(module.sys, "argv", ["vector-smoke", "--summary"])
    assert module.main() == 0
    assert "skipped" in capsys.readouterr().out

    monkeypatch.setattr(
        module,
        "run_cx_vector_persistence_postgres_smoke",
        lambda: {"status": "FAIL", "error": {"code": "boom"}},
    )
    monkeypatch.setattr(module.sys, "argv", ["vector-smoke"])
    assert module.main() == 1
    assert '"status": "FAIL"' in capsys.readouterr().out
