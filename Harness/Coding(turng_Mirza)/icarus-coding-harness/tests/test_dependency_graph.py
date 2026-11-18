import unittest

from icarus_harness.dependency_graph import additional_dependency_edges


def entry(text):
    return {"raw_text": text, "text": text}


class AdditionalDependencyGraphTests(unittest.TestCase):
    def test_go_module_local_imports_resolve_aliases_and_ignore_external_packages(self):
        entries = {
            "go.mod": entry("module example.com/demo\n\ngo 1.22\n"),
            "cmd/app/main.go": entry('''package main
import (
    "fmt"
    parser "example.com/demo/internal/parser"
    _ "example.com/demo/internal/register"
    "github.com/external/pkg"
)
func main() { fmt.Println(parser.Parse("x")) }
'''),
            "internal/parser/parser.go": entry("package parser\nfunc Parse(s string) string { return s }\n"),
            "internal/register/register.go": entry("package register\n"),
            "internal/parser/parser_test.go": entry("package parser\n"),
        }
        edges = additional_dependency_edges(entries)
        self.assertIn({"source": "cmd/app/main.go", "target": "internal/parser/parser.go", "kind": "go_import"}, edges)
        self.assertIn({"source": "cmd/app/main.go", "target": "internal/register/register.go", "kind": "go_import"}, edges)
        self.assertFalse(any(edge["target"].endswith("_test.go") for edge in edges))
        self.assertFalse(any("github.com" in edge["target"] for edge in edges))

    def test_go_nested_module_uses_longest_module_path(self):
        entries = {
            "go.mod": entry("module example.com/demo\n"),
            "tools/go.mod": entry("module example.com/demo/tools\n"),
            "cmd/main.go": entry('package main\nimport "example.com/demo/tools/format"\n'),
            "tools/format/format.go": entry("package format\n"),
        }
        edges = additional_dependency_edges(entries)
        self.assertIn({"source": "cmd/main.go", "target": "tools/format/format.go", "kind": "go_import"}, edges)

    def test_go_does_not_guess_external_or_unresolved_imports(self):
        entries = {
            "go.mod": entry("module example.com/demo\n"),
            "main.go": entry('package main\nimport ("fmt")\n'),
        }
        self.assertEqual(additional_dependency_edges(entries), [])

    def test_rust_mod_and_crate_use_edges_resolve_local_modules(self):
        entries = {
            "Cargo.toml": entry("[package]\nname='demo'\n"),
            "src/lib.rs": entry("pub mod parser;\npub mod lexer;\n"),
            "src/parser.rs": entry("pub mod token;\nuse crate::lexer::scan;\n"),
            "src/parser/token.rs": entry("pub fn parse() {}\n"),
            "src/lexer.rs": entry("pub fn scan() {}\n"),
        }
        edges = additional_dependency_edges(entries)
        self.assertIn({"source": "src/lib.rs", "target": "src/parser.rs", "kind": "rust_mod"}, edges)
        self.assertIn({"source": "src/parser.rs", "target": "src/parser/token.rs", "kind": "rust_mod"}, edges)
        self.assertIn({"source": "src/parser.rs", "target": "src/lexer.rs", "kind": "rust_use"}, edges)

    def test_rust_super_use_and_path_attribute_resolve(self):
        entries = {
            "src/lib.rs": entry('#[path = "shared/parser.rs"]\npub mod parser;\n'),
            "src/shared/parser.rs": entry("pub mod token;\n"),
            "src/shared/parser/token.rs": entry("use super::normalize;\n"),
        }
        edges = additional_dependency_edges(entries)
        self.assertIn({"source": "src/lib.rs", "target": "src/shared/parser.rs", "kind": "rust_mod"}, edges)
        self.assertIn({"source": "src/shared/parser.rs", "target": "src/shared/parser/token.rs", "kind": "rust_mod"}, edges)
        self.assertIn({"source": "src/shared/parser/token.rs", "target": "src/shared/parser.rs", "kind": "rust_use"}, edges)

    def test_rust_external_unresolved_and_nested_indented_modules_are_not_inferred(self):
        entries = {
            "src/lib.rs": entry("use serde::Serialize;\nmod missing;\nmod inline {\n    mod not_external;\n}\n"),
        }
        self.assertEqual(additional_dependency_edges(entries), [])


if __name__ == "__main__":
    unittest.main()
