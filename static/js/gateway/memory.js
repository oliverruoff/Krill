import { state, MEMORY_MAX_LENGTH } from "./state.js";
import {
  memoryModal,
  coreMemoryList,
  normalMemoryList,
  coreMemorySearchInput,
  normalMemorySearchInput,
  coreMemoryInput,
  normalMemoryInput,
  compactCoreMemoryButton,
  compactNormalMemoryButton,
  coreMemoryTokenCountNode,
  normalMemoryTokenCountNode,
  memoryTokenTotalNode,
  brainModal,
  timedJobsModal,
  tokenUsageModal,
  changePasswordModal,
} from "./dom.js";
import { setStatus, getServerDate, formatNumber, normalizeErrorMessage, buildHttpErrorDetail, createTimestamp } from "./utils.js";
import { showToast } from "./toast.js";

function normalizeIncomingMemories(rawMemories) {
  if (!Array.isArray(rawMemories)) {
    return [];
  }

  return rawMemories
    .filter((memory) => memory && typeof memory === "object")
    .map((memory) => {
      const content = typeof memory.content === "string" ? memory.content.trim().slice(0, MEMORY_MAX_LENGTH) : "";
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

  const parsed = getServerDate(value);
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
      editInput.maxLength = MEMORY_MAX_LENGTH;
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
  updateMemoryCompactionButtons();
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

  const { persistSettings } = await import("./chat-sync.js");
  const persisted = await persistSettings(nextSettings);
  state.settings = persisted;
  state.coreMemories = normalizeIncomingMemories(persisted.core_memories);
  state.normalMemories = normalizeIncomingMemories(persisted.normal_memories);
}

function updateMemoryCompactionButtons() {
  if (compactCoreMemoryButton instanceof HTMLButtonElement) {
    const busy = state.memoryCompactionType === "core";
    compactCoreMemoryButton.disabled = busy;
    compactCoreMemoryButton.textContent = busy ? "Compacting..." : "Compaction";
  }
  if (compactNormalMemoryButton instanceof HTMLButtonElement) {
    const busy = state.memoryCompactionType === "normal";
    compactNormalMemoryButton.disabled = busy;
    compactNormalMemoryButton.textContent = busy ? "Compacting..." : "Compaction";
  }
}

async function compactMemoryType(memoryType) {
  if (!state.settings || state.memoryCompactionType) {
    return;
  }

  const targetType = memoryType === "core" ? "core" : "normal";
  state.memoryCompactionType = targetType;
  updateMemoryCompactionButtons();

  try {
    setStatus(`Compacting ${targetType} memories...`);
    const response = await fetch("/api/memory/compact", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ memory_type: targetType }),
    });

    if (!response.ok) {
      const detail = await buildHttpErrorDetail(response, "Memory compaction failed.");
      throw new Error(detail);
    }

    const payload = await response.json();
    state.coreMemories = normalizeIncomingMemories(payload.core_memories);
    state.normalMemories = normalizeIncomingMemories(payload.normal_memories);
    if (state.settings) {
      state.settings.core_memories = state.coreMemories;
      state.settings.normal_memories = state.normalMemories;
    }
    renderMemoryManagement();

    const compactedCount = Number.isFinite(Number(payload.compacted_count)) ? Number(payload.compacted_count) : 0;
    const typeLabel = targetType === "core" ? "Core" : "Normal";
    const message = compactedCount > 0
      ? `${typeLabel} memories compacted (${compactedCount} -> 1).`
      : `${typeLabel} memories compacted.`;
    setStatus(message);
    showToast(message);
  } catch (error) {
    setStatus(normalizeErrorMessage(error, "Memory compaction failed."), true);
  } finally {
    state.memoryCompactionType = "";
    updateMemoryCompactionButtons();
  }
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
  refreshMemoriesFromServer().catch(() => {});

  if (coreMemorySearchInput instanceof HTMLInputElement) {
    coreMemorySearchInput.focus();
  }
}

function closeMemoryManagementModal() {
  if (!(memoryModal instanceof HTMLElement)) {
    return;
  }

  memoryModal.classList.add("hidden");
  if ((!(brainModal instanceof HTMLElement) || brainModal.classList.contains("hidden"))
    && (!(timedJobsModal instanceof HTMLElement) || timedJobsModal.classList.contains("hidden"))
    && (!(tokenUsageModal instanceof HTMLElement) || tokenUsageModal.classList.contains("hidden"))
    && (!(changePasswordModal instanceof HTMLElement) || changePasswordModal.classList.contains("hidden"))
    && (!state.mobileLeftDrawerOpen && !state.mobileRightDrawerOpen)) {
    document.body.style.overflow = "";
  }
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

  if (text.length > MEMORY_MAX_LENGTH) {
    setStatus(`Memory must be at most ${formatNumber(MEMORY_MAX_LENGTH)} characters.`, true);
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
  const normalized = String(nextValue || "").slice(0, MEMORY_MAX_LENGTH);
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

async function refreshMemoriesFromServer() {
  const response = await fetch("/api/settings", { cache: "no-store" });
  if (!response.ok) {
    const detail = await buildHttpErrorDetail(response, "Failed to refresh memories.");
    throw new Error(detail);
  }

  const settings = await response.json();
  state.settings = settings;
  state.coreMemories = normalizeIncomingMemories(settings?.core_memories);
  state.normalMemories = normalizeIncomingMemories(settings?.normal_memories);

  if (memoryModal instanceof HTMLElement && !memoryModal.classList.contains("hidden")) {
    renderMemoryManagement();
  }
}

export {
  normalizeIncomingMemories,
  estimateTextTokens,
  estimateMemoryTokens,
  formatMemoryTimestamp,
  getFilteredMemories,
  renderMemoryList,
  renderMemoryTokenCounts,
  renderMemoryManagement,
  persistMemoriesToSettings,
  updateMemoryCompactionButtons,
  compactMemoryType,
  openMemoryManagementModal,
  closeMemoryManagementModal,
  addMemory,
  deleteMemory,
  startMemoryInlineEdit,
  updateMemoryEditDraft,
  cancelMemoryInlineEdit,
  saveMemoryInlineEdit,
  refreshMemoriesFromServer,
};
