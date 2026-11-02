"""Offline visual exports for project plans and execution queues."""
from __future__ import annotations

import html
import json
import hashlib
from pathlib import Path
from typing import Any


def _node_key(task_id: str) -> str:
    return "n_" + hashlib.sha1(task_id.encode("utf-8")).hexdigest()[:12]


def _label(value: Any, limit: int = 26) -> list[str]:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return [text]
    words = text.split(" ")
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = (current + " " + word).strip()
        if len(candidate) > limit and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines[:3]


def _flatten(plan: dict[str, Any], queue: dict[str, Any]):
    statuses = {item.get("task_id"): item.get("status", "awaiting_approval")
                for item in queue.get("tasks", [])}
    nodes: dict[str, dict[str, Any]] = {}
    roots = plan.get("tasks", [])

    def visit(task: dict[str, Any], parent: str | None, depth: int) -> int:
        task_id = str(task["id"])
        children = task.get("children", [])
        child_spans = []
        cursor = 0
        for child in children:
            span = visit(child, task_id, depth + 1)
            child_spans.append((cursor, cursor + span))
            cursor += span
        span = max(cursor, 1)
        center = (span - 1) / 2
        nodes[task_id] = {
            "id": task_id, "title": str(task.get("title", task_id)),
            "depth": depth, "span": span, "center": center,
            "parent": parent, "status": statuses.get(task_id,
                "planning_blocked" if task.get("planning_blocked") else
                "planned" if children else "awaiting_approval"),
            "children": [str(child["id"]) for child in children],
        }
        return span

    total = 0
    for root in roots:
        total += visit(root, None, 0)
    # Recompute absolute leaf slots from the tree to keep sibling subtrees separated.
    cursor = 0

    def place(task: dict[str, Any], start: int):
        task_id = str(task["id"])
        children = task.get("children", [])
        if children:
            child_start = start
            for child in children:
                child_start = place(child, child_start)
            nodes[task_id]["x_slot"] = (start + child_start - 1) / 2
            return child_start
        nodes[task_id]["x_slot"] = float(start)
        return start + 1

    for root in roots:
        cursor = place(root, cursor)

    dependencies = []
    for task in queue.get("tasks", []):
        target = task.get("task_id")
        for dependency in task.get("dependencies", []):
            if dependency in nodes and target in nodes:
                dependencies.append((dependency, target))
    return nodes, dependencies, max(total, 1)


