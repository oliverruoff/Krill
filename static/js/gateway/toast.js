/*
 * Toast messages and browser notification helpers.
 */

import { state } from "./state.js";
import { toastNode, setToastNode } from "./dom.js";
import { normalizeChatTitle } from "./utils.js";
import { themeIconPath } from "./theme.js";

export function showToast(message) {
  let node = toastNode;
  if (!(node instanceof HTMLElement)) {
    const fallbackToast = document.createElement("div");
    fallbackToast.id = "toast";
    fallbackToast.className = "toast hidden";
    fallbackToast.setAttribute("role", "status");
    fallbackToast.setAttribute("aria-live", "polite");
    document.body.appendChild(fallbackToast);
    setToastNode(fallbackToast);
    node = fallbackToast;
  }

  if (state.toastTimerId) {
    window.clearTimeout(state.toastTimerId);
  }

  node.textContent = message;
  node.classList.remove("hidden");
  state.toastTimerId = window.setTimeout(() => {
    node.classList.add("hidden");
    state.toastTimerId = null;
  }, 1800);
}

export function canUseBrowserNotifications() {
  return typeof window !== "undefined" && "Notification" in window;
}

function shouldNotifyForAssistantResponse() {
  return document.visibilityState !== "visible" || document.hidden;
}

export async function requestNotificationPermissionIfNeeded() {
  if (!canUseBrowserNotifications()) {
    return "unsupported";
  }

  if (Notification.permission === "granted" || Notification.permission === "denied") {
    return Notification.permission;
  }

  try {
    return await Notification.requestPermission();
  } catch (error) {
    return "default";
  }
}

export function sendAssistantResponseNotification(chat, assistantMessage) {
  if (!canUseBrowserNotifications() || Notification.permission !== "granted") {
    return;
  }

  if (!shouldNotifyForAssistantResponse()) {
    return;
  }

  const rawBody = typeof assistantMessage?.content === "string" ? assistantMessage.content.trim() : "";
  if (!rawBody) {
    return;
  }

  const preview = rawBody.length > 140 ? `${rawBody.slice(0, 140).trimEnd()}...` : rawBody;
  const chatTitle = chat && typeof chat.title === "string" ? normalizeChatTitle(chat.title) : "New chat";
  const notification = new Notification(`Krill - ${chatTitle}`, {
    body: preview,
    icon: themeIconPath(state.theme),
    tag: `krill-chat-${chat?.id || "default"}`,
  });
  notification.onclick = () => {
    window.focus();
    notification.close();
  };
}
