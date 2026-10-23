from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime

import pytest
from nex_ae_api.voucher_attachment_manifest import (
    VoucherAttachmentManifestError,
    approval_display_summary,
    bind_manifest_to_governed_payload,
    bind_manifest_to_work_intent,
    build_attachment_manifest,
    manifest_identity,
    require_manifest_approval_binding,
    validate_attachment_manifest,
    work_intent_manifest_binding,
)
from nex_ae_api.voucher_attachments import (
    ATTACHMENT_BATCH_SCHEMA_VERSION,
    SqlAlchemyVoucherAttachmentRepository,
    VoucherAttachmentPersistenceError,
)
from nex_runtime.semantic_hashes import (
    nsl_write_payload_hash_ref,
    semantic_sha256_hash_ref,
)
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

TENANT = "tenant-p8-s75e"
OWNER = "employee-1001"
BATCH_ID = "75e00000-0000-4000-8000-000000000001"
CONVERSATION_ID = "75e00000-0000-4000-8000-000000000002"
INTERACTION_ID = "75e00000-0000-4000-8000-000000000003"
FIRST_ID = "75e00000-0000-4000-8000-000000000010"
SECOND_ID = "75e00000-0000-4000-8000-000000000009"
NOW = datetime(2026, 10, 23, 16, 0, tzinfo=UTC)


