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

  if (role === "assistant") {
    bubble.innerHTML = renderMarkdown(text);
  } else {
    bubble.textContent = text;
  }

  wrapper.appendChild(title);
  wrapper.appendChild(bubble);
  chatThread.appendChild(wrapper);
  chatThread.scrollTop = chatThread.scrollHeight;

  return bubble;
}

function escapeHtml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function renderInlineMarkdown(text) {
  let output = text;
  output = output.replace(/~~([^~]+)~~/g, "<del>$1</del>");
  output = output.replace(/\*\*\*([^*]+)\*\*\*/g, "<strong><em>$1</em></strong>");
  output = output.replace(/`([^`]+)`/g, "<code>$1</code>");
  output = output.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  output = output.replace(/\*([^*]+)\*/g, "<em>$1</em>");
  output = output.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
  return output;
}

function isTableSeparatorRow(line) {
  const normalized = line.trim().replace(/^\|/, "").replace(/\|$/, "");
  if (!normalized) {
    return false;
  }

  const parts = normalized.split("|").map((part) => part.trim());
  if (parts.length === 0) {
    return false;
  }

  return parts.every((part) => /^:?-{3,}:?$/.test(part));
}

function parseTableCells(line) {
  const normalized = line.trim().replace(/^\|/, "").replace(/\|$/, "");
  return normalized.split("|").map((cell) => renderInlineMarkdown(cell.trim()));
}

function renderMarkdown(rawText) {
  const escaped = escapeHtml(rawText || "");
  const lines = escaped.split("\n");
  const html = [];
  let inCodeBlock = false;
  let inUlList = false;
  let inOlList = false;

  function closeOpenLists() {
    if (inUlList) {
      html.push("</ul>");
      inUlList = false;
    }

    if (inOlList) {
      html.push("</ol>");
      inOlList = false;
    }
  }

  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i];
    const trimmed = line.trim();

    if (trimmed.startsWith("```")) {
      if (!inCodeBlock) {
        closeOpenLists();
        html.push("<pre><code>");
        inCodeBlock = true;
      } else {
        html.push("</code></pre>");
        inCodeBlock = false;
      }
      continue;
    }

    if (inCodeBlock) {
      html.push(`${line}\n`);
      continue;
    }

    if (trimmed.includes("|") && i + 1 < lines.length && isTableSeparatorRow(lines[i + 1])) {
      closeOpenLists();

      const headerCells = parseTableCells(trimmed);
      html.push("<table><thead><tr>");
      headerCells.forEach((cell) => {
        html.push(`<th>${cell}</th>`);
      });
      html.push("</tr></thead><tbody>");

      i += 2;
      while (i < lines.length) {
        const rowLine = lines[i];
        if (!rowLine.trim() || !rowLine.includes("|")) {
          i -= 1;
          break;
        }

        const rowCells = parseTableCells(rowLine);
        html.push("<tr>");
        rowCells.forEach((cell) => {
          html.push(`<td>${cell}</td>`);
        });
        html.push("</tr>");
        i += 1;
      }

      html.push("</tbody></table>");
      continue;
    }

    if (trimmed.startsWith("- ")) {
      if (!inUlList) {
        if (inOlList) {
          html.push("</ol>");
          inOlList = false;
        }
        html.push("<ul>");
        inUlList = true;
      }
      html.push(`<li>${renderInlineMarkdown(trimmed.slice(2))}</li>`);
      continue;
    }

    const orderedMatch = trimmed.match(/^\d+\.\s+(.*)$/);
    if (orderedMatch) {
      if (!inOlList) {
        if (inUlList) {
          html.push("</ul>");
          inUlList = false;
        }
        html.push("<ol>");
        inOlList = true;
      }
      html.push(`<li>${renderInlineMarkdown(orderedMatch[1])}</li>`);
      continue;
    }

    closeOpenLists();

    if (/^---+$/.test(trimmed) || /^\*\*\*+$/.test(trimmed)) {
      html.push("<hr>");
      continue;
    }

    if (trimmed.startsWith("> ")) {
      html.push(`<blockquote>${renderInlineMarkdown(trimmed.slice(2))}</blockquote>`);
      continue;
    }

    if (trimmed.length === 0) {
      html.push("<br>");
      continue;
    }

    const headingMatch = trimmed.match(/^(#{1,6})\s+(.*)$/);
    if (headingMatch) {
      const level = headingMatch[1].length;
      html.push(`<h${level}>${renderInlineMarkdown(headingMatch[2])}</h${level}>`);
      continue;
    }

    html.push(`<p>${renderInlineMarkdown(trimmed)}</p>`);
  }

  closeOpenLists();

  if (inCodeBlock) {
    html.push("</code></pre>");
  }

  return html.join("");
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
    const currentText = assistantBubble.dataset.rawText ?? "";
    const nextText = `${currentText}${payload.text ?? ""}`;
    assistantBubble.dataset.rawText = nextText;
    assistantBubble.innerHTML = renderMarkdown(nextText);
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
  assistantBubble.dataset.rawText = "";
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
    if (!assistantBubble.dataset.rawText) {
      assistantBubble.dataset.rawText = "Sorry, something went wrong.";
      assistantBubble.innerHTML = renderMarkdown(assistantBubble.dataset.rawText);
    }

    setStatus(error.message, true);
  } finally {
    setSendingState(false);
    chatInput.focus();
  }
}

chatInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    if (!sendButton.disabled) {
      chatForm.requestSubmit();
    }
  }
});

chatForm.addEventListener("submit", sendMessage);
window.addEventListener("load", loadGatewayMeta);
