const CHAT_TITLE_MAX_LENGTH = 24;
const EDITABLE_CHAT_TITLE_MAX_LENGTH = 24;

const chatForm = document.getElementById("chat-form");
const chatInput = document.getElementById("chat-input");
const sendButton = document.getElementById("send-btn");
const stopButton = document.getElementById("stop-btn");
const chatThread = document.getElementById("chat-thread");
const providerIndicator = document.getElementById("provider-indicator");
const modelIndicator = document.getElementById("model-indicator");
const systemTraceToggleButton = document.getElementById("system-trace-toggle");
const tokenCounterNode = document.getElementById("token-counter");
const tokenCounterTotalNode = document.getElementById("token-counter-total");
const statusNode = document.getElementById("status");
const menuButton = document.getElementById("menu-btn");
const menuPopover = document.getElementById("menu-popover");
const assistantTitleNode = document.getElementById("assistant-title");
const assistantMetaNode = document.getElementById("assistant-meta");
const dailyTokenUsageNode = document.getElementById("daily-token-usage");
const headerProviderSelect = document.getElementById("header-provider-select");
const headerModelSelect = document.getElementById("header-model-select");
const compactButton = document.getElementById("compact-btn");
const currentChatTitleNode = document.getElementById("current-chat-title");
const chatHistoryList = document.getElementById("chat-history-list");
const newChatButton = document.getElementById("new-chat-btn");
const mcpList = document.getElementById("mcp-list");
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
  dailyTokenUsage: [],
  mcps: [],
  mcpConfigs: {},
  chats: [],
  activeChatId: "",
  chatRuntimes: {},
  isCompacting: false,
  isSwitching: false,
  suppressSwitcherEvents: false,
  toastTimerId: null,
  compactionBubble: null,
};

function getChatRuntime(chatId) {
  if (!chatId) {
    return null;
  }

  if (!state.chatRuntimes[chatId] || typeof state.chatRuntimes[chatId] !== "object") {
    state.chatRuntimes[chatId] = {
      processing: false,
      queue: [],
      cancelledRequestIds: new Set(),
      activeRequestId: "",
      abortController: null,
    };
  }

  return state.chatRuntimes[chatId];
}

function removeChatRuntime(chatId) {
  const runtime = state.chatRuntimes[chatId];
  if (!runtime) {
    return;
  }

  runtime.queue.forEach((job) => {
    if (job && typeof job.requestId === "string") {
      runtime.cancelledRequestIds.add(job.requestId);
    }
  });

  runtime.queue = [];
  if (runtime.activeRequestId) {
    runtime.cancelledRequestIds.add(runtime.activeRequestId);
  }

  if (runtime.abortController instanceof AbortController) {
    runtime.abortController.abort();
  }
}

function isChatBusy(chatId) {
  const runtime = state.chatRuntimes[chatId];
  if (!runtime) {
    return false;
  }
  return Boolean(runtime.processing) || (Array.isArray(runtime.queue) && runtime.queue.length > 0);
}

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
  currentChatTitleNode.textContent = activeChat ? deriveChatTitle(normalizeChatTitle(activeChat.title)) : "New chat";
}

function updateSystemTraceToggleLabel() {
  if (!(systemTraceToggleButton instanceof HTMLButtonElement)) {
    return;
  }

  const activeChat = getActiveChat();
  const isCollapsed = Boolean(activeChat?.collapse_system_trace);
  systemTraceToggleButton.textContent = isCollapsed ? "Show system trace" : "Hide system trace";
  systemTraceToggleButton.disabled = !activeChat;
}

function createChatEntry(firstMessage) {
  const timestamp = createTimestamp();
  return {
    id: createChatId(),
    title: deriveChatTitle(firstMessage),
    type: "normal",
    messages: [],
    memory_block: "",
    total_tokens_used: 0,
    collapse_system_trace: true,
    created_at: timestamp,
    updated_at: timestamp,
  };
}

function toApiHistory(messages) {
  return messages
    .filter((turn) => turn && (turn.role === "user" || turn.role === "assistant"))
    .filter((turn) => typeof turn.content === "string" && turn.content.trim())
    .map((turn) => ({ role: turn.role, content: turn.content }));
}

function setHistoryControlsDisabled(disabled) {
  if (newChatButton instanceof HTMLButtonElement) {
    newChatButton.disabled = disabled;
  }

  const buttons = chatHistoryList.querySelectorAll("button[data-chat-id]");
  buttons.forEach((button) => {
    const action = button.dataset.action;
    if (action === "delete" || action === "edit") {
      button.disabled = disabled;
      return;
    }
    button.disabled = false;
  });
}

function addMessage(role, text = "", timestamp = "", status = "") {
  const wrapper = document.createElement("div");
  wrapper.className = `chat-message ${role}`;
  if (status) {
    wrapper.classList.add(`status-${status}`);
  }

  const title = document.createElement("p");
  title.className = "chat-role";
  const roleLabel = role === "user" ? "You" : role === "system" ? "System" : state.botName || "Krill";
  title.textContent = `${roleLabel} - ${formatMessageTimestamp(timestamp)}`;

  const bubble = document.createElement("div");
  bubble.className = "chat-bubble";

  if (role === "assistant") {
    if ((status === "queued" || status === "processing") && !text) {
      const label = status === "queued" ? "Queued" : "Processing";
      bubble.innerHTML = `<span class="compaction-loading">${label} <span class="typing-dots" aria-label="${label}"><span></span><span></span><span></span></span></span>`;
    } else {
      bubble.innerHTML = renderMarkdown(text);
    }
  } else {
    bubble.textContent = text;
  }

  wrapper.appendChild(title);
  wrapper.appendChild(bubble);
  chatThread.appendChild(wrapper);
  chatThread.scrollTop = chatThread.scrollHeight;

  return bubble;
}

