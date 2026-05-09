#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import readline from "node:readline";

const rl = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
const pendingToolCalls = new Map();
const activeRuns = new Map();

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

function extractAssistantError(messages) {
  if (!Array.isArray(messages)) return "";
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (!message || typeof message !== "object") continue;
    if (message.role !== "assistant" && message.type !== "assistant") continue;
    if (typeof message.errorMessage === "string" && message.errorMessage.trim()) {
      return message.errorMessage.trim();
    }
  }
  return "";
}

function extractAssistantTextFromSessionFile(sessionFile, afterLine = 0) {
  if (!sessionFile || !fs.existsSync(sessionFile)) return "";
  try {
    const lines = fs.readFileSync(sessionFile, "utf8").split(/\r?\n/).filter(Boolean);
    for (let index = lines.length - 1; index >= 0; index -= 1) {
      if (index < afterLine) break;
      const entry = JSON.parse(lines[index]);
      const message = entry?.type === "message" ? entry.message : entry;
      if (!message || message.role !== "assistant") continue;
      const text = contentToText(message.content);
      if (text.trim()) return text.trim();
    }
  } catch (_error) {
    return "";
  }
  return "";
}

function extractAssistantErrorFromSessionFile(sessionFile, afterLine = 0) {
  if (!sessionFile || !fs.existsSync(sessionFile)) return "";
  try {
    const lines = fs.readFileSync(sessionFile, "utf8").split(/\r?\n/).filter(Boolean);
    for (let index = lines.length - 1; index >= 0; index -= 1) {
      if (index < afterLine) break;
      const entry = JSON.parse(lines[index]);
      const message = entry?.type === "message" ? entry.message : entry;
      if (!message || message.role !== "assistant") continue;
      if (typeof message.errorMessage === "string" && message.errorMessage.trim()) {
        return message.errorMessage.trim();
      }
    }
  } catch (_error) {
    return "";
  }
  return "";
}

function countSessionFileLines(sessionFile) {
  if (!sessionFile || !fs.existsSync(sessionFile)) return 0;
  try {
    return fs.readFileSync(sessionFile, "utf8").split(/\r?\n/).filter(Boolean).length;
  } catch (_error) {
    return 0;
  }
}

function messageText(message) {
  return contentToText(message?.content || "");
}

function sessionFileContainsUserMessage(sessionFile, expectedText) {
  if (!sessionFile || !fs.existsSync(sessionFile)) return false;
  try {
    const lines = fs.readFileSync(sessionFile, "utf8").split(/\r?\n/).filter(Boolean);
    for (let index = lines.length - 1; index >= 0; index -= 1) {
      const entry = JSON.parse(lines[index]);
      const message = entry?.type === "message" ? entry.message : entry;
      if (message?.role === "user" && messageText(message) === expectedText) return true;
    }
  } catch (_error) {
    return false;
  }
  return false;
}

function findSessionFileForRun(sessionDir, runStartedAtMs, expectedText) {
  try {
    return fs
      .readdirSync(sessionDir)
      .filter((name) => name.endsWith(".jsonl"))
      .map((name) => path.join(sessionDir, name))
      .filter((file) => fs.statSync(file).mtimeMs >= runStartedAtMs - 1000)
      .sort((left, right) => fs.statSync(right).mtimeMs - fs.statSync(left).mtimeMs)
      .find((file) => sessionFileContainsUserMessage(file, expectedText)) || "";
  } catch (_error) {
    return "";
  }
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

function toolResultKey(requestId, id) {
  return `${String(requestId || "")}:${String(id || "")}`;
}

function waitForToolResult(requestId, id, signal) {
  return new Promise((resolve, reject) => {
    const key = toolResultKey(requestId, id);
    if (signal?.aborted) {
      reject(new Error("Tool call aborted."));
      return;
    }
    const onAbort = () => {
      pendingToolCalls.delete(key);
      reject(new Error("Tool call aborted."));
    };
    if (signal) signal.addEventListener("abort", onAbort, { once: true });
    pendingToolCalls.set(key, (payload) => {
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

function buildCustomTools({ krillTools, defineTool, requestId }) {
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
          request_id: requestId,
          id: toolCallId,
          tool_name: name,
          mcp_id: mcpId,
          mcp_label: String(tool.mcp_label || mcpId),
          tool_id: toolId,
          tool_label: String(tool.tool_label || toolId),
          arguments: params && typeof params === "object" ? params : {},
        });
        const result = await waitForToolResult(requestId, toolCallId, signal);
        return {
          content: [{ type: "text", text: JSON.stringify(result) }],
          details: result,
        };
      },
    });
  });
}

