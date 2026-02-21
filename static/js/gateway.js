const form = document.getElementById("gateway-form");
const statusNode = document.getElementById("status");

const fields = {
  botName: document.getElementById("bot_name"),
  systemPrompt: document.getElementById("system_prompt"),
  activeProviderSelect: document.getElementById("active_provider_select"),
  activeModelSelect: document.getElementById("active_model_select"),
  activeApiKey: document.getElementById("active_api_key"),
  addProviderSelect: document.getElementById("add_provider_select"),
  addModelSelect: document.getElementById("add_model_select"),
  addApiKey: document.getElementById("add_api_key"),
  addProviderButton: document.getElementById("add-provider-btn"),
  resetButton: document.getElementById("reset-btn"),
};

const state = {
  providers: [],
  providerConfigs: {},
};

function setStatus(message, isError = false) {
  statusNode.textContent = message;
  statusNode.className = isError ? "error" : "ok";
}

function getProviderById(providerId) {
  return state.providers.find((provider) => provider.id === providerId);
}

function renderAddProviderOptions() {
  fields.addProviderSelect.innerHTML = "";

  state.providers.forEach((provider) => {
    const option = document.createElement("option");
    option.value = provider.id;
    option.textContent = provider.label;
    fields.addProviderSelect.appendChild(option);
  });

  renderAddModelOptions(fields.addProviderSelect.value);
}

function renderAddModelOptions(providerId) {
  const provider = getProviderById(providerId);
  fields.addModelSelect.innerHTML = "";

  if (!provider) {
    return;
  }

  provider.models.forEach((model) => {
    const option = document.createElement("option");
    option.value = model.id;
    option.textContent = model.label;
    fields.addModelSelect.appendChild(option);
  });
}

function renderActiveProviderOptions(selectedProviderId) {
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
    setStatus("No configured providers. Please add one.", true);
    return;
  }

  const nextProvider = configuredProviderIds.includes(selectedProviderId)
    ? selectedProviderId
    : configuredProviderIds[0];

  fields.activeProviderSelect.value = nextProvider;
  renderActiveProviderDetails(nextProvider);
}

function renderActiveProviderDetails(providerId) {
  const provider = getProviderById(providerId);
  const config = state.providerConfigs[providerId];

  fields.activeModelSelect.innerHTML = "";
  if (!provider || !config) {
    return;
  }

  provider.models.forEach((model) => {
    const option = document.createElement("option");
    option.value = model.id;
    option.textContent = model.label;
    fields.activeModelSelect.appendChild(option);
  });

  fields.activeModelSelect.value = config.model || provider.models[0]?.id || "";
  fields.activeApiKey.value = config.api_key || "";
}

function addOrUpdateProvider() {
  const providerId = fields.addProviderSelect.value;
  const modelId = fields.addModelSelect.value;
  const apiKey = fields.addApiKey.value;

  if (!providerId || !modelId) {
    setStatus("Select provider and model before adding.", true);
    return;
  }

  state.providerConfigs[providerId] = {
    api_key: apiKey,
    model: modelId,
  };

  renderActiveProviderOptions(fields.activeProviderSelect.value || providerId);
  setStatus("Provider added/updated. Save changes to persist.");
}

function syncActiveProviderConfig() {
  const providerId = fields.activeProviderSelect.value;

  if (!providerId) {
    return;
  }

  state.providerConfigs[providerId] = {
    api_key: fields.activeApiKey.value,
    model: fields.activeModelSelect.value,
  };
}

function buildPayload() {
  syncActiveProviderConfig();

  return {
    bot_name: fields.botName.value,
    system_prompt: fields.systemPrompt.value,
    setup_completed: true,
    active_provider_id: fields.activeProviderSelect.value,
    provider_configs: state.providerConfigs,
  };
}

async function saveGateway(event) {
  event.preventDefault();
  const payload = buildPayload();

  try {
    const response = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      throw new Error("Could not save changes.");
    }

    setStatus("Gateway settings saved.");
  } catch (error) {
    setStatus(error.message, true);
  }
}

async function resetEverything() {
  try {
    const response = await fetch("/api/reset", { method: "POST" });
    if (!response.ok) {
      throw new Error("Reset failed.");
    }

    window.location.href = "/setup";
  } catch (error) {
    setStatus(error.message, true);
  }
}

async function loadGateway() {
  try {
    const [providersResponse, settingsResponse] = await Promise.all([
      fetch("/api/providers"),
      fetch("/api/settings"),
    ]);

    if (!providersResponse.ok || !settingsResponse.ok) {
      throw new Error("Unable to load gateway data.");
    }

    state.providers = await providersResponse.json();
    const settings = await settingsResponse.json();
    state.providerConfigs = settings.provider_configs ?? {};

    fields.botName.value = settings.bot_name ?? "";
    fields.systemPrompt.value = settings.system_prompt ?? "";

    renderAddProviderOptions();
    renderActiveProviderOptions(settings.active_provider_id || "");
    setStatus("Gateway ready.");
  } catch (error) {
    setStatus(error.message, true);
  }
}

fields.addProviderSelect.addEventListener("change", () => {
  renderAddModelOptions(fields.addProviderSelect.value);
});

fields.activeProviderSelect.addEventListener("change", () => {
  renderActiveProviderDetails(fields.activeProviderSelect.value);
});

fields.activeModelSelect.addEventListener("change", syncActiveProviderConfig);
fields.activeApiKey.addEventListener("input", syncActiveProviderConfig);
fields.addProviderButton.addEventListener("click", addOrUpdateProvider);
fields.resetButton.addEventListener("click", resetEverything);
form.addEventListener("submit", saveGateway);
window.addEventListener("load", loadGateway);
