# GitHub Signal Promotion V0

## Objective

GitHub signals are evidence that something deserves attention. They are not incidents merely because they exist.

This frontier introduces an explicit, policy-governed bridge:

```text
GITHUB_SIGNAL
  -> POLICY_DECISION
  -> REPAIR_CASE
```

There is no built-in auto-promotion rule.

An empty policy promotes nothing.

## Policy

A promotion policy has a stable `policy_id` and explicit rules.

Example:

```json
{
  "policy_id": "example-workflow-failures",
  "rules": [
    {
      "rule_id": "failed-workflow-exact-head",
      "kinds": ["WORKFLOW_RUN"],
      "states": ["failure", "timed_out", "startup_failure"],
      "severity": "SEV-2",
      "require_subject_ref": true
    }
  ]
}
```

Rules match only fields that are already evidence in the GitHub signal envelope.

Policy digests are canonical over rule IDs and set-like kind/state members. Reordering equivalent rules, kinds, or states therefore does not manufacture a new policy identity. Configuration booleans are type-checked rather than coerced from strings.

Severity is policy-bound. RepairTracker does not infer severity from a title, repository, actor, or generic signal type.

If no rule matches:

`DEFER`

If exactly one rule matches:

`PROMOTE`

If more than one rule matches:

fail closed with a policy ambiguity error.

Rule ordering therefore never creates hidden priority semantics.

## Stable identity

GitHub signal identity is:

```text
github:{repository}:{kind}:{external_id}
```

Repository identity is normalized case-insensitively for the stable key.

A RepairCase ID and opening event ID are deterministically derived from that stable source identity.

This means later observations of the same GitHub object cannot silently create additional RepairCases merely because title, state metadata, observation time, or payload digest changed.

## Subject binding

When GitHub supplies an exact subject revision:

```text
repo:owner/name@exact-revision
```

Otherwise the case remains repository-scoped:

```text
repo:owner/name
```

RepairTracker does not invent a more precise affected subject than the signal provides.

A policy may require an exact subject reference before promotion.

## Opening evidence

Promotion creates one opening RepairEvent:

`REPAIR_CASE_PROMOTED_FROM_GITHUB_SIGNAL`

It carries:

- policy ID and deterministic policy digest;
- exact rule ID;
- policy-bound severity;
- stable signal identity;
- source locator;
- GitHub kind/state/external ID;
- signal observation time;
- exact subject reference when available;
- signal payload digest.

Evidence class:

`RETRIEVED_EVIDENCE`

Authority/effect ceiling:

`OBSERVE_ONLY`

Promotion creates repair state. It grants no authority to modify GitHub, deploy, merge, retry effects, or mutate the affected system.

## Persistence and idempotence

The SQLite ledger is the durable opening-event authority.

The promotion path checks the deterministic RepairCase identity before append.

Concurrent duplicate promotion attempts are reconciled through the existing stale-head/transaction semantics.

If the same source signal was already promoted:

- no second RepairCase is opened;
- no second opening event is appended.

If a later observation has a different payload digest:

- the existing case remains authoritative;
- the promotion path reports `evidence_changed=true`;
- it does not rewrite the original opening evidence;
- it does not silently append a generic update.

If the same signal is evaluated under a different policy digest, the existing case also remains untouched and the promotion path reports `policy_changed=true`. Governance drift is therefore visible independently from evidence drift.

A separate evidence-update lifecycle can consume that condition later.

## CLI surfaces

Plan only:

```text
repairtracker github-promotion-plan OWNER/REPO --policy policy.json
```

This reads GitHub and evaluates policy but performs no local ledger mutation.

Persist explicit promotions to a local SQLite ledger:

```text
repairtracker github-promote OWNER/REPO \
  --policy policy.json \
  --sqlite repairtracker.sqlite3
```

Only matched signals are persisted.

Unmatched signals remain visible as DEFER decisions.

## Security / epistemic boundary

```text
GITHUB_SIGNAL != REPAIR_CASE
SIGNAL_PRESENCE != FAILURE_PROOF
POLICY_MATCH != ROOT_CAUSE
POLICY_SEVERITY != MEASURED_IMPACT
PROMOTION != EFFECT_AUTHORITY
PROMOTION != REPAIR_PLAN
PROMOTION != DEPLOYMENT_PERMISSION
SIGNAL_UPDATE != SECOND_REPAIR_CASE
```

## Claim ceiling

V0 establishes a deterministic, evidence-bound, opt-in promotion mechanism for GitHub signals.

It does not establish:

- that the matched signal represents a real defect;
- that policy severity equals actual impact;
- automatic diagnosis;
- automatic repair execution;
- closure criteria;
- GitHub write authority;
- production effect authority.
