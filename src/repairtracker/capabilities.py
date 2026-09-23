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


@dataclass(frozen=True, slots=True)
class QualificationReceipt:
    provider_id: str
    provider_version: str
    capability: Capability
    method: str
    evidence_ref: str

    def __post_init__(self) -> None:
        if not self.method.strip():
            raise ValueError("qualification method is required")
        if not self.evidence_ref.strip():
            raise ValueError("qualification evidence_ref is required")


class CapabilityRegistry:
    """Discovery, qualification, and admission are separate states.

    Native providers are source-local and can become eligible after admission.
    External providers must be both qualified for the exact advertised
    version/capability and admitted. Neither state expands the advertisement's
    effect ceiling.
    """

    def __init__(self) -> None:
        self._providers: dict[
            tuple[str, Capability], CapabilityAdvertisement
        ] = {}
        self._qualified: dict[
            tuple[str, Capability], QualificationReceipt
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

    def qualify(self, receipt: QualificationReceipt) -> None:
        key = (receipt.provider_id, receipt.capability)
        advertisement = self._providers.get(key)
        if advertisement is None:
            raise KeyError(key)
        if advertisement.provider_kind is not ProviderKind.EXTERNAL:
            raise ValueError("native providers do not require external qualification")
        if receipt.provider_version != advertisement.provider_version:
            raise ValueError(
                "qualification version mismatch: "
                f"advertised={advertisement.provider_version}, "
                f"qualified={receipt.provider_version}"
            )
        self._qualified[key] = receipt

    def revoke_qualification(
        self, provider_id: str, capability: Capability
    ) -> None:
        self._qualified.pop((provider_id, capability), None)

    def qualification(
        self, provider_id: str, capability: Capability
    ) -> QualificationReceipt | None:
        return self._qualified.get((provider_id, capability))

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
        eligible: list[CapabilityAdvertisement] = []
        for provider in self.discovered(capability):
            if provider.provider_id not in self._admitted:
                continue
            if (
                provider.provider_kind is ProviderKind.EXTERNAL
                and (provider.provider_id, capability) not in self._qualified
            ):
                continue
            eligible.append(provider)
        return tuple(eligible)

    def select(self, capability: Capability) -> CapabilityAdvertisement:
        eligible = self.eligible(capability)
        if not eligible:
            raise LookupError(
                f"no qualified and admitted provider for capability {capability}"
            )
        return sorted(
            eligible,
            key=lambda item: (
                item.provider_kind is ProviderKind.EXTERNAL,
                item.provider_id,
            ),
            reverse=True,
        )[0]
