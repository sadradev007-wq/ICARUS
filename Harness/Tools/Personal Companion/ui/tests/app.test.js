import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const html = await readFile(new URL("../index.html", import.meta.url), "utf8");
const js = await readFile(new URL("../app.js", import.meta.url), "utf8");
const css = await readFile(new URL("../styles.css", import.meta.url), "utf8");

test("the GUI exposes all eight primary workspaces", () => {
  for (const view of ["chat","tasks","calendar","memory","files","models","activity","settings"]) {
    assert.match(html, new RegExp(`data-view="${view}"`));
    assert.match(html, new RegExp(`id="view-${view}"`));
  }
});

test("the application shell contains a collapsible global priority drawer", () => {
  assert.match(html, /id="priority-drawer"/);
  assert.match(html, /id="priority-toggle"/);
  assert.match(html, /id="priority-panel"/);
  assert.match(js, /priorityToggle\.setAttribute\("aria-expanded"/);
});

test("the prototype keeps its local-only and quarantine boundaries visible", () => {
  assert.match(html, /نمونهٔ رابط/);
  assert.match(html, /قرنطینه فعال است/);
  assert.match(html, /هنوز به TaskStore متصل نیست/);
  assert.match(js, /icarus\.prototype\.tasks/);
});

test("responsive and reduced-motion rules are present", () => {
  assert.match(css, /@media\(max-width:600px\)/);
  assert.match(css, /prefers-reduced-motion/);
});
