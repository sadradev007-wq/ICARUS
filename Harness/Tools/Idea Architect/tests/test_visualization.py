import tempfile
import unittest
from pathlib import Path

from idea_architect.orchestrator import ProjectOrchestrator
from idea_architect.crash_recovery import DurableJournal
from idea_architect.visualization import export_project_graph, render_html, render_mermaid, render_svg


def leaf(task_id, title, dependencies=None):
    return {
        "id": task_id, "title": title, "description": "A bounded task",
        "priority": "normal", "status": "pending", "is_leaf": True,
        "method": ["produce output"], "inputs": ["source"],
        "expected_outputs": ["artifact"], "acceptance_criteria": ["artifact exists"],
        "children": [], "dependencies": dependencies or []
    }


def sample_plan():
    return {
        "protocol": "ITP-1.0", "project_id": "graph-test",
        "objective": "ساخت یک پروژهٔ نمونه",
        "tasks": [{
            "id": "ROOT", "title": "پروژهٔ اصلی", "description": "Root",
            "priority": "high", "status": "pending", "children": [
                leaf("A", "تحلیل نیازمندی‌ها"),
                leaf("B", "ساخت خروجی", ["A"])
            ], "dependencies": []
        }]
    }


class GraphVisualizationTests(unittest.TestCase):
    def setUp(self):
        self.plan = sample_plan()
        self.queue = {
            "project_id": "graph-test",
            "tasks": [
                {"task_id": "A", "status": "completed", "dependencies": []},
                {"task_id": "B", "status": "awaiting_approval", "dependencies": ["A"]}
            ]
        }

    def test_svg_contains_tree_nodes_and_dependency_edge(self):
        svg = render_svg(self.plan, self.queue)
        self.assertIn("پروژهٔ اصلی", svg)
        self.assertIn("تحلیل نیازمندی‌ها", svg)
        self.assertIn("stroke-dasharray", svg)
        self.assertIn("#c084fc", svg)

    def test_mermaid_contains_hierarchy_and_dependency(self):
        graph = render_mermaid(self.plan, self.queue)
        self.assertIn("flowchart TD", graph)
        self.assertIn("-. وابستگی .->", graph)
        self.assertIn("classDef completed", graph)

    def test_html_is_standalone_rtl_with_zoom_controls(self):
        page = render_html(self.plan, self.queue)
        self.assertIn('<html lang="fa" dir="rtl">', page)
        self.assertIn("<svg", page)
        self.assertIn("function zoom", page)
        self.assertNotIn("cdn.", page)

    def test_export_writes_three_formats(self):
        with tempfile.TemporaryDirectory() as directory:
            outputs = export_project_graph(Path(directory), self.plan, self.queue)
            self.assertEqual(set(outputs), {"svg", "html", "mermaid"})
            for path in outputs.values():
                self.assertTrue(Path(path).is_file())
                self.assertGreater(Path(path).stat().st_size, 100)

    def test_project_creation_returns_graph_paths(self):
        class Planner:
            def create_plan(self, idea, project_id):
                plan = sample_plan()
                plan["project_id"] = project_id
                plan["objective"] = idea
                return plan
        with tempfile.TemporaryDirectory() as directory:
            result = ProjectOrchestrator(Path(directory), Planner()).create_project(
                "نمودار آزمایشی", "project-graph"
            )
            self.assertIn("visualization", result)
            self.assertTrue(Path(result["visualization"]["html"]).is_file())
            journal = DurableJournal(
                Path(directory) / "project-graph" / "execution" / "event_journal.jsonl"
            )
            event_types = [event["event_type"] for event in journal.read_events()]
            self.assertIn("plan_snapshot", event_types)
            self.assertIn("queue_snapshot", event_types)


if __name__ == "__main__":
    unittest.main()
