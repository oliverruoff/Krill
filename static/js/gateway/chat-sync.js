/*
 * Chat state persistence, remote sync, and integration status polling.
 */

import { state, CHAT_SYNC_INTERVAL_MS, INTEGRATION_STATUS_SYNC_INTERVAL_MS } from "./state.js";
import { timedJobAuthAlertNode } from "./dom.js";
import { buildHttpErrorDetail, createTimestamp, setStatus, normalizeChatTitle } from "./utils.js";

export async function persistSettings(nextSettings) {
  const response = await fetch("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(nextSettings),
  });

  if (!response.ok) {
    let detail = "Failed to save active provider/model.";
    try {
      const payload = await response.json();
      if (typeof payload.detail === "string" && payload.detail) {
        detail = payload.detail;
      }
    } catch (error) {
      detail = "Failed to save active provider/model.";
    }
    throw new Error(detail);
  }

  return response.json();
}

export async function persistChatState(chats, activeChatId, dailyTokenUsage) {
  const response = await fetch("/api/chat/state", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      chats,
      active_chat_id: activeChatId,
      daily_token_usage: dailyTokenUsage,
    }),
  });

  if (!response.ok) {
    const detail = await buildHttpErrorDetail(response, "Failed to save chat state.");
    throw new Error(detail);
  }

  return response.json();
}

export async function registerCompletedTurnForMemory(sourceChannel, sourceChatId, userMessage, assistantMessage) {
  const response = await fetch("/api/memory/turn-complete", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      source_channel: sourceChannel,
      source_chat_id: sourceChatId || "",
      user_message: userMessage,
      assistant_message: assistantMessage || "",
    }),
  });
  if (!response.ok) {
    return;
  }
}

export function normalizeDailyTokenUsage(rawUsage) {
  if (!Array.isArray(rawUsage)) {
    return [];
  }

  return rawUsage
    .filter((entry) => entry && typeof entry === "object")
    .map((entry) => {
      const date = typeof entry.date === "string" ? entry.date.trim() : "";
      const tokensRaw = Number(entry.tokens);
      const tokens = Number.isFinite(tokensRaw) && tokensRaw > 0 ? Math.floor(tokensRaw) : 0;
      return { date, tokens };
    })
    .filter((entry) => entry.date);
}

