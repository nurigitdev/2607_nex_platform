from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import runpy
import sys

from fastapi import Request
import pytest

from nex_runtime import issue_mock_service_token
from nex_cx.access_context import (
    CxAccessContextError,
    authenticate_cx_service_claim,
)
from nex_cx.authorization import authorize_cx_request
import run_cx_central_authorization_enforcement as evidence_runner


NOW = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)


def _authorization(service_id: str = "nex-ae-api", **kwargs: object) -> str:
    issued = issue_mock_service_token(
        service_id=service_id,
        audience="nex-cx",
        issued_at=NOW,
        **kwargs,
    )
    return f"Bearer {issued.access_token}"


def _request(path: str = "/api/v1/documents") -> Request:
    return evidence_runner._request(path)


def test_authenticate_cx_service_claim_returns_safe_validated_claims() -> None:
    claims = authenticate_cx_service_claim(
        authorization=_authorization(),
        now=NOW + timedelta(seconds=1),
    )

    assert claims.service_id == "nex-ae-api"
    assert claims.audience == "nex-cx"
    assert claims.scopes == ("service:call",)


def test_central_guard_attaches_token_free_caller_state() -> None:
    request = _request()
    authorization = _authorization()

    assert (
        authorize_cx_request(
            request,
            authorization,
            now=NOW + timedelta(seconds=1),
        )
        is None
    )
    assert request.state.cx_caller_service_id == "nex-ae-api"
    assert request.state.cx_caller_scopes == ("service:call",)
    assert authorization not in repr(vars(request.state))


def test_central_guard_returns_consistent_authentication_problem() -> None:
    response = authorize_cx_request(
        _request("/api/v1/chunks"),
        None,
        now=NOW + timedelta(seconds=1),
    )

    assert response is not None
    assert response.status_code == 401
    payload = json.loads(response.body)
    assert payload["title"] == "Authentication failed"
    assert payload["error_code"] == "AUTHORIZATION_HEADER_MISSING"
    assert payload["instance"] == "/api/v1/chunks"
    assert payload["details"] == {}


def test_central_guard_forbids_service_that_cannot_assert_ownership() -> None:
    response = authorize_cx_request(
        _request(),
        _authorization("nex-mo"),
        now=NOW + timedelta(seconds=1),
    )

    assert response is not None
    assert response.status_code == 403
    payload = json.loads(response.body)
    assert payload["title"] == "Authorization failed"
    assert payload["error_code"] == "CX_CALLER_SERVICE_FORBIDDEN"
    assert payload["details"]["allowed_caller_services"] == [
        "nex-ae-api",
        "nex-ag",
        "nex-cx",
    ]


def test_authenticate_rejects_untrusted_service_directly() -> None:
    with pytest.raises(CxAccessContextError) as caught:
        authenticate_cx_service_claim(
            authorization=_authorization("nex-oa"),
            now=NOW + timedelta(seconds=1),
        )

    assert caught.value.status_code == 403


def test_authorization_evidence_passes_for_repository() -> None:
    evidence = evidence_runner.run_cx_central_authorization_enforcement()

    assert evidence["status"] == "PASS"
    assert all(evidence["checks"].values())
    assert evidence["summary"] == {
        "route_module_count": 11,
        "centralized_route_module_count": 11,
        "failed_check_count": 0,
        "postgres_required": False,
        "dgx_required": False,
    }


def test_authorization_evidence_fails_closed_without_sources(tmp_path: Path) -> None:
    evidence = evidence_runner.run_cx_central_authorization_enforcement(tmp_path)

    assert evidence["status"] == "FAIL"
    assert evidence["summary"]["centralized_route_module_count"] == 0
    assert evidence["summary"]["failed_check_count"] == 2


def test_authorization_evidence_cli_paths(monkeypatch, capsys) -> None:
    passing = evidence_runner.run_cx_central_authorization_enforcement()
    monkeypatch.setattr(
        evidence_runner,
        "run_cx_central_authorization_enforcement",
        lambda: passing,
    )
    assert evidence_runner.main(["--summary"]) == 0
    assert "modules=11/11" in capsys.readouterr().out
    assert evidence_runner.main([]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "PASS"

    monkeypatch.setattr(
        evidence_runner,
        "run_cx_central_authorization_enforcement",
        lambda: {"status": "FAIL"},
    )
    assert evidence_runner.main([]) == 1
    assert "modules=0/0" in evidence_runner.summary_line({"status": "FAIL"})


def test_authorization_evidence_module_entrypoint(monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", [evidence_runner.__file__, "--summary"])

    with pytest.raises(SystemExit) as caught:
        runpy.run_path(evidence_runner.__file__, run_name="__main__")

    assert caught.value.code == 0
