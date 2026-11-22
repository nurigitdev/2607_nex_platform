from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DIAGNOSTIC_EVIDENCE_SCHEMA_VERSION = "diagnostic_evidence_event.v1"
DIAGNOSTIC_EVIDENCE_MANIFEST_SCHEMA_VERSION = "diagnostic_evidence_manifest.v1"
DIAGNOSTIC_EVIDENCE_MODES = frozenset({"OFF", "METADATA", "LIVE_JOURNEY"})
DIAGNOSTIC_EVIDENCE_MODE_ENV = "NEX_DIAGNOSTIC_EVIDENCE_MODE"
DIAGNOSTIC_EVIDENCE_ROOT_ENV = "NEX_DIAGNOSTIC_EVIDENCE_ROOT"
DIAGNOSTIC_EVIDENCE_SESSION_ENV = "NEX_DIAGNOSTIC_EVIDENCE_SESSION_ID"
DIAGNOSTIC_EVIDENCE_RAW_ENV = "NEX_DIAGNOSTIC_EVIDENCE_INCLUDE_RAW"
DIAGNOSTIC_EVIDENCE_RETENTION_ENV = "NEX_DIAGNOSTIC_EVIDENCE_RETENTION_DAYS"
DEFAULT_DIAGNOSTIC_EVIDENCE_RETENTION_DAYS = 7
MAX_DIAGNOSTIC_EVIDENCE_RETENTION_DAYS = 30
REDACTED_DIAGNOSTIC_VALUE = "<redacted>"
OMITTED_DIAGNOSTIC_VALUE = "<omitted:metadata-mode>"

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_RAW_PAYLOAD_KEYS = frozenset(
    {
        "agent_plan",
        "candidate",
        "context_candidate",
        "executable_plan",
        "execution_plan",
        "intent_candidate",
        "messages",
        "plan_candidate",
        "prompt",
        "provider_request",
        "provider_response",
        "raw_prompt",
        "request_body",
        "response_body",
        "step_input",
        "step_output",
        "tool_input",
        "tool_output",
        "user_prompt",
        "work_intent",
    }
)
_SECRET_EXACT_KEYS = frozenset(
    {
        "api_key",
        "authorization",
        "client_secret",
        "cookie",
        "credential",
        "database_url",
        "lease_token",
        "password",
        "passwd",
        "private_key",
        "resume_token",
        "secret",
        "service_token",
        "set_cookie",
        "token",
    }
)
_SECRET_KEY_PARTS = (
    "api_key",
    "authorization",
    "client_secret",
    "cookie",
    "credential",
    "database_url",
    "lease_token",
    "password",
    "private_key",
    "refresh_token",
    "resume_token",
    "secret_key",
    "service_token",
    "access_token",
    "token_value",
)
_GENESIS_DIGEST = "0" * 64


@dataclass(frozen=True)
class DiagnosticEvidenceError(Exception):
    error_code: str
    detail: str

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class DiagnosticEvidencePolicy:
    mode: str
    root: Path | None = None
    session_id: str | None = None
    include_raw: bool = False
    retention_days: int = DEFAULT_DIAGNOSTIC_EVIDENCE_RETENTION_DAYS

    @property
    def enabled(self) -> bool:
        return self.mode != "OFF"

    @classmethod
    def from_environment(
        cls, environ: Mapping[str, str] | None = None
    ) -> DiagnosticEvidencePolicy:
        env = os.environ if environ is None else environ
        mode = str(env.get(DIAGNOSTIC_EVIDENCE_MODE_ENV, "OFF")).strip().upper()
        if mode not in DIAGNOSTIC_EVIDENCE_MODES:
            raise DiagnosticEvidenceError(
                "diagnostic_evidence.mode_invalid",
                "diagnostic evidence mode must be OFF, METADATA, or LIVE_JOURNEY",
            )
        if mode == "OFF":
            return cls(mode="OFF")
        root_value = str(env.get(DIAGNOSTIC_EVIDENCE_ROOT_ENV, "")).strip()
        session_id = str(env.get(DIAGNOSTIC_EVIDENCE_SESSION_ENV, "")).strip()
        if not root_value:
            raise DiagnosticEvidenceError(
                "diagnostic_evidence.root_required",
                "enabled diagnostic evidence requires a dedicated root",
            )
        _require_identifier(session_id, "session_id")
        include_raw = _boolean(
            env.get(DIAGNOSTIC_EVIDENCE_RAW_ENV, "false"),
            DIAGNOSTIC_EVIDENCE_RAW_ENV,
        )
        if mode == "LIVE_JOURNEY" and not include_raw:
            raise DiagnosticEvidenceError(
                "diagnostic_evidence.raw_required",
                "LIVE_JOURNEY evidence requires explicit raw payload admission",
            )
        if mode != "LIVE_JOURNEY" and include_raw:
            raise DiagnosticEvidenceError(
                "diagnostic_evidence.raw_mode_invalid",
                "raw payload evidence is allowed only in LIVE_JOURNEY mode",
            )
        retention_days = _positive_integer(
            env.get(
                DIAGNOSTIC_EVIDENCE_RETENTION_ENV,
                str(DEFAULT_DIAGNOSTIC_EVIDENCE_RETENTION_DAYS),
            ),
            DIAGNOSTIC_EVIDENCE_RETENTION_ENV,
        )
        if retention_days > MAX_DIAGNOSTIC_EVIDENCE_RETENTION_DAYS:
            raise DiagnosticEvidenceError(
                "diagnostic_evidence.retention_invalid",
                f"diagnostic evidence retention must not exceed "
                f"{MAX_DIAGNOSTIC_EVIDENCE_RETENTION_DAYS} days",
            )
        return cls(
            mode=mode,
            root=Path(root_value).expanduser(),
            session_id=session_id,
            include_raw=include_raw,
            retention_days=retention_days,
        )


