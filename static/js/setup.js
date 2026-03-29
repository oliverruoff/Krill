/*
 * Setup client: handles initial provider/tool/integration configuration,
 * advanced settings, import/export, and setup completion persistence.
 */

const form = document.getElementById("setup-form");
const landingView = document.getElementById("setup-landing");
const statusNode = document.getElementById("status");
const toastNode = document.getElementById("toast");
const timedJobAuthAlertNode = document.getElementById("timed-job-auth-alert");

const fields = {
  startScratchButton: document.getElementById("start-scratch-btn"),
  cancelButton: document.getElementById("cancel-btn"),
  braindumpFileInput: document.getElementById("braindump_file"),
  braindumpDropzone: document.getElementById("braindump_dropzone"),
  setupBraindumpFileInput: document.getElementById("setup_braindump_file"),
  setupImportBraindumpButton: document.getElementById("setup-import-braindump-btn"),
  botName: document.getElementById("bot_name"),
  userFullName: document.getElementById("user_full_name"),
  userCallName: document.getElementById("user_call_name"),
  systemPrompt: document.getElementById("system_prompt"),
  systemPromptCount: document.getElementById("system_prompt_count"),
  providerSelect: document.getElementById("provider_select"),
  modelSelect: document.getElementById("model_select"),
  providerApiHelp: document.getElementById("provider-api-help"),
  providerApiLink: document.getElementById("provider-api-link"),
  providerApiKey: document.getElementById("provider_api_key"),
  providerOauthPanel: document.getElementById("provider-oauth-panel"),
  providerOauthStatus: document.getElementById("provider-oauth-status"),
  providerOauthConnectButton: document.getElementById("provider-oauth-connect-btn"),
  providerOauthDisconnectButton: document.getElementById("provider-oauth-disconnect-btn"),
  providerOauthManualLabel: document.getElementById("provider-oauth-manual-label"),
  providerOauthManualInput: document.getElementById("provider_oauth_manual_input"),
  providerOauthCompleteButton: document.getElementById("provider-oauth-complete-btn"),
  coreMemoryInput: document.getElementById("core_memory_input"),
  addCoreMemoryButton: document.getElementById("add-core-memory-btn"),
  coreMemoryList: document.getElementById("core-memory-list"),
  providerList: document.getElementById("provider-list"),
  activeProviderSelect: document.getElementById("active_provider_select"),
  toolMaxRecursion: document.getElementById("tool_max_recursion"),
  toolTimeoutSeconds: document.getElementById("tool_timeout_seconds"),
  memoryExtractionInterval: document.getElementById("memory_extraction_interval"),
  addProviderButton: document.getElementById("add-provider-btn"),
  completeButton: document.getElementById("complete-btn"),
  viewBrainButton: document.getElementById("view-brain-btn"),
  brainModal: document.getElementById("brain-modal"),
  brainModalBackdrop: document.getElementById("brain-modal-backdrop"),
  brainModalClose: document.getElementById("brain-modal-close"),
  brainModalMeta: document.getElementById("brain-modal-meta"),
  brainRefreshButton: document.getElementById("brain-refresh-btn"),
  brainTableList: document.getElementById("brain-table-list"),
  brainTableTitle: document.getElementById("brain-table-title"),
  brainTableColumns: document.getElementById("brain-table-columns"),
  brainTableView: document.getElementById("brain-table-view"),
  appVersionNode: document.getElementById("app-version"),
};

const state = {
  providers: [],
  providerConfigs: {},
  coreMemories: [],
  normalMemories: [],
  chats: [],
  mcpConfigs: {},
  integrationConfigs: {},
  dailyTokenUsage: [],
  activeChatId: "",
  telegramState: { owner_user_id: "", last_update_id: 0 },
  activeProviderId: "",
  toolMaxRecursion: 6,
  toolTimeoutSeconds: 45,
  memoryExtractionInterval: 10,
  setupCompleted: false,
  initialSetupSnapshot: "",
  toastTimerId: null,
  brainTables: [],
  selectedBrainTable: "",
  brainLoading: false,
  theme: normalizeThemeMode(document.documentElement.getAttribute("data-theme")),
  oauthStatusByProvider: {},
  oauthBundleByProvider: {},
  oauthUnsupportedByProvider: {},
  timedJobAuthAlertSyncTimerId: null,
  timedJobAuthAlertSyncInFlight: false,
};

const TIMED_JOB_ALERT_SYNC_INTERVAL_MS = 8000;

const OAUTH_PROVIDER_CONFIG = {
  openai_codex_oauth: {
    label: "OpenAI",
    startUrl: "/api/providers/openai-codex/oauth/start?mode=manual",
    statusUrl: "/api/providers/openai-codex/oauth/status",
    modelsUrl: "/api/providers/openai-codex/oauth/models",
    completeUrl: "/api/providers/openai-codex/oauth/complete",
    disconnectUrl: "/api/providers/openai-codex/oauth/disconnect",
    popupEventType: "krill-openai-oauth-finished",
    connectButtonText: "Connect OpenAI",
    manualLabel: "Manual OAuth completion (paste redirect URL/code)",
    manualPlaceholder: "http://localhost:1455/auth/callback?code=...&state=...",
    completeFieldName: "redirect_url_or_code",
    connectHint: "Not connected yet. Click Connect OpenAI.",
    connectedText: (status, unsupported) => {
      const accountId = typeof status?.account_id === "string" ? status.account_id : "";
      const expiresIn = Number.isFinite(Number(status?.expires_in_seconds)) ? Number(status.expires_in_seconds) : 0;
      const expiryLabel = expiresIn > 0 ? `token expires in ${Math.ceil(expiresIn / 60)}m` : "token needs refresh";
      const unsupportedIds = unsupported.map((entry) => entry.id).filter(Boolean).join(", ");
      const suffix = unsupportedIds ? ` Unsupported on your account: ${unsupportedIds}.` : "";
      return `Connected to OpenAI OAuth (${accountId || "account unknown"}; ${expiryLabel}).${suffix}`;
    },
  },
  google_gemini_oauth: {
    label: "Google Gemini",
    startUrl: "/api/providers/google-gemini/oauth/start",
    statusUrl: "/api/providers/google-gemini/oauth/status",
    modelsUrl: "/api/providers/google-gemini/oauth/models",
    completeUrl: "/api/providers/google-gemini/oauth/complete",
    disconnectUrl: "/api/providers/google-gemini/oauth/disconnect",
    popupEventType: "krill-gemini-oauth-finished",
    connectButtonText: "Connect Gemini OAuth",
    manualLabel: "Manual Gemini OAuth completion (paste OAuth JSON or local file path)",
    manualPlaceholder: "{\"access_token\":\"...\"} or ~/.gemini/oauth_creds.json",
    completeFieldName: "oauth_payload_or_path",
    connectHint: "Not connected yet. Click Connect Gemini OAuth.",
    connectedText: (status, unsupported) => {
      const email = typeof status?.email === "string" ? status.email : "";
      const expiresIn = Number.isFinite(Number(status?.expires_in_seconds)) ? Number(status.expires_in_seconds) : 0;
      const expiryLabel = expiresIn > 0 ? `token expires in ${Math.ceil(expiresIn / 60)}m` : "token needs refresh";
      const unsupportedIds = unsupported.map((entry) => entry.id).filter(Boolean).join(", ");
      const suffix = unsupportedIds ? ` Unsupported on your account: ${unsupportedIds}.` : "";
      return `Connected to Gemini OAuth (${email || "account unknown"}; ${expiryLabel}).${suffix}`;
    },
  },
};

