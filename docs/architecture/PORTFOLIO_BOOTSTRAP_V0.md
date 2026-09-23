# Portfolio Bootstrap and Topology Reconstruction V0

## Purpose

RepairTracker must be useful after being cloned into a portfolio it has never seen.

That requires more than listing files. It needs a reconstructible topology in which observed facts, inferred relationships, verified relationships, and currentness are distinct.

This V0 frontier introduces:

- multi-repository observations;
- exact-revision currentness where the source exposes one;
- typed topology nodes and edges;
- manifest-derived package identities and dependency declarations;
- explicitly inferred cross-repository dependencies;
- local read-only portfolio bootstrap;
- GitHub REST read-only repository observation and bounded user/org portfolio enumeration;
- OpenTelemetry-compatible repair event correlation;
- optional donor capability advertisements.

## Epistemic model

The system keeps these propositions separate:

```text
manifest says "A depends on package X"
    = OBSERVED

repository B uniquely declares itself as package X
    = OBSERVED

therefore repository A depends on repository B
    = INFERRED (unique-package-provider-match)

A runtime or reviewed architecture record confirms A calls B
    = future VERIFIED relation
```

An inferred edge cannot be emitted without an inference rule.

An observed or verified edge cannot be emitted without evidence.

## Currentness

Every repository observation carries a CurrentnessEvidence record.

GitHub observations:

```text
default branch -> exact branch head SHA -> tree/manifests/workflows
```

The exact revision is included in evidence pointers used by topology edges.

Local observations read `.git/HEAD` and refs without executing Git. When an exact revision cannot be recovered, currentness is explicitly `OBSERVED_UNPINNED` rather than guessed.

A portfolio has a separate `currentness_digest` derived only from its subject/revision bindings. This allows a caller to distinguish "same topology structure" from "same exact observed revisions."

## Topology objects

Initial node classes:

- PORTFOLIO
- REPOSITORY
- PACKAGE
- WORKFLOW
- TEST_SURFACE
- BUILD_SURFACE
- DEPLOYMENT_SURFACE
- DATASTORE
- CAPABILITY_PROVIDER

Initial relation classes:

- CONTAINS
- PROVIDES
- DECLARES_DEPENDENCY
- DEPENDS_ON
- TESTS
- BUILDS
- DEPLOYS
- EMITS_TELEMETRY_TO
- PROVIDES_CAPABILITY
- REFERENCES

Relation dispositions:

- OBSERVED
- INFERRED
- VERIFIED

V0 currently infers `DEPENDS_ON` only when a manifest dependency package has exactly one provider in the observed portfolio. Ambiguous providers remain unresolved and produce a warning.

## GitHub adapter

`GitHubReadClient` is a read-only adapter.

RepairTracker can either observe explicitly selected repositories or enumerate a bounded GitHub user/organization portfolio. Owner enumeration is paginated at up to 100 repositories per request, filters archived repositories and forks by default, and returns a completeness warning if its configured repository ceiling is reached.

For each selected repository it:

1. reads repository metadata;
2. resolves the default branch;
3. captures branch head B0;
4. reads the recursive Git tree and supported dependency manifests pinned to B0;
5. identifies workflow paths from that exact Git tree;
6. re-reads branch head and default branch as B1;
7. accepts the observation only when B0/B1 are stable, retrying the full sequence once before failing closed.

The stdlib transport exposes GET only and restricts its API host to `https://api.github.com`.

A truncated recursive Git tree does not become an exhaustive result; it emits a warning.

Manifest reads are bounded by count and byte limits.

Repository contents remain evidence. They are never executable instructions or authorization.

## Supported dependency manifests

V0 parses without executing repository code:

- `pyproject.toml`
- `package.json`
- `go.mod`
- `Cargo.toml`

The parser extracts package identities and declared dependencies.

Name matching is intentionally conservative. A unique package-provider match produces an inferred repository dependency with confidence below 1.0 and keeps both source observations attached.

## OpenTelemetry correlation

RepairTracker emits an OpenTelemetry-compatible semantic event representation.

The event uses the low-cardinality name:

```text
repairtracker.repair.event
```

Dynamic values such as repair ID, subject ID, event type, evidence class, source system, authority/effect ceiling, and event digest are attributes rather than part of the event name.

The event timestamp is the RepairEvent occurrence time. The observed timestamp is the RepairEvent observation time.

Optional W3C trace context supplies trace ID, span ID, and flags.

This V0 representation is not an OTLP protobuf exporter. Export transport is a later adapter boundary.

## Donor capabilities

Known donor repositories can emit unqualified optional-capability advertisements only when the exact repository identity is recognized. Repository identity is an integration hint, not proof that the current revision satisfies a historical donor contract.

Current descriptors:

| Repository | Capability |
| --- | --- |
| roots | PROVENANCE |
| rezon | HOSTILE_REVIEW |
| driftguard | REGRESSION_ADMISSION |
| project-runner | WORK_EXECUTION |
| wip | RECOVERY |
| chat-communication-bus | COMMUNICATION |
| masamune | DEBUGGING |
| project-achilles | SECURITY_REVIEW |
| vera-control-plane | CONTROL_PLANE |

Advertisements bind to the observed repository revision when available and use an `OBSERVE_ONLY` effect ceiling.

Detection does not qualify or admit the provider. The current descriptor layer is non-executable discovery metadata; semantic qualification is a later gate. Admission still requires a separate registry action and never enlarges the provider's effect ceiling.

BugOps remains a migration/import source, not a continuing optional authority provider.

## Known limits

This frontier does not yet prove:

- exhaustive account-wide discovery beyond the selected GitHub owner or configured repository ceiling;
- service-call topology from runtime traces;
- deployment target inference;
- database/schema topology;
- CODEOWNERS-to-runtime ownership equivalence;
- dependency resolution beyond supported manifest identity matching;
- OTLP network export;
- automatic donor-provider admission;
- authority to execute any discovered repair capability.

Those are later frontiers and must not be implied by the current source.
