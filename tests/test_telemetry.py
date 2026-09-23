import unittest

from repairtracker.model import EvidenceClass, RepairEvent
from repairtracker.telemetry import TraceContext, repair_event_to_otel_event


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

    def test_zero_trace_ids_are_rejected(self):
        with self.assertRaises(ValueError):
            TraceContext("0" * 32, "1" * 16)


if __name__ == "__main__":
    unittest.main()
