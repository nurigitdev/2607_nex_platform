"""Signed MyBee M1 Skill admission and Project Agent invocation planning."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import date
from pathlib import Path
from typing import Any

from nex_runtime.semantic_hashes import semantic_sha256_hash_ref
from nsl.adapters.ed25519 import Ed25519TrustStore
from nsl.cli_config import load_tool_catalog
from nsl.compiler import NslCompiler
from nsl.nsp_verification import NspVerificationPolicy, NspVerifier
from nsl.security import RuntimeEnvironment

from ..domain.work_codes import load_work_code_catalog
from .nex_skill_packs import SkillPackBinding, load_skill_pack_manifests

M1_SIGNED_SKILL_SCHEMA_VERSION = "nex.mybee.m1-signed-skill-checkpoint.v1"
M1_PA_PLAN_SCHEMA_VERSION = "nex.mybee.pa-nsl-invocation-plan.v1"
M1_CHECKPOINT_ID = "CP-M1-MB8-01"
M1_D04_WORK_CODE_ID = "FL0004009"
M1_D12_WORK_CODE_ID = "FL0012005"
M1_D04_CAPABILITY_ID = "FINANCE.VOUCHER.APPROVE_AND_POST"
M1_D12_CAPABILITY_ID = "PROJECT.WORK_CODE_SET.GET"

_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_M1_SIGNED_SKILL_LOCK = (
    _ROOT / "deployment/locks/ae-mybee-m1-signed-skill-checkpoint.v1.json"
)
_PROJECT_CODE = re.compile(r"^[A-Z0-9][A-Z0-9._-]{2,63}$")
_UUID_TEXT = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_JOURNAL_ARGUMENTS = frozenset(
    {
        "schema_version",
        "tenant_id",
        "company_id",
        "candidate_id",
        "expected_candidate_version",
        "expected_candidate_revision",
        "expected_candidate_hash",
        "accounting_approval_evidence_id",
    }
)


class M1SkillAdmissionError(ValueError):
    """Fail-closed error raised for M1 release or PA-plan drift."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        super().__init__(f"{code}: {detail}")


@dataclass(frozen=True)
class AdmittedM1Skill:
    domain_code: str
    skill_id: str
    skill_version: str
    semantic_hash: str
    artifact_hash: str
    capability_id: str
    operation_semantics: str
    approval_requirement: str
    oa_action: str
    input_contract_ref: str
    output_contract_ref: str
    trust_policy_id: str


@dataclass(frozen=True)
class AdmittedM1FlBinding:
    work_code_id: str
    binding_role: str
    capability_id: str
    skill_id: str


@dataclass(frozen=True)
class AdmittedM1SignedSkillRelease:
    release_id: str
    release_version: int
    checkpoint_id: str
    content_hash: str
    package_ref: str
    package_hash: str
    signing_key_id: str
    registry_ref: str
    registry_hash: str
    skills: tuple[AdmittedM1Skill, ...]
    fl_bindings: tuple[AdmittedM1FlBinding, ...]
    verified_skills: tuple[Any, ...] = dataclass_field(
        repr=False, compare=False, default=()
    )

    def skill_for_capability(self, capability_id: str) -> AdmittedM1Skill:
        for skill in self.skills:
            if skill.capability_id == capability_id:
                return skill
        raise M1SkillAdmissionError("M1_CAPABILITY_NOT_ADMITTED", capability_id)

    def verified_skill_for_capability(self, capability_id: str) -> Any:
        admitted = self.skill_for_capability(capability_id)
        matches = tuple(
            item
            for item in self.verified_skills
            if str(item.skill.skill_id) == admitted.skill_id
            and str(item.skill.skill_version) == admitted.skill_version
            and str(item.skill.semantic_hash) == admitted.semantic_hash
        )
        if len(matches) != 1:
            raise M1SkillAdmissionError(
                "M1_VERIFIED_SKILL_IDENTITY_INVALID", capability_id
            )
        return matches[0]


