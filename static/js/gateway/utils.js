/*
 * General utility functions: error handling, date/time helpers, ID generators,
 * chat title helpers, status display, input sync.
 */

import { state, CHAT_TITLE_MAX_LENGTH, EDITABLE_CHAT_TITLE_MAX_LENGTH, CHAT_INPUT_MAX_HEIGHT_PX } from "./state.js";
import { statusNode, chatInput } from "./dom.js";

export function syncGatewayViewportHeight() {
  const visualViewportHeight = Number(window.visualViewport?.height);
  const fallbackHeight = Number(window.innerHeight);
  const viewportHeight = Number.isFinite(visualViewportHeight) && visualViewportHeight > 0
    ? visualViewportHeight
    : fallbackHeight;

  if (!Number.isFinite(viewportHeight) || viewportHeight <= 0) {
    return;
  }

  document.documentElement.style.setProperty("--gateway-viewport-height", `${viewportHeight}px`);
}

export function scheduleGatewayViewportSync() {
  syncGatewayViewportHeight();
  window.requestAnimationFrame(() => {
    syncGatewayViewportHeight();
  });
  window.setTimeout(syncGatewayViewportHeight, 120);
  window.setTimeout(syncGatewayViewportHeight, 360);
}

export function setStatus(message, isError = false) {
  statusNode.textContent = message;
  statusNode.className = isError ? "error" : "ok";
}

export function syncChatInputHeight() {
  if (!(chatInput instanceof HTMLTextAreaElement)) {
    return;
  }

  chatInput.style.height = "auto";
  const targetHeight = Math.min(chatInput.scrollHeight, CHAT_INPUT_MAX_HEIGHT_PX);
  chatInput.style.height = `${Math.max(targetHeight, 38)}px`;
  chatInput.style.overflowY = chatInput.scrollHeight > CHAT_INPUT_MAX_HEIGHT_PX ? "auto" : "hidden";
}

export function normalizeErrorMessage(error, fallback = "Request failed.") {
  if (error instanceof DOMException && error.name === "AbortError") {
    return "Request was aborted.";
  }
  if (typeof error?.message === "string" && error.message.trim()) {
    return error.message.trim();
  }
  return fallback;
}

export async function buildHttpErrorDetail(response, fallback = "Request failed.") {
  const statusPart = Number.isFinite(Number(response?.status))
    ? `HTTP ${response.status}${response.statusText ? ` ${response.statusText}` : ""}`
    : "HTTP error";

  let rawBody = "";
  try {
    rawBody = await response.text();
  } catch (error) {
    rawBody = "";
  }

  let detail = "";
  if (rawBody.trim()) {
    try {
      const parsed = JSON.parse(rawBody);
      if (typeof parsed?.detail === "string" && parsed.detail.trim()) {
        detail = parsed.detail.trim();
      } else if (typeof parsed?.error === "string" && parsed.error.trim()) {
        detail = parsed.error.trim();
      } else if (typeof parsed?.message === "string" && parsed.message.trim()) {
        detail = parsed.message.trim();
      } else {
        detail = rawBody.trim();
      }
    } catch (error) {
      detail = rawBody.trim();
    }
  }

  const compactDetail = detail.length > 400 ? `${detail.slice(0, 400)}...` : detail;
  if (compactDetail) {
    return `${fallback} ${statusPart}. ${compactDetail}`;
  }
  return `${fallback} ${statusPart}.`;
}

export function getServerDate(rawValue) {
  const date = rawValue ? new Date(rawValue) : new Date();
  if (Number.isNaN(date.getTime())) {
    return new Date();
  }
  const serverOffsetMs = (state.serverTimezoneOffset || 0) * 60 * 1000;
  const browserOffsetMs = date.getTimezoneOffset() * 60 * 1000;
  return new Date(date.getTime() + serverOffsetMs + browserOffsetMs);
}

export function formatMessageTimestamp(rawValue = "") {
  const date = getServerDate(rawValue);
  const hour = String(date.getHours()).padStart(2, "0");
  const minute = String(date.getMinutes()).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  const year = date.getFullYear();
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const month = months[date.getMonth()];
  const zone = state.serverTimezoneName ? ` (${state.serverTimezoneName})` : "";
  return `${hour}:${minute} ${day}. ${month}. ${year}${zone}`;
}

export function createTimestamp() {
  return new Date().toISOString();
}

export function normalizeChatTitle(rawTitle) {
  if (typeof rawTitle !== "string") {
    return "New chat";
  }

  const trimmed = rawTitle.trim();
  return trimmed || "New chat";
}

export function deriveChatTitle(firstMessage) {
  const normalized = String(firstMessage || "").trim().replace(/\s+/g, " ");
  if (!normalized) {
    return "New chat";
  }

  if (normalized.length <= CHAT_TITLE_MAX_LENGTH) {
    return normalized;
  }

  return `${normalized.slice(0, CHAT_TITLE_MAX_LENGTH).trimEnd()}...`;
}

export function normalizeEditedChatTitle(rawTitle) {
  const normalized = String(rawTitle || "").trim().replace(/\s+/g, " ");
  if (!normalized) {
    return "New chat";
  }

  if (normalized.length <= EDITABLE_CHAT_TITLE_MAX_LENGTH) {
    return normalized;
  }

  return normalized.slice(0, EDITABLE_CHAT_TITLE_MAX_LENGTH).trimEnd();
}

export function createChatId() {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }

  return `chat-${Date.now()}-${Math.random().toString(16).slice(2, 10)}`;
}

export function createLocalRequestId() {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return `local-${crypto.randomUUID()}`;
  }

  return `local-${Date.now()}-${Math.random().toString(16).slice(2, 10)}`;
}

export function createClientEnqueueId() {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return `enqueue-${crypto.randomUUID()}`;
  }

  return `enqueue-${Date.now()}-${Math.random().toString(16).slice(2, 10)}`;
}

export function formatNumber(value) {
  return Number(value || 0).toLocaleString("de-DE");
}

export function buildEnqueueDraftKey(message, pendingImage) {
  const textPart = typeof message === "string" ? message.trim() : "";
  if (!pendingImage || typeof pendingImage !== "object") {
    return textPart;
  }
  const fileName = typeof pendingImage.fileName === "string" ? pendingImage.fileName : "image";
  const mimeType = typeof pendingImage.mimeType === "string" ? pendingImage.mimeType : "image/jpeg";
  const contentBase64 = typeof pendingImage.contentBase64 === "string" ? pendingImage.contentBase64 : "";
  return `${textPart}::${fileName}::${mimeType}::${contentBase64}`;
}
