# BugOps migration snapshot — 2026-10-02

Source repository: 	hebrazenbeard/bugops
Exact source head: 1d35bcbd16da24c7635a004845de1390de850b4e

This directory preserves the four still-open BugOps SEV-1 incident reports and the exact source incident registry before repository archival.

NORMALIZED_INCIDENTS.json supplies the fields required by RepairTracker's existing import_normalized_bugops_incident() adapter while retaining source issue/report locators. Status remains OPEN; migration is custody/queue transfer, not behavioral closure.

The archived BugOps repository remains provenance. RepairTracker becomes the live repair queue for these incidents after corresponding issues are created.
