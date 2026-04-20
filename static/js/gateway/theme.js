/*
 * Theme mode: normalize, apply, toggle, and render labels.
 */

import { state } from "./state.js";
import { themeToggleButton, mobileThemeToggleButton } from "./dom.js";

export function themeIconPath(theme) {
  const normalized = normalizeThemeMode(theme);
  const background = normalized === "business"
    ? "#19324a"
    : normalized === "dark"
      ? "#141c28"
      : "#fff7f3";
  return "data:image/svg+xml," + encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="16" fill="${background}"/><text x="50%" y="54%" text-anchor="middle" dominant-baseline="middle" font-size="40">🦐</text></svg>`
  );
}

export function normalizeThemeMode(value) {
  const v = String(value || "").trim().toLowerCase();
  if (v === "dark") return "dark";
  if (v === "business") return "business";
  return "light";
}

export function renderThemeToggleLabels() {
  const nextModeLabel = state.theme === "light" ? "Dark" : state.theme === "dark" ? "Business" : "Light";
  const buttonLabel = `Switch to ${nextModeLabel} Mode`;
  if (themeToggleButton instanceof HTMLButtonElement) {
    themeToggleButton.innerHTML = `<span class="menu-item-icon" aria-hidden="true">◐</span>${buttonLabel}`;
    themeToggleButton.setAttribute("aria-label", buttonLabel);
    themeToggleButton.title = buttonLabel;
  }
  if (mobileThemeToggleButton instanceof HTMLButtonElement) {
    mobileThemeToggleButton.innerHTML = `<span class="menu-item-icon" aria-hidden="true">◐</span>${buttonLabel}`;
    mobileThemeToggleButton.setAttribute("aria-label", buttonLabel);
    mobileThemeToggleButton.title = buttonLabel;
  }
}

export function applyThemeMode(theme) {
  const normalized = normalizeThemeMode(theme);
  state.theme = normalized;
  document.documentElement.setAttribute("data-theme", normalized);
  try {
    window.localStorage.setItem("krill-theme", normalized);
  } catch (_error) {
    // Ignore localStorage failures (private mode, blocked storage).
  }
  const favicon = document.getElementById("favicon");
  if (favicon) favicon.href = themeIconPath(normalized);
  renderThemeToggleLabels();
}

export async function toggleThemePreference() {
  if (!state.settings) {
    return;
  }

  const { persistSettings } = await import("./chat-sync.js");
  const { showToast } = await import("./toast.js");
  const nextTheme = state.theme === "light" ? "dark" : state.theme === "dark" ? "business" : "light";
  const nextSettings = JSON.parse(JSON.stringify(state.settings));
  nextSettings.theme = nextTheme;
  const persisted = await persistSettings(nextSettings);
  state.settings = persisted;
  applyThemeMode(persisted.theme);
  showToast(`Theme: ${state.theme}`);
}
