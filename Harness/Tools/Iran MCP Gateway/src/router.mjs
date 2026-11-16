const TOKEN_RE = /[\p{L}\p{N}_-]+/gu;
const MUTATING_RE = /(?:^|[_-])(create|add|update|edit|delete|remove|send|message|pay|payment|transfer|withdraw|deposit|purchase|buy|order|checkout|cancel|refund|login|logout|verify|otp|sms|submit|book|reserve|publish|post|upload|write|execute|run|change|set|invite|revoke|approve)(?:$|[_-])/i;

function tokens(value) {
  return new Set(String(value ?? "").toLocaleLowerCase().match(TOKEN_RE) ?? []);
}

function toolKey(serverName, toolName) {
  return `${serverName}::${toolName}`;
}

function isMutatingTool(tool) {
  if (tool.read_only === false) return true;
  if (tool.read_only === true) return false;
  return MUTATING_RE.test(tool.name) || MUTATING_RE.test(tool.title ?? "");
}

function normalizeTool(server, tool) {
  return {
    serverName: server.name,
    serverTitle: server.title ?? server.name,
    category: server.category ?? "other",
    serverReadOnly: server.read_only === true,
    name: tool.name,
    title: tool.title ?? tool.name,
    summary: tool.summary ?? "",
    readOnly: tool.read_only === true && server.read_only === true,
    requiresApproval: server.read_only !== true || tool.read_only !== true || isMutatingTool(tool)
  };
}

/**
 * In-memory registry for tools exposed by already-connected MCP clients.
 * The host owns transports, credentials, UI confirmation and client lifecycle.
 */
export class McpToolRegistry {
  #catalog = new Map();
  #clients = new Map();
  #tools = new Map();

  constructor(catalog = []) {
    for (const server of catalog) {
      if (!server?.name || this.#catalog.has(server.name)) {
        throw new Error(`Invalid or duplicate catalog server: ${server?.name}`);
      }
      this.#catalog.set(server.name, server);
    }
  }

  registerClient(serverName, client) {
    if (!this.#catalog.has(serverName)) throw new Error(`Server is not in the approved catalog: ${serverName}`);
    if (!client || typeof client.listTools !== "function" || typeof client.callTool !== "function") {
      throw new TypeError("MCP client must implement listTools() and callTool()");
    }
    this.#clients.set(serverName, client);
  }

  unregisterClient(serverName) {
    this.#clients.delete(serverName);
    for (const key of this.#tools.keys()) {
      if (key.startsWith(`${serverName}::`)) this.#tools.delete(key);
    }
  }

  async refreshServer(serverName) {
    const client = this.#clients.get(serverName);
    const server = this.#catalog.get(serverName);
    if (!client || !server) throw new Error(`MCP server is not connected: ${serverName}`);
    const response = await client.listTools();
    if (!Array.isArray(response?.tools)) throw new Error(`Invalid tools/list response from ${serverName}`);

    const next = new Map();
    for (const remoteTool of response.tools) {
      if (!remoteTool || typeof remoteTool.name !== "string" || !remoteTool.name) continue;
      const metadata = (server.tools ?? []).find(item => item.name === remoteTool.name);
      if (!metadata) {
        // Unknown upstream tools are not callable until the catalog is refreshed and reviewed.
        continue;
      }
      const tool = normalizeTool(server, { ...metadata, ...remoteTool });
      next.set(toolKey(serverName, tool.name), { ...tool, inputSchema: remoteTool.inputSchema ?? { type: "object" } });
    }
    for (const key of this.#tools.keys()) {
      if (key.startsWith(`${serverName}::`)) this.#tools.delete(key);
    }
    for (const [key, tool] of next) this.#tools.set(key, tool);
    return [...next.values()].map(publicTool);
  }

  async refreshAll() {
    const results = await Promise.allSettled([...this.#clients.keys()].map(name => this.refreshServer(name)));
    return results.map((result, index) => ({
      serverName: [...this.#clients.keys()][index],
      status: result.status,
      ...(result.status === "fulfilled" ? { toolCount: result.value.length } : { error: result.reason?.message ?? String(result.reason) })
    }));
  }

  listTools() {
    return [...this.#tools.values()].map(publicTool);
  }

  discover(query, { limit = 12, category } = {}) {
    const queryTokens = tokens(query);
    if (!queryTokens.size) return [];
    const ranked = [];
    for (const tool of this.#tools.values()) {
      if (category && tool.category !== category) continue;
      const nameTokens = tokens(tool.name);
      const titleTokens = tokens(tool.title);
      const summaryTokens = tokens(tool.summary);
      let score = 0;
      for (const token of queryTokens) {
        if (nameTokens.has(token)) score += 8;
        if (titleTokens.has(token)) score += 5;
        if (summaryTokens.has(token)) score += 2;
        if (tool.category === token) score += 3;
      }
      if (score > 0) ranked.push({ ...publicTool(tool), score });
    }
    return ranked.sort((a, b) => b.score - a.score || a.serverName.localeCompare(b.serverName) || a.name.localeCompare(b.name)).slice(0, Math.max(1, limit));
  }

  async callTool({ serverName, toolName, arguments: args = {}, authorize, audit = () => {} }) {
    const key = toolKey(serverName, toolName);
    const tool = this.#tools.get(key);
    const client = this.#clients.get(serverName);
    if (!tool || !client) throw new Error(`Tool is not registered or server disconnected: ${key}`);

    if (tool.requiresApproval) {
      if (typeof authorize !== "function") {
        return { status: "approval_required", tool: publicTool(tool), executed: false };
      }
      const approved = await authorize({
        action: "mcp_tool_call",
        serverName,
        toolName,
        title: tool.title,
        summary: tool.summary,
        arguments: args
      });
      if (approved !== true) {
        await audit({ type: "mcp.tool.denied", serverName, toolName, at: new Date().toISOString() });
        return { status: "denied", executed: false };
      }
    }

    await audit({ type: "mcp.tool.started", serverName, toolName, at: new Date().toISOString() });
    try {
      const result = await client.callTool({ name: toolName, arguments: args });
      await audit({ type: "mcp.tool.completed", serverName, toolName, at: new Date().toISOString() });
      return { status: "completed", executed: true, result };
    } catch (error) {
      await audit({ type: "mcp.tool.failed", serverName, toolName, error: error?.message ?? String(error), at: new Date().toISOString() });
      throw error;
    }
  }

  get connectedServers() {
    return [...this.#clients.keys()];
  }
}

function publicTool(tool) {
  const { inputSchema, ...safe } = tool;
  return { ...safe, inputSchema };
}
