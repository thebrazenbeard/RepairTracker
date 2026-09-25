import unittest

from repairtracker.artifact import apply_runtime_artifact_topology
from repairtracker.telemetry import extract_otlp_json_spans
from repairtracker.topology import PortfolioTopology, RelationType


class DeploymentIdentityTelemetryTests(unittest.TestCase):
    def test_deployment_id_and_name_remain_runtime_observation_context(self):
        payload = {
            "resourceSpans": [
                {
                    "resource": {
                        "attributes": [
                            {"key": "service.name", "value": {"stringValue": "api"}},
                            {"key": "deployment.id", "value": {"stringValue": "otel-deploy-42"}},
                            {"key": "deployment.name", "value": {"stringValue": "api-prod"}},
                            {
                                "key": "container.image.repo_digests",
                                "value": {
                                    "arrayValue": {
                                        "values": [
                                            {
                                                "stringValue": (
                                                    "ghcr.io/acme/api@sha256:"
                                                    + ("d" * 64)
                                                )
                                            }
                                        ]
                                    }
                                },
                            },
                        ]
                    },
                    "scopeSpans": [
                        {
                            "spans": [
                                {
                                    "traceId": "a" * 32,
                                    "spanId": "1" * 16,
                                    "name": "request",
                                }
                            ]
                        }
                    ],
                }
            ]
        }
        result = extract_otlp_json_spans(
            payload,
            observed_at="2026-09-23T13:30:00+00:00",
            source_locator="otel://fixture",
        )
        self.assertEqual(result.spans[0].deployment_id, "otel-deploy-42")
        self.assertEqual(result.spans[0].deployment_name, "api-prod")

        topology = PortfolioTopology("test")
        apply_runtime_artifact_topology(topology, result.spans)
        edge = next(
            edge for edge in topology.edges.values()
            if edge.relation is RelationType.RUNS_ARTIFACT
        )
        self.assertEqual(edge.attributes["deployment.id"], "otel-deploy-42")
        self.assertEqual(edge.attributes["deployment.name"], "api-prod")


if __name__ == "__main__":
    unittest.main()
