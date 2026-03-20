/*
 * Theme mode: normalize, apply, toggle, and render labels.
 */

import { state } from "./state.js";
import { themeToggleButton, mobileThemeToggleButton } from "./dom.js";

export function normalizeThemeMode(value) {
  return String(value || "").trim().toLowerCase() === "dark" ? "dark" : "light";
}

export function renderThemeToggleLabels() {
  const nextModeLabel = state.theme === "dark" ? "Light" : "Dark";
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
  renderThemeToggleLabels();
}

export async function toggleThemePreference() {
  if (!state.settings) {
    return;
  }

  const { persistSettings } = await import("./chat-sync.js");
  const { showToast } = await import("./toast.js");
  const nextTheme = state.theme === "dark" ? "light" : "dark";
  const nextSettings = JSON.parse(JSON.stringify(state.settings));
  nextSettings.theme = nextTheme;
  const persisted = await persistSettings(nextSettings);
  state.settings = persisted;
  applyThemeMode(persisted.theme);
  showToast(`Theme: ${state.theme}`);
}
