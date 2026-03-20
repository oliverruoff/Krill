/*
 * Short-term memory modal: load, render, accept/decline, and background sync.
 */

import { state, CHAT_SYNC_INTERVAL_MS } from "./state.js";
import {
  shortTermMemoryModal,
  shortTermMemoryMetaNode,
  shortTermMemoryRefreshButton,
  shortTermMemoryListNode,
  shortTermMemoryStatusNode,
  mobileLeftShortTermMemoryStatusNode,
  memoryModal,
  brainModal,
  timedJobsModal,
  tokenUsageModal,
  changePasswordModal,
} from "./dom.js";
import {
  setStatus,
  normalizeErrorMessage,
  buildHttpErrorDetail,
  formatNumber,
} from "./utils.js";
import { showToast } from "./toast.js";

async function fetchShortTermMemory() {
  const response = await fetch("/api/memory/short-term", { cache: "no-store" });
  if (!response.ok) {
    const detail = await buildHttpErrorDetail(response, "Failed to load short term memory.");
    throw new Error(detail);
  }
  return response.json();
}

async function resolveShortTermMemory(items) {
  const response = await fetch("/api/memory/short-term/resolve", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ items }),
  });
  if (!response.ok) {
    const detail = await buildHttpErrorDetail(response, "Failed to resolve short term memory.");
    throw new Error(detail);
  }
  return response.json();
}

export function updateShortTermMemoryBadge() {
  const hasDesktopNode = shortTermMemoryStatusNode instanceof HTMLElement;
  const hasMobileNode = mobileLeftShortTermMemoryStatusNode instanceof HTMLElement;
  if (!hasDesktopNode && !hasMobileNode) { return; }
  const pending = Math.max(0, Number(state.shortTermMemoryCount || 0));
  const suffix = state.shortTermMemoryExtracting ? " - identifying..." : "";
  const label = `Short Term Memory: ${formatNumber(pending)} pending${suffix}`;
  if (hasDesktopNode) { shortTermMemoryStatusNode.textContent = label; }
  if (hasMobileNode) { mobileLeftShortTermMemoryStatusNode.textContent = label; }
  if (hasDesktopNode) { shortTermMemoryStatusNode.classList.toggle("assistant-meta-alert", pending > 0); }
  if (hasMobileNode) { mobileLeftShortTermMemoryStatusNode.classList.toggle("assistant-meta-alert", pending > 0); }
}

