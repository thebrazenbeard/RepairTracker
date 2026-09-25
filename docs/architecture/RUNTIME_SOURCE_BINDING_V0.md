# Runtime to Source Identity Binding V0

## Objective

RepairTracker needs to connect runtime observations to source without laundering self-reported telemetry into provenance proof.

V0 therefore models two separate propositions:

```text
runtime service reports repository + revision
    = OBSERVED

GitHub resolves that immutable revision to an exact commit in that repository
    = VERIFIED repository membership
```

Those propositions compose, but they do not prove that the running artifact was built from that source commit.

## OpenTelemetry inputs

The binding layer consumes these resource attributes when present:

- `service.name`
- `service.namespace`
- `service.instance.id`
- `service.version`
- `deployment.environment.name`
- `vcs.repository.url.full`
- `vcs.ref.head.revision`

The service namespace/name pair identifies the logical service. Instance, version, and deployment environment remain contextual attributes.

For GitHub source binding, V0 accepts only canonical `https://github.com/owner/repo` repository URLs.

## Exact revision rule

OpenTelemetry allows `vcs.ref.head.revision` to be a symbolic value such as a branch name.

RepairTracker does not treat a mutable branch name as an exact historical source binding.

V0 only attempts source binding when the reported revision is an immutable-looking hexadecimal revision of at least seven characters.

GitHub resolution must return an exact commit SHA beginning with that reported revision. Otherwise binding fails closed.

## Topology

The binding creates:

```text
SERVICE
  --REPORTS_SOURCE / OBSERVED-->
SOURCE_REVISION
  --BELONGS_TO / VERIFIED-->
REPOSITORY
```

The first edge has claim ceiling:

`RUNTIME_SELF_REPORTED_SOURCE`

The second edge has verification ceiling:

`SOURCE_REVISION_EXISTS_IN_REPOSITORY`

This prevents a GitHub commit lookup from being misrepresented as build provenance.

## Missing proof

A stronger chain still requires artifact/deployment evidence:

```text
runtime service
  -> deployment instance
  -> immutable artifact identity/digest
  -> build provenance or attestation
  -> exact source revision
```

Until that exists, RepairTracker may say:

- the runtime reported repository/revision X;
- GitHub independently confirmed X exists in repository Y.

It may not say:

- the live binary/container was proven to have been built from X.

That is the next claim ceiling.
