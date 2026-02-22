const CHAT_TITLE_MAX_LENGTH = 48;
const EDITABLE_CHAT_TITLE_MAX_LENGTH = 32;

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
const compactButton = document.getElementById("compact-btn");
const currentChatTitleNode = document.getElementById("current-chat-title");
const chatHistoryList = document.getElementById("chat-history-list");
const newChatButton = document.getElementById("new-chat-btn");
let toastNode = document.getElementById("toast");

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
  settings: null,
  chats: [],
  activeChatId: "",
  isCompacting: false,
  isSwitching: false,
  isSending: false,
  suppressSwitcherEvents: false,
  toastTimerId: null,
  compactionBubble: null,
};

function setStatus(message, isError = false) {
  statusNode.textContent = message;
  statusNode.className = isError ? "error" : "ok";
}

function showToast(message) {
  if (!(toastNode instanceof HTMLElement)) {
    const fallbackToast = document.createElement("div");
    fallbackToast.id = "toast";
    fallbackToast.className = "toast hidden";
    fallbackToast.setAttribute("role", "status");
    fallbackToast.setAttribute("aria-live", "polite");
    document.body.appendChild(fallbackToast);
    toastNode = fallbackToast;
  }

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

function formatMessageTimestamp(rawValue = "") {
  const parsed = rawValue ? new Date(rawValue) : new Date();
  const date = Number.isNaN(parsed.getTime()) ? new Date() : parsed;
  const hour = String(date.getHours()).padStart(2, "0");
  const minute = String(date.getMinutes()).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  const year = date.getFullYear();
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const month = months[date.getMonth()];
  return `${hour}:${minute} ${day}. ${month}. ${year}`;
}

function createTimestamp() {
  return new Date().toISOString();
}

function normalizeChatTitle(rawTitle) {
  if (typeof rawTitle !== "string") {
    return "New chat";
  }

  const trimmed = rawTitle.trim();
  return trimmed || "New chat";
}

function deriveChatTitle(firstMessage) {
  const normalized = String(firstMessage || "").trim().replace(/\s+/g, " ");
  if (!normalized) {
    return "New chat";
  }

  if (normalized.length <= CHAT_TITLE_MAX_LENGTH) {
    return normalized;
  }

  return `${normalized.slice(0, CHAT_TITLE_MAX_LENGTH).trimEnd()}...`;
}

function normalizeEditedChatTitle(rawTitle) {
  const normalized = String(rawTitle || "").trim().replace(/\s+/g, " ");
  if (!normalized) {
    return "New chat";
  }

  if (normalized.length <= EDITABLE_CHAT_TITLE_MAX_LENGTH) {
    return normalized;
  }

  return normalized.slice(0, EDITABLE_CHAT_TITLE_MAX_LENGTH).trimEnd();
}

function createChatId() {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }

  return `chat-${Date.now()}-${Math.random().toString(16).slice(2, 10)}`;
}

function getLatestChatMessage(chat) {
  if (!chat || !Array.isArray(chat.messages) || chat.messages.length === 0) {
    return null;
  }

  return chat.messages[chat.messages.length - 1] ?? null;
}

function getLatestChatTimestamp(chat) {
  const latest = getLatestChatMessage(chat);
  if (latest && typeof latest.timestamp === "string" && latest.timestamp) {
    return latest.timestamp;
  }

  return "";
}

function sortChatsByLatestMessage(chats) {
  return [...chats].sort((left, right) => {
    const leftDate = new Date(getLatestChatTimestamp(left) || 0).getTime();
    const rightDate = new Date(getLatestChatTimestamp(right) || 0).getTime();
    if (rightDate !== leftDate) {
      return rightDate - leftDate;
    }
    return (left.title || "").localeCompare(right.title || "");
  });
}

function getActiveChat() {
  return state.chats.find((chat) => chat.id === state.activeChatId) ?? null;
}

function updateCurrentChatTitle() {
  if (!(currentChatTitleNode instanceof HTMLElement)) {
    return;
  }

  const activeChat = getActiveChat();
  currentChatTitleNode.textContent = activeChat ? normalizeChatTitle(activeChat.title) : "New chat";
}

