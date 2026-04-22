/*
 * Matrix integration access-management modal.
 */

import { state } from "./state.js";
import {
  matrixAccessModal,
  matrixAccessBotUserNode,
  matrixAccessUsersList,
  matrixAccessRoomsList,
  matrixAccessAllowedMcps,
  memoryModal,
  brainModal,
  timedJobsModal,
  shortTermMemoryModal,
  tokenUsageModal,
  changePasswordModal,
} from "./dom.js";
import { setStatus, buildHttpErrorDetail } from "./utils.js";
import { showToast } from "./toast.js";

const MATRIX_ROLES = [
  { value: "no_assistant_usage", label: "no_assistant_usage" },
  { value: "assistant_usage", label: "assistant_usage" },
  { value: "admin_usage", label: "admin_usage" },
];

function createLabeledField(labelText, inputNode) {
  const wrapper = document.createElement("label");
  wrapper.className = "token-usage-field";
  const labelNode = document.createElement("span");
  labelNode.textContent = labelText;
  wrapper.appendChild(labelNode);
  wrapper.appendChild(inputNode);
  return wrapper;
}

function renderUsers() {
  if (!(matrixAccessUsersList instanceof HTMLElement)) {
    return;
  }
  matrixAccessUsersList.innerHTML = "";
  if (!Array.isArray(state.matrixAccessUsers) || state.matrixAccessUsers.length === 0) {
    const empty = document.createElement("p");
    empty.className = "memory-modal-empty";
    empty.textContent = "No Matrix users configured yet.";
    matrixAccessUsersList.appendChild(empty);
    return;
  }
  state.matrixAccessUsers.forEach((entry, index) => {
    const card = document.createElement("div");
    card.className = "memory-modal-card-item";

    const mxidInput = document.createElement("input");
    mxidInput.type = "text";
    mxidInput.value = String(entry.mxid || "");
    mxidInput.placeholder = "@user:example.com";
    mxidInput.dataset.matrixUserIndex = String(index);
    mxidInput.dataset.matrixUserField = "mxid";

    const roleSelect = document.createElement("select");
    roleSelect.dataset.matrixUserIndex = String(index);
    roleSelect.dataset.matrixUserField = "role";
    MATRIX_ROLES.forEach((role) => {
      const optionNode = document.createElement("option");
      optionNode.value = role.value;
      optionNode.textContent = role.label;
      roleSelect.appendChild(optionNode);
    });
    roleSelect.value = String(entry.role || "no_assistant_usage");

    const noteInput = document.createElement("input");
    noteInput.type = "text";
    noteInput.value = String(entry.note || "");
    noteInput.placeholder = "Optional note";
    noteInput.dataset.matrixUserIndex = String(index);
    noteInput.dataset.matrixUserField = "note";

    const removeButton = document.createElement("button");
    removeButton.type = "button";
    removeButton.className = "secondary";
    removeButton.textContent = "Remove";
    removeButton.dataset.matrixUserRemove = String(index);

    card.appendChild(createLabeledField("MXID", mxidInput));
    card.appendChild(createLabeledField("Role", roleSelect));
    card.appendChild(createLabeledField("Note", noteInput));
    card.appendChild(removeButton);
    matrixAccessUsersList.appendChild(card);
  });
}

