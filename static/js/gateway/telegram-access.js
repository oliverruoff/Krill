/*
 * Telegram integration group-access management modal.
 */

import { state } from "./state.js";
import {
  telegramAccessModal,
  telegramAccessGroupsList,
  telegramAccessAllowedMcps,
  memoryModal,
  brainModal,
  timedJobsModal,
  shortTermMemoryModal,
  tokenUsageModal,
  changePasswordModal,
} from "./dom.js";
import { setStatus, buildHttpErrorDetail } from "./utils.js";
import { showToast } from "./toast.js";

let telegramAccessLoading = false;

function renderGroups() {
  if (!(telegramAccessGroupsList instanceof HTMLElement)) {
    return;
  }
  telegramAccessGroupsList.innerHTML = "";
  if (telegramAccessLoading) {
    const loading = document.createElement("p");
    loading.className = "memory-modal-empty";
    loading.textContent = "Loading Telegram groups...";
    telegramAccessGroupsList.appendChild(loading);
    return;
  }
  const groups = Array.isArray(state.telegramApprovedGroupIds) ? state.telegramApprovedGroupIds : [];
  if (groups.length === 0) {
    const empty = document.createElement("p");
    empty.className = "memory-modal-empty";
    empty.textContent = "No approved groups yet. Use /approve@botname inside a group.";
    telegramAccessGroupsList.appendChild(empty);
    return;
  }
  groups.forEach((groupId, index) => {
    const card = document.createElement("div");
    card.className = "memory-modal-card-item";

    const idSpan = document.createElement("span");
    idSpan.className = "mcp-description";
    idSpan.textContent = String(groupId);

    const removeButton = document.createElement("button");
    removeButton.type = "button";
    removeButton.className = "secondary";
    removeButton.textContent = "Remove";
    removeButton.dataset.telegramGroupRemove = String(index);

    card.appendChild(idSpan);
    card.appendChild(removeButton);
    telegramAccessGroupsList.appendChild(card);
  });
}

function renderGuestAllowedMcps() {
  if (!(telegramAccessAllowedMcps instanceof HTMLElement)) {
    return;
  }
  telegramAccessAllowedMcps.innerHTML = "";
  if (telegramAccessLoading) {
    const loading = document.createElement("p");
    loading.className = "memory-modal-empty";
    loading.textContent = "Loading allowed tools...";
    telegramAccessAllowedMcps.appendChild(loading);
    return;
  }
  const selected = new Set(Array.isArray(state.telegramGuestAllowedMcpIds) ? state.telegramGuestAllowedMcpIds : []);
  const mcps = Array.isArray(state.mcps) ? state.mcps : [];
  mcps.forEach((mcp) => {
    const mcpId = String(mcp?.id || "");
    if (!mcpId) {
      return;
    }
    const row = document.createElement("label");
    row.className = "mcp-toggle";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = selected.has(mcpId);
    checkbox.dataset.telegramGuestMcp = mcpId;
    const text = document.createElement("span");
    text.textContent = String(mcp?.label || mcpId);
    row.appendChild(checkbox);
    row.appendChild(text);
    telegramAccessAllowedMcps.appendChild(row);
  });
}

function renderTelegramAccessModal() {
  renderGroups();
  renderGuestAllowedMcps();
}

export async function loadTelegramAccess() {
  try {
    const response = await fetch("/api/integrations/telegram/access", { cache: "no-store" });
    if (!response.ok) {
      throw new Error(await buildHttpErrorDetail(response, "Failed to load Telegram access settings."));
    }
    const payload = await response.json();
    state.telegramApprovedGroupIds = Array.isArray(payload?.approved_group_ids) ? payload.approved_group_ids : [];
    state.telegramGuestAllowedMcpIds = Array.isArray(payload?.guest_allowed_mcp_ids) ? payload.guest_allowed_mcp_ids : [];
    if (Array.isArray(payload?.available_mcps) && payload.available_mcps.length > 0) {
      state.mcps = payload.available_mcps;
    }
  } finally {
    telegramAccessLoading = false;
    renderTelegramAccessModal();
  }
}

export async function openTelegramAccessModal() {
  if (!(telegramAccessModal instanceof HTMLElement)) {
    return;
  }
  telegramAccessModal.classList.remove("hidden");
  document.body.style.overflow = "hidden";
  telegramAccessLoading = true;
  renderTelegramAccessModal();
  await loadTelegramAccess();
}

export function closeTelegramAccessModal() {
  if (!(telegramAccessModal instanceof HTMLElement)) {
    return;
  }
  telegramAccessModal.classList.add("hidden");
  if (
    (!(memoryModal instanceof HTMLElement) || memoryModal.classList.contains("hidden"))
    && (!(brainModal instanceof HTMLElement) || brainModal.classList.contains("hidden"))
    && (!(timedJobsModal instanceof HTMLElement) || timedJobsModal.classList.contains("hidden"))
    && (!(shortTermMemoryModal instanceof HTMLElement) || shortTermMemoryModal.classList.contains("hidden"))
    && (!(tokenUsageModal instanceof HTMLElement) || tokenUsageModal.classList.contains("hidden"))
    && (!(changePasswordModal instanceof HTMLElement) || changePasswordModal.classList.contains("hidden"))
    && (!state.mobileLeftDrawerOpen && !state.mobileRightDrawerOpen)
  ) {
    document.body.style.overflow = "";
  }
}

export function handleTelegramAccessInputChange(event) {
  const target = event.target;
  if (!(target instanceof HTMLInputElement)) {
    return;
  }
  const guestMcpId = String(target.dataset.telegramGuestMcp || "");
  if (guestMcpId) {
    const selected = new Set(state.telegramGuestAllowedMcpIds);
    if (target.checked) {
      selected.add(guestMcpId);
    } else {
      selected.delete(guestMcpId);
    }
    state.telegramGuestAllowedMcpIds = Array.from(selected).sort();
  }
}

export function handleTelegramAccessClick(event) {
  const target = event.target;
  if (!(target instanceof HTMLElement)) {
    return;
  }
  const removeIndexRaw = target.dataset.telegramGroupRemove;
  if (removeIndexRaw !== undefined) {
    const removeIndex = Number(removeIndexRaw);
    if (Number.isInteger(removeIndex) && removeIndex >= 0) {
      state.telegramApprovedGroupIds.splice(removeIndex, 1);
      renderGroups();
    }
  }
}

export async function saveTelegramAccess() {
  const response = await fetch("/api/integrations/telegram/access", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      approved_group_ids: state.telegramApprovedGroupIds,
      guest_allowed_mcp_ids: state.telegramGuestAllowedMcpIds,
    }),
  });
  if (!response.ok) {
    throw new Error(await buildHttpErrorDetail(response, "Failed to save Telegram access settings."));
  }
  const payload = await response.json();
  state.telegramApprovedGroupIds = Array.isArray(payload?.approved_group_ids) ? payload.approved_group_ids : [];
  state.telegramGuestAllowedMcpIds = Array.isArray(payload?.guest_allowed_mcp_ids) ? payload.guest_allowed_mcp_ids : [];
  renderTelegramAccessModal();
  const { syncIntegrationStatus } = await import("./chat-sync.js");
  await syncIntegrationStatus();
  const { renderIntegrationPanel } = await import("./mcp-panel.js");
  renderIntegrationPanel();
  showToast("Telegram access saved");
  setStatus("Telegram access settings saved.");
}