def load_m1_signed_skill_release(
    lock_path: Path = DEFAULT_M1_SIGNED_SKILL_LOCK,
    *,
    repository_root: Path = _ROOT,
) -> AdmittedM1SignedSkillRelease:
    """Verify the signed NSP and all source-backed M1 activation bindings."""

    lock = _json(lock_path, "M1_RELEASE_LOCK_UNAVAILABLE")
    if lock.get("schema_version") != M1_SIGNED_SKILL_SCHEMA_VERSION:
        _fail("M1_RELEASE_SCHEMA_UNSUPPORTED", str(lock.get("schema_version")))
    if lock.get("checkpoint_id") != M1_CHECKPOINT_ID:
        _fail("M1_CHECKPOINT_ID_INVALID", str(lock.get("checkpoint_id")))
    if lock.get("release_state") != "SIGNED_ACTIVE_CHECKPOINT":
        _fail("M1_RELEASE_INACTIVE", str(lock.get("release_state")))
    if lock.get("runtime_selectable") is not True:
        _fail("M1_RELEASE_NOT_SELECTABLE", "runtime_selectable must be true")
    _verify_content_hash(lock)

    runtime = _mapping(lock.get("nsl_runtime"), "nsl_runtime")
    if runtime.get("package_version") != "0.2.1":
        _fail("M1_NSL_VERSION_INVALID", str(runtime.get("package_version")))
    _verify_ref(repository_root, runtime, "wheel_lock_ref", "wheel_lock_sha256")

    package = _mapping(lock.get("package"), "package")
    package_path = _verify_ref(repository_root, package, "path", "file_sha256")
    key_path = _verify_ref(
        repository_root, package, "public_key_ref", "public_key_sha256"
    )
    key = _json(key_path, "M1_TRUST_KEY_UNAVAILABLE")
    _require_exact_key(key, package)
    public_key = _decode_public_key(str(key["public_key_base64"]))
    verifier = NspVerifier(
        policy=NspVerificationPolicy(environment=RuntimeEnvironment.PRODUCTION),
        signature_verifier=Ed25519TrustStore({str(key["key_id"]): public_key}),
    )
    try:
        verified = verifier.verify(package_path.read_bytes())
    except (OSError, ValueError) as exc:
        raise M1SkillAdmissionError(
            "M1_NSP_SIGNATURE_INVALID", "signed package verification failed"
        ) from exc
    if verified.package_hash != package.get("package_hash"):
        _fail("M1_NSP_PACKAGE_HASH_MISMATCH", verified.package_hash)
    if (
        verified.signature is None
        or verified.signature.key_id != package.get("signing_key_id")
        or verified.signature.algorithm != package.get("signature_algorithm")
    ):
        _fail("M1_NSP_SIGNATURE_METADATA_INVALID", str(verified.signature))

    catalog_ref = _mapping(lock.get("tool_catalog"), "tool_catalog")
    catalog_path = _verify_ref(repository_root, catalog_ref, "path", "sha256")
    catalog = load_tool_catalog(catalog_path)
    package_skills = {item.manifest.skill_id: item for item in verified.skills}
    skill_records = lock.get("skills")
    if not isinstance(skill_records, list) or len(skill_records) != 2:
        _fail("M1_SKILL_SET_INVALID", str(skill_records))
    skills = tuple(
        _admit_skill(
            _mapping(record, "skills[]"),
            repository_root=repository_root,
            catalog=catalog,
            package_skills=package_skills,
        )
        for record in skill_records
    )
    if {item.capability_id for item in skills} != {
        M1_D04_CAPABILITY_ID,
        M1_D12_CAPABILITY_ID,
    }:
        _fail("M1_SKILL_SET_INVALID", "unexpected capability set")
    _verify_candidate_bindings(skills, repository_root=repository_root)

    fl_bindings = _admit_fl_bindings(lock.get("fl_bindings"), skills)
    if load_work_code_catalog().get(M1_D12_WORK_CODE_ID).code_id != M1_D12_WORK_CODE_ID:
        _fail("M1_D12_WORK_CODE_INVALID", M1_D12_WORK_CODE_ID)

    registry = _mapping(
        lock.get("product_capability_registry"), "product_capability_registry"
    )
    registry_path = _verify_ref(repository_root, registry, "path", "file_sha256")
    _verify_registry(_json(registry_path, "M1_REGISTRY_UNAVAILABLE"), registry, skills)

    boundary = _mapping(lock.get("activation_boundary"), "activation_boundary")
    expected_boundary = {
        "allowed_agent_types": ["PA"],
        "allowed_project_states": ["ACTIVE"],
        "allowed_agent_statuses": ["ACTIVE"],
        "allowed_capability_modes": ["ORDINARY"],
        "full_pack_activation": "DEFERRED_TO_M2_MB8_01",
        "canonical_compose_registry_unchanged": True,
        "remote_provider_required": False,
    }
    if dict(boundary) != expected_boundary:
        _fail("M1_ACTIVATION_BOUNDARY_DRIFT", str(dict(boundary)))

    return AdmittedM1SignedSkillRelease(
        release_id=_text(lock.get("release_id"), "release_id"),
        release_version=_positive_int(lock.get("release_version"), "release_version"),
        checkpoint_id=M1_CHECKPOINT_ID,
        content_hash=str(lock["content_hash"]),
        package_ref=str(package["path"]),
        package_hash=str(package["package_hash"]),
        signing_key_id=str(package["signing_key_id"]),
        registry_ref=str(registry["path"]),
        registry_hash=str(registry["registry_hash"]),
        skills=skills,
        fl_bindings=fl_bindings,
        verified_skills=tuple(verified.skills),
    )


