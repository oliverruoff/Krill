/*
 * MCP and integration config management: normalize, persist, autosave,
 * input/action handlers, telegram status, and display labels.
 */

import { state } from "./state.js";
import {
  telegramStatusNode,
  mcpList,
  integrationList,
  timedJobsModal,
} from "./dom.js";
import { setStatus } from "./utils.js";
import { showToast } from "./toast.js";

export function normalizeIncomingMcpConfigs(rawConfigs) {
  if (!rawConfigs || typeof rawConfigs !== "object") {
    return {};
  }

  const normalized = {};
  Object.entries(rawConfigs).forEach(([mcpId, rawValue]) => {
    if (!rawValue || typeof rawValue !== "object") {
      return;
    }

    const params = rawValue.params && typeof rawValue.params === "object" ? rawValue.params : {};
    const normalizedParams = {};
    Object.entries(params).forEach(([key, value]) => {
      if (typeof key !== "string") {
        return;
      }
      normalizedParams[key] = typeof value === "string" ? value : String(value ?? "");
    });

    normalized[mcpId] = {
      enabled: Boolean(rawValue.enabled),
      params: normalizedParams,
    };
  });

  return normalized;
}

export function getMcpDefaultEnabled(mcpId) {
  const mcp = Array.isArray(state.mcps) ? state.mcps.find((entry) => entry?.id === mcpId) : null;
  return Boolean(mcp?.default_enabled);
}

export function getMcpConfig(mcpId) {
  const config = state.mcpConfigs[mcpId];
  if (config && typeof config === "object") {
    return config;
  }

  return { enabled: getMcpDefaultEnabled(mcpId), params: {} };
}

export function ensureMcpConfig(mcpId) {
  if (!state.mcpConfigs[mcpId] || typeof state.mcpConfigs[mcpId] !== "object") {
    state.mcpConfigs[mcpId] = { enabled: getMcpDefaultEnabled(mcpId), params: {} };
  }

  if (!state.mcpConfigs[mcpId].params || typeof state.mcpConfigs[mcpId].params !== "object") {
    state.mcpConfigs[mcpId].params = {};
  }

  return state.mcpConfigs[mcpId];
}

export function ensureIntegrationConfig(integrationId) {
  if (!state.integrationConfigs[integrationId] || typeof state.integrationConfigs[integrationId] !== "object") {
    state.integrationConfigs[integrationId] = { enabled: false, params: {} };
  }

  if (!state.integrationConfigs[integrationId].params || typeof state.integrationConfigs[integrationId].params !== "object") {
    state.integrationConfigs[integrationId].params = {};
  }

  return state.integrationConfigs[integrationId];
}

export function getIntegrationConfig(integrationId) {
  const config = state.integrationConfigs[integrationId];
  if (config && typeof config === "object") {
    return config;
  }

  return { enabled: false, params: {} };
}

export async function persistMcpConfigsToSettings() {
  if (!state.settings) {
    return;
  }

  const nextSettings = JSON.parse(JSON.stringify(state.settings));
  nextSettings.mcp_configs = state.mcpConfigs;
  nextSettings.integration_configs = state.integrationConfigs;
  nextSettings.chats = state.chats;
  nextSettings.active_chat_id = state.activeChatId;
  nextSettings.daily_token_usage = state.dailyTokenUsage;
  const { persistSettings } = await import("./chat-sync.js");
  const persisted = await persistSettings(nextSettings);
  state.settings = persisted;
  if (typeof persisted.active_chat_id === "string") {
    state.activeChatId = persisted.active_chat_id;
  }
  state.mcpConfigs = normalizeIncomingMcpConfigs(persisted.mcp_configs);
  state.integrationConfigs = normalizeIncomingMcpConfigs(persisted.integration_configs);
  syncTelegramFlagsFromIntegrationConfig();
  const { normalizeDailyTokenUsage, refreshLocalChatStateSignature } = await import("./chat-sync.js");
  state.dailyTokenUsage = normalizeDailyTokenUsage(persisted.daily_token_usage);
  refreshLocalChatStateSignature();
  const { updateDailyTokenUsageLabel } = await import("./header.js");
  updateDailyTokenUsageLabel();
  updateTelegramStatusLabel();
}

