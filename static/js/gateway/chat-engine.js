import { state, RUNTIME_CONTEXT_SYSTEM_TYPE } from "./state.js";
import { chatInput } from "./dom.js";
import {
  setStatus,
  createTimestamp,
  createLocalRequestId,
  createClientEnqueueId,
  buildEnqueueDraftKey,
  normalizeErrorMessage,
  syncChatInputHeight,
  buildHttpErrorDetail,
  normalizeChatTitle,
  deriveChatTitle,
} from "./utils.js";
import { showToast, sendAssistantResponseNotification, requestNotificationPermissionIfNeeded } from "./toast.js";
import { getChatRuntime } from "./chat-runtime.js";
import { clearPendingImageAttachment, clonePendingImageAttachment, renderPendingImageAttachment } from "./image-upload.js";

function normalizeToolUsage(toolUsage) {
  if (!Array.isArray(toolUsage)) {
    return [];
  }

  return toolUsage
    .filter((entry) => entry && typeof entry === "object")
    .map((entry) => ({
      mcp_id: typeof entry.mcp_id === "string" ? entry.mcp_id : "",
      mcp_label: typeof entry.mcp_label === "string" ? entry.mcp_label : "",
      tool_id: typeof entry.tool_id === "string" ? entry.tool_id : "",
      tool_label: typeof entry.tool_label === "string" ? entry.tool_label : "",
    }))
    .filter((entry) => entry.mcp_id && entry.tool_id);
}

function toApiChatHistory(messages) {
  return messages
    .filter((turn) => turn && (turn.role === "user" || turn.role === "assistant" || turn.role === "system"))
    .filter((turn) => typeof turn.content === "string" && turn.content.trim())
    .filter((turn) => {
      if (turn.role !== "system") {
        return true;
      }
      return turn.system_type === RUNTIME_CONTEXT_SYSTEM_TYPE;
    })
    .map((turn) => ({ role: turn.role, content: turn.content }));
}

function processSseBlock(block, context) {
  const lines = block.split("\n");
  let eventName = "message";
  let data = "";

  lines.forEach((line) => {
    if (line.startsWith("event:")) {
      eventName = line.slice(6).trim();
      return;
    }

    if (line.startsWith("data:")) {
      data += line.slice(5).trim();
    }
  });

  if (!data) {
    return { done: false, hasError: false };
  }

  let payload = {};
  try {
    payload = JSON.parse(data);
  } catch (error) {
    const preview = data.length > 160 ? `${data.slice(0, 160)}...` : data;
    return { done: false, hasError: true, errorMessage: `Invalid stream payload: ${preview}` };
  }

  if (eventName === "token") {
    context.assistantMessage.content = `${context.assistantMessage.content || ""}${payload.text ?? ""}`;
    context.assistantMessage.status = "processing";
    if (state.activeChatId === context.chatId) {
      _renderActiveChat();
    }
    return { done: false, hasError: false };
  }

  if (eventName === "meta") {
    const requestUsedTokens = Number(payload.used_tokens ?? 0);
    if (Number.isFinite(requestUsedTokens) && requestUsedTokens > 0) {
      context.usedTokens = requestUsedTokens;
      if (state.activeChatId === context.chatId) {
        state.lastRequestTokens = requestUsedTokens;
        _syncUsedTokensToContext();
      }
    }

    context.toolUsage = normalizeToolUsage(payload.used_mcp_tools);
    const metaTrace = Array.isArray(payload.system_trace_messages)
      ? payload.system_trace_messages
          .filter((entry) => entry && typeof entry === "object")
          .map((entry) => ({
            system_type: typeof entry.system_type === "string" ? entry.system_type : "orchestrator",
            content: typeof entry.content === "string" ? entry.content : "",
          }))
          .filter((entry) => entry.content)
      : [];
    if (metaTrace.length > 0) {
      const merged = [...context.systemTrace];
      metaTrace.forEach((entry) => {
        const exists = merged.some((item) => item.system_type === entry.system_type && item.content === entry.content);
        if (!exists) {
          merged.push(entry);
        }
      });
      context.systemTrace = merged;
    }

    const executionTrace = Array.isArray(payload.execution_events)
      ? payload.execution_events
          .filter((entry) => entry && typeof entry === "object")
          .map((entry) => ({
            system_type: typeof entry.event_type === "string" ? `execution_${entry.event_type}` : "execution_progress",
            content: typeof entry.message === "string" ? entry.message : "",
          }))
          .filter((entry) => entry.content)
      : [];
    if (executionTrace.length > 0) {
      const merged = [...context.systemTrace];
      executionTrace.forEach((entry) => {
        const exists = merged.some((item) => item.system_type === entry.system_type && item.content === entry.content);
        if (!exists) {
          merged.push(entry);
        }
      });
      context.systemTrace = merged;
    }

    if (payload.token_limit && state.activeChatId === context.chatId) {
      _updateTokenCounter(state.usedTokens, payload.token_limit ?? state.modelTokenLimit);
    }
    return { done: false, hasError: false };
  }

  if (eventName === "tool_step" || eventName === "progress") {
    const entry = {
      system_type: typeof payload.system_type === "string" ? payload.system_type : "tool_step",
      content: typeof payload.content === "string"
        ? payload.content
        : (typeof payload.message === "string" ? payload.message : ""),
    };

    if (entry.content) {
      const duplicate = context.systemTrace.some(
        (item) => item.system_type === entry.system_type && item.content === entry.content,
      );
      if (!duplicate) {
        context.systemTrace.push(entry);
        const chat = state.chats.find((entryChat) => entryChat.id === context.chatId);
        if (chat) {
          appendSystemTraceMessages(chat, [entry], createTimestamp(), context.requestId);
          chat.updated_at = createTimestamp();
          if (state.activeChatId === context.chatId) {
            _renderActiveChat();
          }
          _renderChatHistory();
        }
      }
    }
    return { done: false, hasError: false };
  }

  if (eventName === "done") {
    return { done: true, hasError: false };
  }

  if (eventName === "error") {
    return {
      done: true,
      hasError: true,
      errorMessage: payload.detail ?? "Chat failed.",
    };
  }

  return { done: false, hasError: false };
}

