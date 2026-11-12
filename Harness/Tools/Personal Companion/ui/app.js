const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const labels = {chat:"دستیار",tasks:"کارها",calendar:"تقویم",memory:"حافظه",files:"کتابخانه",models:"مدل‌های هوش مصنوعی",activity:"گزارش فعالیت‌ها",settings:"تنظیمات"};
const views = $$(".view");
const navButtons = $$("[data-view]");
const modal = $("#modal-backdrop");
const toast = $("#toast");
const priorityDrawer = $("#priority-drawer");
const priorityPanel = $("#priority-panel");
const priorityToggle = $("#priority-toggle");
let toastTimer;

function notify(message) {
  toast.textContent = message;
  toast.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("show"), 2600);
}
function navigate(name) {
  if (!labels[name]) return;
  priorityPanel.hidden = true;
  priorityToggle.setAttribute("aria-expanded", "false");
  views.forEach(view => view.classList.toggle("active", view.id === `view-${name}`));
  navButtons.forEach(button => button.classList.toggle("active", button.dataset.view === name));
  $("#current-section").textContent = labels[name];
  if (window.innerWidth <= 600) window.scrollTo({top:0,behavior:"smooth"});
}
navButtons.forEach(button => button.addEventListener("click", () => navigate(button.dataset.view)));

priorityToggle.addEventListener("click", () => {
  const opening = priorityPanel.hidden;
  priorityPanel.hidden = !opening;
  priorityToggle.setAttribute("aria-expanded", String(opening));
});
$("#priority-close").addEventListener("click", () => {
  priorityPanel.hidden = true;
  priorityToggle.setAttribute("aria-expanded", "false");
});
document.addEventListener("click", event => {
  if (!priorityPanel.hidden && !priorityDrawer.contains(event.target)) {
    priorityPanel.hidden = true;
    priorityToggle.setAttribute("aria-expanded", "false");
  }
});

function openModal() {
  modal.hidden = false;
  document.body.style.overflow = "hidden";
  setTimeout(() => $('input[name="title"]', modal)?.focus(), 0);
}
function closeModal() {
  modal.hidden = true;
  document.body.style.overflow = "";
}
$$("[data-close-modal]").forEach(button => button.addEventListener("click", closeModal));
modal.addEventListener("click", event => { if (event.target === modal) closeModal(); });
document.addEventListener("keydown", event => { if (event.key === "Escape" && !modal.hidden) closeModal(); });

function makeTaskRow(task) {
  const row = document.createElement("article");
  row.className = "task-row";
  const check = document.createElement("button");
  check.className = "task-check";
  check.type = "button";
  check.setAttribute("aria-label", "تغییر وضعیت کار");
  check.addEventListener("click", () => {
    check.classList.toggle("done");
    check.textContent = check.classList.contains("done") ? "✓" : "";
    notify("وضعیت فقط در نمونهٔ محلی تغییر کرد.");
  });
  const main = document.createElement("div");
  main.className = "task-main";
  const title = document.createElement("b");
  title.textContent = task.title;
  const meta = document.createElement("small");
  meta.textContent = task.folder || "صندوق ورودی";
  main.append(title, meta);
  const priority = document.createElement("span");
  priority.className = "priority-pill " + (task.priority === "critical" || task.priority === "high" ? "urgent" : task.priority === "low" ? "low" : "medium");
  priority.textContent = ({critical:"بحرانی",high:"بالا",normal:"معمولی",low:"پایین"})[task.priority] || "معمولی";
  const due = document.createElement("time");
  due.textContent = task.due ? new Date(task.due).toLocaleString("fa-IR",{dateStyle:"medium",timeStyle:"short"}) : "بدون موعد";
  const more = document.createElement("button");
  more.className = "more-button";
  more.type = "button";
  more.textContent = "···";
  more.addEventListener("click", () => notify("جزئیات و ویرایش به اتصال TaskStore نیاز دارد."));
  row.dataset.priority = task.priority || "normal";
  row.dataset.due = task.due || "";
  row.append(check, main, priority, due, more);
  return row;
}
const categoryNames = {projects:"پروژه‌ها و توسعه",research:"پژوهش و یکپارچه‌سازی",learning:"یادگیری و مطالعه",personal:"امور شخصی",ideas:"ایده‌ها و پیگیری"};
function categoryFor(task) {
  if (categoryNames[task.category]) return task.category;
  const folder = String(task.folder || "").toLowerCase();
  if (folder.includes("learning") || folder.includes("study")) return "learning";
  if (folder.includes("integration") || folder.includes("research")) return "research";
  if (folder.includes("idea")) return "ideas";
  if (folder.includes("personal")) return "projects";
  return "ideas";
}
function addTaskToCategory(task) {
  const category = categoryFor(task);
  let section = $(`[data-task-category="${category}"]`);
  if (!section) {
    const grid = $("#task-list");
    if (!grid) return;
    section = document.createElement("section");
    section.className = "task-category";
    section.dataset.taskCategory = category;
    const header = document.createElement("header");
    const heading = document.createElement("div");
    const title = document.createElement("b");
    title.textContent = categoryNames[category];
    const subtitle = document.createElement("small");
    subtitle.textContent = "کارهای ثبت‌شده در این دسته";
    heading.append(title, subtitle);
    const count = document.createElement("span");
    count.className = "category-count";
    count.textContent = "0";
    header.append(heading, count);
    const items = document.createElement("div");
    items.className = "task-category-items";
    section.append(header, items);
    grid.append(section);
  }
  const list = $(".task-category-items", section);
  list?.prepend(makeTaskRow(task));
  const count = $(".category-count", section);
  if (count) count.textContent = String($(".task-row", list).length);
}
function loadLocalTasks() {
  try {
    const items = JSON.parse(localStorage.getItem("icarus.prototype.tasks") || "[]");
    items.forEach(addTaskToCategory);
  } catch { /* Ignore unavailable or malformed prototype storage. */ }
}
$("#task-form").addEventListener("submit", event => {
  event.preventDefault();
  const data = new FormData(event.currentTarget);
  const task = {
    title: String(data.get("title") || "").trim(),
    folder: String(data.get("folder") || ""),
    category: String(data.get("category") || "ideas"),
    priority: String(data.get("priority") || "normal"),
    due: String(data.get("due") || ""),
    description: String(data.get("description") || "")
  };
  if (!task.title) return;
  let items = [];
  try { items = JSON.parse(localStorage.getItem("icarus.prototype.tasks") || "[]"); } catch { items = []; }
  items.push(task);
  try { localStorage.setItem("icarus.prototype.tasks", JSON.stringify(items)); } catch { notify("ذخیره‌سازی مرورگر در دسترس نیست."); }
  addTaskToCategory(task);
  event.currentTarget.reset();
  closeModal();
  notify("پیش‌نویس کار در نمونهٔ محلی ثبت شد.");
  navigate("tasks");
});

