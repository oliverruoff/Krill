const form = document.getElementById("setup-form");
const landingView = document.getElementById("setup-landing");
const statusNode = document.getElementById("status");
const toastNode = document.getElementById("toast");

const fields = {
  startScratchButton: document.getElementById("start-scratch-btn"),
  cancelButton: document.getElementById("cancel-btn"),
  braindumpFileInput: document.getElementById("braindump_file"),
  braindumpDropzone: document.getElementById("braindump_dropzone"),
  botName: document.getElementById("bot_name"),
  systemPrompt: document.getElementById("system_prompt"),
  systemPromptCount: document.getElementById("system_prompt_count"),
  providerSelect: document.getElementById("provider_select"),
  modelSelect: document.getElementById("model_select"),
  providerApiHelp: document.getElementById("provider-api-help"),
  providerApiLink: document.getElementById("provider-api-link"),
  providerApiKey: document.getElementById("provider_api_key"),
  providerList: document.getElementById("provider-list"),
  activeProviderSelect: document.getElementById("active_provider_select"),
  addProviderButton: document.getElementById("add-provider-btn"),
  completeButton: document.getElementById("complete-btn"),
};

const state = {
  providers: [],
  providerConfigs: {},
  activeProviderId: "",
  setupCompleted: false,
  initialSetupSnapshot: "",
  toastTimerId: null,
};

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
  fields.systemPromptCount.textContent = `${used}/200`;
}

function setImportingState(isImporting) {
  fields.startScratchButton.disabled = isImporting;
  fields.cancelButton.disabled = isImporting;
  fields.braindumpDropzone.classList.toggle("disabled", isImporting);
  fields.braindumpFileInput.disabled = isImporting;
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

function createSetupSnapshot() {
  const snapshot = {
    bot_name: fields.botName.value,
    system_prompt: fields.systemPrompt.value,
    active_provider_id: fields.activeProviderSelect.value || "",
    provider_configs: normalizeProviderConfigs(state.providerConfigs),
  };

  return JSON.stringify(snapshot);
}

function hasUnsavedChanges() {
  return createSetupSnapshot() !== state.initialSetupSnapshot;
}

function buildPayload() {
  return {
    bot_name: fields.botName.value,
    system_prompt: fields.systemPrompt.value,
    setup_completed: true,
    active_provider_id: fields.activeProviderSelect.value,
    provider_configs: normalizeProviderConfigs(state.providerConfigs),
  };
}

async function saveSetup(event) {
  event.preventDefault();
  const payload = buildPayload();

  try {
    const response = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      throw new Error("Setup save failed. Check provider, model, and API key.");
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
  if (state.setupCompleted) {
    showConfigView();
    fields.completeButton.textContent = "Apply and Back to Gateway";
    return;
  }

  showLandingView();
  fields.completeButton.textContent = "Apply and Back to Gateway";
}

async function loadPage() {
  try {
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
    fields.systemPrompt.value = settings.system_prompt ?? "";
    updateSystemPromptCounter();

    state.providerConfigs = settings.provider_configs ?? {};
    state.activeProviderId = settings.active_provider_id ?? "";
    state.setupCompleted = settings.setup_completed ?? false;

    renderProviderOptions();
    renderConfiguredProviders();
    setModeFromSettings();
    state.initialSetupSnapshot = createSetupSnapshot();
    setStatus("Setup data loaded.");
  } catch (error) {
    setStatus(error.message, true);
  }
}

function openFilePicker() {
  if (!fields.braindumpFileInput.disabled) {
    fields.braindumpFileInput.click();
  }
}

async function importBraindumpFile(file) {
  if (!file) {
    setStatus("Please choose a braindump.json file.", true);
    return;
  }

  setImportingState(true);
  setStatus("Importing braindump...");

  try {
    const text = await file.text();
    const payload = JSON.parse(text);
    payload.setup_completed = true;

    const response = await fetch("/api/braindump/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
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
    const message = error.message || "Invalid braindump.json file.";
    setStatus(message, true);
    showToast(message);
  } finally {
    fields.braindumpFileInput.value = "";
    setImportingState(false);
  }
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

  event.preventDefault();
  cancelSetupChanges();
}

fields.providerSelect.addEventListener("change", () => {
  renderModelOptions(fields.providerSelect.value);
  renderProviderApiHelp(fields.providerSelect.value);
});

fields.systemPrompt.addEventListener("input", updateSystemPromptCounter);
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

fields.addProviderButton.addEventListener("click", addOrUpdateProvider);

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
