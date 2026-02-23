/*
 * Gateway client: manages chat UI, queueing/stream handling, settings sync,
 * tool/integration panels, and header status indicators.
 */

const CHAT_TITLE_MAX_LENGTH = 24;
const EDITABLE_CHAT_TITLE_MAX_LENGTH = 24;
const CHAT_SYNC_INTERVAL_MS = 3000;
const INTEGRATION_STATUS_SYNC_INTERVAL_MS = 3000;
const RUNTIME_CONTEXT_SYSTEM_TYPE = "runtime_context_seed";

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
const telegramStatusNode = document.getElementById("telegram-status");
const headerProviderSelect = document.getElementById("header-provider-select");
const headerModelSelect = document.getElementById("header-model-select");
const compactButton = document.getElementById("compact-btn");
const currentChatTitleNode = document.getElementById("current-chat-title");
const chatHistoryList = document.getElementById("chat-history-list");
const newChatButton = document.getElementById("new-chat-btn");
const mcpList = document.getElementById("mcp-list");
const integrationList = document.getElementById("integration-list");
const memoryManagementButton = document.getElementById("memory-management-btn");
const memoryModal = document.getElementById("memory-modal");
const memoryModalBackdrop = document.getElementById("memory-modal-backdrop");
const memoryModalCloseButton = document.getElementById("memory-modal-close");
const memoryTokenTotalNode = document.getElementById("memory-token-total");
const coreMemoryTokenCountNode = document.getElementById("core-memory-token-count");
const normalMemoryTokenCountNode = document.getElementById("normal-memory-token-count");
const coreMemorySearchInput = document.getElementById("core-memory-search");
const normalMemorySearchInput = document.getElementById("normal-memory-search");
const coreMemoryInput = document.getElementById("core-memory-input");
const normalMemoryInput = document.getElementById("normal-memory-input");
const addCoreMemoryButton = document.getElementById("add-core-memory-btn");
const addNormalMemoryButton = document.getElementById("add-normal-memory-btn");
const coreMemoryList = document.getElementById("core-memory-list");
const normalMemoryList = document.getElementById("normal-memory-list");
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
  integrations: [],
  integrationConfigs: {},
  chats: [],
  activeChatId: "",
  chatRuntimes: {},
  isCompacting: false,
  isSwitching: false,
  suppressSwitcherEvents: false,
  toastTimerId: null,
  compactionBubble: null,
  chatSyncTimerId: null,
  chatSyncInFlight: false,
  integrationStatusSyncTimerId: null,
  integrationStatusSyncInFlight: false,
  lastChatStateSignature: "",
  telegramEnabled: false,
  telegramTokenConfigured: false,
  telegramOwnerUserId: "",
  coreMemories: [],
  normalMemories: [],
  coreMemorySearchTerm: "",
  normalMemorySearchTerm: "",
  coreMemoryEditingIndex: -1,
  normalMemoryEditingIndex: -1,
  coreMemoryEditDraft: "",
  normalMemoryEditDraft: "",
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

function isAnyChatBusy() {
  return Object.values(state.chatRuntimes).some((runtime) => {
    if (!runtime || typeof runtime !== "object") {
      return false;
    }
    return Boolean(runtime.processing) || (Array.isArray(runtime.queue) && runtime.queue.length > 0);
  });
}

function setStatus(message, isError = false) {
  statusNode.textContent = message;
  statusNode.className = isError ? "error" : "ok";
}

function normalizeErrorMessage(error, fallback = "Request failed.") {
  if (error instanceof DOMException && error.name === "AbortError") {
    return "Request was aborted.";
  }
  if (typeof error?.message === "string" && error.message.trim()) {
    return error.message.trim();
  }
  return fallback;
}

async function buildHttpErrorDetail(response, fallback = "Request failed.") {
  const statusPart = Number.isFinite(Number(response?.status))
    ? `HTTP ${response.status}${response.statusText ? ` ${response.statusText}` : ""}`
    : "HTTP error";

  let rawBody = "";
  try {
    rawBody = await response.text();
  } catch (error) {
    rawBody = "";
  }

  let detail = "";
  if (rawBody.trim()) {
    try {
      const parsed = JSON.parse(rawBody);
      if (typeof parsed?.detail === "string" && parsed.detail.trim()) {
        detail = parsed.detail.trim();
      } else if (typeof parsed?.error === "string" && parsed.error.trim()) {
        detail = parsed.error.trim();
      } else if (typeof parsed?.message === "string" && parsed.message.trim()) {
        detail = parsed.message.trim();
      } else {
        detail = rawBody.trim();
      }
    } catch (error) {
      detail = rawBody.trim();
    }
  }

  const compactDetail = detail.length > 400 ? `${detail.slice(0, 400)}...` : detail;
  if (compactDetail) {
    return `${fallback} ${statusPart}. ${compactDetail}`;
  }
  return `${fallback} ${statusPart}.`;
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

function normalizeIncomingMemories(rawMemories) {
  if (!Array.isArray(rawMemories)) {
    return [];
  }

  return rawMemories
    .filter((memory) => memory && typeof memory === "object")
    .map((memory) => {
      const content = typeof memory.content === "string" ? memory.content.trim().slice(0, 200) : "";
      const createdAt = typeof memory.created_at === "string" ? memory.created_at.trim() : "";
      return { content, created_at: createdAt };
    })
    .filter((memory) => memory.content.length > 0);
}

function estimateTextTokens(text) {
  const normalized = typeof text === "string" ? text.trim() : "";
  if (!normalized) {
    return 0;
  }
  return Math.max(1, Math.ceil(normalized.length / 4));
}

function estimateMemoryTokens(memories) {
  if (!Array.isArray(memories)) {
    return 0;
  }
  return memories.reduce((sum, memory) => sum + estimateTextTokens(memory?.content ?? ""), 0);
}

function formatMemoryTimestamp(rawValue) {
  const value = typeof rawValue === "string" ? rawValue.trim() : "";
  if (!value) {
    return "Unknown time";
  }

  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }

  const year = parsed.getFullYear();
  const month = String(parsed.getMonth() + 1).padStart(2, "0");
  const day = String(parsed.getDate()).padStart(2, "0");
  const hours = String(parsed.getHours()).padStart(2, "0");
  const minutes = String(parsed.getMinutes()).padStart(2, "0");
  return `${year}-${month}-${day} ${hours}:${minutes}`;
}

