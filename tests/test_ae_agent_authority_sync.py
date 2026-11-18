from __future__ import annotations

import httpx
import pytest
from nex_ae_api.agent_authority import (
    AgentAuthoritySyncError,
    HttpOaAgentAuthoritySynchronizer,
    build_agent_authority_synchronizer,
)

TENANT_ID = "tenant-a"
AGENT_ID = "agent-a"


def _membership(
    *,
    status: str = "ACTIVE",
    scopes: list[str] | None = None,
    agent_type: str = "IA",
    revision: int = 1,
    managed: bool = True,
):
    return {
        "membership": {
            "tenant_ref": {"type": "oa.tenant", "id": TENANT_ID},
            "subject_ref": {"type": "oa.user", "id": AGENT_ID},
            "status": status,
            "revision": revision,
            "roles": ["nex-agent", f"nex-agent-{agent_type.lower()}"],
            "scopes": scopes or ["work:claim", "work:delegate"],
            "metadata": (
                {"source": "nex-ae-agent-identity", "agent_type": agent_type}
                if managed
                else {}
            ),
        }
    }


def test_missing_active_ia_authority_is_created_with_bounded_policy() -> None:
    calls = []

    def requester(method, url, **kwargs):
        calls.append((method, url, kwargs))
        if method == "GET":
            return httpx.Response(404, json={"error_code": "oa.membership_not_found"})
        return httpx.Response(200, json=_membership())

    result = HttpOaAgentAuthoritySynchronizer(
        "https://oa.example",
        "signed-token",
        requester=requester,
    ).synchronize(
        tenant_id=TENANT_ID,
        agent_id=AGENT_ID,
        agent_type="IA",
        status="ACTIVE",
    )

    assert result["status"] == "ACTIVE"
    assert [item[0] for item in calls] == ["GET", "POST"]
    payload = calls[1][2]["json"]
    assert payload["roles"] == ["nex-agent", "nex-agent-ia"]
    assert payload["scopes"] == ["work:claim", "work:delegate"]
    assert "M1" not in str(payload)


def test_existing_pa_authority_replays_without_mutation() -> None:
    calls = []

    def requester(method, url, **kwargs):
        calls.append(method)
        return httpx.Response(
            200,
            json=_membership(
                scopes=["work:claim", "work:delegate", "work:result:submit"],
                agent_type="PA",
            ),
        )

    result = HttpOaAgentAuthoritySynchronizer(
        "https://oa.example", "signed-token", requester=requester
    ).synchronize(
        tenant_id=TENANT_ID,
        agent_id=AGENT_ID,
        agent_type="PA",
        status="ACTIVE",
    )

    assert calls == ["GET"]
    assert result["changed"] is False


def test_inactive_agent_authority_is_revision_guarded_and_disabled() -> None:
    calls = []

    def requester(method, url, **kwargs):
        calls.append((method, kwargs.get("json")))
        if method == "GET":
            return httpx.Response(
                200,
                json=_membership(
                    scopes=["work:claim", "work:delegate", "work:result:submit"],
                    agent_type="PA",
                ),
            )
        return httpx.Response(
            200,
            json={
                "tenant_id": TENANT_ID,
                "subject_id": AGENT_ID,
                "status": "DISABLED",
                "revision": 2,
            },
        )

    result = HttpOaAgentAuthoritySynchronizer(
        "https://oa.example", "signed-token", requester=requester
    ).synchronize(
        tenant_id=TENANT_ID,
        agent_id=AGENT_ID,
        agent_type="PA",
        status="RETIRED",
    )

    assert result["status"] == "DISABLED"
    assert calls == [
        ("GET", None),
        (
            "PATCH",
            {
                "target_status": "DISABLED",
                "expected_revision": 1,
                "reason_code": "ae.agent-lifecycle-sync",
            },
        ),
    ]


def test_missing_inactive_authority_does_not_create_membership() -> None:
    calls = []

    def requester(method, url, **kwargs):
        calls.append(method)
        return httpx.Response(404, json={})

    result = HttpOaAgentAuthoritySynchronizer(
        "https://oa.example", "signed-token", requester=requester
    ).synchronize(
        tenant_id=TENANT_ID,
        agent_id=AGENT_ID,
        agent_type="PA",
        status="INACTIVE",
    )

    assert calls == ["GET"]
    assert result["status"] == "DISABLED"


