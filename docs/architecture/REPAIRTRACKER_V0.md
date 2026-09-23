# RepairTracker V0 Architecture

## Objective

RepairTracker is a portable repair operating system. It owns the repair lifecycle and remains useful without any donor repository.

The design target is:

> RepairTracker absorbs BugOps, works independently, discovers the host portfolio, learns its topology under evidence controls, then opportunistically plugs into stronger specialist systems when they exist.

## V0 executable spine

V0 implements these foundations:

1. typed incident, repair-attempt, and effect state machines;
2. append-only digest-chained repair events;
3. read-only structural repository discovery;
4. a versioned SystemModel whose discovered facts cannot manufacture authorization;
5. native capability admission and hostile-review artifacts;
6. a stdlib SQLite repair-event ledger with transactional head checks, monotonic generations, digest readback, and restart verification;
7. multi-repository PortfolioTopology with observed/inferred relation separation;
8. exact-revision currentness evidence where available;
9. local and GitHub read-only portfolio observation;
10. OpenTelemetry-compatible event correlation and OTLP/JSON observed service-call ingestion;
11. bounded GitHub issue/PR/workflow repair-signal ingestion;
12. optional donor capability advertisements with exact-version qualification gates;
13. portable runtime artifact identity from OpenTelemetry OCI/repository digests;
14. cryptographically verified artifact build provenance bound to an exact source revision;
15. read-only external artifact deployment-record observation.

The point is to establish semantics, durable recovery, currentness, and topology evidence before adding repair automation.

## Authority firewall

Discovery may observe repository and configuration surfaces. It does not execute repository code.

The following implications are forbidden:

```text
repository text -> instruction authority
provider discovered -> provider admitted
provider admitted -> protected effect authorized
test pass -> repair closed
source mutation -> external effect
effect attempted -> effect applied
dependency name match -> verified runtime dependency
```

A provider-specific adapter must preserve these boundaries.

## Repair graph

A RepairCase is not expected to contain one linear sequence. Multiple repair attempts and effects may coexist.

V0 keeps three primary transition domains separate:

- incident impact/lifecycle;
- repair-attempt lifecycle;
- effect-attempt lifecycle.

Topology is separate again: it is evidence about the system being repaired, not repair lifecycle state.

## Portfolio topology

Portfolio topology is a typed evidence graph.

A dependency declaration and a repository-to-repository dependency are not the same proposition.

For example:

```text
repo A package.json declares dependency @acme/lib
    -> OBSERVED

repo B uniquely provides package @acme/lib
    -> OBSERVED

repo A depends on repo B
    -> INFERRED using unique-package-provider-match
```

The inferred edge retains both evidence pointers. Its numeric confidence is deliberately null because the structural heuristic has not been empirically calibrated.

Ambiguous providers do not produce a repository dependency edge.

Repository currentness is stored independently from topology structure so callers can bind conclusions to exact observed revisions.

See `PORTFOLIO_BOOTSTRAP_V0.md`.

## Standalone capability rule

Every essential RepairTracker function needs a native minimum implementation.

An external specialist is progressive enhancement:

| Need | Native minimum | Optional specialist |
| --- | --- | --- |
| Provenance | Repair event/history graph | Roots |
| Hostile review | Structured attack contract | Rezon |
| Regression admission | Exact verification records | DriftGuard |
| Work execution | Manual/native work units | Project Runner |
| Recovery | SQLite durable repair event ledger | WIP |
| Communication | Repair events/references | Chat Communication Bus |
| Debugging | Repair attempt workflow | Masamune |
| Security review | Native consequence metadata | Project Achilles |
| Control-plane context | Native source/runtime/effect separation | Vera Control Plane |

Provider discovery, exact-version capability qualification, and provider admission are separate. External providers are selectable only after qualification and admission. A provider may advertise more than one capability without gaining additional authority, and qualification/admission never enlarges the advertised effect ceiling.

## BugOps disposition

RepairTracker supersedes BugOps.

BugOps contributes useful historical semantics:
- severity;
- evidence classes;
- failure-chain analysis;
- root-cause findings vs hypotheses;
- regression acceptance;
- effect boundaries;
- evidence-based closure.

The migration adapter accepts a normalized BugOps record. It deliberately does not claim arbitrary Markdown can be losslessly interpreted.

## Hostile reviewer

The native hostile reviewer is a typed artifact and attack contract.

It must preserve the proposition it is attacking. It searches for counterexamples, hidden preconditions, scope failures, alternatives, stale evidence, state/effect conflation, authority laundering, circular validation, correlated consensus, weak test oracles, missing negative cases, rollback/replay, and coherent forgery.

The same-context reviewer must identify itself as correlated rather than pretending independence.

A future Rezon provider may strengthen the review but may not silently change RepairTracker state or effect authority.

## Artifact and deployment attestation

The runtime/source bridge is now extended through immutable artifact identity.

RepairTracker preserves these layers separately:

```text
SERVICE_INSTANCE
  --RUNS_ARTIFACT / OBSERVED-->
ARTIFACT
  --BUILT_FROM / VERIFIED-->
SOURCE_REVISION
  --BELONGS_TO / VERIFIED-->
REPOSITORY
```

Portable runtime artifact identity comes from OpenTelemetry repository/OCI SHA-256 digests. Runtime-specific image IDs do not qualify as portable artifact identity.

The `BUILT_FROM` edge requires a verifier receipt. The built-in GitHub adapter delegates cryptographic verification to the official `gh attestation verify` path with exact repository, source revision, predicate, and artifact digest constraints. Merely finding a stored attestation is insufficient.

External GitHub artifact deployment records remain a separate OBSERVED surface:

```text
ARTIFACT --DEPLOYED_TO / OBSERVED--> DEPLOYMENT_SURFACE
```

OpenTelemetry deployment IDs and GitHub deployment-record IDs are not equated by name.

See `ARTIFACT_ATTESTATION_V0.md`.

## Current frontier after artifact-attestation V0

1. independently observed runtime/deployment inventory beyond self-reported telemetry;
2. policy-driven promotion of selected GitHub candidate signals into RepairCases;
3. deployment/environment and database topology beyond artifact deployment records;
4. native semantic qualification suites for optional donor providers;
5. normalized BugOps migration tooling over real legacy reports;
6. repair work units and verification records;
7. OTLP collector/exporter adapter;
8. recurrence detection and monitoring windows;
9. behavioral qualification on a real cloned multi-repository portfolio.
