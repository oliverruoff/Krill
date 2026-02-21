const form = document.getElementById("settings-form");
const statusNode = document.getElementById("status");
const stepOne = document.getElementById("step-1");
const stepTwo = document.getElementById("step-2");
const nextButton = document.getElementById("next-btn");
const backButton = document.getElementById("back-btn");

const fields = {
  bot_name: document.getElementById("bot_name"),
  system_prompt: document.getElementById("system_prompt"),
  llm_provider: document.getElementById("llm_provider"),
  api_key: document.getElementById("api_key"),
};

function setStatus(message, isError = false) {
  statusNode.textContent = message;
  statusNode.className = isError ? "error" : "ok";
}

async function loadSettings() {
  try {
    const [providersResponse, settingsResponse] = await Promise.all([
      fetch("/api/providers"),
      fetch("/api/settings"),
    ]);

    if (!providersResponse.ok) {
      throw new Error("Unable to load providers.");
    }

    if (!settingsResponse.ok) {
      throw new Error("Unable to load settings.");
    }

    const providers = await providersResponse.json();
    const data = await settingsResponse.json();
    populateProviders(providers, data.llm_provider);

    fields.bot_name.value = data.bot_name ?? "";
    fields.system_prompt.value = data.system_prompt ?? "";
    fields.api_key.value = data.api_key ?? "";

    setStatus("Settings loaded.");
  } catch (error) {
    setStatus(error.message, true);
  }
}

function populateProviders(providers, selectedProvider) {
  fields.llm_provider.innerHTML = "";

  providers.forEach((provider) => {
    const option = document.createElement("option");
    option.value = provider.id;
    option.textContent = provider.label;
    fields.llm_provider.appendChild(option);
  });

  if (providers.length === 0) {
    setStatus("No providers are available.", true);
    return;
  }

  const isSupported = providers.some((provider) => provider.id === selectedProvider);
  fields.llm_provider.value = isSupported ? selectedProvider : providers[0].id;
}

function showStep(step) {
  if (step === 1) {
    stepOne.classList.remove("hidden");
    stepTwo.classList.add("hidden");
    return;
  }

  stepOne.classList.add("hidden");
  stepTwo.classList.remove("hidden");
}

function nextStep() {
  if (!fields.bot_name.value || !fields.system_prompt.value) {
    setStatus("Please fill bot name and system prompt first.", true);
    return;
  }

  showStep(2);
  setStatus("Now choose your provider and API key.");
}

function previousStep() {
  showStep(1);
  setStatus("Back to base settings.");
}

async function saveSettings(event) {
  event.preventDefault();

  const payload = {
    bot_name: fields.bot_name.value,
    system_prompt: fields.system_prompt.value,
    llm_provider: fields.llm_provider.value,
    api_key: fields.api_key.value,
  };

  try {
    const response = await fetch("/api/settings", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });

    if (response.ok) {
      setStatus("Successfully saved.");
      return;
    }

    if (response.status === 422) {
      setStatus("Validation failed. Check input limits and try again.", true);
      return;
    }

    setStatus("Save failed. Please try again.", true);
  } catch (error) {
    setStatus(error.message, true);
  }
}

window.onload = loadSettings;
nextButton.addEventListener("click", nextStep);
backButton.addEventListener("click", previousStep);
form.addEventListener("submit", saveSettings);
