# P8-DEMO-S08: OpenBao Secret, Trust, and PKI Admission

## Outcome

The additive Demo deployment now has one owner-scoped OpenBao inventory for
all seven backend services. Historical S143 configuration remains unchanged.
The Demo inventory admits 31 secret bindings across OA, AE, CX, MO, AG, WC,
and EOS, including all 16 cross-service signed-token grants used by the
installed source.

AE-to-MO and AE-to-AG were found in the runtime source but absent from the old
five-service production manifest. They are explicitly included in the Demo
inventory together with the AE/WC/EOS trust paths introduced by P8.

## Runtime Boundary

`NEX_DEPLOYMENT_BOUNDARY=P8_DEMO` selects the Demo owner materializer. Each
container resolves only the bindings owned by its service AppRole. Raw values,
other-owner references, malformed versions, resolver metadata drift, and
missing generations fail closed. All `*_REF` and AppRole credential-file
inputs are removed before the packaged process is executed.

The existing production bootstrap remains the entrypoint. The historical
S143 five-owner manifest and default helper behavior are unchanged.

## Trust and PKI

The Demo trust contract records each outbound token's owner, audience, and
required scopes. OpenBao stores opaque token values; OA issuance and semantic
token validation remain part of the installed protected journey rather than
secret custody.

The managed certificate covers all 13 routed names, including WC, EOS,
identity, object storage, and the three DGX provider routes.

## Protected Evidence

The protected runner starts an isolated digest-pinned OpenBao instance and
proves:

- seven AppRoles and least-privilege owner policies;
- 31 versioned KV v2 bindings;
- generation `v1` to `v2` rotation;
- per-owner resolution before and after rotation;
- denied cross-owner access;
- OpenBao PKI issuance with the exact 13-host SAN set;
- cleanup of the temporary Raft volume and runtime material;
- evidence with no secret or token value.

Synthetic opaque payloads are used for this custody rehearsal. S10 owns OA
service-principal exchange and end-to-end signed-token meaning.

Observed protected result:

```text
status = PASS
owners = 7
secrets = 31
generations = [1, 2]
owner resolutions = 7 + 7
cross-owner access denied = true
routed TLS hosts = 13
certificate SANs = 14 (13 routes + nex-staging.test common name)
runtime residue retained = false
```

The focused Slice Gate passed 379 tests with 97.78% statement and 97.28%
branch coverage across the changed runtime boundary. Contract validation
passed 207 schemas, 271 examples, 231 negative examples, and 9 OpenAPI files.
