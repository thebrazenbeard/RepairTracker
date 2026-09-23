from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Capability(StrEnum):
    PROVENANCE = "PROVENANCE"
    HOSTILE_REVIEW = "HOSTILE_REVIEW"
    REGRESSION_ADMISSION = "REGRESSION_ADMISSION"
    WORK_EXECUTION = "WORK_EXECUTION"
    RECOVERY = "RECOVERY"
    COMMUNICATION = "COMMUNICATION"
    DEBUGGING = "DEBUGGING"
    SECURITY_REVIEW = "SECURITY_REVIEW"
    OBSERVABILITY = "OBSERVABILITY"
    CONTROL_PLANE = "CONTROL_PLANE"


class ProviderKind(StrEnum):
    NATIVE = "NATIVE"
    EXTERNAL = "EXTERNAL"


@dataclass(frozen=True, slots=True)
class CapabilityAdvertisement:
    provider_id: str
    provider_version: str
    capability: Capability
    provider_kind: ProviderKind
    supported_operations: tuple[str, ...]
    evidence_outputs: tuple[str, ...]
    effect_ceiling: str
    currentness_ref: str | None = None
    replay_semantics: str = "UNSPECIFIED"


class CapabilityRegistry:
    """Discovery and admission are deliberately separate.

    One provider may advertise several capabilities. Admission applies to the
    provider identity, not just one advertisement, but does not grant any
    authority beyond each advertisement's effect ceiling.
    """

    def __init__(self) -> None:
        self._providers: dict[
            tuple[str, Capability], CapabilityAdvertisement
        ] = {}
        self._admitted: set[str] = set()

    def register(self, advertisement: CapabilityAdvertisement) -> None:
        key = (advertisement.provider_id, advertisement.capability)
        if key in self._providers:
            raise ValueError(
                "provider capability already registered: "
                f"{advertisement.provider_id}/{advertisement.capability}"
            )
        self._providers[key] = advertisement

    def admit(self, provider_id: str) -> None:
        if not any(
            candidate_id == provider_id
            for candidate_id, _ in self._providers
        ):
            raise KeyError(provider_id)
        self._admitted.add(provider_id)

    def revoke(self, provider_id: str) -> None:
        self._admitted.discard(provider_id)

    def discovered(self, capability: Capability) -> tuple[CapabilityAdvertisement, ...]:
        return tuple(
            provider
            for (_, candidate_capability), provider in self._providers.items()
            if candidate_capability is capability
        )

    def eligible(self, capability: Capability) -> tuple[CapabilityAdvertisement, ...]:
        return tuple(
            provider
            for provider in self.discovered(capability)
            if provider.provider_id in self._admitted
        )

    def select(self, capability: Capability) -> CapabilityAdvertisement:
        eligible = self.eligible(capability)
        if not eligible:
            raise LookupError(f"no admitted provider for capability {capability}")
        return sorted(
            eligible,
            key=lambda item: (
                item.provider_kind is ProviderKind.EXTERNAL,
                item.provider_id,
            ),
            reverse=True,
        )[0]
