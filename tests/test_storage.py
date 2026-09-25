import tempfile
import unittest
from pathlib import Path

from repairtracker.model import EvidenceClass, RepairEvent
from repairtracker.storage import SQLiteEventStore, StaleHeadError


class StorageTests(unittest.TestCase):
    def test_sqlite_ledger_survives_restart_and_rejects_stale_head(self):
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "repairtracker.sqlite3"

            store = SQLiteEventStore(database)
            first = RepairEvent(
                event_id="evt-1",
                repair_id="R-1",
                event_type="INCIDENT_DETECTED",
                subject_id="repo@sha",
                evidence_class=EvidenceClass.OBSERVED,
                actor="test",
            )
            receipt1 = store.append(first)
            self.assertEqual(receipt1.generation, 1)

            second = RepairEvent(
                event_id="evt-2",
                repair_id="R-1",
                event_type="DIAGNOSIS_STARTED",
                subject_id="repo@sha",
                evidence_class=EvidenceClass.OBSERVED,
                actor="test",
                predecessor_digest=first.digest,
            )
            receipt2 = store.append(second)
            self.assertEqual(receipt2.generation, 2)

            restarted = SQLiteEventStore(database)
            log = restarted.load("R-1")
            self.assertEqual(len(log.events), 2)
            self.assertEqual(log.head_digest, second.digest)
            self.assertEqual(restarted.head("R-1"), (second.digest, 2))

            stale = RepairEvent(
                event_id="evt-stale",
                repair_id="R-1",
                event_type="STALE_WRITE",
                subject_id="repo@sha",
                evidence_class=EvidenceClass.INFERENCE,
                actor="stale-worker",
                predecessor_digest=first.digest,
            )
            with self.assertRaises(StaleHeadError):
                restarted.append(stale)

            log_after = restarted.load("R-1")
            self.assertEqual(len(log_after.events), 2)


if __name__ == "__main__":
    unittest.main()
