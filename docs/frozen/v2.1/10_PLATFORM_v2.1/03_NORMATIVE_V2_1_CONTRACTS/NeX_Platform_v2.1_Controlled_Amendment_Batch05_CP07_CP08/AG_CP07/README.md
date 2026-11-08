# PLAT-CP07 Governance Contracts

Governance remains a PAP/projection plane. OA remains PDP, AE Agent Registry remains Agent identity/profile SoR, and AE Skill Artifact Gateway produces runtime PackageTrustEvidence.

New v2.1 governance vocabulary:
- AGENT_PROFILE
- TRUST_PROFILE / TRUST_EVALUATOR
- NSP_PACKAGE / PUBLISHER / SIGNING_KEY

AG does not become the runtime PackageTrustEvidence producer or Agent identity SoR.


## Step 3 WRITE Contract Hardening v1.4
AG package governance remains a PAP/projection plane. Artifact admission must consume current package/publisher/signing-key governance and produce typed PackageTrustEvidence / ArtifactAdmissionDecision before a production WRITE artifact can be constructed.