def build_pa_nsl_invocation_plan(
    release: AdmittedM1SignedSkillRelease,
    *,
    tenant_id: str,
    requester_subject_id: str,
    project: Mapping[str, Any],
    project_agent: Mapping[str, Any],
    project_work_code_ids: Sequence[str],
    business_work_code_id: str,
    journal_arguments: Mapping[str, Any],
    effective_on: str,
) -> dict[str, Any]:
    """Build a deterministic context-then-write PA orchestration checkpoint."""

    if not isinstance(release, AdmittedM1SignedSkillRelease):
        _fail("M1_RELEASE_REQUIRED", "admitted release is required")
    tenant = _text(tenant_id, "tenant_id")
    requester = _text(requester_subject_id, "requester_subject_id")
    project_id = _uuid_text(project.get("project_id"), "project.project_id")
    project_code = _text(project.get("project_code"), "project.project_code")
    if _PROJECT_CODE.fullmatch(project_code) is None:
        _fail("M1_PROJECT_CODE_INVALID", project_code)
    if project.get("tenant_id") != tenant or project.get("project_state") != "ACTIVE":
        _fail("M1_PROJECT_NOT_ACTIVE", project_code)
    if (
        project_agent.get("tenant_id") != tenant
        or project_agent.get("project_id") != project_id
        or project_agent.get("project_code") != project_code
    ):
        _fail("M1_PROJECT_AGENT_SCOPE_MISMATCH", project_code)
    if project_agent.get("agent_type", "PA") != "PA":
        _fail("M1_AGENT_TYPE_DENIED", str(project_agent.get("agent_type")))
    if project_agent.get("agent_status") != "ACTIVE":
        _fail("M1_PROJECT_AGENT_INACTIVE", str(project_agent.get("agent_status")))
    if project_agent.get("capability_mode") != "ORDINARY":
        _fail("M1_CAPABILITY_MODE_DENIED", str(project_agent.get("capability_mode")))
    agent_id = _uuid_text(project_agent.get("agent_id"), "project_agent.agent_id")

    normalized_work_codes = tuple(sorted(set(project_work_code_ids)))
    if M1_D12_WORK_CODE_ID not in normalized_work_codes:
        _fail("M1_PROJECT_CONTEXT_WORK_CODE_REQUIRED", M1_D12_WORK_CODE_ID)
    if business_work_code_id != M1_D04_WORK_CODE_ID:
        _fail("M1_PRIMARY_WORK_CODE_DENIED", str(business_work_code_id))
    try:
        date.fromisoformat(effective_on)
    except (TypeError, ValueError) as exc:
        raise M1SkillAdmissionError(
            "M1_EFFECTIVE_DATE_INVALID", str(effective_on)
        ) from exc

    journal = _normalize_journal_arguments(journal_arguments, tenant_id=tenant)
    context_skill = release.skill_for_capability(M1_D12_CAPABILITY_ID)
    action_skill = release.skill_for_capability(M1_D04_CAPABILITY_ID)
    plan: dict[str, Any] = {
        "schema_version": M1_PA_PLAN_SCHEMA_VERSION,
        "checkpoint_id": release.checkpoint_id,
        "release": {
            "release_id": release.release_id,
            "release_version": release.release_version,
            "release_hash": release.content_hash,
            "package_ref": release.package_ref,
            "package_hash": release.package_hash,
            "signing_key_id": release.signing_key_id,
            "registry_ref": release.registry_ref,
            "registry_hash": release.registry_hash,
        },
        "principal": {
            "tenant_id": tenant,
            "requester_subject_id": requester,
            "agent_type": "PA",
            "agent_id": agent_id,
        },
        "project": {
            "project_id": project_id,
            "project_code": project_code,
            "project_state": "ACTIVE",
            "work_code_ids": list(normalized_work_codes),
        },
        "steps": [
            _step(
                1,
                "PROJECT_CONTEXT",
                M1_D12_WORK_CODE_ID,
                context_skill,
                {
                    "tenant_id": tenant,
                    "requester_subject_id": requester,
                    "project_id": project_id,
                    "effective_on": effective_on,
                },
            ),
            _step(
                2,
                "PRIMARY_ACTION",
                M1_D04_WORK_CODE_ID,
                action_skill,
                journal,
            ),
        ],
    }
    plan["plan_hash"] = semantic_sha256_hash_ref(plan)
    return plan