export async function verifyMcpConfig(mcpId) {
  const config = getMcpConfig(mcpId);
  const response = await fetch("/api/mcps/verify", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      mcp_id: mcpId,
      params: config.params,
    }),
  });

  if (!response.ok) {
    let detail = "Tool verification failed.";
    try {
      const payload = await response.json();
      if (typeof payload.detail === "string" && payload.detail) {
        detail = payload.detail;
      }
    } catch (error) {
      detail = "Tool verification failed.";
    }

    throw new Error(detail);
  }

  const payload = await response.json();
  return payload;
}

export async function verifyIntegrationConfig(integrationId) {
  const config = getIntegrationConfig(integrationId);
  const response = await fetch("/api/integrations/verify", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      integration_id: integrationId,
      params: config.params,
    }),
  });

  if (!response.ok) {
    let detail = "Integration verification failed.";
    try {
      const payload = await response.json();
      if (typeof payload.detail === "string" && payload.detail) {
        detail = payload.detail;
      }
    } catch (error) {
      detail = "Integration verification failed.";
    }
    throw new Error(detail);
  }

  const payload = await response.json();
  if (integrationId === "telegram") {
    const { syncIntegrationStatus } = await import("./chat-sync.js");
    await syncIntegrationStatus();
  }
  return payload;
}

export function getFrontendMcpLabel(mcpId, fallbackLabel = "") {
  const normalizedId = typeof mcpId === "string" ? mcpId : "";
  if (normalizedId === "local_files") {
    return "Local Ops";
  }
  if (typeof fallbackLabel === "string" && fallbackLabel.trim()) {
    return fallbackLabel;
  }
  return normalizedId;
}

export function getMcpDisplayLabel(mcpId) {
  const normalizedId = typeof mcpId === "string" ? mcpId : "";
  if (!normalizedId) {
    return "Tool";
  }
  const mcp = Array.isArray(state.mcps) ? state.mcps.find((entry) => entry?.id === normalizedId) : null;
  return getFrontendMcpLabel(normalizedId, typeof mcp?.label === "string" ? mcp.label : normalizedId);
}

export function updateTelegramStatusLabel() {
  if (!(telegramStatusNode instanceof HTMLElement)) {
    return;
  }

  if (!state.telegramEnabled) {
    telegramStatusNode.textContent = "Telegram: disabled";
    return;
  }

  if (!state.telegramTokenConfigured) {
    telegramStatusNode.textContent = "Telegram: enabled, token missing";
    return;
  }

  if (!state.telegramOwnerUserId) {
    telegramStatusNode.textContent = "Telegram: waiting for first owner message";
    return;
  }

  if (!state.telegramOwnerChatId) {
    telegramStatusNode.textContent = "Telegram: owner bound, waiting for chat target";
    return;
  }

  telegramStatusNode.textContent = "Telegram: connected";
}

export function syncTelegramFlagsFromIntegrationConfig() {
  const telegramConfig = getIntegrationConfig("telegram");
  state.telegramEnabled = Boolean(telegramConfig.enabled);
  state.telegramTokenConfigured = Boolean(
    typeof telegramConfig.params?.bot_token === "string" && telegramConfig.params.bot_token.trim(),
  );
}

export async function runMcpAutosave(mcpId) {
  if (!mcpId) {
    return;
  }

  if (state.mcpAutosaveInFlight) {
    state.mcpAutosaveQueuedId = mcpId;
    return;
  }

  state.mcpAutosaveInFlight = true;
  try {
    await persistMcpConfigsToSettings();
    const label = getMcpDisplayLabel(mcpId);
    const message = `MCP: ${label} saved.`;
    setStatus(message);
    showToast(message);
  } catch (error) {
    setStatus(`MCP save failed: ${error.message}`, true);
  } finally {
    state.mcpAutosaveInFlight = false;
    if (state.mcpAutosaveQueuedId) {
      const queuedId = state.mcpAutosaveQueuedId;
      state.mcpAutosaveQueuedId = "";
      scheduleMcpAutosave(queuedId);
    }
  }
}