function appendSystemTraceMessages(chat, traceMessages, timestamp, requestId = "") {
  if (!Array.isArray(traceMessages) || traceMessages.length === 0) {
    return;
  }

  traceMessages.forEach((entry) => {
    if (!entry || typeof entry !== "object") {
      return;
    }

    const content = typeof entry.content === "string" ? entry.content.trim() : "";
    if (!content) {
      return;
    }

    const duplicate = chat.messages.some(
      (message) =>
        message.role === "system" &&
        message.request_id === requestId &&
        message.system_type === (typeof entry.system_type === "string" ? entry.system_type : "orchestrator") &&
        message.content === content,
    );
    if (duplicate) {
      return;
    }

    chat.messages.push({
      role: "system",
      content,
      timestamp,
      system_type: typeof entry.system_type === "string" ? entry.system_type : "orchestrator",
      tool_usage: [],
      request_id: requestId,
      status: "",
    });
  });
}

async function finalizeSuccessfulResponse(chat, assistantMessage, context) {
  if (!chat || !assistantMessage) {
    return;
  }

  const assistantTimestamp = createTimestamp();
  appendSystemTraceMessages(chat, context.systemTrace, assistantTimestamp, context.requestId);

  assistantMessage.timestamp = assistantTimestamp;
  assistantMessage.status = "done";
  assistantMessage.tool_usage = context.toolUsage;
  if (Number.isFinite(Number(context.usedTokens)) && Number(context.usedTokens) > 0) {
    const currentTotal = Number(chat.total_tokens_used || 0);
    chat.total_tokens_used = Math.max(0, currentTotal) + Number(context.usedTokens);
    const { addDailyTokenUsage } = await import("./token-usage.js");
    addDailyTokenUsage(Number(context.usedTokens));
  }
  chat.updated_at = assistantTimestamp;

  if (state.activeChatId === chat.id) {
    state.lastRequestTokens = Number.isFinite(Number(context.usedTokens)) ? Number(context.usedTokens) : 0;
  }

  const { maybeAutoCompact } = await import("./chat-compact.js");
  const compactResult = await maybeAutoCompact(chat, "ongoing chat", state.modelTokenLimit);
  if (!compactResult.ok) {
    return;
  }

  if (state.activeChatId === chat.id) {
    const { renderActiveChat } = await import("./chat-render.js");
    renderActiveChat();
  }
  const { renderChatHistory } = await import("./chat-history.js");
  renderChatHistory();
  if (state.activeChatId === chat.id) {
    const { syncUsedTokensToContext } = await import("./providers.js");
    syncUsedTokensToContext();
  }

  try {
    const { persistChatsToSettings } = await import("./chat-sync.js");
    await persistChatsToSettings();
  } catch (error) {
    setStatus(`Response complete, but chat history was not saved: ${error.message}`, true);
    return;
  }

  try {
    const { refreshTimedJobsAfterMcpUsage } = await import("./timed-jobs.js");
    await refreshTimedJobsAfterMcpUsage(context.toolUsage);
  } catch {
    // Best-effort sync only.
  }

  try {
    const { refreshScriptsAfterMcpUsage } = await import("./timed-jobs.js");
    await refreshScriptsAfterMcpUsage(context.toolUsage);
  } catch {
    // Best-effort sync only.
  }

  const userMessages = Array.isArray(chat.messages)
    ? chat.messages.filter((message) => message && message.role === "user" && typeof message.content === "string")
    : [];
  const lastUserMessage = userMessages.length > 0 ? userMessages[userMessages.length - 1].content : "";
  const { registerCompletedTurnForMemory } = await import("./chat-sync.js");
  registerCompletedTurnForMemory("gateway", chat.id, lastUserMessage, assistantMessage.content || "").catch(() => {});
  sendAssistantResponseNotification(chat, assistantMessage);

  if (compactResult.compacted) {
    setStatus("Response complete. Memory compacted.");
    return;
  }

  setStatus("Response complete.");
}

