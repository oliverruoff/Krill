/*
 * Application bootstrap: initial data load and window lifecycle handlers.
 */

import { state } from "./state.js";
import {
  assistantTitleNode,
  mobileAssistantNameNode,
  assistantMetaNode,
  gatewayBootOverlay,
  gatewayBootTitleNode,
  gatewayBootDetailNode,
  gatewayBootRetryButton,
} from "./dom.js";
import { setStatus, syncChatInputHeight } from "./utils.js";
import { applyThemeMode } from "./theme.js";
import { normalizeIncomingMemories } from "./memory.js";
import {
  renderChatHistory,
  createChatEntry,
  updateSystemTraceToggleLabel,
} from "./chat-history.js";
import { ensureVisibleActiveChat, findReusableNewChatDraft } from "./chat-sync.js";
import { renderActiveChat, renderEmptyChatView } from "./chat-render.js";
import { normalizeIncomingChats, normalizeDailyTokenUsage } from "./chat-sync.js";
import {
  syncSwitcherControls,
  getModelTokenLimit,
  syncUsedTokensToContext,
} from "./providers.js";
import { updateMetaIndicators, updateAssistantHeader, updateDailyTokenUsageLabel } from "./header.js";
import { updateTokenCounter } from "./token-usage.js";
import { loadTimedJobs } from "./timed-jobs.js";
import {
  loadShortTermMemories as loadShortTermMemory,
  startShortTermMemorySync,
} from "./short-term-memory.js";
import { fetchGoogleOauthStatus } from "./google-oauth.js";
import {
  hydrateWhatsappContactsFromCache,
  fetchWhatsappContacts,
  syncWhatsappContactsWithRetry,
} from "./whatsapp.js";
import { normalizeScriptTitles, normalizeScriptsCatalog } from "./scripts.js";
import { initializeSpeechRecognition, stopSpeechRecognition } from "./speech.js";
import { renderPendingImageAttachment } from "./image-upload.js";
import { syncMobileDrawerUi } from "./mobile-drawer.js";
import { showToast } from "./toast.js";

function setBootLoading(loading, options = {}) {
  const title = typeof options.title === "string" && options.title.trim()
    ? options.title.trim()
    : (loading ? "Loading Gateway" : "Gateway ready");
  const detail = typeof options.detail === "string"
    ? options.detail.trim()
    : (loading ? "Preparing chats, tools, and integrations..." : "");
  const error = typeof options.error === "string" ? options.error.trim() : "";
  const showRetry = Boolean(options.showRetry);

  state.bootLoading = Boolean(loading);
  state.bootError = error;
  document.body.classList.toggle("gateway-boot-loading", state.bootLoading);

  if (!(gatewayBootOverlay instanceof HTMLElement)) {
    return;
  }

  gatewayBootOverlay.classList.toggle("hidden", !state.bootLoading && !error);
  gatewayBootOverlay.classList.toggle("is-error", Boolean(error));
  gatewayBootOverlay.setAttribute("aria-hidden", (!state.bootLoading && !error).toString());

  if (gatewayBootTitleNode instanceof HTMLElement) {
    gatewayBootTitleNode.textContent = error ? "Gateway failed to load" : title;
  }
  if (gatewayBootDetailNode instanceof HTMLElement) {
    gatewayBootDetailNode.textContent = error || detail || "";
  }
  if (gatewayBootRetryButton instanceof HTMLButtonElement) {
    gatewayBootRetryButton.classList.toggle("hidden", !showRetry);
    gatewayBootRetryButton.disabled = state.bootLoading;
  }
}

