const form = document.getElementById("setup-form");
const statusNode = document.getElementById("status");
const gatewayLink = document.getElementById("gateway-link");

const fields = {
  botName: document.getElementById("bot_name"),
  systemPrompt: document.getElementById("system_prompt"),
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

function addOrUpdateProvider() {
  const providerId = fields.providerSelect.value;
  const modelId = fields.modelSelect.value;
  const apiKey = fields.providerApiKey.value;

  if (!providerId || !modelId) {
    setStatus("Please choose a provider and model.", true);
    return;
  }

  state.providerConfigs[providerId] = {
    api_key: apiKey,
    model: modelId,
  };

  if (!state.activeProviderId) {
    state.activeProviderId = providerId;
  }

  renderConfiguredProviders();
  setStatus("Provider added/updated.");
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

fields.providerSelect.addEventListener("change", () => {
  renderModelOptions(fields.providerSelect.value);
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
