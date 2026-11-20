from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from nex_ae_api.runtime_jobs import RuntimeJobClaim
from nex_ae_api.step_executors import ContinuationSource


@dataclass(frozen=True)
class RuntimeContinuationSourceError(Exception):
    error_code: str
    detail: str
    retryable: bool = False

    def __str__(self) -> str:
        return self.detail


class RuntimeContinuationSourceRegistry:
    """Route one running resume claim to its exact durable authority source."""

    def __init__(
        self,
        sources: Mapping[frozenset[str], ContinuationSource],
    ) -> None:
        admitted: dict[frozenset[str], ContinuationSource] = {}
        for fields, source in sources.items():
            key = frozenset(fields)
            if not key or any(not isinstance(field, str) or not field for field in key):
                raise _invalid("Continuation source payload fields are invalid.")
            if not callable(getattr(source, "resolve", None)):
                raise _invalid("Continuation source must implement resolve().")
            admitted[key] = source
        if not admitted:
            raise _invalid("At least one continuation source is required.")
        self._sources = MappingProxyType(admitted)

    def resolve(self, claim: RuntimeJobClaim) -> Mapping[str, Any]:
        if not isinstance(claim, RuntimeJobClaim):
            raise _invalid("Continuation routing requires a RuntimeJobClaim.")
        job = claim.job
        payload = job.get("payload")
        if job.get("job_type") != "RESUME_EXECUTION" or not isinstance(
            payload, Mapping
        ):
            raise _invalid("Continuation routing requires a resume payload.")
        source = self._sources.get(frozenset(payload))
        if source is None:
            raise RuntimeContinuationSourceError(
                "ae.runtime_continuation_source_not_found",
                "No durable continuation source admits the resume payload contract.",
            )
        return source.resolve(claim)


def _invalid(detail: str) -> RuntimeContinuationSourceError:
    return RuntimeContinuationSourceError(
        "ae.runtime_continuation_source_invalid",
        detail,
    )
