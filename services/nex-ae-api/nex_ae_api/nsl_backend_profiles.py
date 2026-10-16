from __future__ import annotations

NSL_V01_IN_PROCESS_BACKEND = "NSL_V01_IN_PROCESS"
NSL_V01_PROCESS_ISOLATED_BACKEND = "NSL_V01_PROCESS_ISOLATED"

DEFAULT_NSL_V01_BACKEND_PROFILE = NSL_V01_IN_PROCESS_BACKEND
NSL_V01_BACKEND_PROFILES = frozenset(
    {
        NSL_V01_IN_PROCESS_BACKEND,
        NSL_V01_PROCESS_ISOLATED_BACKEND,
    }
)


def normalize_nsl_backend_profile(value: object) -> str:
    if not isinstance(value, str) or value not in NSL_V01_BACKEND_PROFILES:
        raise ValueError("NSL v0.1 backend profile is unsupported.")
    return value