def render_svg(plan: dict[str, Any], queue: dict[str, Any]) -> str:
    nodes, dependencies, total = _flatten(plan, queue)
    node_w, node_h, gap_x, gap_y = 236, 92, 286, 166
    margin_x, margin_y = 150, 100
    max_depth = max((node["depth"] for node in nodes.values()), default=0)
    width = max(900, int((total - 1) * gap_x + node_w + 2 * margin_x))
    height = max(360, int(max_depth * gap_y + node_h + 2 * margin_y))
    positions = {
        task_id: (margin_x + node["x_slot"] * gap_x, margin_y + node["depth"] * gap_y)
        for task_id, node in nodes.items()
    }
    palette = {
        "completed": ("#dcfce7", "#15803d"),
        "failed": ("#fee2e2", "#b91c1c"),
        "running": ("#dbeafe", "#1d4ed8"),
        "awaiting_review": ("#fef3c7", "#a16207"),
        "awaiting_approval": ("#ede9fe", "#6d28d9"),
        "planning_blocked": ("#f3f4f6", "#4b5563"),
        "planned": ("#e0f2fe", "#0369a1"),
    }
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" role="img" aria-label="نمودار گرافیکی پروژه" ',
        'viewBox="0 0 %d %d" width="%d" height="%d">' % (width, height, width, height),
        '<defs><marker id="arrow" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto"><path d="M0,0 L0,6 L9,3 z" fill="#64748b"/></marker>',
        '<marker id="dep-arrow" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto"><path d="M0,0 L0,6 L9,3 z" fill="#c084fc"/></marker></defs>',
        '<rect width="100%" height="100%" rx="24" fill="#f8fafc"/>',
    ]
    # Parent-child hierarchy edges.
    for task_id, node in nodes.items():
        parent = node["parent"]
        if parent and parent in positions:
            px, py = positions[parent]
            x, y = positions[task_id]
            sx, sy = px + node_w / 2, py + node_h
            ex, ey = x + node_w / 2, y
            mid = (sy + ey) / 2
            parts.append('<path d="M %.1f %.1f C %.1f %.1f, %.1f %.1f, %.1f %.1f" fill="none" stroke="#94a3b8" stroke-width="2.5" marker-end="url(#arrow)"/>' % (sx, sy, sx, mid, ex, mid, ex, ey))
    # Dependency edges are visually distinct from hierarchy edges.
    for source, target in dependencies:
        sx, sy = positions[source]
        tx, ty = positions[target]
        start_x, start_y = sx + node_w / 2, sy + node_h / 2
        end_x, end_y = tx + node_w / 2, ty + node_h / 2
        bend = max(55, abs(end_x - start_x) * 0.28)
        parts.append('<path d="M %.1f %.1f C %.1f %.1f, %.1f %.1f, %.1f %.1f" fill="none" stroke="#c084fc" stroke-width="2.5" stroke-dasharray="7 6" marker-end="url(#dep-arrow)"><title>وابستگی: %s ← %s</title></path>' % (start_x, start_y, start_x, start_y - bend, end_x, end_y - bend, end_x, end_y, html.escape(source), html.escape(target)))
    for task_id, node in nodes.items():
        x, y = positions[task_id]
        fill, stroke = palette.get(node["status"], ("#f1f5f9", "#475569"))
        parts.append('<g><rect x="%.1f" y="%.1f" width="%d" height="%d" rx="16" fill="%s" stroke="%s" stroke-width="2.2"/>' % (x, y, node_w, node_h, fill, stroke))
        parts.append('<text x="%.1f" y="%.1f" text-anchor="middle" direction="rtl" unicode-bidi="plaintext" font-family="Vazirmatn, Noto Sans Arabic, sans-serif" font-size="15" font-weight="700" fill="#0f172a">' % (x + node_w / 2, y + 29))
        for index, line in enumerate(_label(node["title"])):
            parts.append('<tspan x="%.1f" dy="%s">%s</tspan>' % (x + node_w / 2, "0" if index == 0 else "19", html.escape(line)))
        parts.append('</text><text x="%.1f" y="%.1f" text-anchor="middle" direction="rtl" font-family="Vazirmatn, Noto Sans Arabic, sans-serif" font-size="11" fill="%s">%s</text>' % (x + node_w / 2, y + 78, stroke, html.escape(node["status"])))
        parts.append('<title>%s — %s</title></g>' % (html.escape(task_id), html.escape(node["title"])))
    parts.append('</svg>')
    return "".join(parts)


def render_mermaid(plan: dict[str, Any], queue: dict[str, Any]) -> str:
    nodes, dependencies, _ = _flatten(plan, queue)
    lines = ["flowchart TD"]
    for task_id, node in nodes.items():
        label = (node["title"].replace("&", "&amp;").replace('"', "&quot;")
                 .replace("[", "#91;").replace("]", "#93;")
                 .replace("|", "#124;").replace("\n", " "))
        lines.append('  %s["%s"]' % (_node_key(task_id), label))
    for task_id, node in nodes.items():
        if node["parent"]:
            lines.append("  %s --> %s" % (_node_key(node["parent"]), _node_key(task_id)))
    for source, target in dependencies:
        lines.append("  %s -. وابستگی .-> %s" % (_node_key(source), _node_key(target)))
    lines.extend([
        "  classDef completed fill:#dcfce7,stroke:#15803d,color:#14532d",
        "  classDef failed fill:#fee2e2,stroke:#b91c1c,color:#7f1d1d",
        "  classDef running fill:#dbeafe,stroke:#1d4ed8,color:#1e3a8a",
        "  classDef awaiting_review fill:#fef3c7,stroke:#a16207,color:#78350f",
        "  classDef awaiting_approval fill:#ede9fe,stroke:#6d28d9,color:#4c1d95",
    ])
    for task_id, node in nodes.items():
        if node["status"] in {"completed", "failed", "running", "awaiting_review", "awaiting_approval"}:
            lines.append("  class %s %s" % (_node_key(task_id), node["status"]))
    return "\n".join(lines) + "\n"