async function refreshMemoriesFromServer() {
  const { normalizeIncomingMemories, renderMemoryManagement } = await import("./memory.js");

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

export function renderShortTermMemoryList() {
  if (!(shortTermMemoryListNode instanceof HTMLElement)) {
    return;
  }
  shortTermMemoryListNode.innerHTML = "";

  if (!Array.isArray(state.shortTermMemories) || state.shortTermMemories.length === 0) {
    const emptyNode = document.createElement("p");
    emptyNode.className = "memory-empty";
    emptyNode.textContent = "No short term memories pending.";
    shortTermMemoryListNode.appendChild(emptyNode);
    return;
  }

  state.shortTermMemories.forEach((item) => {
    const wrapper = document.createElement("article");
    wrapper.className = "short-term-item";
    wrapper.dataset.shortTermId = String(item.id);

    const contentNode = document.createElement("p");
    contentNode.className = "short-term-item-content";
    contentNode.textContent = item.content;

    const row = document.createElement("div");
    row.className = "short-term-item-row";

    const typeSelect = document.createElement("select");
    typeSelect.className = "short-term-item-type";
    typeSelect.dataset.shortTermType = "1";
    typeSelect.dataset.shortTermId = String(item.id);

    ["core", "normal"].forEach((type) => {
      const option = document.createElement("option");
      option.value = type;
      option.textContent = type;
      typeSelect.appendChild(option);
    });
    typeSelect.value = item.memory_type === "core" ? "core" : "normal";

    const actions = document.createElement("div");
    actions.className = "short-term-item-actions";

    const confirmButton = document.createElement("button");
    confirmButton.type = "button";
    confirmButton.className = "short-term-action-btn short-term-action-confirm";
    confirmButton.dataset.shortTermAction = "accept";
    confirmButton.dataset.shortTermId = String(item.id);
    confirmButton.textContent = "Confirm";

    const declineButton = document.createElement("button");
    declineButton.type = "button";
    declineButton.className = "short-term-action-btn short-term-action-decline";
    declineButton.dataset.shortTermAction = "decline";
    declineButton.dataset.shortTermId = String(item.id);
    declineButton.textContent = "Decline";

    actions.appendChild(confirmButton);
    actions.appendChild(declineButton);
    row.appendChild(typeSelect);
    row.appendChild(actions);
    wrapper.appendChild(contentNode);
    wrapper.appendChild(row);
    shortTermMemoryListNode.appendChild(wrapper);
  });
}

export function openShortTermMemoryModal() {
  if (!(shortTermMemoryModal instanceof HTMLElement)) {
    return;
  }
  shortTermMemoryModal.classList.remove("hidden");
  document.body.style.overflow = "hidden";
  loadShortTermMemories(true);
}

export function closeShortTermMemoryModal() {
  if (!(shortTermMemoryModal instanceof HTMLElement)) {
    return;
  }
  shortTermMemoryModal.classList.add("hidden");
  if (
    (!(memoryModal instanceof HTMLElement) || memoryModal.classList.contains("hidden"))
    && (!(brainModal instanceof HTMLElement) || brainModal.classList.contains("hidden"))
    && (!(timedJobsModal instanceof HTMLElement) || timedJobsModal.classList.contains("hidden"))
    && (!(tokenUsageModal instanceof HTMLElement) || tokenUsageModal.classList.contains("hidden"))
    && (!(changePasswordModal instanceof HTMLElement) || changePasswordModal.classList.contains("hidden"))
    && (!state.mobileLeftDrawerOpen && !state.mobileRightDrawerOpen)
  ) {
    document.body.style.overflow = "";
  }
}

export async function loadShortTermMemories(renderModal = false) {
  if (state.shortTermMemorySyncInFlight) {
    return;
  }
  state.shortTermMemorySyncInFlight = true;
  if (renderModal && shortTermMemoryMetaNode instanceof HTMLElement) {
    shortTermMemoryMetaNode.textContent = "Loading short term memory...";
  }
  const shouldTouchRefreshButton = renderModal
    || (shortTermMemoryModal instanceof HTMLElement && !shortTermMemoryModal.classList.contains("hidden"));
  if (shouldTouchRefreshButton && shortTermMemoryRefreshButton instanceof HTMLButtonElement) {
    shortTermMemoryRefreshButton.disabled = true;
  }

  try {
    const payload = await fetchShortTermMemory();
    const items = Array.isArray(payload.items) ? payload.items : [];
    state.shortTermMemoryExtracting = Boolean(payload?.extraction?.in_progress);
    const previousCount = state.shortTermMemoryCount;
    state.shortTermMemories = items;
    state.shortTermMemoryCount = Number.isFinite(Number(payload.count)) ? Number(payload.count) : items.length;

    if (state.shortTermMemoryCount > previousCount && state.shortTermMemoryCount > state.shortTermMemoryLastToastCount) {
      showToast("Memories identified - check Short Term Memory.");
      state.shortTermMemoryLastToastCount = state.shortTermMemoryCount;
    }

    updateShortTermMemoryBadge();

    if (shortTermMemoryMetaNode instanceof HTMLElement) {
      shortTermMemoryMetaNode.textContent = state.shortTermMemoryExtracting
        ? `${state.shortTermMemoryCount} pending - identifying...`
        : `${state.shortTermMemoryCount} pending`;
    }
    updateShortTermMemoryBadge();

    if (renderModal || (shortTermMemoryModal instanceof HTMLElement && !shortTermMemoryModal.classList.contains("hidden"))) {
      renderShortTermMemoryList();
    }
  } catch (error) {
    if (renderModal && shortTermMemoryMetaNode instanceof HTMLElement) {
      shortTermMemoryMetaNode.textContent = normalizeErrorMessage(error, "Failed to load short term memory.");
    }
  } finally {
    state.shortTermMemorySyncInFlight = false;
    if (shouldTouchRefreshButton && shortTermMemoryRefreshButton instanceof HTMLButtonElement) {
      shortTermMemoryRefreshButton.disabled = false;
    }
  }
}

export async function handleShortTermAction(action, suggestionId) {
  const itemId = Number.parseInt(String(suggestionId), 10);
  if (!Number.isFinite(itemId)) {
    return;
  }

  const wrapper = shortTermMemoryListNode instanceof HTMLElement
    ? shortTermMemoryListNode.querySelector(`[data-short-term-id="${itemId}"]`)
    : null;
  const selectNode = wrapper instanceof HTMLElement
    ? wrapper.querySelector("select[data-short-term-type='1']")
    : null;
  const selectedType = selectNode instanceof HTMLSelectElement && selectNode.value === "core" ? "core" : "normal";

  try {
    await resolveShortTermMemory([{ id: itemId, action, memory_type: selectedType }]);
    state.shortTermMemories = state.shortTermMemories.filter((entry) => Number(entry.id) !== itemId);
    state.shortTermMemoryCount = Math.max(0, state.shortTermMemories.length);
    if (shortTermMemoryMetaNode instanceof HTMLElement) {
      shortTermMemoryMetaNode.textContent = state.shortTermMemoryExtracting
        ? `${state.shortTermMemoryCount} pending - identifying...`
        : `${state.shortTermMemoryCount} pending`;
    }
    renderShortTermMemoryList();
    if (action === "accept") {
      await refreshMemoriesFromServer();
      setStatus("Memory accepted.");
    } else {
      setStatus("Memory declined.");
    }
  } catch (error) {
    setStatus(normalizeErrorMessage(error, "Short term memory update failed."), true);
  }
}

export function startShortTermMemorySync() {
  if (state.shortTermMemorySyncTimerId) {
    window.clearInterval(state.shortTermMemorySyncTimerId);
  }
  state.shortTermMemorySyncTimerId = window.setInterval(() => {
    loadShortTermMemories(false);
  }, CHAT_SYNC_INTERVAL_MS);
}

export function stopShortTermMemorySync() {
  if (state.shortTermMemorySyncTimerId) {
    window.clearInterval(state.shortTermMemorySyncTimerId);
    state.shortTermMemorySyncTimerId = null;
  }
}
