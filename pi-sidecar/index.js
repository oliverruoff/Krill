#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import readline from "node:readline";

const rl = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
const pendingToolCalls = new Map();

function emit(payload) {
  process.stdout.write(`${JSON.stringify(payload)}\n`);
}

function sanitizeToolName(value) {
  return String(value || "")
    .trim()
    .replace(/[^a-zA-Z0-9_-]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 96) || "krill_tool";
}

function contentToText(content) {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  return content
    .map((part) => {
      if (!part || typeof part !== "object") return "";
      if (typeof part.text === "string") return part.text;
      return "";
    })
    .filter(Boolean)
    .join("");
}

function extractAssistantText(messages) {
  if (!Array.isArray(messages)) return "";
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (!message || typeof message !== "object") continue;
    if (message.role !== "assistant" && message.type !== "assistant") continue;
    const text = contentToText(message.content);
    if (text.trim()) return text.trim();
  }
  return "";
}

function ensureDir(dir) {
  fs.mkdirSync(dir, { recursive: true });
}

function readJsonFile(filePath, fallback) {
  try {
    return JSON.parse(fs.readFileSync(filePath, "utf8"));
  } catch (_error) {
    return fallback;
  }
}

function writeJsonFile(filePath, payload) {
  ensureDir(path.dirname(filePath));
  fs.writeFileSync(filePath, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
}

function waitForToolResult(id, signal) {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new Error("Tool call aborted."));
      return;
    }
    const onAbort = () => {
      pendingToolCalls.delete(id);
      reject(new Error("Tool call aborted."));
    };
    if (signal) signal.addEventListener("abort", onAbort, { once: true });
    pendingToolCalls.set(id, (payload) => {
      if (signal) signal.removeEventListener("abort", onAbort);
      if (payload && payload.ok === false) {
        reject(new Error(String(payload.error || "Krill MCP tool failed.")));
        return;
      }
      resolve(payload?.result || {});
    });
  });
}

function toTypeboxSchema(schema) {
  if (schema && typeof schema === "object" && !Array.isArray(schema)) return schema;
  return { type: "object", properties: {}, additionalProperties: true };
}

function buildCustomTools({ krillTools, defineTool }) {
  return krillTools.map((tool) => {
    const mcpId = String(tool.mcp_id || "");
    const toolId = String(tool.tool_id || "");
    const name = sanitizeToolName(`krill_${mcpId}_${toolId}`);
    return defineTool({
      name,
      label: String(tool.tool_label || toolId || name),
      description: String(tool.tool_description || ""),
      parameters: toTypeboxSchema(tool.input_schema),
      async execute(toolCallId, params, signal, onUpdate) {
        onUpdate?.({ status: "calling_krill_mcp", mcp_id: mcpId, tool_id: toolId });
        emit({
          type: "tool_call",
          id: toolCallId,
          tool_name: name,
          mcp_id: mcpId,
          mcp_label: String(tool.mcp_label || mcpId),
          tool_id: toolId,
          tool_label: String(tool.tool_label || toolId),
          arguments: params && typeof params === "object" ? params : {},
        });
        const result = await waitForToolResult(toolCallId, signal);
        return {
          content: [{ type: "text", text: JSON.stringify(result) }],
          details: result,
        };
      },
    });
  });
}

async function loadPiSdk() {
  return import("@earendil-works/pi-coding-agent");
}

async function loadPiAi() {
  return import("@earendil-works/pi-ai");
}

function providerEnvName(provider) {
  const map = {
    google: "GEMINI_API_KEY",
    openai: "OPENAI_API_KEY",
    openrouter: "OPENROUTER_API_KEY",
    minimax: "MINIMAX_API_KEY",
  };
  return map[provider] || "";
}

function emitRelevantEvent(event) {
  if (!event || typeof event !== "object") return;
  const allowed = new Set([
    "agent_start",
    "agent_end",
    "tool_execution_start",
    "tool_execution_update",
    "tool_execution_end",
    "compaction_start",
    "compaction_end",
    "auto_retry_start",
    "auto_retry_end",
  ]);
  if (allowed.has(event.type)) {
    emit({ type: "event", event });
  }
}

function computeStats(session) {
  const messages = Array.isArray(session?.messages) ? session.messages : [];
  const stats = {
    tokens: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
    contextUsage: undefined,
    sessionFile: session?.sessionFile,
    sessionId: session?.sessionId,
  };
  for (const message of messages) {
    const usage = message?.usage || message?.metadata?.usage;
    if (!usage || typeof usage !== "object") continue;
    const input = Number(usage.inputTokens ?? usage.input ?? usage.prompt_tokens ?? 0);
    const output = Number(usage.outputTokens ?? usage.output ?? usage.completion_tokens ?? 0);
    const cacheRead = Number(usage.cacheReadTokens ?? usage.cacheRead ?? 0);
    const cacheWrite = Number(usage.cacheWriteTokens ?? usage.cacheWrite ?? 0);
    stats.tokens.input += Number.isFinite(input) ? input : 0;
    stats.tokens.output += Number.isFinite(output) ? output : 0;
    stats.tokens.cacheRead += Number.isFinite(cacheRead) ? cacheRead : 0;
    stats.tokens.cacheWrite += Number.isFinite(cacheWrite) ? cacheWrite : 0;
  }
  stats.tokens.total = stats.tokens.input + stats.tokens.output + stats.tokens.cacheRead + stats.tokens.cacheWrite;
  return stats;
}

