# MyBee Phase 1 MB1-02 D12 Project Template Consumer Contract

## Scope

MB1-02 publishes the immutable MyBee D12 Project template and a
transport-neutral consumer for the S1-05 EOS Project WorkCodeSet and
BusinessReady APIs. It does not add a database table, duplicate EOS business
state, or activate an NSL Tool.

The admitted template identity is:

- template ID `mybee.d12.required-five`;
- template version `1.0.0`, revision `1`;
- status `EOS_CONSUMER_ADMITTED`;
- content digest
  `sha256:5476e505e33ceb2551f8edb080010b34e5425906029df3c90214751177274fe3`.

## Catalog Binding

The template pins the MB1-01 source catalog and the S1-05 provider contract:

- catalog ID `mybee.fl.d12.project-governance`;
- catalog version `1.0.0`;
- catalog digest
  `sha256:31e5a24a8a5e62f80fc1571a4a232723a90f9c1b628841ae80df24654848c8ba`;
- mandatory set `FL0012004`, `FL0012005`, `FL0012006`, `FL0012013`, and
  `FL0012026`;
- mandatory-set hash
  `sha256:f867477ed5983904e1c4a353bf05a4a11ffb56b5fa0299ffd63bbc8cd70bd9a1`.

`required_five.json` is validated by a strict Draft 2020-12 schema and a
fail-closed runtime loader. Catalog, operation, readiness, ownership, or
attestation drift prevents admission.

## EOS Consumer Boundary

MyBee builds requests only for these admitted EOS operations:

| Operation | Method and path | Purpose |
| --- | --- | --- |
| `PROJECT.WORK_CODE_SET.APPROVE` | `POST /internal/v2/projects/{project_id}/work-code-sets:approve` | Approve one immutable D12 WorkCodeSet revision |
| `PROJECT.WORK_CODE_SET.GET` | `GET /internal/v2/projects/{project_id}/work-code-set` | Read the effective approved revision |
| `PROJECT.BUSINESS_READINESS.GET` | `GET /internal/v2/projects/{project_id}/business-readiness` | Admit Project business execution readiness |

Approval request hashing is byte-for-byte compatible with the S1-05 EOS
provider helper. The consumer does not import EOS private source, open the EOS
database, or infer readiness from local data.

## Runtime Admission

The consumer fails closed unless:

1. tenant and Project scope match the request;
2. the returned WorkCodeSet pins the admitted catalog, template, mandatory
   set, proof lineage, and approved state;
3. human PM and PA identity references are distinct;
4. the EOS readiness source hash is valid;
5. technical status is `ACTIVE` and projection state is `BUSINESS_READY`;
6. every required readiness flag is true and no reason code remains;
7. the nested WorkCodeSet hash matches the readiness projection.

Technical Project `ACTIVE` is deliberately insufficient for PA-domain WRITE.
The caller must use the admitted `BUSINESS_READY` projection.

## Deferred Scope

- WorkAssignment, Grade, and planned Man-Day remain deferred to S1-06.
- NSL Tool binding remains deferred to MB8-01.
- Transport authentication and retry policy remain owned by the installed
  service client; MB1-02 defines a transport-neutral request contract.
- No remote model provider or PostgreSQL migration is required by this Slice.

## Verification

- Focused MB1-02 contract suite: `48 passed`.
- New `project_templates.py`: statement `100.00%`, branch `100.00%`.
- MyBee plus S1-05 EOS regression: `250 passed`, `1` explicit protected
  PostgreSQL smoke skipped.
- Static formatting and lint: PASS.
- EOS/MyBee Slice Gate: `1246 passed`, `34` explicit protected tests skipped;
  all `6/6` commands passed.
- Slice Gate coverage: statement `97.08%`, branch `96.18%`.
- MyBee coverage scope: statement `99.91%`, branch `99.36%`.
- Contract validation passed for `233` schemas, `292` examples, `245`
  negative examples, and `10` OpenAPI documents.
- MyBee exact compatibility lock, Golden Journey transition audit, and
  demo/product dependency audit: PASS.
