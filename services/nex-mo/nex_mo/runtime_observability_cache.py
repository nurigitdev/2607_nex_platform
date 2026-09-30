from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from threading import Lock
from typing import Callable

from nex_mo.runtime_observability import (
    ModelRuntimeSnapshot,
    RUNTIME_CACHE_STATUSES,
)


RUNTIME_CACHE_LOOKUP_STATUSES = {"MISS", "FRESH", "STALE"}
RefreshRuntimeObservation = Callable[[], ModelRuntimeSnapshot]


@dataclass(frozen=True)
class RuntimeObservationCacheLookup:
    status: str
    snapshot: ModelRuntimeSnapshot | None

    def __post_init__(self) -> None:
        if self.status not in RUNTIME_CACHE_LOOKUP_STATUSES:
            raise ValueError("unsupported runtime cache lookup status")
        if (self.status == "MISS") != (self.snapshot is None):
            raise ValueError("runtime cache miss must not contain a snapshot")


class InMemoryRuntimeObservationStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self._snapshot: ModelRuntimeSnapshot | None = None

    def read(self, *, now: datetime | None = None) -> RuntimeObservationCacheLookup:
        with self._lock:
            return self._read_unlocked(_utc_datetime(now))

    def save(self, snapshot: ModelRuntimeSnapshot) -> None:
        with self._lock:
            self._snapshot = snapshot

    def clear(self) -> None:
        with self._lock:
            self._snapshot = None

    def resolve(
        self,
        refresh: RefreshRuntimeObservation,
        *,
        now: datetime | None = None,
        force_refresh: bool = False,
    ) -> ModelRuntimeSnapshot:
        observed_at = _utc_datetime(now)
        with self._lock:
            lookup = self._read_unlocked(observed_at)
            if lookup.status == "FRESH" and not force_refresh:
                assert lookup.snapshot is not None
                return lookup.snapshot

            previous = self._snapshot
            try:
                candidate = refresh()
            except Exception:
                if previous is None:
                    raise
                stale = with_runtime_cache_status(previous, "STALE")
                self._snapshot = stale
                return stale

            status = "REFRESHED" if previous is not None else "FRESH"
            resolved = with_runtime_cache_status(candidate, status)
            self._snapshot = resolved
            return resolved

    def _read_unlocked(self, now: datetime) -> RuntimeObservationCacheLookup:
        if self._snapshot is None:
            return RuntimeObservationCacheLookup("MISS", None)
        if self._snapshot.cache_status == "STALE":
            return RuntimeObservationCacheLookup("STALE", self._snapshot)
        if now >= _parse_timestamp(self._snapshot.expires_at):
            stale = with_runtime_cache_status(self._snapshot, "STALE")
            self._snapshot = stale
            return RuntimeObservationCacheLookup("STALE", stale)
        return RuntimeObservationCacheLookup("FRESH", self._snapshot)


def with_runtime_cache_status(
    snapshot: ModelRuntimeSnapshot,
    cache_status: str,
) -> ModelRuntimeSnapshot:
    if cache_status not in RUNTIME_CACHE_STATUSES:
        raise ValueError("unsupported runtime cache status")
    if cache_status == "STALE":
        return replace(
            snapshot,
            runtime_status="UNKNOWN",
            cache_status="STALE",
            failure_code="runtime_observation_stale",
        )
    return replace(snapshot, cache_status=cache_status)


def _utc_datetime(value: datetime | None) -> datetime:
    selected = value or datetime.now(UTC)
    if selected.tzinfo is None:
        raise ValueError("runtime cache time must include a timezone")
    return selected.astimezone(UTC)


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