export function scheduleMcpAutosave(mcpId) {
  const normalizedId = typeof mcpId === "string" ? mcpId.trim() : "";
  if (!normalizedId) {
    return;
  }

  state.mcpAutosavePendingId = normalizedId;
  if (state.mcpAutosaveTimerId) {
    window.clearTimeout(state.mcpAutosaveTimerId);
  }

  state.mcpAutosaveTimerId = window.setTimeout(async () => {
    state.mcpAutosaveTimerId = null;
    const pendingId = state.mcpAutosavePendingId;
    state.mcpAutosavePendingId = "";
    await runMcpAutosave(pendingId);
  }, 300);
}

export function getConfigExpandKey(kind, configId) {
  return `${kind}:${configId}`;
}

export function parseMultiselectParam(rawValue) {
  if (typeof rawValue !== "string") {
    return [];
  }
  const trimmed = rawValue.trim();
  if (!trimmed) {
    return [];
  }

  try {
    const parsed = JSON.parse(trimmed);
    if (Array.isArray(parsed)) {
      return parsed.map((item) => String(item || "").trim()).filter((item) => item.length > 0);
    }
  } catch (error) {
    // Fallback to comma-separated legacy values.
  }

  return trimmed.split(",").map((item) => item.trim()).filter((item) => item.length > 0);
}

export function encodeMultiselectParam(values) {
  if (!Array.isArray(values)) {
    return "[]";
  }
  const normalized = [];
  values.forEach((value) => {
    const item = String(value || "").trim();
    if (!item || normalized.includes(item)) {
      return;
    }
    normalized.push(item);
  });
  return JSON.stringify(normalized);
}

export function parseBooleanConfigParam(rawValue) {
  const normalized = String(rawValue || "").trim().toLowerCase();
  return normalized === "1" || normalized === "true" || normalized === "yes" || normalized === "on";
}

export function readMultiselectSelection(fieldsetNode) {
  if (!(fieldsetNode instanceof HTMLElement)) {
    return [];
  }
  const selected = [];
  const boxes = fieldsetNode.querySelectorAll("input[type='checkbox'][data-multiselect-value]");
  boxes.forEach((boxNode) => {
    if (!(boxNode instanceof HTMLInputElement)) {
      return;
    }
    if (!boxNode.checked) {
      return;
    }
    const optionValue = String(boxNode.dataset.multiselectValue || "").trim();
    if (!optionValue || selected.includes(optionValue)) {
      return;
    }
    selected.push(optionValue);
  });
  return selected;
}

export function isConfigExpanded(kind, configId) {
  const key = getConfigExpandKey(kind, configId);
  return Boolean(state.expandedConfigs[key]);
}

export function toggleConfigExpanded(kind, configId) {
  const key = getConfigExpandKey(kind, configId);
  state.expandedConfigs[key] = !Boolean(state.expandedConfigs[key]);
}

