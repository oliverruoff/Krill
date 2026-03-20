import { state, CHAT_HISTORY_PAGE_SIZE, CHAT_HISTORY_SCROLL_LOAD_THRESHOLD_PX, EDITABLE_CHAT_TITLE_MAX_LENGTH } from "./state.js";
import { chatHistoryList, currentChatTitleNode, systemTraceToggleButton, newChatButton, chatInput } from "./dom.js";
import { setStatus, formatMessageTimestamp, normalizeChatTitle, deriveChatTitle, normalizeEditedChatTitle, createTimestamp, createChatId } from "./utils.js";
import { isMobileDrawerMode, closeMobileDrawers } from "./mobile-drawer.js";
import { removeChatRuntime } from "./chat-runtime.js";

function doesChatMatchSearch(chat, normalizedSearch) {
  if (!normalizedSearch) {
    return true;
  }

  const title = typeof chat?.title === "string" ? chat.title.toLowerCase() : "";
  if (title.includes(normalizedSearch)) {
    return true;
  }

  if (!Array.isArray(chat?.messages)) {
    return false;
  }

  return chat.messages.some((message) => {
    if (!message || (message.role !== "user" && message.role !== "assistant")) {
      return false;
    }
    const content = typeof message.content === "string" ? message.content.toLowerCase() : "";
    return content.includes(normalizedSearch);
  });
}

function isHiddenTimedJobDebugChat(chat) {
  const title = typeof chat?.title === "string" ? chat.title.trim() : "";
  return title.startsWith("[Hidden]");
}

function getFilteredChats(chats, searchTerm) {
  const normalizedSearch = String(searchTerm || "").trim().toLowerCase();
  return chats.filter((chat) => {
    if (!state.showHiddenTimedJobChats && isHiddenTimedJobDebugChat(chat)) {
      return false;
    }
    return doesChatMatchSearch(chat, normalizedSearch);
  });
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
  const mobileMode = isMobileDrawerMode();
  if (mobileMode) {
    systemTraceToggleButton.textContent = isCollapsed ? "Trace: Off" : "Trace: On";
  } else {
    systemTraceToggleButton.textContent = isCollapsed ? "Show system trace" : "Hide system trace";
  }
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
    hidden_from_history: false,
    created_at: timestamp,
    updated_at: timestamp,
  };
}

