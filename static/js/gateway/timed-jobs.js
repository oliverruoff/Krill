/*
 * Timed jobs CRUD, modal, rendering, and clock helpers.
 */

import { state } from "./state.js";
import {
  timedJobsNowNode,
  timedJobsModal,
  timedJobsCloseButton,
  timedJobsMetaNode,
  timedJobsListNode,
  timedJobTitleInput,
  timedJobPromptInput,
  timedJobIntervalSelect,
  timedJobStartDateInput,
  timedJobTimeInput,
  timedJobProviderSelect,
  timedJobModelSelect,
  timedJobEnabledInput,
  timedJobOutputDecisionEnabledInput,
  timedJobChannelsNode,
  memoryModal,
  brainModal,
  shortTermMemoryModal,
  tokenUsageModal,
  changePasswordModal,
} from "./dom.js";
import {
  setStatus,
  getServerDate,
  normalizeErrorMessage,
  buildHttpErrorDetail,
  formatMessageTimestamp,
} from "./utils.js";

/* ---- private helpers mirrored from gateway (pure state lookups) ---- */
function getProviderById(providerId) {
  return state.providers.find((provider) => provider.id === providerId);
}

function getConfiguredProviderIds() {
  return Object.keys(state.settings?.provider_configs ?? {});
}
/* ------------------------------------------------------------------- */