export function handleMcpInputChange(event) {
  const target = event.target;
  if (!(target instanceof HTMLInputElement) && !(target instanceof HTMLSelectElement) && !(target instanceof HTMLTextAreaElement)) {
    return;
  }

  const action = target.dataset.action;
  const configKind = target.dataset.configKind;
  const configId = target.dataset.configId;
  if (!action || !configKind || !configId) {
    return;
  }

  const config = configKind === "integration" ? ensureIntegrationConfig(configId) : ensureMcpConfig(configId);
  if (action === "toggle") {
    config.enabled = target.checked;
    if (configKind === "mcp") {
      scheduleMcpAutosave(configId);
    }
    if (configKind === "integration" && configId === "telegram") {
      syncTelegramFlagsFromIntegrationConfig();
      updateTelegramStatusLabel();
    }
    return;
  }

  if (action === "param") {
    const fieldId = target.dataset.fieldId;
    if (!fieldId) {
      return;
    }
    let persistImmediately = false;
    if (target instanceof HTMLInputElement && target.type === "checkbox") {
      config.params[fieldId] = target.checked ? "true" : "false";
      if (configKind === "mcp" && configId === "whatsapp" && fieldId === "auto_answer" && !target.checked) {
        persistImmediately = true;
      }
    } else {
      config.params[fieldId] = target.value;
    }
    if (configKind === "mcp") {
      if (persistImmediately) {
        if (state.mcpAutosaveTimerId) {
          window.clearTimeout(state.mcpAutosaveTimerId);
          state.mcpAutosaveTimerId = null;
        }
        state.mcpAutosavePendingId = "";
        void runMcpAutosave(configId);
      } else {
        scheduleMcpAutosave(configId);
      }
    }
    if (configKind === "integration" && configId === "telegram") {
      syncTelegramFlagsFromIntegrationConfig();
      updateTelegramStatusLabel();
    }
    return;
  }

  if (action === "param-multiselect") {
    const fieldId = target.dataset.fieldId;
    if (!fieldId) {
      return;
    }
    const cardNode = target.closest(".mcp-card");
    if (!(cardNode instanceof HTMLElement)) {
      return;
    }
    const fieldsetNode = cardNode.querySelector(`.mcp-multiselect[data-field-id='${fieldId}']`);
    config.params[fieldId] = encodeMultiselectParam(readMultiselectSelection(fieldsetNode));
    if (configKind === "mcp") {
      scheduleMcpAutosave(configId);
    }
    return;
  }

  if (action === "script-toggle" && configKind === "mcp" && configId === "scripts") {
    if (!(target instanceof HTMLInputElement)) {
      return;
    }
    const scriptTitle = typeof target.dataset.scriptTitle === "string" ? target.dataset.scriptTitle : "";
    void (async () => {
      const { setScriptEnabledForExecution } = await import("./scripts.js");
      setScriptEnabledForExecution(scriptTitle, target.checked);
      scheduleMcpAutosave(configId);
    })();
    return;
  }

  if (action === "google-write-access" && configKind === "mcp" && configId === "google_services") {
    if (!(target instanceof HTMLInputElement)) {
      return;
    }
    config.params.access_mode = target.checked ? "read_write" : "read_only";
    scheduleMcpAutosave(configId);
  }
}

