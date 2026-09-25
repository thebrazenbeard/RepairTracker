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
        repository_stable_id=4242,
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

    def test_repository_rename_keeps_stable_signal_identity(self):
        before = promote_signal(
            signal(repository_id="acme/app"),
            policy(),
        )
        after = promote_signal(
            signal(repository_id="renamed-owner/renamed-app"),
            policy(),
        )
        assert before is not None and after is not None
        self.assertEqual(
            before.decision.signal_key,
            "github:repo-id:4242:WORKFLOW_RUN:11",
        )
        self.assertEqual(
            before.repair_case.repair_id,
            after.repair_case.repair_id,
        )

    def test_name_fallback_is_explicit_when_stable_id_is_missing(self):
        fallback = signal(repository_stable_id=None)
        decision = evaluate_signal(fallback, policy())
        self.assertEqual(
            decision.signal_key,
            "github:repo-name:acme/app:WORKFLOW_RUN:11",
        )

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

    def test_policy_digest_is_order_invariant_for_semantic_sets(self):
        first = SignalPromotionPolicy.from_dict(
            {
                "policy_id": "stable",
                "rules": [
                    {
                        "rule_id": "b",
                        "kinds": ["WORKFLOW_RUN", "ISSUE"],
                        "states": ["timed_out", "failure"],
                        "severity": "SEV-2",
                    },
                    {
                        "rule_id": "a",
                        "kinds": ["PULL_REQUEST"],
                        "states": ["open"],
                        "severity": "SEV-3",
                    },
                ],
            }
        )
        reordered = SignalPromotionPolicy.from_dict(
            {
                "policy_id": "stable",
                "rules": [
                    {
                        "rule_id": "a",
                        "kinds": ["PULL_REQUEST"],
                        "states": ["open"],
                        "severity": "SEV-3",
                    },
                    {
                        "rule_id": "b",
                        "kinds": ["ISSUE", "WORKFLOW_RUN"],
                        "states": ["failure", "timed_out"],
                        "severity": "SEV-2",
                    },
                ],
            }
        )
        self.assertEqual(first.digest, reordered.digest)

    def test_non_boolean_subject_requirement_is_rejected(self):
        with self.assertRaises(ValueError):
            SignalPromotionPolicy.from_dict(
                {
                    "policy_id": "bad",
                    "rules": [
                        {
                            "rule_id": "bad",
                            "kinds": ["WORKFLOW_RUN"],
                            "states": ["failure"],
                            "severity": "SEV-2",
                            "require_subject_ref": "false",
                        }
                    ],
                }
            )

    def test_policy_change_is_surfaced_without_rewriting_case(self):
        with tempfile.TemporaryDirectory() as temp:
            store = SQLiteEventStore(Path(temp) / "repairtracker.sqlite3")
            first_policy = policy()
            first = promote_signal(signal(), first_policy)
            assert first is not None
            persist_promotion(store, first)

            changed_policy = SignalPromotionPolicy.from_dict(
                {
                    "policy_id": "changed",
                    "rules": [
                        {
                            "rule_id": "failed-workflow",
                            "kinds": ["WORKFLOW_RUN"],
                            "states": ["failure", "timed_out", "startup_failure"],
                            "severity": "SEV-1",
                            "require_subject_ref": True,
                        }
                    ],
                }
            )
            changed = promote_signal(signal(), changed_policy)
            assert changed is not None
            result = persist_promotion(store, changed)
            self.assertFalse(result.created)
            self.assertFalse(result.evidence_changed)
            self.assertTrue(result.policy_changed)
            self.assertNotEqual(
                result.persisted_policy_digest,
                result.incoming_policy_digest,
            )
            self.assertEqual(len(store.load(first.repair_case.repair_id).events), 1)

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
