from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import sqlite3
from typing import Any

from .adapters.github import GitHubRepairSignal
from .case import RepairCase
from .model import EvidenceClass, RepairEvent, Severity, canonical_digest
from .storage import SQLiteEventStore, StaleHeadError


class PromotionDisposition(StrEnum):
    PROMOTE = "PROMOTE"
    DEFER = "DEFER"


class PolicyAmbiguityError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PromotionRule:
    rule_id: str
    kinds: tuple[str, ...]
    states: tuple[str, ...]
    severity: Severity
    require_subject_ref: bool = False

    def __post_init__(self) -> None:
        if not self.rule_id.strip():
            raise ValueError("promotion rule_id is required")
        if not self.kinds:
            raise ValueError("promotion rule must name at least one signal kind")
        if any(not kind.strip() for kind in self.kinds):
            raise ValueError("promotion rule kinds cannot be empty")
        if any(not state.strip() for state in self.states):
            raise ValueError("promotion rule states cannot be empty")

    def matches(self, signal: GitHubRepairSignal) -> bool:
        if signal.kind not in self.kinds:
            return False
        if self.states and signal.state not in self.states:
            return False
        if self.require_subject_ref and not signal.subject_ref:
            return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "kinds": sorted(set(self.kinds)),
            "states": sorted(set(self.states)),
            "severity": self.severity.value,
            "require_subject_ref": self.require_subject_ref,
        }


@dataclass(frozen=True, slots=True)
class SignalPromotionPolicy:
    policy_id: str
    rules: tuple[PromotionRule, ...]

    def __post_init__(self) -> None:
        if not self.policy_id.strip():
            raise ValueError("promotion policy_id is required")
        rule_ids = [rule.rule_id for rule in self.rules]
        if len(rule_ids) != len(set(rule_ids)):
            raise ValueError("promotion policy rule_id values must be unique")

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "SignalPromotionPolicy":
        policy_id = value.get("policy_id")
        rules = value.get("rules", [])
        if not isinstance(policy_id, str):
            raise ValueError("promotion policy_id must be a string")
        if not isinstance(rules, list):
            raise ValueError("promotion rules must be a list")

        parsed: list[PromotionRule] = []
        for item in rules:
            if not isinstance(item, dict):
                raise ValueError("promotion rule must be an object")
            kinds = item.get("kinds", [])
            states = item.get("states", [])
            if not isinstance(kinds, list) or not all(
                isinstance(kind, str) for kind in kinds
            ):
                raise ValueError("promotion rule kinds must be a string list")
            if not isinstance(states, list) or not all(
                isinstance(state, str) for state in states
            ):
                raise ValueError("promotion rule states must be a string list")
            require_subject_ref = item.get("require_subject_ref", False)
            if not isinstance(require_subject_ref, bool):
                raise ValueError(
                    "promotion rule require_subject_ref must be a boolean"
                )
            severity = item.get("severity")
            if not isinstance(severity, str):
                raise ValueError("promotion rule severity must be a string")
            parsed.append(
                PromotionRule(
                    rule_id=str(item.get("rule_id", "")),
                    kinds=tuple(kinds),
                    states=tuple(states),
                    severity=Severity(severity),
                    require_subject_ref=require_subject_ref,
                )
            )
        return cls(policy_id=policy_id, rules=tuple(parsed))

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "rules": [
                rule.to_dict()
                for rule in sorted(self.rules, key=lambda item: item.rule_id)
            ],
        }

    @property
    def digest(self) -> str:
        return canonical_digest(self.to_dict())


@dataclass(frozen=True, slots=True)
class PromotionDecision:
    disposition: PromotionDisposition
    signal_key: str
    policy_id: str
    policy_digest: str
    rule_id: str | None
    severity: Severity | None
    reason: str


@dataclass(frozen=True, slots=True)
class SignalPromotion:
    decision: PromotionDecision
    repair_case: RepairCase
    opening_event: RepairEvent


@dataclass(frozen=True, slots=True)
class PromotionPersistence:
    repair_id: str
    event_id: str
    created: bool
    generation: int
    event_digest: str
    incoming_signal_payload_digest: str
    persisted_signal_payload_digest: str
    evidence_changed: bool
    incoming_policy_digest: str
    persisted_policy_digest: str
    policy_changed: bool


def github_signal_key(signal: GitHubRepairSignal) -> str:
    return (
        f"github:{signal.repository_id.lower()}:"
        f"{signal.kind}:{signal.external_id}"
    )


def _repair_id(signal_key: str) -> str:
    return f"RT-GH-{canonical_digest({'signal_key': signal_key})[:20]}"


def _opening_event_id(signal_key: str) -> str:
    return f"promotion-{canonical_digest({'signal_key': signal_key})[:24]}"


def _subject_id(signal: GitHubRepairSignal) -> str:
    repository = signal.repository_id
    if signal.subject_ref:
        return f"repo:{repository}@{signal.subject_ref}"
    return f"repo:{repository}"


def evaluate_signal(
    signal: GitHubRepairSignal,
    policy: SignalPromotionPolicy,
) -> PromotionDecision:
    signal_key = github_signal_key(signal)
    matches = [rule for rule in policy.rules if rule.matches(signal)]
    if not matches:
        return PromotionDecision(
            disposition=PromotionDisposition.DEFER,
            signal_key=signal_key,
            policy_id=policy.policy_id,
            policy_digest=policy.digest,
            rule_id=None,
            severity=None,
            reason="no promotion rule matched the observed signal",
        )
    if len(matches) > 1:
        raise PolicyAmbiguityError(
            f"multiple promotion rules matched {signal_key}: "
            + ", ".join(rule.rule_id for rule in matches)
        )
    rule = matches[0]
    return PromotionDecision(
        disposition=PromotionDisposition.PROMOTE,
        signal_key=signal_key,
        policy_id=policy.policy_id,
        policy_digest=policy.digest,
        rule_id=rule.rule_id,
        severity=rule.severity,
        reason=f"matched explicit promotion rule {rule.rule_id}",
    )


