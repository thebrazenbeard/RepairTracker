# Artifact and Deployment Attestation V0

## Objective

RepairTracker must be able to distinguish four different propositions:

```text
runtime says service instance I is running artifact digest D
GitHub says an attestation exists for D
cryptographic verifier says attestation A for D is authentic under policy P
verified attestation A binds D to exact source revision S
```

Those propositions are not interchangeable.

V0 completes the source-level chain:

```text
SERVICE / service.instance.id
  --RUNS_ARTIFACT / OBSERVED-->
ARTIFACT sha256:D
  --BUILT_FROM / VERIFIED-->
SOURCE_REVISION repo@S
  --BELONGS_TO / VERIFIED-->
REPOSITORY
```

The `BUILT_FROM` edge is deliberately bounded by its verification metadata. It means a cryptographically verified SLSA provenance attestation bound the immutable artifact digest to the source revision under the enforced verification policy. It does not establish that the build platform or workflow was uncompromised.

## Runtime artifact identity

RepairTracker consumes OpenTelemetry resource attributes when present:

- `container.id`
- `container.image.id`
- `container.image.name`
- `container.image.repo_digests`
- `oci.manifest.digest`
- service/deployment attributes already used by the runtime topology layer.

Portable artifact identity prefers:

1. `container.image.repo_digests`
2. `oci.manifest.digest`

Both must resolve to a SHA-256 digest.

`container.image.id` is retained as observation context but is not promoted to portable artifact identity because OpenTelemetry documents it as runtime-specific.

If one runtime observation reports conflicting repository digests, or a repository digest disagrees with `oci.manifest.digest`, RepairTracker fails closed rather than selecting one.

If several repository names report the same digest, the portable digest is retained but the artifact name is left ambiguous rather than selecting one registry path arbitrarily.

The runtime edge claim ceiling is:

`RUNTIME_OBSERVED_PORTABLE_ARTIFACT_DIGEST`

## Attestation discovery is not verification

The GitHub REST repository-attestation endpoint can locate bundle references for a subject digest.

RepairTracker exposes that through:

```text
repairtracker github-attestations OWNER/REPO sha256:D
```

The output explicitly reports:

```json
"cryptographically_verified": false
```

RepairTracker does not fetch an arbitrary returned bundle URL or upgrade the listing into verified provenance.

A GitHub 404 at the attestation-subject endpoint is preserved as ambiguous: it may mean no matching attestation or an inaccessible resource. RepairTracker therefore returns no references plus an incompleteness warning rather than claiming a complete empty set.

GitHub documents that meaningful security requires cryptographic signature/timestamp verification and signer identity validation; listing an attestation is insufficient.

## Cryptographic verification

The optional native adapter delegates verification to the GitHub CLI:

```text
gh attestation verify
```

The RepairTracker CLI surface is:

```text
repairtracker verify-oci-attestation IMAGE SHA256_HEX OWNER/REPO SOURCE_SHA
```

V0 enforces:

- digest-pinned OCI identity;
- no mutable tag in the image name;
- linked GitHub repository;
- exact full source Git revision through `--source-digest`;
- SLSA provenance v1 predicate type;
- optional exact signer workflow;
- denial of self-hosted runners by default, with explicit policy opt-out;
- optional OCI-registry bundle retrieval.

The verifier returns an `AttestationVerificationReceipt` only after the GitHub CLI exits successfully and emits usable verified JSON.

## SLSA/in-toto validation

RepairTracker independently checks the verified statement before graph promotion:

- in-toto Statement v1;
- SLSA provenance v1;
- subject SHA-256 equals the runtime artifact digest;
- resolved dependency contains the cryptographically verified GitHub source repository and full Git revision;
- workflow repository metadata, when present, is canonical GitHub HTTPS metadata and agrees with the verified source repository.

The build type, builder ID, invocation ID, and predicate fields are recorded as evidence metadata. They are not silently promoted into stronger trust.

GitHub's verifier documentation warns that provenance predicate content may be influenced by the originating workflow. V0 therefore records:

