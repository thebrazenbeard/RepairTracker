import unittest

from repairtracker.model import EvidenceClass, RepairEvent
from repairtracker.telemetry import (
    TraceContext,
    apply_otel_service_topology,
    extract_otlp_json_spans,
    repair_event_to_otel_event,
)
from repairtracker.topology import (
    PortfolioTopology,
    RelationDisposition,
    RelationType,
)


class TelemetryTests(unittest.TestCase):
    def test_traceparent_round_trip(self):
        value = (
            "00-4bf92f3577b34da6a3ce929d0e0e4736-"
            "00f067aa0ba902b7-01"
        )
        context = TraceContext.from_traceparent(value)
        self.assertEqual(context.traceparent, value)

    def test_repair_event_uses_low_cardinality_otel_event_name(self):
        event = RepairEvent(
            event_id="evt-1",
            repair_id="repair-123",
            event_type="REPAIR_VERIFIED",
            subject_id="repo@sha",
            evidence_class=EvidenceClass.OBSERVED,
            actor="test",
        )
        record = repair_event_to_otel_event(event)
        self.assertEqual(record["event_name"], "repairtracker.repair.event")
        self.assertEqual(
            record["attributes"]["repairtracker.event.type"],
            "REPAIR_VERIFIED",
        )
        self.assertEqual(
            record["attributes"]["repairtracker.repair.id"],
            "repair-123",
        )
        self.assertNotIn("repair-123", record["event_name"])

    def test_otlp_json_parent_child_cross_service_is_observed_call(self):
        payload = {
            "resourceSpans": [
                {
                    "resource": {
                        "attributes": [
                            {
                                "key": "service.name",
                                "value": {"stringValue": "frontend"},
                            }
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
                },
                {
                    "resource": {
                        "attributes": [
                            {
                                "key": "service.name",
                                "value": {"stringValue": "backend"},
                            }
                        ]
                    },
                    "scopeSpans": [
                        {
                            "spans": [
                                {
                                    "traceId": "a" * 32,
                                    "spanId": "2" * 16,
                                    "parentSpanId": "1" * 16,
                                    "name": "handle",
                                }
                            ]
                        }
                    ],
                },
            ]
        }
        result = extract_otlp_json_spans(
            payload,
            observed_at="2026-09-23T11:00:00+00:00",
            source_locator="otel://fixture",
        )
        self.assertEqual(result.warnings, ())
        topology = PortfolioTopology("test")
        added = apply_otel_service_topology(topology, result.spans)
        self.assertEqual(added, 1)
        calls = [
            edge
            for edge in topology.edges.values()
            if edge.relation is RelationType.CALLS
        ]
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].disposition, RelationDisposition.OBSERVED)
        self.assertIsNone(calls[0].verification_ref)
        self.assertFalse(
            any(
                edge.relation is RelationType.DEPENDS_ON
                for edge in topology.edges.values()
            )
        )

    def test_empty_service_namespace_normalizes_to_unspecified(self):
        result = extract_otlp_json_spans(
            {
                "resourceSpans": [
                    {
                        "resource": {
                            "attributes": [
                                {
                                    "key": "service.name",
                                    "value": {"stringValue": " frontend "},
                                },
                                {
                                    "key": "service.namespace",
                                    "value": {"stringValue": ""},
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
            },
            observed_at="2026-09-23T11:00:00+00:00",
            source_locator="otel://fixture",
        )
        self.assertEqual(result.spans[0].service_name, "frontend")
        self.assertIsNone(result.spans[0].service_namespace)

    def test_duplicate_span_identity_fails_closed(self):
        payload = {
            "resourceSpans": [
                {
                    "resource": {
                        "attributes": [
                            {
                                "key": "service.name",
                                "value": {"stringValue": "frontend"},
                            }
                        ]
                    },
                    "scopeSpans": [
                        {
                            "spans": [
                                {
                                    "traceId": "a" * 32,
                                    "spanId": "1" * 16,
                                    "name": "one",
                                },
                                {
                                    "traceId": "a" * 32,
                                    "spanId": "1" * 16,
                                    "name": "duplicate",
                                },
                            ]
                        }
                    ],
                }
            ]
        }
        result = extract_otlp_json_spans(
            payload,
            observed_at="2026-09-23T11:00:00+00:00",
            source_locator="otel://fixture",
        )
        with self.assertRaises(ValueError):
            apply_otel_service_topology(PortfolioTopology("test"), result.spans)

    def test_otlp_extracts_runtime_source_resource_attributes(self):
        payload = {
            "resourceSpans": [
                {
                    "resource": {
                        "attributes": [
                            {"key": "service.name", "value": {"stringValue": "api"}},
                            {"key": "service.version", "value": {"stringValue": "1.2.3"}},
                            {"key": "service.instance.id", "value": {"stringValue": "api-1"}},
                            {"key": "deployment.environment.name", "value": {"stringValue": "production"}},
                            {"key": "vcs.repository.url.full", "value": {"stringValue": "https://github.com/acme/app"}},
                            {"key": "vcs.ref.head.revision", "value": {"stringValue": "abcdef1"}},
                        ]
                    },
                    "scopeSpans": [
                        {"spans": [{"traceId": "a" * 32, "spanId": "1" * 16, "name": "request"}]}
                    ],
                }
            ]
        }
        result = extract_otlp_json_spans(
            payload,
            observed_at="2026-09-23T12:00:00+00:00",
            source_locator="otel://fixture",
        )
        span = result.spans[0]
        self.assertEqual(span.service_version, "1.2.3")
        self.assertEqual(span.service_instance_id, "api-1")
        self.assertEqual(span.deployment_environment, "production")
        self.assertEqual(span.vcs_repository_url, "https://github.com/acme/app")
        self.assertEqual(span.vcs_revision, "abcdef1")

    def test_otlp_missing_service_name_is_warning_not_inference(self):
        result = extract_otlp_json_spans(
            {
                "resourceSpans": [
                    {
                        "resource": {"attributes": []},
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
            },
            observed_at="2026-09-23T11:00:00+00:00",
            source_locator="otel://fixture",
        )
        self.assertEqual(result.spans, ())
        self.assertTrue(result.warnings)

    def test_zero_trace_ids_are_rejected(self):
        with self.assertRaises(ValueError):
            TraceContext("0" * 32, "1" * 16)


if __name__ == "__main__":
    unittest.main()
