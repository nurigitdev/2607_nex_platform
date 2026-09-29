from __future__ import annotations

from contextlib import nullcontext
from copy import deepcopy
from datetime import UTC, datetime
import json

import pytest

import run_ae_mvp_acceptance_postgres_live_smoke as smoke


NOW = datetime(2026, 9, 29, 7, 0, tzinfo=UTC)


def _env() -> dict[str, str]:
    return {
        smoke.SMOKE_ENV: "1",
        smoke.AE_DATABASE_ENV: "postgresql+psycopg://nex_ae_user:ae-private@localhost/nex_ae_test",
        smoke.CX_DATABASE_ENV: "postgresql+psycopg://nex_cx_user:cx-private@localhost/nex_cx_test",
        "NEX_MO_VLLM_API_KEY": "generation-private-key",
    }


def _source() -> dict:
    return {
        "status": "PASS",
        "actual_postgres": True,
        "database_identity": deepcopy(smoke.EXPECTED_IDENTITIES),
        "browser_observation": {"display_mode": "VERIFIED_RESPONSE"},
        "provider_observation": {
            capability: {"model": model, "success_count": 1, "failure_count": 0}
            for capability, model in smoke.EXPECTED_MODELS.items()
        },
        "persistence_observation": {
            "ae_status": "COMPLETED",
            "retrieval_status": "READY",
            "generation_status": "COMPLETED",
            "job_status": "SUCCEEDED",
        },
        "checks": {
            "integrated_path": True,
            "browser_received_no_server_secret": True,
        },
    }


def _residue(total: int = 0) -> dict:
    return {
        "status": "PASS" if total == 0 else "FAIL",
        "counts": {"ae_chat_interactions": total},
        "total_rows": total,
    }


def test_smoke_is_protected_and_requires_both_database_urls() -> None:
    skipped = smoke.run_ae_mvp_acceptance_postgres_live_smoke({})
    missing = smoke.run_ae_mvp_acceptance_postgres_live_smoke(
        {smoke.SMOKE_ENV: "1"}
    )

    assert skipped["status"] == "SKIPPED"
    assert "=skipped" in smoke.summary_line(skipped)
    assert missing["failure_code"] == "database_url_missing"


def test_smoke_promotes_s109_live_evidence_to_acceptance_gates() -> None:
    result = smoke.run_ae_mvp_acceptance_postgres_live_smoke(
        _env(),
        live_runner=lambda _env: _source(),
        residue_reader=lambda _ae, _cx: _residue(),
        now=NOW,
    )

    assert result["status"] == "PASS"
    assert all(result["checks"].values())
    assert all(
        item["status"] == "PASS"
        for item in result["acceptance_gate_evidence"].values()
    )
    assert result["provider_observation"]["models"] == smoke.EXPECTED_MODELS
    assert result["handoff_observation"]["verification_status"] == "VERIFIED"
    assert smoke.summary_line(result).endswith(
        "providers=3/3 display=VERIFIED_RESPONSE residue=0"
    )


def test_source_failure_short_circuits_residue_read() -> None:
    calls: list[str] = []
    result = smoke.run_ae_mvp_acceptance_postgres_live_smoke(
        _env(),
        live_runner=lambda _env: {"status": "FAIL", "failure_code": "offline"},
        residue_reader=lambda _ae, _cx: calls.append("called") or _residue(),
    )

    assert result["failure_code"] == "s109_live_smoke_failed"
    assert result["detail"] == "offline"
    assert calls == []


@pytest.mark.parametrize(
    ("mutator", "failed_check"),
    [
        (lambda value: value["database_identity"].update({"ae": {}}), "actual_test_postgres_proven"),
        (lambda value: value["provider_observation"]["reranking"].update({"model": "wrong"}), "live_provider_models_frozen"),
        (lambda value: value["provider_observation"]["generation"].update({"failure_count": 1}), "live_provider_failures_absent"),
        (lambda value: value["browser_observation"].update({"display_mode": "BLOCKED"}), "verified_response_displayed"),
        (lambda value: value["persistence_observation"].update({"job_status": "FAILED"}), "durable_terminal_states_proven"),
        (lambda value: value["checks"].update({"browser_received_no_server_secret": False}), "browser_server_secret_absent"),
    ],
)
def test_acceptance_checks_fail_closed(mutator, failed_check: str) -> None:
    source = _source()
    mutator(source)

    result = smoke.run_ae_mvp_acceptance_postgres_live_smoke(
        _env(),
        live_runner=lambda _env: source,
        residue_reader=lambda _ae, _cx: _residue(),
        now=NOW,
    )

    assert result["status"] == "FAIL"
    assert failed_check in result["failed_checks"]