export function normalizeToolUsage(toolUsage) {
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

export function normalizeIncomingChats(rawChats) {
  if (!Array.isArray(rawChats)) {
    return [];
  }

  const normalized = [];
  rawChats.forEach((rawChat) => {
    if (!rawChat || typeof rawChat !== "object") {
      return;
    }

    const chatId = typeof rawChat.id === "string" ? rawChat.id.trim() : "";
    if (!chatId) {
      return;
    }

    const messages = Array.isArray(rawChat.messages)
      ? rawChat.messages
          .filter((message) => message && (message.role === "user" || message.role === "assistant" || message.role === "system"))
          .map((message) => ({
            role: message.role,
            content: typeof message.content === "string" ? message.content : "",
            timestamp: typeof message.timestamp === "string" ? message.timestamp : createTimestamp(),
            system_type: typeof message.system_type === "string" ? message.system_type : "",
            tool_usage: normalizeToolUsage(message.tool_usage),
            request_id: typeof message.request_id === "string" ? message.request_id : "",
            status: typeof message.status === "string" ? message.status : "",
          }))
      : [];

    normalized.push({
      id: chatId,
      title: normalizeChatTitle(rawChat.title),
      type: "normal",
      messages,
      memory_block: typeof rawChat.memory_block === "string" ? rawChat.memory_block : "",
      total_tokens_used:
        Number.isFinite(Number(rawChat.total_tokens_used)) && Number(rawChat.total_tokens_used) > 0
          ? Number(rawChat.total_tokens_used)
          : 0,
      collapse_system_trace:
        typeof rawChat.collapse_system_trace === "boolean" ? rawChat.collapse_system_trace : true,
      hidden_from_history: Boolean(rawChat.hidden_from_history),
      created_at: typeof rawChat.created_at === "string" ? rawChat.created_at : "",
      updated_at: typeof rawChat.updated_at === "string" ? rawChat.updated_at : "",
    });
  });

  return normalized;
}

export function mergeSessionOnlySystemMessages(incomingChats, currentChats = []) {
  const currentById = new Map(
    Array.isArray(currentChats)
      ? currentChats
          .filter((chat) => chat && typeof chat.id === "string" && chat.id)
          .map((chat) => [chat.id, chat])
      : [],
  );

  return (Array.isArray(incomingChats) ? incomingChats : []).map((chat) => {
    const current = currentById.get(chat.id);
    if (!current || !Array.isArray(current.messages)) {
      return chat;
    }

    const transientSystemMessages = current.messages.filter((message) => message && message.role === "system");
    if (transientSystemMessages.length === 0) {
      return chat;
    }

    const mergedMessages = Array.isArray(chat.messages) ? [...chat.messages] : [];
    transientSystemMessages.forEach((message) => {
      const duplicate = mergedMessages.some(
        (entry) => entry
          && entry.role === "system"
          && entry.request_id === message.request_id
          && entry.system_type === message.system_type
          && entry.content === message.content,
      );
      if (!duplicate) {
        mergedMessages.push({ ...message, tool_usage: normalizeToolUsage(message.tool_usage) });
      }
    });

    mergedMessages.sort((left, right) => {
      const leftTime = new Date(typeof left?.timestamp === "string" ? left.timestamp : 0).getTime();
      const rightTime = new Date(typeof right?.timestamp === "string" ? right.timestamp : 0).getTime();
      return leftTime - rightTime;
    });

    return {
      ...chat,
      messages: mergedMessages,
    };
  });
}

export function ensureVisibleActiveChat() {
  if (state.showHiddenTimedJobChats) {
    return;
  }
  const activeChat = state.chats.find((chat) => chat.id === state.activeChatId);
  if (activeChat && !isHiddenTimedJobDebugChat(activeChat)) {
    return;
  }
  const sortedChats = sortChatsByLatestMessage(state.chats);
  const nextVisibleChat = sortedChats.find((chat) => !isHiddenTimedJobDebugChat(chat));
  state.activeChatId = nextVisibleChat?.id ?? "";
}

export function findReusableNewChatDraft(chats) {
  const entries = Array.isArray(chats) ? chats : [];
  return entries.find((chat) => {
    if (!chat || isHiddenTimedJobDebugChat(chat)) {
      return false;
    }
    if (normalizeChatTitle(chat.title).toLowerCase() !== "new chat") {
      return false;
    }
    return !Array.isArray(chat.messages) || chat.messages.length === 0;
  }) ?? null;
}

function isHiddenTimedJobDebugChat(chat) {
  const title = typeof chat?.title === "string" ? chat.title.trim() : "";
  return title.toUpperCase().startsWith("[HIDDEN]");
}

function sortChatsByLatestMessage(chats) {
  return [...chats].sort((left, right) => {
    const leftDate = new Date(getLatestChatTimestamp(left) || 0).getTime();
    const rightDate = new Date(getLatestChatTimestamp(right) || 0).getTime();
    if (rightDate !== leftDate) {
      return rightDate - leftDate;
    }
    return (left.title || "").localeCompare(right.title || "");
  });
}

function getLatestChatTimestamp(chat) {
  if (!chat || !Array.isArray(chat.messages) || chat.messages.length === 0) {
    return chat?.created_at || "";
  }
  const lastMessage = chat.messages[chat.messages.length - 1];
  return typeof lastMessage?.timestamp === "string" ? lastMessage.timestamp : chat.created_at || "";
}

export async function persistChatsToSettingsDirect() {
  if (!state.settings) {
    return;
  }

  const persisted = await persistChatState(state.chats, state.activeChatId, state.dailyTokenUsage);
  state.chats = mergeSessionOnlySystemMessages(normalizeIncomingChats(persisted.chats), state.chats);
  if (typeof persisted.active_chat_id === "string") {
    state.activeChatId = persisted.active_chat_id;
  }
  state.dailyTokenUsage = normalizeDailyTokenUsage(persisted.daily_token_usage);
  if (state.settings && typeof state.settings === "object") {
    state.settings.chats = state.chats;
    state.settings.active_chat_id = state.activeChatId;
    state.settings.daily_token_usage = state.dailyTokenUsage;
  }
  refreshLocalChatStateSignature();
  const { updateDailyTokenUsageLabel } = await import("./header.js");
  updateDailyTokenUsageLabel();
}

export async function persistChatsToSettings() {
  if (!state.settings) {
    return;
  }

  markLocalChatStatePending();

  if (state.chatPersistInFlight) {
    state.chatPersistQueued = true;
    if (state.chatPersistPromise) {
      await state.chatPersistPromise;
    }
    return;
  }

  state.chatPersistInFlight = true;
  state.chatPersistPromise = (async () => {
    let lastError = null;
    do {
      state.chatPersistQueued = false;
      try {
        await persistChatsToSettingsDirect();
        lastError = null;
      } catch (error) {
        lastError = error;
      }
    } while (state.chatPersistQueued);

    if (lastError) {
      throw lastError;
    }
  })();

  try {
    await state.chatPersistPromise;
  } finally {
    state.chatPersistInFlight = false;
    state.chatPersistPromise = null;
    state.chatStateDirty = false;
  }
}

export function buildChatStateSignature(payload) {
  const chats = Array.isArray(payload?.chats)
    ? payload.chats.map((chat) => {
      if (!chat || typeof chat !== "object") {
        return chat;
      }
      const messages = Array.isArray(chat.messages)
        ? chat.messages.filter((message) => message && message.role !== "system")
        : [];
      return {
        ...chat,
        messages,
      };
    })
    : [];
  const activeChatId = typeof payload?.active_chat_id === "string" ? payload.active_chat_id : "";
  const dailyTokenUsage = Array.isArray(payload?.daily_token_usage) ? payload.daily_token_usage : [];
  return JSON.stringify({ chats, activeChatId, dailyTokenUsage });
}

export function refreshLocalChatStateSignature() {
  state.lastChatStateSignature = buildChatStateSignature({
    chats: state.chats,
    active_chat_id: state.activeChatId,
    daily_token_usage: state.dailyTokenUsage,
  });
}

export function markLocalChatStatePending() {
  state.chatStateDirty = true;
  state.chatStateMutationVersion += 1;
  refreshLocalChatStateSignature();
}

export async function applyRemoteChatState(payload) {
  const incomingChats = mergeSessionOnlySystemMessages(normalizeIncomingChats(payload?.chats), state.chats);
  const incomingActiveChatId = typeof payload?.active_chat_id === "string" ? payload.active_chat_id : "";
  const incomingDailyUsage = normalizeDailyTokenUsage(payload?.daily_token_usage);
  const currentActiveChatId = state.activeChatId;

  state.chats = incomingChats;
  state.dailyTokenUsage = incomingDailyUsage;
  const { updateDailyTokenUsageLabel } = await import("./header.js");
  updateDailyTokenUsageLabel();

  if (currentActiveChatId && state.chats.some((chat) => chat.id === currentActiveChatId)) {
    state.activeChatId = currentActiveChatId;
  } else if (state.chats.some((chat) => chat.id === incomingActiveChatId)) {
    state.activeChatId = incomingActiveChatId;
  } else {
    const sorted = sortChatsByLatestMessage(state.chats);
    state.activeChatId = sorted[0]?.id ?? "";
  }
  ensureVisibleActiveChat();

  const { renderChatHistory } = await import("./chat-history.js");
  const { renderActiveChat } = await import("./chat-render.js");
  renderChatHistory();
  renderActiveChat();
  const { syncUsedTokensToContext } = await import("./providers.js");
  await syncUsedTokensToContext();
  const { updateComposerState } = await import("./chat-render.js");
  updateComposerState();
}

export async function syncRemoteChatState() {
  if (state.chatSyncInFlight || state.isCompacting || state.isSwitching || state.chatPersistInFlight || state.chatStateDirty) {
    return;
  }

  const startedAtMutationVersion = state.chatStateMutationVersion;
  state.chatSyncInFlight = true;
  try {
    const response = await fetch("/api/chat/state", { cache: "no-store" });
    if (!response.ok) {
      return;
    }
    const payload = await response.json();

    if (startedAtMutationVersion !== state.chatStateMutationVersion || state.chatPersistInFlight || state.chatStateDirty) {
      return;
    }

    const signature = buildChatStateSignature(payload);
    if (signature === state.lastChatStateSignature) {
      return;
    }

    state.lastChatStateSignature = signature;
    await applyRemoteChatState(payload);
  } catch (error) {
    // Keep sync best-effort and silent.
  } finally {
    state.chatSyncInFlight = false;
  }
}

export function startChatStateSync() {
  if (state.chatSyncTimerId) {
    window.clearInterval(state.chatSyncTimerId);
  }
  state.chatSyncTimerId = window.setInterval(syncRemoteChatState, CHAT_SYNC_INTERVAL_MS);
}

export async function syncIntegrationStatus() {
  if (state.integrationStatusSyncInFlight) {
    return;
  }

  state.integrationStatusSyncInFlight = true;
  try {
    const response = await fetch("/api/integrations/status", { cache: "no-store" });
    if (!response.ok) {
      return;
    }
    const payload = await response.json();
    await applyIntegrationStatusPayload(payload);
  } catch (error) {
    // Keep sync best-effort and silent.
  } finally {
    state.integrationStatusSyncInFlight = false;
  }
}

async function applyIntegrationStatusPayload(payload) {
  const statuses = payload?.statuses;
  const telegramStatus = statuses && typeof statuses === "object" ? statuses.telegram : null;
  if (!telegramStatus || typeof telegramStatus !== "object") {
    return;
  }

  state.telegramEnabled = Boolean(telegramStatus.enabled);
  state.telegramTokenConfigured = Boolean(telegramStatus.token_configured);
  state.telegramOwnerUserId = typeof telegramStatus.owner_user_id === "string" ? telegramStatus.owner_user_id : "";
  state.telegramOwnerChatId = typeof telegramStatus.owner_chat_id === "string" ? telegramStatus.owner_chat_id : "";
  const { updateTelegramStatusLabel } = await import("./mcp-handlers.js");
  updateTelegramStatusLabel();
}

export function startIntegrationStatusSync() {
  if (state.integrationStatusSyncTimerId) {
    window.clearInterval(state.integrationStatusSyncTimerId);
  }
  state.integrationStatusSyncTimerId = window.setInterval(syncIntegrationStatus, INTEGRATION_STATUS_SYNC_INTERVAL_MS);
}

export async function syncTimedJobAuthAlertStatus() {
  if (state.timedJobAuthAlertSyncInFlight) {
    return;
  }
  state.timedJobAuthAlertSyncInFlight = true;
  try {
    const response = await fetch("/api/timed-jobs/auth-alert-status", { cache: "no-store" });
    if (!response.ok) {
      return;
    }
    const payload = await response.json();
    renderTimedJobAuthAlert(payload);
  } catch (error) {
    // Keep sync best-effort and silent.
  } finally {
    state.timedJobAuthAlertSyncInFlight = false;
  }
}

export function renderTimedJobAuthAlert(payload) {
  if (!(timedJobAuthAlertNode instanceof HTMLElement)) {
    return;
  }
  const active = Boolean(payload?.active);
  if (!active) {
    timedJobAuthAlertNode.textContent = "";
    timedJobAuthAlertNode.classList.add("hidden");
    return;
  }
  const providerIds = Array.isArray(payload?.provider_ids)
    ? payload.provider_ids.map((entry) => String(entry || "").trim()).filter(Boolean)
    : [];
  const providerLabel = providerIds.length > 0 ? providerIds.join(", ") : "current provider";
  const detail = typeof payload?.detail === "string" ? payload.detail.trim() : "";
  timedJobAuthAlertNode.textContent = detail
    || `Timed jobs are suppressing repeated auth-expired alerts for ${providerLabel}. Reconnect the provider in Setup.`;
  timedJobAuthAlertNode.classList.remove("hidden");
}

export function startTimedJobAuthAlertSync() {
  if (state.timedJobAuthAlertSyncTimerId) {
    window.clearInterval(state.timedJobAuthAlertSyncTimerId);
  }
  state.timedJobAuthAlertSyncTimerId = window.setInterval(
    syncTimedJobAuthAlertStatus,
    INTEGRATION_STATUS_SYNC_INTERVAL_MS,
  );
}

