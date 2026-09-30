from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from nex_mo import provider_transport, remote_provider
from nex_mo.providers import ProviderRouteError
import run_mo_provider_transport_extraction as runner


CONFIG = SimpleNamespace(
    method="POST",
    url="http://provider.invalid/v1/test",
    timeout_seconds=15.0,
    headers=lambda: {"Accept": "application/json"},
)


def test_transport_success_and_default_requester(monkeypatch) -> None:
    calls = []

    def requester(*args, **kwargs):
        calls.append((args, kwargs))
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(provider_transport.httpx, "request", requester)
    result = provider_transport.execute_remote_json_request(
        CONFIG,
        json_payload={"input": "safe"},
        requester=None,
        error_code_prefix="mo.remote_test",
    )

    assert result == {"ok": True}
    assert calls[0][0] == ("POST", CONFIG.url)
    assert calls[0][1]["timeout"] == 15.0


@pytest.mark.parametrize(
    ("failure", "status_code", "kind"),
    [
        (httpx.ReadTimeout("timeout"), 504, "read_timeout"),
        (httpx.ConnectError("unavailable"), 503, "connection_error"),
    ],
)
def test_transport_classifies_request_failures(failure, status_code, kind) -> None:
    def requester(*args, **kwargs):
        raise failure

    with pytest.raises(ProviderRouteError) as exc_info:
        provider_transport.execute_remote_json_request(
            CONFIG,
            json_payload={},
            requester=requester,
            error_code_prefix="mo.remote_test",
        )

    assert exc_info.value.status_code == status_code
    assert exc_info.value.failure_kind == kind


@pytest.mark.parametrize(
    ("status", "projected", "retryable"),
    [(429, 429, True), (503, 503, True), (400, 502, False)],
)
def test_transport_classifies_http_failures(status, projected, retryable) -> None:
    with pytest.raises(ProviderRouteError) as exc_info:
        provider_transport.execute_remote_json_request(
            CONFIG,
            json_payload={},
            requester=lambda *args, **kwargs: httpx.Response(status),
            error_code_prefix="mo.remote_test",
        )

    assert exc_info.value.status_code == projected
    assert exc_info.value.retryable is retryable
    assert exc_info.value.upstream_status_code == status


def test_transport_rejects_non_json_and_preserves_safe_projection() -> None:
    with pytest.raises(ProviderRouteError) as exc_info:
        provider_transport.execute_remote_json_request(
            CONFIG,
            json_payload={},
            requester=lambda *args, **kwargs: httpx.Response(200, content=b"not-json"),
            error_code_prefix="mo.remote_test",
        )

    assert exc_info.value.failure_kind == "malformed_response"
    decision = provider_transport.remote_provider_response_invalid_decision(
        error_code_prefix="mo.remote_test",
        detail="private detail",
    )
    assert decision.to_safe_summary() == {
        "failure_kind": "malformed_response",
        "error_code": "mo.remote_test_response_invalid",
        "status_code": 502,
        "retryable": True,
        "degraded": True,
    }


def test_transport_compatibility_and_evidence_runner(tmp_path: Path, monkeypatch, capsys) -> None:
    assert remote_provider.RemoteProviderFailureDecision is (
        provider_transport.RemoteProviderFailureDecision
    )
    assert remote_provider.classify_remote_provider_exception is (
        provider_transport.classify_remote_provider_exception
    )
    missing = runner.run_mo_provider_transport_extraction(tmp_path)
    assert missing["status"] == "FAIL"
    assert missing["summary"]["failed_check_count"] == 2

    passing = runner.run_mo_provider_transport_extraction()
    assert passing["status"] == "PASS"
    monkeypatch.setattr(runner, "run_mo_provider_transport_extraction", lambda: passing)
    assert runner.main(["--summary"]) == 0
    assert "classifiers=3" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out

    failing = {"status": "FAIL", "summary": {}}
    monkeypatch.setattr(runner, "run_mo_provider_transport_extraction", lambda: failing)
    assert runner.main(["--summary"]) == 1
    assert "transport_extraction=fail" in capsys.readouterr().out
