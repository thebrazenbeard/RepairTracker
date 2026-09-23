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
    """Discovery and admission are deliberately separate."""

    def __init__(self) -> None:
        self._providers: dict[str, CapabilityAdvertisement] = {}
        self._admitted: set[str] = set()

    def register(self, advertisement: CapabilityAdvertisement) -> None:
        if advertisement.provider_id in self._providers:
            raise ValueError(f"provider already registered: {advertisement.provider_id}")
        self._providers[advertisement.provider_id] = advertisement

    def admit(self, provider_id: str) -> None:
        if provider_id not in self._providers:
            raise KeyError(provider_id)
        self._admitted.add(provider_id)

    def revoke(self, provider_id: str) -> None:
        self._admitted.discard(provider_id)

    def discovered(self, capability: Capability) -> tuple[CapabilityAdvertisement, ...]:
        return tuple(
            provider for provider in self._providers.values()
            if provider.capability is capability
        )

    def eligible(self, capability: Capability) -> tuple[CapabilityAdvertisement, ...]:
        return tuple(
            provider for provider in self.discovered(capability)
            if provider.provider_id in self._admitted
        )

    def select(self, capability: Capability) -> CapabilityAdvertisement:
        eligible = self.eligible(capability)
        if not eligible:
            raise LookupError(f"no admitted provider for capability {capability}")
        # External specialization is progressive enhancement only after admission.
        return sorted(
            eligible,
            key=lambda item: (item.provider_kind is ProviderKind.EXTERNAL, item.provider_id),
            reverse=True,
        )[0]