function getFilteredMemories(memories, searchTerm) {
  const normalizedSearch = String(searchTerm || "").trim().toLowerCase();
  return memories
    .map((memory, index) => ({ memory, index }))
    .filter(({ memory }) => {
      if (!normalizedSearch) {
        return true;
      }
      return memory.content.toLowerCase().includes(normalizedSearch);
    });
}

function renderMemoryList(node, memories, searchTerm, type) {
  if (!(node instanceof HTMLElement)) {
    return;
  }

  node.innerHTML = "";
  const filtered = getFilteredMemories(memories, searchTerm);
  if (filtered.length === 0) {
    const emptyNode = document.createElement("p");
    emptyNode.className = "memory-modal-empty";
    emptyNode.textContent = searchTerm ? "No matching memories." : "No memories yet.";
    node.appendChild(emptyNode);
    return;
  }

  filtered.forEach(({ memory, index }) => {
    const card = document.createElement("article");
    card.className = "memory-modal-card-item";

    const timeNode = document.createElement("span");
    timeNode.className = "memory-modal-card-time";
    timeNode.textContent = formatMemoryTimestamp(memory.created_at);
    card.appendChild(timeNode);

    const deleteButton = document.createElement("button");
    deleteButton.type = "button";
    deleteButton.className = "memory-card-delete-btn";
    deleteButton.dataset.memoryType = type;
    deleteButton.dataset.memoryIndex = String(index);
    deleteButton.dataset.memoryAction = "delete";
    deleteButton.textContent = "x";
    deleteButton.setAttribute("aria-label", "Delete memory");
    card.appendChild(deleteButton);

    const editingIndex = type === "core" ? state.coreMemoryEditingIndex : state.normalMemoryEditingIndex;
    const isEditing = editingIndex === index;

    if (isEditing) {
      const draft = type === "core" ? state.coreMemoryEditDraft : state.normalMemoryEditDraft;
      const editInput = document.createElement("textarea");
      editInput.className = "memory-inline-editor";
      editInput.maxLength = 200;
      editInput.rows = 3;
      editInput.value = draft;
      editInput.dataset.memoryType = type;
      editInput.dataset.memoryIndex = String(index);
      editInput.dataset.memoryAction = "draft";

      const actions = document.createElement("div");
      actions.className = "memory-inline-actions";

      const saveButton = document.createElement("button");
      saveButton.type = "button";
      saveButton.className = "memory-inline-btn";
      saveButton.dataset.memoryType = type;
      saveButton.dataset.memoryIndex = String(index);
      saveButton.dataset.memoryAction = "save";
      saveButton.textContent = "Save";

      const cancelButton = document.createElement("button");
      cancelButton.type = "button";
      cancelButton.className = "memory-inline-btn memory-inline-btn-secondary";
      cancelButton.dataset.memoryType = type;
      cancelButton.dataset.memoryIndex = String(index);
      cancelButton.dataset.memoryAction = "cancel";
      cancelButton.textContent = "Cancel";

      actions.appendChild(saveButton);
      actions.appendChild(cancelButton);
      card.appendChild(editInput);
      card.appendChild(actions);
    } else {
      const contentNode = document.createElement("p");
      contentNode.className = "memory-modal-card-content";
      contentNode.textContent = memory.content;
      contentNode.dataset.memoryType = type;
      contentNode.dataset.memoryIndex = String(index);
      contentNode.dataset.memoryAction = "edit";
      contentNode.setAttribute("role", "button");
      contentNode.setAttribute("tabindex", "0");
      card.appendChild(contentNode);

      const editHint = document.createElement("p");
      editHint.className = "memory-edit-hint";
      editHint.textContent = "Click to edit";
      card.appendChild(editHint);
    }

    node.appendChild(card);
  });
}

function renderMemoryTokenCounts() {
  const coreTokens = estimateMemoryTokens(state.coreMemories);
  const normalTokens = estimateMemoryTokens(state.normalMemories);
  const totalTokens = coreTokens + normalTokens;

  if (coreMemoryTokenCountNode instanceof HTMLElement) {
    coreMemoryTokenCountNode.textContent = `Estimated tokens: ${formatNumber(coreTokens)}`;
  }
  if (normalMemoryTokenCountNode instanceof HTMLElement) {
    normalMemoryTokenCountNode.textContent = `Estimated tokens: ${formatNumber(normalTokens)}`;
  }
  if (memoryTokenTotalNode instanceof HTMLElement) {
    memoryTokenTotalNode.textContent = `Total estimated memory tokens: ${formatNumber(totalTokens)}`;
  }
}

