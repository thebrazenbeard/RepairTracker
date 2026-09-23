import unittest

from repairtracker.adapters.github import GitHubReadClient


class SignalTransport:
    def get_json(self, path, query=None):
        if path == "/repos/acme/app/issues":
            return [
                {
                    "number": 7,
                    "title": "Broken checkout",
                    "state": "open",
                    "html_url": "https://github.com/acme/app/issues/7",
                    "updated_at": "2026-09-23T10:00:00Z",
                },
                {
                    "number": 8,
                    "title": "PR masquerading in issues endpoint",
                    "state": "open",
                    "pull_request": {"url": "x"},
                },
            ]
        if path == "/repos/acme/app/pulls":
            return [
                {
                    "number": 9,
                    "title": "Repair checkout",
                    "state": "open",
                    "html_url": "https://github.com/acme/app/pull/9",
                    "head": {"sha": "a" * 40},
                    "updated_at": "2026-09-23T10:00:00Z",
                }
            ]
        if path == "/repos/acme/app/actions/runs":
            return {
                "workflow_runs": [
                    {
                        "id": 11,
                        "name": "ci",
                        "conclusion": "failure",
                        "head_sha": "b" * 40,
                        "html_url": "https://github.com/acme/app/actions/runs/11",
                        "event": "push",
                        "updated_at": "2026-09-23T10:00:00Z",
                    },
                    {
                        "id": 12,
                        "name": "lint",
                        "conclusion": "success",
                        "head_sha": "c" * 40,
                    },
                ]
            }
        raise AssertionError(f"unexpected GET: {path} {query}")


class GitHubSignalTests(unittest.TestCase):
    def test_candidate_signals_are_read_without_incident_promotion(self):
        result = GitHubReadClient(
            transport=SignalTransport()
        ).observe_repair_signals("acme/app")
        self.assertEqual(
            [signal.kind for signal in result.signals],
            ["ISSUE", "PULL_REQUEST", "WORKFLOW_RUN"],
        )
        self.assertEqual(result.signals[1].subject_ref, "a" * 40)
        self.assertEqual(result.signals[2].state, "failure")
        self.assertTrue(all(signal.payload_digest for signal in result.signals))

    def test_successful_workflow_is_not_failure_signal(self):
        result = GitHubReadClient(
            transport=SignalTransport()
        ).observe_repair_signals("acme/app")
        self.assertFalse(
            any(signal.external_id == "12" for signal in result.signals)
        )


if __name__ == "__main__":
    unittest.main()
