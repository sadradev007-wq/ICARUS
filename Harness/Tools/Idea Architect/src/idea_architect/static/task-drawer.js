import { parseTaskSnapshot, selectDrawerSections } from "./task-drawer-model.js";

const root = document.querySelector("[data-task-drawer]");
if (root) {
  const query = (selector) => root.querySelector(selector);
  const toggle = query("[data-drawer-toggle]");
  const closeButton = query("[data-drawer-close]");
  const panel = query("#task-drawer-panel");
  const backdrop = document.querySelector("[data-drawer-backdrop]");
  const statusNode = query("[data-drawer-status]");
  const refreshButton = query("[data-drawer-refresh]");
  const priorityLabels = { critical: "بحرانی", high: "بالا", normal: "معمولی", low: "پایین" };
  const statusLabels = { inbox: "صندوق ورودی", next: "بعدی", in_progress: "در حال انجام", waiting: "منتظر" };
  const runStatusLabels = { completed: "اجرای تکمیل‌شده", step_limit: "توقف در سقف گام‌ها" };
  let refreshing = false;

  function setStatus(state, message) {
    statusNode.dataset.state = state;
    statusNode.textContent = message;
  }

  function setOpen(open, { focus = true } = {}) {
    const mobile = window.matchMedia("(max-width: 760px)").matches;
    root.classList.toggle("is-open", open);
    panel.hidden = !open;
    backdrop.hidden = !(open && mobile);
    document.body.classList.toggle("task-drawer-open", open && !mobile);
    toggle.setAttribute("aria-expanded", String(open));
    try {
      window.localStorage.setItem("icarus.task-drawer.open", open ? "1" : "0");
    } catch {
      // Storage can be disabled; drawer state still works for this page.
    }
    if (focus) (open ? closeButton : toggle).focus();
  }

  function formatDue(value) {
    if (!value) return "بدون موعد";
    const normalized = value.includes("T") ? value : value.replace(" ", "T");
    const date = new Date(normalized);
    if (Number.isNaN(date.getTime())) return value;
    return new Intl.DateTimeFormat("fa-IR", { dateStyle: "medium", timeStyle: "short" }).format(date);
  }

  function taskCard(task) {
    const article = document.createElement("article");
    article.className = "task-drawer__task";
    const title = document.createElement("a");
    title.href = "#tasks";
    title.textContent = task.title;
    title.addEventListener("click", () => setOpen(false));
    const meta = document.createElement("p");
    const parts = [
      priorityLabels[task.priority] ?? task.priority,
      statusLabels[task.status] ?? task.status,
    ];
    if (task.due_at) parts.push("موعد: " + formatDue(task.due_at));
    meta.textContent = parts.join(" · ");
    article.append(title, meta);
    return article;
  }

  function renderList(container, tasks, emptyText) {
    container.replaceChildren();
    if (!tasks.length) {
      const empty = document.createElement("p");
      empty.className = "task-drawer__empty";
      empty.textContent = emptyText;
      container.append(empty);
      return;
    }
    for (const task of tasks) container.append(taskCard(task));
  }

  function feedbackCard(event) {
    const article = document.createElement("article");
    article.className = "task-drawer__task task-drawer__feedback";
    const heading = document.createElement("strong");
    heading.textContent = "کار " + event.task_id;
    const meta = document.createElement("p");
    meta.textContent = (runStatusLabels[event.run_status] ?? event.run_status)
      + " · " + formatDue(event.created_at);
    const summary = document.createElement("p");
    summary.textContent = event.summary;
    const correlation = document.createElement("p");
    if (event.run_id) {
      const code = document.createElement("code");
      code.dir = "ltr";
      code.textContent = event.run_id;
      correlation.append("شناسهٔ اجرا: ", code);
    } else {
      correlation.textContent = "شناسهٔ اجرا: رویداد قدیمی (بدون run_id)";
    }
    article.append(heading, meta, summary, correlation);
    return article;
  }

  function renderFeedback(container, events) {
    container.replaceChildren();
    if (!events.length) {
      const empty = document.createElement("p");
      empty.className = "task-drawer__empty";
      empty.textContent = "پیشنهاد اجرایی در انتظار تأیید نیست.";
      container.append(empty);
      return;
    }
    for (const event of events) container.append(feedbackCard(event));
  }

  function render(snapshot) {
    const sections = selectDrawerSections(snapshot);
    query("[data-active-count]").textContent = new Intl.NumberFormat("fa-IR").format(sections.activeCount);
    query("[data-feedback-count]").textContent = new Intl.NumberFormat("fa-IR").format(sections.pendingFeedbackCount);
    query("[data-critical-count]").textContent = new Intl.NumberFormat("fa-IR").format(sections.criticalOrHighCount);
    query("[data-feedback-link]").hidden = sections.pendingFeedbackCount === 0;

    if (sections.recommended) {
      renderList(query("[data-recommended]"), [sections.recommended], "فعلاً کاری برای انجام نیست.");
      query("[data-recommended-reason]").textContent =
        sections.recommended.status === "waiting"
          ? "همهٔ کارهای فعال منتظر هستند؛ این مورد برای پیگیری نمایش داده شده است."
          : "بر اساس ترتیب اولویت و موعد ثبت‌شده در TaskStore انتخاب شده است.";
    } else {
      renderList(query("[data-recommended]"), [], "فعلاً کاری برای انجام ثبت نشده است.");
      query("[data-recommended-reason]").textContent = "با ثبت یک کار، اقدام بعدی اینجا نمایش داده می‌شود.";
    }
    renderList(query("[data-urgent]"), sections.urgent, "کار بحرانی یا با اولویت بالا وجود ندارد.");
    renderList(query("[data-due-soon]"), sections.dueSoon, "موعد گذشته یا نزدیک ثبت نشده است.");
    renderList(query("[data-waiting]"), sections.waiting, "کاری در وضعیت انتظار نیست.");
    renderFeedback(query("[data-pending-feedback]"), sections.pendingFeedback);
    setStatus("ready", sections.activeCount ? "فهرست وظایف به‌روز شد." : "هنوز کاری ثبت نشده است.");
  }

  async function refresh() {
    if (refreshing) return;
    refreshing = true;
    setStatus("loading", "در حال دریافت کارها…");
    refreshButton.disabled = true;
    try {
      let response;
      try {
        response = await fetch("/api/v2/tasks", {
          method: "GET",
          headers: { Accept: "application/json" },
          cache: "no-store",
          credentials: "same-origin",
        });
      } catch {
        setStatus("offline", "ارتباط با سرور محلی برقرار نیست؛ اجرای icarus-tasks را بررسی کن.");
        return;
      }
      if (!response.ok) throw new Error("Task API request failed");
      const snapshot = parseTaskSnapshot(await response.json());
      render(snapshot);
    } catch {
      setStatus("error", "دریافت فهرست ناموفق بود؛ برای تلاش دوباره از دکمهٔ به‌روزرسانی استفاده کن.");
    } finally {
      refreshing = false;
      refreshButton.disabled = false;
    }
  }

  toggle.addEventListener("click", () => setOpen(toggle.getAttribute("aria-expanded") !== "true"));
  closeButton.addEventListener("click", () => setOpen(false));
  backdrop.addEventListener("click", () => setOpen(false));
  refreshButton.addEventListener("click", refresh);
  query("[data-all-tasks]").addEventListener("click", () => setOpen(false));
  query("[data-feedback-link]").addEventListener("click", () => setOpen(false));
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && root.classList.contains("is-open")) setOpen(false);
  });
  window.addEventListener("online", refresh);
  window.matchMedia("(max-width: 760px)").addEventListener("change", () => {
    if (root.classList.contains("is-open")) setOpen(true, { focus: false });
  });

  let initiallyOpen = false;
  try {
    initiallyOpen = window.localStorage.getItem("icarus.task-drawer.open") === "1";
  } catch {
    initiallyOpen = false;
  }
  setOpen(initiallyOpen, { focus: false });
  refresh();
  window.setInterval(() => {
    if (document.visibilityState === "visible") refresh();
  }, 30000);
}
