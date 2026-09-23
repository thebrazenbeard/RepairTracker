from __future__ import annotations

import argparse
import json
import os

from .adapters.github import GitHubReadClient
from .discovery import discover_repository
from .hostile import HostileReviewRequest
from .portfolio import bootstrap_portfolio, observe_local_repository


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="repairtracker")
    sub = parser.add_subparsers(dest="command", required=True)

    discover = sub.add_parser("discover", help="read-only repository discovery")
    discover.add_argument("path", nargs="?", default=".")
    discover.add_argument("--max-files", type=int, default=10_000)

    portfolio_local = sub.add_parser(
        "portfolio-local",
        help="bootstrap a topology from one or more local repositories",
    )
    portfolio_local.add_argument("paths", nargs="+")
    portfolio_local.add_argument("--portfolio-id", default="default")
    portfolio_local.add_argument("--max-files", type=int, default=10_000)

    portfolio_github = sub.add_parser(
        "portfolio-github",
        help="bootstrap a topology from explicit GitHub repositories (read-only)",
    )
    portfolio_github.add_argument("repositories", nargs="+")
    portfolio_github.add_argument("--portfolio-id", default="default")
    portfolio_github.add_argument("--token-env", default="GITHUB_TOKEN")

    portfolio_owner = sub.add_parser(
        "portfolio-github-owner",
        help="discover and bootstrap a bounded GitHub user/org portfolio (read-only)",
    )
    portfolio_owner.add_argument("owner")
    portfolio_owner.add_argument("--kind", choices=("user", "org"), default="user")
    portfolio_owner.add_argument("--portfolio-id")
    portfolio_owner.add_argument("--max-repositories", type=int, default=200)
    portfolio_owner.add_argument("--include-archived", action="store_true")
    portfolio_owner.add_argument("--include-forks", action="store_true")
    portfolio_owner.add_argument("--token-env", default="GITHUB_TOKEN")

    github_signals = sub.add_parser(
        "github-signals",
        help="read bounded GitHub candidate repair signals without incident promotion",
    )
    github_signals.add_argument("repository")
    github_signals.add_argument("--max-items-per-kind", type=int, default=200)
    github_signals.add_argument("--token-env", default="GITHUB_TOKEN")

    hostile = sub.add_parser(
        "hostile-template", help="emit hostile-review attack prompts"
    )
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

    if args.command == "portfolio-local":
        observations = [
            observe_local_repository(path, max_files=args.max_files)
            for path in args.paths
        ]
        topology = bootstrap_portfolio(
            observations, portfolio_id=args.portfolio_id
        )
        print(json.dumps(topology.to_dict(), indent=2, sort_keys=True))
        return 0

    if args.command == "portfolio-github":
        token = os.environ.get(args.token_env)
        client = GitHubReadClient(token=token)
        observations = [
            client.observe_repository(repository)
            for repository in args.repositories
        ]
        topology = bootstrap_portfolio(
            observations, portfolio_id=args.portfolio_id
        )
        print(json.dumps(topology.to_dict(), indent=2, sort_keys=True))
        return 0

    if args.command == "portfolio-github-owner":
        token = os.environ.get(args.token_env)
        client = GitHubReadClient(token=token)
        observations, warnings = client.observe_owner_portfolio(
            args.owner,
            args.kind,
            include_archived=args.include_archived,
            include_forks=args.include_forks,
            max_repositories=args.max_repositories,
        )
        topology = bootstrap_portfolio(
            observations,
            portfolio_id=args.portfolio_id or args.owner,
        )
        topology.warnings.extend(warnings)
        print(json.dumps(topology.to_dict(), indent=2, sort_keys=True))
        return 0

    if args.command == "github-signals":
        token = os.environ.get(args.token_env)
        client = GitHubReadClient(token=token)
        result = client.observe_repair_signals(
            args.repository,
            max_items_per_kind=args.max_items_per_kind,
        )
        print(
            json.dumps(
                {
                    "schema": "REPAIRTRACKER_GITHUB_SIGNALS_V0",
                    "signals": [
                        {
                            "kind": signal.kind,
                            "repository_id": signal.repository_id,
                            "external_id": signal.external_id,
                            "title": signal.title,
                            "state": signal.state,
                            "locator": signal.locator,
                            "observed_at": signal.observed_at,
                            "subject_ref": signal.subject_ref,
                            "payload_digest": signal.payload_digest,
                        }
                        for signal in result.signals
                    ],
                    "warnings": list(result.warnings),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    if args.command == "hostile-template":
        request = HostileReviewRequest(
            proposition=args.proposition,
            success_criteria=tuple(args.success),
        )
        print(
            json.dumps(
                {
                    "schema": "REPAIRTRACKER_HOSTILE_REVIEW_TEMPLATE_V0",
                    "proposition": request.proposition,
                    "success_criteria": list(request.success_criteria),
                    "attacks": list(request.prompts()),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    raise AssertionError("unreachable")
