"""Loopback-only local dashboard for human-controlled project execution."""
from __future__ import annotations

import html
import json
import secrets
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .execution import ExecutionEngine, HandlerRegistry
from .visualization import render_svg


def _page(project_dir: Path, engine: ExecutionEngine, registry: HandlerRegistry,
          token: str, message: str = "") -> str:
    queue = json.loads(engine.queue_path.read_text(encoding="utf-8"))
    plan_path = project_dir / "system1" / "initial_plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    svg = render_svg(plan, queue)
    handlers = registry.handler_ids()
    cards = []
    for task in queue.get("tasks", []):
        task_id = str(task.get("task_id", ""))
        status = str(task.get("status", "unknown"))
        title = html.escape(str(task.get("title", task_id)))
        safe_id = html.escape(task_id)
        fields = (
            f'<input type="hidden" name="csrf" value="{token}">'
            f'<input type="hidden" name="task_id" value="{safe_id}">'
        )
        actions = []
        if status == "awaiting_approval":
            if handlers:
                options = "".join(
                    f'<option value="{html.escape(handler, quote=True)}">'
                    f'{html.escape(handler)}</option>' for handler in handlers
                )
                actions.append(
                    '<form method="post">' + fields +
                    '<input type="hidden" name="action" value="approve">'
                    '<label>Handler <select name="handler_id">' + options + '</select></label>'
                    '<label>تأییدکننده <input name="approved_by" required></label>'
                    '<button>تأیید وظیفه</button></form>'
                )
            else:
                actions.append('<p class="muted">هیچ Handler مورداعتمادی ثبت نشده است.</p>')
        elif status == "approved":
            actions.append(
                '<form method="post">' + fields +
                '<input type="hidden" name="action" value="run">'
                '<button>اجرای وظیفهٔ تأییدشده</button></form>'
            )
        elif status == "awaiting_review":
            for decision, label in (("accept", "تأیید نتیجه"), ("reject", "رد نتیجه")):
                actions.append(
                    '<form method="post">' + fields +
                    '<input type="hidden" name="action" value="review">'
                    f'<input type="hidden" name="decision" value="{decision}">'
                    '<label>بازبین <input name="reviewed_by" required></label>'
                    '<label>دلیل <input name="reason" required></label>'
                    f'<button>{label}</button></form>'
                )
        elif status == "failed":
            actions.append(
                '<form method="post">' + fields +
                '<input type="hidden" name="action" value="retry">'
                '<label>درخواست‌کننده <input name="requested_by" required></label>'
                '<label>دلیل تلاش مجدد <input name="reason" required></label>'
                '<button>درخواست تلاش مجدد</button></form>'
            )
        detail_data = {
            "روش اجرا": task.get("method", []),
            "ورودی‌ها": task.get("inputs", []),
            "خروجی‌های مورد انتظار": task.get("expected_outputs", []),
            "معیارهای پذیرش": task.get("acceptance_criteria", []),
            "خروجی واقعی": task.get("outputs"),
            "ارزیابی": task.get("evaluation"),
            "بازیابی": task.get("recovery"),
            "خطا": task.get("error"),
            "بازبینی انسانی": task.get("human_review"),
        }
        details = (
            '<details><summary>جزئیات و شواهد وظیفه</summary><pre>' +
            html.escape(json.dumps(detail_data, ensure_ascii=False, indent=2)) +
            '</pre></details>'
        )
        result_file = task.get("result_file")
        result = (
            f'<p class="muted">خروجی: {html.escape(str(result_file))}</p>'
            if result_file else ""
        )
        dependencies = ", ".join(str(x) for x in task.get("dependencies", [])) or "ندارد"
        cards.append(
            '<article class="task"><div class="task-head">'
            f'<div><small>{safe_id}</small><h2>{title}</h2></div>'
            f'<span class="status">{html.escape(status)}</span></div>'
            f'<p class="muted">پیش‌نیازها: {html.escape(dependencies)}</p>'
            f'{details}{result}<div class="actions">{"".join(actions)}</div></article>'
        )
    body = "".join(cards) or '<p>هنوز وظیفه‌ای در صف وجود ندارد.</p>'
    status_message = f'<p class="message">{html.escape(message)}</p>' if message else ""
    return f"""<!doctype html>
<html lang="fa" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>داشبورد ایکاروس</title>
<style>
:root{{color-scheme:light dark;font-family:system-ui,sans-serif}}
body{{margin:0;background:#101522;color:#edf2ff}}
header{{padding:24px max(20px,calc((100vw - 1100px)/2));background:#192235}}
main{{max-width:1100px;margin:24px auto;padding:0 18px}}
h1{{margin:0 0 8px}}h2{{font-size:1.05rem;margin:5px 0}}
small,.muted{{color:#a9b5ca}}.message{{padding:12px;background:#243b31;border-radius:10px}}
.task{{background:#1a2436;border:1px solid #33415a;border-radius:14px;padding:16px;margin:14px 0}}
.task-head{{display:flex;justify-content:space-between;gap:12px;align-items:center}}
.status{{background:#34304d;border-radius:20px;padding:6px 12px;font-size:.85rem}}
.actions{{display:flex;flex-wrap:wrap;gap:10px;margin-top:14px}}
form{{display:flex;flex-wrap:wrap;gap:8px;align-items:end;background:#111a29;padding:10px;border-radius:10px}}
label{{display:grid;gap:4px;font-size:.85rem}}input,select,button{{font:inherit;border-radius:8px;padding:8px;border:1px solid #50617e}}
button{{background:#6554a4;color:white;cursor:pointer}}button:hover{{filter:brightness(1.15)}}
.graph{{overflow:auto;background:#fff;color:#111;border-radius:12px;padding:10px}}
.graph svg{{max-width:100%;height:auto}}summary{{cursor:pointer;padding:12px}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#111a29;padding:12px;border-radius:10px}}
</style></head><body><header><h1>ایکاروس · داشبورد پروژه</h1>
<div>شناسهٔ پروژه: {html.escape(str(queue.get("project_id", "")))}</div></header>
<main>{status_message}<details class="graph"><summary>نمایش نمودار زندهٔ برنامه و وضعیت وظایف</summary>{svg}</details>
<h2>صف اجرا ({len(queue.get("tasks", []))} وظیفه)</h2>{body}
<p class="muted">این داشبورد فقط روی رایانهٔ محلی در دسترس است. اجرای هر وظیفه همچنان به تأیید انسانی و Handler ثبت‌شده نیاز دارد.</p>
</main></body></html>"""


