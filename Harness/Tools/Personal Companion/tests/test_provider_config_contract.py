"""Guard the shipped provider example against schema drift.

This intentionally uses only the standard library so the Personal Companion
package keeps its zero-runtime-dependency contract.
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "providers.example.json"
SCHEMA_PATH = ROOT / "schemas" / "llm-providers.v1.schema.json"
ROUTES = {"system1_local", "system1_api", "system2_local", "system2_api"}


class ProviderConfigContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        cls.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    def test_example_top_level_keys_are_declared_by_schema(self) -> None:
        properties = self.schema["properties"]
        self.assertEqual(self.config["schema"], self.schema["properties"]["schema"]["const"])
        self.assertTrue(set(self.schema["required"]).issubset(self.config))
        self.assertFalse(set(self.config) - set(properties))

    def test_all_four_routes_match_the_provider_definition(self) -> None:
        route_schema = self.schema["properties"]["routes"]
        provider_schema = self.schema["$defs"]["provider"]
        route_properties = route_schema["properties"]
        provider_properties = provider_schema["properties"]

        self.assertEqual(set(self.config["routes"]), ROUTES)
        self.assertEqual(set(route_schema["required"]), ROUTES)
        self.assertEqual(set(route_properties), ROUTES)

        for route_name, route in self.config["routes"].items():
            with self.subTest(route=route_name):
                self.assertFalse(set(provider_schema["required"]) - set(route))
                self.assertFalse(set(route) - set(provider_properties))
                self.assertIs(type(route["enabled"]), bool)
                self.assertIn(route["kind"], provider_properties["kind"]["enum"])
                self.assertIsInstance(route["model"], str)
                self.assertTrue(route["model"].strip())
                self.assertIs(type(route["timeout_seconds"]), int)
                self.assertGreaterEqual(route["timeout_seconds"], 1)
                self.assertLessEqual(route["timeout_seconds"], 600)

                parsed = urlsplit(route["base_url"])
                self.assertIn(parsed.scheme, {"http", "https"})
                self.assertTrue(parsed.hostname)

                key_env = route.get("api_key_env")
                if route["kind"] == "api":
                    self.assertIsInstance(key_env, str)
                    self.assertRegex(key_env, r"^[A-Z][A-Z0-9_]*$")
                else:
                    self.assertTrue(key_env is None or isinstance(key_env, str))

    def test_routing_section_declares_every_example_route_selector(self) -> None:
        section_schema = self.schema["properties"]["routing"]
        properties = section_schema["properties"]
        section = self.config["routing"]

        self.assertTrue(set(section_schema["required"]).issubset(section))
        self.assertFalse(set(section) - set(properties))
        for name, value in section.items():
            with self.subTest(setting=name):
                if name == "allow_automatic_fallback":
                    self.assertIs(type(value), bool)
                else:
                    self.assertIn(value, properties[name]["enum"])
                    self.assertIn(value, ROUTES)

    def test_safety_section_declares_and_preserves_every_invariant(self) -> None:
        section_schema = self.schema["properties"]["safety"]
        properties = section_schema["properties"]
        section = self.config["safety"]

        self.assertTrue(set(section_schema["required"]).issubset(section))
        self.assertEqual(set(section), set(properties))
        for name, value in section.items():
            with self.subTest(setting=name):
                self.assertIs(type(value), bool)
                self.assertEqual(properties[name]["type"], "boolean")
                if "const" in properties[name]:
                    self.assertIs(value, properties[name]["const"])

    def test_chat_only_is_a_rollout_flag_not_a_permission_override(self) -> None:
        safety = self.schema["properties"]["safety"]["properties"]
        self.assertNotIn("const", safety["chat_only_initially"])
        self.assertIs(type(self.config["safety"]["chat_only_initially"]), bool)
        self.assertIs(safety["legacy_agents_enabled"]["const"], False)
        self.assertIs(safety["tool_execution_requires_policy"]["const"], True)
        self.assertIs(safety["provider_config_cannot_change_permissions"]["const"], True)


if __name__ == "__main__":
    unittest.main()
