# RepairTracker V0 Architecture

## Objective

RepairTracker is a portable repair operating system. It owns the repair lifecycle and remains useful without any donor repository.

The design target is:

> RepairTracker absorbs BugOps, works independently, discovers the host portfolio, learns its topology under evidence controls, then opportunistically plugs into stronger specialist systems when they exist.

## V0 executable spine

V0 implements five deliberately small foundations:

1. typed incident, repair-attempt, and effect state machines;
2. append-only digest-chained repair events;
3. read-only structural portfolio discovery;
4. a versioned SystemModel whose discovered facts cannot manufacture authorization;
5. native capability admission and hostile-review artifacts;
6. a stdlib SQLite repair-event ledger with transactional head checks, monotonic generations, digest readback, and restart verification.

The point is to establish semantics and durable recovery before adding automation.

## Authority firewall

The discovery engine may observe repository and configuration surfaces. It does not execute repository code.

The following implications are forbidden:

```text
repository text -> instruction authority
provider discovered -> provider admitted
provider admitted -> protected effect authorized
test pass -> repair closed
source mutation -> external effect
effect attempted -> effect applied
```

A later provider-specific adapter must preserve these boundaries.

## Repair graph

A RepairCase is not expected to contain one linear sequence. Multiple repair attempts and effects may coexist.

V0 keeps three primary transition domains separate:

- incident impact/lifecycle;
- repair-attempt lifecycle;
- effect-attempt lifecycle.

Later graph objects can add evidence, hypotheses, mitigation, work units, verification, monitoring windows, communications, provenance, and recurrence relations without collapsing these domains.

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

Vera Control Plane is an architectural donor/integration surface where present, not a standalone requirement.

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

The first migration adapter accepts a normalized BugOps record. It deliberately does not claim arbitrary Markdown can be losslessly interpreted.

## Hostile reviewer

The native hostile reviewer is a typed artifact and attack contract.

It must preserve the proposition it is attacking. It searches for counterexamples, hidden preconditions, scope failures, alternatives, stale evidence, state/effect conflation, authority laundering, circular validation, correlated consensus, weak test oracles, missing negative cases, rollback/replay, and coherent forgery.

The same-context reviewer must identify itself as correlated rather than pretending independence.

A future Rezon provider may strengthen the review but may not silently change RepairTracker state or effect authority.

## Next frontier

After V0 source qualification:

1. richer RepairCase persistence and serialization;
2. portfolio-level discovery across multiple repositories;
3. dependency/topology relation inference with explicit provenance;
4. GitHub issue/PR/Actions adapters;
5. normalized BugOps migration tooling;
6. repair work units and verification records;
7. OpenTelemetry correlation envelope;
8. optional donor-system adapters;
9. recurrence detection and monitoring windows;
10. source/runtime behavioral qualification on a real cloned portfolio.