function normalizeToolUsage(toolUsage) {
  if (!Array.isArray(toolUsage)) {
    return [];
  }

  return toolUsage
    .filter((entry) => entry && typeof entry === "object")
    .map((entry) => ({
      mcp_id: typeof entry.mcp_id === "string" ? entry.mcp_id : "",
      mcp_label: typeof entry.mcp_label === "string" ? entry.mcp_label : "",
      tool_id: typeof entry.tool_id === "string" ? entry.tool_id : "",
      tool_label: typeof entry.tool_label === "string" ? entry.tool_label : "",
    }))
    .filter((entry) => entry.mcp_id && entry.tool_id);
}

function renderToolUsageLine(wrapper, toolUsage) {
  const normalized = normalizeToolUsage(toolUsage);
  if (normalized.length === 0) {
    return;
  }

  const usageNode = document.createElement("p");
  usageNode.className = "tool-usage-note";
  const labels = normalized.map((entry) => {
    const mcpLabel = entry.mcp_label || entry.mcp_id;
    const toolLabel = entry.tool_label || entry.tool_id;
    return `${mcpLabel} (${toolLabel})`;
  });
  usageNode.textContent = `used Tools: ${labels.join(", ")}`;
  wrapper.appendChild(usageNode);
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
  updateSystemTraceToggleLabel();
  const activeChat = getActiveChat();
  if (!activeChat) {
    renderEmptyChatView();
    return;
  }

  chatThread.innerHTML = "";
  activeChat.messages.forEach((turn) => {
    if (turn?.role !== "user" && turn?.role !== "assistant" && turn?.role !== "system") {
      return;
    }

    if (turn.role === "system" && activeChat.collapse_system_trace) {
      return;
    }

    const bubble = addMessage(turn.role, String(turn.content ?? ""), String(turn.timestamp ?? ""), String(turn.status ?? ""));
    if (turn.role === "assistant") {
      const wrapper = bubble.parentElement;
      if (wrapper instanceof HTMLElement) {
        renderToolUsageLine(wrapper, turn.tool_usage);
      }
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
    selectButton.disabled = false;

    const titleNode = document.createElement("p");
    titleNode.className = "chat-history-title";
    titleNode.textContent = normalizeChatTitle(chat.title);

    const timeNode = document.createElement("p");
    timeNode.className = "chat-history-time";
    const latestTimestamp = getLatestChatTimestamp(chat);
    const runtime = getChatRuntime(chat.id);
    const queuedCount = runtime && Array.isArray(runtime.queue) ? runtime.queue.length : 0;
    timeNode.textContent = latestTimestamp ? formatMessageTimestamp(latestTimestamp) : "No messages yet";

    const queueBadgeNode = document.createElement("p");
    queueBadgeNode.className = "chat-history-queue-badge";
    if (runtime && runtime.processing && queuedCount > 0) {
      queueBadgeNode.textContent = `${queuedCount} queued`;
    } else if (runtime && runtime.processing) {
      queueBadgeNode.textContent = "processing";
    } else if (queuedCount > 0) {
      queueBadgeNode.textContent = `${queuedCount} queued`;
    } else {
      queueBadgeNode.textContent = "";
    }

    selectButton.appendChild(titleNode);
    selectButton.appendChild(timeNode);
    if (queueBadgeNode.textContent) {
      selectButton.appendChild(queueBadgeNode);
    }

    const actionsNode = document.createElement("div");
    actionsNode.className = "chat-history-actions";

    const editButton = document.createElement("button");
    editButton.type = "button";
    editButton.className = "chat-history-action-btn";
    editButton.dataset.chatId = chat.id;
    editButton.dataset.action = "edit";
    editButton.disabled = state.isSwitching || state.isCompacting;
    editButton.setAttribute("aria-label", "Edit chat title");
    editButton.textContent = "✎";

    const deleteButton = document.createElement("button");
    deleteButton.type = "button";
    deleteButton.className = "chat-history-action-btn danger";
    deleteButton.dataset.chatId = chat.id;
    deleteButton.dataset.action = "delete";
    deleteButton.disabled = state.isSwitching || state.isCompacting;
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

  removeChatRuntime(chatId);

  state.chats.splice(index, 1);

  if (state.activeChatId === chatId) {
    const nextActiveChat = sortChatsByLatestMessage(state.chats)[0] ?? null;
    state.activeChatId = nextActiveChat?.id ?? "";
    state.lastRequestTokens = 0;
  }

  renderChatHistory();
  renderActiveChat();
  syncUsedTokensToContext();
  updateComposerState();

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
  updateComposerState();
}

function startNewChat() {
  if (state.isSwitching || state.isCompacting) {
    return;
  }

  state.activeChatId = "";
  state.lastRequestTokens = 0;
  renderChatHistory();
  renderActiveChat();
  updateTokenCounter(0, state.modelTokenLimit);
  setStatus("New chat ready. Send a first message to create it.");
  updateComposerState();
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

function getTodayDateKey() {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function normalizeDailyTokenUsage(rawUsage) {
  if (!Array.isArray(rawUsage)) {
    return [];
  }

  return rawUsage
    .filter((entry) => entry && typeof entry === "object")
    .map((entry) => {
      const date = typeof entry.date === "string" ? entry.date.trim() : "";
      const tokensRaw = Number(entry.tokens);
      const tokens = Number.isFinite(tokensRaw) && tokensRaw > 0 ? Math.floor(tokensRaw) : 0;
      return { date, tokens };
    })
    .filter((entry) => entry.date);
}

function updateDailyTokenUsageLabel() {
  if (!(dailyTokenUsageNode instanceof HTMLElement)) {
    return;
  }

  const today = getTodayDateKey();
  const todayEntry = state.dailyTokenUsage.find((entry) => entry.date === today);
  const tokens = todayEntry ? Number(todayEntry.tokens || 0) : 0;
  dailyTokenUsageNode.textContent = `Today: ${formatNumber(tokens)} tokens`;
}

function addDailyTokenUsage(tokensToAdd) {
  const tokens = Number(tokensToAdd);
  if (!Number.isFinite(tokens) || tokens <= 0) {
    return;
  }

  const today = getTodayDateKey();
  const existingEntry = state.dailyTokenUsage.find((entry) => entry.date === today);
  if (existingEntry) {
    existingEntry.tokens = Math.max(0, Number(existingEntry.tokens || 0)) + Math.floor(tokens);
  } else {
    state.dailyTokenUsage.push({ date: today, tokens: Math.floor(tokens) });
  }

  updateDailyTokenUsageLabel();
}

function updateTokenCounter(usedTokens = state.usedTokens, tokenLimit = state.modelTokenLimit) {
  const safeUsed = Math.max(0, Number(usedTokens || 0));
  const safeLimit = Math.max(0, Number(tokenLimit || 0));

  state.usedTokens = safeUsed;
  state.modelTokenLimit = safeLimit;
  const activeChat = getActiveChat();
  const chatTotalTokens = activeChat && Number.isFinite(Number(activeChat.total_tokens_used))
    ? Math.max(0, Number(activeChat.total_tokens_used || 0))
    : 0;

  const percent = safeLimit > 0 ? ((safeUsed / safeLimit) * 100).toFixed(2) : "0.00";
  tokenCounterNode.textContent = `${formatNumber(safeUsed)} / ${formatNumber(safeLimit)} tokens (${percent}% used)`;
  if (tokenCounterTotalNode instanceof HTMLElement) {
    tokenCounterTotalNode.textContent = `Chat total: ${formatNumber(chatTotalTokens)}`;
  }
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
    if (role !== "user" && role !== "assistant") {
      return total;
    }
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
  nextSettings.mcp_configs = state.mcpConfigs;
  nextSettings.daily_token_usage = state.dailyTokenUsage;
  const persisted = await persistSettings(nextSettings);
  state.settings = persisted;
  state.dailyTokenUsage = normalizeDailyTokenUsage(persisted.daily_token_usage);
  updateDailyTokenUsageLabel();
}

function normalizeIncomingMcpConfigs(rawConfigs) {
  if (!rawConfigs || typeof rawConfigs !== "object") {
    return {};
  }

  const normalized = {};
  Object.entries(rawConfigs).forEach(([mcpId, rawValue]) => {
    if (!rawValue || typeof rawValue !== "object") {
      return;
    }

    const params = rawValue.params && typeof rawValue.params === "object" ? rawValue.params : {};
    const normalizedParams = {};
    Object.entries(params).forEach(([key, value]) => {
      if (typeof key !== "string") {
        return;
      }
      normalizedParams[key] = typeof value === "string" ? value : String(value ?? "");
    });

    normalized[mcpId] = {
      enabled: Boolean(rawValue.enabled),
      params: normalizedParams,
    };
  });

  return normalized;
}

function getMcpConfig(mcpId) {
  const config = state.mcpConfigs[mcpId];
  if (config && typeof config === "object") {
    return config;
  }

  return { enabled: false, params: {} };
}

async function persistMcpConfigsToSettings() {
  if (!state.settings) {
    return;
  }

  const nextSettings = JSON.parse(JSON.stringify(state.settings));
  nextSettings.mcp_configs = state.mcpConfigs;
  nextSettings.chats = state.chats;
  nextSettings.daily_token_usage = state.dailyTokenUsage;
  const persisted = await persistSettings(nextSettings);
  state.settings = persisted;
  state.mcpConfigs = normalizeIncomingMcpConfigs(persisted.mcp_configs);
  state.dailyTokenUsage = normalizeDailyTokenUsage(persisted.daily_token_usage);
  updateDailyTokenUsageLabel();
}

async function verifyMcpConfig(mcpId) {
  const config = getMcpConfig(mcpId);
  const response = await fetch("/api/mcps/verify", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      mcp_id: mcpId,
      params: config.params,
    }),
  });

  if (!response.ok) {
    let detail = "Tool verification failed.";
    try {
      const payload = await response.json();
      if (typeof payload.detail === "string" && payload.detail) {
        detail = payload.detail;
      }
    } catch (error) {
      detail = "Tool verification failed.";
    }

    throw new Error(detail);
  }
}

async function fetchGitSshKey() {
  const response = await fetch("/api/mcps/git/ssh-key");
  if (!response.ok) {
    let detail = "Failed to load SSH key.";
    try {
      const payload = await response.json();
      if (typeof payload.detail === "string" && payload.detail) {
        detail = payload.detail;
      }
    } catch (error) {
      detail = "Failed to load SSH key.";
    }
    throw new Error(detail);
  }

  const payload = await response.json();
  const publicKey = typeof payload.public_key === "string" ? payload.public_key : "";
  if (!publicKey) {
    throw new Error("SSH key response was empty.");
  }

  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(publicKey);
    return;
  }

  throw new Error("Clipboard API unavailable. Use a modern browser context.");
}

async function verifyGitSshAccess() {
  const response = await fetch("/api/mcps/git/verify-ssh", { method: "POST" });
  if (!response.ok) {
    let detail = "GitHub SSH verification failed.";
    try {
      const payload = await response.json();
      if (typeof payload.detail === "string" && payload.detail) {
        detail = payload.detail;
      }
    } catch (error) {
      detail = "GitHub SSH verification failed.";
    }
    throw new Error(detail);
  }
}

function renderMcpPanel() {
  if (!(mcpList instanceof HTMLElement)) {
    return;
  }

  mcpList.innerHTML = "";
  if (!Array.isArray(state.mcps) || state.mcps.length === 0) {
    const emptyNode = document.createElement("p");
    emptyNode.className = "chat-history-empty";
    emptyNode.textContent = "No tools available.";
    mcpList.appendChild(emptyNode);
    return;
  }

  state.mcps.forEach((mcp) => {
    const card = document.createElement("div");
    card.className = "mcp-card";
    card.dataset.mcpId = mcp.id;

    const config = getMcpConfig(mcp.id);

    const titleRow = document.createElement("div");
    titleRow.className = "mcp-title-row";

    const title = document.createElement("p");
    title.className = "mcp-title";
    title.textContent = mcp.label;

    const toggleLabel = document.createElement("label");
    toggleLabel.className = "mcp-toggle";

    const toggleInput = document.createElement("input");
    toggleInput.type = "checkbox";
    toggleInput.checked = Boolean(config.enabled);
    toggleInput.dataset.action = "toggle";
    toggleInput.dataset.mcpId = mcp.id;

    const toggleText = document.createElement("span");
    toggleText.textContent = "Enabled";

    toggleLabel.appendChild(toggleInput);
    toggleLabel.appendChild(toggleText);

    titleRow.appendChild(title);
    titleRow.appendChild(toggleLabel);

    const description = document.createElement("p");
    description.className = "mcp-description";
    description.textContent = typeof mcp.description === "string" ? mcp.description : "";

    card.appendChild(titleRow);
    card.appendChild(description);

    const fields = Array.isArray(mcp.config_fields) ? mcp.config_fields : [];
    fields.forEach((field) => {
      const fieldId = typeof field.id === "string" ? field.id : "";
      if (!fieldId) {
        return;
      }

      const fieldWrapper = document.createElement("div");
      fieldWrapper.className = "mcp-field";

      const fieldLabel = document.createElement("label");
      fieldLabel.textContent = field.label || fieldId;
      fieldLabel.setAttribute("for", `mcp-${mcp.id}-${fieldId}`);

      const fieldInput = document.createElement("input");
      fieldInput.id = `mcp-${mcp.id}-${fieldId}`;
      fieldInput.type = field.type === "password" ? "password" : "text";
      fieldInput.value = typeof config.params?.[fieldId] === "string" ? config.params[fieldId] : "";
      fieldInput.placeholder = typeof field.placeholder === "string" ? field.placeholder : "";
      fieldInput.dataset.action = "param";
      fieldInput.dataset.mcpId = mcp.id;
      fieldInput.dataset.fieldId = fieldId;

      fieldWrapper.appendChild(fieldLabel);
      fieldWrapper.appendChild(fieldInput);
      card.appendChild(fieldWrapper);
    });

    const actions = document.createElement("div");
    actions.className = "mcp-card-actions";

    if (mcp.id === "git_ops") {
      const sshKeyButton = document.createElement("button");
      sshKeyButton.type = "button";
      sshKeyButton.className = "mcp-link-btn";
      sshKeyButton.textContent = "SSH key";
      sshKeyButton.dataset.action = "ssh-key";
      sshKeyButton.dataset.mcpId = mcp.id;

      const verifyButton = document.createElement("button");
      verifyButton.type = "button";
      verifyButton.className = "mcp-link-btn";
      verifyButton.textContent = "Verify";
      verifyButton.dataset.action = "verify-ssh";
      verifyButton.dataset.mcpId = mcp.id;

      actions.appendChild(sshKeyButton);
      actions.appendChild(verifyButton);
    } else {
      const saveButton = document.createElement("button");
      saveButton.type = "button";
      saveButton.className = "mcp-link-btn";
      saveButton.textContent = "Save";
      saveButton.dataset.action = "save";
      saveButton.dataset.mcpId = mcp.id;

      const verifyButton = document.createElement("button");
      verifyButton.type = "button";
      verifyButton.className = "mcp-link-btn";
      verifyButton.textContent = "Verify";
      verifyButton.dataset.action = "verify";
      verifyButton.dataset.mcpId = mcp.id;

      actions.appendChild(saveButton);
      actions.appendChild(verifyButton);
    }

    if (mcp.id !== "local_files") {
      card.appendChild(actions);
    }
    mcpList.appendChild(card);
  });
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
    if (state.activeChatId === chat.id) {
      state.lastRequestTokens = estimateContextTokens(chat.messages, chat.memory_block);
    }
  } finally {
    clearCompactionProgressBubble();
    state.isCompacting = false;
    setSwitchersDisabled(state.isSwitching);
    setCompactButtonDisabled(state.isSwitching);
    setHistoryControlsDisabled(state.isSwitching);
    updateComposerState();
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
    nextSettings.mcp_configs = state.mcpConfigs;
    nextSettings.daily_token_usage = state.dailyTokenUsage;
    const persisted = await persistSettings(nextSettings);

    state.settings = persisted;
    state.dailyTokenUsage = normalizeDailyTokenUsage(persisted.daily_token_usage);
    updateDailyTokenUsageLabel();
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
    setStatus(hardErrorText, true);
  } finally {
    state.isSwitching = false;
    setSwitchersDisabled(state.isCompacting);
    setCompactButtonDisabled(state.isCompacting);
    setHistoryControlsDisabled(state.isCompacting);
    updateComposerState();
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
          .filter((message) => message && (message.role === "user" || message.role === "assistant" || message.role === "system"))
          .map((message) => ({
            role: message.role,
            content: typeof message.content === "string" ? message.content : "",
            timestamp: typeof message.timestamp === "string" ? message.timestamp : createTimestamp(),
            system_type: typeof message.system_type === "string" ? message.system_type : "",
            tool_usage: normalizeToolUsage(message.tool_usage),
            request_id: typeof message.request_id === "string" ? message.request_id : "",
            status: typeof message.status === "string" ? message.status : "",
          }))
      : [];

    normalized.push({
      id: chatId,
      title: normalizeChatTitle(rawChat.title),
      type: "normal",
      messages,
      memory_block: typeof rawChat.memory_block === "string" ? rawChat.memory_block : "",
      total_tokens_used:
        Number.isFinite(Number(rawChat.total_tokens_used)) && Number(rawChat.total_tokens_used) > 0
          ? Number(rawChat.total_tokens_used)
          : 0,
      collapse_system_trace:
        typeof rawChat.collapse_system_trace === "boolean" ? rawChat.collapse_system_trace : true,
      created_at: typeof rawChat.created_at === "string" ? rawChat.created_at : "",
      updated_at: typeof rawChat.updated_at === "string" ? rawChat.updated_at : "",
    });
  });

  return normalized;
}

