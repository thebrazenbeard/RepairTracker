from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ReviewOutcome(StrEnum):
    SURVIVES = "SURVIVES"
    SURVIVES_NARROWED = "SURVIVES_NARROWED"
    RETEST = "RETEST"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    REJECT = "REJECT"
    ESCALATE = "ESCALATE"


ATTACK_CLASSES: tuple[str, ...] = (
    "counterexample",
    "hidden_precondition",
    "scope_error",
    "alternative_explanation",
    "stale_evidence",
    "state_effect_conflation",
    "authority_laundering",
    "circular_validation",
    "correlated_reviewer_consensus",
    "test_oracle_trusts_subject",
    "missing_negative_case",
    "rollback_or_replay",
    "coherent_multi_artifact_forgery",
)


@dataclass(frozen=True, slots=True)
class HostileReviewRequest:
    proposition: str
    success_criteria: tuple[str, ...]
    evidence_refs: tuple[str, ...] = ()

    def prompts(self) -> tuple[str, ...]:
        return tuple(
            f"Attack the literal proposition using {attack.replace('_', ' ')}."
            for attack in ATTACK_CLASSES
        )


@dataclass(frozen=True, slots=True)
class HostileReviewResult:
    proposition: str
    outcome: ReviewOutcome
    reviewer_id: str
    reviewer_independence: str
    attacks: tuple[str, ...]
    unsupported_assumptions: tuple[str, ...] = ()
    surviving_claim: str | None = None
    stronger_route: str | None = None
    unresolved: tuple[str, ...] = ()

    def validate(self) -> None:
        if not self.proposition.strip():
            raise ValueError("review proposition must be preserved")
        if self.outcome in {
            ReviewOutcome.REJECT,
            ReviewOutcome.RETEST,
            ReviewOutcome.INSUFFICIENT_EVIDENCE,
            ReviewOutcome.ESCALATE,
        } and not self.attacks:
            raise ValueError("negative/uncertain review outcome requires concrete attacks")
        if self.outcome is ReviewOutcome.SURVIVES_NARROWED and not self.surviving_claim:
            raise ValueError("SURVIVES_NARROWED requires surviving_claim")
        if self.outcome is ReviewOutcome.REJECT and not self.stronger_route:
            raise ValueError("REJECT requires a stronger_route that preserves the objective")
