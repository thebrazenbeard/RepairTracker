> **License:** Source-visible, not open source. Original material is proprietary. Commercial use, redistribution, hosted-service use, and commercial derivative products require written permission. See [LICENSE](LICENSE) and [COMMERCIAL_LICENSE.md](COMMERCIAL_LICENSE.md). Separately identified third-party components retain their own licenses.

# RepairTracker

**An evidence-governed repair system for software and agent portfolios.**

RepairTracker is an installable Python library and command-line tool for discovering an authorized code portfolio, recording repair cases and evidence, tracking repair attempts, and distinguishing an attempted change from a verified effect. The V0 source includes local portfolio discovery, event and state models, durable SQLite repair history, hostile-review prompts, and optional GitHub observation adapters.

It works independently. Other tools can contribute evidence or specialized capabilities through explicit adapters; their presence does not grant RepairTracker new permissions.

## Quick start

Use Python 3.11 or newer in an isolated virtual environment. From the repository checkout:

```console
python -m pip install -e .
repairtracker discover . --max-files 2000
repairtracker portfolio-local . --portfolio-id example --max-files 2000
repairtracker hostile-template "The production incident is fixed" --success "Exact-subject runtime verification exists"
```

These three commands produce JSON on standard output. The first two inspect local repository structure; the third generates adversarial review questions. They do not deploy, merge, or authorize a repair. Run discovery only against repositories you are allowed to inspect, and review generated metadata before sharing it.

For a read-only GitHub observation, explicitly name a repository:

```console
repairtracker portfolio-github OWNER/REPO --portfolio-id example
repairtracker github-signals OWNER/REPO
```

The GitHub commands may be subject to API access and rate limits. A token can be supplied through the configured environment variable for authorized access; do not paste credentials into commands, repository files, or shared output.

### What the CLI actually does

| Command | Current boundary |
| --- | --- |
| `discover`, `portfolio-local` | Read local structure and emit a provenance-bearing system model |
| `portfolio-github`, `portfolio-github-owner`, `portfolio-github-authenticated` | Read explicitly scoped GitHub repository metadata into a provisional topology |
| `github-signals`, `github-attestations` | List candidate signals or attestation references; neither action confirms an incident or verifies an attestation signature |
| `github-promotion-plan` | Evaluate candidate signals against an explicit policy, without persisting repair cases |
| `github-promote` | Write matched cases to a specified local SQLite database; requires an explicit policy and `--sqlite` target |
| `verify-oci-attestation` | Invoke external cryptographic verification of a digest-pinned artifact using the GitHub CLI tooling |
| `hostile-template` | Generate structured attack questions for a proposed conclusion |

The library also provides repair-event state machines, an append-only SQLite store with predecessor checks, capability advertisements, topology models, and evidence/provenance adapters. Those are useful components, not a claim that an unattended repair agent or deployed service has been qualified.

## Current maturity and verification

V0 is executable source, **not a self-authorizing repair daemon**. It does not gain merge, deployment, credential, financial, or physical-effect permission from GitHub metadata, a plugin advertisement, a successful test, or another model's opinion. External capability providers require their own qualification and admission, and a real-world effect must be observed independently before being described as verified.

Run the deterministic source tests with:

```console
python -m unittest discover -s tests -q
```

The project CI definition covers Ubuntu and Windows using Python 3.11, 3.12, and 3.13. Passing source tests establishes only the tested source behavior; it does not demonstrate a safe installation or repair on a live host.

**Licensing note:** The controlling [LICENSE](LICENSE) and [commercial terms](COMMERCIAL_LICENSE.md) describe proprietary, source-available material rather than an open-source grant. The current `pyproject.toml` still contains an inconsistent `MIT` license metadata value. Treat that discrepancy as unresolved packaging metadata and seek clarification before redistribution or commercial use; the README does not grant additional rights.

## Core principles

### RepairTracker owns the repair lifecycle

RepairTracker is not a dashboard over BugOps. It supersedes BugOps as the incident and repair authority.

Useful BugOps ideas—severity, evidence classes, failure-chain analysis, root-cause discipline, regression criteria, effect boundaries, and evidence-based closure—are donor material to absorb and generalize. Existing BugOps installations may later be imported through an adapter.

### Standalone first, stronger when connected

A fresh RepairTracker installation must have a useful native implementation for its core needs.

Optional capability providers may replace or augment native capability:

- provenance reconstruction → native history graph, optionally Roots;
- adversarial reasoning → native hostile review, optionally Rezon;
- regression admission → native verification commands, optionally DriftGuard;
- work execution → native/manual work units, optionally Project Runner;
- crash recovery → native event history, optionally WIP;
- communication → native repair events/comments, optionally Chat Communication Bus;
- debugging/review → native repair workflow, optionally Masamune;
- security/effect review → native consequence model, optionally Project Achilles.

