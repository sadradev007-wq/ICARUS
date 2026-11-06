"""Local-first Task Companion web form and task list.

The service binds to loopback only. Creating a task is a direct, explicit user
action through a CSRF-protected form; no task is created by page rendering.
"""
from __future__ import annotations

import html
import json
import secrets
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from .task_companion import TaskStore

PRIORITY_LABELS = {
    "critical": "بحرانی",
    "high": "بالا",
    "normal": "معمولی",
    "low": "پایین",
}
STATUS_LABELS = {
    "inbox": "صندوق ورودی",
    "next": "بعدی",
    "in_progress": "در حال انجام",
    "waiting": "منتظر",
    "completed": "انجام‌شده",
    "archived": "بایگانی",
}


def _e(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def _task_api_payload(store: TaskStore) -> dict[str, Any]:
    """Build the versioned, read-only snapshot consumed by local ICARUS surfaces."""
    tasks = store.list_tasks()
    events = store.pending_execution_events()
    public_tasks = [
        {
            "id": task["id"],
            "title": task["title"],
            "description": task.get("description", ""),
            "priority": task["priority"],
            "status": task["status"],
            "due_at": task.get("due_at"),
            "project_id": task.get("project_id"),
            "parent_id": task.get("parent_id"),
            "tags": [tag for tag in task.get("tags", []) if isinstance(tag, str)],
            "created_at": task["created_at"],
            "updated_at": task["updated_at"],
        }
        for task in tasks
    ]
    public_events = [
        {
            "event_id": event["event_id"],
            "task_id": event["task_id"],
            "run_status": event["run_status"],
            "proposed_status": event["proposed_status"],
            "summary": event["summary"],
            "created_at": event["created_at"],
        }
        for event in events
    ]
    return {
        "schema": "icarus.task-api.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tasks": public_tasks,
        "pending_execution_events": public_events,
        "counts": {
            "active_tasks": len(public_tasks),
            "critical_or_high_tasks": sum(
                task["priority"] in {"critical", "high"} for task in public_tasks
            ),
            "pending_execution_events": len(public_events),
        },
    }


def _page(store: TaskStore, token: str, *, message: str = "",
          error: str = "", values: dict[str, str] | None = None) -> str:
    values = values or {}
    tasks = store.list_tasks(include_closed=True)
    events = store.pending_execution_events()
    event_rows = []
    for event in events:
        event_id = _e(event.get("event_id"))
        task_id = _e(event.get("task_id"))
        proposed = STATUS_LABELS.get(event.get("proposed_status"), event.get("proposed_status"))
        summary = _e(event.get("summary"))
        event_rows.append(
            '<article class="task feedback"><div class="task-title"><div><h3>پیشنهاد نتیجهٔ اجرای هارنس</h3>'
            f'<p>کار: {task_id} · وضعیت پیشنهادی: {_e(proposed)}</p><p>{summary}</p></div></div>'
            '<div class="actions">'
            '<form method="post" action="/events/apply">'
            f'<input type="hidden" name="csrf" value="{_e(token)}">'
            f'<input type="hidden" name="event_id" value="{event_id}">'
            '<button type="submit">پذیرش پیشنهاد و به‌روزرسانی کار</button></form>'
            '<form method="post" action="/events/reject">'
            f'<input type="hidden" name="csrf" value="{_e(token)}">'
            f'<input type="hidden" name="event_id" value="{event_id}">'
            '<button type="submit" class="secondary">رد پیشنهاد</button></form>'
            '</div></article>'
        )
    feedback_section = (
        '<section class="panel"><h2>بازخوردهای در انتظار تأیید (' + str(len(events)) + ')</h2>'
        + "".join(event_rows) + '</section>'
    ) if events else ""
    rows = []
    for task in tasks:
        priority = PRIORITY_LABELS.get(task["priority"], task["priority"])
        status = STATUS_LABELS.get(task["status"], task["status"])
        due = task.get("due_at") or "بدون موعد"
        project = task.get("project_id") or "بدون پروژه"
        rows.append(
            '<article class="task">'
            '<div class="task-title"><div><h3>' + _e(task["title"]) + '</h3>'
            '<p>' + _e(task.get("description")) + '</p></div>'
            '<span class="priority ' + _e(task["priority"]) + '">' + _e(priority) + '</span></div>'
            '<div class="meta"><span>' + _e(status) + '</span><span>' + _e(project) +
            '</span><span>' + _e(due) + '</span></div></article>'
        )
    task_list = "".join(rows) or '<p class="empty">هنوز کاری ثبت نشده است. اولین کار را از فرم بالا اضافه کن.</p>'
    notice = ('<div class="notice success">' + _e(message) + '</div>') if message else ""
    error_box = ('<div class="notice error">' + _e(error) + '</div>') if error else ""
    selected = lambda name, value: " selected" if values.get(name, "normal" if name == "priority" else "inbox") == value else ""
    return f"""<!doctype html>
<html lang="fa" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ایکاروس · همراه وظایف</title>
<style>
:root{{color-scheme:dark;font-family:Vazirmatn,IRANSans,Tahoma,system-ui,sans-serif}}
*{{box-sizing:border-box}}body{{margin:0;background:#10131d;color:#edf0fa}}
header{{padding:24px max(20px,calc((100vw - 1000px)/2));background:#191e2b;border-bottom:1px solid #30364a}}
header small,.muted,.meta{{color:#9ba4bb}}main{{max-width:1000px;margin:28px auto;padding:0 18px}}
h1{{font-size:1.5rem;margin:0 0 6px}}h2{{font-size:1.15rem;margin:0 0 18px}}
.panel{{background:#191e2b;border:1px solid #30364a;border-radius:18px;padding:22px;margin-bottom:24px}}
form{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}
.field{{display:grid;gap:7px}}.wide{{grid-column:1/-1}}
label{{font-size:.9rem;color:#c5cbe0}}
input,textarea,select{{width:100%;font:inherit;color:#f2f2fa;background:#101521;border:1px solid #3b4560;border-radius:10px;padding:11px;min-width:0}}
textarea{{min-height:90px;resize:vertical}}
input:focus,textarea:focus,select:focus{{outline:2px solid #9b7bea;outline-offset:2px}}
button{{font:inherit;border:0;border-radius:10px;background:#8061c7;color:white;padding:12px 18px;cursor:pointer;font-weight:700}}
button:hover{{filter:brightness(1.12)}}.submit{{grid-column:1/-1;justify-self:start;min-width:170px}}
.notice{{padding:12px 15px;border-radius:10px;margin:0 0 16px}}.success{{background:#18382f;color:#b8f3d9}}.error{{background:#47262e;color:#ffd0d5}}
.task{{background:#191e2b;border:1px solid #30364a;border-radius:14px;padding:16px;margin:12px 0}}
.feedback{{border-color:#8061c7}}.actions{{display:flex;flex-wrap:wrap;gap:10px;margin-top:14px}}
.actions form{{display:block;background:transparent;padding:0}}.secondary{{background:#444b5e}}
.task-title{{display:flex;align-items:start;justify-content:space-between;gap:12px}}h3{{margin:0 0 7px;font-size:1rem}}.task p{{margin:0;color:#aab2c8;white-space:pre-wrap;overflow-wrap:anywhere}}
.priority{{white-space:nowrap;border-radius:30px;padding:5px 10px;font-size:.8rem;background:#33384a}}
.critical{{background:#542d3c;color:#ffbdca}}.high{{background:#514126;color:#ffe0a1}}.normal{{background:#30364a;color:#d4d9e8}}.low{{background:#263e45;color:#b5e9ec}}
.meta{{display:flex;flex-wrap:wrap;gap:16px;margin-top:14px;font-size:.8rem}}.empty{{color:#aab2c8}}
@media(max-width:640px){{form{{grid-template-columns:1fr}}.wide,.submit{{grid-column:1}}.task-title{{flex-direction:column}}}}
</style></head><body>
<header><h1>ICARUS · Task Companion</h1><small>ثبت و پیگیری کارهای شخصی و پروژه‌ای</small></header>
<main>{notice}{error_box}{feedback_section}
<section class="panel"><h2>＋ افزودن کار جدید</h2>
<form method="post" action="/tasks">
<input type="hidden" name="csrf" value="{_e(token)}">
<div class="field wide"><label for="title">عنوان کار <strong>*</strong></label>
<input id="title" name="title" maxlength="200" required autofocus placeholder="مثلاً: طراحی فرم ثبت کار در ایکاروس" value="{_e(values.get('title'))}"></div>
<div class="field wide"><label for="description">توضیحات</label>
<textarea id="description" name="description" maxlength="5000" placeholder="خروجی مورد انتظار، جزئیات یا یادداشت‌های لازم...">{_e(values.get('description'))}</textarea></div>
<div class="field"><label for="priority">اولویت</label><select id="priority" name="priority">
<option value="critical"{selected('priority','critical')}>بحرانی</option>
<option value="high"{selected('priority','high')}>بالا</option>
<option value="normal"{selected('priority','normal')}>معمولی</option>
<option value="low"{selected('priority','low')}>پایین</option></select></div>
<div class="field"><label for="status">وضعیت اولیه</label><select id="status" name="status">
<option value="inbox"{selected('status','inbox')}>صندوق ورودی</option>
<option value="next"{selected('status','next')}>بعدی</option>
<option value="in_progress"{selected('status','in_progress')}>در حال انجام</option>
<option value="waiting"{selected('status','waiting')}>منتظر</option></select></div>
<div class="field"><label for="due_at">موعد انجام (اختیاری)</label><input id="due_at" name="due_at" type="datetime-local" value="{_e(values.get('due_at'))}"></div>
<div class="field"><label for="project_id">پروژه (اختیاری)</label><input id="project_id" name="project_id" maxlength="120" placeholder="مثلاً ICARUS" value="{_e(values.get('project_id'))}"></div>
<div class="field wide"><label for="tags">برچسب‌ها (با ویرگول جدا کن)</label><input id="tags" name="tags" maxlength="500" placeholder="طراحی، فوری، شخصی" value="{_e(values.get('tags'))}"></div>
<button class="submit" type="submit">ثبت کار در فهرست</button>
</form></section>
<section><h2>کارها <span class="muted">({len(tasks)})</span></h2>{task_list}</section>
<p class="muted">اطلاعات به‌صورت محلی در فایل TaskStore ذخیره می‌شوند. ثبت کار هیچ عملیات اجرایی بیرونی را آغاز نمی‌کند.</p>
</main></body></html>"""


def create_task_server(store: TaskStore, *, host: str = "127.0.0.1",
                       port: int = 8766) -> HTTPServer:
    """Create a loopback-only Task Companion server."""
    if host != "127.0.0.1":
        raise ValueError("Task Companion may only bind to 127.0.0.1")
    token = secrets.token_urlsafe(32)
    server = HTTPServer((host, port), None)
    server.dashboard_message = ""

    class TaskHandler(BaseHTTPRequestHandler):
        def _respond(self, status: int, body: str, content_type: str = "text/html; charset=utf-8") -> None:
            data = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _require_loopback_host(self) -> bool:
            host = self.headers.get("Host", "")
            if urlparse("//" + host).hostname != "127.0.0.1":
                self._respond(403, "Forbidden")
                return False
            return True

        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if not self._require_loopback_host():
                return
            if path == "/":
                message = server.dashboard_message
                server.dashboard_message = ""
                self._respond(200, _page(store, token, message=message))
            elif path == "/health":
                self._respond(200, '{"status":"ok"}', "application/json; charset=utf-8")
            elif path == "/api/v1/tasks":
                payload = json.dumps(_task_api_payload(store), ensure_ascii=False, separators=(",", ":"))
                self._respond(200, payload, "application/json; charset=utf-8")
            else:
                self._respond(404, "Not found")

        def do_POST(self) -> None:
            route = urlparse(self.path).path
            if not self._require_loopback_host():
                return
            if route not in {"/tasks", "/events/apply", "/events/reject"}:
                self._respond(404, "Not found")
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 16384:
                    raise ValueError("اندازهٔ فرم نامعتبر است.")
                raw = self.rfile.read(length).decode("utf-8")
                form = parse_qs(raw, strict_parsing=True, keep_blank_values=True)
                values = {key: items[-1] for key, items in form.items() if items}
                if not secrets.compare_digest(values.get("csrf", ""), token):
                    raise PermissionError("درخواست معتبر نیست؛ صفحه را تازه‌سازی کن.")
                if route in {"/events/apply", "/events/reject"}:
                    event_id = values.get("event_id", "")
                    event = next((item for item in store.pending_execution_events()
                                  if item.get("event_id") == event_id), None)
                    if event is None:
                        raise ValueError("پیشنهاد پیدا نشد یا قبلاً بررسی شده است.")
                    if route == "/events/apply":
                        updated = store.apply_execution_event(event, user_approved=True)
                        server_message = f"پیشنهاد پذیرفته شد؛ وضعیت «{updated['status']}» ثبت شد."
                    else:
                        store.dismiss_execution_event(event_id)
                        server_message = "پیشنهاد رد شد؛ وضعیت کار تغییری نکرد."
                    server.dashboard_message = server_message
                    self.send_response(303)
                    self.send_header("Location", "/")
                    self.send_header("Content-Length", "0")
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    return
                title = values.get("title", "").strip()
                description = values.get("description", "").strip()
                priority = values.get("priority", "normal")
                status = values.get("status", "inbox")
                if status not in {"inbox", "next", "in_progress", "waiting"}:
                    raise ValueError("وضعیت اولیه نامعتبر است.")
                due_raw = values.get("due_at", "").strip()
                due_at = due_raw.replace("T", " ") if due_raw else None
                project_id = values.get("project_id", "").strip() or None
                tags = [tag.strip() for tag in values.get("tags", "").split(",") if tag.strip()]
                if len(title) > 200 or len(description) > 5000 or len(tags) > 30:
                    raise ValueError("یکی از فیلدها از حد مجاز طولانی‌تر است.")
                task = store.add(
                    title, description=description, priority=priority,
                    due_at=due_at, project_id=project_id, tags=tags,
                    source="task_companion_form",
                )
                if status != "inbox":
                    task = store.update(task["id"], status=status)
                self.send_response(303)
                self.send_header("Location", "/")
                self.send_header("Content-Length", "0")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
            except (ValueError, PermissionError, UnicodeDecodeError) as exc:
                message = str(exc)
                safe_values = locals().get("values", {})
                self._respond(400, _page(store, token, error=message, values=safe_values))
            except Exception as exc:
                self._respond(500, _page(store, token, error="خطای داخلی: " + type(exc).__name__))

        def log_message(self, format: str, *args: Any) -> None:
            return

    server.RequestHandlerClass = TaskHandler
    return server


def serve_task_companion(store: TaskStore, *, port: int = 8766) -> None:
    server = create_task_server(store, port=port)
    print(f"ICARUS Task Companion: http://127.0.0.1:{port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