function renderMemoryManagement() {
  renderMemoryTokenCounts();
  renderMemoryList(coreMemoryList, state.coreMemories, state.coreMemorySearchTerm, "core");
  renderMemoryList(normalMemoryList, state.normalMemories, state.normalMemorySearchTerm, "normal");
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

function buildRuntimeContextSeed() {
  const botName = typeof state.settings?.bot_name === "string" ? state.settings.bot_name.trim() : "Krill";
  const behavior = typeof state.settings?.system_prompt === "string" ? state.settings.system_prompt.trim() : "";
  const coreMemories = Array.isArray(state.coreMemories) ? state.coreMemories : [];

  let seed = (
    `You are Krill assistant named '${botName}'. `
    + `This is the system prompt your user provided: ${behavior}`
  );

  const memoryLines = coreMemories
    .map((memory) => (typeof memory?.content === "string" ? memory.content.trim() : ""))
    .filter((content) => Boolean(content))
    .map((content) => `- ${content}`);

  if (memoryLines.length > 0) {
    seed = (
      `${seed}\n\n`
      + "Core memories (background context from the user):\n"
      + "Use these memories subtly and only when they are relevant and helpful. "
      + "Do not repeatedly mention or announce these memories. "
      + "Keep the response natural, personal, and context-aware.\n"
      + memoryLines.join("\n")
    );
  }

  return seed;
}

function ensureRuntimeContextSeed(chat) {
  if (!chat || !Array.isArray(chat.messages)) {
    return;
  }

  const hasSeed = chat.messages.some(
    (message) =>
      message
      && message.role === "system"
      && typeof message.system_type === "string"
      && message.system_type === RUNTIME_CONTEXT_SYSTEM_TYPE,
  );
  if (hasSeed) {
    return;
  }

  const timestamp = createTimestamp();
  chat.messages.unshift({
    role: "system",
    content: buildRuntimeContextSeed(),
    timestamp,
    system_type: RUNTIME_CONTEXT_SYSTEM_TYPE,
    tool_usage: [],
    request_id: "",
    status: "",
  });
  chat.updated_at = timestamp;
}

function toApiChatHistory(messages) {
  return messages
    .filter((turn) => turn && (turn.role === "user" || turn.role === "assistant" || turn.role === "system"))
    .filter((turn) => typeof turn.content === "string" && turn.content.trim())
    .filter((turn) => {
      if (turn.role !== "system") {
        return true;
      }
      return turn.system_type === RUNTIME_CONTEXT_SYSTEM_TYPE;
    })
    .map((turn) => ({ role: turn.role, content: turn.content }));
}

function toApiCompactionHistory(messages) {
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

    if (turn.role === "system" && activeChat.collapse_system_trace && turn.system_type !== "memory_compaction") {
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
  persistChatsToSettings().catch((error) => {
    setStatus(`Active chat changed locally, but save failed: ${error.message}`, true);
  });
}

function startNewChat() {
  if (state.isSwitching || state.isCompacting) {
    return;
  }

  const chat = createChatEntry("");
  chat.title = "New chat";
  state.chats.push(chat);
  state.activeChatId = chat.id;
  state.lastRequestTokens = 0;
  renderChatHistory();
  renderActiveChat();
  updateTokenCounter(0, state.modelTokenLimit);
  setStatus("New chat ready. Send a first message to create it.");
  updateComposerState();
  persistChatsToSettings().catch((error) => {
    setStatus(`New chat context set locally, but save failed: ${error.message}`, true);
  });
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

function updateTelegramStatusLabel() {
  if (!(telegramStatusNode instanceof HTMLElement)) {
    return;
  }

  if (!state.telegramEnabled) {
    telegramStatusNode.textContent = "Telegram: disabled";
    return;
  }

  if (!state.telegramTokenConfigured) {
    telegramStatusNode.textContent = "Telegram: enabled, token missing";
    return;
  }

  if (!state.telegramOwnerUserId) {
    telegramStatusNode.textContent = "Telegram: waiting for first owner message";
    return;
  }

  telegramStatusNode.textContent = "Telegram: connected";
}

function syncTelegramFlagsFromIntegrationConfig() {
  const telegramConfig = getIntegrationConfig("telegram");
  state.telegramEnabled = Boolean(telegramConfig.enabled);
  state.telegramTokenConfigured = Boolean(
    typeof telegramConfig.params?.bot_token === "string" && telegramConfig.params.bot_token.trim(),
  );
}

function applyIntegrationStatusPayload(payload) {
  const statuses = payload?.statuses;
  const telegramStatus = statuses && typeof statuses === "object" ? statuses.telegram : null;
  if (!telegramStatus || typeof telegramStatus !== "object") {
    return;
  }

  state.telegramEnabled = Boolean(telegramStatus.enabled);
  state.telegramTokenConfigured = Boolean(telegramStatus.token_configured);
  state.telegramOwnerUserId = typeof telegramStatus.owner_user_id === "string" ? telegramStatus.owner_user_id : "";
  updateTelegramStatusLabel();
}

async function syncIntegrationStatus() {
  if (state.integrationStatusSyncInFlight) {
    return;
  }

  state.integrationStatusSyncInFlight = true;
  try {
    const response = await fetch("/api/integrations/status", { cache: "no-store" });
    if (!response.ok) {
      return;
    }
    const payload = await response.json();
    applyIntegrationStatusPayload(payload);
  } catch (error) {
    // Keep sync best-effort and silent.
  } finally {
    state.integrationStatusSyncInFlight = false;
  }
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
  nextSettings.active_chat_id = state.activeChatId;
  nextSettings.mcp_configs = state.mcpConfigs;
  nextSettings.integration_configs = state.integrationConfigs;
  nextSettings.daily_token_usage = state.dailyTokenUsage;
  const persisted = await persistSettings(nextSettings);
  state.settings = persisted;
  if (typeof persisted.active_chat_id === "string") {
    state.activeChatId = persisted.active_chat_id;
  }
  state.dailyTokenUsage = normalizeDailyTokenUsage(persisted.daily_token_usage);
  refreshLocalChatStateSignature();
  updateDailyTokenUsageLabel();
}

async function persistMemoriesToSettings() {
  if (!state.settings) {
    return;
  }

  const nextSettings = JSON.parse(JSON.stringify(state.settings));
  nextSettings.core_memories = state.coreMemories;
  nextSettings.normal_memories = state.normalMemories;
  nextSettings.chats = state.chats;
  nextSettings.active_chat_id = state.activeChatId;
  nextSettings.daily_token_usage = state.dailyTokenUsage;

  const persisted = await persistSettings(nextSettings);
  state.settings = persisted;
  state.coreMemories = normalizeIncomingMemories(persisted.core_memories);
  state.normalMemories = normalizeIncomingMemories(persisted.normal_memories);
}

function openMemoryManagementModal() {
  if (!(memoryModal instanceof HTMLElement)) {
    return;
  }

  if (coreMemorySearchInput instanceof HTMLInputElement) {
    coreMemorySearchInput.value = "";
    state.coreMemorySearchTerm = "";
  }
  if (normalMemorySearchInput instanceof HTMLInputElement) {
    normalMemorySearchInput.value = "";
    state.normalMemorySearchTerm = "";
  }
  state.coreMemoryEditingIndex = -1;
  state.normalMemoryEditingIndex = -1;
  state.coreMemoryEditDraft = "";
  state.normalMemoryEditDraft = "";

  renderMemoryManagement();
  memoryModal.classList.remove("hidden");
  document.body.style.overflow = "hidden";

  if (coreMemorySearchInput instanceof HTMLInputElement) {
    coreMemorySearchInput.focus();
  }
}

function closeMemoryManagementModal() {
  if (!(memoryModal instanceof HTMLElement)) {
    return;
  }

  memoryModal.classList.add("hidden");
  document.body.style.overflow = "";
}

async function addMemory(type) {
  const isCore = type === "core";
  const inputNode = isCore ? coreMemoryInput : normalMemoryInput;
  if (!(inputNode instanceof HTMLInputElement)) {
    return;
  }

  const text = inputNode.value.trim();
  if (!text) {
    setStatus(`Please enter a ${isCore ? "core" : "normal"} memory.`, true);
    return;
  }

  if (text.length > 200) {
    setStatus("Memory must be at most 200 characters.", true);
    return;
  }

  const targetList = isCore ? state.coreMemories : state.normalMemories;
  targetList.push({ content: text, created_at: createTimestamp() });
  inputNode.value = "";
  renderMemoryManagement();

  try {
    await persistMemoriesToSettings();
    state.coreMemoryEditingIndex = -1;
    state.normalMemoryEditingIndex = -1;
    renderMemoryManagement();
    setStatus(`${isCore ? "Core" : "Normal"} memory added.`);
  } catch (error) {
    targetList.pop();
    renderMemoryManagement();
    setStatus(`Memory add failed: ${error.message}`, true);
  }
}

async function deleteMemory(type, indexValue) {
  const parsedIndex = Number.parseInt(String(indexValue), 10);
  if (!Number.isFinite(parsedIndex) || parsedIndex < 0) {
    return;
  }

  const targetList = type === "core" ? state.coreMemories : state.normalMemories;
  if (parsedIndex >= targetList.length) {
    return;
  }

  const [removed] = targetList.splice(parsedIndex, 1);
  renderMemoryManagement();

  try {
    await persistMemoriesToSettings();
    state.coreMemoryEditingIndex = -1;
    state.normalMemoryEditingIndex = -1;
    renderMemoryManagement();
    setStatus(`${type === "core" ? "Core" : "Normal"} memory deleted.`);
  } catch (error) {
    if (removed) {
      targetList.splice(parsedIndex, 0, removed);
    }
    renderMemoryManagement();
    setStatus(`Memory delete failed: ${error.message}`, true);
  }
}

function startMemoryInlineEdit(type, indexValue) {
  const parsedIndex = Number.parseInt(String(indexValue), 10);
  if (!Number.isFinite(parsedIndex) || parsedIndex < 0) {
    return;
  }

  const targetList = type === "core" ? state.coreMemories : state.normalMemories;
  if (parsedIndex >= targetList.length) {
    return;
  }

  const content = targetList[parsedIndex]?.content ?? "";
  if (type === "core") {
    state.coreMemoryEditingIndex = parsedIndex;
    state.coreMemoryEditDraft = content;
    state.normalMemoryEditingIndex = -1;
    state.normalMemoryEditDraft = "";
  } else {
    state.normalMemoryEditingIndex = parsedIndex;
    state.normalMemoryEditDraft = content;
    state.coreMemoryEditingIndex = -1;
    state.coreMemoryEditDraft = "";
  }

  renderMemoryManagement();
}

function updateMemoryEditDraft(type, nextValue) {
  const normalized = String(nextValue || "").slice(0, 200);
  if (type === "core") {
    state.coreMemoryEditDraft = normalized;
  } else {
    state.normalMemoryEditDraft = normalized;
  }
}

function cancelMemoryInlineEdit(type) {
  if (type === "core") {
    state.coreMemoryEditingIndex = -1;
    state.coreMemoryEditDraft = "";
  } else {
    state.normalMemoryEditingIndex = -1;
    state.normalMemoryEditDraft = "";
  }
  renderMemoryManagement();
}

async function saveMemoryInlineEdit(type, indexValue) {
  const parsedIndex = Number.parseInt(String(indexValue), 10);
  if (!Number.isFinite(parsedIndex) || parsedIndex < 0) {
    return;
  }

  const targetList = type === "core" ? state.coreMemories : state.normalMemories;
  if (parsedIndex >= targetList.length) {
    return;
  }

  const draft = type === "core" ? state.coreMemoryEditDraft : state.normalMemoryEditDraft;
  const updatedText = String(draft || "").trim();
  if (!updatedText) {
    setStatus("Memory cannot be empty.", true);
    return;
  }

  const previousText = targetList[parsedIndex].content;
  targetList[parsedIndex].content = updatedText;
  renderMemoryManagement();

  try {
    await persistMemoriesToSettings();
    cancelMemoryInlineEdit(type);
    setStatus(`${type === "core" ? "Core" : "Normal"} memory updated.`);
  } catch (error) {
    targetList[parsedIndex].content = previousText;
    renderMemoryManagement();
    setStatus(`Memory update failed: ${error.message}`, true);
  }
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
  nextSettings.integration_configs = state.integrationConfigs;
  nextSettings.chats = state.chats;
  nextSettings.active_chat_id = state.activeChatId;
  nextSettings.daily_token_usage = state.dailyTokenUsage;
  const persisted = await persistSettings(nextSettings);
  state.settings = persisted;
  if (typeof persisted.active_chat_id === "string") {
    state.activeChatId = persisted.active_chat_id;
  }
  state.mcpConfigs = normalizeIncomingMcpConfigs(persisted.mcp_configs);
  state.integrationConfigs = normalizeIncomingMcpConfigs(persisted.integration_configs);
  syncTelegramFlagsFromIntegrationConfig();
  state.dailyTokenUsage = normalizeDailyTokenUsage(persisted.daily_token_usage);
  refreshLocalChatStateSignature();
  updateDailyTokenUsageLabel();
  updateTelegramStatusLabel();
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

async function verifyIntegrationConfig(integrationId) {
  const config = getIntegrationConfig(integrationId);
  const response = await fetch("/api/integrations/verify", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      integration_id: integrationId,
      params: config.params,
    }),
  });

  if (!response.ok) {
    let detail = "Integration verification failed.";
    try {
      const payload = await response.json();
      if (typeof payload.detail === "string" && payload.detail) {
        detail = payload.detail;
      }
    } catch (error) {
      detail = "Integration verification failed.";
    }
    throw new Error(detail);
  }

  return response.json();
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

function renderConfigPanel(container, items, getConfig, options) {
  if (!(container instanceof HTMLElement)) {
    return;
  }

  container.innerHTML = "";
  if (!Array.isArray(items) || items.length === 0) {
    const emptyNode = document.createElement("p");
    emptyNode.className = "chat-history-empty";
    emptyNode.textContent = options.emptyLabel;
    container.appendChild(emptyNode);
    return;
  }

  items.forEach((item) => {
    const card = document.createElement("div");
    card.className = "mcp-card";
    card.dataset.configKind = options.kind;
    card.dataset.configId = item.id;

    const config = getConfig(item.id);

    const titleRow = document.createElement("div");
    titleRow.className = "mcp-title-row";

    const title = document.createElement("p");
    title.className = "mcp-title";
    title.textContent = item.label;

    const toggleLabel = document.createElement("label");
    toggleLabel.className = "mcp-toggle";

    const toggleInput = document.createElement("input");
    toggleInput.type = "checkbox";
    toggleInput.checked = Boolean(config.enabled);
    toggleInput.dataset.action = "toggle";
    toggleInput.dataset.configKind = options.kind;
    toggleInput.dataset.configId = item.id;

    const toggleText = document.createElement("span");
    toggleText.textContent = "Enabled";

    toggleLabel.appendChild(toggleInput);
    toggleLabel.appendChild(toggleText);

    titleRow.appendChild(title);
    titleRow.appendChild(toggleLabel);

    const description = document.createElement("p");
    description.className = "mcp-description";
    description.textContent = typeof item.description === "string" ? item.description : "";

    card.appendChild(titleRow);
    card.appendChild(description);

    const fields = Array.isArray(item.config_fields) ? item.config_fields : [];
    fields.forEach((field) => {
      const fieldId = typeof field.id === "string" ? field.id : "";
      if (!fieldId) {
        return;
      }

      const fieldWrapper = document.createElement("div");
      fieldWrapper.className = "mcp-field";

      const fieldLabel = document.createElement("label");
      fieldLabel.textContent = field.label || fieldId;
      fieldLabel.setAttribute("for", `${options.kind}-${item.id}-${fieldId}`);

      const fieldInput = document.createElement("input");
      fieldInput.id = `${options.kind}-${item.id}-${fieldId}`;
      fieldInput.type = field.type === "password" ? "password" : "text";
      fieldInput.value = typeof config.params?.[fieldId] === "string" ? config.params[fieldId] : "";
      fieldInput.placeholder = typeof field.placeholder === "string" ? field.placeholder : "";
      fieldInput.dataset.action = "param";
      fieldInput.dataset.configKind = options.kind;
      fieldInput.dataset.configId = item.id;
      fieldInput.dataset.fieldId = fieldId;

      fieldWrapper.appendChild(fieldLabel);
      fieldWrapper.appendChild(fieldInput);
      card.appendChild(fieldWrapper);
    });

    const actions = document.createElement("div");
    actions.className = "mcp-card-actions";

    if (options.kind === "mcp" && item.id === "git_ops") {
      const sshKeyButton = document.createElement("button");
      sshKeyButton.type = "button";
      sshKeyButton.className = "mcp-link-btn";
      sshKeyButton.textContent = "SSH key";
      sshKeyButton.dataset.action = "ssh-key";
      sshKeyButton.dataset.configKind = options.kind;
      sshKeyButton.dataset.configId = item.id;

      const verifyButton = document.createElement("button");
      verifyButton.type = "button";
      verifyButton.className = "mcp-link-btn";
      verifyButton.textContent = "Verify";
      verifyButton.dataset.action = "verify-ssh";
      verifyButton.dataset.configKind = options.kind;
      verifyButton.dataset.configId = item.id;

      actions.appendChild(sshKeyButton);
      actions.appendChild(verifyButton);
      card.appendChild(actions);
    } else if (!(options.kind === "mcp" && item.id === "local_files")) {
      const saveButton = document.createElement("button");
      saveButton.type = "button";
      saveButton.className = "mcp-link-btn";
      saveButton.textContent = "Save";
      saveButton.dataset.action = "save";
      saveButton.dataset.configKind = options.kind;
      saveButton.dataset.configId = item.id;

      const verifyButton = document.createElement("button");
      verifyButton.type = "button";
      verifyButton.className = "mcp-link-btn";
      verifyButton.textContent = "Verify";
      verifyButton.dataset.action = "verify";
      verifyButton.dataset.configKind = options.kind;
      verifyButton.dataset.configId = item.id;

      actions.appendChild(saveButton);
      actions.appendChild(verifyButton);
      card.appendChild(actions);
    }

    container.appendChild(card);
  });
}

function renderMcpPanel() {
  renderConfigPanel(mcpList, state.mcps, getMcpConfig, {
    kind: "mcp",
    emptyLabel: "No tools available.",
  });
}

function renderIntegrationPanel() {
  renderConfigPanel(integrationList, state.integrations, getIntegrationConfig, {
    kind: "integration",
    emptyLabel: "No integrations available.",
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
        history: toApiCompactionHistory(chat.messages),
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
    chat.memory_block = typeof payload.memory_block === "string" ? payload.memory_block : chat.memory_block;
    const contextTimestamp = createTimestamp();
    const runtimeContextMessage = {
      role: "system",
      content: buildRuntimeContextSeed(),
      timestamp: contextTimestamp,
      system_type: RUNTIME_CONTEXT_SYSTEM_TYPE,
      tool_usage: [],
      request_id: "",
      status: "",
    };
    if (chat.memory_block.trim()) {
      const timestamp = createTimestamp();
      chat.messages = [
        runtimeContextMessage,
        {
          role: "system",
          content: `Compacted memory\n\n${chat.memory_block.trim()}`,
          timestamp,
          system_type: "memory_compaction",
          tool_usage: [],
          request_id: "",
          status: "",
        },
      ];
    } else {
      chat.messages = [runtimeContextMessage];
    }
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
    nextSettings.active_chat_id = state.activeChatId;
    nextSettings.mcp_configs = state.mcpConfigs;
    nextSettings.integration_configs = state.integrationConfigs;
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
    const [providersResponse, settingsResponse, mcpsResponse, integrationsResponse] = await Promise.all([
      fetch("/api/providers"),
      fetch("/api/settings"),
      fetch("/api/mcps"),
      fetch("/api/integrations"),
    ]);

    if (!providersResponse.ok || !settingsResponse.ok || !mcpsResponse.ok || !integrationsResponse.ok) {
      throw new Error("Failed to load gateway metadata.");
    }

    const providers = await providersResponse.json();
    const settings = await settingsResponse.json();
    const mcps = await mcpsResponse.json();
    const integrations = await integrationsResponse.json();

    const activeProvider = providers.find((provider) => provider.id === settings.active_provider_id);
    const activeConfig = settings.provider_configs?.[settings.active_provider_id];

    state.providers = providers;
    state.settings = settings;
    state.activeProviderId = settings.active_provider_id ?? "";
    state.activeModelId = activeConfig?.model ?? "";
    state.botName = typeof settings?.bot_name === "string" ? settings.bot_name.trim() : "";
    state.coreMemories = normalizeIncomingMemories(settings.core_memories);
    state.normalMemories = normalizeIncomingMemories(settings.normal_memories);
    state.chats = normalizeIncomingChats(settings.chats);
    state.dailyTokenUsage = normalizeDailyTokenUsage(settings.daily_token_usage);
    state.mcps = Array.isArray(mcps) ? mcps : [];
    state.integrations = Array.isArray(integrations) ? integrations : [];
    state.mcpConfigs = normalizeIncomingMcpConfigs(settings.mcp_configs);
    state.integrationConfigs = normalizeIncomingMcpConfigs(settings.integration_configs);
    syncTelegramFlagsFromIntegrationConfig();
    state.telegramOwnerUserId = typeof settings?.telegram_state?.owner_user_id === "string"
      ? settings.telegram_state.owner_user_id
      : "";

    state.providerLabel = activeProvider?.label ?? settings.active_provider_id ?? "";
    state.modelLabel = activeProvider?.models?.find((model) => model.id === activeConfig?.model)?.label ?? activeConfig?.model ?? "";
    state.modelTokenLimit = getModelTokenLimit(state.activeProviderId, state.activeModelId);

    const sortedChats = sortChatsByLatestMessage(state.chats);
    const persistedActiveChatId = typeof settings.active_chat_id === "string" ? settings.active_chat_id : "";
    state.activeChatId = state.chats.some((chat) => chat.id === persistedActiveChatId)
      ? persistedActiveChatId
      : (sortedChats[0]?.id ?? "");

    syncSwitcherControls();
    updateMetaIndicators();
    updateAssistantHeader(settings);
    renderChatHistory();
    renderActiveChat();
    renderMcpPanel();
    renderIntegrationPanel();
    syncUsedTokensToContext();
    updateDailyTokenUsageLabel();
    updateTelegramStatusLabel();
    refreshLocalChatStateSignature();
    startChatStateSync();
    startIntegrationStatusSync();
    syncIntegrationStatus();
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
    renderIntegrationPanel();
    updateTokenCounter(0, 0);
    updateDailyTokenUsageLabel();
    updateTelegramStatusLabel();
    startChatStateSync();
    startIntegrationStatusSync();
    updateComposerState();
    setStatus(error.message, true);
  }
}

function buildChatStateSignature(payload) {
  const chats = Array.isArray(payload?.chats) ? payload.chats : [];
  const activeChatId = typeof payload?.active_chat_id === "string" ? payload.active_chat_id : "";
  const dailyTokenUsage = Array.isArray(payload?.daily_token_usage) ? payload.daily_token_usage : [];
  return JSON.stringify({ chats, activeChatId, dailyTokenUsage });
}

function refreshLocalChatStateSignature() {
  state.lastChatStateSignature = buildChatStateSignature({
    chats: state.chats,
    active_chat_id: state.activeChatId,
    daily_token_usage: state.dailyTokenUsage,
  });
}

function applyRemoteChatState(payload) {
  const incomingChats = normalizeIncomingChats(payload?.chats);
  const incomingActiveChatId = typeof payload?.active_chat_id === "string" ? payload.active_chat_id : "";
  const incomingDailyUsage = normalizeDailyTokenUsage(payload?.daily_token_usage);

  state.chats = incomingChats;
  state.dailyTokenUsage = incomingDailyUsage;
  updateDailyTokenUsageLabel();

  if (state.chats.some((chat) => chat.id === incomingActiveChatId)) {
    state.activeChatId = incomingActiveChatId;
  } else {
    const sorted = sortChatsByLatestMessage(state.chats);
    state.activeChatId = sorted[0]?.id ?? "";
  }

  renderChatHistory();
  renderActiveChat();
  syncUsedTokensToContext();
  updateComposerState();
}

async function syncRemoteChatState() {
  if (state.chatSyncInFlight || state.isCompacting || state.isSwitching) {
    return;
  }

  state.chatSyncInFlight = true;
  try {
    const response = await fetch("/api/chat/state", { cache: "no-store" });
    if (!response.ok) {
      return;
    }
    const payload = await response.json();
    if (isAnyChatBusy()) {
      return;
    }

    const signature = buildChatStateSignature(payload);
    if (signature === state.lastChatStateSignature) {
      return;
    }

    state.lastChatStateSignature = signature;
    applyRemoteChatState(payload);
  } catch (error) {
    // Keep sync best-effort and silent.
  } finally {
    state.chatSyncInFlight = false;
  }
}

function startChatStateSync() {
  if (state.chatSyncTimerId) {
    window.clearInterval(state.chatSyncTimerId);
  }
  state.chatSyncTimerId = window.setInterval(syncRemoteChatState, CHAT_SYNC_INTERVAL_MS);
}

function startIntegrationStatusSync() {
  if (state.integrationStatusSyncTimerId) {
    window.clearInterval(state.integrationStatusSyncTimerId);
  }
  state.integrationStatusSyncTimerId = window.setInterval(syncIntegrationStatus, INTEGRATION_STATUS_SYNC_INTERVAL_MS);
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
    const preview = data.length > 160 ? `${data.slice(0, 160)}...` : data;
    return { done: false, hasError: true, errorMessage: `Invalid stream payload: ${preview}` };
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
    history: toApiChatHistory(chat.messages),
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

    if (!response.ok) {
      const detail = await buildHttpErrorDetail(response, "Chat request failed.");
      throw new Error(detail);
    }

    if (!response.body) {
      throw new Error("Chat request failed. HTTP 200 but response body stream was empty.");
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

    const hardErrorText = normalizeErrorMessage(error, "Hard error.");
    console.error("Gateway chat request failed", {
      chatId: chat.id,
      requestId: job.requestId,
      providerId: job.snapshot.providerId,
      model: job.snapshot.model,
      messagePreview: typeof job.message === "string" ? job.message.slice(0, 160) : "",
      error: hardErrorText,
    });
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
  try {
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
  } finally {
    runtime.processing = false;
    runtime.activeRequestId = "";
    renderChatHistory();
    if (state.activeChatId === chatId) {
      updateComposerState();
    }
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
  } else if ((!Array.isArray(chat.messages) || chat.messages.length === 0) && normalizeChatTitle(chat.title).toLowerCase() === "new chat") {
    chat.title = deriveChatTitle(message);
  }

  ensureRuntimeContextSeed(chat);
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

  processChatQueue(chat.id);

  try {
    await persistChatsToSettings();
  } catch (error) {
    setStatus(`Message queued, but save failed: ${error.message}`, true);
  }

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

function ensureIntegrationConfig(integrationId) {
  if (!state.integrationConfigs[integrationId] || typeof state.integrationConfigs[integrationId] !== "object") {
    state.integrationConfigs[integrationId] = { enabled: false, params: {} };
  }

  if (!state.integrationConfigs[integrationId].params || typeof state.integrationConfigs[integrationId].params !== "object") {
    state.integrationConfigs[integrationId].params = {};
  }

  return state.integrationConfigs[integrationId];
}

function getIntegrationConfig(integrationId) {
  const config = state.integrationConfigs[integrationId];
  if (config && typeof config === "object") {
    return config;
  }

  return { enabled: false, params: {} };
}

function handleMcpInputChange(event) {
  const target = event.target;
  if (!(target instanceof HTMLInputElement)) {
    return;
  }

  const action = target.dataset.action;
  const configKind = target.dataset.configKind;
  const configId = target.dataset.configId;
  if (!action || !configKind || !configId) {
    return;
  }

  const config = configKind === "integration" ? ensureIntegrationConfig(configId) : ensureMcpConfig(configId);
  if (action === "toggle") {
    config.enabled = target.checked;
    if (configKind === "integration" && configId === "telegram") {
      syncTelegramFlagsFromIntegrationConfig();
      updateTelegramStatusLabel();
    }
    return;
  }

  if (action === "param") {
    const fieldId = target.dataset.fieldId;
    if (!fieldId) {
      return;
    }
    config.params[fieldId] = target.value;
    if (configKind === "integration" && configId === "telegram") {
      syncTelegramFlagsFromIntegrationConfig();
      updateTelegramStatusLabel();
    }
  }
}

async function handleMcpActionClick(event) {
  const target = event.target;
  if (!(target instanceof HTMLElement)) {
    return;
  }

  const button = target.closest("button[data-action][data-config-kind][data-config-id]");
  if (!(button instanceof HTMLButtonElement)) {
    return;
  }

  const action = button.dataset.action;
  const configKind = button.dataset.configKind;
  const configId = button.dataset.configId;
  if (!action || !configKind || !configId) {
    return;
  }

  try {
    if (action === "save") {
      await persistMcpConfigsToSettings();
      setStatus(configKind === "integration" ? "Integration settings saved." : "Tool settings saved.");
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
      if (configKind === "integration") {
        await verifyIntegrationConfig(configId);
        setStatus("Integration verified.");
      } else {
        await verifyMcpConfig(configId);
        setStatus("Tool verified.");
      }
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

if (memoryManagementButton instanceof HTMLButtonElement) {
  memoryManagementButton.addEventListener("click", () => {
    toggleMenu(false);
    openMemoryManagementModal();
  });
}

if (memoryModalCloseButton instanceof HTMLButtonElement) {
  memoryModalCloseButton.addEventListener("click", closeMemoryManagementModal);
}

if (memoryModalBackdrop instanceof HTMLElement) {
  memoryModalBackdrop.addEventListener("click", closeMemoryManagementModal);
}

if (coreMemorySearchInput instanceof HTMLInputElement) {
  coreMemorySearchInput.addEventListener("input", () => {
    state.coreMemorySearchTerm = coreMemorySearchInput.value;
    renderMemoryManagement();
  });
}

if (normalMemorySearchInput instanceof HTMLInputElement) {
  normalMemorySearchInput.addEventListener("input", () => {
    state.normalMemorySearchTerm = normalMemorySearchInput.value;
    renderMemoryManagement();
  });
}

if (addCoreMemoryButton instanceof HTMLButtonElement) {
  addCoreMemoryButton.addEventListener("click", async () => {
    await addMemory("core");
  });
}

if (addNormalMemoryButton instanceof HTMLButtonElement) {
  addNormalMemoryButton.addEventListener("click", async () => {
    await addMemory("normal");
  });
}

if (coreMemoryInput instanceof HTMLInputElement) {
  coreMemoryInput.addEventListener("keydown", async (event) => {
    if (event.key !== "Enter") {
      return;
    }
    event.preventDefault();
    await addMemory("core");
  });
}

if (normalMemoryInput instanceof HTMLInputElement) {
  normalMemoryInput.addEventListener("keydown", async (event) => {
    if (event.key !== "Enter") {
      return;
    }
    event.preventDefault();
    await addMemory("normal");
  });
}

async function handleMemoryListClick(event) {
  const target = event.target;
  if (!(target instanceof HTMLElement)) {
    return;
  }

  const actionable = target.closest("[data-memory-type][data-memory-index][data-memory-action]");
  if (!(actionable instanceof HTMLElement)) {
    return;
  }

  const memoryType = actionable.dataset.memoryType;
  const memoryIndex = actionable.dataset.memoryIndex;
  const memoryAction = actionable.dataset.memoryAction;
  if (!memoryType || typeof memoryIndex !== "string" || !memoryAction) {
    return;
  }

  if (memoryAction === "delete") {
    await deleteMemory(memoryType, memoryIndex);
    return;
  }

  if (memoryAction === "edit") {
    startMemoryInlineEdit(memoryType, memoryIndex);
    return;
  }

  if (memoryAction === "save") {
    await saveMemoryInlineEdit(memoryType, memoryIndex);
    return;
  }

  if (memoryAction === "cancel") {
    cancelMemoryInlineEdit(memoryType);
  }
}

function handleMemoryListInput(event) {
  const target = event.target;
  if (!(target instanceof HTMLTextAreaElement)) {
    return;
  }

  const memoryType = target.dataset.memoryType;
  const memoryAction = target.dataset.memoryAction;
  if (!memoryType || memoryAction !== "draft") {
    return;
  }

  updateMemoryEditDraft(memoryType, target.value);
}

function handleMemoryListKeydown(event) {
  const target = event.target;
  if (!(target instanceof HTMLElement)) {
    return;
  }

  const isEnterOnEditableText =
    (event.key === "Enter" || event.key === " ") &&
    target.dataset.memoryAction === "edit" &&
    target.dataset.memoryType &&
    target.dataset.memoryIndex;

  if (!isEnterOnEditableText) {
    return;
  }

  event.preventDefault();
  startMemoryInlineEdit(target.dataset.memoryType, target.dataset.memoryIndex);
}

if (coreMemoryList instanceof HTMLElement) {
  coreMemoryList.addEventListener("click", handleMemoryListClick);
  coreMemoryList.addEventListener("input", handleMemoryListInput);
  coreMemoryList.addEventListener("keydown", handleMemoryListKeydown);
}

if (normalMemoryList instanceof HTMLElement) {
  normalMemoryList.addEventListener("click", handleMemoryListClick);
  normalMemoryList.addEventListener("input", handleMemoryListInput);
  normalMemoryList.addEventListener("keydown", handleMemoryListKeydown);
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

document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") {
    return;
  }

  if (memoryModal instanceof HTMLElement && !memoryModal.classList.contains("hidden")) {
    closeMemoryManagementModal();
  }
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

if (integrationList instanceof HTMLElement) {
  integrationList.addEventListener("input", handleMcpInputChange);
  integrationList.addEventListener("click", handleMcpActionClick);
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
window.addEventListener("beforeunload", () => {
  if (state.chatSyncTimerId) {
    window.clearInterval(state.chatSyncTimerId);
    state.chatSyncTimerId = null;
  }
  if (state.integrationStatusSyncTimerId) {
    window.clearInterval(state.integrationStatusSyncTimerId);
    state.integrationStatusSyncTimerId = null;
  }
});
window.addEventListener("load", loadGatewayMeta);
