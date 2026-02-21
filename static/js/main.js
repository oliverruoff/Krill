const form = document.getElementById("settings-form");
const statusNode = document.getElementById("status");

const fields = {
  bot_name: document.getElementById("bot_name"),
  system_prompt: document.getElementById("system_prompt"),
  api_key: document.getElementById("api_key"),
};

function setStatus(message, isError = false) {
  statusNode.textContent = message;
  statusNode.className = isError ? "error" : "ok";
}

async function loadSettings() {
  try {
    const response = await fetch("/api/settings");
    if (!response.ok) {
      throw new Error("Unable to load settings.");
    }

    const data = await response.json();
    fields.bot_name.value = data.bot_name ?? "";
    fields.system_prompt.value = data.system_prompt ?? "";
    fields.api_key.value = data.api_key ?? "";
    setStatus("Settings loaded.");
  } catch (error) {
    setStatus(error.message, true);
  }
}

async function saveSettings(event) {
  event.preventDefault();

  const payload = {
    bot_name: fields.bot_name.value,
    system_prompt: fields.system_prompt.value,
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
form.addEventListener("submit", saveSettings);