async function loadGatewayMeta() {
  setBootLoading(true, { detail: "Preparing chats, tools, and integrations..." });
  try {
    const { loadAppVersion } = await import("./header.js");
    loadAppVersion();
    const [providersResponse, settingsResponse, mcpsResponse, integrationsResponse, scriptsResponse] = await Promise.all([
      fetch("/api/providers"),
      fetch("/api/settings"),
      fetch("/api/mcps"),
      fetch("/api/integrations"),
      fetch("/api/mcps/scripts", { cache: "no-store" }),
    ]);

    if (!providersResponse.ok || !settingsResponse.ok || !mcpsResponse.ok || !integrationsResponse.ok || !scriptsResponse.ok) {
      throw new Error("Failed to load gateway metadata.");
    }

    const providers = await providersResponse.json();
    const settings = await settingsResponse.json();
    const mcps = await mcpsResponse.json();
    const integrations = await integrationsResponse.json();
    const scriptsCatalog = await scriptsResponse.json();

    const activeProvider = providers.find((provider) => provider.id === settings.active_provider_id);
    const activeConfig = settings.provider_configs?.[settings.active_provider_id];

    state.providers = providers;
    state.settings = settings;
    applyThemeMode(settings.theme);
    state.activeProviderId = settings.active_provider_id ?? "";
    state.activeModelId = activeConfig?.model ?? "";
    state.botName = typeof settings?.bot_name === "string" ? settings.bot_name.trim() : "";
    state.coreMemories = normalizeIncomingMemories(settings.core_memories);
    state.normalMemories = normalizeIncomingMemories(settings.normal_memories);
    const { mergeSessionOnlySystemMessages } = await import("./chat-sync.js");
    state.chats = mergeSessionOnlySystemMessages(normalizeIncomingChats(settings.chats), state.chats);
    state.dailyTokenUsage = normalizeDailyTokenUsage(settings.daily_token_usage);
    state.mcps = Array.isArray(mcps) ? mcps : [];
    state.scriptTitles = normalizeScriptTitles(scriptsCatalog?.titles);
    state.scripts = normalizeScriptsCatalog(scriptsCatalog?.scripts);
    state.integrations = Array.isArray(integrations) ? integrations : [];
    const { normalizeIncomingMcpConfigs } = await import("./mcp-handlers.js");
    state.mcpConfigs = normalizeIncomingMcpConfigs(settings.mcp_configs);
    state.integrationConfigs = normalizeIncomingMcpConfigs(settings.integration_configs);
    hydrateWhatsappContactsFromCache();
    try {
      await fetchGoogleOauthStatus();
    } catch (error) {
      state.googleOauthStatus = null;
    }
    await fetchWhatsappContacts();
    const { syncTelegramFlagsFromIntegrationConfig } = await import("./mcp-handlers.js");
    syncTelegramFlagsFromIntegrationConfig();
    state.telegramOwnerUserId = typeof settings?.telegram_state?.owner_user_id === "string"
      ? settings.telegram_state.owner_user_id
      : "";
    state.telegramOwnerChatId = typeof settings?.telegram_state?.owner_chat_id === "string"
      ? settings.telegram_state.owner_chat_id
      : "";

    state.providerLabel = activeProvider?.label ?? settings.active_provider_id ?? "";
    state.modelLabel = activeProvider?.models?.find((model) => model.id === activeConfig?.model)?.label ?? activeConfig?.model ?? "";
    state.modelTokenLimit = getModelTokenLimit(state.activeProviderId, state.activeModelId);

    // findReusableNewChatDraft is imported statically from chat-sync.js at the top
    const reusableNewChatDraft = findReusableNewChatDraft(state.chats);
    let createdNewChatDraft = false;
    if (reusableNewChatDraft) {
      state.activeChatId = reusableNewChatDraft.id;
    } else {
      const freshChat = createChatEntry("");
      freshChat.title = "New chat";
      state.chats.push(freshChat);
      state.activeChatId = freshChat.id;
      createdNewChatDraft = true;
    }
    ensureVisibleActiveChat();
    if (createdNewChatDraft) {
      try {
        const { persistChatsToSettings } = await import("./chat-sync.js");
        await persistChatsToSettings();
      } catch (error) {
      }
    }

    syncSwitcherControls();
    updateMetaIndicators();
    updateAssistantHeader(settings);
    renderChatHistory();
    renderActiveChat();
    const { renderMcpPanel, renderIntegrationPanel } = await import("./mcp-panel.js");
    renderMcpPanel();
    renderIntegrationPanel();
    syncUsedTokensToContext();
    updateDailyTokenUsageLabel();
    const { updateTelegramStatusLabel } = await import("./mcp-handlers.js");
    updateTelegramStatusLabel();
    const { updateShortTermMemoryBadge } = await import("./short-term-memory.js");
    updateShortTermMemoryBadge();
    const { refreshLocalChatStateSignature, startChatStateSync } = await import("./chat-sync.js");
    refreshLocalChatStateSignature();
    startChatStateSync();
    const { startIntegrationStatusSync } = await import("./chat-sync.js");
    startIntegrationStatusSync();
    const { startTimedJobAuthAlertSync } = await import("./chat-sync.js");
    startTimedJobAuthAlertSync();
    startShortTermMemorySync();
    loadShortTermMemory(false);
    loadTimedJobs(false);
    const { syncIntegrationStatus } = await import("./chat-sync.js");
    syncIntegrationStatus();
    const { syncTimedJobAuthAlertStatus } = await import("./chat-sync.js");
    syncTimedJobAuthAlertStatus();
    const { updateComposerState } = await import("./chat-render.js");
    state.bootLoading = false;
    state.bootError = "";
    updateComposerState();
    setBootLoading(false);
    setStatus("");
  } catch (error) {
    const errorMessage = error instanceof Error ? error.message : "Failed to load Gateway.";
    updateMetaIndicators();
    assistantTitleNode.textContent = "This is your personal assistant";
    if (mobileAssistantNameNode instanceof HTMLElement) {
      mobileAssistantNameNode.textContent = "Assistant";
    }
    assistantMetaNode.textContent = "Assistant metadata unavailable.";
    syncSwitcherControls();
    renderChatHistory();
    renderEmptyChatView();
    const { renderMcpPanel, renderIntegrationPanel } = await import("./mcp-panel.js");
    renderMcpPanel();
    renderIntegrationPanel();
    updateTokenCounter(0, 0);
    updateDailyTokenUsageLabel();
    const { updateTelegramStatusLabel } = await import("./mcp-handlers.js");
    updateTelegramStatusLabel();
    const { updateShortTermMemoryBadge } = await import("./short-term-memory.js");
    updateShortTermMemoryBadge();
    const { startChatStateSync } = await import("./chat-sync.js");
    startChatStateSync();
    const { startIntegrationStatusSync } = await import("./chat-sync.js");
    startIntegrationStatusSync();
    const { startTimedJobAuthAlertSync } = await import("./chat-sync.js");
    startTimedJobAuthAlertSync();
    startShortTermMemorySync();
    loadShortTermMemory(false);
    loadTimedJobs(false);
    const { renderTimedJobAuthAlert } = await import("./chat-sync.js");
    renderTimedJobAuthAlert({ active: false });
    const { updateComposerState } = await import("./chat-render.js");
    state.bootLoading = false;
    state.bootError = errorMessage;
    updateComposerState();
    setBootLoading(false, {
      error: errorMessage,
      detail: "Krill could not finish the initial startup.",
      showRetry: true,
    });
    setStatus(errorMessage, true);
  }
}

