from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from repairtracker.capabilities import CapabilityAdvertisement


@dataclass(frozen=True, slots=True)
class ExternalReference:
    source_system: str
    source_subject: str
    locator: str | None
    payload_digest: str | None
    evidence_class: str
    effect_ceiling: str


class CapabilityAdapter(Protocol):
    def advertisement(self) -> CapabilityAdvertisement: ...

    def observe(self) -> dict[str, Any]: ...
