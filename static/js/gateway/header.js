/*
 * Header / assistant meta indicators and daily-usage label.
 */

import { state } from "./state.js";
import {
  providerIndicator,
  modelIndicator,
  assistantTitleNode,
  assistantMetaNode,
  mobileAssistantNameNode,
  mobileLeftAssistantNameNode,
  dailyTokenUsageNode,
  mobileLeftDailyTokenUsageNode,
  tokenUsageModal,
  menuPopover,
  menuButton,
  appVersionNode,
} from "./dom.js";
import { formatNumber } from "./utils.js";

export function updateMetaIndicators() {
  providerIndicator.textContent = state.providerLabel || "Not configured";
  modelIndicator.textContent = state.modelLabel || "Not configured";
}

export function updateAssistantHeader(settings) {
  const botName = settings?.bot_name?.trim();
  const configuredProviders = Object.keys(settings?.provider_configs ?? {}).length;
  const providerText = configuredProviders === 1 ? "1 provider" : `${configuredProviders} providers`;
  const activeProviderText = state.providerLabel || "No provider selected";
  const modelText = state.modelLabel || "No model selected";

  assistantTitleNode.textContent = botName
    ? `This is ${botName} - your personal assistant`
    : "This is your personal assistant";
  if (mobileAssistantNameNode instanceof HTMLElement) {
    mobileAssistantNameNode.textContent = botName || "Assistant";
  }
  if (mobileLeftAssistantNameNode instanceof HTMLElement) {
    mobileLeftAssistantNameNode.textContent = botName || "Assistant";
  }
  assistantMetaNode.textContent = `${providerText} connected - Active provider: ${activeProviderText} - Active model: ${modelText}`;
}

export function toggleMenu(forceOpen) {
  const shouldOpen = typeof forceOpen === "boolean" ? forceOpen : menuPopover.classList.contains("hidden");
  menuPopover.classList.toggle("hidden", !shouldOpen);
  menuButton.setAttribute("aria-expanded", shouldOpen ? "true" : "false");
}

export async function loadAppVersion() {
  if (!(appVersionNode instanceof HTMLElement)) {
    return;
  }
  try {
    const response = await fetch("/api/version", { cache: "no-store" });
    if (!response.ok) {
      return;
    }
    const payload = await response.json();
    const version = typeof payload?.version === "string" ? payload.version.trim() : "";
    if (version) {
      appVersionNode.textContent = `v${version}`;
    }
    if (typeof payload?.server_timezone === "string") {
      state.serverTimezoneName = payload.server_timezone;
    }
    if (typeof payload?.server_timezone_offset === "number") {
      state.serverTimezoneOffset = payload.server_timezone_offset;
    }
  } catch (error) {
    // Best-effort display only.
  }
}

export async function updateDailyTokenUsageLabel() {
  const hasDesktopNode = dailyTokenUsageNode instanceof HTMLElement;
  const hasMobileNode = mobileLeftDailyTokenUsageNode instanceof HTMLElement;
  if (!hasDesktopNode && !hasMobileNode) {
    return;
  }

  const { getTodayDateKey } = await import("./token-usage.js");
  const today = getTodayDateKey();
  const todayEntry = state.dailyTokenUsage.find((entry) => entry.date === today);
  const tokens = todayEntry ? Number(todayEntry.tokens || 0) : 0;
  const label = `Today: ${formatNumber(tokens)} tokens`;
  if (hasDesktopNode) {
    dailyTokenUsageNode.textContent = label;
  }
  if (hasMobileNode) {
    mobileLeftDailyTokenUsageNode.textContent = label;
  }
  if (tokenUsageModal instanceof HTMLElement && !tokenUsageModal.classList.contains("hidden")) {
    const { renderTokenUsageModal } = await import("./token-usage.js");
    renderTokenUsageModal();
  }
}