const MEMORY_MAX_LENGTH = 200000;

function normalizeThemeMode(value) {
  const v = String(value || "").trim().toLowerCase();
  if (v === "dark") return "dark";
  if (v === "business") return "business";
  return "light";
}

function applyThemeMode(theme) {
  const normalized = normalizeThemeMode(theme);
  state.theme = normalized;
  document.documentElement.setAttribute("data-theme", normalized);
  try {
    window.localStorage.setItem("krill-theme", normalized);
  } catch (_error) {
    // Ignore localStorage failures (private mode, blocked storage).
  }
  // Swap favicon for business theme.
  const favicon = document.getElementById("favicon");
  if (favicon) {
    favicon.href = normalized === "business"
      ? "/static/img/krill_icon_business.png"
      : "/static/img/krill_icon.png";
  }
}

function setStatus(message, isError = false) {
  statusNode.textContent = message;
  statusNode.className = isError ? "error" : "ok";
}

function showToast(message) {
  if (state.toastTimerId) {
    window.clearTimeout(state.toastTimerId);
  }

  toastNode.textContent = message;
  toastNode.classList.remove("hidden");
  state.toastTimerId = window.setTimeout(() => {
    toastNode.classList.add("hidden");
    state.toastTimerId = null;
  }, 1600);
}

function renderTimedJobAuthAlert(payload) {
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
    || `Timed jobs are suppressing repeated auth-expired alerts for ${providerLabel}. Reconnect the provider now.`;
  timedJobAuthAlertNode.classList.remove("hidden");
}

