import unittest

from repairtracker.capabilities import (
    Capability,
    CapabilityAdvertisement,
    CapabilityRegistry,
    ProviderKind,
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


class CapabilityTests(unittest.TestCase):
    def test_discovery_does_not_equal_admission(self):
        registry = CapabilityRegistry()
        registry.register(provider("native", ProviderKind.NATIVE))
        registry.register(provider("roots", ProviderKind.EXTERNAL))

        self.assertEqual(len(registry.discovered(Capability.PROVENANCE)), 2)
        with self.assertRaises(LookupError):
            registry.select(Capability.PROVENANCE)

        registry.admit("native")
        self.assertEqual(registry.select(Capability.PROVENANCE).provider_id, "native")

        registry.admit("roots")
        self.assertEqual(registry.select(Capability.PROVENANCE).provider_id, "roots")

    def test_one_provider_may_advertise_multiple_capabilities(self):
        registry = CapabilityRegistry()
        registry.register(
            provider("multi", ProviderKind.EXTERNAL, Capability.PROVENANCE)
        )
        registry.register(
            provider("multi", ProviderKind.EXTERNAL, Capability.HOSTILE_REVIEW)
        )
        registry.admit("multi")
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