function appendMessage(text, author = "user") {
  const wrapper = document.createElement("div");
  wrapper.className = "message " + (author === "user" ? "user-message" : "assistant-message");
  if (author === "assistant") {
    const icon = document.createElement("span");
    icon.className = "message-avatar";
    icon.textContent = "I";
    wrapper.append(icon);
  }
  const body = document.createElement("div");
  body.className = "message-body";
  const meta = document.createElement("div");
  meta.className = "message-meta";
  meta.textContent = author === "user" ? "شما · همین حالا" : "ایکاروس · پاسخ نمایشی";
  const paragraph = document.createElement("p");
  paragraph.textContent = text;
  body.append(meta, paragraph);
  wrapper.append(body);
  if (author === "user") {
    const avatar = document.createElement("span");
    avatar.className = "user-avatar";
    avatar.textContent = "S";
    wrapper.append(avatar);
  }
  $("#chat-messages").append(wrapper);
  wrapper.scrollIntoView({behavior:"smooth",block:"nearest"});
}
$("#chat-form").addEventListener("submit", event => {
  event.preventDefault();
  const input = $("#chat-input");
  const text = input.value.trim();
  if (!text) return;
  appendMessage(text);
  input.value = "";
  setTimeout(() => appendMessage("پیامت در این نمونهٔ رابط دریافت شد. برای پاسخ هوشمند، ذخیرهٔ مکالمه و ساخت وظیفه باید سرویس چت و حافظه به این رابط متصل شوند. فعلاً هیچ عملیات واقعی اجرا نشده است.", "assistant"), 350);
});

$$("[data-action]").forEach(button => button.addEventListener("click", () => {
  const action = button.dataset.action;
  if (action === "new-task") {
    $("#modal-title").textContent = "کار جدید";
    openModal();
  } else if (action === "quick-idea") {
    $("#modal-title").textContent = "ثبت ایده به‌عنوان کار";
    openModal();
  } else if (action === "add-memory") {
    notify("فرم مدیریت حافظه در مرحلهٔ اتصال سرویس حافظه فعال می‌شود.");
  } else if (action === "new-folder") {
    notify("ساخت پوشه پس از اتصال Workspace Library فعال می‌شود.");
  } else if (action === "accept-suggestion") {
    notify("پیشنهاد آمادهٔ بررسی است؛ ثبت واقعی نیازمند اتصال TaskStore است.");
  }
}));
$$("[data-view]").forEach(button => {
  if (button.tagName !== "BUTTON") return;
  button.addEventListener("click", () => {
    if (button.classList.contains("subtle-button") || button.classList.contains("more-button")) notify("نمای بخش باز شد.");
  });
});
loadLocalTasks();