async function syncTimedJobAuthAlertStatus() {
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

function startTimedJobAuthAlertSync() {
  if (state.timedJobAuthAlertSyncTimerId) {
    window.clearInterval(state.timedJobAuthAlertSyncTimerId);
  }
  state.timedJobAuthAlertSyncTimerId = window.setInterval(
    syncTimedJobAuthAlertStatus,
    TIMED_JOB_ALERT_SYNC_INTERVAL_MS,
  );
}

function showLandingView() {
  landingView.classList.remove("hidden");
  form.classList.add("hidden");
}

function showConfigView() {
  landingView.classList.add("hidden");
  form.classList.remove("hidden");
}

function updateSystemPromptCounter() {
  const used = fields.systemPrompt.value.length;
  const maxLength = fields.systemPrompt.maxLength > 0 ? fields.systemPrompt.maxLength : 400;
  fields.systemPromptCount.textContent = `${used}/${maxLength}`;
}

function setImportingState(isImporting) {
  fields.startScratchButton.disabled = isImporting;
  fields.cancelButton.disabled = isImporting;
  fields.braindumpDropzone.classList.toggle("disabled", isImporting);
  fields.braindumpFileInput.disabled = isImporting;
  if (fields.setupImportBraindumpButton instanceof HTMLButtonElement) {
    fields.setupImportBraindumpButton.disabled = isImporting;
  }
  if (fields.setupBraindumpFileInput instanceof HTMLInputElement) {
    fields.setupBraindumpFileInput.disabled = isImporting;
  }
}

function getProviderById(providerId) {
  return state.providers.find((provider) => provider.id === providerId);
}

function renderProviderOptions() {
  fields.providerSelect.innerHTML = "";

  state.providers.forEach((provider) => {
    const option = document.createElement("option");
    option.value = provider.id;
    option.textContent = provider.label;
    fields.providerSelect.appendChild(option);
  });

  if (state.providers.length > 0) {
    renderModelOptions(fields.providerSelect.value);
    renderProviderApiHelp(fields.providerSelect.value);
    void refreshAllOauthStates()
      .then(() => renderProviderAuthInputs(fields.providerSelect.value));
    return;
  }

  fields.modelSelect.value = "";
  renderProviderApiHelp("");
  renderProviderAuthInputs("");
}

function renderModelOptions(providerId) {
  fields.modelSelect.innerHTML = "";
  const provider = getProviderById(providerId);

  if (!provider) {
    fields.modelSelect.value = "";
    return;
  }

  const existingConfig = state.providerConfigs[providerId];
  const existingModel = typeof existingConfig?.model === "string" ? existingConfig.model : "";

  provider.models.forEach((model) => {
    const option = document.createElement("option");
    option.value = model.id;
    option.textContent = model.label;
    fields.modelSelect.appendChild(option);
  });

  if (existingModel) {
    fields.modelSelect.value = existingModel;
  } else if (provider.models.length > 0) {
    fields.modelSelect.value = provider.models[0].id;
  } else {
    fields.modelSelect.value = "";
  }
}

function renderProviderApiHelp(providerId) {
  const provider = getProviderById(providerId);
  const apiKeyUrl = provider?.api_key_url;

  if (typeof apiKeyUrl !== "string" || !apiKeyUrl.trim()) {
    fields.providerApiHelp.classList.add("hidden");
    fields.providerApiLink.removeAttribute("href");
    return;
  }

  fields.providerApiLink.href = apiKeyUrl;
  fields.providerApiHelp.classList.remove("hidden");
}

function getOauthConfig(providerId) {
  return OAUTH_PROVIDER_CONFIG[providerId] || null;
}

function isOauthProvider(providerId) {
  const provider = getProviderById(providerId);
  if (!provider || provider.auth_mode !== "oauth") {
    return false;
  }
  return Boolean(getOauthConfig(providerId));
}

async function refreshOAuthStatus(providerId) {
  const config = getOauthConfig(providerId);
  if (!config) {
    return null;
  }
  try {
    const response = await fetch(config.statusUrl, { cache: "no-store" });
    if (!response.ok) {
      throw new Error("OAuth status unavailable.");
    }
    const payload = await response.json();
    const status = payload && typeof payload === "object" ? payload : null;
    const bundle = typeof payload?.credential_bundle === "string" ? payload.credential_bundle : "";
    state.oauthStatusByProvider[providerId] = status;
    state.oauthBundleByProvider[providerId] = bundle;
    if (state.providerConfigs[providerId]) {
      state.providerConfigs[providerId].api_key = bundle;
    }
    return status;
  } catch (_error) {
    state.oauthStatusByProvider[providerId] = null;
    return null;
  }
}

async function refreshOAuthSupportedModels(providerId) {
  const config = getOauthConfig(providerId);
  const provider = getProviderById(providerId);
  if (!config || !provider) {
    return;
  }
  const status = state.oauthStatusByProvider[providerId];
  if (!status?.connected) {
    state.oauthUnsupportedByProvider[providerId] = [];
    return;
  }
  try {
    const response = await fetch(config.modelsUrl, { cache: "no-store" });
    if (!response.ok) {
      throw new Error("Failed to load supported models.");
    }
    const payload = await response.json();
    const models = Array.isArray(payload?.models) ? payload.models : [];
    const unsupported = Array.isArray(payload?.unsupported_models) ? payload.unsupported_models : [];
    if (models.length > 0) {
      provider.models = models;
    }
    state.oauthUnsupportedByProvider[providerId] = unsupported;

    const currentModel = fields.modelSelect.value;
    if (fields.providerSelect.value === providerId) {
      renderModelOptions(providerId);
      if (currentModel && provider.models.some((entry) => entry.id === currentModel)) {
        fields.modelSelect.value = currentModel;
      }
    }
  } catch (_error) {
    // Keep current model list on failure.
  }
}

async function refreshAllOauthStates() {
  const providerIds = Object.keys(OAUTH_PROVIDER_CONFIG);
  for (const providerId of providerIds) {
    await refreshOAuthStatus(providerId);
    await refreshOAuthSupportedModels(providerId);
  }
}

function renderProviderAuthInputs(providerId) {
  const config = getOauthConfig(providerId);
  const isOauth = isOauthProvider(providerId);
  const apiKeyLabel = document.querySelector("label[for='provider_api_key']");

  if (apiKeyLabel instanceof HTMLElement) {
    apiKeyLabel.classList.toggle("hidden", isOauth);
  }
  fields.providerApiKey.classList.toggle("hidden", isOauth);
  if (isOauth) {
    fields.providerApiHelp.classList.add("hidden");
  } else {
    renderProviderApiHelp(providerId);
  }
  fields.providerOauthPanel.classList.toggle("hidden", !isOauth);

  if (!isOauth) {
    return;
  }

  const status = state.oauthStatusByProvider[providerId] || null;
  const connected = Boolean(status?.connected);
  const unsupported = Array.isArray(state.oauthUnsupportedByProvider[providerId])
    ? state.oauthUnsupportedByProvider[providerId]
    : [];

  fields.providerOauthConnectButton.textContent = config.connectButtonText;
  fields.providerOauthCompleteButton.textContent = `Complete ${config.label} OAuth`;
  fields.providerOauthManualLabel.textContent = config.manualLabel;
  fields.providerOauthManualInput.placeholder = config.manualPlaceholder;

  fields.providerOauthStatus.textContent = connected
    ? config.connectedText(status, unsupported)
    : config.connectHint;
}

async function startProviderOAuth(providerId) {
  const config = getOauthConfig(providerId);
  if (!config) {
    throw new Error("OAuth is not configured for this provider.");
  }
  const popup = window.open(config.startUrl, `krill-${providerId}-oauth`, "width=680,height=820");
  if (!popup) {
    throw new Error("Popup blocked. Please allow popups and try again.");
  }
  const startedAt = Date.now();
  const maxWaitMs = 120000;
  while (Date.now() - startedAt < maxWaitMs) {
    await new Promise((resolve) => window.setTimeout(resolve, 1200));
    if (popup.closed) {
      break;
    }
  }
  const status = await refreshOAuthStatus(providerId);
  await refreshOAuthSupportedModels(providerId);
  renderProviderAuthInputs(fields.providerSelect.value);
  if (!status?.connected) {
    throw new Error(`After approving ${config.label} OAuth, finish manual completion in Setup if needed.`);
  }

  const connectedConfig = state.providerConfigs[providerId] ?? { model: fields.modelSelect.value, api_key: "" };
  if (!connectedConfig.model) {
    connectedConfig.model = fields.modelSelect.value;
  }
  connectedConfig.api_key = connectedConfig.api_key || String(state.oauthBundleByProvider[providerId] || "");
  state.providerConfigs[providerId] = connectedConfig;
}

async function completeProviderOAuthManually(providerId) {
  const config = getOauthConfig(providerId);
  if (!config) {
    throw new Error("OAuth is not configured for this provider.");
  }
  const raw = String(fields.providerOauthManualInput.value || "").trim();
  if (!raw) {
    throw new Error("Paste OAuth payload first.");
  }

  const response = await fetch(config.completeUrl, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ [config.completeFieldName]: raw }),
  });

  if (!response.ok) {
    let detail = "Manual OAuth completion failed.";
    try {
      const payload = await response.json();
      if (typeof payload?.detail === "string" && payload.detail.trim()) {
        detail = payload.detail.trim();
      }
    } catch (_error) {
      // Keep fallback detail.
    }
    throw new Error(detail);
  }

  fields.providerOauthManualInput.value = "";
  await refreshOAuthStatus(providerId);
  await refreshOAuthSupportedModels(providerId);
  renderProviderAuthInputs(fields.providerSelect.value);
}

