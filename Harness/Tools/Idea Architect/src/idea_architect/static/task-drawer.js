import {
  parseProviderHealthSnapshot,
  parseTaskSnapshot,
  selectDrawerSections,
} from "./task-drawer-model.js";

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
  const runStatusLabels = { completed: "اجرای تکمیل‌شده", step_limit: "توقف در سقف گام‌ها", error: "اجرای ناموفق" };
  const reviewStatusLabels = {
    completed: "تکمیل‌شده", no_changes: "بدون تغییر", required: "نیازمند بازبینی",
    unavailable: "بازبین در دسترس نبود", invalid_or_unknown: "نامشخص",
    static_diff_reviewed: "بررسی ایستای diff",
  };
  const actionTypeLabels = {
    user_request: "درخواست کاربر", assistant_decision: "تصمیم دستیار",
    tool_started: "شروع ابزار", tool_finished: "پایان ابزار",
    mutation_proposed: "پیشنهاد تغییر", mutation_applied: "اعمال تغییر",
    approval_granted: "تأیید کاربر", approval_denied: "رد کاربر",
    checkpoint_created: "ایجاد نقطهٔ بازگشت", rollback_applied: "بازگردانی",
    task_changed: "تغییر کار", calendar_changed: "تغییر تقویم",
    provider_selected: "انتخاب مدل", error: "خطا", response_completed: "پاسخ نهایی",
  };
  const actorLabels = { user: "کاربر", assistant: "دستیار", system: "سیستم", external_service: "سرویس بیرونی" };
  const outcomeLabels = { proposed: "پیشنهادشده", succeeded: "موفق", failed: "ناموفق", denied: "ردشده", cancelled: "لغوشده", skipped: "ردشده" };
  const approvalLabels = { not_required: "نیازی به تأیید نبود", pending: "در انتظار", approved: "تأییدشده", denied: "ردشده" };
  const timelineSourceLabels = { coding_harness: "Coding Harness", action_journal: "Action Journal" };
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

  function runHistoryDetails(task, sections) {
    if (sections.runHistoryStatus !== "configured") return null;
    const runs = sections.runHistoryByTask.get(task.id) ?? [];
    const details = document.createElement("details");
    details.className = "task-drawer__run-history";
    const summary = document.createElement("summary");
    summary.textContent = "تاریخچهٔ اجرای هارنس (" + new Intl.NumberFormat("fa-IR").format(runs.length) + ")";
    details.append(summary);

    if (!runs.length) {
      const empty = document.createElement("p");
      empty.className = "task-drawer__empty";
      empty.textContent = "برای این کار اجرای ثبت‌شده‌ای وجود ندارد.";
      details.append(empty);
      return details;
    }

    const list = document.createElement("ol");
    for (const run of runs) {
      const item = document.createElement("li");
      const heading = document.createElement("strong");
      heading.textContent = runStatusLabels[run.status] ?? run.status;
      const verification = run.verification;
      const meta = document.createElement("p");
      const parts = [
        formatDue(run.created_at),
        new Intl.NumberFormat("fa-IR").format(run.steps) + " گام",
        verification.tests_reported ? "آزمون گزارش شد" : "آزمون گزارش نشده",
        "بازبینی: " + (reviewStatusLabels[verification.review_status] ?? verification.review_status),
      ];
      if (verification.ci_status) parts.push("CI: " + verification.ci_status);
      meta.textContent = parts.join(" · ");
      const correlation = document.createElement("p");
      if (run.run_id) {
        const code = document.createElement("code");
        code.dir = "ltr";
        code.textContent = run.run_id;
        correlation.append("شناسهٔ اجرا: ", code);
      } else {
        correlation.textContent = "رکورد تاریخی؛ شناسهٔ اجرا ثبت نشده است.";
      }
      item.append(heading, meta, correlation);
      list.append(item);
    }
    details.append(list);
    return details;
  }


  function actionHistoryDetails(task, sections) {
    if (sections.actionHistoryStatus !== "configured") return null;
    const events = sections.actionHistoryByTask.get(task.id) ?? [];
    const details = document.createElement("details");
    details.className = "task-drawer__run-history task-drawer__action-history";
    const summary = document.createElement("summary");
    summary.textContent = "تاریخچهٔ Action Journal (" + new Intl.NumberFormat("fa-IR").format(events.length) + ")";
    details.append(summary);

    if (!events.length) {
      const empty = document.createElement("p");
      empty.className = "task-drawer__empty";
      empty.textContent = "رویداد عملیاتی ثبت‌شده‌ای برای این کار وجود ندارد.";
      details.append(empty);
      return details;
    }

    const list = document.createElement("ol");
    for (const event of events) {
      const item = document.createElement("li");
      const heading = document.createElement("strong");
      heading.textContent = actionTypeLabels[event.event_type] ?? event.event_type;
      const meta = document.createElement("p");
      meta.textContent = [
        formatDue(event.created_at),
        actorLabels[event.actor] ?? event.actor,
        "نتیجه: " + (outcomeLabels[event.outcome_status] ?? event.outcome_status),
        "تأیید: " + (approvalLabels[event.approval_status] ?? event.approval_status),
      ].join(" · ");
      const identifiers = document.createElement("p");
      const eventCode = document.createElement("code");
      eventCode.dir = "ltr";
      eventCode.textContent = event.event_id;
      identifiers.append("رویداد: ", eventCode);
      if (event.run_id) {
        const runCode = document.createElement("code");
        runCode.dir = "ltr";
        runCode.textContent = event.run_id;
        identifiers.append(" · اجرا: ", runCode);
      }
      if (event.proposal_id) {
        const proposalCode = document.createElement("code");
        proposalCode.dir = "ltr";
        proposalCode.textContent = event.proposal_id;
        identifiers.append(" · پیشنهاد: ", proposalCode);
      }
      item.append(heading, meta, identifiers);
      list.append(item);
    }
    details.append(list);
    return details;
  }

  function executionTimelineDetails(task, sections) {
    if (!["configured", "partial"].includes(sections.executionTimelineStatus)) return null;
    const entries = sections.executionTimelineByTask.get(task.id) ?? [];
    const details = document.createElement("details");
    details.className = "task-drawer__run-history task-drawer__execution-timeline";
    const summary = document.createElement("summary");
    summary.textContent = "تاریخچهٔ یکپارچهٔ اجرا (" + new Intl.NumberFormat("fa-IR").format(entries.length) + ")";
    details.append(summary);
    if (!entries.length) {
      const empty = document.createElement("p");
      empty.className = "task-drawer__empty";
      empty.textContent = "برای این کار هنوز رویداد اجرایی ثبت نشده است.";
      details.append(empty);
      return details;
    }
    const list = document.createElement("ol");
    for (const entry of entries) {
      const item = document.createElement("li");
      const heading = document.createElement("strong");
      heading.textContent = entry.source === "coding_harness"
        ? (runStatusLabels[entry.status] ?? entry.status)
        : (actionTypeLabels[entry.event_type] ?? entry.event_type);
      const meta = document.createElement("p");
      const parts = [formatDue(entry.created_at), timelineSourceLabels[entry.source] ?? entry.source];
      if (entry.source === "coding_harness") {
        parts.push(new Intl.NumberFormat("fa-IR").format(entry.steps) + " گام");
        parts.push(entry.tests_reported ? "آزمون گزارش شد" : "آزمون گزارش نشده");
        parts.push("بازبینی: " + (reviewStatusLabels[entry.review_status] ?? entry.review_status));
        if (entry.ci_status) parts.push("CI: " + entry.ci_status);
      } else {
        parts.push(actorLabels[entry.actor] ?? entry.actor);
        parts.push("نتیجه: " + (outcomeLabels[entry.status] ?? entry.status));
        parts.push("تأیید: " + (approvalLabels[entry.approval_status] ?? entry.approval_status));
      }
      meta.textContent = parts.join(" · ");
      const identifiers = document.createElement("p");
      const sourceCode = document.createElement("code");
      sourceCode.dir = "ltr";
      sourceCode.textContent = entry.source_id;
      identifiers.append("شناسهٔ منبع: ", sourceCode);
      if (entry.run_id) {
        const runCode = document.createElement("code");
        runCode.dir = "ltr";
        runCode.textContent = entry.run_id;
        identifiers.append(" · اجرا: ", runCode);
      }
      if (entry.proposal_id) {
        const proposalCode = document.createElement("code");
        proposalCode.dir = "ltr";
        proposalCode.textContent = entry.proposal_id;
        identifiers.append(" · پیشنهاد: ", proposalCode);
      }
      item.append(heading, meta, identifiers);
      list.append(item);
    }
    details.append(list);
    return details;
  }

  function taskCard(task, sections) {
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
    if (sections.executionTimelineStatus !== "unsupported") {
      const timeline = executionTimelineDetails(task, sections);
      if (timeline) article.append(timeline);
    } else {
      const history = runHistoryDetails(task, sections);
      if (history) article.append(history);
      const actionHistory = actionHistoryDetails(task, sections);
      if (actionHistory) article.append(actionHistory);
    }
    return article;
  }

  function renderList(container, tasks, emptyText, sections) {
    container.replaceChildren();
    if (!tasks.length) {
      const empty = document.createElement("p");
      empty.className = "task-drawer__empty";
      empty.textContent = emptyText;
      container.append(empty);
      return;
    }
    for (const task of tasks) container.append(taskCard(task, sections));
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


  function renderProviderHealth(snapshot) {
    const statusNode = query("[data-provider-health-status]");
    const routesNode = query("[data-provider-health-routes]");
    routesNode.replaceChildren();
    const overallLabels = {
      configured: "گزارش سلامت دریافت شد",
      not_configured: "مسیر گزارش Provider Health تنظیم نشده است.",
      unavailable: "گزارش سلامت در دسترس نیست.",
      invalid: "گزارش سلامت نامعتبر است و نمایش داده نشد.",
    };
    const statusLabels = {
      ok: "سالم", warning: "هشدار", error: "خطا", skipped: "غیرفعال",
    };
    const probeLabels = {
      not_probed: "Inference آزمایش نشده",
      skipped: "آزمایش رد شده یا اجرا نشده",
      passed: "Inference پاسخ معتبر داده",
      failed: "آزمایش Inference ناموفق",
    };
    const freshnessLabels = {
      fresh: "گزارش تازه",
      stale: "گزارش قدیمی؛ اجرای دوباره doctor لازم است",
      unknown: "تازگی گزارش نامشخص است",
    };
    const routeLabels = {
      system1_local: "System 1 · محلی",
      system1_api: "System 1 · API",
      system2_local: "System 2 · محلی",
      system2_api: "System 2 · API",
    };
    if (snapshot.status !== "configured") {
      statusNode.textContent = overallLabels[snapshot.status];
      return;
    }
    const observed = formatDue(snapshot.observed_at);
    const freshness = snapshot.schema === "icarus.provider-health-projection.v2"
      ? " · " + freshnessLabels[snapshot.freshness]
        + (snapshot.age_seconds === null ? "" : " · " +
          new Intl.NumberFormat("fa-IR").format(snapshot.age_seconds) + " ثانیه")
      : "";
    statusNode.textContent = overallLabels.configured + " · " +
      (statusLabels[snapshot.report_status] ?? snapshot.report_status) +
      " · " + probeLabels[snapshot.chat_completions_probe] +
      freshness + " · " + observed;
    const list = document.createElement("ul");
    list.className = "task-drawer__provider-health-list";
    for (const [name, route] of Object.entries(snapshot.routes)) {
      const item = document.createElement("li");
      const title = document.createElement("strong");
      title.textContent = routeLabels[name] ?? name;
      const detail = document.createElement("span");
      detail.textContent = [
        route.enabled ? "فعال" : "غیرفعال",
        statusLabels[route.status] ?? route.status,
        probeLabels[route.inference_status] ?? route.inference_status,
      ].join(" · ");
      item.append(title, detail);
      list.append(item);
    }
    routesNode.append(list);
  }

  async function refreshProviderHealth() {
    const unavailable = {
      schema: "icarus.provider-health-projection.v1",
      status: "unavailable",
      report_schema: null,
      report_status: null,
      observed_at: null,
      chat_completions_probe: "not_probed",
      routes: {},
    };
    try {
      let response = await requestSnapshot("/api/v2/provider-health");
      if (response.status === 404) {
        response = await requestSnapshot("/api/v1/provider-health");
      }
      if (!response.ok) {
        renderProviderHealth(unavailable);
        return;
      }
      renderProviderHealth(parseProviderHealthSnapshot(await response.json()));
    } catch {
      renderProviderHealth(unavailable);
    }
  }

  function render(snapshot) {
    const sections = selectDrawerSections(snapshot);
    query("[data-active-count]").textContent = new Intl.NumberFormat("fa-IR").format(sections.activeCount);
    query("[data-feedback-count]").textContent = new Intl.NumberFormat("fa-IR").format(sections.pendingFeedbackCount);
    query("[data-critical-count]").textContent = new Intl.NumberFormat("fa-IR").format(sections.criticalOrHighCount);
    query("[data-feedback-link]").hidden = sections.pendingFeedbackCount === 0;

    if (sections.recommended) {
      renderList(query("[data-recommended]"), [sections.recommended], "فعلاً کاری برای انجام نیست.", sections);
      query("[data-recommended-reason]").textContent =
        sections.recommended.status === "waiting"
          ? "همهٔ کارهای فعال منتظر هستند؛ این مورد برای پیگیری نمایش داده شده است."
          : "بر اساس ترتیب اولویت و موعد ثبت‌شده در TaskStore انتخاب شده است.";
    } else {
      renderList(query("[data-recommended]"), [], "فعلاً کاری برای انجام ثبت نشده است.", sections);
      query("[data-recommended-reason]").textContent = "با ثبت یک کار، اقدام بعدی اینجا نمایش داده می‌شود.";
    }
    renderList(query("[data-urgent]"), sections.urgent, "کار بحرانی یا با اولویت بالا وجود ندارد.", sections);
    renderList(query("[data-due-soon]"), sections.dueSoon, "موعد گذشته یا نزدیک ثبت نشده است.", sections);
    renderList(query("[data-waiting]"), sections.waiting, "کاری در وضعیت انتظار نیست.", sections);
    renderFeedback(query("[data-pending-feedback]"), sections.pendingFeedback);

    let historyHint = "";
    if (sections.executionTimelineStatus === "configured") {
      historyHint = " " + new Intl.NumberFormat("fa-IR").format(sections.executionTimelineEntriesCount) + " رخداد در تاریخچهٔ یکپارچه موجود است.";
    } else if (sections.executionTimelineStatus === "partial") {
      historyHint = " فقط بخشی از منابع تاریخچهٔ یکپارچه تنظیم شده است.";
    } else if (sections.executionTimelineStatus === "not_configured") {
      historyHint = " مسیرهای تاریخچهٔ اجرای Harness و Action Journal تنظیم نشده‌اند.";
    } else {
      if (sections.runHistoryStatus === "configured") {
        historyHint = " " + new Intl.NumberFormat("fa-IR").format(sections.taskRunRecordsCount) + " اجرای هارنس در دسترس است.";
      } else if (sections.runHistoryStatus === "not_configured") {
        historyHint = " مسیر تاریخچهٔ اجرای هارنس تنظیم نشده است.";
      } else {
        historyHint = " سرور قدیمی است؛ تاریخچهٔ اجرا در پنل در دسترس نیست.";
      }
      if (sections.actionHistoryStatus === "configured") {
        historyHint += " " + new Intl.NumberFormat("fa-IR").format(sections.actionJournalEventsCount) + " رویداد Action Journal در دسترس است.";
      } else if (sections.actionHistoryStatus === "not_configured") {
        historyHint += " مسیر Action Journal تنظیم نشده است.";
      }
    }
    setStatus("ready", (sections.activeCount ? "فهرست وظایف به‌روز شد." : "هنوز کاری ثبت نشده است.") + historyHint);
  }

  async function requestSnapshot(path) {
    return fetch(path, {
      method: "GET",
      headers: { Accept: "application/json" },
      cache: "no-store",
      credentials: "same-origin",
    });
  }

  async function refresh() {
    if (refreshing) return;
    refreshing = true;
    setStatus("loading", "در حال دریافت کارها…");
    refreshButton.disabled = true;
    try {
      let response;
      try {
        response = await requestSnapshot("/api/v5/tasks");
      } catch {
        setStatus("offline", "ارتباط با سرور محلی برقرار نیست؛ اجرای icarus-tasks را بررسی کن.");
        return;
      }
      if (response.status === 404) {
        try {
          response = await requestSnapshot("/api/v4/tasks");
        } catch {
          setStatus("offline", "ارتباط با سرور محلی برقرار نیست؛ اجرای icarus-tasks را بررسی کن.");
          return;
        }
      }
      if (response.status === 404) {
        try {
          response = await requestSnapshot("/api/v3/tasks");
        } catch {
          setStatus("offline", "ارتباط با سرور محلی برقرار نیست؛ اجرای icarus-tasks را بررسی کن.");
          return;
        }
      }
      if (response.status === 404) {
        try {
          response = await requestSnapshot("/api/v2/tasks");
        } catch {
          setStatus("offline", "ارتباط با سرور محلی برقرار نیست؛ اجرای icarus-tasks را بررسی کن.");
          return;
        }
      }
      if (!response.ok) throw new Error("Task API request failed");
      const snapshot = parseTaskSnapshot(await response.json());
      render(snapshot);
      await refreshProviderHealth();
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