function formatNowWithSeconds() {
  const now = getServerDate();
  const yyyy = now.getFullYear();
  const mm = String(now.getMonth() + 1).padStart(2, "0");
  const dd = String(now.getDate()).padStart(2, "0");
  const hh = String(now.getHours()).padStart(2, "0");
  const mi = String(now.getMinutes()).padStart(2, "0");
  const ss = String(now.getSeconds()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd} ${hh}:${mi}:${ss}`;
}


function updateTimedJobsNowLabel() {
  if (!(timedJobsNowNode instanceof HTMLElement)) {
    return;
  }
  const zone = state.serverTimezoneName ? ` (${state.serverTimezoneName})` : "";
  timedJobsNowNode.innerHTML = `<strong>Now:</strong> ${formatNowWithSeconds()}${zone}`;
}


export function startTimedJobsClock() {
  updateTimedJobsNowLabel();
  if (state.timedJobsClockTimerId) {
    window.clearInterval(state.timedJobsClockTimerId);
  }
  state.timedJobsClockTimerId = window.setInterval(updateTimedJobsNowLabel, 1000);
}

export function stopTimedJobsClock() {
  if (state.timedJobsClockTimerId) {
    window.clearInterval(state.timedJobsClockTimerId);
    state.timedJobsClockTimerId = null;
  }
}

function todayDateInputValue() {
  const now = getServerDate();
  const yyyy = now.getFullYear();
  const mm = String(now.getMonth() + 1).padStart(2, "0");
  const dd = String(now.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}


function normalizeIncomingTimedJobs(rawJobs) {
  if (!Array.isArray(rawJobs)) {
    return [];
  }
  return rawJobs
    .filter((entry) => entry && typeof entry === "object")
    .map((entry) => ({
      id: typeof entry.id === "string" ? entry.id : "",
      title: typeof entry.title === "string" ? entry.title : "",
      prompt: typeof entry.prompt === "string" ? entry.prompt : "",
      interval: typeof entry.interval === "string" ? entry.interval : "daily",
      start_date: typeof entry.start_date === "string" ? entry.start_date : todayDateInputValue(),
      time_of_day: typeof entry.time_of_day === "string" ? entry.time_of_day.slice(0, 5) : "09:00",
      enabled: Boolean(entry.enabled),
      output_decision_enabled: Boolean(entry.output_decision_enabled),
      channels: Array.isArray(entry.channels) ? entry.channels.map((channel) => String(channel)) : ["gateway"],
      provider_id: typeof entry.provider_id === "string" ? entry.provider_id : "",
      model: typeof entry.model === "string" ? entry.model : "",
      next_run_at: typeof entry.next_run_at === "string" ? entry.next_run_at : "",
      last_run_at: typeof entry.last_run_at === "string" ? entry.last_run_at : "",
      updated_at: typeof entry.updated_at === "string" ? entry.updated_at : "",
    }))
    .filter((entry) => Boolean(entry.id));
}

function normalizeTimedJobChannels(rawChannels) {
  if (!Array.isArray(rawChannels)) {
    return [];
  }
  return rawChannels
    .filter((entry) => entry && typeof entry === "object")
    .map((entry) => ({
      id: typeof entry.id === "string" ? entry.id : "",
      label: typeof entry.label === "string" ? entry.label : "",
      description: typeof entry.description === "string" ? entry.description : "",
      available: Boolean(entry.available),
      default: Boolean(entry.default),
    }))
    .filter((entry) => Boolean(entry.id));
}

function renderTimedJobProviderOptions(selectedProviderId = "") {
  if (!(timedJobProviderSelect instanceof HTMLSelectElement)) {
    return "";
  }

  const configuredProviderIds = getConfiguredProviderIds();
  timedJobProviderSelect.innerHTML = "";

  const useActiveOption = document.createElement("option");
  useActiveOption.value = "";
  useActiveOption.textContent = "Use active provider/model";
  timedJobProviderSelect.appendChild(useActiveOption);

  configuredProviderIds.forEach((providerId) => {
    const provider = getProviderById(providerId);
    const option = document.createElement("option");
    option.value = providerId;
    option.textContent = provider?.label ?? providerId;
    timedJobProviderSelect.appendChild(option);
  });

  const normalizedSelected = configuredProviderIds.includes(selectedProviderId) ? selectedProviderId : "";
  timedJobProviderSelect.value = normalizedSelected;
  return normalizedSelected;
}

export function renderTimedJobModelOptions(providerId, selectedModel = "") {
  if (!(timedJobModelSelect instanceof HTMLSelectElement)) {
    return "";
  }

  timedJobModelSelect.innerHTML = "";
  const normalizedProviderId = String(providerId || "").trim();
  if (!normalizedProviderId) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "Use active provider model";
    timedJobModelSelect.appendChild(option);
    timedJobModelSelect.disabled = true;
    timedJobModelSelect.value = "";
    return "";
  }

  const provider = getProviderById(normalizedProviderId);
  const configuredModel = state.settings?.provider_configs?.[normalizedProviderId]?.model ?? "";
  const modelCandidates = provider?.models ?? [];
  const normalizedSelected = selectedModel || configuredModel || modelCandidates[0]?.id || "";

  modelCandidates.forEach((model) => {
    const option = document.createElement("option");
    option.value = model.id;
    option.textContent = model.label;
    timedJobModelSelect.appendChild(option);
  });

  if (normalizedSelected && !modelCandidates.some((model) => model.id === normalizedSelected)) {
    const customOption = document.createElement("option");
    customOption.value = normalizedSelected;
    customOption.textContent = normalizedSelected;
    timedJobModelSelect.appendChild(customOption);
  }

  timedJobModelSelect.disabled = false;
  if (normalizedSelected) {
    timedJobModelSelect.value = normalizedSelected;
  }
  return (timedJobModelSelect.value || normalizedSelected || "").trim();
}

export function resetTimedJobEditor() {
  state.timedJobEditingId = "";
  if (timedJobTitleInput instanceof HTMLInputElement) {
    timedJobTitleInput.value = "";
  }
  if (timedJobPromptInput instanceof HTMLTextAreaElement) {
    timedJobPromptInput.value = "";
  }
  if (timedJobIntervalSelect instanceof HTMLSelectElement) {
    timedJobIntervalSelect.value = "daily";
  }
  if (timedJobStartDateInput instanceof HTMLInputElement) {
    timedJobStartDateInput.value = todayDateInputValue();
  }
  if (timedJobTimeInput instanceof HTMLInputElement) {
    const now = getServerDate();
    const hh = String(now.getHours()).padStart(2, "0");
    const mm = String(now.getMinutes()).padStart(2, "0");
    timedJobTimeInput.value = `${hh}:${mm}`;
  }

  if (timedJobEnabledInput instanceof HTMLInputElement) {
    timedJobEnabledInput.checked = true;
  }
  if (timedJobOutputDecisionEnabledInput instanceof HTMLInputElement) {
    timedJobOutputDecisionEnabledInput.checked = false;
  }
  renderTimedJobProviderOptions("");
  renderTimedJobModelOptions("", "");
  renderTimedJobChannelOptions(["gateway"]);
}

function renderTimedJobChannelOptions(selectedChannels = ["gateway"]) {
  if (!(timedJobChannelsNode instanceof HTMLElement)) {
    return;
  }
  timedJobChannelsNode.innerHTML = "";
  if (!Array.isArray(state.timedJobChannels) || state.timedJobChannels.length === 0) {
    const emptyNode = document.createElement("p");
    emptyNode.className = "memory-modal-empty";
    emptyNode.textContent = "No output channels available.";
    timedJobChannelsNode.appendChild(emptyNode);
    return;
  }

  const selectedSet = new Set(selectedChannels.map((entry) => String(entry)));
  state.timedJobChannels.forEach((channel) => {
    const wrapper = document.createElement("label");
    wrapper.className = "timed-job-check";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.dataset.timedJobChannelId = channel.id;
    input.disabled = !channel.available;
    input.checked = channel.available && (selectedSet.has(channel.id) || (selectedSet.size === 0 && channel.default));

    const text = document.createElement("span");
    const suffix = channel.available ? "" : " (unavailable)";
    text.textContent = `${channel.label || channel.id}${suffix}`;
    if (channel.description) {
      text.title = channel.description;
    }

    wrapper.appendChild(input);
    wrapper.appendChild(text);
    timedJobChannelsNode.appendChild(wrapper);
  });
}

function populateTimedJobEditor(job) {
  if (!job || typeof job !== "object") {
    resetTimedJobEditor();
    return;
  }
  state.timedJobEditingId = typeof job.id === "string" ? job.id : "";
  if (state.timedJobEditingId) {
    state.expandedTimedJobIds[state.timedJobEditingId] = true;
  }
  if (timedJobTitleInput instanceof HTMLInputElement) {
    timedJobTitleInput.value = typeof job.title === "string" ? job.title : "";
  }
  if (timedJobPromptInput instanceof HTMLTextAreaElement) {
    timedJobPromptInput.value = typeof job.prompt === "string" ? job.prompt : "";
  }
  if (timedJobIntervalSelect instanceof HTMLSelectElement) {
    timedJobIntervalSelect.value = typeof job.interval === "string" ? job.interval : "daily";
  }
  if (timedJobStartDateInput instanceof HTMLInputElement) {
    timedJobStartDateInput.value = typeof job.start_date === "string" && job.start_date ? job.start_date : todayDateInputValue();
  }
  if (timedJobTimeInput instanceof HTMLInputElement) {
    timedJobTimeInput.value = typeof job.time_of_day === "string" && job.time_of_day ? job.time_of_day.slice(0, 5) : "09:00";
  }
  if (timedJobEnabledInput instanceof HTMLInputElement) {
    timedJobEnabledInput.checked = Boolean(job.enabled);
  }
  if (timedJobOutputDecisionEnabledInput instanceof HTMLInputElement) {
    timedJobOutputDecisionEnabledInput.checked = Boolean(job.output_decision_enabled);
  }
  const selectedProviderId = renderTimedJobProviderOptions(typeof job.provider_id === "string" ? job.provider_id : "");
  renderTimedJobModelOptions(selectedProviderId, typeof job.model === "string" ? job.model : "");
  renderTimedJobChannelOptions(Array.isArray(job.channels) ? job.channels : ["gateway"]);
}

function formatTimedJobMeta(job) {
  const interval = typeof job.interval === "string" ? job.interval : "daily";
  const nextRun = typeof job.next_run_at === "string" && job.next_run_at
    ? formatMessageTimestamp(job.next_run_at)
    : "-";
  const channels = Array.isArray(job.channels) && job.channels.length > 0
    ? job.channels.join(", ")
    : "gateway";
  const status = job.enabled ? "enabled" : "disabled";
  const outputMode = job.output_decision_enabled ? "output: AI decision" : "output: always";
  const providerModel = job.provider_id
    ? `${job.provider_id}${job.model ? `/${job.model}` : ""}`
    : "active provider/model";
  return `${interval} | ${status} | next: ${nextRun} | channels: ${channels} | run: ${providerModel} | ${outputMode}`;
}

function isTimedJobExpanded(jobId) {
  return Boolean(state.expandedTimedJobIds[String(jobId || "")]);
}

function setTimedJobExpanded(jobId, expanded) {
  const normalizedJobId = String(jobId || "").trim();
  if (!normalizedJobId) {
    return;
  }
  if (expanded) {
    state.expandedTimedJobIds[normalizedJobId] = true;
    return;
  }
  delete state.expandedTimedJobIds[normalizedJobId];
}

export function renderTimedJobsList() {
  if (!(timedJobsListNode instanceof HTMLElement)) {
    return;
  }
  timedJobsListNode.innerHTML = "";
  if (!Array.isArray(state.timedJobs) || state.timedJobs.length === 0) {
    const emptyNode = document.createElement("p");
    emptyNode.className = "memory-modal-empty";
    emptyNode.textContent = "No timed jobs yet.";
    timedJobsListNode.appendChild(emptyNode);
    return;
  }

  state.timedJobs.forEach((job) => {
    const isExpanded = isTimedJobExpanded(job.id);
    const card = document.createElement("article");
    card.className = "timed-job-item";
    card.dataset.timedJobId = job.id;
    card.classList.toggle("is-expanded", isExpanded);

    const titleRow = document.createElement("div");
    titleRow.className = "timed-job-item-row";

    const titleNode = document.createElement("button");
    titleNode.type = "button";
    titleNode.className = "timed-job-item-title";
    titleNode.textContent = job.title || "Untitled timed job";
    titleNode.dataset.timedJobAction = "toggle-expand";
    titleNode.dataset.timedJobId = job.id;
    titleNode.setAttribute("aria-expanded", isExpanded ? "true" : "false");

    const actions = document.createElement("div");
    actions.className = "short-term-item-actions";

    const triggerNowButton = document.createElement("button");
    triggerNowButton.type = "button";
    triggerNowButton.className = "timed-job-trigger-link";
    triggerNowButton.dataset.timedJobAction = "trigger-now";
    triggerNowButton.dataset.timedJobId = job.id;
    triggerNowButton.textContent = "trigger";

    const editButton = document.createElement("button");
    editButton.type = "button";
    editButton.className = "chat-history-action-btn";
    editButton.dataset.timedJobAction = "edit";
    editButton.dataset.timedJobId = job.id;
    editButton.setAttribute("aria-label", "Edit timed job");
    editButton.textContent = "\u270E";

    const deleteButton = document.createElement("button");
    deleteButton.type = "button";
    deleteButton.className = "chat-history-action-btn danger";
    deleteButton.dataset.timedJobAction = "delete";
    deleteButton.dataset.timedJobId = job.id;
    deleteButton.setAttribute("aria-label", "Delete timed job");
    deleteButton.textContent = "\u00D7";

    actions.appendChild(triggerNowButton);
    actions.appendChild(editButton);
    actions.appendChild(deleteButton);
    titleRow.appendChild(titleNode);
    titleRow.appendChild(actions);

    const metaNode = document.createElement("p");
    metaNode.className = "timed-job-item-meta";
    metaNode.textContent = formatTimedJobMeta(job);

    const promptNode = document.createElement("p");
    promptNode.className = "short-term-item-content";
    promptNode.textContent = job.prompt || "(No prompt)";

    const detailsNode = document.createElement("div");
    detailsNode.className = "timed-job-item-details";
    detailsNode.classList.toggle("hidden", !isExpanded);
    detailsNode.appendChild(promptNode);

    card.appendChild(titleRow);
    card.appendChild(metaNode);
    card.appendChild(detailsNode);
    timedJobsListNode.appendChild(card);
  });
}

async function fetchTimedJobs() {
  const response = await fetch("/api/timed-jobs", { cache: "no-store" });
  if (!response.ok) {
    throw new Error(await buildHttpErrorDetail(response, "Failed to load timed jobs."));
  }
  return response.json();
}

function collectTimedJobPayload() {
  const title = timedJobTitleInput instanceof HTMLInputElement ? timedJobTitleInput.value.trim() : "";
  const prompt = timedJobPromptInput instanceof HTMLTextAreaElement ? timedJobPromptInput.value.trim() : "";
  const interval = timedJobIntervalSelect instanceof HTMLSelectElement ? timedJobIntervalSelect.value : "daily";
  const startDate = timedJobStartDateInput instanceof HTMLInputElement ? timedJobStartDateInput.value : "";
  const timeOfDay = timedJobTimeInput instanceof HTMLInputElement ? timedJobTimeInput.value : "";
  const providerId = timedJobProviderSelect instanceof HTMLSelectElement ? timedJobProviderSelect.value.trim() : "";
  const model = timedJobModelSelect instanceof HTMLSelectElement ? timedJobModelSelect.value.trim() : "";
  const enabled = timedJobEnabledInput instanceof HTMLInputElement ? timedJobEnabledInput.checked : false;
  const outputDecisionEnabled =
    timedJobOutputDecisionEnabledInput instanceof HTMLInputElement ? timedJobOutputDecisionEnabledInput.checked : false;

  const channels = [];
  if (timedJobChannelsNode instanceof HTMLElement) {
    const checkboxes = timedJobChannelsNode.querySelectorAll("input[type='checkbox'][data-timed-job-channel-id]");
    checkboxes.forEach((checkbox) => {
      if (!(checkbox instanceof HTMLInputElement)) {
        return;
      }
      if (checkbox.checked && !checkbox.disabled && checkbox.dataset.timedJobChannelId) {
        channels.push(checkbox.dataset.timedJobChannelId);
      }
    });
  }

  return {
    title,
    prompt,
    interval,
    start_date: startDate,
    time_of_day: timeOfDay,
    enabled,
    output_decision_enabled: outputDecisionEnabled,
    channels,
    provider_id: providerId,
    model: providerId ? model : "",
  };
}

export async function saveTimedJob() {
  const payload = collectTimedJobPayload();
  if (!payload.prompt) {
    setStatus("Timed job prompt is required.", true);
    return;
  }
  if (!payload.start_date) {
    setStatus("Timed job start date is required.", true);
    return;
  }
  if (!payload.time_of_day) {
    setStatus("Timed job time is required.", true);
    return;
  }
  if (!Array.isArray(payload.channels) || payload.channels.length === 0) {
    setStatus("Select at least one output channel.", true);
    return;
  }

  const method = state.timedJobEditingId ? "PUT" : "POST";
  const path = state.timedJobEditingId ? `/api/timed-jobs/${encodeURIComponent(state.timedJobEditingId)}` : "/api/timed-jobs";
  const response = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(await buildHttpErrorDetail(response, "Failed to save timed job."));
  }
}

export async function deleteTimedJob(jobId) {
  const response = await fetch(`/api/timed-jobs/${encodeURIComponent(jobId)}`, { method: "DELETE" });
  if (!response.ok) {
    throw new Error(await buildHttpErrorDetail(response, "Failed to delete timed job."));
  }
}

async function triggerTimedJobNow(jobId) {
  const response = await fetch(`/api/timed-jobs/${encodeURIComponent(jobId)}/trigger`, { method: "POST" });
  if (!response.ok) {
    throw new Error(await buildHttpErrorDetail(response, "Failed to trigger timed job."));
  }
}

export async function loadTimedJobs(renderModal = false) {
  try {
    const payload = await fetchTimedJobs();
    state.timedJobs = normalizeIncomingTimedJobs(payload.jobs);
    state.timedJobChannels = normalizeTimedJobChannels(payload.channels);
    if (renderModal) {
      renderTimedJobChannelOptions(Array.isArray(collectTimedJobPayload().channels) ? collectTimedJobPayload().channels : ["gateway"]);
      renderTimedJobsList();
      if (timedJobsMetaNode instanceof HTMLElement) {
        timedJobsMetaNode.textContent = `${state.timedJobs.length} jobs configured.`;
      }
    }
  } catch (error) {
    if (renderModal && timedJobsMetaNode instanceof HTMLElement) {
      timedJobsMetaNode.textContent = normalizeErrorMessage(error, "Failed to load timed jobs.");
    }
    if (renderModal) {
      throw error;
    }
  }
}

export async function refreshTimedJobsAfterMcpUsage(toolUsage) {
  if (!Array.isArray(toolUsage) || toolUsage.length === 0) {
    return;
  }
  const usedTimedJobsMcp = toolUsage.some(
    (entry) => entry && typeof entry === "object" && String(entry.mcp_id || "") === "timed_jobs",
  );
  if (!usedTimedJobsMcp) {
    return;
  }
  const renderModal = timedJobsModal instanceof HTMLElement && !timedJobsModal.classList.contains("hidden");
  await loadTimedJobs(renderModal);
}

export async function refreshScriptsAfterMcpUsage(toolUsage) {
  if (!Array.isArray(toolUsage) || toolUsage.length === 0) {
    return;
  }
  const usedScriptsMcp = toolUsage.some((entry) => {
    if (!entry || typeof entry !== "object") {
      return false;
    }
    if (String(entry.mcp_id || "") !== "scripts") {
      return false;
    }
    const toolId = String(entry.tool_id || "");
    return (
      toolId === "create_script"
      || toolId === "edit_script"
      || toolId === "check_script_requirements"
      || toolId === "install_script_requirements"
      || toolId === "execute_script"
      || toolId === "remove_script"
    );
  });
  if (!usedScriptsMcp) {
    return;
  }

  const { normalizeScriptTitles, normalizeScriptsCatalog } = await import("./scripts.js");
  const { renderMcpPanel } = await import("./mcp-panel.js");
  const response = await fetch("/api/mcps/scripts", { cache: "no-store" });
  if (!response.ok) {
    throw new Error(await buildHttpErrorDetail(response, "Failed to refresh scripts list."));
  }
  const payload = await response.json();
  state.scriptTitles = normalizeScriptTitles(payload?.titles);
  state.scripts = normalizeScriptsCatalog(payload?.scripts);
  renderMcpPanel();
}

export async function openTimedJobsModal() {
  if (!(timedJobsModal instanceof HTMLElement)) {
    return;
  }
  resetTimedJobEditor();
  timedJobsModal.classList.remove("hidden");
  document.body.style.overflow = "hidden";
  startTimedJobsClock();
  await loadTimedJobs(true);
  if (timedJobsCloseButton instanceof HTMLButtonElement) {
    timedJobsCloseButton.focus({ preventScroll: true });
  }
}

export function closeTimedJobsModal() {
  if (!(timedJobsModal instanceof HTMLElement)) {
    return;
  }
  timedJobsModal.classList.add("hidden");
  stopTimedJobsClock();
  if (
    (!(memoryModal instanceof HTMLElement) || memoryModal.classList.contains("hidden"))
    && (!(brainModal instanceof HTMLElement) || brainModal.classList.contains("hidden"))
    && (!(shortTermMemoryModal instanceof HTMLElement) || shortTermMemoryModal.classList.contains("hidden"))
    && (!(tokenUsageModal instanceof HTMLElement) || tokenUsageModal.classList.contains("hidden"))
    && (!(changePasswordModal instanceof HTMLElement) || changePasswordModal.classList.contains("hidden"))
    && (!state.mobileLeftDrawerOpen && !state.mobileRightDrawerOpen)
  ) {
    document.body.style.overflow = "";
  }
}

export async function handleTimedJobsListAction(event) {
  const target = event.target;
  if (!(target instanceof HTMLElement)) {
    return;
  }
  const actionNode = target.closest("[data-timed-job-action][data-timed-job-id]");
  if (!(actionNode instanceof HTMLElement)) {
    return;
  }
  const action = actionNode.dataset.timedJobAction;
  const jobId = actionNode.dataset.timedJobId;
  if (!action || !jobId) {
    return;
  }

  const job = state.timedJobs.find((entry) => entry.id === jobId);
  if (!job) {
    return;
  }

  if (action === "edit") {
    populateTimedJobEditor(job);
    renderTimedJobsList();
    setStatus("Editing timed job.");
    return;
  }

  if (action === "toggle-expand") {
    setTimedJobExpanded(jobId, !isTimedJobExpanded(jobId));
    renderTimedJobsList();
    return;
  }

  if (action === "delete") {
    try {
      await deleteTimedJob(jobId);
      await loadTimedJobs(true);
      if (state.timedJobEditingId === jobId) {
        resetTimedJobEditor();
      }
      setStatus("Timed job deleted.");
    } catch (error) {
      setStatus(normalizeErrorMessage(error, "Timed job delete failed."), true);
    }
    return;
  }

  if (action === "trigger-now") {
    try {
      await triggerTimedJobNow(jobId);
      setStatus("Timed job triggered now.");
      window.setTimeout(() => {
        loadTimedJobs(true).catch(() => {});
      }, 600);
    } catch (error) {
      setStatus(normalizeErrorMessage(error, "Timed job trigger failed."), true);
    }
  }
}

export function toggleTimedJobExpand(jobId) {
  setTimedJobExpanded(jobId, !isTimedJobExpanded(jobId));
  renderTimedJobsList();
}