function normalizeHistory(history) {
  if (!Array.isArray(history)) return [];
  return history
    .map((entry) => ({
      role: String(entry?.role || "").trim().toLowerCase(),
      content: String(entry?.content || "").trim(),
    }))
    .filter((entry) => ["system", "user", "assistant"].includes(entry.role) && entry.content);
}

function hydrateKrillHistory(sessionManager, history) {
  const normalized = normalizeHistory(history);
  if (!normalized.length || sessionManager.buildSessionContext().messages.length > 0) {
    return;
  }
  for (const entry of normalized) {
    if (entry.role === "system") {
      sessionManager.appendCustomMessageEntry(
        "krill_runtime_context",
        entry.content,
        false,
        { source: "krill_chat_history" },
      );
      continue;
    }
    sessionManager.appendMessage({
      role: entry.role,
      content: [{ type: "text", text: entry.content }],
      timestamp: Date.now(),
    });
  }
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

function emitForRequest(requestId, payload) {
  emit({ request_id: requestId, ...payload });
}

function emitRelevantEvent(requestId, event) {
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
    emitForRequest(requestId, { type: "event", event });
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

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function waitForAssistantTextFromSessionFile(getSessionFiles, startLinesByFile, signal) {
  return new Promise((resolve, reject) => {
    let timeout = null;
    const cleanup = () => {
      if (timeout) clearTimeout(timeout);
      if (signal) signal.removeEventListener("abort", onAbort);
    };
    const onAbort = () => {
      cleanup();
      reject(new Error("Assistant text watch aborted."));
    };
    const poll = () => {
      const files = getSessionFiles();
      for (const sessionFile of files) {
        if (!sessionFile) continue;
        const text = extractAssistantTextFromSessionFile(sessionFile, startLinesByFile.get(sessionFile) || 0);
        if (text.trim()) {
          cleanup();
          resolve(text.trim());
          return;
        }
      }
      timeout = setTimeout(poll, 200);
    };
    if (signal?.aborted) {
      onAbort();
      return;
    }
    if (signal) signal.addEventListener("abort", onAbort, { once: true });
    poll();
  });
}

async function runFake(request, requestId) {
  const response = process.env.KRILL_PI_FAKE_RESPONSE || "";
  emitForRequest(requestId, { type: "event", event: { type: "agent_start" } });
  if (request.krill_tools?.length) {
    const tool = request.krill_tools[0];
    emitForRequest(requestId, {
      type: "tool_call",
      id: "fake-tool-1",
      tool_name: sanitizeToolName(`krill_${tool.mcp_id}_${tool.tool_id}`),
      mcp_id: tool.mcp_id,
      mcp_label: tool.mcp_label,
      tool_id: tool.tool_id,
      tool_label: tool.tool_label,
      arguments: {},
    });
    await waitForToolResult(requestId, "fake-tool-1");
  }
  emitForRequest(requestId, { type: "event", event: { type: "agent_end", messages: [] } });
  emitForRequest(requestId, {
    type: "result",
    text: response || `Pi fake response: ${request.message}`,
    session_file: "",
    session_id: request.session_key || "",
    stats: { tokens: { total: 123 }, contextUsage: { tokens: 123, contextWindow: 1000, percent: 12.3 } },
  });
}

async function runReal(request, requestId) {
  const sdk = await loadPiSdk();
  const piAi = await loadPiAi();
  const {
    AuthStorage,
    ModelRegistry,
    SessionManager,
    SettingsManager,
    createAgentSession,
    createCodingTools,
    defineTool,
    DefaultResourceLoader,
  } = sdk;

  const cwd = request.cwd || process.cwd();
  const dataDir = request.pi_data_dir || path.join(cwd, "data", "pi_sessions");
  const agentDir = path.join(dataDir, "agent");
  const sessionDir = path.join(dataDir, "sessions");
  ensureDir(dataDir);
  ensureDir(agentDir);
  ensureDir(sessionDir);
  const mapPath = path.join(dataDir, "session-map.json");
  const sessionMap = readJsonFile(mapPath, {});
  const sessionKey = String(request.session_key || "default");

  const authStorage = AuthStorage.create(path.join(dataDir, "auth.json"));
  if (request.provider?.api_key) {
    authStorage.setRuntimeApiKey(request.provider.provider, request.provider.api_key);
    const envName = providerEnvName(request.provider.provider);
    if (envName) process.env[envName] = request.provider.api_key;
  }
  const modelRegistry = ModelRegistry.create(authStorage, path.join(dataDir, "models.json"));
  const settingsManager = SettingsManager.create(cwd, agentDir);
  const model =
    piAi.getModel?.(request.provider?.provider, request.provider?.model) ||
    modelRegistry.find?.(request.provider?.provider, request.provider?.model);
  if (!model) {
    throw new Error(`Pi model is not available: ${request.provider?.provider}/${request.provider?.model}`);
  }

  const loader = new DefaultResourceLoader({
    cwd,
    agentDir,
    settingsManager,
    systemPromptOverride: () => String(request.system_prompt || ""),
  });
  await loader.reload();

  const existingSession = sessionMap[sessionKey];
  const sessionManager = existingSession && fs.existsSync(existingSession)
    ? SessionManager.open(existingSession, sessionDir, cwd)
    : SessionManager.create(cwd, sessionDir);
  hydrateKrillHistory(sessionManager, request.history);

  const customTools = buildCustomTools({ krillTools: request.krill_tools || [], defineTool, requestId });
  const { session } = await createAgentSession({
    cwd,
    agentDir,
    resourceLoader: loader,
    sessionManager,
    authStorage,
    modelRegistry,
    settingsManager,
    model,
    thinkingLevel: "off",
    tools: createCodingTools(cwd),
    customTools,
  });

  const abortController = new AbortController();
  activeRuns.set(requestId, { abortController, session });
  let assistantText = "";
  const requestMessage = String(request.message || "");
  const runStartedAtMs = Date.now();
  const initialSessionFile = session.sessionFile || sessionManager.sessionFile || existingSession || "";
  const startLinesByFile = new Map();
  if (initialSessionFile) {
    startLinesByFile.set(initialSessionFile, countSessionFileLines(initialSessionFile));
  }
  const getSessionFiles = () => {
    const candidates = [
      session.sessionFile,
      sessionManager.sessionFile,
      initialSessionFile,
      findSessionFileForRun(sessionDir, runStartedAtMs, requestMessage),
    ];
    return [...new Set(candidates.filter(Boolean))];
  };
  let resolveAgentEnd;
  const agentEndPromise = new Promise((resolve) => {
    resolveAgentEnd = resolve;
  });
  const unsubscribe = session.subscribe((event) => {
    emitRelevantEvent(requestId, event);
    if (event?.type === "message_update" && event.assistantMessageEvent?.type === "text_delta") {
      assistantText += String(event.assistantMessageEvent.delta || "");
    }
    if (event?.type === "agent_end") {
      const finalText = extractAssistantText(event.messages);
      if (finalText) assistantText = finalText;
      resolveAgentEnd?.();
    }
  });

  let promptSettled = false;
  let promptError = null;
  const promptPromise = session
    .prompt(String(request.message || ""), { signal: abortController.signal })
    .then(() => {
      promptSettled = true;
    })
    .catch((error) => {
      promptSettled = true;
      promptError = error;
    });
  const fileTextPromise = waitForAssistantTextFromSessionFile(
    getSessionFiles,
    startLinesByFile,
    abortController.signal,
  )
    .then((text) => {
      if (text) assistantText = text;
    })
    .catch(() => {});

  try {
    await Promise.race([promptPromise, agentEndPromise, fileTextPromise]);
    if (!promptSettled) {
      await Promise.race([promptPromise, delay(250)]);
    }
    if (promptError) {
      throw promptError;
    }
  } finally {
    if (!promptSettled) {
      abortController.abort();
      promptPromise.catch(() => {});
    }
    unsubscribe?.();
    activeRuns.delete(requestId);
  }

  if (session.sessionFile) {
    sessionMap[sessionKey] = session.sessionFile;
    writeJsonFile(mapPath, sessionMap);
  }

  const finalText = (
    assistantText.trim()
    || extractAssistantText(session.messages)
    || extractAssistantTextFromSessionFile(session.sessionFile)
  );
  const finalError = (
    !finalText
      ? (extractAssistantError(session.messages) || extractAssistantErrorFromSessionFile(session.sessionFile))
      : ""
  );

  if (finalError) {
    emitForRequest(requestId, {
      type: "error",
      error: `Pi provider error: ${finalError}`,
    });
    session.dispose?.();
    return;
  }

  emitForRequest(requestId, {
    type: "result",
    text: finalText,
    session_file: session.sessionFile || "",
    session_id: session.sessionId || "",
    stats: computeStats(session),
  });
  session.dispose?.();
}

async function handleHealth(requestId) {
  try {
    if (process.env.KRILL_PI_FAKE !== "1") {
      await loadPiSdk();
      await loadPiAi();
    }
    emitForRequest(requestId, { type: "ready" });
  } catch (error) {
    emitForRequest(requestId, { type: "error", error: error?.stack || error?.message || String(error) });
  }
}

async function handleRequest(request, requestId) {
  try {
    if (process.env.KRILL_PI_FAKE === "1") {
      await runFake(request, requestId);
      return;
    }
    await runReal(request, requestId);
  } catch (error) {
    activeRuns.delete(requestId);
    emitForRequest(requestId, { type: "error", error: error?.stack || error?.message || String(error) });
  }
}

function cancelRequest(requestId) {
  const active = activeRuns.get(requestId);
  if (!active) {
    emitForRequest(requestId, { type: "cancelled" });
    return;
  }
  active.abortController?.abort?.();
  active.session?.agent?.cancel?.();
  active.session?.agent?.abort?.();
  active.session?.dispose?.();
  activeRuns.delete(requestId);
  emitForRequest(requestId, { type: "cancelled" });
}

async function closeSidecar() {
  for (const requestId of activeRuns.keys()) {
    cancelRequest(requestId);
  }
  process.exit(0);
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
    const resolver = pendingToolCalls.get(toolResultKey(payload.request_id, payload.id));
    if (resolver) {
      pendingToolCalls.delete(toolResultKey(payload.request_id, payload.id));
      resolver(payload);
    }
    return;
  }
  const requestId = String(payload.request_id || payload.request?.request_id || "");
  if (payload.type === "health") {
    handleHealth(requestId || "health");
    return;
  }
  if (payload.type === "cancel") {
    cancelRequest(requestId);
    return;
  }
  if (payload.type === "shutdown") {
    closeSidecar();
    return;
  }
  if (payload.type === "run") {
    handleRequest(payload.request, requestId || String(payload.request?.session_key || "default"));
  }
});
