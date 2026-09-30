from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from threading import Lock
from typing import Callable

from nex_mo.provider_readiness import CACHE_STATUSES, ProviderReadinessSnapshot


CACHE_LOOKUP_STATUSES = {"MISS", "FRESH", "STALE"}
RefreshProviderReadiness = Callable[[], ProviderReadinessSnapshot]


@dataclass(frozen=True)
class ProviderReadinessCacheLookup:
    status: str
    snapshot: ProviderReadinessSnapshot | None

    def __post_init__(self) -> None:
        if self.status not in CACHE_LOOKUP_STATUSES:
            raise ValueError("unsupported cache lookup status")
        if (self.status == "MISS") != (self.snapshot is None):
            raise ValueError("cache miss must not contain a snapshot")


class InMemoryProviderReadinessStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self._snapshot: ProviderReadinessSnapshot | None = None

    def read(self, *, now: datetime | None = None) -> ProviderReadinessCacheLookup:
        with self._lock:
            return self._read_unlocked(_utc_datetime(now))

    def save(self, snapshot: ProviderReadinessSnapshot) -> None:
        with self._lock:
            self._snapshot = snapshot

    def clear(self) -> None:
        with self._lock:
            self._snapshot = None

    def resolve(
        self,
        refresh: RefreshProviderReadiness,
        *,
        now: datetime | None = None,
        force_refresh: bool = False,
    ) -> ProviderReadinessSnapshot:
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
                stale = with_cache_status(previous, "STALE")
                self._snapshot = stale
                return stale

            cache_status = "REFRESHED" if previous is not None else "FRESH"
            resolved = with_cache_status(candidate, cache_status)
            self._snapshot = resolved
            return resolved

    def _read_unlocked(self, now: datetime) -> ProviderReadinessCacheLookup:
        if self._snapshot is None:
            return ProviderReadinessCacheLookup("MISS", None)
        if self._snapshot.cache_status == "STALE":
            return ProviderReadinessCacheLookup("STALE", self._snapshot)
        expires_at = _parse_timestamp(self._snapshot.expires_at)
        if now >= expires_at:
            stale = with_cache_status(self._snapshot, "STALE")
            self._snapshot = stale
            return ProviderReadinessCacheLookup("STALE", stale)
        return ProviderReadinessCacheLookup("FRESH", self._snapshot)


def with_cache_status(
    snapshot: ProviderReadinessSnapshot,
    cache_status: str,
) -> ProviderReadinessSnapshot:
    if cache_status not in CACHE_STATUSES:
        raise ValueError("unsupported cache status")
    if cache_status == "STALE":
        return replace(
            snapshot,
            readiness_status="NOT_READY",
            cache_status="STALE",
            failure_code="provider_readiness_snapshot_stale",
        )
    return replace(snapshot, cache_status=cache_status)


def _utc_datetime(value: datetime | None) -> datetime:
    selected = value or datetime.now(UTC)
    if selected.tzinfo is None:
        raise ValueError("cache time must include a timezone")
    return selected.astimezone(UTC)


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