function createChatEntry(firstMessage) {
  const timestamp = createTimestamp();
  return {
    id: createChatId(),
    title: deriveChatTitle(firstMessage),
    type: "normal",
    messages: [],
    memory_block: "",
    created_at: timestamp,
    updated_at: timestamp,
  };
}

function toApiHistory(messages) {
  return messages.map((turn) => ({ role: turn.role, content: turn.content }));
}

function setHistoryControlsDisabled(disabled) {
  if (newChatButton instanceof HTMLButtonElement) {
    newChatButton.disabled = disabled;
  }

  const buttons = chatHistoryList.querySelectorAll("button[data-chat-id]");
  buttons.forEach((button) => {
    button.disabled = disabled;
  });
}

function addMessage(role, text = "", timestamp = "") {
  const wrapper = document.createElement("div");
  wrapper.className = `chat-message ${role}`;

  const title = document.createElement("p");
  title.className = "chat-role";
  const roleLabel = role === "user" ? "You" : state.botName || "Krill";
  title.textContent = `${roleLabel} - ${formatMessageTimestamp(timestamp)}`;

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

function renderEmptyChatView() {
  chatThread.innerHTML = "";
  const emptyNode = document.createElement("p");
  emptyNode.className = "chat-history-empty";
  emptyNode.textContent = "Start a new chat with your first message.";
  chatThread.appendChild(emptyNode);
}

function renderActiveChat() {
  updateCurrentChatTitle();
  const activeChat = getActiveChat();
  if (!activeChat) {
    renderEmptyChatView();
    return;
  }

  chatThread.innerHTML = "";
  activeChat.messages.forEach((turn) => {
    if (turn?.role === "user" || turn?.role === "assistant") {
      addMessage(turn.role, String(turn.content ?? ""), String(turn.timestamp ?? ""));
    }
  });

  if (typeof activeChat.memory_block === "string" && activeChat.memory_block.trim()) {
    addMessage("assistant", `**Auto-compacted memory**\n\n${activeChat.memory_block.trim()}`);
  }
}

function renderChatHistory() {
  chatHistoryList.innerHTML = "";
  const sortedChats = sortChatsByLatestMessage(state.chats);

  if (sortedChats.length === 0) {
    const emptyNode = document.createElement("p");
    emptyNode.className = "chat-history-empty";
    emptyNode.textContent = "No chats yet.";
    chatHistoryList.appendChild(emptyNode);
    return;
  }

  sortedChats.forEach((chat) => {
    const item = document.createElement("div");
    item.className = "chat-history-item";
    if (chat.id === state.activeChatId) {
      item.classList.add("active");
    }
    item.dataset.chatId = chat.id;

    const selectButton = document.createElement("button");
    selectButton.type = "button";
    selectButton.className = "chat-history-main";
    selectButton.dataset.chatId = chat.id;
    selectButton.dataset.action = "open";
    selectButton.disabled = state.isSending || state.isSwitching || state.isCompacting;

    const titleNode = document.createElement("p");
    titleNode.className = "chat-history-title";
    titleNode.textContent = normalizeChatTitle(chat.title);

    const timeNode = document.createElement("p");
    timeNode.className = "chat-history-time";
    const latestTimestamp = getLatestChatTimestamp(chat);
    timeNode.textContent = latestTimestamp ? formatMessageTimestamp(latestTimestamp) : "No messages yet";

    selectButton.appendChild(titleNode);
    selectButton.appendChild(timeNode);

    const actionsNode = document.createElement("div");
    actionsNode.className = "chat-history-actions";

    const editButton = document.createElement("button");
    editButton.type = "button";
    editButton.className = "chat-history-action-btn";
    editButton.dataset.chatId = chat.id;
    editButton.dataset.action = "edit";
    editButton.disabled = state.isSending || state.isSwitching || state.isCompacting;
    editButton.setAttribute("aria-label", "Edit chat title");
    editButton.textContent = "✎";

    const deleteButton = document.createElement("button");
    deleteButton.type = "button";
    deleteButton.className = "chat-history-action-btn danger";
    deleteButton.dataset.chatId = chat.id;
    deleteButton.dataset.action = "delete";
    deleteButton.disabled = state.isSending || state.isSwitching || state.isCompacting;
    deleteButton.setAttribute("aria-label", "Delete chat");
    deleteButton.textContent = "×";

    actionsNode.appendChild(deleteButton);
    actionsNode.appendChild(editButton);

    item.appendChild(selectButton);
    item.appendChild(actionsNode);
    chatHistoryList.appendChild(item);
  });
}

async function deleteChat(chatId) {
  const index = state.chats.findIndex((chat) => chat.id === chatId);
  if (index === -1) {
    return;
  }

  state.chats.splice(index, 1);

  if (state.activeChatId === chatId) {
    const nextActiveChat = sortChatsByLatestMessage(state.chats)[0] ?? null;
    state.activeChatId = nextActiveChat?.id ?? "";
    state.lastRequestTokens = 0;
  }

  renderChatHistory();
  renderActiveChat();
  syncUsedTokensToContext();

  try {
    await persistChatsToSettings();
    setStatus("Chat deleted.");
  } catch (error) {
    setStatus(`Chat deleted locally, but save failed: ${error.message}`, true);
  }
}

async function editChatTitle(chatId) {
  const chat = state.chats.find((entry) => entry.id === chatId);
  if (!chat) {
    return;
  }

  const nextTitleRaw = window.prompt(
    `Edit chat title (max ${EDITABLE_CHAT_TITLE_MAX_LENGTH} characters):`,
    normalizeChatTitle(chat.title),
  );

  if (nextTitleRaw === null) {
    return;
  }

  chat.title = normalizeEditedChatTitle(nextTitleRaw);
  chat.updated_at = createTimestamp();
  renderChatHistory();
  updateCurrentChatTitle();

  try {
    await persistChatsToSettings();
    setStatus("Chat title updated.");
  } catch (error) {
    setStatus(`Title updated locally, but save failed: ${error.message}`, true);
  }
}

function activateChat(chatId) {
  state.activeChatId = chatId;
  state.lastRequestTokens = 0;
  renderChatHistory();
  renderActiveChat();
  syncUsedTokensToContext();
}

function startNewChat() {
  if (state.isSending || state.isSwitching || state.isCompacting) {
    return;
  }

  state.activeChatId = "";
  state.lastRequestTokens = 0;
  renderChatHistory();
  renderActiveChat();
  updateTokenCounter(0, state.modelTokenLimit);
  setStatus("New chat ready. Send a first message to create it.");
  chatInput.focus();
}

function setAssistantLoading(bubble, isLoading) {
  if (isLoading) {
    bubble.classList.add("is-loading");
    bubble.innerHTML = '<span class="typing-dots" aria-label="Krill is thinking"><span></span><span></span><span></span></span>';
    return;
  }

  bubble.classList.remove("is-loading");
}

function showCompactionProgressBubble() {
  if (state.compactionBubble instanceof HTMLElement) {
    return;
  }

  const bubble = addMessage("assistant", "");
  bubble.classList.add("is-loading");
  bubble.innerHTML =
    '<span class="compaction-loading">Chat compaction ongoing <span class="typing-dots" aria-label="Chat compaction ongoing"><span></span><span></span><span></span></span></span>';
  state.compactionBubble = bubble;
}

function clearCompactionProgressBubble() {
  if (!(state.compactionBubble instanceof HTMLElement)) {
    return;
  }

  const wrapper = state.compactionBubble.parentElement;
  if (wrapper instanceof HTMLElement) {
    wrapper.remove();
  }

  state.compactionBubble = null;
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
  const provider = getProviderById(providerId);
  const model = provider?.models?.find((entry) => entry.id === modelId);
  if (model?.token_limit) {
    return Number(model.token_limit);
  }

  return 0;
}

function estimateContextTokens(messages, memoryBlock = "") {
  const memoryTokens = Math.ceil((memoryBlock || "").length / 4);
  const historyTokens = messages.reduce((total, item) => {
    const role = typeof item?.role === "string" ? item.role : "";
    const content = typeof item?.content === "string" ? item.content : "";
    return total + Math.ceil((role.length + content.length) / 4);
  }, 0);
  return Math.max(0, memoryTokens + historyTokens);
}

function syncUsedTokensToContext() {
  const activeChat = getActiveChat();
  if (!activeChat) {
    updateTokenCounter(0, state.modelTokenLimit);
    return;
  }

  const estimatedContext = estimateContextTokens(activeChat.messages, activeChat.memory_block || "");
  const contextTokens = Math.max(estimatedContext, Number(state.lastRequestTokens || 0));
  state.usedTokens = Math.max(0, contextTokens);
  updateTokenCounter(state.usedTokens, state.modelTokenLimit);
}

function shouldCompactForLimit(messages, memoryBlock, tokenLimit) {
  const safeLimit = Math.max(0, Number(tokenLimit || 0));
  if (safeLimit <= 0) {
    return false;
  }

  const observedContext = Math.max(0, Number(state.lastRequestTokens || 0));
  const estimatedContext = estimateContextTokens(messages, memoryBlock);
  const contextTokens = Math.max(observedContext, estimatedContext);
  return contextTokens >= safeLimit * 0.75;
}

function setSwitchersDisabled(disabled) {
  headerProviderSelect.disabled = disabled;
  headerModelSelect.disabled = disabled;
}

function setCompactButtonDisabled(disabled) {
  if (compactButton instanceof HTMLButtonElement) {
    compactButton.disabled = disabled;
  }
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

async function persistChatsToSettings() {
  if (!state.settings) {
    return;
  }

  const nextSettings = JSON.parse(JSON.stringify(state.settings));
  nextSettings.chats = state.chats;
  const persisted = await persistSettings(nextSettings);
  state.settings = persisted;
}

async function compactHistoryForLimit(chat, targetTokenLimit, reasonLabel) {
  if (state.isCompacting || !chat) {
    return;
  }

  state.isCompacting = true;
  setSwitchersDisabled(true);
  setCompactButtonDisabled(true);
  setHistoryControlsDisabled(true);
  showCompactionProgressBubble();

  try {
    setStatus(`Compacting memory for ${reasonLabel}...`);
    const response = await fetch("/api/chat/compact", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        history: toApiHistory(chat.messages),
        target_token_limit: Math.max(0, Number(targetTokenLimit || 0)),
        memory_block: chat.memory_block || "",
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
    const compactedMessages = Array.isArray(payload.history) ? payload.history : [];

    if (compactedMessages.length > 0) {
      const timestamp = createTimestamp();
      chat.messages = compactedMessages.map((turn) => ({
        role: turn.role,
        content: turn.content,
        timestamp,
      }));
    }

    chat.memory_block = typeof payload.memory_block === "string" ? payload.memory_block : chat.memory_block;
    chat.updated_at = createTimestamp();
    state.lastRequestTokens = estimateContextTokens(chat.messages, chat.memory_block);
  } finally {
    clearCompactionProgressBubble();
    state.isCompacting = false;
    setSwitchersDisabled(state.isSwitching || state.isSending);
    setCompactButtonDisabled(state.isSwitching || state.isSending);
    setHistoryControlsDisabled(state.isSwitching || state.isSending);
  }
}

async function maybeAutoCompact(chat, reasonLabel, targetTokenLimit = state.modelTokenLimit) {
  if (!chat) {
    return { ok: true, compacted: false };
  }

  if (!shouldCompactForLimit(chat.messages, chat.memory_block || "", targetTokenLimit)) {
    return { ok: true, compacted: false };
  }

  try {
    await compactHistoryForLimit(chat, targetTokenLimit, reasonLabel);
    renderActiveChat();
    renderChatHistory();
    syncUsedTokensToContext();
    showToast("Compaction complete. Chat context was reduced.");
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
  setCompactButtonDisabled(true);
  setHistoryControlsDisabled(true);

  try {
    const activeChat = getActiveChat();
    const targetLimit = getModelTokenLimit(nextProviderId, nextModelId);
    const currentContextTokens = activeChat
      ? Math.max(Number(state.usedTokens || 0), estimateContextTokens(activeChat.messages, activeChat.memory_block || ""))
      : 0;
    if (targetLimit > 0 && currentContextTokens > targetLimit && activeChat) {
      const compactResult = await maybeAutoCompact(activeChat, "provider/model switch", targetLimit);
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
    nextSettings.chats = state.chats;
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
    syncUsedTokensToContext();
    setStatus("Active provider/model updated.");
  } catch (error) {
    state.activeProviderId = previousProviderId;
    state.activeModelId = previousModelId;
    syncSwitcherControls();
    updateMetaIndicators();
    setStatus(error.message, true);
  } finally {
    state.isSwitching = false;
    setSwitchersDisabled(state.isSending || state.isCompacting);
    setCompactButtonDisabled(state.isSending || state.isCompacting);
    setHistoryControlsDisabled(state.isSending || state.isCompacting);
  }
}

function normalizeIncomingChats(rawChats) {
  if (!Array.isArray(rawChats)) {
    return [];
  }

  const normalized = [];
  rawChats.forEach((rawChat) => {
    if (!rawChat || typeof rawChat !== "object") {
      return;
    }

    const chatId = typeof rawChat.id === "string" ? rawChat.id.trim() : "";
    if (!chatId) {
      return;
    }

    const messages = Array.isArray(rawChat.messages)
      ? rawChat.messages
          .filter((message) => message && (message.role === "user" || message.role === "assistant"))
          .map((message) => ({
            role: message.role,
            content: typeof message.content === "string" ? message.content : "",
            timestamp: typeof message.timestamp === "string" ? message.timestamp : createTimestamp(),
          }))
      : [];

    normalized.push({
      id: chatId,
      title: normalizeChatTitle(rawChat.title),
      type: "normal",
      messages,
      memory_block: typeof rawChat.memory_block === "string" ? rawChat.memory_block : "",
      created_at: typeof rawChat.created_at === "string" ? rawChat.created_at : "",
      updated_at: typeof rawChat.updated_at === "string" ? rawChat.updated_at : "",
    });
  });

  return normalized;
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
    state.chats = normalizeIncomingChats(settings.chats);

    state.providerLabel = activeProvider?.label ?? settings.active_provider_id ?? "";
    state.modelLabel = activeProvider?.models?.find((model) => model.id === activeConfig?.model)?.label ?? activeConfig?.model ?? "";
    state.modelTokenLimit = getModelTokenLimit(state.activeProviderId, state.activeModelId);

    const sortedChats = sortChatsByLatestMessage(state.chats);
    state.activeChatId = sortedChats[0]?.id ?? "";

    syncSwitcherControls();
    updateMetaIndicators();
    updateAssistantHeader(settings);
    renderChatHistory();
    renderActiveChat();
    syncUsedTokensToContext();
    setStatus("Gateway ready.");
  } catch (error) {
    updateMetaIndicators();
    assistantTitleNode.textContent = "This is your personal assistant";
    assistantMetaNode.textContent = "Assistant metadata unavailable.";
    syncSwitcherControls();
    renderChatHistory();
    renderEmptyChatView();
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
  state.isSending = isSending;
  sendButton.disabled = isSending;
  chatInput.disabled = isSending;
  setSwitchersDisabled(isSending || state.isSwitching || state.isCompacting);
  setCompactButtonDisabled(isSending || state.isSwitching || state.isCompacting);
  setHistoryControlsDisabled(isSending || state.isSwitching || state.isCompacting);
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

async function finalizeSuccessfulResponse(chatId, assistantBubble) {
  const chat = state.chats.find((entry) => entry.id === chatId);
  if (!chat) {
    return;
  }

  chat.messages.push({
    role: "assistant",
    content: assistantBubble.dataset.rawText ?? "",
    timestamp: createTimestamp(),
  });
  chat.updated_at = createTimestamp();

  const compactResult = await maybeAutoCompact(chat, "ongoing chat", state.modelTokenLimit);
  if (!compactResult.ok) {
    return;
  }

  renderChatHistory();
  syncUsedTokensToContext();

  try {
    await persistChatsToSettings();
  } catch (error) {
    setStatus(`Response complete, but chat history was not saved: ${error.message}`, true);
    return;
  }

  if (compactResult.compacted) {
    setStatus("Response complete. Memory compacted.");
    return;
  }

  setStatus("Response complete.");
}

async function sendMessage(event) {
  event.preventDefault();

  const message = chatInput.value.trim();
  if (!message) {
    setStatus("Please enter a message.", true);
    return;
  }

  const existingChat = getActiveChat();
  const requestHistory = existingChat ? toApiHistory(existingChat.messages) : [];
  const requestMemoryBlock = existingChat?.memory_block || "";

  let chat = existingChat;
  if (!chat) {
    chat = createChatEntry(message);
    state.chats.push(chat);
    state.activeChatId = chat.id;
    updateCurrentChatTitle();
    renderChatHistory();
  }

  const userTimestamp = createTimestamp();
  chat.messages.push({
    role: "user",
    content: message,
    timestamp: userTimestamp,
  });
  chat.updated_at = userTimestamp;

  renderChatHistory();
  setSendingState(true);
  setStatus("Sending...");

  addMessage("user", message, userTimestamp);
  const assistantBubble = addMessage("assistant", "");
  assistantBubble.dataset.rawText = "";
  setAssistantLoading(assistantBubble, true);
  chatInput.value = "";

  try {
    await persistChatsToSettings();
  } catch (error) {
    setStatus(`Message sent, but chat history was not saved yet: ${error.message}`, true);
  }

  try {
    const response = await fetch("/api/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message,
        history: requestHistory,
        memory_block: requestMemoryBlock,
      }),
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
          await finalizeSuccessfulResponse(chat.id, assistantBubble);
          setSendingState(false);
          return;
        }
      }
    }

    await finalizeSuccessfulResponse(chat.id, assistantBubble);
  } catch (error) {
    setAssistantLoading(assistantBubble, false);

    if (!assistantBubble.dataset.rawText) {
      assistantBubble.dataset.rawText = "Sorry, something went wrong.";
      assistantBubble.innerHTML = renderMarkdown(assistantBubble.dataset.rawText);
    }

    setStatus(error.message, true);
  } finally {
    setSendingState(false);
    syncUsedTokensToContext();
    chatInput.focus();
  }
}

async function triggerManualCompaction() {
  if (state.isCompacting || state.isSwitching || sendButton.disabled) {
    return;
  }

  const activeChat = getActiveChat();
  if (!activeChat) {
    setStatus("No active chat to compact.", true);
    return;
  }

  try {
    await compactHistoryForLimit(activeChat, state.modelTokenLimit, "manual request");
    renderActiveChat();
    renderChatHistory();
    syncUsedTokensToContext();
    await persistChatsToSettings();
    showToast("Compaction complete. Chat context was reduced.");
    setStatus("Memory compacted.");
  } catch (error) {
    setStatus(error.message, true);
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

if (compactButton instanceof HTMLButtonElement) {
  compactButton.addEventListener("click", triggerManualCompaction);
}

if (newChatButton instanceof HTMLButtonElement) {
  newChatButton.addEventListener("click", startNewChat);
}

chatHistoryList.addEventListener("click", (event) => {
  const target = event.target;
  if (!(target instanceof Node)) {
    return;
  }

  const actionButton = target instanceof HTMLElement ? target.closest("button[data-chat-id][data-action]") : null;
  if (!(actionButton instanceof HTMLButtonElement)) {
    return;
  }

  const chatId = actionButton.dataset.chatId;
  const action = actionButton.dataset.action;
  if (!chatId || !action) {
    return;
  }

  if (action === "open") {
    if (chatId === state.activeChatId) {
      return;
    }
    activateChat(chatId);
    return;
  }

  if (action === "delete") {
    deleteChat(chatId);
    return;
  }

  if (action === "edit") {
    editChatTitle(chatId);
  }
});

chatForm.addEventListener("submit", sendMessage);
window.addEventListener("load", loadGatewayMeta);