async function disconnectProviderOAuth(providerId) {
  const config = getOauthConfig(providerId);
  if (!config) {
    throw new Error("OAuth is not configured for this provider.");
  }
  const response = await fetch(config.disconnectUrl, { method: "POST" });
  if (!response.ok) {
    throw new Error(`Failed to disconnect ${config.label} OAuth.`);
  }
  if (state.providerConfigs[providerId]) {
    state.providerConfigs[providerId].api_key = "";
  }
  state.oauthBundleByProvider[providerId] = "";
  await refreshOAuthStatus(providerId);
  await refreshOAuthSupportedModels(providerId);
  renderProviderAuthInputs(fields.providerSelect.value);
}

function renderConfiguredProviders() {
  fields.providerList.innerHTML = "";
  const configuredProviderIds = Object.keys(state.providerConfigs);

  if (configuredProviderIds.length === 0) {
    fields.providerList.textContent = "No providers configured yet.";
    renderActiveProviderOptions();
    return;
  }

  configuredProviderIds.forEach((providerId) => {
    const provider = getProviderById(providerId);
    const item = document.createElement("div");
    item.className = "provider-item";

    const providerConfig = state.providerConfigs[providerId] ?? {};
    const modelLabel = provider?.models.find((model) => model.id === providerConfig.model)?.label;
    item.textContent = `${provider?.label ?? providerId} - ${modelLabel ?? providerConfig.model}`;

    const removeButton = document.createElement("button");
    removeButton.type = "button";
    removeButton.className = "danger ghost";
    removeButton.dataset.providerId = providerId;
    removeButton.textContent = "Remove";

    item.appendChild(removeButton);
    fields.providerList.appendChild(item);
  });

  renderActiveProviderOptions();
}

function renderActiveProviderOptions() {
  const configuredProviderIds = Object.keys(state.providerConfigs);
  fields.activeProviderSelect.innerHTML = "";

  configuredProviderIds.forEach((providerId) => {
    const provider = getProviderById(providerId);
    const option = document.createElement("option");
    option.value = providerId;
    option.textContent = provider?.label ?? providerId;
    fields.activeProviderSelect.appendChild(option);
  });

  if (configuredProviderIds.length === 0) {
    state.activeProviderId = "";
    return;
  }

  if (!configuredProviderIds.includes(state.activeProviderId)) {
    state.activeProviderId = configuredProviderIds[0];
  }

  fields.activeProviderSelect.value = state.activeProviderId;
}

async function addOrUpdateProvider() {
  const providerId = fields.providerSelect.value;
  const modelId = fields.modelSelect.value;
  const apiKey = isOauthProvider(providerId)
    ? String(state.oauthBundleByProvider[providerId] || "")
    : fields.providerApiKey.value;

  if (!providerId || !modelId) {
    setStatus("Please choose a provider and model.", true);
    return;
  }

  fields.addProviderButton.disabled = true;
  setStatus(isOauthProvider(providerId) ? "Checking OAuth connection..." : "Checking API key...");

  try {
    if (isOauthProvider(providerId) && !apiKey.trim()) {
      const oauthConfig = getOauthConfig(providerId);
      throw new Error(`${oauthConfig ? oauthConfig.label : "OAuth"} is not connected yet. Click Connect first.`);
    }
    await verifyProvider(providerId, modelId, apiKey);

    state.providerConfigs[providerId] = {
      api_key: apiKey,
      model: modelId,
    };

    if (!state.activeProviderId) {
      state.activeProviderId = providerId;
    }

    renderConfiguredProviders();
    setStatus("Provider verified and ready.");
  } catch (error) {
    setStatus(error.message, true);
  } finally {
    fields.addProviderButton.disabled = false;
  }
}

function removeProvider(providerId) {
  delete state.providerConfigs[providerId];
  if (getOauthConfig(providerId)) {
    state.oauthBundleByProvider[providerId] = "";
    state.oauthStatusByProvider[providerId] = null;
    state.oauthUnsupportedByProvider[providerId] = [];
  }

  if (state.activeProviderId === providerId) {
    state.activeProviderId = "";
  }

  renderConfiguredProviders();
  setStatus("Provider removed.");
}

function normalizeProviderConfigs(providerConfigs) {
  const normalized = {};
  const providerIds = Object.keys(providerConfigs).sort();

  providerIds.forEach((providerId) => {
    const config = providerConfigs[providerId] ?? {};
    normalized[providerId] = {
      api_key: String(config.api_key ?? ""),
      model: String(config.model ?? ""),
    };
  });

  return normalized;
}

function normalizeMemories(memories) {
  if (!Array.isArray(memories)) {
    return [];
  }

  return memories
    .filter((memory) => memory && typeof memory === "object")
    .map((memory) => {
      const content = typeof memory.content === "string" ? memory.content.trim().slice(0, MEMORY_MAX_LENGTH) : "";
      const createdAt = typeof memory.created_at === "string" ? memory.created_at.trim() : "";
      return { content, created_at: createdAt };
    })
    .filter((memory) => memory.content.length > 0);
}

function renderCoreMemories() {
  fields.coreMemoryList.innerHTML = "";

  if (!Array.isArray(state.coreMemories) || state.coreMemories.length === 0) {
    const emptyState = document.createElement("p");
    emptyState.className = "memory-empty";
    emptyState.textContent = "No core memories yet.";
    fields.coreMemoryList.appendChild(emptyState);
    return;
  }

  state.coreMemories.forEach((memory, index) => {
    const card = document.createElement("article");
    card.className = "memory-card";

    const row = document.createElement("div");
    row.className = "memory-card-row";

    const timestamp = document.createElement("span");
    timestamp.className = "memory-card-timestamp";
    timestamp.textContent = memory.created_at || "";

    const removeButton = document.createElement("button");
    removeButton.type = "button";
    removeButton.className = "memory-card-delete-btn";
    removeButton.dataset.coreMemoryIndex = String(index);
    removeButton.textContent = "x";
    removeButton.setAttribute("aria-label", "Delete core memory");

    row.appendChild(timestamp);
    row.appendChild(removeButton);

    const content = document.createElement("p");
    content.className = "memory-card-content";
    content.textContent = memory.content;

    card.appendChild(row);
    card.appendChild(content);
    fields.coreMemoryList.appendChild(card);
  });
}

