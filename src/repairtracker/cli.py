from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .adapters.attestation_cli import GitHubCLIAttestationVerifier
from .adapters.github import GitHubReadClient
from .discovery import discover_repository
from .hostile import HostileReviewRequest
from .portfolio import bootstrap_portfolio, observe_local_repository
from .promotion import (
    SignalPromotionPolicy,
    evaluate_signal,
    persist_promotion,
    promote_signal,
)
from .storage import SQLiteEventStore


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

    portfolio_authenticated = sub.add_parser(
        "portfolio-github-authenticated",
        help="discover repositories visible to the authenticated GitHub identity",
    )
    portfolio_authenticated.add_argument("--portfolio-id", default="authenticated")
    portfolio_authenticated.add_argument("--max-repositories", type=int, default=200)
    portfolio_authenticated.add_argument("--include-archived", action="store_true")
    portfolio_authenticated.add_argument("--include-forks", action="store_true")
    portfolio_authenticated.add_argument("--token-env", default="GITHUB_TOKEN")

    github_signals = sub.add_parser(
        "github-signals",
        help="read bounded GitHub candidate repair signals without incident promotion",
    )
    github_signals.add_argument("repository")
    github_signals.add_argument("--max-items-per-kind", type=int, default=200)
    github_signals.add_argument("--token-env", default="GITHUB_TOKEN")

    github_attestations = sub.add_parser(
        "github-attestations",
        help=(
            "locate GitHub artifact attestations without treating listing as "
            "cryptographic verification"
        ),
    )
    github_attestations.add_argument("repository")
    github_attestations.add_argument("subject_digest")
    github_attestations.add_argument("--predicate-type", default="provenance")
    github_attestations.add_argument("--max-results", type=int, default=100)
    github_attestations.add_argument("--token-env", default="GITHUB_TOKEN")

    verify_attestation = sub.add_parser(
        "verify-oci-attestation",
        help="cryptographically verify SLSA provenance for a digest-pinned OCI image",
    )
    verify_attestation.add_argument("artifact_name")
    verify_attestation.add_argument("sha256_digest")
    verify_attestation.add_argument("repository")
    verify_attestation.add_argument("source_revision")
    verify_attestation.add_argument("--signer-workflow")
    verify_attestation.add_argument("--deny-self-hosted-runners", action="store_true")
    verify_attestation.add_argument("--bundle-from-oci", action="store_true")

    promotion_plan = sub.add_parser(
        "github-promotion-plan",
        help="evaluate GitHub candidate repair signals against an explicit policy",
    )
    promotion_plan.add_argument("repository")
    promotion_plan.add_argument("--policy", required=True)
    promotion_plan.add_argument("--max-items-per-kind", type=int, default=200)
    promotion_plan.add_argument("--token-env", default="GITHUB_TOKEN")

    promote = sub.add_parser(
        "github-promote",
        help="persist explicitly policy-matched GitHub signals as RepairCases",
    )
    promote.add_argument("repository")
    promote.add_argument("--policy", required=True)
    promote.add_argument("--sqlite", required=True)
    promote.add_argument("--actor", default="repairtracker/promotion-engine")
    promote.add_argument("--max-items-per-kind", type=int, default=200)
    promote.add_argument("--token-env", default="GITHUB_TOKEN")

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

    if args.command == "portfolio-github-authenticated":
        token = os.environ.get(args.token_env)
        if not token:
            raise SystemExit(
                f"{args.token_env} is required for authenticated portfolio discovery"
            )
        client = GitHubReadClient(token=token)
        observations, warnings = client.observe_authenticated_portfolio(
            include_archived=args.include_archived,
            include_forks=args.include_forks,
            max_repositories=args.max_repositories,
        )
        topology = bootstrap_portfolio(
            observations,
            portfolio_id=args.portfolio_id,
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
                            "repository_stable_id": signal.repository_stable_id,
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

    if args.command == "github-attestations":
        token = os.environ.get(args.token_env)
        client = GitHubReadClient(token=token)
        result = client.list_attestations(
            args.repository,
            args.subject_digest,
            predicate_type=args.predicate_type,
            max_results=args.max_results,
        )
        print(
            json.dumps(
                {
                    "schema": "REPAIRTRACKER_GITHUB_ATTESTATION_INDEX_V0",
                    "cryptographically_verified": False,
                    "references": [
                        {
                            "repository_id": item.repository_id,
                            "subject_digest": item.subject_digest,
                            "bundle_url": item.bundle_url,
                            "initiator": item.initiator,
                        }
                        for item in result.references
                    ],
                    "warnings": list(result.warnings),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    if args.command == "verify-oci-attestation":
        verifier = GitHubCLIAttestationVerifier()
        receipts = verifier.verify_oci(
            artifact_name=args.artifact_name,
            sha256_digest=args.sha256_digest,
            repository_id=args.repository,
            source_revision=args.source_revision,
            signer_workflow=args.signer_workflow,
            deny_self_hosted_runners=args.deny_self_hosted_runners,
            bundle_from_oci=args.bundle_from_oci,
        )
        print(
            json.dumps(
                {
                    "schema": "REPAIRTRACKER_ATTESTATION_VERIFICATION_V0",
                    "cryptographically_verified": True,
                    "receipts": [
                        {
                            "verifier": item.verifier,
                            "verified_at": item.verified_at,
                            "repository_id": item.repository_id,
                            "subject_algorithm": item.subject_algorithm,
                            "subject_digest": item.subject_digest,
                            "predicate_type": item.predicate_type,
                            "source_repository_id": item.source_repository_id,
                            "source_revision": item.source_revision,
                            "verification_locator": item.verification_locator,
                            "signer_policy": item.signer_policy,
                            "witness_timestamps": list(item.witness_timestamps),
                            "statement_digest": item.statement_digest,
                        }
                        for item in receipts
                    ],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    if args.command in {"github-promotion-plan", "github-promote"}:
        policy_payload = json.loads(
            Path(args.policy).read_text(encoding="utf-8")
        )
        if not isinstance(policy_payload, dict):
            raise SystemExit("promotion policy must be a JSON object")
        policy = SignalPromotionPolicy.from_dict(policy_payload)
        token = os.environ.get(args.token_env)
        client = GitHubReadClient(token=token)
        signal_result = client.observe_repair_signals(
            args.repository,
            max_items_per_kind=args.max_items_per_kind,
        )

        decisions = []
        promotions = []
        store = (
            SQLiteEventStore(args.sqlite)
            if args.command == "github-promote"
            else None
        )
        for signal in signal_result.signals:
            decision = evaluate_signal(signal, policy)
            decision_payload = {
                "signal_key": decision.signal_key,
                "disposition": decision.disposition.value,
                "policy_id": decision.policy_id,
                "policy_digest": decision.policy_digest,
                "rule_id": decision.rule_id,
                "severity": (
                    decision.severity.value
                    if decision.severity is not None
                    else None
                ),
                "reason": decision.reason,
            }
            decisions.append(decision_payload)

            promotion = promote_signal(
                signal,
                policy,
                actor=(
                    args.actor
                    if args.command == "github-promote"
                    else "repairtracker/promotion-plan"
                ),
            )
            if promotion is None:
                continue

            promotion_payload = {
                "repair_id": promotion.repair_case.repair_id,
                "title": promotion.repair_case.title,
                "subject_id": promotion.repair_case.subject_id,
                "severity": promotion.repair_case.severity.value,
                "opening_event_id": promotion.opening_event.event_id,
                "source_subject": promotion.opening_event.source_subject,
                "authority_or_effect_ceiling": (
                    promotion.opening_event.authority_or_effect_ceiling
                ),
            }
            if store is not None:
                persisted = persist_promotion(store, promotion)
                promotion_payload["persistence"] = {
                    "created": persisted.created,
                    "generation": persisted.generation,
                    "event_digest": persisted.event_digest,
                    "evidence_changed": persisted.evidence_changed,
                    "policy_changed": persisted.policy_changed,
                    "incoming_policy_digest": persisted.incoming_policy_digest,
                    "persisted_policy_digest": persisted.persisted_policy_digest,
                    "incoming_signal_payload_digest": (
                        persisted.incoming_signal_payload_digest
                    ),
                    "persisted_signal_payload_digest": (
                        persisted.persisted_signal_payload_digest
                    ),
                }
            promotions.append(promotion_payload)

        print(
            json.dumps(
                {
                    "schema": (
                        "REPAIRTRACKER_GITHUB_PROMOTION_V0"
                        if store is not None
                        else "REPAIRTRACKER_GITHUB_PROMOTION_PLAN_V0"
                    ),
                    "policy_id": policy.policy_id,
                    "policy_digest": policy.digest,
                    "decisions": decisions,
                    "promotions": promotions,
                    "warnings": list(signal_result.warnings),
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