function initBoot() {
  window.addEventListener("message", (event) => {
    if (event.origin !== window.location.origin) {
      return;
    }
    const payload = event.data;
    if (!payload || typeof payload !== "object") {
      return;
    }
    if (payload.type !== "krill-whatsapp-connected") {
      return;
    }
    const stateLabel = typeof payload.state === "string" ? payload.state : "ready";
    void (async () => {
      const syncResult = await syncWhatsappContactsWithRetry();
      const { renderMcpPanel } = await import("./mcp-panel.js");
      renderMcpPanel();
      const contactCount = Array.isArray(syncResult?.contacts) ? syncResult.contacts.length : 0;
      if (syncResult?.cacheRetained) {
        const warning = typeof syncResult.warning === "string" && syncResult.warning.trim()
          ? syncResult.warning.trim()
          : "Kept previously cached contacts.";
        setStatus(`WhatsApp connected (${stateLabel}). ${warning} Cached contacts: ${contactCount}.`, true);
      } else {
        setStatus(`WhatsApp connected (${stateLabel}). Contacts synced (${contactCount}).`);
      }
      showToast("WhatsApp connected.");
    })();
  });
  window.addEventListener("beforeunload", () => {
    stopSpeechRecognition(true);
    if (state.chatSyncTimerId) {
      window.clearInterval(state.chatSyncTimerId);
      state.chatSyncTimerId = null;
    }
    if (state.integrationStatusSyncTimerId) {
      window.clearInterval(state.integrationStatusSyncTimerId);
      state.integrationStatusSyncTimerId = null;
    }
    if (state.timedJobAuthAlertSyncTimerId) {
      window.clearInterval(state.timedJobAuthAlertSyncTimerId);
      state.timedJobAuthAlertSyncTimerId = null;
    }
    if (state.shortTermMemorySyncTimerId) {
      window.clearInterval(state.shortTermMemorySyncTimerId);
      state.shortTermMemorySyncTimerId = null;
    }
  });
  window.addEventListener("load", () => {
    setBootLoading(true, { detail: "Preparing chats, tools, and integrations..." });
    applyThemeMode(state.theme);
    initializeSpeechRecognition();
    syncChatInputHeight();
    renderPendingImageAttachment();
    syncMobileDrawerUi();
    loadGatewayMeta();
  });
  if (gatewayBootRetryButton instanceof HTMLButtonElement) {
    gatewayBootRetryButton.addEventListener("click", () => {
      if (state.bootLoading) {
        return;
      }
      void loadGatewayMeta();
    });
  }
}

export { loadGatewayMeta, initBoot };