def verify_pa_nsl_invocation_plan(plan: Mapping[str, Any]) -> dict[str, Any]:
    """Verify a materialized M1 PA invocation plan before scheduling it."""

    if not isinstance(plan, Mapping):
        _fail("M1_PA_PLAN_INVALID", "plan must be an object")
    normalized = json.loads(json.dumps(dict(plan), sort_keys=True))
    supplied = normalized.pop("plan_hash", None)
    if supplied != semantic_sha256_hash_ref(normalized):
        _fail("M1_PA_PLAN_HASH_MISMATCH", str(supplied))
    if normalized.get("schema_version") != M1_PA_PLAN_SCHEMA_VERSION:
        _fail("M1_PA_PLAN_SCHEMA_INVALID", str(normalized.get("schema_version")))
    if normalized.get("checkpoint_id") != M1_CHECKPOINT_ID:
        _fail("M1_PA_PLAN_CHECKPOINT_INVALID", str(normalized.get("checkpoint_id")))
    principal = _mapping(normalized.get("principal"), "principal")
    project = _mapping(normalized.get("project"), "project")
    if principal.get("agent_type") != "PA" or project.get("project_state") != "ACTIVE":
        _fail("M1_PA_PLAN_BOUNDARY_INVALID", "inactive Project Agent boundary")
    steps = normalized.get("steps")
    expected_steps = [
        (1, "PROJECT_CONTEXT", M1_D12_WORK_CODE_ID, M1_D12_CAPABILITY_ID),
        (2, "PRIMARY_ACTION", M1_D04_WORK_CODE_ID, M1_D04_CAPABILITY_ID),
    ]
    observed_steps = (
        [
            (
                item.get("sequence"),
                item.get("role"),
                item.get("work_code_id"),
                item.get("capability_id"),
            )
            for item in steps
        ]
        if isinstance(steps, list) and all(isinstance(item, Mapping) for item in steps)
        else None
    )
    if observed_steps != expected_steps:
        _fail("M1_PA_PLAN_STEP_ORDER_INVALID", str(steps))
    normalized["plan_hash"] = supplied
    return normalized


