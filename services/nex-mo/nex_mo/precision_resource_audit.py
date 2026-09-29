from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from nex_mo.providers import build_model_profile_catalog


ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class EvidenceProbe:
    probe_id: str
    path: str
    token: str


EVIDENCE_PROBES = (
    EvidenceProbe(
        "embedding_bf16_catalog",
        "services/nex-mo/nex_mo/providers.py",
        'model_name="Qwen3-Embedding-4B"',
    ),
    EvidenceProbe(
        "reranker_bf16_catalog",
        "services/nex-mo/nex_mo/providers.py",
        'model_name="Qwen3-Reranker-4B"',
    ),
    EvidenceProbe(
        "generation_bf16_catalog",
        "services/nex-mo/nex_mo/providers.py",
        '"model_name": "Qwen3.5-4B"',
    ),
    EvidenceProbe(
        "dtype_operator_rule",
        "services/nex-mo/README.md",
        "--dtype bfloat16",
    ),
    EvidenceProbe(
        "live_identity_profile",
        "scripts/smoke/run_protected_dgx_live_profile.py",
        '"NEX_MO_REMOTE_RERANKER_MODEL": "Qwen3-Reranker-4B"',
    ),
)


def build_mo_precision_resource_safety_audit(
    root: Path = ROOT,
    *,
    probes: Sequence[EvidenceProbe] = EVIDENCE_PROBES,
) -> dict[str, Any]:
    evidence = [_inspect_probe(root, probe) for probe in probes]
    evidence_issues = [
        {
            "category": "precision_evidence_missing",
            "probe_id": item["probe_id"],
            "path": item["path"],
        }
        for item in evidence
        if not item["present"]
    ]
    profiles = build_model_profile_catalog({})
    selected = [profile for profile in profiles if profile.selected]
    precision_by_capability = {
        profile.provider_capability: profile.precision for profile in selected
    }
    mo_source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (root / "services/nex-mo/nex_mo").glob("*.py")
        if path.is_file() and path.name != "precision_resource_audit.py"
    )
    forbidden_local_loader_tokens = (
        "AutoModel.from_pretrained",
        "AutoModelForSequenceClassification.from_pretrained",
        "torch_dtype=torch.float32",
        "dtype=torch.float32",
    )
    checks = {
        "precision_evidence_present": not evidence_issues,
        "selected_capabilities_complete": set(precision_by_capability)
        == {"embedding", "reranking", "generation"},
        "selected_precision_matches_policy": precision_by_capability
        == {"embedding": "BF16", "reranking": "BF16", "generation": "BF16"},
        "mo_has_no_local_model_loader": not any(
            token in mo_source for token in forbidden_local_loader_tokens
        ),
        "runtime_dtype_evidence_deferred_explicitly": True,
        "resource_metrics_gap_classified": True,
    }
    passed = all(checks.values())
    return {
        "audit_schema_version": "mo_precision_resource_safety_audit.v1",
        "slice": "1107",
        "requirement": "S111",
        "status": "PASS" if passed else "FAIL",
        "failure_code": None if passed else "mo_precision_resource_safety_audit_failed",
        "precision_readiness": (
            "DECLARED_SAFE_RUNTIME_EVIDENCE_REQUIRED" if passed else "BLOCKED"
        ),
        "resource_metrics_readiness": "GAP_CONFIRMED" if passed else "BLOCKED",
        "checks": checks,
        "summary": {
            "selected_profile_count": len(selected),
            "bf16_selected_count": sum(
                profile.precision == "BF16" for profile in selected
            ),
            "evidence_probe_count": len(evidence),
            "evidence_issue_count": len(evidence_issues),
            "runtime_gap_count": 2,
        },
        "precision_by_capability": precision_by_capability,
        "runtime_gaps": [
            {
                "gap_id": "loaded_dtype_not_http_observable",
                "risk": "HIGH",
                "required_evidence": "DGX vLLM process or launch log shows --dtype bfloat16",
                "verification_slice": "1110",
            },
            {
                "gap_id": "gpu_resource_metrics_not_projected",
                "risk": "MEDIUM",
                "required_evidence": "GPU memory and utilization adapter or operator snapshot",
                "verification_slice": "S112",
            },
        ],
        "guardrails": [
            "never infer loaded dtype from model name alone",
            "reject FP32 embedding or reranker launch evidence",
            "keep model loading on DGX provider runtimes",
            "do not expose host process arguments or model paths through public APIs",
        ],
        "evidence": evidence,
        "issues": evidence_issues,
        "next_slice": "1108",
    }


def _inspect_probe(root: Path, probe: EvidenceProbe) -> dict[str, Any]:
    path = root / probe.path
    present = path.is_file() and probe.token in path.read_text(encoding="utf-8")
    return {
        "probe_id": probe.probe_id,
        "path": probe.path,
        "present": present,
    }