def test_managed_legacy_ia_authority_is_revision_guarded_and_reconciled() -> None:
    calls = []

    def requester(method, url, **kwargs):
        calls.append((method, url, kwargs.get("json")))
        if method == "GET":
            return httpx.Response(200, json=_membership(scopes=["work:delegate"]))
        return httpx.Response(
            200,
            json=_membership(
                scopes=["work:claim", "work:delegate"],
                revision=2,
            ),
        )

    result = HttpOaAgentAuthoritySynchronizer(
        "https://oa.example", "signed-token", requester=requester
    ).synchronize(
        tenant_id=TENANT_ID,
        agent_id=AGENT_ID,
        agent_type="IA",
        status="ACTIVE",
    )

    assert result["changed"] is True
    assert [item[0] for item in calls] == ["GET", "PUT"]
    assert calls[1][1].endswith(f"/tenants/{TENANT_ID}/subjects/{AGENT_ID}/authority")
    assert calls[1][2] == {
        "expected_revision": 1,
        "roles": ["nex-agent", "nex-agent-ia"],
        "scopes": ["work:claim", "work:delegate"],
    }


def test_unmanaged_authority_drift_is_not_overwritten() -> None:
    calls = []

    def requester(method, _url, **_kwargs):
        calls.append(method)
        return httpx.Response(
            200,
            json=_membership(scopes=["work:delegate"], managed=False),
        )

    synchronizer = HttpOaAgentAuthoritySynchronizer(
        "https://oa.example", "signed-token", requester=requester
    )
    with pytest.raises(AgentAuthoritySyncError) as raised:
        synchronizer.synchronize(
            tenant_id=TENANT_ID,
            agent_id=AGENT_ID,
            agent_type="IA",
            status="ACTIVE",
        )

    assert raised.value.error_code == "ae.agent_authority_scope_drift"
    assert calls == ["GET"]


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (_membership(scopes=["workspace:use"]), "ae.agent_authority_scope_drift"),
        ({"membership": {"status": "ACTIVE"}}, "ae.agent_authority_sync_invalid"),
    ],
)
def test_malformed_or_under_scoped_authority_fails_closed(response, code) -> None:
    synchronizer = HttpOaAgentAuthoritySynchronizer(
        "https://oa.example",
        "signed-token",
        requester=lambda *_args, **_kwargs: httpx.Response(200, json=response),
    )

    with pytest.raises(AgentAuthoritySyncError) as raised:
        synchronizer.synchronize(
            tenant_id=TENANT_ID,
            agent_id=AGENT_ID,
            agent_type="IA",
            status="ACTIVE",
        )
    assert raised.value.error_code == code


def test_http_failures_and_invalid_configuration_are_bounded() -> None:
    timeout = HttpOaAgentAuthoritySynchronizer(
        "https://oa.example",
        "signed-token",
        requester=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            httpx.ReadTimeout("slow")
        ),
    )
    with pytest.raises(AgentAuthoritySyncError, match="timed out") as raised:
        timeout.synchronize(
            tenant_id=TENANT_ID,
            agent_id=AGENT_ID,
            agent_type="IA",
            status="ACTIVE",
        )
    assert raised.value.retryable is True

    unavailable = HttpOaAgentAuthoritySynchronizer(
        "https://oa.example",
        "signed-token",
        requester=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            httpx.ConnectError("down")
        ),
    )
    with pytest.raises(AgentAuthoritySyncError, match="unavailable"):
        unavailable.synchronize(
            tenant_id=TENANT_ID,
            agent_id=AGENT_ID,
            agent_type="IA",
            status="ACTIVE",
        )

    missing_token = HttpOaAgentAuthoritySynchronizer(
        "https://oa.example", "", requester=lambda *_args, **_kwargs: None
    )
    with pytest.raises(AgentAuthoritySyncError, match="token is unavailable"):
        missing_token.synchronize(
            tenant_id=TENANT_ID,
            agent_id=AGENT_ID,
            agent_type="IA",
            status="ACTIVE",
        )

    assert build_agent_authority_synchronizer({}) is None
    with pytest.raises(AgentAuthoritySyncError, match="not configured"):
        build_agent_authority_synchronizer(
            {"NEX_AE_AGENT_AUTHORITY_SYNC_MODE": "required"}
        )
    with pytest.raises(AgentAuthoritySyncError, match="disabled or required"):
        build_agent_authority_synchronizer(
            {"NEX_AE_AGENT_AUTHORITY_SYNC_MODE": "sometimes"}
        )


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="not-json"),
        httpx.Response(200, json=["not", "an", "object"]),
        httpx.Response(403, json={"error_code": "oa.agent_authority_denied"}),
    ],
)
def test_invalid_or_rejected_oa_response_fails_closed(response) -> None:
    synchronizer = HttpOaAgentAuthoritySynchronizer(
        "https://oa.example",
        "signed-token",
        requester=lambda *_args, **_kwargs: response,
    )
    with pytest.raises(AgentAuthoritySyncError):
        synchronizer.synchronize(
            tenant_id=TENANT_ID,
            agent_id=AGENT_ID,
            agent_type="IA",
            status="ACTIVE",
        )


