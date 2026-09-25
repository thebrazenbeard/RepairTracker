import tempfile
import unittest
from pathlib import Path

from repairtracker.discovery import discover_repository
from repairtracker.system_model import FactDisposition, SystemFact, SystemModel


class DiscoveryTests(unittest.TestCase):
    def test_discovery_is_structural_and_never_authorizes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
            workflow = root / ".github" / "workflows"
            workflow.mkdir(parents=True)
            (workflow / "ci.yml").write_text("name: ci\n", encoding="utf-8")
            tests = root / "tests"
            tests.mkdir()
            (tests / "test_x.py").write_text("pass\n", encoding="utf-8")

            result = discover_repository(root)
            dispositions = {fact.disposition for fact in result.model.facts}

            self.assertTrue(result.model.facts)
            self.assertNotIn(FactDisposition.AUTHORIZED_CAPABILITY, dispositions)
            self.assertIn("digest", result.model.to_dict())

    def test_system_model_rejects_discovery_authority_laundering(self):
        model = SystemModel()
        fact = SystemFact(
            fact_id="auth",
            kind="capability",
            key="deploy",
            value=True,
            disposition=FactDisposition.AUTHORIZED_CAPABILITY,
            provenance="README.md",
        )
        with self.assertRaises(ValueError):
            model.add_discovered_fact(fact)

    def test_system_model_rejects_duplicate_fact_identity(self):
        model = SystemModel()
        first = SystemFact(
            fact_id="same",
            kind="test_surface",
            key="tests/a.py",
            value="test-file",
            disposition=FactDisposition.OBSERVED_SOURCE,
            provenance="tests/a.py",
        )
        second = SystemFact(
            fact_id="same",
            kind="deployment_surface",
            key="deploy.yml",
            value="something-else",
            disposition=FactDisposition.OBSERVED_SOURCE,
            provenance="deploy.yml",
        )
        model.add_discovered_fact(first)
        with self.assertRaises(ValueError):
            model.add_discovered_fact(second)


if __name__ == "__main__":
    unittest.main()