function renderChatHistory(options = {}) {
  const preserveScroll = Boolean(options && options.preserveScroll);
  const previousScrollTop = preserveScroll ? chatHistoryList.scrollTop : 0;
  chatHistoryList.innerHTML = "";
  const sortedChats = sortChatsByLatestMessage(state.chats);
  const filteredChats = getFilteredChats(sortedChats, state.chatHistorySearchTerm);
  const normalizedSearch = String(state.chatHistorySearchTerm || "").trim().toLowerCase();
  const signature = `${normalizedSearch}::${filteredChats.map((chat) => String(chat?.id || "")).join("|")}`;
  const signatureChanged = state.chatHistorySignature !== signature;
  if (!state.chatHistorySignature) {
    state.chatHistoryVisibleCount = CHAT_HISTORY_PAGE_SIZE;
  }
  state.chatHistorySignature = signature;
  if (signatureChanged) {
    state.chatHistoryVisibleCount = CHAT_HISTORY_PAGE_SIZE;
  }

  if (filteredChats.length === 0) {
    state.chatHistoryVisibleCount = CHAT_HISTORY_PAGE_SIZE;
    const emptyNode = document.createElement("p");
    emptyNode.className = "chat-history-empty";
    emptyNode.textContent = sortedChats.length === 0 ? "No chats yet." : "No matching chats.";
    chatHistoryList.appendChild(emptyNode);
    if (preserveScroll) {
      chatHistoryList.scrollTop = previousScrollTop;
    }
    return;
  }

  let visibleCount = Math.max(CHAT_HISTORY_PAGE_SIZE, Math.floor(Number(state.chatHistoryVisibleCount) || CHAT_HISTORY_PAGE_SIZE));
  visibleCount = Math.min(visibleCount, filteredChats.length);
  state.chatHistoryVisibleCount = visibleCount;

  filteredChats.slice(0, visibleCount).forEach((chat) => {
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
    const pendingMessages = Array.isArray(chat.messages)
      ? chat.messages.filter((message) => message && message.role === "assistant" && (message.status === "queued" || message.status === "processing"))
      : [];
    const queuedCount = pendingMessages.filter((message) => message.status === "queued").length;
    const processingCount = pendingMessages.filter((message) => message.status === "processing").length;
    timeNode.textContent = latestTimestamp ? formatMessageTimestamp(latestTimestamp) : "No messages yet";

    const queueBadgeNode = document.createElement("p");
    queueBadgeNode.className = "chat-history-queue-badge";
    if (processingCount > 0 && queuedCount > 0) {
      queueBadgeNode.textContent = `${queuedCount} queued`;
    } else if (processingCount > 0) {
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

  if (visibleCount < filteredChats.length) {
    const moreNode = document.createElement("p");
    moreNode.className = "chat-history-more";
    moreNode.textContent = `Showing ${visibleCount} of ${filteredChats.length}. Scroll for more...`;
    chatHistoryList.appendChild(moreNode);
  }

  if (preserveScroll) {
    chatHistoryList.scrollTop = previousScrollTop;
  }
}

function maybeLoadMoreChatHistory() {
  if (!(chatHistoryList instanceof HTMLElement)) {
    return;
  }
  const sortedChats = sortChatsByLatestMessage(state.chats);
  const filteredChats = getFilteredChats(sortedChats, state.chatHistorySearchTerm);
  if (filteredChats.length <= state.chatHistoryVisibleCount) {
    return;
  }
  if (chatHistoryList.scrollHeight <= chatHistoryList.clientHeight) {
    return;
  }
  const distanceFromBottom = chatHistoryList.scrollHeight - chatHistoryList.clientHeight - chatHistoryList.scrollTop;
  if (distanceFromBottom > CHAT_HISTORY_SCROLL_LOAD_THRESHOLD_PX) {
    return;
  }
  state.chatHistoryVisibleCount = Math.min(
    filteredChats.length,
    state.chatHistoryVisibleCount + CHAT_HISTORY_PAGE_SIZE,
  );
  renderChatHistory({ preserveScroll: true });
}

async function deleteChat(chatId) {
  const index = state.chats.findIndex((chat) => chat.id === chatId);
  if (index === -1) {
    return;
  }

  removeChatRuntime(chatId);
  delete state.pendingEnqueueByChat[chatId];

  state.chats.splice(index, 1);

  if (state.activeChatId === chatId) {
    const nextActiveChat = sortChatsByLatestMessage(state.chats)[0] ?? null;
    state.activeChatId = nextActiveChat?.id ?? "";
    state.lastRequestTokens = 0;
  }

  renderChatHistory();
  const { renderActiveChat } = await import("./chat-render.js");
  renderActiveChat();
  const { syncUsedTokensToContext } = await import("./providers.js");
  const { updateComposerState } = await import("./chat-render.js");
  const { persistChatsToSettings } = await import("./chat-sync.js");
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
    const { persistChatsToSettings } = await import("./chat-sync.js");
    await persistChatsToSettings();
    setStatus("Chat title updated.");
  } catch (error) {
    setStatus(`Title updated locally, but save failed: ${error.message}`, true);
  }
}

async function activateChat(chatId) {
  state.activeChatId = chatId;
  state.lastRequestTokens = 0;
  closeMobileDrawers();
  renderChatHistory();
  const { renderActiveChat } = await import("./chat-render.js");
  renderActiveChat();
  const { syncUsedTokensToContext } = await import("./providers.js");
  const { updateComposerState } = await import("./chat-render.js");
  const { persistChatsToSettings } = await import("./chat-sync.js");
  syncUsedTokensToContext();
  updateComposerState();
  persistChatsToSettings().catch((error) => {
    setStatus(`Active chat changed locally, but save failed: ${error.message}`, true);
  });
}

async function startNewChat() {
  if (state.isSwitching || state.isCompacting) {
    return;
  }

  closeMobileDrawers();
  const chat = createChatEntry("");
  chat.title = "New chat";
  state.chats.push(chat);
  state.activeChatId = chat.id;
  state.lastRequestTokens = 0;
  renderChatHistory();
  const { renderActiveChat } = await import("./chat-render.js");
  renderActiveChat();
  const { updateTokenCounter } = await import("./token-usage.js");
  const { syncUsedTokensToContext } = await import("./providers.js");
  const { updateComposerState } = await import("./chat-render.js");
  const { persistChatsToSettings } = await import("./chat-sync.js");
  updateTokenCounter(0, state.modelTokenLimit);
  setStatus("New chat ready. Send a first message to create it.");
  updateComposerState();
  persistChatsToSettings().catch((error) => {
    setStatus(`New chat context set locally, but save failed: ${error.message}`, true);
  });
  chatInput.focus();
}

async function toggleSystemTraceVisibility() {
  const activeChat = getActiveChat();
  if (!activeChat) {
    return;
  }

  activeChat.collapse_system_trace = !Boolean(activeChat.collapse_system_trace);
  const { renderActiveChat } = await import("./chat-render.js");
  renderActiveChat();

  try {
    const { persistChatsToSettings } = await import("./chat-sync.js");
    await persistChatsToSettings();
  } catch (error) {
    setStatus(`System trace toggle saved locally only: ${error.message}`, true);
  }
}

export {
  doesChatMatchSearch,
  isHiddenTimedJobDebugChat,
  getFilteredChats,
  getLatestChatMessage,
  getLatestChatTimestamp,
  sortChatsByLatestMessage,
  getActiveChat,
  updateCurrentChatTitle,
  updateSystemTraceToggleLabel,
  createChatEntry,
  renderChatHistory,
  maybeLoadMoreChatHistory,
  deleteChat,
  editChatTitle,
  activateChat,
  startNewChat,
  toggleSystemTraceVisibility,
};