def _admit_skill(
    record: Mapping[str, Any],
    *,
    repository_root: Path,
    catalog: Any,
    package_skills: Mapping[str, Any],
) -> AdmittedM1Skill:
    source_path = _verify_ref(repository_root, record, "source_ref", "source_sha256")
    try:
        compiled = NslCompiler(catalog).compile(source_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise M1SkillAdmissionError(
            "M1_SKILL_COMPILE_FAILED", str(record.get("skill_id"))
        ) from exc
    skill_id = _text(record.get("skill_id"), "skill_id")
    packaged = package_skills.get(skill_id)
    if packaged is None:
        _fail("M1_NSP_SKILL_MISSING", skill_id)
    expected = (
        record.get("skill_version"),
        record.get("semantic_hash"),
        record.get("artifact_hash"),
    )
    observed = (
        compiled.skill.skill_version,
        compiled.skill.semantic_hash,
        packaged.manifest.artifact_sha256,
    )
    if (
        expected != observed
        or packaged.skill.semantic_hash != compiled.skill.semantic_hash
    ):
        _fail("M1_SKILL_IDENTITY_MISMATCH", skill_id)
    return AdmittedM1Skill(
        domain_code=_text(record.get("domain_code"), "domain_code"),
        skill_id=skill_id,
        skill_version=str(record["skill_version"]),
        semantic_hash=str(record["semantic_hash"]),
        artifact_hash=str(record["artifact_hash"]),
        capability_id=_text(record.get("capability_id"), "capability_id"),
        operation_semantics=_text(
            record.get("operation_semantics"), "operation_semantics"
        ),
        approval_requirement=_text(
            record.get("approval_requirement"), "approval_requirement"
        ),
        oa_action=_text(record.get("oa_action"), "oa_action"),
        input_contract_ref=_text(
            record.get("input_contract_ref"), "input_contract_ref"
        ),
        output_contract_ref=_text(
            record.get("output_contract_ref"), "output_contract_ref"
        ),
        trust_policy_id=_text(record.get("trust_policy_id"), "trust_policy_id"),
    )


def _verify_candidate_bindings(
    skills: Sequence[AdmittedM1Skill], *, repository_root: Path
) -> None:
    candidates = {
        binding.canonical_operation_id: binding
        for manifest in load_skill_pack_manifests(
            repository_root / "domains/mybee/skills"
        )
        for binding in manifest.bindings
    }
    for skill in skills:
        candidate = candidates.get(skill.capability_id)
        if candidate is None:
            _fail("M1_CANDIDATE_BINDING_MISSING", skill.capability_id)
        _verify_candidate_binding(skill, candidate)


def _verify_candidate_binding(
    skill: AdmittedM1Skill, candidate: SkillPackBinding
) -> None:
    expected = (
        skill.operation_semantics,
        skill.approval_requirement,
        skill.oa_action,
        skill.input_contract_ref,
        skill.output_contract_ref,
    )
    observed = (
        candidate.invocation_semantics,
        candidate.approval_requirement,
        candidate.oa_action,
        candidate.input_contract_ref,
        candidate.output_contract_refs[0],
    )
    if expected != observed or candidate.runtime_selectable:
        _fail("M1_CANDIDATE_BINDING_DRIFT", skill.capability_id)


def _admit_fl_bindings(
    value: object, skills: Sequence[AdmittedM1Skill]
) -> tuple[AdmittedM1FlBinding, ...]:
    if not isinstance(value, list) or len(value) != 2:
        _fail("M1_FL_BINDINGS_INVALID", str(value))
    bindings = tuple(
        AdmittedM1FlBinding(
            work_code_id=_text(item.get("work_code_id"), "work_code_id"),
            binding_role=_text(item.get("binding_role"), "binding_role"),
            capability_id=_text(item.get("capability_id"), "capability_id"),
            skill_id=_text(item.get("skill_id"), "skill_id"),
        )
        for raw in value
        for item in [_mapping(raw, "fl_bindings[]")]
    )
    expected = {
        (M1_D04_WORK_CODE_ID, "PRIMARY_ACTION", M1_D04_CAPABILITY_ID),
        (M1_D12_WORK_CODE_ID, "PROJECT_CONTEXT", M1_D12_CAPABILITY_ID),
    }
    observed = {
        (item.work_code_id, item.binding_role, item.capability_id) for item in bindings
    }
    skill_ids = {item.capability_id: item.skill_id for item in skills}
    if observed != expected or any(
        skill_ids.get(item.capability_id) != item.skill_id for item in bindings
    ):
        _fail("M1_FL_BINDINGS_INVALID", str(observed))
    return bindings


def _verify_registry(
    registry: Mapping[str, Any],
    reference: Mapping[str, Any],
    skills: Sequence[AdmittedM1Skill],
) -> None:
    if (
        registry.get("registry_id") != reference.get("registry_id")
        or registry.get("registry_version") != reference.get("registry_version")
        or registry.get("registry_hash") != reference.get("registry_hash")
    ):
        _fail("M1_REGISTRY_IDENTITY_MISMATCH", str(reference))
    expected_hash = semantic_sha256_hash_ref(
        {key: value for key, value in registry.items() if key != "registry_hash"}
    )
    if registry.get("registry_hash") != expected_hash:
        _fail("M1_REGISTRY_HASH_MISMATCH", str(registry.get("registry_hash")))
    registrations = registry.get("registrations")
    if not isinstance(registrations, list):
        _fail("M1_REGISTRY_INVALID", "registrations must be an array")
    by_id = {
        item.get("capability", {}).get("capability_id"): item
        for item in registrations
        if isinstance(item, Mapping) and isinstance(item.get("capability"), Mapping)
    }
    for skill in skills:
        item = by_id.get(skill.capability_id)
        if not isinstance(item, Mapping):
            _fail("M1_REGISTRY_CAPABILITY_MISSING", skill.capability_id)
        capability = _mapping(item.get("capability"), "capability")
        binding = _mapping(capability.get("local_skill_binding"), "local_skill_binding")
        artifact = _mapping(item.get("skill_artifact"), "skill_artifact")
        if (
            capability.get("status") != "ACTIVE"
            or binding.get("skill_id") != skill.skill_id
            or binding.get("exact_skill_version") != skill.skill_version
            or binding.get("skill_semantic_hash") != skill.semantic_hash
            or artifact.get("skill_id") != skill.skill_id
            or artifact.get("skill_semantic_hash") != skill.semantic_hash
        ):
            _fail("M1_REGISTRY_CAPABILITY_DRIFT", skill.capability_id)


def _normalize_journal_arguments(
    value: Mapping[str, Any], *, tenant_id: str
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _JOURNAL_ARGUMENTS:
        _fail(
            "M1_JOURNAL_ARGUMENTS_INVALID",
            str(sorted(value) if isinstance(value, Mapping) else value),
        )
    normalized = dict(value)
    if normalized.get("tenant_id") != tenant_id:
        _fail("M1_JOURNAL_TENANT_MISMATCH", str(normalized.get("tenant_id")))
    for field in (
        "schema_version",
        "company_id",
        "candidate_id",
        "expected_candidate_hash",
        "accounting_approval_evidence_id",
    ):
        _text(normalized.get(field), f"journal_arguments.{field}")
    _positive_int(
        normalized.get("expected_candidate_version"), "expected_candidate_version"
    )
    _positive_int(
        normalized.get("expected_candidate_revision"), "expected_candidate_revision"
    )
    return normalized


def _step(
    sequence: int,
    role: str,
    work_code_id: str,
    skill: AdmittedM1Skill,
    arguments: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "sequence": sequence,
        "role": role,
        "work_code_id": work_code_id,
        "capability_id": skill.capability_id,
        "capability_version": skill.skill_version,
        "skill_id": skill.skill_id,
        "exact_skill_version": skill.skill_version,
        "skill_semantic_hash": skill.semantic_hash,
        "skill_artifact_hash": skill.artifact_hash,
        "trust_policy_id": skill.trust_policy_id,
        "oa_action": skill.oa_action,
        "approval_requirement": skill.approval_requirement,
        "arguments": dict(arguments),
    }


def _verify_ref(
    root: Path,
    value: Mapping[str, Any],
    path_field: str,
    hash_field: str,
) -> Path:
    relative = _text(value.get(path_field), path_field)
    path = (root / relative).resolve()
    try:
        path.relative_to(root.resolve())
        payload = path.read_bytes()
    except (OSError, ValueError) as exc:
        raise M1SkillAdmissionError("M1_ARTIFACT_UNAVAILABLE", relative) from exc
    observed = "sha256:" + hashlib.sha256(payload).hexdigest()
    if value.get(hash_field) != observed:
        _fail("M1_ARTIFACT_HASH_MISMATCH", relative)
    return path


def _verify_content_hash(value: Mapping[str, Any]) -> None:
    expected = semantic_sha256_hash_ref(
        {key: item for key, item in value.items() if key != "content_hash"}
    )
    if value.get("content_hash") != expected:
        _fail("M1_RELEASE_HASH_MISMATCH", str(value.get("content_hash")))


def _require_exact_key(key: Mapping[str, Any], package: Mapping[str, Any]) -> None:
    if (
        set(key)
        != {
            "schema_version",
            "algorithm",
            "key_id",
            "public_key_base64",
            "usage",
            "private_key_persisted",
        }
        or key.get("schema_version") != "nex.mybee.nsp-trust-key.v1"
    ):
        _fail("M1_TRUST_KEY_INVALID", str(sorted(key)))
    if (
        key.get("algorithm") != "Ed25519"
        or key.get("algorithm") != package.get("signature_algorithm")
        or key.get("key_id") != package.get("signing_key_id")
        or key.get("usage") != "VERIFY_ONLY"
        or key.get("private_key_persisted") is not False
    ):
        _fail("M1_TRUST_KEY_INVALID", str(dict(key)))


def _decode_public_key(value: str) -> bytes:
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, TypeError) as exc:
        raise M1SkillAdmissionError("M1_TRUST_KEY_INVALID", "invalid base64") from exc
    if len(decoded) != 32:
        _fail("M1_TRUST_KEY_INVALID", "Ed25519 key must be 32 bytes")
    return decoded


def _json(path: Path, code: str) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise M1SkillAdmissionError(code, str(path)) from exc
    return _mapping(value, str(path))


def _mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail("M1_FIELD_INVALID", f"{field} must be an object")
    return value


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail("M1_FIELD_INVALID", f"{field} must be non-empty text")
    return value


def _positive_int(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        _fail("M1_FIELD_INVALID", f"{field} must be a positive integer")
    return value


def _uuid_text(value: object, field: str) -> str:
    text = _text(value, field)
    if _UUID_TEXT.fullmatch(text) is None:
        _fail("M1_FIELD_INVALID", f"{field} must be a UUID")
    return text.lower()


def _fail(code: str, detail: str) -> None:
    raise M1SkillAdmissionError(code, detail)
