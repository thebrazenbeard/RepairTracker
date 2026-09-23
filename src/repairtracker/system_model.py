from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

from .model import canonical_digest


class FactDisposition(StrEnum):
    OBSERVED_SOURCE = "OBSERVED_SOURCE"
    DECLARED_CONFIGURATION = "DECLARED_CONFIGURATION"
    EXECUTABLE_CONFIGURATION = "EXECUTABLE_CONFIGURATION"
    DERIVED_RELATION = "DERIVED_RELATION"
    HYPOTHESIS = "HYPOTHESIS"
    VERIFIED_RELATION = "VERIFIED_RELATION"
    AUTHORIZED_CAPABILITY = "AUTHORIZED_CAPABILITY"


@dataclass(frozen=True, slots=True)
class SystemFact:
    fact_id: str
    kind: str
    key: str
    value: Any
    disposition: FactDisposition
    provenance: str
    confidence: float = 1.0
    currentness: str = "OBSERVED_AT_BOOTSTRAP"

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")


@dataclass(slots=True)
class SystemModel:
    facts: list[SystemFact] = field(default_factory=list)

    def add_discovered_fact(self, fact: SystemFact) -> None:
        if fact.disposition is FactDisposition.AUTHORIZED_CAPABILITY:
            raise ValueError(
                "discovery cannot manufacture AUTHORIZED_CAPABILITY; "
                "authorization requires a separate admission step"
            )
        self.facts.append(fact)

    @property
    def digest(self) -> str:
        serial = []
        for fact in sorted(self.facts, key=lambda item: item.fact_id):
            row = asdict(fact)
            row["disposition"] = fact.disposition.value
            serial.append(row)
        return canonical_digest(serial)

    def to_dict(self) -> dict[str, Any]:
        rows = []
        for fact in self.facts:
            row = asdict(fact)
            row["disposition"] = fact.disposition.value
            rows.append(row)
        return {"schema": "REPAIRTRACKER_SYSTEM_MODEL_V0", "facts": rows, "digest": self.digest}
