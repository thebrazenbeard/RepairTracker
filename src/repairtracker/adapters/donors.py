from __future__ import annotations

from dataclasses import dataclass

from repairtracker.capabilities import (
    Capability,
    CapabilityAdvertisement,
    ProviderKind,
)
from repairtracker.portfolio import RepositoryObservation


@dataclass(frozen=True, slots=True)
class DonorDescriptor:
    repository_id: str
    capabilities: tuple[Capability, ...]
    operations: tuple[str, ...]
    evidence_outputs: tuple[str, ...]


_DONORS: tuple[DonorDescriptor, ...] = (
    DonorDescriptor(
        "thebrazenbeard/roots",
        (Capability.PROVENANCE,),
        ("trace_provenance", "reconstruct_lineage"),
        ("provenance_receipt",),
    ),
    DonorDescriptor(
        "thebrazenbeard/rezon",
        (Capability.HOSTILE_REVIEW,),
        ("adversarial_review", "falsify_claim"),
        ("review_receipt",),
    ),
    DonorDescriptor(
        "thebrazenbeard/driftguard",
        (Capability.REGRESSION_ADMISSION,),
        ("evaluate_candidate", "compare_baseline"),
        ("admission_receipt",),
    ),
    DonorDescriptor(
        "thebrazenbeard/project-runner",
        (Capability.WORK_EXECUTION,),
        ("plan_work", "dispatch_work", "reconcile_work"),
        ("execution_receipt",),
    ),
    DonorDescriptor(
        "thebrazenbeard/wip",
        (Capability.RECOVERY,),
        ("checkpoint", "recover_operation", "reconcile_effect"),
        ("recovery_receipt",),
    ),
    DonorDescriptor(
        "thebrazenbeard/chat-communication-bus",
        (Capability.COMMUNICATION,),
        ("route_message", "thread_repair_coordination"),
        ("message_receipt",),
    ),
    DonorDescriptor(
        "thebrazenbeard/masamune",
        (Capability.DEBUGGING,),
        ("reproduce_failure", "isolate_root_cause", "verify_regression"),
        ("debug_receipt",),
    ),
    DonorDescriptor(
        "thebrazenbeard/project-achilles",
        (Capability.SECURITY_REVIEW,),
        ("classify_effect", "review_security_boundary"),
        ("security_review_receipt",),
    ),
    DonorDescriptor(
        "thebrazenbeard/vera-control-plane",
        (Capability.CONTROL_PLANE,),
        ("coordinate_control_plane", "separate_source_runtime_effect"),
        ("control_plane_receipt",),
    ),
)


def known_donor_descriptors() -> tuple[DonorDescriptor, ...]:
    return _DONORS


def advertisements_for_repository(
    observation: RepositoryObservation,
) -> tuple[CapabilityAdvertisement, ...]:
    descriptor = next(
        (
            item
            for item in _DONORS
            if item.repository_id.lower() == observation.repository_id.lower()
        ),
        None,
    )
    if descriptor is None:
        return ()

    revision = observation.revision or "UNPINNED"
    return tuple(
        CapabilityAdvertisement(
            provider_id=descriptor.repository_id,
            provider_version=revision,
            capability=capability,
            provider_kind=ProviderKind.EXTERNAL,
            supported_operations=descriptor.operations,
            evidence_outputs=descriptor.evidence_outputs,
            effect_ceiling="OBSERVE_ONLY",
            currentness_ref=observation.revision,
            replay_semantics="PROVIDER_DEFINED",
        )
        for capability in descriptor.capabilities
    )


def register_detected_donors(
    observations: tuple[RepositoryObservation, ...],
    registry,
) -> tuple[CapabilityAdvertisement, ...]:
    """Register exact-identity donor advertisements without admitting them."""

    registered: list[CapabilityAdvertisement] = []
    for observation in observations:
        for advertisement in advertisements_for_repository(observation):
            registry.register(advertisement)
            registered.append(advertisement)
    return tuple(registered)