def render_html(plan: dict[str, Any], queue: dict[str, Any]) -> str:
    svg = render_svg(plan, queue)
    project_name = html.escape(str(plan.get("objective", plan.get("project_id", "ICARUS"))))
    return """<!doctype html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>نقشهٔ پروژه — %s</title>
<style>
:root{color-scheme:light;font-family:Vazirmatn,"Noto Sans Arabic",Tahoma,sans-serif;background:#eef2ff;color:#172033}
*{box-sizing:border-box}body{margin:0;padding:28px;background:linear-gradient(135deg,#eef2ff,#f8fafc 55%%,#f5f3ff)}
main{max-width:1500px;margin:auto}.top{display:flex;align-items:center;justify-content:space-between;gap:18px;flex-wrap:wrap}
h1{font-size:clamp(22px,3vw,34px);margin:0 0 8px}.sub{color:#64748b;margin:0 0 22px}
.toolbar{display:flex;gap:8px}.toolbar button{border:1px solid #cbd5e1;background:#fff;border-radius:12px;padding:9px 14px;font:inherit;cursor:pointer}
.canvas{background:#fff;border:1px solid #e2e8f0;border-radius:22px;box-shadow:0 18px 55px #33415518;overflow:auto;padding:16px}
svg{max-width:none;height:auto}.legend{display:flex;gap:12px;flex-wrap:wrap;margin-top:18px;color:#475569;font-size:13px}
.legend span{display:inline-flex;align-items:center;gap:7px}.dot{width:11px;height:11px;border-radius:50%;display:inline-block}
.note{margin-top:16px;color:#64748b;font-size:13px}
</style></head>
<body><main><div class="top"><div><h1>نقشهٔ گرافیکی پروژه</h1><p class="sub">%s</p></div>
<div class="toolbar"><button onclick="zoom(1.15)">بزرگ‌نمایی +</button><button onclick="zoom(.87)">کوچک‌نمایی −</button><button onclick="resetZoom()">بازنشانی</button></div></div>
<div class="canvas" id="canvas">%s</div>
<div class="legend"><span><i class="dot" style="background:#ede9fe"></i>در انتظار تأیید</span><span><i class="dot" style="background:#fef3c7"></i>نیازمند بازبینی</span><span><i class="dot" style="background:#dcfce7"></i>تکمیل‌شده</span><span><i class="dot" style="background:#fee2e2"></i>ناموفق</span><span>خط پیوسته: ساختار وظایف</span><span>خط‌چین بنفش: وابستگی</span></div>
<p class="note">این نمودار از داده‌های واقعی برنامه و صف اجرا ساخته شده است؛ وضعیت‌ها با تغییر صف در اجرای بعدی دوباره تولید می‌شوند.</p>
</main><script>
const svg=document.querySelector('.canvas svg');let scale=1;
function zoom(f){scale=Math.max(.35,Math.min(2.5,scale*f));svg.style.width=(svg.viewBox.baseVal.width*scale)+'px'}
function resetZoom(){scale=1;svg.style.width=''}
</script></body></html>""" % (project_name, project_name, svg)


def export_project_graph(project_dir: Path, plan: dict[str, Any],
                         queue: dict[str, Any]) -> dict[str, str]:
    target = Path(project_dir) / "visualization"
    target.mkdir(parents=True, exist_ok=True)
    outputs = {
        "svg": target / "project_graph.svg",
        "html": target / "project_graph.html",
        "mermaid": target / "project_graph.mmd",
    }
    outputs["svg"].write_text(render_svg(plan, queue), encoding="utf-8")
    outputs["html"].write_text(render_html(plan, queue), encoding="utf-8")
    outputs["mermaid"].write_text(render_mermaid(plan, queue), encoding="utf-8")
    return {key: str(path) for key, path in outputs.items()}