async function loadGatewayMeta() {
  try {
    const [providersResponse, settingsResponse, mcpsResponse] = await Promise.all([
      fetch("/api/providers"),
      fetch("/api/settings"),
      fetch("/api/mcps"),
    ]);

    if (!providersResponse.ok || !settingsResponse.ok || !mcpsResponse.ok) {
      throw new Error("Failed to load gateway metadata.");
    }

    const providers = await providersResponse.json();
    const settings = await settingsResponse.json();
    const mcps = await mcpsResponse.json();

    const activeProvider = providers.find((provider) => provider.id === settings.active_provider_id);
    const activeConfig = settings.provider_configs?.[settings.active_provider_id];

    state.providers = providers;
    state.settings = settings;
    state.activeProviderId = settings.active_provider_id ?? "";
    state.activeModelId = activeConfig?.model ?? "";
    state.botName = typeof settings?.bot_name === "string" ? settings.bot_name.trim() : "";
    state.chats = normalizeIncomingChats(settings.chats);
    state.dailyTokenUsage = normalizeDailyTokenUsage(settings.daily_token_usage);
    state.mcps = Array.isArray(mcps) ? mcps : [];
    state.mcpConfigs = normalizeIncomingMcpConfigs(settings.mcp_configs);

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
    renderMcpPanel();
    syncUsedTokensToContext();
    updateDailyTokenUsageLabel();
    updateComposerState();
    setStatus("Gateway ready.");
  } catch (error) {
    updateMetaIndicators();
    assistantTitleNode.textContent = "This is your personal assistant";
    assistantMetaNode.textContent = "Assistant metadata unavailable.";
    syncSwitcherControls();
    renderChatHistory();
    renderEmptyChatView();
    renderMcpPanel();
    updateTokenCounter(0, 0);
    updateDailyTokenUsageLabel();
    updateComposerState();
    setStatus(error.message, true);
  }
}