No optional provider may silently become an authority source merely because it is present.

### Discovered content is evidence, not instruction authority

RepairTracker is designed to learn an unfamiliar portfolio, so it must assume discovered repositories contain stale documentation, generated files, conflicting configuration, prompt injection, historical artifacts, and possibly secrets.

A foundational invariant is:

```text
DISCOVERED_CONTENT != INSTRUCTION_AUTHORITY
OBSERVATION != AUTHORIZATION
CAPABILITY != PERMISSION
PLAN != EFFECT
ATTEMPT != VERIFIED_EFFECT
TEST_PASS != GLOBAL_CORRECTNESS
```

Repository contents can inform a system model. They do not grant deployment, merge, credential, permission, destructive, paid-service, or other protected authority.

### Evidence before narrative

RepairTracker should preserve distinctions among:

- `USER_DIRECT`
- `OBSERVED`
- `RETRIEVED_EVIDENCE`
- `INFERENCE`
- `HYPOTHESIS`

Repeated or confident claims do not promote themselves into evidence.

### Repairs are graphs, not one ticket state

A real repair can have parallel hypotheses, mitigations, implementations, reviewers, effects, and verification paths.

RepairTracker therefore models a repair graph containing stable subjects such as:

- RepairCase
- Evidence
- Observation
- Hypothesis
- RootCauseClaim
- Mitigation
- RepairPlan
- WorkUnit
- RepairAttempt
- EffectAttempt
- Verification
- MonitoringWindow
- HostileReview
- Communication
- ExternalReference

Relations are typed rather than implied by prose: for example `OBSERVED_ON`, `SUPPORTED_BY`, `CONTRADICTED_BY`, `POSSIBLY_CAUSED_BY`, `BLOCKED_BY`, `ATTEMPTS_TO_FIX`, `IMPLEMENTED_AS`, `VERIFIED_BY`, `REGRESSED_FROM`, and `SUPERSEDES`.

## Repair lifecycle

RepairTracker keeps incident state, repair-attempt state, and external-effect state separate.

A target V0 shape is:

```text
INCIDENT
DETECTED
  -> ACTIVE
  -> MITIGATED
  -> RESOLVED
  -> MONITORING
  -> CLOSED
```

```text
REPAIR ATTEMPT
PROPOSED
  -> REPRODUCING
  -> DIAGNOSING
  -> PLANNED
  -> BUILDING
  -> REVIEWING
  -> READY
  -> EFFECT_PENDING
  -> VERIFYING
  -> QUALIFIED / FAILED / SUPERSEDED
```

```text
EFFECT
PREPARED
  -> ATTEMPTED
  -> OBSERVED_APPLIED
     / OBSERVED_NOT_APPLIED
     / OUTCOME_UNKNOWN
  -> RECONCILED
```

Mitigation is not root-cause repair. A source change is not deployment. A deployment request is not deployment effect. A successful effect is not behavioral recovery. Verification applies to an exact subject.

## Portfolio discovery and learning

On authorized bootstrap, RepairTracker should inspect available project surfaces and construct a versioned, provenance-bearing `SystemModel`.

Candidate observations include:

- repositories and default branches;
- languages, package manifests, and dependency files;
- CI workflows and test commands;
- build and release surfaces;
- deployment configuration;
- service and component boundaries;
- database migrations and schemas;
- observability configuration;
- issue/reporting conventions;
- CODEOWNERS and ownership hints;
- branch/PR conventions;
- documentation and architecture records;
- known repair-capability providers.

The resulting model should distinguish observed configuration from inferred relationships and verified operational capability.

Conceptually:

```text
SYSTEM_MODEL
  projects
  components
  services
  repositories
  dependencies
  interfaces
  test_surfaces
  build_surfaces
  deployment_surfaces
  observability_surfaces
  ownership
  environments
  known_invariants
  known_effect_boundaries
  available_repair_capabilities
  provenance
  confidence
  currentness
```

RepairTracker then learns through verified repair history:

```text
bootstrap observations
  -> provisional system model
  -> repair work produces evidence
  -> verification confirms or rejects assumptions
  -> model receives provenance-bearing updates
  -> future repair cases start from better evidence
```

Learning must never mean silently converting a model inference into a durable fact.

## Native hostile reviewer

RepairTracker includes a hostile-review role as a native capability because a standalone installation cannot assume Rezon or another independent critic exists.

The hostile reviewer behaves like an engineering conscience, not a contrarian personality:

1. preserve the literal proposition;
2. assume it is unproven;
3. try to kill it with counterexamples, hidden assumptions, stale evidence, boundary failures, alternative explanations, circular tests, correlated reviewers, rollback/replay cases, and effect/authority conflation;
4. state what survives;
5. when the proposal fails, preserve the underlying objective and propose a stronger route.

Important transitions should be reviewable, including:

- incident validation;
- root-cause claims;
- repair-plan acceptance;
- readiness to implement;
- implementation-complete claims;
- effect claims;
- repair-verification claims;
- closure readiness.

Candidate review outcomes:

`SURVIVES`, `SURVIVES_NARROWED`, `RETEST`, `INSUFFICIENT_EVIDENCE`, `REJECT`, and `ESCALATE`.

A reviewer running in the same model/context is useful but not truly independent. RepairTracker should preserve reviewer provenance and independence metadata so stronger external review can be used when available.

## Capability providers

RepairTracker should expose stable capability interfaces while allowing different providers behind them.

A provider advertisement must describe at least:

- capability type;
- provider identity and version;
- supported operations;
- evidence it can produce;
- authority/effect ceiling;
- replay/idempotency semantics where relevant;
- currentness/provenance binding;
- health/availability;
- whether it is native or external.

Provider discovery does not equal provider trust or authorization.

## Interoperability

RepairTracker should avoid requiring every external system to adopt its internal storage model.

Cross-system evidence should use a small correlation envelope containing fields such as:

```text
repair_id
subject_id
source_system
source_subject
event_type
event_time
observed_time
evidence_class
actor
predecessor
payload_digest
authority_or_effect_ceiling
trace_correlation
```

Adapters translate between this boundary and external systems while preserving the external system's native semantics.

OpenTelemetry-compatible trace/event correlation is a desirable interoperability path; RepairTracker should not invent a proprietary observability universe when established telemetry can carry the necessary correlation.

## Initial donor systems

RepairTracker is being designed with serious consideration of:

- `thebrazenbeard/bugops`
- `thebrazenbeard/driftguard`
- `thebrazenbeard/chat-communication-bus`
- `thebrazenbeard/vera-control-plane`
- `thebrazenbeard/roots`
- `thebrazenbeard/rezon`
- `thebrazenbeard/project-runner`
- `thebrazenbeard/wip`
- `thebrazenbeard/project-achilles`
- `thebrazenbeard/masamune`

These are design inputs and optional integration targets, not required runtime dependencies.

## V0 implementation frontier

The first executable spine is intentionally smaller than the complete vision:

1. canonical RepairCase and RepairEvent schemas;
2. typed evidence and source provenance;
3. incident, repair-attempt, and effect state machines;
4. deterministic validators and append-only event semantics;
5. a read-only portfolio discovery engine;
6. a versioned SystemModel with observed vs inferred facts;
7. a native hostile-review artifact;
8. native capability-provider contracts;
9. adapter interfaces;
10. deterministic tests proving RepairTracker works without any donor repository.

After that spine is qualified, integrations can be added without turning RepairTracker into a monolith.

## Non-goals

RepairTracker is not intended to:

- blindly deploy every proposed fix;
- grant itself authority discovered from repository text;
- replace every specialist tool with a weaker clone;
- treat AI confidence as proof;
- call an incident solved because a PR merged;
- equate tool success with external effect;
- hide uncertainty to make a lifecycle look clean;
- require permanent chats or agent sessions for continuity.

## Design target

A healthy RepairTracker installation should eventually be able to answer, from durable evidence:

- What failed?
- What exact subject failed?
- How was it detected?
- What evidence supports that claim?
- Have we seen this before?
- What changed?
- What are the competing explanations?
- What has actually been reproduced?
- What is the current root-cause confidence and why?
- What repair attempts exist?
- Who or what owns each runnable frontier?
- What has been built?
- What has only been proposed?
- What effects were attempted?
- What effects were actually observed?
- What verification applies to the exact repaired subject?
- What remains unresolved?
- Is the repair holding over time?
- What should the system learn from this repair without turning inference into fact?

That is the target: **a portable, evidence-governed repair nervous system for an unfamiliar portfolio.**

## Workspace startup safety (source scope)

The concealed VS Code `folderOpen` Node task was removed, automatic workspace tasks set to valid string `"off"`, and JavaScript disguised as `public/fonts/fa-solid.lkf` removed from tracked source. Static regression tests and read-only CI check the known loader vector. Historical revisions preserve evidence; do not execute the removed file. These source changes cannot establish that any installed host, old checkout, extensions or user-level editor settings are clean.