@dataclass(frozen=True)
class DiagnosticEvidenceRecorder:
    policy: DiagnosticEvidencePolicy
    service_id: str
    component: str

    def __post_init__(self) -> None:
        _require_identifier(self.service_id, "service_id")
        _require_identifier(self.component, "component")

    def emit(
        self,
        event_type: str,
        payload: Mapping[str, Any],
        *,
        trace_id: str | None = None,
        request_id: str | None = None,
        interaction_id: str | None = None,
        agent_execution_id: str | None = None,
        runtime_job_id: str | None = None,
        observed_at: str | None = None,
    ) -> dict[str, Any] | None:
        if not self.policy.enabled:
            return None
        _require_identifier(event_type, "event_type")
        if not isinstance(payload, Mapping):
            raise DiagnosticEvidenceError(
                "diagnostic_evidence.payload_invalid",
                "diagnostic evidence payload must be an object",
            )
        session_directory = self._session_directory()
        path = session_directory / (
            f"{self.service_id}--{self.component}--{os.getpid()}.jsonl"
        )
        sanitized, redacted_paths, raw_paths = _sanitize_payload(
            payload,
            include_raw=self.policy.include_raw,
        )
        with path.open("a+", encoding="utf-8") as stream:
            os.chmod(path, 0o600)
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            sequence, previous_digest = _last_chain_state(stream)
            body = {
                "schema_version": DIAGNOSTIC_EVIDENCE_SCHEMA_VERSION,
                "session_id": self.policy.session_id,
                "sequence": sequence + 1,
                "service_id": self.service_id,
                "component": self.component,
                "event_type": event_type,
                "observed_at": observed_at or _utc_now(),
                "correlation": {
                    "trace_id": trace_id,
                    "request_id": request_id,
                    "interaction_id": interaction_id,
                    "agent_execution_id": agent_execution_id,
                    "runtime_job_id": runtime_job_id,
                },
                "payload": sanitized,
                "payload_sha256": _sha256_json(sanitized),
                "raw_payload_included": bool(raw_paths),
                "raw_payload_paths": sorted(raw_paths),
                "secret_redacted_paths": sorted(redacted_paths),
                "previous_event_sha256": previous_digest,
                "retention_days": self.policy.retention_days,
            }
            event = {**body, "event_sha256": _sha256_json(body)}
            stream.seek(0, os.SEEK_END)
            stream.write(_canonical_json(event) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        return event

    def _session_directory(self) -> Path:
        if self.policy.root is None or self.policy.session_id is None:
            raise DiagnosticEvidenceError(
                "diagnostic_evidence.policy_incomplete",
                "enabled diagnostic evidence policy is incomplete",
            )
        root = self.policy.root.resolve()
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(root, 0o700)
        session = root / self.policy.session_id
        session.mkdir(exist_ok=True, mode=0o700)
        os.chmod(session, 0o700)
        return session


def diagnostic_evidence_recorder_from_environment(
    *,
    service_id: str,
    component: str,
    environ: Mapping[str, str] | None = None,
) -> DiagnosticEvidenceRecorder:
    return DiagnosticEvidenceRecorder(
        DiagnosticEvidencePolicy.from_environment(environ),
        service_id=service_id,
        component=component,
    )


def write_diagnostic_evidence_manifest(
    policy: DiagnosticEvidencePolicy,
    *,
    metadata: Mapping[str, Any] | None = None,
    observed_at: str | None = None,
) -> dict[str, Any]:
    if not policy.enabled or policy.root is None or policy.session_id is None:
        raise DiagnosticEvidenceError(
            "diagnostic_evidence.manifest_disabled",
            "diagnostic evidence manifest requires an enabled policy",
        )
    session = policy.root.resolve() / policy.session_id
    if not session.is_dir():
        raise DiagnosticEvidenceError(
            "diagnostic_evidence.session_missing",
            "diagnostic evidence session directory does not exist",
        )
    files = []
    for path in sorted(session.rglob("*")):
        if not path.is_file() or path.name == "manifest.json":
            continue
        stat = path.stat()
        files.append(
            {
                "name": path.relative_to(session).as_posix(),
                "size_bytes": stat.st_size,
                "sha256": _sha256_bytes(path.read_bytes()),
                "mode": oct(stat.st_mode & 0o777),
            }
        )
    safe_metadata, _, _ = _sanitize_payload(metadata or {}, include_raw=False)
    manifest = {
        "schema_version": DIAGNOSTIC_EVIDENCE_MANIFEST_SCHEMA_VERSION,
        "session_id": policy.session_id,
        "mode": policy.mode,
        "raw_payload_included": policy.include_raw,
        "secrets_forbidden": True,
        "retention_days": policy.retention_days,
        "created_at": observed_at or _utc_now(),
        "metadata": safe_metadata,
        "files": files,
    }
    body = _canonical_json(manifest).encode("utf-8")
    result = {**manifest, "manifest_sha256": _sha256_bytes(body)}
    target = session / "manifest.json"
    target.write_text(_canonical_json(result) + "\n", encoding="utf-8")
    os.chmod(target, 0o600)
    return result


def _sanitize_payload(
    payload: Mapping[str, Any], *, include_raw: bool
) -> tuple[dict[str, Any], list[str], list[str]]:
    redacted_paths: list[str] = []
    raw_paths: list[str] = []

    def visit(value: Any, path: str, key: str | None = None) -> Any:
        normalized_key = "" if key is None else key.strip().lower()
        if key is not None and _is_secret_key(normalized_key):
            redacted_paths.append(path)
            return REDACTED_DIAGNOSTIC_VALUE
        if key is not None and normalized_key in _RAW_PAYLOAD_KEYS:
            if not include_raw:
                normalized_value = _json_safe(value)
                return {
                    "value": OMITTED_DIAGNOSTIC_VALUE,
                    "sha256": _sha256_json(normalized_value),
                }
            raw_paths.append(path)
        if isinstance(value, Mapping):
            return {
                str(child_key): visit(
                    child_value,
                    f"{path}.{child_key}" if path else str(child_key),
                    str(child_key),
                )
                for child_key, child_value in value.items()
            }
        if isinstance(value, (list, tuple)):
            return [
                visit(child, f"{path}[{index}]", key=None)
                for index, child in enumerate(value)
            ]
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        return _json_safe(value)

    sanitized = {
        str(key): visit(value, str(key), str(key)) for key, value in payload.items()
    }
    return sanitized, redacted_paths, raw_paths


def _is_secret_key(key: str) -> bool:
    normalized = key.replace("-", "_").lower()
    return (
        normalized in _SECRET_EXACT_KEYS
        or normalized.endswith("_token")
        or any(part in normalized for part in _SECRET_KEY_PARTS)
    )


def _json_safe(value: Any) -> Any:
    if isinstance(value, bytes):
        return {
            "binary_size_bytes": len(value),
            "binary_sha256": _sha256_bytes(value),
        }
    if isinstance(value, Mapping):
        return {str(key): _json_safe(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(child) for child in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _last_chain_state(stream: Any) -> tuple[int, str]:
    stream.seek(0)
    last_line = ""
    for line in stream:
        if line.strip():
            last_line = line
    if not last_line:
        return 0, _GENESIS_DIGEST
    try:
        last_event = json.loads(last_line)
        sequence = int(last_event["sequence"])
        digest = str(last_event["event_sha256"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise DiagnosticEvidenceError(
            "diagnostic_evidence.chain_invalid",
            "diagnostic evidence chain tail is invalid",
        ) from exc
    if sequence < 1 or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise DiagnosticEvidenceError(
            "diagnostic_evidence.chain_invalid",
            "diagnostic evidence chain tail is invalid",
        )
    return sequence, digest


def _require_identifier(value: object, name: str) -> str:
    text = str(value or "").strip()
    if not _IDENTIFIER.fullmatch(text):
        raise DiagnosticEvidenceError(
            "diagnostic_evidence.identifier_invalid",
            f"diagnostic evidence {name} is invalid",
        )
    return text


def _boolean(value: object, name: str) -> bool:
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise DiagnosticEvidenceError(
        "diagnostic_evidence.boolean_invalid", f"{name} must be boolean"
    )


def _positive_integer(value: object, name: str) -> int:
    try:
        parsed = int(str(value))
    except ValueError as exc:
        raise DiagnosticEvidenceError(
            "diagnostic_evidence.integer_invalid", f"{name} must be an integer"
        ) from exc
    if parsed < 1:
        raise DiagnosticEvidenceError(
            "diagnostic_evidence.integer_invalid", f"{name} must be positive"
        )
    return parsed


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_json(value: Any) -> str:
    return _sha256_bytes(_canonical_json(value).encode("utf-8"))


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
