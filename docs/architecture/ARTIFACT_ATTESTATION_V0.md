# Artifact and Deployment Attestation V0

## Objective

RepairTracker must distinguish four different propositions:

```text
runtime reports portable artifact digest D
artifact D has cryptographically verified build provenance
that provenance is constrained to source revision S
artifact D has an external deployment record
```

None of those statements is silently substituted for another.

The stronger composed chain is:

```text
SERVICE_INSTANCE
  --RUNS_ARTIFACT / OBSERVED-->
ARTIFACT
  --BUILT_FROM / VERIFIED-->
SOURCE_REVISION
  --BELONGS_TO / VERIFIED-->
REPOSITORY
```

The existing lightweight runtime topology also keeps:

```text
SERVICE --RUNS_ARTIFACT / OBSERVED--> ARTIFACT
```

for portable artifact observation when instance/source/attestation evidence is unavailable.

## Runtime artifact identity

OpenTelemetry resource ingestion recognizes:

- `service.instance.id`;
- `service.version`;
- `deployment.environment.name`;
- `deployment.id`;
- `deployment.name`;
- `container.id`;
- `container.image.id`;
- `container.image.name`;
- `container.image.repo_digests`;
- `oci.manifest.digest`;
- `vcs.repository.url.full`;
- `vcs.ref.head.revision`.

For portable OCI identity, RepairTracker uses SHA-256 repository digests or OCI manifest digests. Runtime-specific `container.image.id` is retained as telemetry context but is not promoted to portable artifact identity.

If repository digests disagree with one another, or disagree with `oci.manifest.digest`, binding fails closed.

If one digest is reported under multiple registry/repository names, the digest remains usable as portable identity but no single OCI verification reference is invented.

The lightweight runtime artifact edge retains:

`RUNTIME_OBSERVED_PORTABLE_ARTIFACT_DIGEST`

The stronger attested runtime binding additionally requires `service.instance.id`, a canonical GitHub repository source claim, an immutable-looking VCS revision, and an unambiguous OCI artifact reference. Its instance-to-artifact edge retains:

`RUNTIME_SELF_REPORTED_ARTIFACT`

## Cryptographic provenance

GitHub can return stored artifact attestations, but stored-attestation presence alone is not treated as verification.

The built-in GitHub verification adapter delegates cryptographic signature, trusted-root, timestamp, identity-policy, predicate, artifact-integrity, and expected-source verification to the official GitHub CLI:

`gh attestation verify`

The adapter constrains verification by:

- expected repository identity;
- exact resolved source revision through `--source-digest`;
- SLSA provenance v1 predicate type;
- exact SHA-256 artifact subject in the verified statement;
- successful GitHub CLI verification;
- GitHub-hosted runner provenance by default through `--deny-self-hosted-runners`.

An optional signer-workflow policy can further narrow accepted signer identity.

The verified artifact edge receives this ceiling:

`CRYPTOGRAPHIC_ARTIFACT_BUILD_PROVENANCE`

The complete JSON verification result is hashed into the receipt evidence.

The attestation predicate is not itself treated as the trust root. The security decision depends on the verifier result and configured identity/source constraints.

## Source revision

Before attestation verification, RepairTracker independently resolves the telemetry-reported immutable-looking VCS revision against the observed GitHub repository.

The attestation verifier receives that exact resolved source revision.

The source-to-repository edge remains separately qualified as:

`SOURCE_REVISION_EXISTS_IN_REPOSITORY`

This prevents repository membership from being confused with artifact provenance.

## Deployment records

For GitHub organizations, RepairTracker can read artifact deployment records using the artifact-metadata read endpoint.

A deployment record is bound to the exact requested SHA-256 artifact digest. A record returning another digest fails closed.

Deployment records retain:

- logical environment;
- physical environment;
- cluster;
- deployment name;
- attestation ID;
- creation/update timestamps;
- immutable payload digest.

The topology relation is:

```text
ARTIFACT --DEPLOYED_TO / OBSERVED--> DEPLOYMENT_SURFACE
```

with ceiling:

`EXTERNAL_ARTIFACT_DEPLOYMENT_RECORD`

A deployment record is not promoted to cryptographic proof merely because it contains an attestation ID.

RepairTracker deliberately does not equate OpenTelemetry `deployment.id` with a GitHub artifact-metadata deployment-record ID. They are separate namespaces until evidence establishes an identity mapping:

```text
OTEL_DEPLOYMENT_ID != GITHUB_DEPLOYMENT_RECORD_ID
```

by default.

## Replay behavior

Repeated observations of the same semantic topology edge accumulate evidence.

An edge ID reused with different non-evidence semantics still fails closed.

This allows recurring runtime observations and repeated verification receipts without converting harmless replay into topology corruption.

## Verification surfaces

The CI matrix exercises the source on:

- Ubuntu with Python 3.11, 3.12, and 3.13;
- Windows with Python 3.11, 3.12, and 3.13.

A dedicated Ubuntu smoke downloads a pinned GitHub CLI release artifact and executes RepairTracker's attestation verifier against the real GitHub attestation service.

Pinned external qualification subject:

- repository: `cli/cli`;
- release: `v2.100.0`;
- source commit: `45437bc7eeeb3359bbfddd1742f79de7652fd3e2`;
- artifact: `gh_2.100.0_linux_amd64.tar.gz`;
- artifact digest: `sha256:e4d4bb4498e8d007abe545b6568926793ace1b6447da598294a610018cb164be`.

## Claim ceiling

A successful attested runtime chain establishes:

- a particular runtime instance reported immutable artifact digest D;
- GitHub's attestation verifier cryptographically verified D under the configured identity policy;
- that verification was constrained to exact source revision S;
- GitHub independently resolves S inside repository R.

It still does not prove runtime telemetry itself is tamper-proof.

Stronger production qualification may add independently observed deployment/runtime inventory, admission-controller receipts, workload identity, or signed deployment inventory.

## Effect ceiling

All V0 artifact/deployment integrations are read-only.

No deployment, image mutation, attestation creation, credential change, permission change, provider mutation, or other protected effect is performed by this frontier.
