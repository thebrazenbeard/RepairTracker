# GitHub and OpenTelemetry Integration V0

## GitHub

RepairTracker's native GitHub adapter is read-only.

It supports three separate observation surfaces:

1. repository topology;
2. bounded user/organization repository enumeration;
3. candidate repair signals from issues, pull requests, and failed workflow runs.

Repository topology reads use a stability sequence:

```text
default branch + B0 head
  -> payload pinned to B0
  -> B1 head + default branch readback
```

If B0 and B1 differ, the complete sequence retries once. A second unstable result fails closed instead of mixing revisions.

Owner enumeration is bounded and emits incompleteness warnings when its configured ceiling is reached. Archived repositories and forks are excluded by default.

Candidate repair signals are observations only. They never auto-create RepairCases.

## OpenTelemetry

RepairTracker has two native OTel surfaces.

The first maps RepairEvents to a low-cardinality semantic event named:

```text
repairtracker.repair.event
```

Repair-specific values are attributes.

The second ingests OTLP/JSON trace payloads. OTLP trace/span identifiers are parsed as hex identifiers. Resource `service.name` is required for service topology; `service.namespace` is used when present.

When a parent span and child span in one trace belong to different services, RepairTracker may add an:

```text
SERVICE --CALLS / OBSERVED--> SERVICE
```

edge carrying both span evidence references.

This is deliberately weaker than:

```text
SERVICE --DEPENDS_ON / VERIFIED--> SERVICE
```

One observed call does not prove a durable architectural dependency.

## Provider boundary

Optional donor repositories are recognized only as candidate capability providers.

For external providers:

```text
repository observed
  != provider qualified
  != provider admitted
  != effect authorized
```

Qualification is bound to the exact advertised provider version and capability. Admission is a distinct operator decision. The provider's declared effect ceiling survives both steps unchanged.

## Current claim ceiling

V0 proves source-level mechanisms for read-only GitHub observation, OTLP/JSON parsing, observed service-call topology, and external capability gating.

It does not prove an OTLP collector/exporter, continuous production monitoring, service-to-repository identity binding, automatic RepairCase promotion, or permission to execute donor systems.
