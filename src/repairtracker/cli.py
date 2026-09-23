from __future__ import annotations

import argparse
import json

from .discovery import discover_repository
from .hostile import HostileReviewRequest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="repairtracker")
    sub = parser.add_subparsers(dest="command", required=True)

    discover = sub.add_parser("discover", help="read-only repository discovery")
    discover.add_argument("path", nargs="?", default=".")
    discover.add_argument("--max-files", type=int, default=10_000)

    hostile = sub.add_parser("hostile-template", help="emit hostile-review attack prompts")
    hostile.add_argument("proposition")
    hostile.add_argument("--success", action="append", default=[])

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    if args.command == "discover":
        result = discover_repository(args.path, max_files=args.max_files)
        payload = result.model.to_dict()
        payload["warnings"] = list(result.warnings)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    if args.command == "hostile-template":
        request = HostileReviewRequest(
            proposition=args.proposition,
            success_criteria=tuple(args.success),
        )
        print(json.dumps({
            "schema": "REPAIRTRACKER_HOSTILE_REVIEW_TEMPLATE_V0",
            "proposition": request.proposition,
            "success_criteria": list(request.success_criteria),
            "attacks": list(request.prompts()),
        }, indent=2, sort_keys=True))
        return 0

    raise AssertionError("unreachable")
