from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from nex_mo.providers import build_model_profile_catalog
from nex_mo.remote_provider import build_remote_provider_preflight_configs


ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class DriftProbe:
    finding_id: str
    path: str
    token: str
    risk: str
    category: str
    remediation_slice: str


DRIFT_PROBES = (
    DriftProbe(
        "embedding_live_mock_alias",
        "services/nex-mo/nex_mo/providers.py",
        'alias="mock-embedding-default"',
        "MEDIUM",
        "live_profile_naming",
        "S112",
    ),
    DriftProbe(
        "reranker_live_mock_alias",
        "services/nex-mo/nex_mo/providers.py",
        'alias="mock-reranker-default"',
        "MEDIUM",
        "live_profile_naming",
        "S112",
    ),
    DriftProbe(
        "legacy_health_env_projection",
        "services/nex-mo/nex_mo/providers.py",
        'live_health_env="NEX_MO_LIVE_EMBEDDING_HEALTH_URL"',
        "LOW",
        "deprecated_configuration_surface",
        "S112",
    ),
    DriftProbe(
        "provider_mode_not_validated",
        "services/nex-mo/nex_mo/providers.py",
        'env.get("NEX_MO_PROVIDER_MODE", DEFAULT_PROVIDER_MODE)',
        "MEDIUM",
        "configuration_validation",
        "S112",
    ),
)


def build_mo_catalog_config_drift_audit(
    root: Path = ROOT,
    *,
    probes: Sequence[DriftProbe] = DRIFT_PROBES,
) -> dict[str, Any]:
    findings = [_inspect_probe(root, probe) for probe in probes]
    evidence_issues = [
        {
            "category": "drift_evidence_missing",
            "finding_id": item["finding_id"],
            "path": item["path"],
        }
        for item in findings
        if not item["evidence_present"]
    ]
    profiles = build_model_profile_catalog({})
    preflight = build_remote_provider_preflight_configs({})
    selected = [profile for profile in profiles if profile.selected]
    current_defaults = {
        "selected_profiles": {
            profile.provider_capability: profile.model_name for profile in selected
        },
        "provider_mode": profiles[0].provider_mode if profiles else None,
        "request_shapes": {
            config.capability: config.request_shape for config in preflight
        },
        "timeouts_seconds": {
            config.capability: config.timeout_seconds for config in preflight
        },
    }
    checks = {
        "drift_inventory_complete": len(findings) == 4,
        "drift_evidence_present": not evidence_issues,
        "required_capabilities_selected": set(current_defaults["selected_profiles"])
        == {"embedding", "reranking", "generation"},
        "direct_vllm_shapes_are_default": current_defaults["request_shapes"]
        == {
            "embedding": "openai_embeddings",
            "reranking": "rerank",
            "generation": "openai_models",
        },
        "capability_timeouts_are_positive": all(
            value > 0 for value in current_defaults["timeouts_seconds"].values()
        ),
    }
    passed = all(checks.values())
    return {
        "audit_schema_version": "mo_catalog_config_drift_audit.v1",
        "slice": "1104",
        "requirement": "S111",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "mo_catalog_config_drift_audit_failed",
        "catalog_readiness": "DRIFT_CONFIRMED" if passed else "BLOCKED",
        "checks": checks,
        "summary": {
            "profile_count": len(profiles),
            "selected_profile_count": len(selected),
            "drift_count": len(findings),
            "high_risk_count": sum(item["risk"] == "HIGH" for item in findings),
            "evidence_issue_count": len(evidence_issues),
        },
        "current_defaults": current_defaults,
        "findings": findings,
        "ordered_remediation": [
            {
                "priority": "P1",
                "action": "separate stable capability aliases from mock deployment names",
                "slice": "S112",
            },
            {
                "priority": "P2",
                "action": "validate provider mode and remove legacy envs from public metadata",
                "slice": "S112",
            },
        ],
        "issues": evidence_issues,
        "next_slice": "1105",
    }


def _inspect_probe(root: Path, probe: DriftProbe) -> dict[str, Any]:
    path = root / probe.path
    present = path.is_file() and probe.token in path.read_text(encoding="utf-8")
    return {
        "finding_id": probe.finding_id,
        "path": probe.path,
        "risk": probe.risk,
        "category": probe.category,
        "remediation_slice": probe.remediation_slice,
        "evidence_present": present,
    }