def test_nonzero_residue_blocks_postgres_gate() -> None:
    result = smoke.run_ae_mvp_acceptance_postgres_live_smoke(
        _env(),
        live_runner=lambda _env: _source(),
        residue_reader=lambda _ae, _cx: _residue(1),
        now=NOW,
    )

    assert result["checks"]["probe_residue_zero"] is False
    assert result["acceptance_gate_evidence"]["postgres_smoke"]["status"] == "FAIL"


def test_runtime_exception_is_bounded_and_redacted() -> None:
    result = smoke.run_ae_mvp_acceptance_postgres_live_smoke(
        _env(),
        live_runner=lambda _env: (_ for _ in ()).throw(
            RuntimeError("generation-private-key")
        ),
    )

    assert result["failure_code"] == "acceptance_live_smoke_failed"
    assert result["detail"] == "RuntimeError"
    assert "generation-private-key" not in json.dumps(result)


def test_default_live_delegate_and_private_content_redaction(monkeypatch) -> None:
    monkeypatch.setattr(
        smoke.s109,
        "run_ae_web_grounded_generation_playwright_postgres_smoke",
        lambda env: {"status": "PASS", "enabled": env[smoke.SMOKE_ENV]},
    )
    assert smoke._run_s109_live({smoke.SMOKE_ENV: "1"})["status"] == "PASS"
    with pytest.raises(ValueError, match="protected content"):
        smoke.assert_evidence_redacted({"value": smoke.s109.SOURCE_TEXT}, {})


class _Scalar:
    def __init__(self, value: int) -> None:
        self.value = value

    def scalar_one(self) -> int:
        return self.value


class _Connection:
    def __init__(self, values: list[int]) -> None:
        self.values = values

    def execute(self, *_args, **_kwargs) -> _Scalar:
        return _Scalar(self.values.pop(0))


class _Engine:
    def __init__(self, values: list[int]) -> None:
        self.connection = _Connection(values)
        self.disposed = False

    def connect(self):
        return nullcontext(self.connection)

    def dispose(self) -> None:
        self.disposed = True


def test_residue_reader_queries_both_databases_and_disposes(monkeypatch) -> None:
    ae = _Engine([0, 0])
    cx = _Engine([0, 0, 0])
    engines = iter((ae, cx))
    monkeypatch.setattr(smoke, "build_engine", lambda _url: next(engines))

    result = smoke.read_s109_probe_residue("ae", "cx")

    assert result["status"] == "PASS"
    assert result["total_rows"] == 0
    assert len(result["counts"]) == 5
    assert ae.disposed is True
    assert cx.disposed is True


def test_redaction_timezone_and_output_main(monkeypatch, tmp_path, capsys) -> None:
    naive = smoke.run_ae_mvp_acceptance_postgres_live_smoke(
        _env(),
        live_runner=lambda _env: _source(),
        residue_reader=lambda _ae, _cx: _residue(),
        now=datetime(2026, 9, 29, 7, 0),
    )
    assert naive["failure_code"] == "acceptance_live_smoke_failed"
    assert naive["detail"] == "ValueError"
    with pytest.raises(ValueError, match="protected value"):
        smoke.assert_evidence_redacted(
            {"value": "generation-private-key"}, _env()
        )

    monkeypatch.setattr(
        smoke,
        "run_ae_mvp_acceptance_postgres_live_smoke",
        lambda: {"status": "PASS", "checks": {"ok": True}},
    )
    output = tmp_path / "evidence.json"
    assert smoke.main(["--summary", "--output", str(output)]) == 0
    assert output.is_file()
    assert "ae_mvp_acceptance_live=pass" in capsys.readouterr().out

    monkeypatch.setattr(
        smoke,
        "run_ae_mvp_acceptance_postgres_live_smoke",
        lambda: {"status": "FAIL", "failure_code": "blocked"},
    )
    assert smoke.main([]) == 1
    assert '"status": "FAIL"' in capsys.readouterr().out
