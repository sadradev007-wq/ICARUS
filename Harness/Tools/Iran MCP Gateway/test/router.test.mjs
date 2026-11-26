import test from "node:test";
import assert from "node:assert/strict";
import { McpToolRegistry } from "../src/router.mjs";

const catalog = [
  {
    name: "shop-mcp", title: "Shopping", category: "shopping", read_only: true,
    tools: [
      { name: "product_search", title: "Search products", summary: "Find products by name", read_only: true },
      { name: "checkout_order", title: "Checkout order", summary: "Place an order", read_only: false }
    ]
  },
  {
    name: "wallet-mcp", title: "Wallet", category: "finance", read_only: false,
    tools: [
      { name: "get_balance", title: "Get balance", summary: "Read wallet balance", read_only: true },
      { name: "wallet_transfer", title: "Transfer money", summary: "Send money to another account" }
    ]
  }
];

function setup() {
  const calls = [];
  const registry = new McpToolRegistry(catalog);
  registry.registerClient("shop-mcp", {
    listTools: async () => ({ tools: catalog[0].tools.map(t => ({ ...t, inputSchema: { type: "object" } })) }),
    callTool: async payload => { calls.push(payload); return { content: [{ type: "text", text: "ok" }] }; }
  });
  registry.registerClient("wallet-mcp", {
    listTools: async () => ({ tools: catalog[1].tools.map(t => ({ ...t })) }),
    callTool: async payload => { calls.push(payload); return { ok: true }; }
  });
  return { registry, calls };
}

test("refreshes connected MCP clients and ignores tools absent from the reviewed catalog", async () => {
  const { registry } = setup();
  await registry.refreshServer("shop-mcp");
  assert.equal(registry.listTools().length, 2);
  assert.throws(() => registry.registerClient("unknown", {}), /not in the approved catalog/);
});

test("discovers relevant tools by name, title and description", async () => {
  const { registry } = setup();
  await registry.refreshAll();
  assert.equal(registry.discover("search products")[0].name, "product_search");
  assert.equal(registry.discover("money transfer", { category: "finance" })[0].name, "wallet_transfer");
});

test("allows catalog-confirmed read-only tool without approval", async () => {
  const { registry, calls } = setup();
  await registry.refreshAll();
  const result = await registry.callTool({ serverName: "shop-mcp", toolName: "product_search", arguments: { q: "tea" } });
  assert.equal(result.status, "completed");
  assert.equal(calls.length, 1);
});

test("requires explicit approval for mutating tools and does not execute on denial", async () => {
  const { registry, calls } = setup();
  await registry.refreshAll();
  const pending = await registry.callTool({ serverName: "shop-mcp", toolName: "checkout_order" });
  assert.equal(pending.status, "approval_required");
  assert.equal(calls.length, 0);
  const denied = await registry.callTool({ serverName: "shop-mcp", toolName: "checkout_order", authorize: async () => false });
  assert.equal(denied.status, "denied");
  assert.equal(calls.length, 0);
  const approved = await registry.callTool({ serverName: "shop-mcp", toolName: "checkout_order", authorize: async () => true });
  assert.equal(approved.status, "completed");
  assert.equal(calls.length, 1);
});

test("treats every tool on a non-read-only server as approval-required", async () => {
  const { registry, calls } = setup();
  await registry.refreshAll();
  const result = await registry.callTool({ serverName: "wallet-mcp", toolName: "get_balance" });
  assert.equal(result.status, "approval_required");
  assert.equal(calls.length, 0);
});

test("writes audit events and propagates tool errors", async () => {
  const { registry } = setup();
  const events = [];
  await registry.refreshAll();
  await registry.callTool({ serverName: "shop-mcp", toolName: "product_search", audit: event => events.push(event) });
  assert.deepEqual(events.map(event => event.type), ["mcp.tool.started", "mcp.tool.completed"]);
});

test("fails closed when a tool omits read_only metadata", async () => {
  const registry = new McpToolRegistry([{ name: "uncertain-mcp", read_only: true, tools: [{ name: "unknown_action" }] }]);
  let calls = 0;
  registry.registerClient("uncertain-mcp", {
    listTools: async () => ({ tools: [{ name: "unknown_action" }] }),
    callTool: async () => { calls += 1; return {}; }
  });
  await registry.refreshAll();
  const result = await registry.callTool({ serverName: "uncertain-mcp", toolName: "unknown_action" });
  assert.equal(result.status, "approval_required");
  assert.equal(calls, 0);
});