function addCoreMemory() {
  const value = String(fields.coreMemoryInput.value || "").trim();
  if (!value) {
    setStatus("Please enter a core memory before adding.", true);
    return;
  }

  if (value.length > MEMORY_MAX_LENGTH) {
    setStatus(`Core memory must be at most ${MEMORY_MAX_LENGTH} characters.`, true);
    return;
  }

  state.coreMemories.push({
    content: value,
    created_at: new Date().toISOString(),
  });

  fields.coreMemoryInput.value = "";
  renderCoreMemories();
  setStatus("Core memory added.");
}

function removeCoreMemoryByIndex(indexValue) {
  const parsedIndex = Number.parseInt(String(indexValue), 10);
  if (!Number.isFinite(parsedIndex) || parsedIndex < 0 || parsedIndex >= state.coreMemories.length) {
    return;
  }

  state.coreMemories.splice(parsedIndex, 1);
  renderCoreMemories();
  setStatus("Core memory deleted.");
}

function createSetupSnapshot() {
  const maxRecursion = clampInteger(fields.toolMaxRecursion.value, 1, 20, state.toolMaxRecursion || 6);
  const timeoutSeconds = clampInteger(fields.toolTimeoutSeconds.value, 5, 300, state.toolTimeoutSeconds || 45);
  const extractionInterval = clampInteger(fields.memoryExtractionInterval.value, 1, 500, state.memoryExtractionInterval || 10);
  const snapshot = {
    bot_name: fields.botName.value,
    user_full_name: fields.userFullName.value,
    user_call_name: fields.userCallName.value,
    system_prompt: fields.systemPrompt.value,
    active_provider_id: fields.activeProviderSelect.value || "",
    provider_configs: normalizeProviderConfigs(state.providerConfigs),
    core_memories: normalizeMemories(state.coreMemories),
    normal_memories: normalizeMemories(state.normalMemories),
    chats: state.chats,
    mcp_configs: state.mcpConfigs,
    integration_configs: state.integrationConfigs,
    daily_token_usage: state.dailyTokenUsage,
    active_chat_id: state.activeChatId,
    telegram_state: state.telegramState,
    tool_max_recursion: maxRecursion,
    tool_timeout_seconds: timeoutSeconds,
    memory_extraction_interval: extractionInterval,
    theme: normalizeThemeMode(state.theme),
  };

  return JSON.stringify(snapshot);
}

function hasUnsavedChanges() {
  return createSetupSnapshot() !== state.initialSetupSnapshot;
}

function clampInteger(value, min, max, fallback) {
  const parsed = Number.parseInt(String(value), 10);
  if (!Number.isFinite(parsed)) {
    return fallback;
  }
  return Math.max(min, Math.min(max, parsed));
}

function buildPayload() {
  const maxRecursion = clampInteger(fields.toolMaxRecursion.value, 1, 20, 6);
  const timeoutSeconds = clampInteger(fields.toolTimeoutSeconds.value, 5, 300, 45);
  const extractionInterval = clampInteger(fields.memoryExtractionInterval.value, 1, 500, 10);
  fields.toolMaxRecursion.value = String(maxRecursion);
  fields.toolTimeoutSeconds.value = String(timeoutSeconds);
  fields.memoryExtractionInterval.value = String(extractionInterval);

  return {
    bot_name: fields.botName.value,
    user_full_name: fields.userFullName.value,
    user_call_name: fields.userCallName.value,
    system_prompt: fields.systemPrompt.value,
    setup_completed: true,
    active_provider_id: fields.activeProviderSelect.value,
    provider_configs: normalizeProviderConfigs(state.providerConfigs),
    core_memories: normalizeMemories(state.coreMemories),
    normal_memories: normalizeMemories(state.normalMemories),
    chats: state.chats,
    mcp_configs: state.mcpConfigs,
    integration_configs: state.integrationConfigs,
    daily_token_usage: state.dailyTokenUsage,
    active_chat_id: state.activeChatId,
    telegram_state: state.telegramState,
    tool_max_recursion: maxRecursion,
    tool_timeout_seconds: timeoutSeconds,
    memory_extraction_interval: extractionInterval,
    theme: normalizeThemeMode(state.theme),
  };
}

async function saveSetup(event) {
  event.preventDefault();

  const fullName = String(fields.userFullName.value || "").trim();
  const callName = String(fields.userCallName.value || "").trim();
  if (!fullName) {
    setStatus("Please enter your full name.", true);
    fields.userFullName.focus();
    return;
  }
  if (!callName) {
    setStatus("Please enter how Krill should call you.", true);
    fields.userCallName.focus();
    return;
  }

  fields.userFullName.value = fullName;
  fields.userCallName.value = callName;
  const payload = buildPayload();

  try {
    const response = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      let detail = "Setup save failed. Check provider, model, API key, and required user fields.";
      try {
        const data = await response.json();
        if (typeof data?.detail === "string" && data.detail.trim()) {
          detail = data.detail.trim();
        }
      } catch (parseError) {
        // Keep fallback detail.
      }
      throw new Error(detail);
    }

    state.setupCompleted = true;
    state.initialSetupSnapshot = createSetupSnapshot();
    setStatus("Setup saved. Redirecting to gateway...");
    window.setTimeout(() => {
      window.location.href = "/gateway";
    }, 550);
  } catch (error) {
    setStatus(error.message, true);
  }
}

async function verifyProvider(providerId, modelId, apiKey) {
  const response = await fetch("/api/providers/verify", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      provider_id: providerId,
      model: modelId,
      api_key: apiKey,
    }),
  });

  if (response.ok) {
    return;
  }

  let message = "Provider verification failed.";
  try {
    const data = await response.json();
    if (typeof data.detail === "string") {
      message = data.detail;
    }
  } catch (error) {
    message = "Provider verification failed.";
  }

  throw new Error(message);
}

function setModeFromSettings() {
  if (shouldForceConfigViewFromQuery()) {
    showConfigView();
    fields.completeButton.textContent = "Apply and Back to Gateway";
    return;
  }

  if (shouldOpenConfigViewFromLoadedState()) {
    showConfigView();
    fields.completeButton.textContent = "Apply and Back to Gateway";
    return;
  }

  showLandingView();
  fields.completeButton.textContent = "Apply and Back to Gateway";
}

