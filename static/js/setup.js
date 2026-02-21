const form = document.getElementById("setup-form");
const statusNode = document.getElementById("status");
const gatewayLink = document.getElementById("gateway-link");

const fields = {
  startScratchButton: document.getElementById("start-scratch-btn"),
  braindumpFileInput: document.getElementById("braindump_file"),
  braindumpDropzone: document.getElementById("braindump_dropzone"),
  importBraindumpButton: document.getElementById("import-braindump-btn"),
  botName: document.getElementById("bot_name"),
  systemPrompt: document.getElementById("system_prompt"),
  systemPromptCount: document.getElementById("system_prompt_count"),
  providerSelect: document.getElementById("provider_select"),
  modelSelect: document.getElementById("model_select"),
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
};

function setStatus(message, isError = false) {
  statusNode.textContent = message;
  statusNode.className = isError ? "error" : "ok";
}

function updateSystemPromptCounter() {
  const used = fields.systemPrompt.value.length;
  fields.systemPromptCount.textContent = `${used}/200`;
}

function setImportingState(isImporting) {
  fields.importBraindumpButton.disabled = isImporting;
  fields.startScratchButton.disabled = isImporting;
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
  }
}

function renderModelOptions(providerId) {
  fields.modelSelect.innerHTML = "";
  const provider = getProviderById(providerId);

  if (!provider) {
    return;
  }

  provider.models.forEach((model) => {
    const option = document.createElement("option");
    option.value = model.id;
    option.textContent = model.label;
    fields.modelSelect.appendChild(option);
  });
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

    const modelLabel = provider?.models.find((model) => model.id === state.providerConfigs[providerId].model)?.label;
    item.textContent = `${provider?.label ?? providerId} - ${modelLabel ?? state.providerConfigs[providerId].model}`;

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
  setStatus("checking API key.");

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
    setStatus("Provider verified and saved in setup form.");
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

function buildPayload() {
  return {
    bot_name: fields.botName.value,
    system_prompt: fields.systemPrompt.value,
    setup_completed: true,
    active_provider_id: fields.activeProviderSelect.value,
    provider_configs: state.providerConfigs,
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
      throw new Error("Setup save failed. Check provider/model/api key.");
    }

    state.setupCompleted = true;
    gatewayLink.classList.remove("hidden");
    fields.completeButton.textContent = "Save Changes";
    setStatus("Setup saved. Redirecting to gateway...");
    window.setTimeout(() => {
      window.location.href = "/gateway";
    }, 500);
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

    if (state.setupCompleted) {
      fields.completeButton.textContent = "Save Changes";
      gatewayLink.classList.remove("hidden");
    }

    setStatus("Setup data loaded.");
  } catch (error) {
    setStatus(error.message, true);
  }
}

async function startFromScratch() {
  const confirmed = window.confirm(
    "Start from scratch? This will immediately replace your current braindump state."
  );

  if (!confirmed) {
    setStatus("Start from scratch cancelled.");
    return;
  }

  setImportingState(true);
  setStatus("Resetting state...");

  try {
    const response = await fetch("/api/reset", { method: "POST" });
    if (!response.ok) {
      throw new Error("Failed to reset settings.");
    }

    await loadPage();
    setStatus("Started from scratch.");
  } catch (error) {
    setStatus(error.message, true);
  } finally {
    setImportingState(false);
  }
}

function setFile(file) {
  const dataTransfer = new DataTransfer();
  dataTransfer.items.add(file);
  fields.braindumpFileInput.files = dataTransfer.files;
}

async function importBraindump() {
  const file = fields.braindumpFileInput.files?.[0];
  if (!file) {
    setStatus("Please choose a braindump.json file first.", true);
    return;
  }

  setImportingState(true);
  setStatus("Importing braindump...");

  try {
    const text = await file.text();
    const payload = JSON.parse(text);

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

    await loadPage();
    setStatus("Braindump imported and applied.");
  } catch (error) {
    setStatus(error.message || "Invalid braindump.json file.", true);
  } finally {
    setImportingState(false);
  }
}

fields.providerSelect.addEventListener("change", () => {
  renderModelOptions(fields.providerSelect.value);
});

fields.systemPrompt.addEventListener("input", updateSystemPromptCounter);

fields.startScratchButton.addEventListener("click", startFromScratch);
fields.importBraindumpButton.addEventListener("click", importBraindump);

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
  if (!file) {
    return;
  }

  setFile(file);
  setStatus(`Selected file: ${file.name}`);
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
window.addEventListener("load", loadPage);
