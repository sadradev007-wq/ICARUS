import test from "node:test";
import assert from "node:assert/strict";
import { loadCatalog, toMcpConfig, summarizeCatalog } from "../src/catalog.mjs";

const response = body => ({ ok: true, json: async () => body });

test("loads and validates a full catalog", async () => {
  const catalog = await loadCatalog("https://example.test/catalog.json", async () => response([
    { name: "alpha-mcp", pypi: "alpha", tools: [{ name: "read" }] },
    { name: "remote", url: "https://example.test/mcp", tools: [] }
  ]));
  assert.equal(catalog.length, 2);
  assert.equal(summarizeCatalog(catalog).catalogTools, 1);
});

test("rejects non-array catalogs and duplicate names", async () => {
  await assert.rejects(loadCatalog("x", async () => response({})), /expected an array/);
  await assert.rejects(loadCatalog("x", async () => response([
    { name: "same", pypi: "same" }, { name: "same", pypi: "same" }
  ])), /duplicate server name/);
});

test("rejects entries without a supported launch method and unsafe protocols", async () => {
  await assert.rejects(loadCatalog("x", async () => response([{ name: "broken" }])), /No supported launch method/);
  await assert.rejects(loadCatalog("x", async () => response([{ name: "bad", url: "file:///tmp/x" }])), /Unsupported URL protocol/);
});

test("builds local and hosted MCP entries and only injects supplied environment values", () => {
  const config = toMcpConfig([
    { name: "private-mcp", pypi: "private", env: [{ name: "TOKEN", isSecret: true }, { name: "OPTIONAL" }] },
    { name: "public", url: "https://example.test/mcp" }
  ], { TOKEN: "injected-secret" });
  assert.deepEqual(config.mcpServers.private, { command: "uvx", args: ["private"], env: { TOKEN: "injected-secret" } });
  assert.deepEqual(config.mcpServers.public, { type: "http", url: "https://example.test/mcp" });
  assert.equal(JSON.stringify(config).includes("OPTIONAL"), false);
  const inherited = toMcpConfig([{ name: "private-mcp", pypi: "private", env: [{ name: "TOKEN", isSecret: true }] }]);
  assert.equal(inherited.mcpServers.private.env, undefined);
});

test("detects normalized server-name collisions", () => {
  assert.throws(() => toMcpConfig([
    { name: "alpha-mcp", pypi: "alpha" },
    { name: "alpha", pypi: "alpha-two" }
  ]), /name collision/);
});

test("summarizes read-only and side-effect server counts", () => {
  const summary = summarizeCatalog([
    { name: "safe", pypi: "safe", read_only: true, tools: [{}, {}] },
    { name: "mutable", pypi: "mutable", read_only: false, tools: [{}] }
  ]);
  assert.equal(summary.catalogServers, 2);
  assert.equal(summary.catalogTools, 3);
  assert.equal(summary.readOnlyServers, 1);
  assert.equal(summary.serversWithSideEffects, 1);
});