function shouldForceConfigViewFromQuery() {
  const searchParams = new URLSearchParams(window.location.search);
  const editValue = String(searchParams.get("edit") || "").trim().toLowerCase();
  return editValue === "1" || editValue === "true" || editValue === "yes";
}

function shouldOpenConfigViewFromLoadedState() {
  if (state.setupCompleted) {
    return true;
  }

  if (Object.keys(state.providerConfigs).length > 0) {
    return true;
  }

  if (Array.isArray(state.coreMemories) && state.coreMemories.length > 0) {
    return true;
  }

  if (Array.isArray(state.normalMemories) && state.normalMemories.length > 0) {
    return true;
  }

  if (Array.isArray(state.chats) && state.chats.length > 0) {
    return true;
  }

  if (Object.keys(state.mcpConfigs).length > 0) {
    return true;
  }

  if (Object.keys(state.integrationConfigs).length > 0) {
    return true;
  }

  if (Array.isArray(state.dailyTokenUsage) && state.dailyTokenUsage.length > 0) {
    return true;
  }

  return false;
}

async function loadPage() {
  try {
    loadAppVersion();
    const [providersResponse, settingsResponse] = await Promise.all([
      fetch("/api/providers"),
      fetch("/api/settings"),
    ]);

    if (!providersResponse.ok || !settingsResponse.ok) {
      throw new Error("Unable to load setup data.");
    }

    state.providers = await providersResponse.json();
    const settings = await settingsResponse.json();

    fields.botName.value = settings.bot_name ?? "";
    fields.userFullName.value = settings.user_full_name ?? "";
    fields.userCallName.value = settings.user_call_name ?? "";
    fields.systemPrompt.value = settings.system_prompt ?? "";
    updateSystemPromptCounter();

    state.providerConfigs = settings.provider_configs ?? {};
    state.coreMemories = normalizeMemories(settings.core_memories);
    state.normalMemories = normalizeMemories(settings.normal_memories);
    state.chats = Array.isArray(settings.chats) ? settings.chats : [];
    state.mcpConfigs = settings.mcp_configs && typeof settings.mcp_configs === "object" ? settings.mcp_configs : {};
    state.integrationConfigs = settings.integration_configs && typeof settings.integration_configs === "object"
      ? settings.integration_configs
      : {};
    state.dailyTokenUsage = Array.isArray(settings.daily_token_usage) ? settings.daily_token_usage : [];
    state.activeChatId = typeof settings.active_chat_id === "string" ? settings.active_chat_id : "";
    state.telegramState = settings.telegram_state && typeof settings.telegram_state === "object"
      ? settings.telegram_state
      : { owner_user_id: "", last_update_id: 0 };
    state.activeProviderId = settings.active_provider_id ?? "";
    state.toolMaxRecursion = Number.isFinite(Number(settings.tool_max_recursion)) ? Number(settings.tool_max_recursion) : 6;
    state.toolTimeoutSeconds = Number.isFinite(Number(settings.tool_timeout_seconds)) ? Number(settings.tool_timeout_seconds) : 45;
    state.memoryExtractionInterval = Number.isFinite(Number(settings.memory_extraction_interval))
      ? Number(settings.memory_extraction_interval)
      : 10;
    fields.toolMaxRecursion.value = String(Math.max(1, Math.min(20, state.toolMaxRecursion)));
    fields.toolTimeoutSeconds.value = String(Math.max(5, Math.min(300, state.toolTimeoutSeconds)));
    fields.memoryExtractionInterval.value = String(Math.max(1, Math.min(500, state.memoryExtractionInterval)));
    state.setupCompleted = settings.setup_completed ?? false;
    applyThemeMode(settings.theme);

    renderProviderOptions();
    await refreshAllOauthStates();
    renderProviderAuthInputs(fields.providerSelect.value);
    renderConfiguredProviders();
    renderCoreMemories();
    setModeFromSettings();
    startTimedJobAuthAlertSync();
    await syncTimedJobAuthAlertStatus();
    state.initialSetupSnapshot = createSetupSnapshot();
    setStatus("Setup data loaded.");

    const searchParams = new URLSearchParams(window.location.search);
    if (searchParams.get("view_brain") === "1") {
      showConfigView();
      openBrainModal();
    }
  } catch (error) {
    renderTimedJobAuthAlert({ active: false });
    setStatus(error.message, true);
  }
}

async function loadAppVersion() {
  if (!(fields.appVersionNode instanceof HTMLElement)) {
    return;
  }
  try {
    const response = await fetch("/api/version", { cache: "no-store" });
    if (!response.ok) {
      return;
    }
    const payload = await response.json();
    const version = typeof payload?.version === "string" ? payload.version.trim() : "";
    if (!version) {
      return;
    }
    fields.appVersionNode.textContent = `v${version}`;
  } catch (error) {
    // Best-effort display.
  }
}

function openFilePicker() {
  openBraindumpPicker(fields.braindumpFileInput);
}

function openBraindumpPicker(input) {
  if (!(input instanceof HTMLInputElement) || input.disabled) {
    return;
  }

  input.value = "";

  if (typeof input.showPicker === "function") {
    try {
      input.showPicker();
      return;
    } catch {
      // Fall through to click fallback.
    }
  }

  try {
    input.click();
    return;
  } catch {
    // Fall through to detached-input fallback.
  }

  const fallbackInput = document.createElement("input");
  fallbackInput.type = "file";
  fallbackInput.accept = ".db";
  fallbackInput.style.position = "fixed";
  fallbackInput.style.left = "-9999px";
  fallbackInput.style.top = "0";

  fallbackInput.addEventListener("change", () => {
    const file = fallbackInput.files?.[0];
    fallbackInput.remove();
    if (file) {
      importBraindumpFile(file);
    }
  });

  document.body.appendChild(fallbackInput);
  fallbackInput.click();
}

