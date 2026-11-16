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

export function toMcpConfig(catalog, environment = process.env) {
  const mcpServers = {};
  for (const server of catalog) {
    const key = server.name.replace(/-mcp$/, "");
    if (server.url) {
      mcpServers[key] = { type: "http", url: server.url };
    } else if (server.pypi || server.run) {
      const packageName = server.pypi ?? server.name;
      const env = Object.fromEntries(
        (server.env ?? [])
          .filter(item => environment[item.name] !== undefined)
          .map(item => [item.name, environment[item.name]])
      );
      mcpServers[key] = { command: "uvx", args: [packageName], ...(Object.keys(env).length ? { env } : {}) };
    }
  }
  return { mcpServers };
}
