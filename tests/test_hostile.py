import unittest

from repairtracker.hostile import HostileReviewRequest, HostileReviewResult, ReviewOutcome


class HostileReviewTests(unittest.TestCase):
    def test_template_attacks_literal_proposition(self):
        request = HostileReviewRequest(
            proposition="the repair is safe to deploy",
            success_criteria=("no regression",),
        )
        prompts = request.prompts()
        self.assertGreater(len(prompts), 5)
        self.assertTrue(all("Attack the literal proposition" in prompt for prompt in prompts))

    def test_reject_requires_stronger_route(self):
        result = HostileReviewResult(
            proposition="the repair is complete",
            outcome=ReviewOutcome.REJECT,
            reviewer_id="same-context-reviewer",
            reviewer_independence="CORRELATED_CONTEXT",
            attacks=("verification does not bind the deployed subject",),
        )
        with self.assertRaises(ValueError):
            result.validate()

        repaired = HostileReviewResult(
            proposition="the repair is complete",
            outcome=ReviewOutcome.REJECT,
            reviewer_id="same-context-reviewer",
            reviewer_independence="CORRELATED_CONTEXT",
            attacks=("verification does not bind the deployed subject",),
            stronger_route="read back deployed subject and rerun exact-subject verification",
        )
        repaired.validate()


if __name__ == "__main__":
    unittest.main()