export async function handleMcpActionClick(event) {
  const target = event.target;
  if (!(target instanceof HTMLElement)) {
    return;
  }

  const actionNode = target.closest("[data-action][data-config-kind][data-config-id]");
  if (!(actionNode instanceof HTMLElement)) {
    return;
  }

  const action = actionNode.dataset.action;
  const configKind = actionNode.dataset.configKind;
  const configId = actionNode.dataset.configId;
  if (!action || !configKind || !configId) {
    return;
  }

  try {
    if (action === "expand") {
      toggleConfigExpanded(configKind, configId);
      const { renderMcpPanel, renderIntegrationPanel } = await import("./mcp-panel.js");
      if (configKind === "integration") {
        renderIntegrationPanel();
      } else {
        renderMcpPanel();
      }
      return;
    }

    if (action === "google-guide-toggle" && configKind === "mcp" && configId === "google_services") {
      state.googleGuideExpanded = !Boolean(state.googleGuideExpanded);
      const { renderMcpPanel } = await import("./mcp-panel.js");
      renderMcpPanel();
      return;
    }

    if (action === "save") {
      await persistMcpConfigsToSettings();
      setStatus(configKind === "integration" ? "Integration settings saved." : "Tool settings saved.");
      return;
    }

    if (action === "ssh-key") {
      const { fetchGitSshKey } = await import("./git-ssh.js");
      await fetchGitSshKey();
      setStatus("GitHub SSH public key copied to clipboard.");
      return;
    }

    if (action === "verify-ssh") {
      const { verifyGitSshAccess } = await import("./git-ssh.js");
      const result = await verifyGitSshAccess();
      const detail = typeof result?.detail === "string" ? result.detail.trim() : "";
      const message = detail ? `GitHub SSH verified: ${detail}` : "GitHub SSH access verified.";
      setStatus(message);
      showToast(message);
      return;
    }

    if (action === "google-login") {
      const { startGoogleOauthLogin } = await import("./google-oauth.js");
      await startGoogleOauthLogin();
      if (Boolean(state.googleOauthStatus?.connected)) {
        setStatus("Google account connected.");
      } else if (Boolean(state.googleOauthStatus?.needs_relogin)) {
        const detail = typeof state.googleOauthStatus?.detail === "string" ? state.googleOauthStatus.detail.trim() : "";
        setStatus(detail || "Google relogin is required.", true);
      } else {
        setStatus("Google login was closed.");
      }
      return;
    }

    if (action === "whatsapp-connect" && configKind === "mcp" && configId === "whatsapp") {
      const popup = window.open("/api/mcps/whatsapp/connect", "krill-whatsapp-connect", "width=560,height=760");
      if (!popup) {
        setStatus("Popup blocked. Allow popups for this site to connect WhatsApp.", true);
        return;
      }
      popup.focus();
      setStatus("WhatsApp connect window opened.");
      const checkTimer = window.setInterval(async () => {
        if (!popup || popup.closed) {
          window.clearInterval(checkTimer);
          const { syncWhatsappContactsWithRetry } = await import("./whatsapp.js");
          await syncWhatsappContactsWithRetry();
          const { renderMcpPanel } = await import("./mcp-panel.js");
          renderMcpPanel();
        }
      }, 1200);
      return;
    }

    if (action === "whatsapp-resync" && configKind === "mcp" && configId === "whatsapp") {
      const { syncWhatsappContactsWithRetry } = await import("./whatsapp.js");
      const syncResult = await syncWhatsappContactsWithRetry();
      const { renderMcpPanel } = await import("./mcp-panel.js");
      renderMcpPanel();
      const contacts = Array.isArray(syncResult?.contacts) ? syncResult.contacts : [];
      const count = contacts.length;
      if (count > 0) {
        if (syncResult?.cacheRetained) {
          const warning = typeof syncResult.warning === "string" && syncResult.warning.trim()
            ? syncResult.warning.trim()
            : "Resync returned no contacts. Kept previously cached contacts.";
          setStatus(`${warning} Cached contacts: ${count}.`, true);
          showToast(`Kept cached WhatsApp contacts (${count}).`);
        } else {
          setStatus(`WhatsApp contacts synced (${count}).`);
          showToast(`WhatsApp contacts synced (${count}).`);
        }
      } else {
        const warning = typeof syncResult?.warning === "string" && syncResult.warning.trim()
          ? syncResult.warning.trim()
          : "No WhatsApp contacts synced yet. Verify WhatsApp is ready, then retry.";
        setStatus(warning, true);
      }
      return;
    }

    if (action === "script-open" && configKind === "mcp" && configId === "scripts") {
      const scriptTitle = actionNode.dataset.scriptTitle;
      if (scriptTitle) {
        const { openScriptEditor } = await import("./scripts.js");
        await openScriptEditor(scriptTitle);
      }
      return;
    }

    if (action === "script-new" && configKind === "mcp" && configId === "scripts") {
      const { openNewScriptEditor } = await import("./scripts.js");
      openNewScriptEditor();
      return;
    }

    if (action === "verify") {
      if (configKind === "integration") {
        const result = await verifyIntegrationConfig(configId);
        const detail = typeof result?.detail === "string" ? result.detail.trim() : "";
        const message = detail ? `Integration verified: ${detail}` : "Integration verified.";
        setStatus(message);
        showToast(message);
        if (configId === "telegram" && timedJobsModal instanceof HTMLElement && !timedJobsModal.classList.contains("hidden")) {
          const { loadTimedJobs } = await import("./timed-jobs.js");
          await loadTimedJobs(true);
        }
      } else {
        const result = await verifyMcpConfig(configId);
        const detail = typeof result?.detail === "string" ? result.detail.trim() : "";
        const message = detail ? `Tool verified: ${detail}` : "Tool verified.";
        if (configId === "whatsapp") {
          const { syncWhatsappContactsWithRetry } = await import("./whatsapp.js");
          await syncWhatsappContactsWithRetry();
          const { renderMcpPanel } = await import("./mcp-panel.js");
          renderMcpPanel();
        }
        setStatus(message);
        showToast(message);
      }
      return;
    }
  } catch (error) {
    setStatus(error.message, true);
  }
}
