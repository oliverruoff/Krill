/*
 * Setup client: handles initial provider/tool/integration configuration,
 * advanced settings, import/export, and setup completion persistence.
 */

const form = document.getElementById("setup-form");
const landingView = document.getElementById("setup-landing");
const statusNode = document.getElementById("status");
const toastNode = document.getElementById("toast");

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
};

const MEMORY_MAX_LENGTH = 200000;

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
    return;
  }

  fields.modelSelect.value = "";
  renderProviderApiHelp("");
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
  const apiKey = fields.providerApiKey.value;

  if (!providerId || !modelId) {
    setStatus("Please choose a provider and model.", true);
    return;
  }

  fields.addProviderButton.disabled = true;
  setStatus("Checking API key...");

  try {
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

    renderProviderOptions();
    renderConfiguredProviders();
    renderCoreMemories();
    setModeFromSettings();
    state.initialSetupSnapshot = createSetupSnapshot();
    setStatus("Setup data loaded.");

    const searchParams = new URLSearchParams(window.location.search);
    if (searchParams.get("view_brain") === "1") {
      showConfigView();
      openBrainModal();
    }
  } catch (error) {
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
  if (!fields.braindumpFileInput.disabled) {
    fields.braindumpFileInput.click();
  }
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
  if (fields.setupBraindumpFileInput instanceof HTMLInputElement && !fields.setupBraindumpFileInput.disabled) {
    fields.setupBraindumpFileInput.click();
  }
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

fields.providerSelect.addEventListener("change", () => {
  renderModelOptions(fields.providerSelect.value);
  renderProviderApiHelp(fields.providerSelect.value);
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
window.addEventListener("load", loadPage);
