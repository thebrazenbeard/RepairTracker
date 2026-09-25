from __future__ import annotations

from dataclasses import dataclass, field

from .model import (
    EffectState,
    EFFECT_TRANSITIONS,
    IncidentState,
    INCIDENT_TRANSITIONS,
    RepairAttemptState,
    ATTEMPT_TRANSITIONS,
    Severity,
    require_transition,
)


@dataclass(slots=True)
class RepairCase:
    repair_id: str
    title: str
    subject_id: str
    severity: Severity
    incident_state: IncidentState = IncidentState.DETECTED
    attempt_states: dict[str, RepairAttemptState] = field(default_factory=dict)
    effect_states: dict[str, EffectState] = field(default_factory=dict)

    def transition_incident(self, successor: IncidentState) -> None:
        require_transition(self.incident_state, successor, INCIDENT_TRANSITIONS)
        self.incident_state = successor

    def create_attempt(self, attempt_id: str) -> None:
        if attempt_id in self.attempt_states:
            raise ValueError(f"attempt already exists: {attempt_id}")
        self.attempt_states[attempt_id] = RepairAttemptState.PROPOSED

    def transition_attempt(self, attempt_id: str, successor: RepairAttemptState) -> None:
        current = self.attempt_states[attempt_id]
        require_transition(current, successor, ATTEMPT_TRANSITIONS)
        self.attempt_states[attempt_id] = successor

    def create_effect(self, effect_id: str) -> None:
        if effect_id in self.effect_states:
            raise ValueError(f"effect already exists: {effect_id}")
        self.effect_states[effect_id] = EffectState.PREPARED

    def transition_effect(self, effect_id: str, successor: EffectState) -> None:
        current = self.effect_states[effect_id]
        require_transition(current, successor, EFFECT_TRANSITIONS)
        self.effect_states[effect_id] = successor
