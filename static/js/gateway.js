const chatForm = document.getElementById("chat-form");
const chatInput = document.getElementById("chat-input");
const sendButton = document.getElementById("send-btn");
const chatThread = document.getElementById("chat-thread");
const providerIndicator = document.getElementById("provider-indicator");
const modelIndicator = document.getElementById("model-indicator");
const tokenCounterNode = document.getElementById("token-counter");
const statusNode = document.getElementById("status");
const menuButton = document.getElementById("menu-btn");
const menuPopover = document.getElementById("menu-popover");
const assistantTitleNode = document.getElementById("assistant-title");
const assistantMetaNode = document.getElementById("assistant-meta");
const headerProviderSelect = document.getElementById("header-provider-select");
const headerModelSelect = document.getElementById("header-model-select");
const toastNode = document.getElementById("toast");

const state = {
  providers: [],
  activeProviderId: "",
  activeModelId: "",
  providerLabel: "",
  modelLabel: "",
  botName: "",
  modelTokenLimit: 0,
  usedTokens: 0,
  lastRequestTokens: 0,
  memoryBlock: "",
  settings: null,
  history: [],
  isCompacting: false,
  isSwitching: false,
  suppressSwitcherEvents: false,
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
  }, 1800);
}

function formatMessageTimestamp(date = new Date()) {
  const hour = String(date.getHours()).padStart(2, "0");
  const minute = String(date.getMinutes()).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  const year = date.getFullYear();
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const month = months[date.getMonth()];
  return `${hour}:${minute} ${day}. ${month}. ${year}`;
}

