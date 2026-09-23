from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from repairtracker.case import RepairCase
from repairtracker.model import Severity


SEVERITY_MAP = {
    "SEV-0": Severity.SEV_0,
    "SEV-1": Severity.SEV_1,
    "SEV-2": Severity.SEV_2,
    "SEV-3": Severity.SEV_3,
}


def import_normalized_bugops_incident(record: Mapping[str, Any]) -> RepairCase:
    """Import a normalized legacy BugOps incident into RepairTracker.

    This intentionally does not pretend arbitrary Markdown can be losslessly
    interpreted. A future migration tool may normalize legacy reports first.
    """

    required = ("incident_id", "title", "subject_id", "severity")
    missing = [key for key in required if not record.get(key)]
    if missing:
        raise ValueError(f"missing normalized BugOps fields: {', '.join(missing)}")

    try:
        severity = SEVERITY_MAP[str(record["severity"])]
    except KeyError as exc:
        raise ValueError(f"unsupported BugOps severity: {record['severity']}") from exc

    return RepairCase(
        repair_id=str(record["incident_id"]),
        title=str(record["title"]),
        subject_id=str(record["subject_id"]),
        severity=severity,
    )
