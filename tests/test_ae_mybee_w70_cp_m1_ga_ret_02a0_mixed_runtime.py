from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import nex_ae_api.controlled_skill_runtime as controlled
import pytest
from run_mybee_w70_golden_a_quarantine_gate import run_gate

ROOT = Path(__file__).resolve().parents[1]


def test_canonical_product_profile_imports_only_neutral_controlled_runtime() -> None:
    pythonpath = os.pathsep.join(
        (
            str(ROOT / "services/nex-ae-api"),
            str(ROOT / "services/_shared"),
            str(ROOT / "domains/mybee"),
        )
    )
    command = (
        "import json,sys; "
        "import nex_ae_api.product_runtime_profile; "
        "print(json.dumps({"
        "'neutral': 'nex_ae_api.controlled_skill_runtime' in sys.modules,"
        "'legacy': 'nex_ae_api.product_controlled_skill' in sys.modules,"
        "'golden': 'nex_ae_api.golden_a_planning' in sys.modules"
        "}))"
    )

    completed = subprocess.run(
        (sys.executable, "-c", command),
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": pythonpath},
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(completed.stdout) == {
        "neutral": True,
        "legacy": False,
        "golden": False,
    }


def test_quarantine_gate_proves_recursive_active_import_separation() -> None:
    result = run_gate(ROOT)

    assert result["status"] == "PASS"
    assert result["checks"]["active_import_graph_is_generic"] is True
    assert result["checks"]["recursive_import_guard_matches_quarantine"] is True
    assert result["historical_active_import_conflicts"] == []
    assert result["active_import_module_count"] > 0


@pytest.mark.parametrize(
    ("commit_state", "verification", "expected_state", "expected_error"),
    (
        ("COMMITTED", "VERIFIED", "SUCCEEDED", None),
        ("NOT_COMMITTED", None, "FAILED", "eos.write_not_committed"),
        (
            "UNKNOWN",
            "UNKNOWN",
            "BLOCKED",
            "eos.write_outcome_requires_reconciliation",
        ),
    ),
)
def test_neutral_controlled_write_outcome_preserves_terminal_mapping(
    commit_state: str,
    verification: str | None,
    expected_state: str,
    expected_error: str | None,
) -> None:
    result = SimpleNamespace(
        outcome=SimpleNamespace(commit_state=SimpleNamespace(value=commit_state)),
        verification=(
            None
            if verification is None
            else SimpleNamespace(status=SimpleNamespace(value=verification))
        ),
        write_request=SimpleNamespace(idempotency_key="idem-1"),
    )

    outcome = controlled._controlled_write_outcome(
        result, business_operation_id="operation-1"
    )

    assert outcome.state == expected_state
    assert outcome.error_ref == expected_error
    assert outcome.result_payload == {
        "commit_state": commit_state,
        "verification_status": verification,
        "business_operation_id": "operation-1",
    }


def test_neutral_runtime_and_principal_primitives_fail_closed() -> None:
    runtime = controlled.ControlledSkillRuntime()
    with pytest.raises(controlled.ControlledSkillRuntimeError, match="initial/resume"):
        runtime.execute()
    with pytest.raises(NotImplementedError):
        runtime._resolve_authority(object())
    with pytest.raises(NotImplementedError):
        runtime._execute_controlled_write(
            execution=object(), invocation=object(), authority=object()
        )

    principal = controlled.principal_document(
        tenant_id="VO00",
        principal_id="employee-1",
        authorization={
            "roles": ["employee"],
            "scopes": ["finance:journal:approve"],
            "revision_hash": "revision-1",
        },
    )
    assert principal["roles"] == ["employee"]
    assert "nsl:skill:execute" in principal["scopes"]
    with pytest.raises(
        controlled.ControlledSkillRuntimeError, match="string set"
    ):
        controlled.principal_document(
            tenant_id="VO00",
            principal_id="employee-1",
            authorization={
                "roles": [""],
                "scopes": [],
                "revision_hash": "revision-1",
            },
        )


def test_neutral_oa_authority_source_accepts_mapping_and_rejects_malformed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Response:
        def __init__(self, payload: object) -> None:
            self.payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> object:
            return self.payload

    payloads = iter(
        (
            {"authorization": {"revision_hash": "revision-1", "scopes": []}},
            {"authorization": "invalid"},
        )
    )
    monkeypatch.setattr(
        controlled,
        "resolve_ae_outbound_service_token",
        lambda _token, *, audience: f"service-token:{audience}",
    )
    monkeypatch.setattr(
        controlled.httpx,
        "get",
        lambda *_args, **_kwargs: _Response(next(payloads)),
    )
    source = controlled.HttpOaAuthoritySource(
        base_url="http://oa.local/", service_token="bootstrap-token"
    )

    assert source.effective_authorization(
        tenant_id="VO00", subject_id="employee-1"
    ) == {"revision_hash": "revision-1", "scopes": [], "active": True}
    with pytest.raises(
        controlled.ControlledSkillRuntimeError, match="response is invalid"
    ):
        source.effective_authorization(
            tenant_id="VO00", subject_id="employee-1"
        )
