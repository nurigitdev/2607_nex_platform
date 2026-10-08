from __future__ import annotations

import hashlib
import importlib
import json
import ssl
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class RustfsIamError(RuntimeError):
    code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


AdminTransport = Callable[[Request, float], tuple[int, bytes]]


def bucket_owner_policy(bucket: str) -> dict[str, Any]:
    if not _bucket_name(bucket):
        raise RustfsIamError(
            "RUSTFS_IAM_BUCKET_INVALID",
            "RustFS IAM bucket name is invalid.",
        )
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "BucketMetadata",
                "Effect": "Allow",
                "Action": ["s3:GetBucketLocation", "s3:ListBucket"],
                "Resource": [f"arn:aws:s3:::{bucket}"],
            },
            {
                "Sid": "PrivateObjectLifecycle",
                "Effect": "Allow",
                "Action": [
                    "s3:DeleteObject",
                    "s3:GetObject",
                    "s3:GetObjectTagging",
                    "s3:GetObjectVersion",
                    "s3:GetObjectVersionTagging",
                    "s3:PutObject",
                    "s3:PutObjectTagging",
                    "s3:PutObjectVersionTagging",
                ],
                "Resource": [f"arn:aws:s3:::{bucket}/*"],
            },
        ],
    }


class RustfsAdminClient:
    def __init__(
        self,
        endpoint: str,
        *,
        access_key: str,
        secret_key: str,
        region: str = "us-east-1",
        allow_insecure: bool = False,
        timeout_seconds: float = 10.0,
        ca_bundle: str | None = None,
        transport: AdminTransport | None = None,
    ) -> None:
        parsed = urlsplit(endpoint.strip().rstrip("/"))
        allowed = {"https"} | ({"http"} if allow_insecure else set())
        if (
            parsed.scheme not in allowed
            or not parsed.hostname
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
            or parsed.username
            or parsed.password
        ):
            raise RustfsIamError(
                "RUSTFS_IAM_ENDPOINT_INVALID",
                "RustFS admin endpoint is invalid.",
            )
        if (
            len(access_key.strip()) < 8
            or len(secret_key.strip()) < 16
            or not region.strip()
            or timeout_seconds <= 0
        ):
            raise RustfsIamError(
                "RUSTFS_IAM_CONFIGURATION_INVALID",
                "RustFS admin configuration is invalid.",
            )
        self._endpoint = endpoint.strip().rstrip("/")
        self._access_key = access_key.strip()
        self._secret_key = secret_key.strip()
        self._region = region.strip()
        self._timeout_seconds = timeout_seconds
        self._transport = transport or (
            lambda request, timeout: _urlopen_transport(
                request, timeout, ca_bundle=ca_bundle
            )
        )

    def provision_bucket_owner(
        self,
        *,
        access_key: str,
        secret_key: str,
        bucket: str,
        policy_name: str,
    ) -> dict[str, Any]:
        if (
            len(access_key.strip()) < 8
            or len(secret_key.strip()) < 16
            or not _policy_name(policy_name)
        ):
            raise RustfsIamError(
                "RUSTFS_IAM_IDENTITY_INVALID",
                "RustFS IAM identity is invalid.",
            )
        policy = bucket_owner_policy(bucket)
        self.request(
            "PUT",
            "/rustfs/admin/v3/add-canned-policy",
            query={"name": policy_name},
            payload=policy,
        )
        self.request(
            "PUT",
            "/rustfs/admin/v3/add-user",
            query={"accessKey": access_key},
            payload={"secretKey": secret_key, "status": "enabled"},
        )
        self.request(
            "PUT",
            "/rustfs/admin/v3/set-user-or-group-policy",
            query={
                "policyName": policy_name,
                "userOrGroup": access_key,
                "isGroup": "false",
            },
        )
        return {
            "schema_version": "rustfs_bucket_owner_provision.v1",
            "status": "PROVISIONED",
            "policy_name": policy_name,
            "bucket_scope_count": 1,
            "root_credential_reused": False,
        }

    def request(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, str] | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        normalized_method = method.strip().upper()
        if normalized_method not in {"DELETE", "GET", "POST", "PUT"} or not path.startswith(
            "/rustfs/admin/v3/"
        ):
            raise RustfsIamError(
                "RUSTFS_IAM_REQUEST_INVALID",
                "RustFS admin request is invalid.",
            )
        encoded_query = urlencode(sorted((query or {}).items()))
        url = f"{self._endpoint}{path}"
        if encoded_query:
            url = f"{url}?{encoded_query}"
        body = (
            json.dumps(dict(payload), sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
            if payload is not None
            else None
        )
        headers = {"Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        signed = self._signed_request(normalized_method, url, headers, body)
        try:
            status, raw = self._transport(signed, self._timeout_seconds)
        except RustfsIamError:
            raise
        except Exception as exc:
            raise RustfsIamError(
                "RUSTFS_IAM_TRANSPORT_FAILED",
                "RustFS admin transport failed.",
                True,
            ) from exc
        if status < 200 or status >= 300:
            raise RustfsIamError(
                f"RUSTFS_IAM_REQUEST_FAILED_{status}",
                f"RustFS admin request failed: {path} status={status}.",
                status == 429 or status >= 500,
            )
        if not raw:
            return {}
        if len(raw) > 2_097_152:
            raise RustfsIamError(
                "RUSTFS_IAM_RESPONSE_INVALID",
                "RustFS admin response is invalid.",
            )
        try:
            decoded = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise RustfsIamError(
                "RUSTFS_IAM_RESPONSE_INVALID",
                "RustFS admin response is invalid.",
            ) from None
        if not isinstance(decoded, Mapping):
            raise RustfsIamError(
                "RUSTFS_IAM_RESPONSE_INVALID",
                "RustFS admin response is invalid.",
            )
        return decoded

    def _signed_request(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
    ) -> Request:
        awsrequest = importlib.import_module("botocore.awsrequest")
        auth = importlib.import_module("botocore.auth")
        credentials = importlib.import_module("botocore.credentials")
        request = awsrequest.AWSRequest(
            method=method,
            url=url,
            data=body,
            headers={
                **dict(headers),
                "X-Amz-Content-SHA256": hashlib.sha256(body or b"").hexdigest(),
            },
        )
        auth.SigV4Auth(
            credentials.Credentials(self._access_key, self._secret_key),
            "s3",
            self._region,
        ).add_auth(request)
        prepared = request.prepare()
        return Request(
            prepared.url,
            data=body,
            headers=dict(prepared.headers.items()),
            method=method,
        )


def _urlopen_transport(
    request: Request,
    timeout_seconds: float,
    *,
    ca_bundle: str | None = None,
) -> tuple[int, bytes]:
    context = ssl.create_default_context(cafile=ca_bundle) if ca_bundle else None
    try:
        with urlopen(request, timeout=timeout_seconds, context=context) as response:
            return response.status, response.read(2_097_153)
    except HTTPError as exc:
        return exc.code, exc.read(2_097_153)
    except (URLError, OSError, TimeoutError) as exc:
        raise RustfsIamError(
            "RUSTFS_IAM_TRANSPORT_FAILED",
            "RustFS admin transport failed.",
            True,
        ) from exc


def _bucket_name(value: str) -> bool:
    text = str(value).strip()
    return (
        3 <= len(text) <= 63
        and text[0].isalnum()
        and text[-1].isalnum()
        and all(character.islower() or character.isdigit() or character in ".-" for character in text)
        and ".." not in text
        and ".-" not in text
        and "-." not in text
    )


def _policy_name(value: str) -> bool:
    text = str(value).strip()
    return 1 <= len(text) <= 128 and all(
        character.isalnum() or character in "-_." for character in text
    )
