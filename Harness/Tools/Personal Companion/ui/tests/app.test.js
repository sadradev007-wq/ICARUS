import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const html = await readFile(new URL("../index.html", import.meta.url), "utf8");
const js = await readFile(new URL("../app.js", import.meta.url), "utf8");
const css = await readFile(new URL("../styles.css", import.meta.url), "utf8");
const taxonomy = JSON.parse(await readFile(new URL("../../data/taxonomy.fa.json", import.meta.url), "utf8"));

test("the GUI exposes all eight primary workspaces", () => {
  for (const view of ["chat","tasks","calendar","memory","files","models","activity","settings"]) {
    assert.match(html, new RegExp("data-view=\"" + view + "\""));
    assert.match(html, new RegExp("id=\"view-" + view + "\""));
  }
});

test("the application shell contains a collapsible global priority drawer", () => {
  assert.match(html, /id="priority-drawer"/);
  assert.match(html, /id="priority-toggle"/);
  assert.match(html, /id="priority-panel"/);
  assert.match(js, /priorityToggle\.setAttribute\("aria-expanded"/);
});

test("the taxonomy contains 50 main domains and 20 subtopics per domain", () => {
  assert.equal(taxonomy.categories.length, 50);
  assert.ok(taxonomy.categories.every(category => category.children.length === 20));
  assert.match(html, /id="taxonomy-tree"/);
  assert.match(html, /id="taxonomy-search"/);
  assert.match(js, /۵۰ حوزه · ۱۰۰۰ زیرعنوان/);
});

test("AI classification is a proposal and needs explicit approval", () => {
  assert.match(html, /id="classify-button"/);
  assert.match(js, /\/api\/ai\/classify/);
  assert.match(js, /تأیید و افزودن به کارها/);
  assert.match(js, /requires_user_approval/);
});

test("AI calendar planning requires user availability and explicit approval", () => {
  assert.match(html, /id="availability-start"/);
  assert.match(html, /id="availability-end"/);
  assert.match(html, /id="calendar-plan-button"/);
  assert.match(js, /\/api\/ai\/calendar/);
  assert.match(js, /available_windows/);
  assert.match(js, /window\.confirm/);
  assert.match(js, /تأیید و ثبت همهٔ رویدادها/);
});

test("legacy agents remain visibly quarantined and AI providers are independently selectable", () => {
  assert.match(html, /قرنطینه فعال است/);
  for (const route of ["system1_local","system1_api","system2_local","system2_api"]) {
    assert.ok(html.includes(route));
  }
});

test("responsive and reduced-motion rules are present", () => {
  assert.match(css, /@media\(max-width:600px\)/);
  assert.match(css, /prefers-reduced-motion/);
  assert.match(css, /taxonomy-tree/);
});
