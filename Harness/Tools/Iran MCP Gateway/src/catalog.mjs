import { readFile } from "node:fs/promises";

export const CATALOG_URL = "https://raw.githubusercontent.com/sepehr071/iran-mcp/main/servers.json";

export async function loadCatalog(url = CATALOG_URL) {
  const response = await fetch(url, { headers: { "user-agent": "ICARUS-Iran-MCP-Gateway/0.1" } });
  if (!response.ok) throw new Error(`Catalog download failed: HTTP ${response.status}`);
  const entries = await response.json();
  if (!Array.isArray(entries)) throw new Error("Invalid catalog: expected an array");
  const names = new Set();
  for (const server of entries) {
    if (!server.name || names.has(server.name)) throw new Error(`Invalid or duplicate server name: ${server.name}`);
    names.add(server.name);
    if (!Array.isArray(server.tools)) server.tools = [];
  }
  return entries;
}

export function toMcpConfig(catalog) {
  const mcpServers = {};
  for (const server of catalog) {
    if (server.url) {
      mcpServers[server.name.replace(/-mcp$/, "")] = {
        type: "http",
        url: server.url,
        ...(server.auth === "oauth" ? { note: "OAuth authorization is completed by the MCP client." } : {})
      };
    } else if (server.pypi || server.run) {
      const packageName = server.pypi ?? server.name;
      mcpServers[server.name.replace(/-mcp$/, "")] = {
        command: "uvx",
        args: [packageName],
        env: Object.fromEntries((server.env ?? []).map(item => [item.name, process.env[item.name] ?? ""]))
      };
    }
  }
  return { mcpServers };
}