function buildQueueSnapshot(chat) {
  const activeProviderId = state.activeProviderId;
  const providerConfig = state.settings?.provider_configs?.[activeProviderId] ?? null;
  return {
    history: toApiChatHistory(chat.messages),
    memoryBlock: chat.memory_block || "",
    providerId: activeProviderId,
    model: providerConfig?.model ?? "",
    apiKey: providerConfig?.api_key ?? "",
    botName: state.settings?.bot_name ?? "",
    systemPrompt: state.settings?.system_prompt ?? "",
  };
}

function findMessageByRequestId(chat, requestId) {
  return chat.messages.find((message) => message.request_id === requestId) ?? null;
}

async function createDebugDump(chat) {
  const response = await fetch("/api/chat/debug", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      chat_id: chat.id,
      chat,
    }),
  });

  if (!response.ok) {
    const detail = await buildHttpErrorDetail(response, "Failed to create debug dump.");
    throw new Error(detail);
  }

  return response.json();
}

async function executeQueuedJob(chat, job, runtime) {
  const assistantMessage = findMessageByRequestId(chat, job.requestId);
  if (!assistantMessage) {
    return;
  }

  const { stopActiveRequestSync } = await import("./chat-sync.js");

  assistantMessage.status = "processing";
  const context = {
    chatId: chat.id,
    requestId: job.requestId,
    assistantMessage,
    usedTokens: 0,
    toolUsage: [],
    systemTrace: [],
  };
  if (state.activeChatId === chat.id) {
    _renderActiveChat();
    setStatus("Processing...");
  }
  _renderChatHistory();

  try {
    runtime.abortController = new AbortController();
    const response = await fetch("/api/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      signal: runtime.abortController.signal,
      body: JSON.stringify({
        message: job.message,
        history: job.snapshot.history,
        memory_block: job.snapshot.memoryBlock,
        provider_id: job.snapshot.providerId,
        model: job.snapshot.model,
        api_key: job.snapshot.apiKey,
        bot_name: job.snapshot.botName,
        system_prompt: job.snapshot.systemPrompt,
        source_channel: "gateway",
        source_chat_id: chat.id,
        source_request_id: job.requestId,
      }),
    });

    if (!response.ok) {
      const detail = await buildHttpErrorDetail(response, "Chat request failed.");
      throw new Error(detail);
    }

    if (!response.body) {
      throw new Error("Chat request failed. HTTP 200 but response body stream was empty.");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        break;
      }

      if (runtime.cancelledRequestIds.has(job.requestId)) {
        return;
      }

      buffer += decoder.decode(value, { stream: true });
      const blocks = buffer.split("\n\n");
      buffer = blocks.pop() ?? "";

      for (const block of blocks) {
        const result = processSseBlock(block, context);
        if (result.hasError) {
          throw new Error(result.errorMessage);
        }

        if (result.done) {
          break;
        }
      }
    }

    if (runtime.cancelledRequestIds.has(job.requestId)) {
      return;
    }

    await finalizeSuccessfulResponse(chat, assistantMessage, context);
  } catch (error) {
    if (runtime.cancelledRequestIds.has(job.requestId)) {
      return;
    }

    if (error instanceof DOMException && error.name === "AbortError") {
      return;
    }

    const hardErrorText = normalizeErrorMessage(error, "Hard error.");
    console.error("Gateway chat request failed", {
      chatId: chat.id,
      requestId: job.requestId,
      providerId: job.snapshot.providerId,
      model: job.snapshot.model,
      messagePreview: typeof job.message === "string" ? job.message.slice(0, 160) : "",
      error: hardErrorText,
    });
    if (assistantMessage.content) {
      assistantMessage.content = `${assistantMessage.content}\n\nHard error: ${hardErrorText}`;
    } else {
      assistantMessage.content = hardErrorText;
    }

    const errorTimestamp = createTimestamp();
    appendSystemTraceMessages(chat, context.systemTrace, errorTimestamp, context.requestId);
    assistantMessage.timestamp = errorTimestamp;
    assistantMessage.status = "error";
    assistantMessage.tool_usage = context.toolUsage;
    if (Number.isFinite(Number(context.usedTokens)) && Number(context.usedTokens) > 0) {
      const currentTotal = Number(chat.total_tokens_used || 0);
      chat.total_tokens_used = Math.max(0, currentTotal) + Number(context.usedTokens);
      const { addDailyTokenUsage } = await import("./token-usage.js");
      addDailyTokenUsage(Number(context.usedTokens));
    }
    chat.updated_at = errorTimestamp;

    if (state.activeChatId === chat.id) {
      state.lastRequestTokens = Number.isFinite(Number(context.usedTokens)) ? Number(context.usedTokens) : 0;
      _renderActiveChat();
      const { syncUsedTokensToContext } = await import("./providers.js");
      syncUsedTokensToContext();
    }
    _renderChatHistory();
    setStatus(hardErrorText, true);

    try {
      const { persistChatsToSettings } = await import("./chat-sync.js");
      await persistChatsToSettings();
    } catch (persistError) {
      setStatus(`Response failed and save failed: ${persistError.message}`, true);
    }
  } finally {
    await stopActiveRequestSync(chat.id, job.requestId);
    runtime.abortController = null;
  }
}

