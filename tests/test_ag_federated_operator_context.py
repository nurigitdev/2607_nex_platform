from __future__ import annotations

from types import SimpleNamespace

import pytest

from nex_ag.federated_operator_context import (
    AG_FEDERATED_OPERATOR_CONTEXT_STATE_KEY,
    AgFederatedOperatorContextError,
    adopt_ag_federated_operator_context,
    ag_federated_operator_context_from_request,
    build_ag_federated_operator_context,
)
from nex_oa.federated_identities import OaFederationError
from nex_oa.federated_login import (
    build_federated_login_response,
    build_federated_operator_context,
)
import run_ag_federated_operator_context as runner


def _context(**overrides: object) -> dict[str, object]:
    return {
        "tenant_id": "company",
        "subject_id": "employee-1001",
        "roles": ["admin"],
        "scopes": ["workspace:use"],
        "auth_method": "federated_oidc",
        "session_id_digest": "a" * 64,
        **overrides,
    }


def _session(**overrides: object) -> dict[str, object]:
    return {
        "session_id": "session-1",
        "tenant_id": "company",
        "subject_id": "employee-1001",
        "roles": ["admin"],
        "scopes": ["workspace:use"],
        **overrides,
    }


def test_context_adoption_is_strict_safe_and_request_bound() -> None:
    request = SimpleNamespace(state=SimpleNamespace())
    context = adopt_ag_federated_operator_context(request, _context())

    assert context.to_wire() == _context()
    assert context.operator_ref() == {
        "operator_type": "user",
        "operator_id": "employee-1001",
    }
    assert ag_federated_operator_context_from_request(request) is context


def test_request_state_absent_and_corrupt_paths_fail_closed() -> None:
    request = SimpleNamespace(state=SimpleNamespace())
    assert ag_federated_operator_context_from_request(request) is None
    setattr(request.state, AG_FEDERATED_OPERATOR_CONTEXT_STATE_KEY, {})
    with pytest.raises(AgFederatedOperatorContextError) as exc:
        ag_federated_operator_context_from_request(request)
    assert exc.value.error_code == "ag.federated_operator_context_invalid"
    assert str(exc.value) == exc.value.detail


@pytest.mark.parametrize(
    ("payload", "code"),
    (
        ([], "ag.federated_operator_context_invalid"),
        ({**_context(), "display_name": "Private"}, "ag.federated_operator_context_field_unsupported"),
        ({**_context(), "id_token": "private"}, "ag.federated_operator_context_private_payload_rejected"),
    ),
)
def test_context_rejects_non_object_and_unsupported_fields(payload, code) -> None:
    with pytest.raises(AgFederatedOperatorContextError) as exc:
        build_ag_federated_operator_context(payload)
    assert exc.value.error_code == code


@pytest.mark.parametrize(
    "payload",
    (
        _context(tenant_id=""),
        _context(subject_id=" spaced "),
        _context(roles="admin"),
        _context(roles=["admin"] * 33),
        _context(roles=["admin", "admin"]),
        _context(scopes=[1]),
        _context(auth_method="password"),
        _context(session_id_digest="A" * 64),
    ),
)
def test_context_rejects_invalid_safe_claim_shapes(payload) -> None:
    with pytest.raises(AgFederatedOperatorContextError) as exc:
        build_ag_federated_operator_context(payload)
    assert exc.value.error_code == "ag.federated_operator_context_invalid"


def test_oa_projection_supports_nested_and_legacy_flat_session_shapes() -> None:
    flat = build_federated_operator_context(_session())
    nested = build_federated_operator_context(
        {
            "session": {
                "session_id": "session-1",
                "tenant_ref": {"id": "company"},
                "subject_ref": {"id": "employee-1001"},
                "roles": ["admin"],
                "scopes": ["workspace:use"],
            }
        }
    )
    assert nested == flat
    assert nested["session_id_digest"] != "session-1"


@pytest.mark.parametrize(
    "session",
    (
        _session(session_id=""),
        _session(tenant_id=1),
        _session(roles="admin"),
        _session(scopes=["workspace:use", "workspace:use"]),
        _session(scopes=["x"] * 33),
    ),
)
def test_oa_projection_rejects_invalid_session_shapes(session) -> None:
    with pytest.raises(OaFederationError) as exc:
        build_federated_operator_context(session)
    assert exc.value.error_code == "oa.federated_session_projection_invalid"
    assert exc.value.status_code == 503


def test_login_response_includes_only_safe_operator_context() -> None:
    response = build_federated_login_response(
        {**_session(), "metadata": []},
        provider_id="company-oidc",
    )
    assert response["metadata"]["provider_id"] == "company-oidc"
    assert response["operator_context"]["auth_method"] == "federated_oidc"
    assert "provider_id" not in response["operator_context"]
    assert "session_id" not in response["operator_context"]


def test_runner_and_cli(monkeypatch, capsys) -> None:
    evidence = runner.run_ag_federated_operator_context()
    assert evidence["status"] == "PASS"
    assert all(evidence["checks"].values())
    assert runner.summary_line(evidence) == (
        "ag_federated_operator_context=pass checks=8/8 "
        "method=federated_oidc next=1288"
    )
    monkeypatch.setattr(runner, "run_ag_federated_operator_context", lambda: evidence)
    assert runner.main(["--summary"]) == 0
    assert "next=1288" in capsys.readouterr().out
    assert runner.main([]) == 0
    assert '"status": "PASS"' in capsys.readouterr().out
    monkeypatch.setattr(
        runner, "run_ag_federated_operator_context", lambda: {"status": "FAIL"}
    )
    assert runner.main([]) == 1
