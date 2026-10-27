"""Package-level shell for the P9 evidence consumer process identity."""

SERVICE_ID = "nex-wa"
PROCESS_ID = "nex-wa-evidence-consumer"
WORKER_TYPE = "wa.evidence_consumer"


def package_readiness() -> dict[str, object]:
    return {
        "service_id": SERVICE_ID,
        "process_id": PROCESS_ID,
        "worker_type": WORKER_TYPE,
        "domain_processing_enabled": False,
    }