function renderRooms() {
  if (!(matrixAccessRoomsList instanceof HTMLElement)) {
    return;
  }
  matrixAccessRoomsList.innerHTML = "";
  if (!Array.isArray(state.matrixApprovedRooms) || state.matrixApprovedRooms.length === 0) {
    const empty = document.createElement("p");
    empty.className = "memory-modal-empty";
    empty.textContent = "No approved Matrix rooms saved yet.";
    matrixAccessRoomsList.appendChild(empty);
    return;
  }
  state.matrixApprovedRooms.forEach((entry, index) => {
    const card = document.createElement("div");
    card.className = "memory-modal-card-item";

    const roomIdInput = document.createElement("input");
    roomIdInput.type = "text";
    roomIdInput.value = String(entry.room_id || "");
    roomIdInput.placeholder = "!roomid:example.com";
    roomIdInput.dataset.matrixRoomIndex = String(index);
    roomIdInput.dataset.matrixRoomField = "room_id";

    const roomNameInput = document.createElement("input");
    roomNameInput.type = "text";
    roomNameInput.value = String(entry.room_name || "");
    roomNameInput.placeholder = "Room name";
    roomNameInput.dataset.matrixRoomIndex = String(index);
    roomNameInput.dataset.matrixRoomField = "room_name";

    const approvedByInput = document.createElement("input");
    approvedByInput.type = "text";
    approvedByInput.value = String(entry.approved_by_mxid || "");
    approvedByInput.placeholder = "@admin:example.com";
    approvedByInput.dataset.matrixRoomIndex = String(index);
    approvedByInput.dataset.matrixRoomField = "approved_by_mxid";

    const activeLabel = document.createElement("label");
    activeLabel.className = "mcp-toggle";
    const activeInput = document.createElement("input");
    activeInput.type = "checkbox";
    activeInput.checked = Boolean(entry.active);
    activeInput.dataset.matrixRoomIndex = String(index);
    activeInput.dataset.matrixRoomField = "active";
    const activeText = document.createElement("span");
    activeText.textContent = "Active";
    activeLabel.appendChild(activeInput);
    activeLabel.appendChild(activeText);

    const removeButton = document.createElement("button");
    removeButton.type = "button";
    removeButton.className = "secondary";
    removeButton.textContent = "Remove";
    removeButton.dataset.matrixRoomRemove = String(index);

    card.appendChild(createLabeledField("Room ID", roomIdInput));
    card.appendChild(createLabeledField("Room Name", roomNameInput));
    card.appendChild(createLabeledField("Approved By", approvedByInput));
    card.appendChild(activeLabel);
    card.appendChild(removeButton);
    matrixAccessRoomsList.appendChild(card);
  });
}

function renderAllowedMcps() {
  if (!(matrixAccessAllowedMcps instanceof HTMLElement)) {
    return;
  }
  matrixAccessAllowedMcps.innerHTML = "";
  const selected = new Set(Array.isArray(state.matrixAssistantAllowedMcpIds) ? state.matrixAssistantAllowedMcpIds : []);
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
    checkbox.dataset.matrixAllowedMcp = mcpId;
    const text = document.createElement("span");
    text.textContent = String(mcp?.label || mcpId);
    row.appendChild(checkbox);
    row.appendChild(text);
    matrixAccessAllowedMcps.appendChild(row);
  });
}

function renderMatrixAccessModal() {
  if (matrixAccessBotUserNode instanceof HTMLElement) {
    const botUserId = state.matrixStatus?.bot_user_id || state.matrixAccessBotUserId || "unknown";
    matrixAccessBotUserNode.textContent = `Bot user id: ${botUserId}`;
  }
  renderUsers();
  renderRooms();
  renderAllowedMcps();
}

export async function loadMatrixAccess() {
  const response = await fetch("/api/integrations/matrix/access", { cache: "no-store" });
  if (!response.ok) {
    throw new Error(await buildHttpErrorDetail(response, "Failed to load Matrix access settings."));
  }
  const payload = await response.json();
  state.matrixAccessUsers = Array.isArray(payload?.users) ? payload.users : [];
  state.matrixApprovedRooms = Array.isArray(payload?.approved_rooms) ? payload.approved_rooms : [];
  state.matrixAssistantAllowedMcpIds = Array.isArray(payload?.assistant_allowed_mcp_ids) ? payload.assistant_allowed_mcp_ids : [];
  state.matrixAccessBotUserId = typeof payload?.bot_user_id === "string" ? payload.bot_user_id : "";
  renderMatrixAccessModal();
}

export async function openMatrixAccessModal() {
  if (!(matrixAccessModal instanceof HTMLElement)) {
    return;
  }
  matrixAccessModal.classList.remove("hidden");
  document.body.style.overflow = "hidden";
  renderMatrixAccessModal();
  await loadMatrixAccess();
}

