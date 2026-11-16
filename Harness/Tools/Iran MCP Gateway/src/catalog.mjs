import { pathToFileURL } from "node:url";

export const CATALOG_URL = "https://raw.githubusercontent.com/sepehr071/iran-mcp/main/servers.json";

export async function loadCatalog(url = CATALOG_URL, fetchImpl = fetch) {
  const response = await fetchImpl(url, { headers: { "user-agent": "ICARUS-Iran-MCP-Gateway/0.2" } });
  if (!response.ok) throw new Error(`Catalog download failed: HTTP ${response.status}`);
  const entries = await response.json();
  if (!Array.isArray(entries)) throw new Error("Invalid catalog: expected an array");
  const names = new Set();
  for (const server of entries) {
    if (!server || typeof server.name !== "string" || !server.name.trim() || names.has(server.name)) {
      throw new Error(`Invalid or duplicate server name: ${server?.name}`);
    }
    names.add(server.name);
    if (server.url) {
      let parsed;
      try { parsed = new URL(server.url); } catch { throw new Error(`Invalid URL for ${server.name}`); }
      if (!["http:", "https:"].includes(parsed.protocol)) throw new Error(`Unsupported URL protocol for ${server.name}`);
    } else if (!(server.pypi || server.run)) {
      throw new Error(`No supported launch method for ${server.name}`);
    }
    if (server.env !== undefined && !Array.isArray(server.env)) {
      throw new Error(`Invalid environment declaration for ${server.name}`);
    }
    if (!Array.isArray(server.tools)) server.tools = [];
  }
  return entries;
}

export function toMcpConfig(catalog, environment = process.env) {
  const mcpServers = {};
  for (const server of catalog) {
    const key = server.name.replace(/-mcp$/, "");
    if (Object.hasOwn(mcpServers, key)) throw new Error(`MCP config name collision: ${key}`);
    if (server.url) {
      mcpServers[key] = { type: "http", url: server.url };
    } else {
      const packageName = server.pypi ?? server.name;
      const env = Object.fromEntries(
        (server.env ?? [])
          .filter(item => item?.name && environment[item.name] !== undefined)
          .map(item => [item.name, environment[item.name]])
      );
      mcpServers[key] = { command: "uvx", args: [packageName], ...(Object.keys(env).length ? { env } : {}) };
    }
  }
  return { mcpServers };
}

export function summarizeCatalog(catalog, config = toMcpConfig(catalog)) {
  const servers = Object.values(config.mcpServers);
  return {
    catalogServers: catalog.length,
    catalogTools: catalog.reduce((sum, server) => sum + (server.tools?.length ?? 0), 0),
    configuredServers: servers.length,
    localPackageServers: servers.filter(server => server.command).length,
    hostedServers: servers.filter(server => server.url).length,
    readOnlyServers: catalog.filter(server => server.read_only === true).length,
    serversWithSideEffects: catalog.filter(server => server.read_only === false).length
  };
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const catalog = await loadCatalog();
  console.log(JSON.stringify(summarizeCatalog(catalog), null, 2));
}