function addMessage(role, text = "") {
  const wrapper = document.createElement("div");
  wrapper.className = `chat-message ${role}`;

  const title = document.createElement("p");
  title.className = "chat-role";
  const roleLabel = role === "user" ? "You" : state.botName || "Krill";
  title.textContent = `${roleLabel} - ${formatMessageTimestamp()}`;

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

function setAssistantLoading(bubble, isLoading) {
  if (isLoading) {
    bubble.classList.add("is-loading");
    bubble.innerHTML = '<span class="typing-dots" aria-label="Krill is thinking"><span></span><span></span><span></span></span>';
    return;
  }

  bubble.classList.remove("is-loading");
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

function updateMetaIndicators() {
  providerIndicator.textContent = state.providerLabel || "Not configured";
  modelIndicator.textContent = state.modelLabel || "Not configured";
}

function updateAssistantHeader(settings) {
  const botName = settings?.bot_name?.trim();
  const configuredProviders = Object.keys(settings?.provider_configs ?? {}).length;
  const providerText = configuredProviders === 1 ? "1 provider" : `${configuredProviders} providers`;
  const activeProviderText = state.providerLabel || "No provider selected";
  const modelText = state.modelLabel || "No model selected";

  assistantTitleNode.textContent = botName
    ? `This is ${botName} - your personal assistant`
    : "This is your personal assistant";
  assistantMetaNode.textContent = `${providerText} connected - Active provider: ${activeProviderText} - Active model: ${modelText}`;
}

function formatNumber(value) {
  return Number(value || 0).toLocaleString("de-DE");
}

function updateTokenCounter(usedTokens = state.usedTokens, tokenLimit = state.modelTokenLimit) {
  const safeUsed = Math.max(0, Number(usedTokens || 0));
  const safeLimit = Math.max(0, Number(tokenLimit || 0));

  state.usedTokens = safeUsed;
  state.modelTokenLimit = safeLimit;

  const percent = safeLimit > 0 ? ((safeUsed / safeLimit) * 100).toFixed(2) : "0.00";
  tokenCounterNode.textContent = `${formatNumber(safeUsed)} / ${formatNumber(safeLimit)} tokens (${percent}% used)`;
}

function getProviderById(providerId) {
  return state.providers.find((provider) => provider.id === providerId);
}

function getConfiguredProviderIds() {
  return Object.keys(state.settings?.provider_configs ?? {});
}

function getModelTokenLimit(providerId, modelId) {
  const configuredLimit = state.settings?.provider_configs?.[providerId]?.token_limit;
  if (Number.isFinite(Number(configuredLimit))) {
    return Math.max(0, Number(configuredLimit));
  }

  const provider = getProviderById(providerId);
  const model = provider?.models?.find((entry) => entry.id === modelId);
  if (model?.token_limit) {
    return Number(model.token_limit);
  }

  return 0;
}

function estimateContextTokens(history, memoryBlock = "") {
  const memoryTokens = Math.ceil((memoryBlock || "").length / 4);
  const historyTokens = history.reduce((total, item) => {
    const role = typeof item?.role === "string" ? item.role : "";
    const content = typeof item?.content === "string" ? item.content : "";
    return total + Math.ceil((role.length + content.length) / 4);
  }, 0);
  return Math.max(0, memoryTokens + historyTokens);
}

function syncUsedTokensToContext() {
  const estimatedContext = estimateContextTokens(state.history, state.memoryBlock);
  const contextTokens = Math.max(estimatedContext, Number(state.lastRequestTokens || 0));
  state.usedTokens = Math.max(0, contextTokens);
  updateTokenCounter(state.usedTokens, state.modelTokenLimit);
}

function renderCompactedChatView() {
  chatThread.innerHTML = "";

  if (state.memoryBlock.trim()) {
    addMessage("assistant", `**Auto-compacted memory**\n\n${state.memoryBlock.trim()}`);
  }

  state.history.forEach((turn) => {
    if (turn?.role === "user" || turn?.role === "assistant") {
      addMessage(turn.role, String(turn.content ?? ""));
    }
  });
}

function shouldCompactForLimit(tokenLimit) {
  const safeLimit = Math.max(0, Number(tokenLimit || 0));
  if (safeLimit <= 0) {
    return false;
  }

  const observedContext = Math.max(0, Number(state.lastRequestTokens || 0));
  const estimatedContext = estimateContextTokens(state.history, state.memoryBlock);
  const contextTokens = Math.max(observedContext, estimatedContext);
  return contextTokens >= safeLimit * 0.75;
}

function setSwitchersDisabled(disabled) {
  headerProviderSelect.disabled = disabled;
  headerModelSelect.disabled = disabled;
}

function renderProviderSwitcher(selectedProviderId = state.activeProviderId) {
  const configuredProviderIds = getConfiguredProviderIds();
  state.suppressSwitcherEvents = true;
  headerProviderSelect.innerHTML = "";

  configuredProviderIds.forEach((providerId) => {
    const provider = getProviderById(providerId);
    const option = document.createElement("option");
    option.value = providerId;
    option.textContent = provider?.label ?? providerId;
    headerProviderSelect.appendChild(option);
  });

  if (configuredProviderIds.length === 0) {
    headerProviderSelect.value = "";
    headerProviderSelect.disabled = true;
    state.suppressSwitcherEvents = false;
    return "";
  }

  const normalizedProvider = configuredProviderIds.includes(selectedProviderId)
    ? selectedProviderId
    : configuredProviderIds[0];
  headerProviderSelect.disabled = false;
  headerProviderSelect.value = normalizedProvider;
  state.suppressSwitcherEvents = false;
  return normalizedProvider;
}

function renderModelSwitcher(providerId, selectedModelId = "") {
  const provider = getProviderById(providerId);
  const configModel = state.settings?.provider_configs?.[providerId]?.model ?? "";
  const modelCandidates = provider?.models ?? [];
  const normalizedSelected = selectedModelId || configModel || modelCandidates[0]?.id || "";

  state.suppressSwitcherEvents = true;
  headerModelSelect.innerHTML = "";

  modelCandidates.forEach((model) => {
    const option = document.createElement("option");
    option.value = model.id;
    option.textContent = model.label;
    headerModelSelect.appendChild(option);
  });

  if (normalizedSelected && !modelCandidates.some((model) => model.id === normalizedSelected)) {
    const customOption = document.createElement("option");
    customOption.value = normalizedSelected;
    customOption.textContent = normalizedSelected;
    headerModelSelect.appendChild(customOption);
  }

  headerModelSelect.disabled = !providerId;
  if (normalizedSelected) {
    headerModelSelect.value = normalizedSelected;
  }
  state.suppressSwitcherEvents = false;

  return headerModelSelect.value || normalizedSelected;
}

function syncSwitcherControls() {
  const providerId = renderProviderSwitcher(state.activeProviderId);
  renderModelSwitcher(providerId, state.activeModelId);
}

async function verifyProviderModel(providerId, modelId, apiKey) {
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

  let detail = "Provider verification failed.";
  try {
    const payload = await response.json();
    if (typeof payload.detail === "string" && payload.detail) {
      detail = payload.detail;
    }
  } catch (error) {
    detail = "Provider verification failed.";
  }

  throw new Error(detail);
}

async function persistSettings(nextSettings) {
  const response = await fetch("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(nextSettings),
  });

  if (!response.ok) {
    let detail = "Failed to save active provider/model.";
    try {
      const payload = await response.json();
      if (typeof payload.detail === "string" && payload.detail) {
        detail = payload.detail;
      }
    } catch (error) {
      detail = "Failed to save active provider/model.";
    }
    throw new Error(detail);
  }

  return response.json();
}

async function compactHistoryForLimit(targetTokenLimit, reasonLabel) {
  if (state.isCompacting) {
    return;
  }

  state.isCompacting = true;
  setSwitchersDisabled(true);

  try {
    setStatus(`Compacting memory for ${reasonLabel}...`);
    const response = await fetch("/api/chat/compact", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        history: state.history,
        target_token_limit: Math.max(0, Number(targetTokenLimit || 0)),
        memory_block: state.memoryBlock,
      }),
    });

    if (!response.ok) {
      let detail = "Compaction failed.";
      try {
        const payload = await response.json();
        if (typeof payload.detail === "string" && payload.detail) {
          detail = payload.detail;
        }
      } catch (error) {
        detail = "Compaction failed.";
      }
      throw new Error(detail);
    }

    const payload = await response.json();
    state.memoryBlock = typeof payload.memory_block === "string" ? payload.memory_block : state.memoryBlock;
    state.history = Array.isArray(payload.history) ? payload.history : state.history;
    state.lastRequestTokens = estimateContextTokens(state.history, state.memoryBlock);
    renderCompactedChatView();
    syncUsedTokensToContext();
  } finally {
    state.isCompacting = false;
    setSwitchersDisabled(state.isSwitching);
  }
}