async function importBraindumpFile(file) {
  if (!file) {
    setStatus("Please choose a braindump.db file.", true);
    return;
  }

  const shouldImport = window.confirm(
    "Importing braindump.db will replace your current state. Continue?"
  );
  if (!shouldImport) {
    return;
  }

  setImportingState(true);
  setStatus("Importing braindump...");

  try {
    const formData = new FormData();
    formData.append("file", file);

    const response = await fetch("/api/braindump/import", {
      method: "POST",
      body: formData,
    });

    if (!response.ok) {
      let detail = "Braindump import failed.";
      try {
        const errorData = await response.json();
        if (typeof errorData.detail === "string") {
          detail = errorData.detail;
        }
      } catch (error) {
        detail = "Braindump import failed.";
      }

      throw new Error(detail);
    }

    showToast("Braindump loaded");
    setStatus("Braindump imported. Redirecting to gateway...");
    window.setTimeout(() => {
      window.location.href = "/gateway";
    }, 800);
  } catch (error) {
    const message = error.message || "Invalid braindump.db file.";
    setStatus(message, true);
    showToast(message);
  } finally {
    fields.braindumpFileInput.value = "";
    if (fields.setupBraindumpFileInput instanceof HTMLInputElement) {
      fields.setupBraindumpFileInput.value = "";
    }
    setImportingState(false);
  }
}

function openSetupImportPicker() {
  openBraindumpPicker(fields.setupBraindumpFileInput);
}

function renderBrainTableList() {
  fields.brainTableList.innerHTML = "";

  if (!Array.isArray(state.brainTables) || state.brainTables.length === 0) {
    const emptyNode = document.createElement("p");
    emptyNode.className = "memory-empty";
    emptyNode.textContent = "No tables found.";
    fields.brainTableList.appendChild(emptyNode);
    return;
  }

  state.brainTables.forEach((table) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "brain-table-item";
    if (table.name === state.selectedBrainTable) {
      button.classList.add("active");
    }
    button.dataset.tableName = table.name;
    button.textContent = `${table.name} (${table.row_count})`;
    fields.brainTableList.appendChild(button);
  });
}

function renderSelectedBrainTable() {
  const table = state.brainTables.find((entry) => entry.name === state.selectedBrainTable);
  if (!table) {
    fields.brainTableTitle.textContent = "Select a table";
    fields.brainTableColumns.textContent = "";
    fields.brainTableView.innerHTML = "";
    return;
  }

  fields.brainTableTitle.textContent = `${table.name} (${table.row_count} rows)`;
  const columnLabels = Array.isArray(table.columns)
    ? table.columns.map((column) => `${column.name}:${column.type || "text"}`)
    : [];
  fields.brainTableColumns.textContent = columnLabels.length > 0 ? columnLabels.join(" | ") : "No columns";

  fields.brainTableView.innerHTML = "";
  const rows = Array.isArray(table.rows) ? table.rows : [];
  const columns = Array.isArray(table.columns) ? table.columns : [];
  if (rows.length === 0 || columns.length === 0) {
    const emptyNode = document.createElement("p");
    emptyNode.className = "memory-empty";
    emptyNode.textContent = "No rows in this table.";
    fields.brainTableView.appendChild(emptyNode);
    return;
  }

  const tableNode = document.createElement("table");
  tableNode.className = "brain-grid";

  const thead = document.createElement("thead");
  const headRow = document.createElement("tr");
  columns.forEach((column) => {
    const th = document.createElement("th");
    th.textContent = column.name;
    headRow.appendChild(th);
  });
  thead.appendChild(headRow);
  tableNode.appendChild(thead);

  const tbody = document.createElement("tbody");
  rows.forEach((row) => {
    const tr = document.createElement("tr");
    columns.forEach((column) => {
      const td = document.createElement("td");
      const value = row[column.name];
      td.textContent = value === null || value === undefined ? "" : String(value);
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
  tableNode.appendChild(tbody);
  fields.brainTableView.appendChild(tableNode);
}

async function loadBrainView() {
  if (state.brainLoading) {
    return;
  }

  state.brainLoading = true;
  fields.brainModalMeta.textContent = "Loading brain tables...";
  fields.brainRefreshButton.disabled = true;

  try {
    const response = await fetch("/api/braindump/view");
    if (!response.ok) {
      throw new Error("Failed to load brain view.");
    }
    const payload = await response.json();
    const tables = Array.isArray(payload.tables) ? payload.tables : [];
    state.brainTables = tables;
    if (!tables.some((table) => table.name === state.selectedBrainTable)) {
      state.selectedBrainTable = tables[0]?.name ?? "";
    }
    fields.brainModalMeta.textContent = `${payload.table_count ?? tables.length} tables loaded`;
    renderBrainTableList();
    renderSelectedBrainTable();
  } catch (error) {
    fields.brainModalMeta.textContent = error.message || "Failed to load brain tables.";
    state.brainTables = [];
    state.selectedBrainTable = "";
    renderBrainTableList();
    renderSelectedBrainTable();
  } finally {
    state.brainLoading = false;
    fields.brainRefreshButton.disabled = false;
  }
}

function openBrainModal() {
  if (!(fields.brainModal instanceof HTMLElement)) {
    return;
  }
  fields.brainModal.classList.remove("hidden");
  document.body.style.overflow = "hidden";
  loadBrainView();
}

function closeBrainModal() {
  if (!(fields.brainModal instanceof HTMLElement)) {
    return;
  }
  fields.brainModal.classList.add("hidden");
  document.body.style.overflow = "";
}

function handleDropzoneKeydown(event) {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    openFilePicker();
  }
}

function startFromScratch() {
  showConfigView();
  setStatus("Configure your assistant, then save to continue.");
}

function cancelSetupChanges() {
  if (hasUnsavedChanges()) {
    const shouldDiscard = window.confirm("Discard unsaved changes and return to gateway?");
    if (!shouldDiscard) {
      return;
    }
  }

  window.location.href = "/gateway";
}

function handleEscapeToGateway(event) {
  if (event.key !== "Escape") {
    return;
  }

  if (fields.brainModal instanceof HTMLElement && !fields.brainModal.classList.contains("hidden")) {
    event.preventDefault();
    closeBrainModal();
    return;
  }

  event.preventDefault();
  cancelSetupChanges();
}

fields.providerSelect.addEventListener("change", async () => {
  renderModelOptions(fields.providerSelect.value);
  renderProviderApiHelp(fields.providerSelect.value);
  await refreshAllOauthStates();
  renderProviderAuthInputs(fields.providerSelect.value);
});

fields.systemPrompt.addEventListener("input", updateSystemPromptCounter);
fields.coreMemoryInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    addCoreMemory();
  }
});
fields.addCoreMemoryButton.addEventListener("click", addCoreMemory);
fields.startScratchButton.addEventListener("click", startFromScratch);
fields.cancelButton.addEventListener("click", cancelSetupChanges);