async function processChatQueue(chatId) {
  const runtime = getChatRuntime(chatId);
  if (!runtime || runtime.processing) {
    return;
  }

  runtime.processing = true;
  try {
    while (runtime.queue.length > 0) {
      const job = runtime.queue.shift();
      if (!job || runtime.cancelledRequestIds.has(job.requestId)) {
        continue;
      }

      const chat = state.chats.find((entry) => entry.id === chatId);
      if (!chat) {
        runtime.cancelledRequestIds.add(job.requestId);
        continue;
      }

      runtime.activeRequestId = job.requestId;
      await executeQueuedJob(chat, job, runtime);
      runtime.activeRequestId = "";

      try {
        const { persistChatsToSettings } = await import("./chat-sync.js");
        await persistChatsToSettings();
      } catch (error) {
        setStatus(`Queued response save failed: ${error.message}`, true);
      }
    }
  } finally {
    runtime.processing = false;
    runtime.activeRequestId = "";
    _renderChatHistory();
    if (state.activeChatId === chatId) {
      const { updateComposerState } = await import("./chat-render.js");
      updateComposerState();
    }
  }
}

async function sendMessage(event) {
  event.preventDefault();

  if (state.speechListening) {
    const { stopSpeechRecognition } = await import("./speech.js");
    stopSpeechRecognition(true);
  }

  requestNotificationPermissionIfNeeded().catch(() => {});

  if (state.isSwitching || state.isCompacting) {
    setStatus("Please wait for current gateway operation to finish.", true);
    return;
  }

  const message = chatInput.value.trim();
  const pendingImage = clonePendingImageAttachment(state.pendingImageAttachment);
  if (!message && !pendingImage) {
    setStatus("Please enter a message or attach an image.", true);
    return;
  }

  const { getActiveChat } = await import("./chat-history.js");
  let chat = getActiveChat();
  const isDebugCommand = !pendingImage && message.toLowerCase() === "/debug";
  if (isDebugCommand) {
    if (!chat) {
      setStatus("No active chat available to debug.", true);
      return;
    }

    try {
      const payload = await createDebugDump(chat);
      chatInput.value = "";
      clearPendingImageAttachment();
      syncChatInputHeight();
      const { syncRemoteChatState } = await import("./chat-sync.js");
      await syncRemoteChatState();
      setStatus(typeof payload?.detail === "string" ? payload.detail : "Debug dump created.");
      chatInput.focus();
    } catch (error) {
      setStatus(normalizeErrorMessage(error, "Failed to create debug dump."), true);
    }
    return;
  }

  if (!chat) {
    const { createChatEntry } = await import("./chat-history.js");
    chat = createChatEntry(message);
    state.chats.push(chat);
    state.activeChatId = chat.id;
    const { updateCurrentChatTitle } = await import("./chat-history.js");
    updateCurrentChatTitle();
    const { updateSystemTraceToggleLabel } = await import("./chat-history.js");
    updateSystemTraceToggleLabel();
  } else if ((!Array.isArray(chat.messages) || chat.messages.length === 0) && normalizeChatTitle(chat.title).toLowerCase() === "new chat") {
    chat.title = deriveChatTitle(message);
  }

  const { ensureRuntimeContextSeed } = await import("./runtime-context.js");
  ensureRuntimeContextSeed(chat);
  const chatExistsInPersistedSettings = Array.isArray(state.settings?.chats)
    && state.settings.chats.some((entry) => entry && entry.id === chat.id);
  if (!chatExistsInPersistedSettings) {
    try {
      const { persistChatsToSettings } = await import("./chat-sync.js");
      await persistChatsToSettings();
    } catch (error) {
      setStatus(normalizeErrorMessage(error, "Failed to prepare chat."), true);
      return;
    }
  }

  const userContent = pendingImage
    ? (message ? `${message}\n\n[Image attached]` : "[Image attached]")
    : message;
  const draftKey = buildEnqueueDraftKey(message, pendingImage);
  if (state.pendingEnqueueByChat[chat.id] === draftKey) {
    setStatus("This message is already being queued.", true);
    return;
  }

  const clientEnqueueId = createClientEnqueueId();
  state.pendingEnqueueByChat[chat.id] = draftKey;
  const localRequestId = createLocalRequestId();
  const queuedTimestamp = createTimestamp();
  const optimisticUserMessage = {
    role: "user",
    content: userContent,
    timestamp: queuedTimestamp,
    system_type: "",
    tool_usage: [],
    request_id: localRequestId,
    status: "",
  };
  const optimisticAssistantMessage = {
    role: "assistant",
    content: "",
    timestamp: "",
    system_type: "",
    tool_usage: [],
    request_id: localRequestId,
    status: "queued",
  };
  chat.messages.push(optimisticUserMessage);
  chat.messages.push(optimisticAssistantMessage);
  chat.updated_at = queuedTimestamp;

  if (state.activeChatId === chat.id) {
    const { renderActiveChat } = await import("./chat-render.js");
    renderActiveChat();
  }
  const { renderChatHistory } = await import("./chat-history.js");
  renderChatHistory();
  chatInput.value = "";
  clearPendingImageAttachment();
  syncChatInputHeight();
  const { updateComposerState } = await import("./chat-render.js");
  updateComposerState();

  try {
    const snapshot = buildQueueSnapshot(chat);
    const response = await fetch("/api/chat/enqueue", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        chat_id: chat.id,
        message,
        client_enqueue_id: clientEnqueueId,
        image: pendingImage
          ? {
            file_name: String(pendingImage.fileName || "image"),
            mime_type: String(pendingImage.mimeType || "image/jpeg"),
            content_base64: String(pendingImage.contentBase64 || ""),
          }
          : null,
        provider_id: snapshot.providerId,
        model: snapshot.model,
        api_key: snapshot.apiKey,
        bot_name: snapshot.botName,
        system_prompt: snapshot.systemPrompt,
      }),
    });
    if (!response.ok) {
      const detail = await buildHttpErrorDetail(response, "Chat request failed.");
      throw new Error(detail);
    }
    const payload = await response.json();
    const serverRequestId = typeof payload?.request_id === "string" ? payload.request_id.trim() : "";
    if (serverRequestId) {
      optimisticAssistantMessage.request_id = serverRequestId;
      optimisticUserMessage.request_id = "";
    }
    setStatus("Queued.");
    const { startActiveRequestSync, syncRemoteChatState } = await import("./chat-sync.js");
    void syncRemoteChatState();
    void startActiveRequestSync(chat.id, serverRequestId || localRequestId);
  } catch (error) {
    const { stopActiveRequestSync } = await import("./chat-sync.js");
    await stopActiveRequestSync(chat.id);
    const filteredMessages = chat.messages.filter((entry) => entry?.request_id !== localRequestId);
    chat.messages = filteredMessages;
    chat.updated_at = createTimestamp();
    if (state.activeChatId === chat.id) {
      const { renderActiveChat: renderActiveChatOnError } = await import("./chat-render.js");
      renderActiveChatOnError();
    }
    const { renderChatHistory: renderChatHistoryOnError } = await import("./chat-history.js");
    renderChatHistoryOnError();
    if (state.activeChatId === chat.id && !chatInput.value && !state.pendingImageAttachment) {
      chatInput.value = message;
      state.pendingImageAttachment = pendingImage;
      renderPendingImageAttachment();
      syncChatInputHeight();
    }
    const { updateComposerState: updateComposerStateOnError } = await import("./chat-render.js");
    updateComposerStateOnError();
    setStatus(normalizeErrorMessage(error, "Failed to queue message."), true);
    delete state.pendingEnqueueByChat[chat.id];
    return;
  }

  delete state.pendingEnqueueByChat[chat.id];
  chatInput.focus();
}