async function runFake(request) {
  const response = process.env.KRILL_PI_FAKE_RESPONSE || "";
  emit({ type: "event", event: { type: "agent_start" } });
  if (request.krill_tools?.length) {
    const tool = request.krill_tools[0];
    emit({
      type: "tool_call",
      id: "fake-tool-1",
      tool_name: sanitizeToolName(`krill_${tool.mcp_id}_${tool.tool_id}`),
      mcp_id: tool.mcp_id,
      mcp_label: tool.mcp_label,
      tool_id: tool.tool_id,
      tool_label: tool.tool_label,
      arguments: {},
    });
    await waitForToolResult("fake-tool-1");
  }
  emit({ type: "event", event: { type: "agent_end", messages: [] } });
  emit({
    type: "result",
    text: response || `Pi fake response: ${request.message}`,
    session_file: "",
    session_id: request.session_key || "",
    stats: { tokens: { total: 123 }, contextUsage: { tokens: 123, contextWindow: 1000, percent: 12.3 } },
  });
}

async function runReal(request) {
  const sdk = await loadPiSdk();
  const piAi = await loadPiAi();
  const {
    AuthStorage,
    ModelRegistry,
    SessionManager,
    createAgentSession,
    createCodingTools,
    defineTool,
    DefaultResourceLoader,
  } = sdk;

  const cwd = request.cwd || process.cwd();
  const dataDir = request.pi_data_dir || path.join(cwd, "data", "pi_sessions");
  ensureDir(dataDir);
  const mapPath = path.join(dataDir, "session-map.json");
  const sessionMap = readJsonFile(mapPath, {});
  const sessionKey = String(request.session_key || "default");

  const authStorage = AuthStorage.create(path.join(dataDir, "auth.json"));
  if (request.provider?.api_key) {
    authStorage.setRuntimeApiKey(request.provider.provider, request.provider.api_key);
    const envName = providerEnvName(request.provider.provider);
    if (envName) process.env[envName] = request.provider.api_key;
  }
  const modelRegistry = ModelRegistry.create(authStorage);
  const model =
    piAi.getModel?.(request.provider?.provider, request.provider?.model) ||
    modelRegistry.find?.(request.provider?.provider, request.provider?.model);
  if (!model) {
    throw new Error(`Pi model is not available: ${request.provider?.provider}/${request.provider?.model}`);
  }

  const loader = new DefaultResourceLoader({
    systemPromptOverride: () => String(request.system_prompt || ""),
  });
  await loader.reload();

  const existingSession = sessionMap[sessionKey];
  const sessionManager = existingSession && fs.existsSync(existingSession)
    ? SessionManager.open(existingSession)
    : SessionManager.create(cwd);

  const customTools = buildCustomTools({ krillTools: request.krill_tools || [], defineTool });
  const { session } = await createAgentSession({
    cwd,
    resourceLoader: loader,
    sessionManager,
    authStorage,
    modelRegistry,
    model,
    thinkingLevel: "off",
    tools: createCodingTools(cwd),
    customTools,
  });

  let assistantText = "";
  const unsubscribe = session.subscribe((event) => {
    emitRelevantEvent(event);
    if (event?.type === "message_update" && event.assistantMessageEvent?.type === "text_delta") {
      assistantText += String(event.assistantMessageEvent.delta || "");
    }
    if (event?.type === "agent_end") {
      const finalText = extractAssistantText(event.messages);
      if (finalText) assistantText = finalText;
    }
  });

  await session.prompt(String(request.message || ""));
  await session.agent?.waitForIdle?.();
  unsubscribe?.();

  if (session.sessionFile) {
    sessionMap[sessionKey] = session.sessionFile;
    writeJsonFile(mapPath, sessionMap);
  }

  emit({
    type: "result",
    text: assistantText.trim() || extractAssistantText(session.messages),
    session_file: session.sessionFile || "",
    session_id: session.sessionId || "",
    stats: computeStats(session),
  });
  session.dispose?.();
}

async function handleRequest(request) {
  try {
    if (process.env.KRILL_PI_FAKE === "1") {
      await runFake(request);
      return;
    }
    await runReal(request);
  } catch (error) {
    emit({ type: "error", error: error?.stack || error?.message || String(error) });
  }
}

rl.on("line", (line) => {
  if (!line.trim()) return;
  let payload;
  try {
    payload = JSON.parse(line);
  } catch (error) {
    emit({ type: "error", error: `Invalid JSON input: ${error.message}` });
    return;
  }
  if (payload.type === "tool_result") {
    const resolver = pendingToolCalls.get(payload.id);
    if (resolver) {
      pendingToolCalls.delete(payload.id);
      resolver(payload);
    }
    return;
  }
  if (payload.type === "run") {
    handleRequest(payload.request);
  }
});
