/*
 * Token-usage helpers: daily counters, usage chart modal, filters.
 */

import { state } from "./state.js";
import {
  tokenCounterNode,
  tokenCounterTotalNode,
  tokenUsageModal,
  tokenUsageBackdrop,
  tokenUsageCloseButton,
  tokenUsageMetaNode,
  tokenUsageRangeSelect,
  tokenUsageFromInput,
  tokenUsageToInput,
  tokenUsageIncludeZeroInput,
  tokenUsageTotalNode,
  tokenUsageAverageNode,
  tokenUsagePeakNode,
  tokenUsageChartNode,
  memoryModal,
  brainModal,
  timedJobsModal,
  shortTermMemoryModal,
  changePasswordModal,
} from "./dom.js";
import { getServerDate, formatNumber, buildHttpErrorDetail } from "./utils.js";

/* ── local helper (not yet extracted to its own module) ── */
function getActiveChat() {
  return state.chats.find((chat) => chat.id === state.activeChatId) ?? null;
}

/* ── date-key helpers ── */

export function getTodayDateKey() {
  const now = getServerDate();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}


export function addDaysToDateKey(dateKey, daysDelta) {
  const parts = String(dateKey || "").split("-");
  if (parts.length !== 3) {
    return "";
  }
  const year = Number(parts[0]);
  const month = Number(parts[1]);
  const day = Number(parts[2]);
  if (!Number.isFinite(year) || !Number.isFinite(month) || !Number.isFinite(day)) {
    return "";
  }
  const date = new Date(Date.UTC(year, month - 1, day));
  date.setUTCDate(date.getUTCDate() + Number(daysDelta || 0));
  const yyyy = String(date.getUTCFullYear());
  const mm = String(date.getUTCMonth() + 1).padStart(2, "0");
  const dd = String(date.getUTCDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

export function formatDateShort(dateKey) {
  const parts = String(dateKey || "").split("-");
  if (parts.length !== 3) {
    return dateKey;
  }
  return `${parts[2]}.${parts[1]}`;
}

export function normalizeDailyTokenUsage(rawUsage) {
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

/* ── daily-usage accumulator ── */

export async function addDailyTokenUsage(tokensToAdd) {
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

  const { updateDailyTokenUsageLabel } = await import("./header.js");
  updateDailyTokenUsageLabel();
}

export function updateTokenCounter(usedTokens = state.usedTokens, tokenLimit = state.modelTokenLimit) {
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

/* ── chart data builder ── */

export function buildTokenUsageSeries() {
  const usageMap = new Map();
  state.dailyTokenUsage.forEach((entry) => {
    const dateKey = typeof entry?.date === "string" ? entry.date.trim() : "";
    const tokens = Math.max(0, Number(entry?.tokens || 0));
    if (!dateKey) {
      return;
    }
    usageMap.set(dateKey, Math.floor(tokens));
  });

  const mode = String(state.tokenUsageRangeMode || "7");
  const includeZeroDays = Boolean(state.tokenUsageIncludeZeroDays);
  let points = [];
  if (mode === "custom") {
    const from = String(state.tokenUsageCustomFrom || "").trim();
    const to = String(state.tokenUsageCustomTo || "").trim();
    if (from && to && from <= to) {
      let current = from;
      let guard = 0;
      while (current && current <= to && guard < 370) {
        points.push({ date: current, tokens: usageMap.get(current) || 0 });
        current = addDaysToDateKey(current, 1);
        guard += 1;
      }
    }
  } else {
    const days = Math.max(1, Math.min(365, Number.parseInt(mode, 10) || 7));
    const today = getTodayDateKey();
    for (let index = days - 1; index >= 0; index -= 1) {
      const dateKey = addDaysToDateKey(today, -index);
      points.push({ date: dateKey, tokens: usageMap.get(dateKey) || 0 });
    }
  }

  if (!includeZeroDays) {
    points = points.filter((entry) => Number(entry.tokens) > 0);
  }

  return points;
}

/* ── modal rendering ── */

export function renderTokenUsageModal() {
  if (!(tokenUsageChartNode instanceof HTMLElement)) {
    return;
  }
  const points = buildTokenUsageSeries();
  tokenUsageChartNode.innerHTML = "";

  if (tokenUsageRangeSelect instanceof HTMLSelectElement) {
    tokenUsageRangeSelect.value = state.tokenUsageRangeMode;
  }
  const customMode = state.tokenUsageRangeMode === "custom";
  if (tokenUsageFromInput instanceof HTMLInputElement) {
    tokenUsageFromInput.value = state.tokenUsageCustomFrom;
    tokenUsageFromInput.disabled = !customMode;
  }
  if (tokenUsageToInput instanceof HTMLInputElement) {
    tokenUsageToInput.value = state.tokenUsageCustomTo;
    tokenUsageToInput.disabled = !customMode;
  }
  if (tokenUsageIncludeZeroInput instanceof HTMLInputElement) {
    tokenUsageIncludeZeroInput.checked = state.tokenUsageIncludeZeroDays;
  }

  if (points.length === 0) {
    const emptyNode = document.createElement("p");
    emptyNode.className = "memory-empty";
    emptyNode.textContent = "No token usage data for the selected filter.";
    tokenUsageChartNode.appendChild(emptyNode);
    if (tokenUsageTotalNode instanceof HTMLElement) {
      tokenUsageTotalNode.textContent = "Total: 0";
    }
    if (tokenUsageAverageNode instanceof HTMLElement) {
      tokenUsageAverageNode.textContent = "Avg/day: 0";
    }
    if (tokenUsagePeakNode instanceof HTMLElement) {
      tokenUsagePeakNode.textContent = "Peak: -";
    }
    if (tokenUsageMetaNode instanceof HTMLElement) {
      tokenUsageMetaNode.textContent = "No points to display.";
    }
    return;
  }

  const totalTokens = points.reduce((sum, entry) => sum + Number(entry.tokens || 0), 0);
  const averageTokens = totalTokens / Math.max(1, points.length);
  let peakEntry = points[0];
  points.forEach((entry) => {
    if (Number(entry.tokens) > Number(peakEntry.tokens)) {
      peakEntry = entry;
    }
  });

  const maxTokens = Math.max(1, ...points.map((entry) => Number(entry.tokens || 0)));
  const barsWrap = document.createElement("div");
  barsWrap.className = "token-usage-bars";

  points.forEach((entry) => {
    const barItem = document.createElement("div");
    barItem.className = "token-usage-bar-item";
    const ratio = Number(entry.tokens || 0) / maxTokens;
    barItem.title = `${entry.date}: ${formatNumber(entry.tokens)} tokens`;

    const barNode = document.createElement("div");
    barNode.className = "token-usage-bar";
    barNode.style.height = `${Math.max(2, Math.round(ratio * 100))}%`;

    const valueNode = document.createElement("span");
    valueNode.className = "token-usage-bar-value";
    valueNode.textContent = formatNumber(entry.tokens);

    const labelNode = document.createElement("span");
    labelNode.className = "token-usage-bar-label";
    labelNode.textContent = formatDateShort(entry.date);

    barItem.appendChild(barNode);
    barItem.appendChild(valueNode);
    barItem.appendChild(labelNode);
    barsWrap.appendChild(barItem);
  });

  tokenUsageChartNode.appendChild(barsWrap);
  if (tokenUsageTotalNode instanceof HTMLElement) {
    tokenUsageTotalNode.textContent = `Total: ${formatNumber(totalTokens)}`;
  }
  if (tokenUsageAverageNode instanceof HTMLElement) {
    tokenUsageAverageNode.textContent = `Avg/day: ${formatNumber(Math.round(averageTokens))}`;
  }
  if (tokenUsagePeakNode instanceof HTMLElement) {
    tokenUsagePeakNode.textContent = `Peak: ${formatDateShort(peakEntry.date)} (${formatNumber(peakEntry.tokens)})`;
  }
  if (tokenUsageMetaNode instanceof HTMLElement) {
    tokenUsageMetaNode.textContent = `${points.length} day(s) shown.`;
  }
}

export function openTokenUsageModal() {
  if (!(tokenUsageModal instanceof HTMLElement)) {
    return;
  }
  if (!state.tokenUsageRangeMode) {
    state.tokenUsageRangeMode = "7";
  }
  state.tokenUsageIncludeZeroDays = true;
  renderTokenUsageModal();
  tokenUsageModal.classList.remove("hidden");
  document.body.style.overflow = "hidden";
}

export function closeTokenUsageModal() {
  if (!(tokenUsageModal instanceof HTMLElement)) {
    return;
  }
  tokenUsageModal.classList.add("hidden");
  if (
    (!(memoryModal instanceof HTMLElement) || memoryModal.classList.contains("hidden"))
    && (!(brainModal instanceof HTMLElement) || brainModal.classList.contains("hidden"))
    && (!(timedJobsModal instanceof HTMLElement) || timedJobsModal.classList.contains("hidden"))
    && (!(shortTermMemoryModal instanceof HTMLElement) || shortTermMemoryModal.classList.contains("hidden"))
    && (!(changePasswordModal instanceof HTMLElement) || changePasswordModal.classList.contains("hidden"))
    && (!state.mobileLeftDrawerOpen && !state.mobileRightDrawerOpen)
  ) {
    document.body.style.overflow = "";
  }
}

/* ── filter controls ── */

export function applyTokenUsageFilters() {
  if (tokenUsageRangeSelect instanceof HTMLSelectElement) {
    state.tokenUsageRangeMode = tokenUsageRangeSelect.value || "7";
  }
  if (tokenUsageFromInput instanceof HTMLInputElement) {
    state.tokenUsageCustomFrom = tokenUsageFromInput.value;
  }
  if (tokenUsageToInput instanceof HTMLInputElement) {
    state.tokenUsageCustomTo = tokenUsageToInput.value;
  }
  if (tokenUsageIncludeZeroInput instanceof HTMLInputElement) {
    state.tokenUsageIncludeZeroDays = tokenUsageIncludeZeroInput.checked;
  }
  if (state.tokenUsageRangeMode === "custom") {
    const fallbackTo = getTodayDateKey();
    const fallbackFrom = addDaysToDateKey(fallbackTo, -6);
    if (!state.tokenUsageCustomFrom) {
      state.tokenUsageCustomFrom = fallbackFrom;
    }
    if (!state.tokenUsageCustomTo) {
      state.tokenUsageCustomTo = fallbackTo;
    }
    if (state.tokenUsageCustomFrom > state.tokenUsageCustomTo) {
      const swapFrom = state.tokenUsageCustomTo;
      state.tokenUsageCustomTo = state.tokenUsageCustomFrom;
      state.tokenUsageCustomFrom = swapFrom;
    }
  }
  renderTokenUsageModal();
}
