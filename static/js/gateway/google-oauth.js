/*
 * Google OAuth flow helpers: status, login, label, and setup guide.
 */

import { state } from "./state.js";
import { setStatus } from "./utils.js";

export async function fetchGoogleOauthStatus() {
  const response = await fetch("/api/mcps/google/oauth/status", { cache: "no-store" });
  if (!response.ok) {
    throw new Error("Failed to load Google OAuth status.");
  }
  const payload = await response.json();
  state.googleOauthStatus = payload && typeof payload === "object" ? payload : null;
  return state.googleOauthStatus;
}

export async function startGoogleOauthLogin() {
  const { persistMcpConfigsToSettings } = await import("./mcp-handlers.js");
  await persistMcpConfigsToSettings();
  const popup = window.open("/api/mcps/google/oauth/start", "krill-google-oauth", "width=640,height=760");
  if (!popup) {
    throw new Error("Popup blocked. Allow popups for this site and try again.");
  }

  const previousStatus = JSON.stringify(state.googleOauthStatus || {});

  await new Promise((resolve) => {
    const intervalId = window.setInterval(async () => {
      if (!popup || popup.closed) {
        window.clearInterval(intervalId);
        resolve();
        return;
      }
    }, 1000);
  });

  await fetchGoogleOauthStatus();
  const nextStatus = JSON.stringify(state.googleOauthStatus || {});
  if (previousStatus !== nextStatus) {
    setStatus("Google OAuth status updated.");
  }
  const { renderMcpPanel } = await import("./mcp-panel.js");
  renderMcpPanel();
}

export function getGoogleOauthStatusLabel() {
  if (!state.googleOauthStatus || typeof state.googleOauthStatus !== "object") {
    return "Google: not connected";
  }

  if (state.googleOauthStatus.needs_relogin) {
    const emailValue = typeof state.googleOauthStatus.email === "string" ? state.googleOauthStatus.email.trim() : "";
    const detailValue = typeof state.googleOauthStatus.detail === "string" ? state.googleOauthStatus.detail.trim() : "";
    const baseLabel = emailValue
      ? `Google: relogin required for ${emailValue}`
      : "Google: relogin required";
    return detailValue ? `${baseLabel} - ${detailValue}` : baseLabel;
  }

  if (!state.googleOauthStatus.connected) {
    return "Google: not connected";
  }

  const emailValue = typeof state.googleOauthStatus.email === "string" ? state.googleOauthStatus.email.trim() : "";
  const modeValue = state.googleOauthStatus.access_mode === "read_write" ? "read-write" : "read-only";
  if (emailValue) {
    return `Google: connected as ${emailValue} (${modeValue})`;
  }
  return `Google: connected (${modeValue})`;
}

export function getGoogleSetupGuideItems() {
  return [
    "In Google Cloud Console, open APIs & Services -> Library and enable Gmail API, Google Calendar API, and Google Drive API for your project.",
    "Open Google Cloud Console -> APIs & Services -> Credentials, then click Create Credentials -> OAuth client ID.",
    "Choose Application type: Web application and create the client.",
    "In OAuth client details, go to Authorized redirect URIs, click Add URI, then paste: http://127.0.0.1:8055/api/mcps/google/oauth/callback",
    "Copy the generated Client ID and Client Secret into this tool's fields: Google OAuth Client ID and Google OAuth Client Secret.",
    "Enable this tool, click Login Google, approve access, then click Verify.",
    "If you enable write access (Mail, Calendar & Drive) later, click Relogin once to approve the extra write scopes.",
  ];
}
