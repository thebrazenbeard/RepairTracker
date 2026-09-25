import unittest

from repairtracker.adapters.bugops import import_normalized_bugops_incident
from repairtracker.model import Severity


class BugOpsImportTests(unittest.TestCase):
    def test_normalized_bugops_import(self):
        case = import_normalized_bugops_incident({
            "incident_id": "BUG-0007",
            "title": "legacy failure",
            "subject_id": "service-x",
            "severity": "SEV-1",
        })
        self.assertEqual(case.repair_id, "BUG-0007")
        self.assertEqual(case.severity, Severity.SEV_1)


if __name__ == "__main__":
    unittest.main()