export function closeMatrixAccessModal() {
  if (!(matrixAccessModal instanceof HTMLElement)) {
    return;
  }
  matrixAccessModal.classList.add("hidden");
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

export function handleMatrixAccessInputChange(event) {
  const target = event.target;
  if (!(target instanceof HTMLInputElement) && !(target instanceof HTMLSelectElement)) {
    return;
  }
  const userIndex = Number(target.dataset.matrixUserIndex);
  const userField = String(target.dataset.matrixUserField || "");
  if (Number.isInteger(userIndex) && userIndex >= 0 && userField) {
    const entry = state.matrixAccessUsers[userIndex];
    if (!entry) {
      return;
    }
    entry[userField] = target instanceof HTMLInputElement && target.type === "checkbox" ? target.checked : target.value;
    return;
  }
  const roomIndex = Number(target.dataset.matrixRoomIndex);
  const roomField = String(target.dataset.matrixRoomField || "");
  if (Number.isInteger(roomIndex) && roomIndex >= 0 && roomField) {
    const entry = state.matrixApprovedRooms[roomIndex];
    if (!entry) {
      return;
    }
    entry[roomField] = target instanceof HTMLInputElement && target.type === "checkbox" ? target.checked : target.value;
    return;
  }
  const allowedMcpId = String(target.dataset.matrixAllowedMcp || "");
  if (allowedMcpId) {
    const selected = new Set(state.matrixAssistantAllowedMcpIds);
    if (target instanceof HTMLInputElement && target.checked) {
      selected.add(allowedMcpId);
    } else {
      selected.delete(allowedMcpId);
    }
    state.matrixAssistantAllowedMcpIds = Array.from(selected).sort();
  }
}

export async function handleMatrixAccessClick(event) {
  const target = event.target;
  if (!(target instanceof HTMLElement)) {
    return;
  }
  const removeUserIndex = Number(target.dataset.matrixUserRemove);
  if (Number.isInteger(removeUserIndex) && removeUserIndex >= 0) {
    state.matrixAccessUsers.splice(removeUserIndex, 1);
    renderUsers();
    return;
  }
  const removeRoomIndex = Number(target.dataset.matrixRoomRemove);
  if (Number.isInteger(removeRoomIndex) && removeRoomIndex >= 0) {
    state.matrixApprovedRooms.splice(removeRoomIndex, 1);
    renderRooms();
  }
}

export function addMatrixAccessUser() {
  state.matrixAccessUsers.push({
    mxid: "",
    role: "assistant_usage",
    note: "",
  });
  renderUsers();
}

export function addMatrixApprovedRoom() {
  state.matrixApprovedRooms.push({
    room_id: "",
    room_name: "",
    approved_by_mxid: "",
    is_direct: false,
    active: true,
  });
  renderRooms();
}

export async function saveMatrixAccess() {
  const response = await fetch("/api/integrations/matrix/access", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      users: state.matrixAccessUsers,
      approved_rooms: state.matrixApprovedRooms,
      assistant_allowed_mcp_ids: state.matrixAssistantAllowedMcpIds,
    }),
  });
  if (!response.ok) {
    throw new Error(await buildHttpErrorDetail(response, "Failed to save Matrix access settings."));
  }
  const payload = await response.json();
  state.matrixAccessUsers = Array.isArray(payload?.users) ? payload.users : [];
  state.matrixApprovedRooms = Array.isArray(payload?.approved_rooms) ? payload.approved_rooms : [];
  state.matrixAssistantAllowedMcpIds = Array.isArray(payload?.assistant_allowed_mcp_ids) ? payload.assistant_allowed_mcp_ids : [];
  renderMatrixAccessModal();
  const { syncIntegrationStatus } = await import("./chat-sync.js");
  await syncIntegrationStatus();
  const { renderIntegrationPanel } = await import("./mcp-panel.js");
  renderIntegrationPanel();
  showToast("Matrix access saved");
  setStatus("Matrix access settings saved.");
}

export async function refreshMatrixBotIdentity() {
  const response = await fetch("/api/integrations/matrix/refresh-identity", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
  });
  if (!response.ok) {
    throw new Error(await buildHttpErrorDetail(response, "Failed to refresh Matrix bot identity."));
  }
  const payload = await response.json();
  state.matrixAccessBotUserId = typeof payload?.bot_user_id === "string" ? payload.bot_user_id : "";
  if (!state.matrixStatus || typeof state.matrixStatus !== "object") {
    state.matrixStatus = {};
  }
  state.matrixStatus.bot_user_id = state.matrixAccessBotUserId;
  renderMatrixAccessModal();
  const { renderIntegrationPanel } = await import("./mcp-panel.js");
  renderIntegrationPanel();
  showToast("Matrix identity refreshed");
}
