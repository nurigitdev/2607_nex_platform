from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request

import pytest
from nex_runtime.rustfs_iam import (
    RustfsAdminClient,
    RustfsIamError,
    _urlopen_transport,
    bucket_owner_policy,
)


def _client(calls: list[Request], responses=None) -> RustfsAdminClient:
    queued = list(responses or [(200, b"") for _ in range(3)])

    def transport(request: Request, timeout: float):
        assert timeout == 10.0
        calls.append(request)
        return queued.pop(0)

    return RustfsAdminClient(
        "http://127.0.0.1:19000",
        access_key="root-access-key",
        secret_key="root-secret-key-value",
        allow_insecure=True,
        transport=transport,
    )


def test_bucket_owner_policy_is_exactly_bucket_scoped() -> None:
    policy = bucket_owner_policy("nex-cx-private")
    serialized = json.dumps(policy)
    assert "arn:aws:s3:::nex-cx-private" in serialized
    assert "arn:aws:s3:::nex-cx-private/*" in serialized
    assert "admin:" not in serialized
    assert "s3:*" not in serialized

    for invalid in ("ab", "UPPER", "bad..bucket", "bad.-bucket"):
        with pytest.raises(RustfsIamError) as caught:
            bucket_owner_policy(invalid)
        assert caught.value.code == "RUSTFS_IAM_BUCKET_INVALID"


def test_provision_bucket_owner_signs_all_admin_requests() -> None:
    calls: list[Request] = []
    result = _client(calls).provision_bucket_owner(
        access_key="cx-service-key",
        secret_key="cx-service-secret-value",
        bucket="nex-cx-private",
        policy_name="nex-cx-private-rw",
    )
    assert result["status"] == "PROVISIONED"
    assert len(calls) == 3
    assert all(call.get_header("Authorization").startswith("AWS4-HMAC-SHA256") for call in calls)
    assert all(len(call.get_header("X-amz-content-sha256")) == 64 for call in calls)
    assert "add-canned-policy" in calls[0].full_url
    assert json.loads(calls[0].data)["Version"] == "2012-10-17"
    assert "add-user" in calls[1].full_url
    assert "set-user-or-group-policy" in calls[2].full_url


def test_admin_client_validates_configuration_request_identity_and_response() -> None:
    with pytest.raises(RustfsIamError):
        RustfsAdminClient(
            "http://127.0.0.1:9000",
            access_key="short",
            secret_key="short",
        )
    with pytest.raises(RustfsIamError) as invalid_configuration:
        RustfsAdminClient(
            "https://rustfs.example.test",
            access_key="valid-access",
            secret_key="valid-secret-value",
            region="",
        )
    assert str(invalid_configuration.value) == invalid_configuration.value.detail
    with pytest.raises(RustfsIamError):
        RustfsAdminClient(
            "http://127.0.0.1:9000",
            access_key="valid-access",
            secret_key="valid-secret-value",
        )

    calls: list[Request] = []
    client = _client(calls, [(200, b'{"status":"ok"}')])
    assert client.request("GET", "/rustfs/admin/v3/list-users") == {
        "status": "ok"
    }
    with pytest.raises(RustfsIamError) as invalid_request:
        client.request("PATCH", "/outside")
    assert invalid_request.value.code == "RUSTFS_IAM_REQUEST_INVALID"
    with pytest.raises(RustfsIamError) as invalid_identity:
        client.provision_bucket_owner(
            access_key="short",
            secret_key="short",
            bucket="nex-cx-private",
            policy_name="bad name",
        )
    assert invalid_identity.value.code == "RUSTFS_IAM_IDENTITY_INVALID"


@pytest.mark.parametrize(
    ("response", "code", "retryable"),
    [
        ((403, b"denied"), "RUSTFS_IAM_REQUEST_FAILED_403", False),
        ((503, b"down"), "RUSTFS_IAM_REQUEST_FAILED_503", True),
        ((200, b"not-json"), "RUSTFS_IAM_RESPONSE_INVALID", False),
        ((200, b"[]"), "RUSTFS_IAM_RESPONSE_INVALID", False),
        ((200, b"x" * 2_097_153), "RUSTFS_IAM_RESPONSE_INVALID", False),
    ],
)
def test_admin_client_maps_remote_failures(response, code, retryable) -> None:
    client = _client([], [response])
    with pytest.raises(RustfsIamError) as caught:
        client.request("GET", "/rustfs/admin/v3/list-users")
    assert caught.value.code == code
    assert caught.value.retryable is retryable


def test_admin_client_maps_transport_failure() -> None:
    def broken(_request, _timeout):
        raise RuntimeError("private transport detail")

    client = RustfsAdminClient(
        "https://rustfs.example.test",
        access_key="root-access-key",
        secret_key="root-secret-key-value",
        transport=broken,
    )
    with pytest.raises(RustfsIamError) as caught:
        client.request("GET", "/rustfs/admin/v3/list-users")
    assert caught.value.code == "RUSTFS_IAM_TRANSPORT_FAILED"
    assert "private transport detail" not in caught.value.detail

    propagated = RustfsIamError("EXPECTED", "safe", True)

    def known_failure(_request, _timeout):
        raise propagated

    known = RustfsAdminClient(
        "https://rustfs.example.test",
        access_key="root-access-key",
        secret_key="root-secret-key-value",
        transport=known_failure,
    )
    with pytest.raises(RustfsIamError) as known_caught:
        known.request("GET", "/rustfs/admin/v3/list-users")
    assert known_caught.value is propagated


def test_default_transport_maps_success_http_and_network_errors(monkeypatch) -> None:
    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, _limit):
            return b"{}"

    monkeypatch.setattr("nex_runtime.rustfs_iam.urlopen", lambda *_args, **_kwargs: Response())
    request = Request("https://rustfs.example.test/rustfs/admin/v3/list-users")
    assert _urlopen_transport(request, 1.0) == (200, b"{}")

    denied = HTTPError(request.full_url, 403, "denied", {}, None)
    denied.read = lambda _limit: b"denied"  # type: ignore[method-assign]
    monkeypatch.setattr(
        "nex_runtime.rustfs_iam.urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(denied),
    )
    assert _urlopen_transport(request, 1.0) == (403, b"denied")

    monkeypatch.setattr(
        "nex_runtime.rustfs_iam.urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(URLError("private")),
    )
    with pytest.raises(RustfsIamError) as unavailable:
        _urlopen_transport(request, 1.0)
    assert unavailable.value.code == "RUSTFS_IAM_TRANSPORT_FAILED"
