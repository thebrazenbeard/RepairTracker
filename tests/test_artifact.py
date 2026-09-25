import unittest

from repairtracker.artifact import (
    apply_runtime_artifact_topology,
    extract_runtime_artifact_claims,
)
from repairtracker.telemetry import OTelSpanObservation, extract_otlp_json_spans
from repairtracker.topology import PortfolioTopology, RelationDisposition, RelationType


def span(**overrides):
    values = dict(
        trace_id="a" * 32,
        span_id="1" * 16,
        parent_span_id=None,
        service_name="api",
        service_namespace="shop",
        span_name="request",
        observed_at="2026-09-23T13:00:00+00:00",
        source_locator="otel://fixture",
        service_version="1.2.3",
        service_instance_id="api-1",
        deployment_environment="production",
        container_id="container-1",
        container_image_id="sha256:" + ("c" * 64),
        container_image_name="ghcr.io/acme/api",
        container_image_repo_digests=(
            "ghcr.io/acme/api@sha256:" + ("d" * 64),
        ),
        oci_manifest_digest="sha256:" + ("d" * 64),
    )
    values.update(overrides)
    return OTelSpanObservation(**values)


class ArtifactTests(unittest.TestCase):
    def test_otlp_array_value_extracts_repository_digests(self):
        payload = {
            "resourceSpans": [
                {
                    "resource": {
                        "attributes": [
                            {"key": "service.name", "value": {"stringValue": "api"}},
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
                            {
                                "key": "oci.manifest.digest",
                                "value": {
                                    "stringValue": "sha256:" + ("d" * 64)
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
            observed_at="2026-09-23T13:00:00+00:00",
            source_locator="otel://fixture",
        )
        self.assertEqual(
            result.spans[0].container_image_repo_digests,
            ("ghcr.io/acme/api@sha256:" + ("d" * 64),),
        )
        self.assertEqual(
            result.spans[0].oci_manifest_digest,
            "sha256:" + ("d" * 64),
        )

    def test_repository_digest_is_preferred_portable_identity(self):
        claims, warnings = extract_runtime_artifact_claims((span(),))
        self.assertEqual(warnings, ())
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0].digest, "d" * 64)
        self.assertEqual(
            claims[0].source_attribute,
            "container.image.repo_digests",
        )

    def test_runtime_specific_image_id_alone_is_not_promoted(self):
        claims, warnings = extract_runtime_artifact_claims(
            (
                span(
                    container_image_repo_digests=(),
                    oci_manifest_digest=None,
                ),
            )
        )
        self.assertEqual(claims, ())
        self.assertTrue(any("runtime-specific identity" in w for w in warnings))

    def test_conflicting_repository_digests_fail_closed(self):
        claims, warnings = extract_runtime_artifact_claims(
            (
                span(
                    container_image_repo_digests=(
                        "ghcr.io/acme/api@sha256:" + ("d" * 64),
                        "mirror.example/acme/api@sha256:" + ("e" * 64),
                    ),
                ),
            )
        )
        self.assertEqual(claims, ())
        self.assertTrue(any("conflicting" in w for w in warnings))

    def test_runtime_artifact_edge_is_observed_not_verified(self):
        topology = PortfolioTopology("test")
        result = apply_runtime_artifact_topology(topology, (span(),))
        self.assertEqual(result.bound_claims, 1)
        edges = [
            edge
            for edge in topology.edges.values()
            if edge.relation is RelationType.RUNS_ARTIFACT
        ]
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0].disposition, RelationDisposition.OBSERVED)
        self.assertEqual(
            edges[0].attributes["claim_ceiling"],
            "RUNTIME_OBSERVED_PORTABLE_ARTIFACT_DIGEST",
        )


if __name__ == "__main__":
    unittest.main()