async function maybeAutoCompact(reasonLabel, targetTokenLimit = state.modelTokenLimit) {
  if (!shouldCompactForLimit(targetTokenLimit)) {
    return { ok: true, compacted: false };
  }

  try {
    await compactHistoryForLimit(targetTokenLimit, reasonLabel);
    showToast("Memory compacted and context updated.");
    return { ok: true, compacted: true };
  } catch (error) {
    setStatus(error.message, true);
    return { ok: false, compacted: false };
  }
}

async function switchActiveProviderModel(nextProviderId, nextModelId) {
  if (state.isSwitching || !state.settings) {
    return;
  }

  if (!nextProviderId || !nextModelId) {
    setStatus("Please choose a provider and model.", true);
    return;
  }

  const previousProviderId = state.activeProviderId;
  const previousModelId = state.activeModelId;

  state.isSwitching = true;
  setSwitchersDisabled(true);

  try {
    const targetLimit = getModelTokenLimit(nextProviderId, nextModelId);
    const currentContextTokens = Math.max(
      Number(state.usedTokens || 0),
      estimateContextTokens(state.history, state.memoryBlock),
    );
    if (targetLimit > 0 && currentContextTokens > targetLimit) {
      const compactResult = await maybeAutoCompact("provider/model switch", targetLimit);
      if (!compactResult.ok) {
        throw new Error("Model switch could not be performed because compaction failed.");
      }
    }

    const nextSettings = JSON.parse(JSON.stringify(state.settings));
    const nextProviderConfig = nextSettings.provider_configs?.[nextProviderId];
    if (!nextProviderConfig) {
      throw new Error("Selected provider is not configured.");
    }

    await verifyProviderModel(nextProviderId, nextModelId, nextProviderConfig.api_key || "");

    nextProviderConfig.model = nextModelId;
    nextSettings.active_provider_id = nextProviderId;
    const persisted = await persistSettings(nextSettings);

    state.settings = persisted;
    state.activeProviderId = nextProviderId;
    state.activeModelId = nextModelId;
    state.modelTokenLimit = getModelTokenLimit(nextProviderId, nextModelId);
    state.providerLabel = getProviderById(nextProviderId)?.label ?? nextProviderId;
    state.modelLabel = getProviderById(nextProviderId)?.models?.find((model) => model.id === nextModelId)?.label ?? nextModelId;

    syncSwitcherControls();
    updateMetaIndicators();
    updateAssistantHeader(state.settings);
    updateTokenCounter(state.usedTokens, state.modelTokenLimit);
    setStatus("Active provider/model updated.");
  } catch (error) {
    state.activeProviderId = previousProviderId;
    state.activeModelId = previousModelId;
    syncSwitcherControls();
    updateMetaIndicators();
    setStatus(error.message, true);
  } finally {
    state.isSwitching = false;
    setSwitchersDisabled(false);
  }
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

    state.providers = providers;
    state.settings = settings;
    state.activeProviderId = settings.active_provider_id ?? "";
    state.activeModelId = activeConfig?.model ?? "";
    state.botName = typeof settings?.bot_name === "string" ? settings.bot_name.trim() : "";

    state.providerLabel = activeProvider?.label ?? settings.active_provider_id ?? "";
    state.modelLabel = activeProvider?.models?.find((model) => model.id === activeConfig?.model)?.label ?? activeConfig?.model ?? "";
    state.modelTokenLimit = getModelTokenLimit(state.activeProviderId, state.activeModelId);

    syncSwitcherControls();
    updateMetaIndicators();
    updateAssistantHeader(settings);
    updateTokenCounter(0, state.modelTokenLimit);
    setStatus("Gateway ready.");
  } catch (error) {
    updateMetaIndicators();
    assistantTitleNode.textContent = "This is your personal assistant";
    assistantMetaNode.textContent = "Assistant metadata unavailable.";
    syncSwitcherControls();
    updateTokenCounter(0, 0);
    setStatus(error.message, true);
  }
}