```text
build_platform_integrity = NOT_ESTABLISHED
predicate_trust_ceiling =
  SIGNED_BUT_WORKFLOW_CONTEXT_CAN_INFLUENCE_PREDICATE
```

If a signer workflow policy was supplied and enforced, the edge records that fact separately. It does not call the workflow trustworthy merely because its identity was enforced.

## Source membership readback

After cryptographic attestation verification, RepairTracker independently resolves the exact source revision through the read-only GitHub commit API.

That creates or reinforces:

```text
SOURCE_REVISION
  --BELONGS_TO / VERIFIED-->
REPOSITORY
```

with ceiling:

`SOURCE_REVISION_EXISTS_IN_REPOSITORY`

This readback prevents a provenance object from manufacturing a repository/revision identity not present in the observed portfolio.

## Artifact deployment records

RepairTracker also reads GitHub organization artifact-metadata deployment records by exact SHA-256 subject digest.

The read adapter preserves the documented deployment fields:

- record ID;
- logical environment;
- physical environment;
- cluster;
- deployment name;
- attestation ID;
- creation/update timestamps;
- exact artifact digest;
- deterministic payload digest.

These records produce:

```text
ARTIFACT
  --DEPLOYED_TO / OBSERVED-->
DEPLOYMENT_SURFACE
```

with ceiling:

`EXTERNAL_ARTIFACT_DEPLOYMENT_RECORD`

This is not a cryptographic edge. The presence of an attestation ID in the deployment record does not substitute for `gh attestation verify`.

OpenTelemetry `deployment.id` and GitHub artifact-metadata deployment-record IDs are not assumed to share an identity namespace.

```text
OTEL_DEPLOYMENT_ID != GITHUB_DEPLOYMENT_RECORD_ID
```

unless a future evidence-bearing mapping proves otherwise.

## Live cryptographic qualification

The CI `github-read-smoke` job performs a real cryptographic verification through RepairTracker's own file-verification adapter against a pinned public artifact:

- repository: `cli/cli`;
- release: `v2.100.0`;
- source commit: `45437bc7eeeb3359bbfddd1742f79de7652fd3e2`;
- artifact: `gh_2.100.0_linux_amd64.tar.gz`;
- expected SHA-256: `e4d4bb4498e8d007abe545b6568926793ace1b6447da598294a610018cb164be`.

The verifier defaults to `--deny-self-hosted-runners`. Callers may explicitly opt out when their own trust policy permits self-hosted build runners.

## Replay and evidence accumulation

Repeated observations of the same semantic relationship are expected.

Topology edges therefore merge new evidence only when every non-evidence semantic field is identical. Any semantic drift under the same edge identity remains a collision and fails closed.

This allows repeated runtime traces and repeated attestation verification receipts to strengthen evidence without rewriting the proposition.

## Standards alignment

V0 follows these current external contracts:

- in-toto Statement v1 subjects are immutable artifact descriptors identified by digest;
- SLSA provenance v1 uses resolved dependencies for build inputs, including Git source revisions;
- GitHub artifact attestations use SLSA provenance and Sigstore verification;
- GitHub CLI attestation verification can enforce repository, source digest, signer workflow, predicate type, and runner policy;
- OpenTelemetry repository/manifest image digests are preferred over runtime-specific image IDs for portable identity.

## Claim ceiling

This frontier establishes source-qualified mechanisms for:

- observing a digest-pinned runtime artifact;
- locating GitHub attestation references without overclaiming;
- invoking cryptographic GitHub attestation verification;
- validating the verified SLSA statement against the runtime artifact and source revision;
- binding the artifact to an exact source revision in the evidence graph;
- independently confirming that source revision belongs to the observed repository.

It does not establish:

- that every host portfolio emits the necessary OTel container/resource attributes;
- that every artifact has a GitHub attestation;
- that the build platform or workflow was uncompromised;
- reproducibility of the artifact;
- runtime admission enforcement;
- deployment mutation or rollback authority;
- permission to generate, delete, or publish attestations.

No attestation is generated by this V0 path.