@pytest.mark.parametrize(
    "membership",
    [
        _membership(status="UNKNOWN"),
        {
            "membership": {
                **_membership()["membership"],
                "revision": 0,
            }
        },
        {
            "membership": {
                **_membership()["membership"],
                "scopes": "work:delegate",
            }
        },
    ],
)
def test_invalid_membership_status_revision_or_scope_shape_is_rejected(
    membership,
) -> None:
    synchronizer = HttpOaAgentAuthoritySynchronizer(
        "https://oa.example",
        "signed-token",
        requester=lambda *_args, **_kwargs: httpx.Response(200, json=membership),
    )
    with pytest.raises(AgentAuthoritySyncError):
        synchronizer.synchronize(
            tenant_id=TENANT_ID,
            agent_id=AGENT_ID,
            agent_type="IA",
            status="ACTIVE",
        )


def test_lifecycle_binding_and_input_validation_fail_closed() -> None:
    responses = iter(
        [
            httpx.Response(
                200,
                json=_membership(
                    scopes=["work:claim", "work:delegate", "work:result:submit"],
                    agent_type="PA",
                ),
            ),
            httpx.Response(
                200,
                json={
                    "tenant_id": TENANT_ID,
                    "subject_id": "different-agent",
                    "status": "DISABLED",
                    "revision": 2,
                },
            ),
        ]
    )
    synchronizer = HttpOaAgentAuthoritySynchronizer(
        "https://oa.example",
        "signed-token",
        requester=lambda *_args, **_kwargs: next(responses),
    )
    with pytest.raises(AgentAuthoritySyncError, match="not applied"):
        synchronizer.synchronize(
            tenant_id=TENANT_ID,
            agent_id=AGENT_ID,
            agent_type="PA",
            status="RETIRED",
        )

    for kwargs in (
        {"tenant_id": "", "agent_id": AGENT_ID, "agent_type": "IA"},
        {"tenant_id": TENANT_ID, "agent_id": AGENT_ID, "agent_type": "BOT"},
    ):
        with pytest.raises(AgentAuthoritySyncError):
            synchronizer.synchronize(status="ACTIVE", **kwargs)

    for timeout in ("zero", "0"):
        with pytest.raises(AgentAuthoritySyncError, match="timeout"):
            build_agent_authority_synchronizer(
                {
                    "NEX_AE_AGENT_AUTHORITY_SYNC_MODE": "required",
                    "NEX_OA_BASE_URL": "https://oa.example",
                    "NEX_AE_TO_OA_SERVICE_TOKEN": "signed-token",
                    "NEX_AE_AGENT_AUTHORITY_SYNC_TIMEOUT_SECONDS": timeout,
                }
            )


def test_required_builder_uses_canonical_oa_binding() -> None:
    result = build_agent_authority_synchronizer(
        {
            "NEX_AE_AGENT_AUTHORITY_SYNC_MODE": "required",
            "NEX_OA_BASE_URL": "https://oa.example",
            "NEX_AE_TO_OA_SERVICE_TOKEN": "signed-token",
            "NEX_AE_AGENT_AUTHORITY_SYNC_TIMEOUT_SECONDS": "7.5",
        }
    )

    assert isinstance(result, HttpOaAgentAuthoritySynchronizer)
    assert result.timeout_seconds == 7.5
