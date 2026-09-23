import tempfile
import unittest
from pathlib import Path

from repairtracker.adapters.github import GitHubRepairSignal
from repairtracker.model import Severity
from repairtracker.promotion import (
    PolicyAmbiguityError,
    PromotionDisposition,
    SignalPromotionPolicy,
    evaluate_signal,
    persist_promotion,
    promote_signal,
)
from repairtracker.storage import SQLiteEventStore


def signal(**overrides):
    values = dict(
        kind="WORKFLOW_RUN",
        repository_id="acme/app",
        external_id="11",
        title="ci",
        state="failure",
        locator="https://github.com/acme/app/actions/runs/11",
        observed_at="2026-09-23T13:30:00+00:00",
        subject_ref="a" * 40,
        payload_digest="b" * 64,
    )
    values.update(overrides)
    return GitHubRepairSignal(**values)


def policy(**overrides):
    value = {
        "policy_id": "fixture",
        "rules": [
            {
                "rule_id": "failed-workflow",
                "kinds": ["WORKFLOW_RUN"],
                "states": ["failure", "timed_out", "startup_failure"],
                "severity": "SEV-2",
                "require_subject_ref": True,
            }
        ],
    }
    value.update(overrides)
    return SignalPromotionPolicy.from_dict(value)


class PromotionTests(unittest.TestCase):
    def test_unmatched_signal_is_deferred_not_promoted(self):
        decision = evaluate_signal(
            signal(kind="ISSUE", state="open", subject_ref=None),
            policy(),
        )
        self.assertEqual(decision.disposition, PromotionDisposition.DEFER)
        self.assertIsNone(
            promote_signal(
                signal(kind="ISSUE", state="open", subject_ref=None),
                policy(),
            )
        )

    def test_explicit_rule_binds_severity_subject_and_evidence(self):
        promotion = promote_signal(signal(), policy())
        self.assertIsNotNone(promotion)
        assert promotion is not None
        self.assertEqual(promotion.repair_case.severity, Severity.SEV_2)
        self.assertEqual(
            promotion.repair_case.subject_id,
            "repo:acme/app@" + ("a" * 40),
        )
        self.assertEqual(
            promotion.opening_event.authority_or_effect_ceiling,
            "OBSERVE_ONLY",
        )
        self.assertEqual(
            promotion.opening_event.payload["signal"]["payload_digest"],
            "b" * 64,
        )
        self.assertEqual(
            promotion.opening_event.payload["promotion"]["policy_digest"],
            policy().digest,
        )

    def test_same_signal_identity_is_deterministic_across_payload_updates(self):
        first = promote_signal(signal(payload_digest="b" * 64), policy())
        second = promote_signal(
            signal(
                payload_digest="c" * 64,
                title="ci rerun changed evidence",
                observed_at="2026-09-23T13:31:00+00:00",
            ),
            policy(),
        )
        assert first is not None and second is not None
        self.assertEqual(
            first.repair_case.repair_id,
            second.repair_case.repair_id,
        )
        self.assertEqual(
            first.opening_event.event_id,
            second.opening_event.event_id,
        )
        self.assertNotEqual(first.opening_event.digest, second.opening_event.digest)

    def test_ambiguous_policy_fails_closed(self):
        ambiguous = SignalPromotionPolicy.from_dict(
            {
                "policy_id": "ambiguous",
                "rules": [
                    {
                        "rule_id": "one",
                        "kinds": ["WORKFLOW_RUN"],
                        "states": ["failure"],
                        "severity": "SEV-2",
                    },
                    {
                        "rule_id": "two",
                        "kinds": ["WORKFLOW_RUN"],
                        "states": ["failure"],
                        "severity": "SEV-1",
                    },
                ],
            }
        )
        with self.assertRaises(PolicyAmbiguityError):
            evaluate_signal(signal(), ambiguous)

    def test_persistence_is_idempotent_and_surfaces_changed_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            store = SQLiteEventStore(Path(temp) / "repairtracker.sqlite3")
            first = promote_signal(signal(payload_digest="b" * 64), policy())
            assert first is not None
            created = persist_promotion(store, first)
            self.assertTrue(created.created)
            self.assertFalse(created.evidence_changed)

            replay = persist_promotion(store, first)
            self.assertFalse(replay.created)
            self.assertFalse(replay.evidence_changed)

            changed = promote_signal(
                signal(
                    payload_digest="c" * 64,
                    observed_at="2026-09-23T13:32:00+00:00",
                ),
                policy(),
            )
            assert changed is not None
            existing = persist_promotion(store, changed)
            self.assertFalse(existing.created)
            self.assertTrue(existing.evidence_changed)
            self.assertEqual(
                existing.persisted_signal_payload_digest,
                "b" * 64,
            )
            self.assertEqual(
                existing.incoming_signal_payload_digest,
                "c" * 64,
            )

            log = store.load(first.repair_case.repair_id)
            self.assertEqual(len(log.events), 1)

    def test_policy_has_no_implicit_rules(self):
        empty = SignalPromotionPolicy.from_dict(
            {"policy_id": "none", "rules": []}
        )
        self.assertEqual(
            evaluate_signal(signal(), empty).disposition,
            PromotionDisposition.DEFER,
        )


if __name__ == "__main__":
    unittest.main()
