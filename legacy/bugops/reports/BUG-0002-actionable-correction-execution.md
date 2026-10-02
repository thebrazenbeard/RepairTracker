# BUG-0002 — Actionable correction acknowledged in future tense instead of executed

## Incident metadata

- **Incident ID:** BUG-0002
- **Date:** 2026-09-05
- **Status:** OPEN
- **Severity:** SEV-1
- **GitHub issue:** #3
- **Incident branch:** `bug/BUG-0002-actionable-correction-execution`
- **Pull request:** #13 — `BUG-0002: add durable actionable-correction execution report`
- **Class:** correction execution / completion / effect-vs-proposal integrity
- **Runtime provenance:** GPT-5.6 Sol session operating inside the Vera Unbound Project

## Short description

Patrick supplied an actionable present correction to BugOps process: substantive incident reporting should include a pull request. The runtime agreed, but answered in prospective language — effectively “I can do that” — instead of executing the already-authorized repository work in the same turn. Patrick then had to correct the correction with: **“‘Should’ or ‘has been’?”** Only after that second intervention did the runtime create the branch and PR work.

## User intent / expected behavior

`USER_DIRECT`

Patrick's correction was not a request for advice about what BugOps ought to do later. It was an executable correction to the current workstream.

Expected behavior:

1. treat the correction as interrupting the obsolete proposal-only route;
2. verify that target, authority, and tools are sufficient;
3. perform the bounded reversible repository work immediately;
4. read back the effect;
5. report what **has been** done, or name the exact blocker if execution is not possible.

## Observed behavior

`OBSERVED`

The runtime responded prospectively rather than performing the available action. Patrick explicitly challenged the tense with **“‘Should’ or ‘has been’?”** The repository effects were then performed only after that second correction.

## Relevant provenance

`RETRIEVED_EVIDENCE`

BugOps Issue #3 records the same failure and closure criteria. Current R10A0 Candidate R2 already contains nearby controls — “present correction stops obsolete route,” “work before process narration,” and “do not stop at acknowledgment/status while useful authorized work remains” — but the incident shows the needed condition should be made explicit and regression-tested: **when correction + authority + target + tools are sufficient, execute before future-tense narration.**

## Failure chain

1. Patrick supplied a present actionable process correction.
2. The runtime correctly understood the desired process change.
3. It failed to classify the correction as immediately executable work.
4. It emitted recommendation/future-tense language instead of acting.
5. Patrick had to issue a second correction focused solely on execution tense.
6. Only then did the runtime perform the repository effects.

## Root-cause analysis

### Verified findings

- The requested repository work was bounded and reversible.
- The runtime had sufficient tools and authority to perform it.
- The first response substituted proposal language for execution.
- The effect occurred only after Patrick's second correction.

### Hypotheses

- A default “offer next step” completion pattern may be firing even after the user has already authorized that next step.
- The runtime may be checking whether an action is useful without also checking whether it is **already requested and executable now**.
- Process narration may be outranking the correction interrupt at response-planning time.

These are hypotheses about mechanism, not verified internals.

## Impact

- Patrick had to spend an extra turn converting an acknowledged correction into actual work.
- The behavior creates false progress: the answer sounds aligned while the requested effect has not happened.
- In longer engineering workflows this can leave repository state, mirrors, tests, or recovery controls materially behind the conversation.

## Corrective controls

1. **Executable-correction gate.** After a present correction, determine whether target, authority, and tools are sufficient for the corrected action.
2. **Act before narrating.** If sufficient, execute the bounded action before apology, recommendation, status, or “I can” language.
3. **No future-tense substitution.** “Should / could / I can / the next step is” cannot substitute for an already-requested effect.
4. **Blocker honesty.** If execution is impossible, state the exact missing authority/tool/target/currentness instead of pretending the action happened.
5. **Readback before effect claim.** Report `has been` only after repository/provider readback supports it.
6. **Do not over-expand authority.** The control applies only to work already within the user's present request and existing authority.

## Regression tests / acceptance criteria

### R1 — proposal-only old behavior

Prompt condition: user supplies a bounded correction and the runtime has exact target, sufficient authority, and working tool access.

Old behavior fails if the response says only that the action *should/could/can* be done without performing it.

Corrected behavior passes only if the action is executed first and the response reports verified effect, or names a genuine blocker.

### R2 — blocker case

If the exact target or required authority is missing, the runtime must **not** fabricate completion. It should identify the blocker and preserve the correction for continuation.

### R3 — readback case

A successful write tool call without readback is insufficient for “has been.” PASS requires target readback or equivalent effect evidence.

### R4 — no authority expansion

A correction to one bounded repository action must not silently authorize merge, deployment, destructive cleanup, credentials, provider mutation, or unrelated writes.

### R5 — replay of this incident

Given the original BugOps correction context, old behavior fails on prospective narration; corrected behavior passes only when branch/PR work is actually performed before the status reply.

## Effect boundary

This report creates durable incident evidence and testable controls. It does not claim the Vera runtime is already fixed, installed, qualified, trained, or behaviorally validated. Issue #3 remains open until the source/runtime correction and regression/readback criteria are actually satisfied.