def create_dashboard_server(
    project_dir: Path,
    registry: HandlerRegistry,
    *,
    evaluator: Any = None,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> HTTPServer:
    """Create a loopback-only server. The caller owns its lifetime and shutdown."""
    if host != "127.0.0.1":
        raise ValueError("The ICARUS dashboard may only bind to 127.0.0.1")
    root = Path(project_dir).resolve()
    engine = ExecutionEngine(root, registry, evaluator=evaluator)
    token = secrets.token_urlsafe(32)
    server = HTTPServer((host, port), None)
    server.dashboard_message = ""

    class DashboardHandler(BaseHTTPRequestHandler):
        def _respond(self, status: int, body: str) -> None:
            data = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            if urlparse(self.path).path != "/":
                self._respond(404, "Not found")
                return
            try:
                page = _page(root, engine, registry, token, server.dashboard_message)
                server.dashboard_message = ""
                self._respond(200, page)
            except Exception as exc:
                self._respond(500, f"<pre>{html.escape(type(exc).__name__ + ': ' + str(exc))}</pre>")

        def do_POST(self) -> None:
            if urlparse(self.path).path != "/":
                self._respond(404, "Not found")
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 16384:
                    raise ValueError("Invalid form size")
                form = parse_qs(self.rfile.read(length).decode("utf-8"), strict_parsing=True)
                values = {key: items[-1] for key, items in form.items() if items}
                if not secrets.compare_digest(values.get("csrf", ""), token):
                    raise PermissionError("Invalid dashboard form token")
                action = values.get("action")
                task_id = values.get("task_id", "")
                if action == "approve":
                    engine.approve(
                        task_id, values.get("handler_id", ""),
                        approved_by=values.get("approved_by", ""),
                    )
                    message = f"وظیفهٔ {task_id} تأیید شد."
                elif action == "run":
                    task = engine.run(task_id)
                    message = f"اجرای {task_id} با وضعیت {task.get('status')} پایان یافت."
                elif action == "review":
                    task = engine.review(
                        task_id, decision=values.get("decision", ""),
                        reviewed_by=values.get("reviewed_by", ""),
                        reason=values.get("reason", ""),
                    )
                    message = f"بازبینی {task_id}: {task.get('status')}."
                elif action == "retry":
                    task = engine.retry(
                        task_id, requested_by=values.get("requested_by", ""),
                        reason=values.get("reason", ""),
                    )
                    message = f"درخواست تلاش مجدد {task_id} ثبت شد."
                else:
                    raise ValueError("Unknown dashboard action")
                server.dashboard_message = message
                self.send_response(303)
                self.send_header("Location", "/")
                self.send_header("Content-Length", "0")
                self.end_headers()
            except Exception as exc:
                self._respond(400, f"<pre>{html.escape(type(exc).__name__ + ': ' + str(exc))}</pre>")

        def log_message(self, format: str, *args: Any) -> None:
            return

    server.RequestHandlerClass = DashboardHandler
    return server


def serve_dashboard(project_dir: Path, registry: HandlerRegistry, *,
                    evaluator: Any = None, port: int = 8765) -> None:
    server = create_dashboard_server(
        project_dir, registry, evaluator=evaluator, port=port
    )
    print(f"ICARUS dashboard: http://127.0.0.1:{port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
