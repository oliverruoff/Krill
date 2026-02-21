const chatForm = document.getElementById("chat-form");
const chatInput = document.getElementById("chat-input");
const sendButton = document.getElementById("send-btn");
const chatThread = document.getElementById("chat-thread");
const modelIndicator = document.getElementById("model-indicator");
const statusNode = document.getElementById("status");

const state = {
  providerLabel: "",
  modelLabel: "",
};

function setStatus(message, isError = false) {
  statusNode.textContent = message;
  statusNode.className = isError ? "error" : "ok";
}

function addMessage(role, text = "") {
  const wrapper = document.createElement("div");
  wrapper.className = `chat-message ${role}`;

  const title = document.createElement("p");
  title.className = "chat-role";
  title.textContent = role === "user" ? "You" : "Krill";

  const bubble = document.createElement("div");
  bubble.className = "chat-bubble";
  bubble.textContent = text;

  wrapper.appendChild(title);
  wrapper.appendChild(bubble);
  chatThread.appendChild(wrapper);
  chatThread.scrollTop = chatThread.scrollHeight;

  return bubble;
}

function updateModelIndicator() {
  if (!state.providerLabel || !state.modelLabel) {
    modelIndicator.textContent = "No active provider/model configured.";
    return;
  }

  modelIndicator.textContent = `Chatting with ${state.providerLabel} - ${state.modelLabel}`;
}

async function loadGatewayMeta() {
  try {
    const [providersResponse, settingsResponse] = await Promise.all([
      fetch("/api/providers"),
      fetch("/api/settings"),
    ]);

    if (!providersResponse.ok || !settingsResponse.ok) {
      throw new Error("Failed to load gateway metadata.");
    }

    const providers = await providersResponse.json();
    const settings = await settingsResponse.json();

    const activeProvider = providers.find((provider) => provider.id === settings.active_provider_id);
    const activeConfig = settings.provider_configs?.[settings.active_provider_id];

    state.providerLabel = activeProvider?.label ?? settings.active_provider_id ?? "";
    state.modelLabel = activeProvider?.models?.find((model) => model.id === activeConfig?.model)?.label ?? activeConfig?.model ?? "";

    updateModelIndicator();
    setStatus("Gateway ready.");
  } catch (error) {
    updateModelIndicator();
    setStatus(error.message, true);
  }
}

function setSendingState(isSending) {
  sendButton.disabled = isSending;
  chatInput.disabled = isSending;
}

function processSseBlock(block, assistantBubble) {
  const lines = block.split("\n");
  let eventName = "message";
  let data = "";

  lines.forEach((line) => {
    if (line.startsWith("event:")) {
      eventName = line.slice(6).trim();
      return;
    }

    if (line.startsWith("data:")) {
      data += line.slice(5).trim();
    }
  });

  if (!data) {
    return { done: false, hasError: false };
  }

  let payload = {};
  try {
    payload = JSON.parse(data);
  } catch (error) {
    return { done: false, hasError: true, errorMessage: "Invalid stream payload." };
  }

  if (eventName === "token") {
    assistantBubble.textContent += payload.text ?? "";
    chatThread.scrollTop = chatThread.scrollHeight;
    return { done: false, hasError: false };
  }

  if (eventName === "done") {
    return { done: true, hasError: false };
  }

  if (eventName === "error") {
    return {
      done: true,
      hasError: true,
      errorMessage: payload.detail ?? "Chat failed.",
    };
  }

  return { done: false, hasError: false };
}

async function sendMessage(event) {
  event.preventDefault();

  const message = chatInput.value.trim();
  if (!message) {
    setStatus("Please enter a message.", true);
    return;
  }

  setSendingState(true);
  setStatus("Sending...");

  addMessage("user", message);
  const assistantBubble = addMessage("assistant", "");
  chatInput.value = "";

  try {
    const response = await fetch("/api/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
    });

    if (!response.ok || !response.body) {
      let detail = "Chat request failed.";
      try {
        const errorBody = await response.json();
        if (typeof errorBody.detail === "string") {
          detail = errorBody.detail;
        }
      } catch (error) {
        detail = "Chat request failed.";
      }

      throw new Error(detail);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        break;
      }

      buffer += decoder.decode(value, { stream: true });
      const blocks = buffer.split("\n\n");
      buffer = blocks.pop() ?? "";

      for (const block of blocks) {
        const result = processSseBlock(block, assistantBubble);
        if (result.hasError) {
          throw new Error(result.errorMessage);
        }

        if (result.done) {
          setStatus("Response complete.");
          setSendingState(false);
          return;
        }
      }
    }

    setStatus("Response complete.");
  } catch (error) {
    if (!assistantBubble.textContent) {
      assistantBubble.textContent = "Sorry, something went wrong.";
    }

    setStatus(error.message, true);
  } finally {
    setSendingState(false);
    chatInput.focus();
  }
}

chatForm.addEventListener("submit", sendMessage);
window.addEventListener("load", loadGatewayMeta);
