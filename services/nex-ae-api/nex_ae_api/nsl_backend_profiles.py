from __future__ import annotations

NSL_V01_IN_PROCESS_BACKEND = "NSL_V01_IN_PROCESS"
NSL_V01_PROCESS_ISOLATED_BACKEND = "NSL_V01_PROCESS_ISOLATED"
NSL_V02_IN_PROCESS_BACKEND = "NSL_V02_IN_PROCESS"

DEFAULT_NSL_V01_BACKEND_PROFILE = NSL_V01_IN_PROCESS_BACKEND
NSL_V01_BACKEND_PROFILES = frozenset(
    {
        NSL_V01_IN_PROCESS_BACKEND,
        NSL_V01_PROCESS_ISOLATED_BACKEND,
    }
)
NSL_V02_BACKEND_PROFILES = frozenset({NSL_V02_IN_PROCESS_BACKEND})
NSL_BACKEND_PROFILES = NSL_V01_BACKEND_PROFILES | NSL_V02_BACKEND_PROFILES
NSL_OPERATION_SEMANTICS = frozenset({"READ", "WRITE"})


def normalize_nsl_backend_profile(value: object) -> str:
    if not isinstance(value, str) or value not in NSL_BACKEND_PROFILES:
        raise ValueError("NSL backend profile is unsupported.")
    return value


def normalize_nsl_backend_profile_for_operation(
    value: object, operation_semantics: object
) -> str:
    profile = normalize_nsl_backend_profile(value)
    if (
        not isinstance(operation_semantics, str)
        or operation_semantics not in NSL_OPERATION_SEMANTICS
    ):
        raise ValueError("NSL operation semantics is unsupported.")
    if operation_semantics == "WRITE" and profile != NSL_V02_IN_PROCESS_BACKEND:
        raise ValueError("NSL WRITE requires the v0.2 in-process profile.")
    return profile