fields.braindumpDropzone.addEventListener("click", openFilePicker);
fields.braindumpDropzone.addEventListener("keydown", handleDropzoneKeydown);

fields.braindumpFileInput.addEventListener("change", () => {
  const file = fields.braindumpFileInput.files?.[0];
  if (file) {
    importBraindumpFile(file);
  }
});

fields.braindumpDropzone.addEventListener("dragover", (event) => {
  event.preventDefault();
  fields.braindumpDropzone.classList.add("dropzone-active");
});

fields.braindumpDropzone.addEventListener("dragleave", () => {
  fields.braindumpDropzone.classList.remove("dropzone-active");
});

fields.braindumpDropzone.addEventListener("drop", (event) => {
  event.preventDefault();
  fields.braindumpDropzone.classList.remove("dropzone-active");

  const file = event.dataTransfer?.files?.[0];
  if (file) {
    importBraindumpFile(file);
  }
});

if (fields.setupImportBraindumpButton instanceof HTMLButtonElement) {
  fields.setupImportBraindumpButton.addEventListener("click", openSetupImportPicker);
}

if (fields.setupBraindumpFileInput instanceof HTMLInputElement) {
  fields.setupBraindumpFileInput.addEventListener("change", () => {
    const file = fields.setupBraindumpFileInput.files?.[0];
    if (file) {
      importBraindumpFile(file);
    }
  });
}

fields.viewBrainButton.addEventListener("click", openBrainModal);
fields.brainModalClose.addEventListener("click", closeBrainModal);
fields.brainModalBackdrop.addEventListener("click", closeBrainModal);
fields.brainRefreshButton.addEventListener("click", loadBrainView);
fields.brainTableList.addEventListener("click", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLButtonElement)) {
    return;
  }

  const tableName = target.dataset.tableName;
  if (!tableName) {
    return;
  }

  state.selectedBrainTable = tableName;
  renderBrainTableList();
  renderSelectedBrainTable();
});

fields.addProviderButton.addEventListener("click", addOrUpdateProvider);

if (fields.providerOauthConnectButton instanceof HTMLButtonElement) {
  fields.providerOauthConnectButton.addEventListener("click", async () => {
    const providerId = fields.providerSelect.value;
    const oauthConfig = getOauthConfig(providerId);
    if (!oauthConfig) {
      setStatus("Selected provider does not support OAuth connect flow.", true);
      return;
    }
    fields.providerOauthConnectButton.disabled = true;
    setStatus(`Opening ${oauthConfig.label} OAuth...`);
    try {
      await startProviderOAuth(providerId);
      await syncTimedJobAuthAlertStatus();
      setStatus(`${oauthConfig.label} OAuth connected. Add provider to save.`);
    } catch (error) {
      setStatus(error.message, true);
    } finally {
      fields.providerOauthConnectButton.disabled = false;
    }
  });
}

if (fields.providerOauthCompleteButton instanceof HTMLButtonElement) {
  fields.providerOauthCompleteButton.addEventListener("click", async () => {
    const providerId = fields.providerSelect.value;
    const oauthConfig = getOauthConfig(providerId);
    if (!oauthConfig) {
      setStatus("Selected provider does not support manual OAuth completion.", true);
      return;
    }
    fields.providerOauthCompleteButton.disabled = true;
    setStatus(`Completing manual ${oauthConfig.label} OAuth...`);
    try {
      await completeProviderOAuthManually(providerId);
      await syncTimedJobAuthAlertStatus();
      setStatus(`${oauthConfig.label} OAuth connected. Add provider to save.`);
    } catch (error) {
      setStatus(error.message, true);
    } finally {
      fields.providerOauthCompleteButton.disabled = false;
    }
  });
}

if (fields.providerOauthDisconnectButton instanceof HTMLButtonElement) {
  fields.providerOauthDisconnectButton.addEventListener("click", async () => {
    const providerId = fields.providerSelect.value;
    const oauthConfig = getOauthConfig(providerId);
    if (!oauthConfig) {
      setStatus("Selected provider does not support OAuth disconnect.", true);
      return;
    }
    fields.providerOauthDisconnectButton.disabled = true;
    try {
      await disconnectProviderOAuth(providerId);
      await syncTimedJobAuthAlertStatus();
      setStatus(`${oauthConfig.label} OAuth disconnected.`);
    } catch (error) {
      setStatus(error.message, true);
    } finally {
      fields.providerOauthDisconnectButton.disabled = false;
    }
  });
}

window.addEventListener("message", async (event) => {
  if (event.origin !== window.location.origin) {
    return;
  }
  const eventType = String(event.data?.type || "");
  const providerEntry = Object.entries(OAUTH_PROVIDER_CONFIG).find(([, config]) => config.popupEventType === eventType);
  if (!providerEntry) {
    return;
  }
  const providerId = providerEntry[0];
  await refreshOAuthStatus(providerId);
  await refreshOAuthSupportedModels(providerId);
  await syncTimedJobAuthAlertStatus();
  renderProviderAuthInputs(fields.providerSelect.value);
});

fields.coreMemoryList.addEventListener("click", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLButtonElement)) {
    return;
  }

  const memoryIndex = target.dataset.coreMemoryIndex;
  if (typeof memoryIndex !== "string") {
    return;
  }

  removeCoreMemoryByIndex(memoryIndex);
});

fields.providerList.addEventListener("click", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLButtonElement)) {
    return;
  }

  const providerId = target.dataset.providerId;
  if (!providerId) {
    return;
  }

  removeProvider(providerId);
});

fields.activeProviderSelect.addEventListener("change", () => {
  state.activeProviderId = fields.activeProviderSelect.value;
});

form.addEventListener("submit", saveSetup);
document.addEventListener("keydown", handleEscapeToGateway);
window.addEventListener("beforeunload", () => {
  if (state.timedJobAuthAlertSyncTimerId) {
    window.clearInterval(state.timedJobAuthAlertSyncTimerId);
    state.timedJobAuthAlertSyncTimerId = null;
  }
});
window.addEventListener("load", loadPage);
