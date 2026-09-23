import unittest

from repairtracker.adapters.donors import (
    advertisements_for_repository,
    register_detected_donors,
)
from repairtracker.capabilities import Capability, CapabilityRegistry
from repairtracker.portfolio import RepositoryObservation


def donor(repo):
    return RepositoryObservation(
        repository_id=repo,
        default_branch="main",
        revision="a" * 40,
        observed_at="2026-09-23T10:00:00+00:00",
        source_system="fixture",
        source_locator=f"fixture://{repo}",
        files={},
    )


class DonorAdapterTests(unittest.TestCase):
    def test_donor_detection_does_not_auto_admit(self):
        observation = donor("thebrazenbeard/roots")
        ads = advertisements_for_repository(observation)
        self.assertEqual(len(ads), 1)
        self.assertEqual(ads[0].capability, Capability.PROVENANCE)
        self.assertEqual(ads[0].effect_ceiling, "OBSERVE_ONLY")
        self.assertEqual(ads[0].currentness_ref, "a" * 40)

        registry = CapabilityRegistry()
        registry.register(ads[0])
        with self.assertRaises(LookupError):
            registry.select(Capability.PROVENANCE)

        registry.admit("thebrazenbeard/roots")
        self.assertEqual(
            registry.select(Capability.PROVENANCE).provider_id,
            "thebrazenbeard/roots",
        )

    def test_vcp_can_advertise_control_plane_without_granting_effect(self):
        ads = advertisements_for_repository(
            donor("thebrazenbeard/vera-control-plane")
        )
        self.assertEqual(len(ads), 1)
        self.assertEqual(ads[0].capability, Capability.CONTROL_PLANE)
        self.assertEqual(ads[0].effect_ceiling, "OBSERVE_ONLY")

    def test_bulk_detection_registers_without_admission(self):
        registry = CapabilityRegistry()
        ads = register_detected_donors(
            (donor("thebrazenbeard/roots"), donor("thebrazenbeard/rezon")),
            registry,
        )
        self.assertEqual(len(ads), 2)
        with self.assertRaises(LookupError):
            registry.select(Capability.PROVENANCE)
        with self.assertRaises(LookupError):
            registry.select(Capability.HOSTILE_REVIEW)

    def test_unknown_repo_is_not_a_donor(self):
        self.assertEqual(advertisements_for_repository(donor("acme/random")), ())


if __name__ == "__main__":
    unittest.main()