@pytest.fixture
def repository():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE ae_voucher_attach_batch (
                    tenant_id TEXT NOT NULL,
                    attachment_batch_id TEXT NOT NULL,
                    owner_subject_id TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    interaction_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    attachment_count INTEGER NOT NULL,
                    total_size_bytes INTEGER NOT NULL,
                    attachment_manifest_hash TEXT,
                    locked_at TEXT,
                    trace_id TEXT NOT NULL,
                    correlation_id TEXT NOT NULL,
                    causation_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, attachment_batch_id),
                    UNIQUE (tenant_id, conversation_id, interaction_id)
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE ae_voucher_attachment (
                    tenant_id TEXT NOT NULL,
                    attachment_batch_id TEXT NOT NULL,
                    attachment_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    media_type TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    content_sha256 TEXT,
                    object_ref TEXT,
                    object_version_ref TEXT,
                    scan_status TEXT NOT NULL,
                    evidence_ref TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (tenant_id, attachment_batch_id, attachment_id),
                    UNIQUE (tenant_id, object_ref)
                )
                """
            )
        )
    value = SqlAlchemyVoucherAttachmentRepository(
        sessionmaker(bind=engine, expire_on_commit=False), clock=lambda: NOW
    )
    yield engine, value
    engine.dispose()


def _batch(items: list[dict], *, state: str = "READY") -> dict:
    return {
        "schema_version": ATTACHMENT_BATCH_SCHEMA_VERSION,
        "attachment_batch_id": BATCH_ID,
        "tenant_id": TENANT,
        "owner_subject_ref": {"type": "oa.user", "id": OWNER},
        "conversation_id": CONVERSATION_ID,
        "interaction_id": INTERACTION_ID,
        "state": state,
        "attachment_count": len(items),
        "total_size_bytes": sum(item["size_bytes"] for item in items),
        "attachment_manifest_hash": None,
        "locked_at": None,
        "items": items,
    }


def _item(attachment_id: str, *, suffix: str, state: str = "READY") -> dict:
    payload = f"receipt-{suffix}".encode()
    return {
        "attachment_id": attachment_id,
        "attachment_batch_id": BATCH_ID,
        "tenant_id": TENANT,
        "state": state,
        "display_name": f"receipt-{suffix}.pdf",
        "media_type": "application/pdf",
        "size_bytes": len(payload),
        "content_sha256": __import__("hashlib").sha256(payload).hexdigest(),
        "object_ref": f"objref:ae:voucher:{suffix:0>32}",
        "object_version_ref": f"version-{suffix}",
        "scan_status": "CLEAN",
        "evidence_ref": f"evidence-{suffix}",
    }


def _create_ready_batch(repository: SqlAlchemyVoucherAttachmentRepository) -> None:
    repository.create_batch(
        {
            "schema_version": ATTACHMENT_BATCH_SCHEMA_VERSION,
            "attachment_batch_id": BATCH_ID,
            "tenant_id": TENANT,
            "owner_subject_ref": {"type": "oa.user", "id": OWNER},
            "conversation_id": CONVERSATION_ID,
            "interaction_id": INTERACTION_ID,
            "trace": {
                "trace_id": "trace-p8-s75e",
                "correlation_id": "request-p8-s75e",
                "causation_id": INTERACTION_ID,
            },
        }
    )
    for attachment_id, suffix in ((FIRST_ID, "10"), (SECOND_ID, "09")):
        item = _item(attachment_id, suffix=suffix)
        repository.register_item(
            {
                "tenant_id": TENANT,
                "attachment_batch_id": BATCH_ID,
                "attachment_id": attachment_id,
                "display_name": item["display_name"],
                "media_type": item["media_type"],
                "size_bytes": item["size_bytes"],
            }
        )
        repository.publish_item(
            tenant_id=TENANT,
            attachment_batch_id=BATCH_ID,
            attachment_id=attachment_id,
            content_sha256=item["content_sha256"],
            object_ref=item["object_ref"],
            object_version_ref=item["object_version_ref"],
            evidence_ref=item["evidence_ref"],
        )
    repository.finalize_batch(tenant_id=TENANT, attachment_batch_id=BATCH_ID)


def test_manifest_is_sorted_deterministic_and_material_mutation_changes_hash() -> None:
    first = _item(FIRST_ID, suffix="10")
    second = _item(SECOND_ID, suffix="09")
    manifest = build_attachment_manifest(_batch([first, second]))
    reordered = build_attachment_manifest(_batch([second, first]))

    assert manifest == reordered
    assert [item["attachment_id"] for item in manifest["items"]] == [
        SECOND_ID,
        FIRST_ID,
    ]
    assert validate_attachment_manifest(manifest) == manifest

    changed_item = deepcopy(first)
    changed_item["display_name"] = "renamed.pdf"
    changed = build_attachment_manifest(_batch([changed_item, second]))
    assert changed["attachment_manifest_hash"] != manifest["attachment_manifest_hash"]


def test_repository_locks_manifest_exactly_once_and_blocks_post_lock_mutation(
    repository,
) -> None:
    engine, store = repository
    _create_ready_batch(store)

    locked = store.lock_manifest(tenant_id=TENANT, attachment_batch_id=BATCH_ID)
    replay = store.lock_manifest(tenant_id=TENANT, attachment_batch_id=BATCH_ID)

    assert replay == locked
    assert [item["attachment_id"] for item in locked["items"]] == [
        SECOND_ID,
        FIRST_ID,
    ]
    persisted = store.get_batch(tenant_id=TENANT, attachment_batch_id=BATCH_ID)
    assert persisted is not None
    assert persisted["state"] == "LOCKED"
    assert {item["state"] for item in persisted["items"]} == {"LOCKED"}
    assert persisted["attachment_manifest_hash"] == locked["attachment_manifest_hash"]

    with pytest.raises(VoucherAttachmentPersistenceError) as removed:
        store.remove_item(
            tenant_id=TENANT,
            attachment_batch_id=BATCH_ID,
            attachment_id=FIRST_ID,
        )
    assert removed.value.status_code == 409
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE ae_voucher_attachment SET display_name = 'tampered.pdf' "
                "WHERE tenant_id = :tenant_id AND attachment_id = :attachment_id"
            ),
            {"tenant_id": TENANT, "attachment_id": FIRST_ID},
        )
    with pytest.raises(VoucherAttachmentManifestError, match="integrity"):
        store.lock_manifest(tenant_id=TENANT, attachment_batch_id=BATCH_ID)


def test_manifest_binds_work_intent_payload_request_and_platform_evidence() -> None:
    manifest = build_attachment_manifest(
        _batch([_item(FIRST_ID, suffix="10"), _item(SECOND_ID, suffix="09")])
    )
    work_intent = {
        "schema_version": "1.1",
        "constraints": [],
        "intent_hash": semantic_sha256_hash_ref({"placeholder": True}),
    }
    bound_intent = bind_manifest_to_work_intent(work_intent, manifest)
    identity = manifest_identity(manifest)
    assert work_intent_manifest_binding(bound_intent) == identity
    assert bound_intent["intent_hash"] != work_intent["intent_hash"]

    base_payload = {
        "schema_version": "eos_create_voucher_draft_command.v1",
        "tenant_id": TENANT,
        "attachments": [],
    }
    governed = bind_manifest_to_governed_payload(base_payload, manifest)
    payload_hash = nsl_write_payload_hash_ref(governed)
    request = {
        "approval_request_id": "approval-p8-s75e",
        "payload_hash": payload_hash,
        "write_intent_hash": "sha256:" + "a" * 64,
        "display_safe_summary": approval_display_summary({}, manifest),
    }
    evidence = {
        "approval_request_id": request["approval_request_id"],
        "payload_hash": payload_hash,
        "write_intent_hash": request["write_intent_hash"],
    }
    assert governed["attachment_manifest_hash"] == identity["attachment_manifest_hash"]
    assert (
        require_manifest_approval_binding(
            manifest=manifest,
            governed_payload=base_payload,
            approval_request=request,
            approval_evidence=evidence,
        )
        == payload_hash
    )

    changed = deepcopy(manifest)
    changed["items"][0]["object_ref"] += "-changed"
    changed["attachment_manifest_hash"] = semantic_sha256_hash_ref(
        {
            key: value
            for key, value in changed.items()
            if key != "attachment_manifest_hash"
        }
    )
    with pytest.raises(VoucherAttachmentManifestError, match="ApprovalRequest"):
        require_manifest_approval_binding(
            manifest=changed,
            governed_payload=base_payload,
            approval_request=request,
            approval_evidence=evidence,
        )


@pytest.mark.parametrize(
    "mutation",
    (
        lambda value: value.update(attachment_manifest_hash="sha256:" + "0" * 64),
        lambda value: value["items"].reverse(),
        lambda value: value.update(attachment_count=99),
    ),
)
def test_manifest_validation_fails_closed(mutation) -> None:
    manifest = build_attachment_manifest(
        _batch([_item(FIRST_ID, suffix="10"), _item(SECOND_ID, suffix="09")])
    )
    mutation(manifest)
    with pytest.raises(VoucherAttachmentManifestError):
        validate_attachment_manifest(manifest)


def _rehash(manifest: dict) -> None:
    manifest["attachment_manifest_hash"] = semantic_sha256_hash_ref(
        {
            key: value
            for key, value in manifest.items()
            if key != "attachment_manifest_hash"
        }
    )


@pytest.mark.parametrize(
    ("batch", "message"),
    (
        ({}, "READY or LOCKED"),
        ({"state": "READY", "items": "bad"}, "items are invalid"),
        ({"state": "READY", "items": [None]}, "batch item is invalid"),
        (
            _batch([_item(FIRST_ID, suffix="10", state="FAILED")]),
            "incomplete item",
        ),
        (
            {**_batch([_item(FIRST_ID, suffix="10")]), "attachment_count": 2},
            "totals are inconsistent",
        ),
    ),
)
def test_manifest_builder_rejects_incomplete_batch_shapes(batch, message) -> None:
    with pytest.raises(VoucherAttachmentManifestError, match=message):
        build_attachment_manifest(batch)


def test_locked_manifest_replay_requires_exact_persisted_hash() -> None:
    item = _item(FIRST_ID, suffix="10")
    ready = build_attachment_manifest(_batch([item]))
    locked_item = {**item, "state": "LOCKED"}
    locked_batch = {
        **_batch([locked_item], state="LOCKED"),
        "attachment_manifest_hash": ready["attachment_manifest_hash"],
    }
    assert build_attachment_manifest(locked_batch) == ready
    locked_batch["attachment_manifest_hash"] = "sha256:" + "0" * 64
    with pytest.raises(VoucherAttachmentManifestError, match="integrity"):
        build_attachment_manifest(locked_batch)


def test_manifest_contract_validation_rejects_canonical_shape_drift() -> None:
    manifest = build_attachment_manifest(
        _batch([_item(FIRST_ID, suffix="10"), _item(SECOND_ID, suffix="09")])
    )
    with pytest.raises(VoucherAttachmentManifestError, match="object"):
        validate_attachment_manifest(None)  # type: ignore[arg-type]
    changed = deepcopy(manifest)
    changed["schema_version"] = "wrong"
    with pytest.raises(VoucherAttachmentManifestError, match="schema"):
        validate_attachment_manifest(changed)
    changed = deepcopy(manifest)
    changed["unexpected"] = True
    _rehash(changed)
    with pytest.raises(VoucherAttachmentManifestError, match="fields"):
        validate_attachment_manifest(changed)
    changed = deepcopy(manifest)
    changed["attachment_manifest_hash"] = "bad"
    with pytest.raises(VoucherAttachmentManifestError, match="hash is invalid"):
        validate_attachment_manifest(changed)
    changed = deepcopy(manifest)
    changed["items"].reverse()
    _rehash(changed)
    with pytest.raises(VoucherAttachmentManifestError, match="sorted"):
        validate_attachment_manifest(changed)
    changed = deepcopy(manifest)
    changed["attachment_count"] = 3
    _rehash(changed)
    with pytest.raises(VoucherAttachmentManifestError, match="totals"):
        validate_attachment_manifest(changed)
    changed = deepcopy(manifest)
    changed["items"][0]["unexpected"] = True
    _rehash(changed)
    with pytest.raises(VoucherAttachmentManifestError, match="item fields"):
        validate_attachment_manifest(changed)


def test_work_intent_and_governed_payload_conflicts_fail_closed() -> None:
    manifest = build_attachment_manifest(_batch([_item(FIRST_ID, suffix="10")]))
    with pytest.raises(VoucherAttachmentManifestError, match="constraints"):
        bind_manifest_to_work_intent({}, manifest)
    bound = bind_manifest_to_work_intent({"constraints": []}, manifest)
    assert bind_manifest_to_work_intent(bound, manifest) == bound
    changed = deepcopy(bound)
    changed["constraints"][0]["attachment_manifest_hash"] = "sha256:" + "0" * 64
    with pytest.raises(VoucherAttachmentManifestError, match="another"):
        bind_manifest_to_work_intent(changed, manifest)
    assert work_intent_manifest_binding({}) is None
    assert work_intent_manifest_binding({"constraints": []}) is None
    duplicate = deepcopy(bound)
    duplicate["constraints"].append(deepcopy(duplicate["constraints"][0]))
    with pytest.raises(VoucherAttachmentManifestError, match="multiple"):
        work_intent_manifest_binding(duplicate)
    with pytest.raises(VoucherAttachmentManifestError, match="other attachments"):
        bind_manifest_to_governed_payload(
            {"attachments": [{"attachment_id": "other"}]}, manifest
        )
    summary = approval_display_summary({}, manifest)
    summary["attachment_count"] = 20
    with pytest.raises(VoucherAttachmentManifestError, match="another"):
        approval_display_summary(summary, manifest)


def test_stale_platform_evidence_and_approval_object_fail_closed() -> None:
    manifest = build_attachment_manifest(_batch([_item(FIRST_ID, suffix="10")]))
    payload = {"schema_version": "test.v1", "attachments": []}
    governed = bind_manifest_to_governed_payload(payload, manifest)
    request_data = {
        "approval_request_id": "approval-p8-s75e",
        "payload_hash": nsl_write_payload_hash_ref(governed),
        "write_intent_hash": "sha256:" + "a" * 64,
        "display_safe_summary": approval_display_summary({}, manifest),
    }

    class ApprovalRequest:
        def to_data(self):
            return request_data

    stale = {
        "approval_request_id": request_data["approval_request_id"],
        "payload_hash": "sha256:" + "0" * 64,
        "write_intent_hash": request_data["write_intent_hash"],
    }
    with pytest.raises(VoucherAttachmentManifestError, match="stale"):
        require_manifest_approval_binding(
            manifest=manifest,
            governed_payload=payload,
            approval_request=ApprovalRequest(),
            approval_evidence=stale,
        )
    with pytest.raises(VoucherAttachmentManifestError, match="ApprovalRequest"):
        require_manifest_approval_binding(
            manifest=manifest,
            governed_payload=payload,
            approval_request=object(),
        )


@pytest.mark.parametrize(
    "mutation",
    (
        lambda item: item.update(content_sha256="short"),
        lambda item: item.update(content_sha256="g" * 64),
        lambda item: item.update(content_sha256="A" * 64),
        lambda item: item.update(size_bytes=0),
    ),
)
def test_manifest_scalar_validation_fails_closed(mutation) -> None:
    batch = _batch([_item(FIRST_ID, suffix="10")])
    mutation(batch["items"][0])
    with pytest.raises(VoucherAttachmentManifestError):
        build_attachment_manifest(batch)

    batch = _batch([_item(FIRST_ID, suffix="10")])
    batch["owner_subject_ref"] = {"type": "wrong", "id": OWNER}
    with pytest.raises(VoucherAttachmentManifestError, match="owner"):
        build_attachment_manifest(batch)


def test_manifest_binding_scalar_validation_fails_closed() -> None:
    invalids = (
        {"constraints": [{"constraint_type": "ATTACHMENT_MANIFEST"}]},
        {
            "constraints": [
                {
                    "constraint_type": "ATTACHMENT_MANIFEST",
                    "attachment_batch_id": BATCH_ID,
                    "attachment_manifest_hash": "bad",
                    "attachment_count": 1,
                    "total_size_bytes": 1,
                }
            ]
        },
        {
            "constraints": [
                {
                    "constraint_type": "ATTACHMENT_MANIFEST",
                    "attachment_batch_id": BATCH_ID,
                    "attachment_manifest_hash": "sha256:" + "a" * 64,
                    "attachment_count": 21,
                    "total_size_bytes": 1,
                }
            ]
        },
        {
            "constraints": [
                {
                    "constraint_type": "ATTACHMENT_MANIFEST",
                    "attachment_batch_id": BATCH_ID,
                    "attachment_manifest_hash": "sha256:" + "a" * 64,
                    "attachment_count": 1,
                    "total_size_bytes": -1,
                }
            ]
        },
    )
    for value in invalids:
        with pytest.raises(VoucherAttachmentManifestError):
            work_intent_manifest_binding(value)
