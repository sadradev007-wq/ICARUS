import json
import tempfile
import unittest
from pathlib import Path
from icarus_harness.test_discovery import TestDiscovery
from icarus_harness.workspace import Workspace, WorkspaceError

class TestDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
    def tearDown(self):
        self.temp.cleanup()
    def write(self, name, content=""):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    def discover(self, changed=None):
        return TestDiscovery(Workspace(self.root)).discover(changed)
    def test_python_unittest_profile_and_related_test(self):
        self.write("pyproject.toml", "[project]\nname='demo'\n")
        self.write("src/parser.py", "value = 1\n")
        self.write("tests/test_parser.py", "import unittest\n")
        result = self.discover(["src/parser.py"])
        profile = result["profiles"][0]
        self.assertEqual(profile["language"], "python")
        self.assertEqual(profile["command"], ["python", "-m", "unittest", "discover", "-s", "tests", "-v"])
        self.assertEqual(profile["related_tests"], ["tests/test_parser.py"])
        self.assertFalse(result["execution_performed"])
    def test_pytest_profile_detected_from_configuration(self):
        self.write("pyproject.toml", "[tool.pytest.ini_options]\ntestpaths=['tests']\n")
        self.write("tests/test_api.py", "")
        self.assertEqual(self.discover()["profiles"][0]["command"], ["pytest", "-q"])
    def test_javascript_test_script_and_related_test(self):
        self.write("package.json", json.dumps({"scripts": {"test": "vitest run"}}))
        self.write("src/app.ts", "")
        self.write("src/app.test.ts", "")
        profile = self.discover(["src/app.ts"])["profiles"][0]
        self.assertEqual(profile["language"], "javascript/typescript")
        self.assertEqual(profile["command"], ["pnpm", "test"])
        self.assertEqual(profile["related_tests"], ["src/app.test.ts"])
    def test_pnpm_is_preferred_and_lockfile_is_reported(self):
        self.write("package.json", json.dumps({"packageManager": "pnpm@10.0.0", "scripts": {"test": "vitest run"}}))
        self.write("pnpm-lock.yaml", "lockfileVersion: '9.0'\n")
        result = self.discover()
        ecosystem = next(item for item in result["ecosystems"] if item["language"] == "javascript/typescript")
        self.assertEqual(ecosystem["manager"], "pnpm")
        self.assertEqual(ecosystem["install_command"], ["pnpm", "install", "--frozen-lockfile"])
        self.assertEqual(ecosystem["lockfiles"], ["pnpm-lock.yaml"])
        self.assertEqual(next(p for p in result["profiles"] if p["language"] == "javascript/typescript")["command"], ["pnpm", "test"])

    def test_major_ecosystems_are_discovered(self):
        for marker in ("pyproject.toml", "Cargo.toml", "go.mod", "pom.xml", "composer.json",
                       "Gemfile", "pubspec.yaml", "Package.swift", "CMakeLists.txt", "mix.exs",
                       "stack.yaml", "Demo.csproj"):
            self.write(marker, "")
        languages = {item["language"] for item in self.discover()["ecosystems"]}
        self.assertTrue({"python", "rust", "go", "java", "php", "ruby", "dart/flutter",
                         "swift", "c/c++", "elixir", "haskell", "dotnet"}.issubset(languages))

    def test_rust_and_go_profiles(self):
        self.write("Cargo.toml", "[package]\nname='demo'\n")
        self.write("src/lib.rs", "")
        self.write("go.mod", "module example.invalid/demo\n")
        self.write("pkg/thing_test.go", "")
        self.assertEqual({p["language"] for p in self.discover()["profiles"]}, {"rust", "go"})
    def test_maven_and_gradle_profiles(self):
        self.write("pom.xml", "<project/>")
        self.write("build.gradle.kts", "plugins {}")
        self.write("src/test/java/DemoTest.java", "")
        self.assertEqual({p["language"] for p in self.discover()["profiles"]}, {"java/maven", "java/gradle"})
    def test_dotnet_profile(self):
        self.write("Demo.csproj", "<Project/>")
        self.write("DemoTests.cs", "")
        self.assertEqual(self.discover()["profiles"][0]["command"], ["dotnet", "test"])
    def test_unknown_project_returns_empty_profiles(self):
        self.write("notes.txt", "hello")
        self.assertEqual(self.discover()["profiles"], [])
    def test_changed_path_escape_is_rejected(self):
        with self.assertRaises(WorkspaceError):
            self.discover(["../outside.txt"])

if __name__ == "__main__":
    unittest.main()