def promote_signal(
    signal: GitHubRepairSignal,
    policy: SignalPromotionPolicy,
    *,
    actor: str = "repairtracker/promotion-engine",
) -> SignalPromotion | None:
    decision = evaluate_signal(signal, policy)
    if decision.disposition is PromotionDisposition.DEFER:
        return None
    if decision.severity is None or decision.rule_id is None:
        raise AssertionError("PROMOTE decision requires severity and rule_id")

    repair_id = _repair_id(decision.signal_key)
    subject_id = _subject_id(signal)
    case = RepairCase(
        repair_id=repair_id,
        title=signal.title,
        subject_id=subject_id,
        severity=decision.severity,
    )
    event = RepairEvent(
        event_id=_opening_event_id(decision.signal_key),
        repair_id=repair_id,
        event_type="REPAIR_CASE_PROMOTED_FROM_GITHUB_SIGNAL",
        subject_id=subject_id,
        evidence_class=EvidenceClass.RETRIEVED_EVIDENCE,
        actor=actor,
        source_system="github",
        source_subject=decision.signal_key,
        event_time=signal.observed_at,
        observed_time=signal.observed_at,
        authority_or_effect_ceiling="OBSERVE_ONLY",
        payload={
            "promotion": {
                "policy_id": decision.policy_id,
                "policy_digest": decision.policy_digest,
                "rule_id": decision.rule_id,
                "severity": decision.severity.value,
                "disposition": decision.disposition.value,
            },
            "signal": {
                "signal_key": decision.signal_key,
                "kind": signal.kind,
                "repository_id": signal.repository_id,
                "external_id": signal.external_id,
                "title": signal.title,
                "state": signal.state,
                "locator": signal.locator,
                "observed_at": signal.observed_at,
                "subject_ref": signal.subject_ref,
                "payload_digest": signal.payload_digest,
            },
        },
    )
    return SignalPromotion(
        decision=decision,
        repair_case=case,
        opening_event=event,
    )


def _persisted_signal_digest(event: RepairEvent) -> str:
    signal = event.payload.get("signal")
    if not isinstance(signal, dict):
        raise ValueError("persisted promotion event is missing signal payload")
    value = signal.get("payload_digest")
    if not isinstance(value, str) or not value:
        raise ValueError("persisted promotion event has no signal payload digest")
    return value


def _persisted_policy_digest(event: RepairEvent) -> str:
    promotion = event.payload.get("promotion")
    if not isinstance(promotion, dict):
        raise ValueError("persisted promotion event is missing policy payload")
    value = promotion.get("policy_digest")
    if not isinstance(value, str) or not value:
        raise ValueError("persisted promotion event has no policy digest")
    return value


def persist_promotion(
    store: SQLiteEventStore,
    promotion: SignalPromotion,
) -> PromotionPersistence:
    """Persist exactly one opening event per stable GitHub signal identity.

    A later observation of the same signal never opens a second RepairCase.
    If its payload changed, this function reports evidence_changed=True and
    leaves the existing case untouched so a separate evidence-update event can
    be handled explicitly by a later workflow.
    """

    event = promotion.opening_event
    incoming_digest = _persisted_signal_digest(event)
    incoming_policy_digest = _persisted_policy_digest(event)

    head_digest, generation = store.head(event.repair_id)
    if head_digest is None:
        try:
            receipt = store.append(event)
            return PromotionPersistence(
                repair_id=event.repair_id,
                event_id=event.event_id,
                created=True,
                generation=receipt.generation,
                event_digest=receipt.event_digest,
                incoming_signal_payload_digest=incoming_digest,
                persisted_signal_payload_digest=incoming_digest,
                evidence_changed=False,
                incoming_policy_digest=incoming_policy_digest,
                persisted_policy_digest=incoming_policy_digest,
                policy_changed=False,
            )
        except (StaleHeadError, sqlite3.IntegrityError):
            # Another writer may have won the same deterministic promotion.
            pass

    log = store.load(event.repair_id)
    matches = [
        existing
        for existing in log.events
        if existing.event_id == event.event_id
    ]
    if len(matches) != 1:
        raise ValueError(
            "repair_id already exists without the deterministic promotion "
            f"event: {event.repair_id}"
        )

    existing = matches[0]
    if existing.source_subject != event.source_subject:
        raise ValueError("promotion event source identity collision")
    persisted_digest = _persisted_signal_digest(existing)
    persisted_policy_digest = _persisted_policy_digest(existing)
    return PromotionPersistence(
        repair_id=event.repair_id,
        event_id=event.event_id,
        created=False,
        generation=log.events.index(existing) + 1,
        event_digest=existing.digest,
        incoming_signal_payload_digest=incoming_digest,
        persisted_signal_payload_digest=persisted_digest,
        evidence_changed=(persisted_digest != incoming_digest),
        incoming_policy_digest=incoming_policy_digest,
        persisted_policy_digest=persisted_policy_digest,
        policy_changed=(
            persisted_policy_digest != incoming_policy_digest
        ),
    )