/* ── Lazy cross-module wrappers (fire-and-forget from sync code) ── */

function _renderActiveChat() {
  import("./chat-render.js").then((mod) => mod.renderActiveChat());
}

function _renderChatHistory() {
  import("./chat-history.js").then((mod) => mod.renderChatHistory());
}

function _syncUsedTokensToContext() {
  import("./providers.js").then((mod) => mod.syncUsedTokensToContext());
}

function _updateTokenCounter(usedTokens, tokenLimit) {
  import("./token-usage.js").then((mod) => mod.updateTokenCounter(usedTokens, tokenLimit));
}

async function stopActiveChatExecution() {
  const { getActiveChat } = await import("./chat-history.js");
  const activeChat = getActiveChat();
  if (!activeChat) {
    return;
  }
  try {
    const response = await fetch("/api/chat/stop", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat_id: activeChat.id }),
    });
    if (!response.ok) {
      const detail = await buildHttpErrorDetail(response, "Failed to stop chat execution.");
      throw new Error(detail);
    }
    const { stopActiveRequestSync, syncRemoteChatState } = await import("./chat-sync.js");
    await stopActiveRequestSync(activeChat.id);
    await syncRemoteChatState();
    setStatus("Stopped. Ready for the next task.", true);
  } catch (error) {
    setStatus(normalizeErrorMessage(error, "Failed to stop chat execution."), true);
  }
}

export {
  processSseBlock,
  appendSystemTraceMessages,
  finalizeSuccessfulResponse,
  buildQueueSnapshot,
  findMessageByRequestId,
  executeQueuedJob,
  processChatQueue,
  sendMessage,
  normalizeToolUsage,
  toApiChatHistory,
  stopActiveChatExecution,
};
