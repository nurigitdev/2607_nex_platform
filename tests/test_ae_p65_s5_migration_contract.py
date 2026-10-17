from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "database/nex-ae-api/migrations/2300_ae_semantic_candidate.sql"


def test_candidate_evidence_migration_is_bounded_and_owner_scoped() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS ae_semantic_candidate" in sql
    assert "UNIQUE (tenant_id, agent_execution_id, semantic_stage, candidate_revision)" in sql
    assert "owner_subject_id TEXT NOT NULL" in sql
    assert "candidate_payload_storage_ref TEXT NULL" in sql
    assert "candidate_payload_size_bytes BIGINT NULL" in sql
    assert "evidence_json JSONB NOT NULL" in sql
    assert "2300_ae_semantic_candidate" in sql
    assert "BYTEA" not in sql.upper()
    assert "BLOB" not in sql.upper()
    assert len("ae_semantic_candidate") <= 30
