from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol


class AuthorizationSource(Protocol):
    def effective_authorization(
        self, *, tenant_id: str, subject_id: str
    ) -> Mapping[str, Any]: ...


class AuthorizationSubjectDenied(RuntimeError):
    pass


def require_active_scope(
    authorization: object,
    *,
    required_scope: str,
) -> str:
    if not isinstance(authorization, Mapping):
        raise AuthorizationSubjectDenied("OA authorization response is malformed.")
    scopes = authorization.get("scopes")
    revision_hash = authorization.get("revision_hash")
    if (
        authorization.get("active") is not True
        or not isinstance(scopes, Sequence)
        or isinstance(scopes, (str, bytes))
        or required_scope not in scopes
        or not isinstance(revision_hash, str)
        or not revision_hash.strip()
        or len(revision_hash) > 256
    ):
        raise AuthorizationSubjectDenied(
            f"Requester lacks active {required_scope} authority."
        )
    return revision_hash
