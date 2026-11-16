import { chmod, mkdir, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { loadCatalog, toMcpConfig } from "./catalog.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "..");
const target = resolve(process.argv[2] ?? resolve(root, ".mcp.iran.json"));
const catalog = await loadCatalog();
const config = toMcpConfig(catalog);
await mkdir(dirname(target), { recursive: true });
await writeFile(target, JSON.stringify(config, null, 2) + "\n", { mode: 0o600 });
await chmod(target, 0o600);
const tools = catalog.reduce((sum, server) => sum + (server.tools?.length ?? 0), 0);
const local = Object.values(config.mcpServers).filter(server => server.command).length;
const remote = Object.values(config.mcpServers).filter(server => server.url).length;
console.log(JSON.stringify({ catalogServers: catalog.length, catalogTools: tools, configuredServers: Object.keys(config.mcpServers).length, localPackageServers: local, hostedServers: remote, output: target }, null, 2));
console.log("Note: package servers are configured for uvx execution; first invocation downloads packages. Hosted OAuth servers require user authorization in the MCP client. Secrets are not written to the config.");