function toggleMenu(forceOpen) {
  const shouldOpen = typeof forceOpen === "boolean" ? forceOpen : menuPopover.classList.contains("hidden");
  menuPopover.classList.toggle("hidden", !shouldOpen);
  menuButton.setAttribute("aria-expanded", shouldOpen ? "true" : "false");
}

function setSendingState(isSending) {
  sendButton.disabled = isSending;
  chatInput.disabled = isSending;
  setSwitchersDisabled(isSending || state.isSwitching || state.isCompacting);
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
    if (assistantBubble.classList.contains("is-loading")) {
      setAssistantLoading(assistantBubble, false);
    }

    const currentText = assistantBubble.dataset.rawText ?? "";
    const nextText = `${currentText}${payload.text ?? ""}`;
    assistantBubble.dataset.rawText = nextText;
    assistantBubble.innerHTML = renderMarkdown(nextText);
    chatThread.scrollTop = chatThread.scrollHeight;
    return { done: false, hasError: false };
  }

  if (eventName === "meta") {
    const requestUsedTokens = Number(payload.used_tokens ?? 0);
    if (Number.isFinite(requestUsedTokens) && requestUsedTokens > 0) {
      state.lastRequestTokens = requestUsedTokens;
      syncUsedTokensToContext();
    }

    if (payload.token_limit) {
      updateTokenCounter(state.usedTokens, payload.token_limit ?? state.modelTokenLimit);
    }
    return { done: false, hasError: false };
  }

  if (eventName === "done") {
    setAssistantLoading(assistantBubble, false);
    return { done: true, hasError: false };
  }

  if (eventName === "error") {
    setAssistantLoading(assistantBubble, false);
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
  setAssistantLoading(assistantBubble, true);
  chatInput.value = "";

  try {
    const response = await fetch("/api/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, history: state.history, memory_block: state.memoryBlock }),
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
          await finalizeSuccessfulResponse(message, assistantBubble);
          setSendingState(false);
          return;
        }
      }
    }

    await finalizeSuccessfulResponse(message, assistantBubble);
  } catch (error) {
    setAssistantLoading(assistantBubble, false);

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

async function finalizeSuccessfulResponse(message, assistantBubble) {
  state.history.push({ role: "user", content: message });
  state.history.push({ role: "assistant", content: assistantBubble.dataset.rawText ?? "" });
  const compactResult = await maybeAutoCompact("ongoing chat", state.modelTokenLimit);
  if (!compactResult.ok) {
    return;
  }

  syncUsedTokensToContext();
  if (compactResult.compacted) {
    setStatus("Response complete. Memory compacted.");
    return;
  }

  setStatus("Response complete.");
}

chatInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    if (!sendButton.disabled) {
      chatForm.requestSubmit();
    }
  }
});

menuButton.addEventListener("click", () => {
  toggleMenu();
});

document.addEventListener("click", (event) => {
  const target = event.target;
  if (!(target instanceof Node)) {
    return;
  }

  if (menuPopover.contains(target) || menuButton.contains(target)) {
    return;
  }

  toggleMenu(false);
});

menuPopover.addEventListener("click", () => {
  toggleMenu(false);
});

headerProviderSelect.addEventListener("change", async () => {
  if (state.suppressSwitcherEvents) {
    return;
  }

  const nextProviderId = headerProviderSelect.value;
  const configuredModel = state.settings?.provider_configs?.[nextProviderId]?.model ?? "";
  const nextModelId = renderModelSwitcher(nextProviderId, configuredModel);
  await switchActiveProviderModel(nextProviderId, nextModelId);
});

headerModelSelect.addEventListener("change", async () => {
  if (state.suppressSwitcherEvents) {
    return;
  }

  const nextProviderId = headerProviderSelect.value;
  const nextModelId = headerModelSelect.value;
  await switchActiveProviderModel(nextProviderId, nextModelId);
});

chatForm.addEventListener("submit", sendMessage);
window.addEventListener("load", loadGatewayMeta);
