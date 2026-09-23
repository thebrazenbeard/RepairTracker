import unittest

from repairtracker.capabilities import (
    Capability,
    CapabilityAdvertisement,
    CapabilityRegistry,
    ProviderKind,
    QualificationReceipt,
)


def provider(provider_id: str, kind: ProviderKind, capability=Capability.PROVENANCE):
    return CapabilityAdvertisement(
        provider_id=provider_id,
        provider_version="1",
        capability=capability,
        provider_kind=kind,
        supported_operations=("trace",),
        evidence_outputs=("provenance-receipt",),
        effect_ceiling="OBSERVE_ONLY",
    )


def qualification(provider_id: str, capability=Capability.PROVENANCE):
    return QualificationReceipt(
        provider_id=provider_id,
        provider_version="1",
        capability=capability,
        method="contract-test",
        evidence_ref="test://qualification",
    )


class CapabilityTests(unittest.TestCase):
    def test_external_provider_requires_qualification_and_admission(self):
        registry = CapabilityRegistry()
        registry.register(provider("native", ProviderKind.NATIVE))
        registry.register(provider("roots", ProviderKind.EXTERNAL))

        self.assertEqual(len(registry.discovered(Capability.PROVENANCE)), 2)
        with self.assertRaises(LookupError):
            registry.select(Capability.PROVENANCE)

        registry.admit("native")
        self.assertEqual(registry.select(Capability.PROVENANCE).provider_id, "native")

        registry.admit("roots")
        self.assertEqual(registry.select(Capability.PROVENANCE).provider_id, "native")

        registry.qualify(qualification("roots"))
        self.assertEqual(registry.select(Capability.PROVENANCE).provider_id, "roots")

    def test_qualification_is_bound_to_exact_provider_version(self):
        registry = CapabilityRegistry()
        registry.register(provider("roots", ProviderKind.EXTERNAL))
        registry.admit("roots")
        bad = QualificationReceipt(
            provider_id="roots",
            provider_version="2",
            capability=Capability.PROVENANCE,
            method="contract-test",
            evidence_ref="test://wrong-version",
        )
        with self.assertRaises(ValueError):
            registry.qualify(bad)
        with self.assertRaises(LookupError):
            registry.select(Capability.PROVENANCE)

    def test_one_provider_may_advertise_multiple_capabilities(self):
        registry = CapabilityRegistry()
        registry.register(
            provider("multi", ProviderKind.EXTERNAL, Capability.PROVENANCE)
        )
        registry.register(
            provider("multi", ProviderKind.EXTERNAL, Capability.HOSTILE_REVIEW)
        )
        registry.admit("multi")
        registry.qualify(qualification("multi", Capability.PROVENANCE))
        registry.qualify(qualification("multi", Capability.HOSTILE_REVIEW))
        self.assertEqual(
            registry.select(Capability.PROVENANCE).provider_id,
            "multi",
        )
        self.assertEqual(
            registry.select(Capability.HOSTILE_REVIEW).provider_id,
            "multi",
        )


if __name__ == "__main__":
    unittest.main()