function toggleMenu(forceOpen) {
  const shouldOpen = typeof forceOpen === "boolean" ? forceOpen : menuPopover.classList.contains("hidden");
  menuPopover.classList.toggle("hidden", !shouldOpen);
  menuButton.setAttribute("aria-expanded", shouldOpen ? "true" : "false");
}

function updateComposerState() {
  const activeChatId = state.activeChatId;
  const runtime = activeChatId ? getChatRuntime(activeChatId) : null;
  const isBusy = Boolean(runtime?.processing);
  sendButton.disabled = false;
  chatInput.disabled = false;
  if (stopButton instanceof HTMLButtonElement) {
    stopButton.disabled = !isBusy;
  }
  setSwitchersDisabled(state.isSwitching || state.isCompacting);
  setCompactButtonDisabled(state.isSwitching || state.isCompacting || isBusy);
  setHistoryControlsDisabled(state.isSwitching || state.isCompacting);
}

function processSseBlock(block, context) {
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
    context.assistantMessage.content = `${context.assistantMessage.content || ""}${payload.text ?? ""}`;
    context.assistantMessage.status = "processing";
    if (state.activeChatId === context.chatId) {
      renderActiveChat();
    }
    return { done: false, hasError: false };
  }

  if (eventName === "meta") {
    const requestUsedTokens = Number(payload.used_tokens ?? 0);
    if (Number.isFinite(requestUsedTokens) && requestUsedTokens > 0) {
      context.usedTokens = requestUsedTokens;
      if (state.activeChatId === context.chatId) {
        state.lastRequestTokens = requestUsedTokens;
        syncUsedTokensToContext();
      }
    }

    context.toolUsage = normalizeToolUsage(payload.used_mcp_tools);
    const metaTrace = Array.isArray(payload.system_trace_messages)
      ? payload.system_trace_messages
          .filter((entry) => entry && typeof entry === "object")
          .map((entry) => ({
            system_type: typeof entry.system_type === "string" ? entry.system_type : "orchestrator",
            content: typeof entry.content === "string" ? entry.content : "",
          }))
          .filter((entry) => entry.content)
      : [];
    if (metaTrace.length > 0) {
      const merged = [...context.systemTrace];
      metaTrace.forEach((entry) => {
        const exists = merged.some((item) => item.system_type === entry.system_type && item.content === entry.content);
        if (!exists) {
          merged.push(entry);
        }
      });
      context.systemTrace = merged;
    }

    if (payload.token_limit && state.activeChatId === context.chatId) {
      updateTokenCounter(state.usedTokens, payload.token_limit ?? state.modelTokenLimit);
    }
    return { done: false, hasError: false };
  }

  if (eventName === "tool_step") {
    const entry = {
      system_type: typeof payload.system_type === "string" ? payload.system_type : "tool_step",
      content: typeof payload.content === "string" ? payload.content : "",
    };

    if (entry.content) {
      const duplicate = context.systemTrace.some(
        (item) => item.system_type === entry.system_type && item.content === entry.content,
      );
      if (!duplicate) {
        context.systemTrace.push(entry);
        const chat = state.chats.find((entryChat) => entryChat.id === context.chatId);
        if (chat) {
          appendSystemTraceMessages(chat, [entry], createTimestamp(), context.requestId);
          chat.updated_at = createTimestamp();
          if (state.activeChatId === context.chatId) {
            renderActiveChat();
          }
          renderChatHistory();
        }
      }
    }
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

function appendSystemTraceMessages(chat, traceMessages, timestamp, requestId = "") {
  if (!Array.isArray(traceMessages) || traceMessages.length === 0) {
    return;
  }

  traceMessages.forEach((entry) => {
    if (!entry || typeof entry !== "object") {
      return;
    }

    const content = typeof entry.content === "string" ? entry.content.trim() : "";
    if (!content) {
      return;
    }

    const duplicate = chat.messages.some(
      (message) =>
        message.role === "system" &&
        message.request_id === requestId &&
        message.system_type === (typeof entry.system_type === "string" ? entry.system_type : "orchestrator") &&
        message.content === content,
    );
    if (duplicate) {
      return;
    }

    chat.messages.push({
      role: "system",
      content,
      timestamp,
      system_type: typeof entry.system_type === "string" ? entry.system_type : "orchestrator",
      tool_usage: [],
      request_id: requestId,
      status: "",
    });
  });
}

async function finalizeSuccessfulResponse(chat, assistantMessage, context) {
  if (!chat || !assistantMessage) {
    return;
  }

  const assistantTimestamp = createTimestamp();
  appendSystemTraceMessages(chat, context.systemTrace, assistantTimestamp, context.requestId);

  assistantMessage.timestamp = assistantTimestamp;
  assistantMessage.status = "done";
  assistantMessage.tool_usage = context.toolUsage;
  if (Number.isFinite(Number(context.usedTokens)) && Number(context.usedTokens) > 0) {
    const currentTotal = Number(chat.total_tokens_used || 0);
    chat.total_tokens_used = Math.max(0, currentTotal) + Number(context.usedTokens);
    addDailyTokenUsage(Number(context.usedTokens));
  }
  chat.updated_at = assistantTimestamp;

  if (state.activeChatId === chat.id) {
    state.lastRequestTokens = Number.isFinite(Number(context.usedTokens)) ? Number(context.usedTokens) : 0;
  }

  const compactResult = await maybeAutoCompact(chat, "ongoing chat", state.modelTokenLimit);
  if (!compactResult.ok) {
    return;
  }

  if (state.activeChatId === chat.id) {
    renderActiveChat();
  }
  renderChatHistory();
  if (state.activeChatId === chat.id) {
    syncUsedTokensToContext();
  }

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

function buildQueueSnapshot(chat) {
  const activeProviderId = state.activeProviderId;
  const providerConfig = state.settings?.provider_configs?.[activeProviderId] ?? null;
  return {
    history: toApiHistory(chat.messages),
    memoryBlock: chat.memory_block || "",
    providerId: activeProviderId,
    model: providerConfig?.model ?? "",
    apiKey: providerConfig?.api_key ?? "",
    botName: state.settings?.bot_name ?? "",
    systemPrompt: state.settings?.system_prompt ?? "",
  };
}

function findMessageByRequestId(chat, requestId) {
  return chat.messages.find((message) => message.request_id === requestId) ?? null;
}

async function executeQueuedJob(chat, job, runtime) {
  const assistantMessage = findMessageByRequestId(chat, job.requestId);
  if (!assistantMessage) {
    return;
  }

  assistantMessage.status = "processing";
  const context = {
    chatId: chat.id,
    requestId: job.requestId,
    assistantMessage,
    usedTokens: 0,
    toolUsage: [],
    systemTrace: [],
  };
  if (state.activeChatId === chat.id) {
    renderActiveChat();
    setStatus("Processing...");
  }
  renderChatHistory();

  try {
    runtime.abortController = new AbortController();
    const response = await fetch("/api/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      signal: runtime.abortController.signal,
      body: JSON.stringify({
        message: job.message,
        history: job.snapshot.history,
        memory_block: job.snapshot.memoryBlock,
        provider_id: job.snapshot.providerId,
        model: job.snapshot.model,
        api_key: job.snapshot.apiKey,
        bot_name: job.snapshot.botName,
        system_prompt: job.snapshot.systemPrompt,
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

      if (runtime.cancelledRequestIds.has(job.requestId)) {
        return;
      }

      buffer += decoder.decode(value, { stream: true });
      const blocks = buffer.split("\n\n");
      buffer = blocks.pop() ?? "";

      for (const block of blocks) {
        const result = processSseBlock(block, context);
        if (result.hasError) {
          throw new Error(result.errorMessage);
        }

        if (result.done) {
          break;
        }
      }
    }

    if (runtime.cancelledRequestIds.has(job.requestId)) {
      return;
    }

    await finalizeSuccessfulResponse(chat, assistantMessage, context);
  } catch (error) {
    if (runtime.cancelledRequestIds.has(job.requestId)) {
      return;
    }

    if (error instanceof DOMException && error.name === "AbortError") {
      return;
    }

    const hardErrorText = typeof error?.message === "string" && error.message ? error.message : "Hard error.";
    if (assistantMessage.content) {
      assistantMessage.content = `${assistantMessage.content}\n\nHard error: ${hardErrorText}`;
    } else {
      assistantMessage.content = hardErrorText;
    }

    const errorTimestamp = createTimestamp();
    appendSystemTraceMessages(chat, context.systemTrace, errorTimestamp, context.requestId);
    assistantMessage.timestamp = errorTimestamp;
    assistantMessage.status = "error";
    assistantMessage.tool_usage = context.toolUsage;
    if (Number.isFinite(Number(context.usedTokens)) && Number(context.usedTokens) > 0) {
      const currentTotal = Number(chat.total_tokens_used || 0);
      chat.total_tokens_used = Math.max(0, currentTotal) + Number(context.usedTokens);
      addDailyTokenUsage(Number(context.usedTokens));
    }
    chat.updated_at = errorTimestamp;

    if (state.activeChatId === chat.id) {
      state.lastRequestTokens = Number.isFinite(Number(context.usedTokens)) ? Number(context.usedTokens) : 0;
      renderActiveChat();
      syncUsedTokensToContext();
    }
    renderChatHistory();
    setStatus(hardErrorText, true);

    try {
      await persistChatsToSettings();
    } catch (persistError) {
      setStatus(`Response failed and save failed: ${persistError.message}`, true);
    }
  } finally {
    runtime.abortController = null;
  }
}

async function processChatQueue(chatId) {
  const runtime = getChatRuntime(chatId);
  if (!runtime || runtime.processing) {
    return;
  }

  runtime.processing = true;
  while (runtime.queue.length > 0) {
    const job = runtime.queue.shift();
    if (!job || runtime.cancelledRequestIds.has(job.requestId)) {
      continue;
    }

    const chat = state.chats.find((entry) => entry.id === chatId);
    if (!chat) {
      runtime.cancelledRequestIds.add(job.requestId);
      continue;
    }

    runtime.activeRequestId = job.requestId;
    await executeQueuedJob(chat, job, runtime);
    runtime.activeRequestId = "";

    try {
      await persistChatsToSettings();
    } catch (error) {
      setStatus(`Queued response save failed: ${error.message}`, true);
    }
  }

  runtime.processing = false;
  renderChatHistory();
  if (state.activeChatId === chatId) {
    updateComposerState();
  }
}

async function sendMessage(event) {
  event.preventDefault();

  if (state.isSwitching || state.isCompacting) {
    setStatus("Please wait for current gateway operation to finish.", true);
    return;
  }

  const message = chatInput.value.trim();
  if (!message) {
    setStatus("Please enter a message.", true);
    return;
  }

  let chat = getActiveChat();
  if (!chat) {
    chat = createChatEntry(message);
    state.chats.push(chat);
    state.activeChatId = chat.id;
    updateCurrentChatTitle();
    updateSystemTraceToggleLabel();
  }

  const snapshot = buildQueueSnapshot(chat);
  const requestId = createChatId();
  const timestamp = createTimestamp();
  chat.messages.push({
    role: "user",
    content: message,
    timestamp,
    system_type: "",
    tool_usage: [],
    request_id: "",
    status: "",
  });
  chat.messages.push({
    role: "assistant",
    content: "",
    timestamp,
    system_type: "",
    tool_usage: [],
    request_id: requestId,
    status: "queued",
  });
  chat.updated_at = timestamp;

  const runtime = getChatRuntime(chat.id);
  runtime.queue.push({
    requestId,
    queuedAt: timestamp,
    message,
    snapshot,
  });

  chatInput.value = "";
  if (state.activeChatId === chat.id) {
    renderActiveChat();
  }
  renderChatHistory();
  updateComposerState();
  setStatus("Queued.");

  try {
    await persistChatsToSettings();
  } catch (error) {
    setStatus(`Message queued, but save failed: ${error.message}`, true);
  }

  processChatQueue(chat.id);
  chatInput.focus();
}

async function triggerManualCompaction() {
  if (state.isCompacting || state.isSwitching) {
    return;
  }

  const activeChat = getActiveChat();
  if (!activeChat) {
    setStatus("No active chat to compact.", true);
    return;
  }

  const runtime = getChatRuntime(activeChat.id);
  if (runtime?.processing) {
    setStatus("Cannot compact while this chat is processing queued messages.", true);
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

async function stopActiveChatExecution() {
  const activeChat = getActiveChat();
  if (!activeChat) {
    return;
  }

  const runtime = getChatRuntime(activeChat.id);
  if (!runtime) {
    return;
  }

  runtime.queue.forEach((job) => {
    if (job && typeof job.requestId === "string") {
      runtime.cancelledRequestIds.add(job.requestId);
    }
  });
  runtime.queue = [];

  if (runtime.activeRequestId) {
    runtime.cancelledRequestIds.add(runtime.activeRequestId);
  }

  if (runtime.abortController instanceof AbortController) {
    runtime.abortController.abort();
  }

  const now = createTimestamp();
  activeChat.messages.forEach((message) => {
    if (message.role !== "assistant") {
      return;
    }
    if (message.status === "queued" || message.status === "processing") {
      message.status = "error";
      message.content = message.content ? `${message.content}\n\nExecution interrupted by user.` : "Execution interrupted by user.";
      message.timestamp = now;
    }
  });

  appendSystemTraceMessages(
    activeChat,
    [{ system_type: "tool_interrupt", content: "Execution interrupted by user." }],
    now,
    runtime.activeRequestId || "",
  );
  activeChat.updated_at = now;

  renderActiveChat();
  renderChatHistory();
  updateComposerState();
  setStatus("Execution stopped. Queued messages were cleared.", true);

  try {
    await persistChatsToSettings();
  } catch (error) {
    setStatus(`Execution stopped, but save failed: ${error.message}`, true);
  }
}

function ensureMcpConfig(mcpId) {
  if (!state.mcpConfigs[mcpId] || typeof state.mcpConfigs[mcpId] !== "object") {
    state.mcpConfigs[mcpId] = { enabled: false, params: {} };
  }

  if (!state.mcpConfigs[mcpId].params || typeof state.mcpConfigs[mcpId].params !== "object") {
    state.mcpConfigs[mcpId].params = {};
  }

  return state.mcpConfigs[mcpId];
}

function handleMcpInputChange(event) {
  const target = event.target;
  if (!(target instanceof HTMLInputElement)) {
    return;
  }

  const action = target.dataset.action;
  const mcpId = target.dataset.mcpId;
  if (!action || !mcpId) {
    return;
  }

  const config = ensureMcpConfig(mcpId);
  if (action === "toggle") {
    config.enabled = target.checked;
    return;
  }

  if (action === "param") {
    const fieldId = target.dataset.fieldId;
    if (!fieldId) {
      return;
    }
    config.params[fieldId] = target.value;
  }
}

async function handleMcpActionClick(event) {
  const target = event.target;
  if (!(target instanceof HTMLElement)) {
    return;
  }

  const button = target.closest("button[data-action][data-mcp-id]");
  if (!(button instanceof HTMLButtonElement)) {
    return;
  }

  const action = button.dataset.action;
  const mcpId = button.dataset.mcpId;
  if (!action || !mcpId) {
    return;
  }

  try {
    if (action === "save") {
      await persistMcpConfigsToSettings();
      setStatus("Tool settings saved.");
      return;
    }

    if (action === "ssh-key") {
      await fetchGitSshKey();
      setStatus("GitHub SSH public key copied to clipboard.");
      return;
    }

    if (action === "verify-ssh") {
      await verifyGitSshAccess();
      setStatus("GitHub SSH access verified.");
      return;
    }

    if (action === "verify") {
      await verifyMcpConfig(mcpId);
      setStatus("Tool verified.");
      return;
    }
  } catch (error) {
    setStatus(error.message, true);
  }
}

async function toggleSystemTraceVisibility() {
  const activeChat = getActiveChat();
  if (!activeChat) {
    return;
  }

  activeChat.collapse_system_trace = !Boolean(activeChat.collapse_system_trace);
  renderActiveChat();

  try {
    await persistChatsToSettings();
  } catch (error) {
    setStatus(`System trace toggle saved locally only: ${error.message}`, true);
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

if (stopButton instanceof HTMLButtonElement) {
  stopButton.addEventListener("click", stopActiveChatExecution);
}

if (systemTraceToggleButton instanceof HTMLButtonElement) {
  systemTraceToggleButton.addEventListener("click", toggleSystemTraceVisibility);
}

if (mcpList instanceof HTMLElement) {
  mcpList.addEventListener("input", handleMcpInputChange);
  mcpList.addEventListener("click", handleMcpActionClick);
}

chatHistoryList.addEventListener("click", (event) => {
  const target = event.target;
  if (!(target instanceof Node)) {
    return;
  }

  const actionButton = target instanceof HTMLElement ? target.closest("button[data-chat-id][data-action]") : null;
  if (actionButton instanceof HTMLButtonElement) {
    const chatId = actionButton.dataset.chatId;
    const action = actionButton.dataset.action;
    if (!chatId || !action) {
      return;
    }

    if (action === "delete") {
      deleteChat(chatId);
      return;
    }

    if (action === "edit") {
      editChatTitle(chatId);
      return;
    }

    if (action === "open") {
      if (chatId === state.activeChatId) {
        return;
      }
      activateChat(chatId);
      return;
    }
  }

  const chatCard = target instanceof HTMLElement ? target.closest(".chat-history-item[data-chat-id]") : null;
  if (!(chatCard instanceof HTMLElement)) {
    return;
  }

  const chatId = chatCard.dataset.chatId;
  if (!chatId || chatId === state.activeChatId) {
    return;
  }

  activateChat(chatId);
});

chatForm.addEventListener("submit", sendMessage);
window.addEventListener("load", loadGatewayMeta);
