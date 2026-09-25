import unittest

from repairtracker.case import RepairCase
from repairtracker.model import (
    EffectState,
    EvidenceClass,
    EventLog,
    IncidentState,
    RepairAttemptState,
    RepairEvent,
    Severity,
    TransitionError,
)


class ModelTests(unittest.TestCase):
    def test_lifecycle_separates_incident_attempt_and_effect(self):
        case = RepairCase("R-1", "broken thing", "repo@sha", Severity.SEV_2)
        case.transition_incident(IncidentState.ACTIVE)

        case.create_attempt("A-1")
        case.transition_attempt("A-1", RepairAttemptState.REPRODUCING)
        case.transition_attempt("A-1", RepairAttemptState.DIAGNOSING)
        case.transition_attempt("A-1", RepairAttemptState.PLANNED)
        case.transition_attempt("A-1", RepairAttemptState.BUILDING)

        case.create_effect("E-1")
        case.transition_effect("E-1", EffectState.ATTEMPTED)
        case.transition_effect("E-1", EffectState.OUTCOME_UNKNOWN)

        self.assertEqual(case.incident_state, IncidentState.ACTIVE)
        self.assertEqual(case.attempt_states["A-1"], RepairAttemptState.BUILDING)
        self.assertEqual(case.effect_states["E-1"], EffectState.OUTCOME_UNKNOWN)

    def test_unknown_effect_reconciliation_preserves_outcome(self):
        case = RepairCase("R-1", "broken thing", "repo@sha", Severity.SEV_2)
        case.create_effect("E-1")
        case.transition_effect("E-1", EffectState.ATTEMPTED)
        case.transition_effect("E-1", EffectState.OUTCOME_UNKNOWN)
        case.transition_effect("E-1", EffectState.RECONCILED_NOT_APPLIED)
        self.assertEqual(case.effect_states["E-1"], EffectState.RECONCILED_NOT_APPLIED)

    def test_invalid_transition_fails_closed(self):
        case = RepairCase("R-1", "broken thing", "repo@sha", Severity.SEV_2)
        with self.assertRaises(TransitionError):
            case.transition_incident(IncidentState.CLOSED)

    def test_event_log_is_digest_chained_and_repair_bound(self):
        first = RepairEvent(
            event_id="evt-1",
            repair_id="R-1",
            event_type="INCIDENT_DETECTED",
            subject_id="repo@sha",
            evidence_class=EvidenceClass.OBSERVED,
            actor="test",
        )
        log = EventLog()
        log.append(first)

        second = RepairEvent(
            event_id="evt-2",
            repair_id="R-1",
            event_type="DIAGNOSIS_STARTED",
            subject_id="repo@sha",
            evidence_class=EvidenceClass.OBSERVED,
            actor="test",
            predecessor_digest=first.digest,
        )
        log.append(second)
        self.assertEqual(log.head_digest, second.digest)
        self.assertEqual(log.repair_id, "R-1")

        cross_case = RepairEvent(
            event_id="evt-3",
            repair_id="R-2",
            event_type="CROSS_CASE",
            subject_id="repo@sha",
            evidence_class=EvidenceClass.INFERENCE,
            actor="test",
            predecessor_digest=second.digest,
        )
        with self.assertRaises(ValueError):
            log.append(cross_case)

        bad_chain = RepairEvent(
            event_id="evt-4",
            repair_id="R-1",
            event_type="BAD_CHAIN",
            subject_id="repo@sha",
            evidence_class=EvidenceClass.INFERENCE,
            actor="test",
            predecessor_digest="wrong",
        )
        with self.assertRaises(ValueError):
            log.append(bad_chain)


if __name__ == "__main__":
    unittest.main()
