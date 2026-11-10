"""MyBee domain contracts that consume canonical NeX Platform boundaries."""

from .coa_approval import (
    CoaApprovalAdmission,
    CoaApprovalAdmissionError,
    text_file_sha256_hash_ref,
    validate_product_accounting_admission,
)
from .coa_candidate import (
    REQUIRED_FX_SEMANTIC_KEYS,
    CoaCandidateError,
    CoaCandidateValidationReport,
    CoaValidationFinding,
    load_json_object,
    validate_coa_candidate,
    verify_coa_candidate_identity,
)
from .work_codes import (
    MANDATORY_D12_WORK_CODE_IDS,
    WorkCode,
    WorkCodeCatalog,
    WorkCodeCatalogError,
    calculate_catalog_digest,
    load_work_code_catalog,
)

__all__ = [
    "CoaApprovalAdmission",
    "CoaApprovalAdmissionError",
    "REQUIRED_FX_SEMANTIC_KEYS",
    "CoaCandidateError",
    "CoaCandidateValidationReport",
    "CoaValidationFinding",
    "MANDATORY_D12_WORK_CODE_IDS",
    "WorkCode",
    "WorkCodeCatalog",
    "WorkCodeCatalogError",
    "calculate_catalog_digest",
    "load_json_object",
    "load_work_code_catalog",
    "text_file_sha256_hash_ref",
    "validate_coa_candidate",
    "validate_product_accounting_admission",
    "verify_coa_candidate_identity",
]
