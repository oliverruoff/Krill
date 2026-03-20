/*
 * WhatsApp contact helpers: normalize, cache, fetch, and sync with retry.
 */

import { state, WHATSAPP_CONTACTS_CACHE_PARAM } from "./state.js";

export function normalizeWhatsappContacts(rawContacts) {
  if (!Array.isArray(rawContacts)) {
    return [];
  }
  const normalized = [];
  const seen = new Set();
  rawContacts.forEach((entry) => {
    if (!entry || typeof entry !== "object") {
      return;
    }
    const number = String(entry.number || "").trim();
    if (!number || seen.has(number)) {
      return;
    }
    seen.add(number);
    const name = String(entry.name || number).trim() || number;
    normalized.push({ number, name });
  });
  return normalized;
}

export function getWhatsappContactsCacheFromConfig() {
  const config = state.mcpConfigs?.whatsapp;
  const params = config && typeof config === "object" && config.params && typeof config.params === "object"
    ? config.params
    : null;
  const raw = params ? String(params[WHATSAPP_CONTACTS_CACHE_PARAM] || "").trim() : "";
  if (!raw) {
    return [];
  }
  try {
    const parsed = JSON.parse(raw);
    return normalizeWhatsappContacts(parsed);
  } catch (_error) {
    return [];
  }
}

export async function persistWhatsappContactsCacheInConfig(contacts) {
  const { ensureMcpConfig } = await import("./mcp-handlers.js");
  const normalized = normalizeWhatsappContacts(contacts);
  const config = ensureMcpConfig("whatsapp");
  const previousRaw = typeof config.params?.[WHATSAPP_CONTACTS_CACHE_PARAM] === "string"
    ? config.params[WHATSAPP_CONTACTS_CACHE_PARAM]
    : "";
  const nextRaw = JSON.stringify(normalized);
  if (previousRaw === nextRaw) {
    return false;
  }
  config.params[WHATSAPP_CONTACTS_CACHE_PARAM] = nextRaw;
  return true;
}

export function hydrateWhatsappContactsFromCache() {
  const cached = getWhatsappContactsCacheFromConfig();
  state.whatsappContacts = cached;
  return cached;
}

export async function fetchWhatsappContactsLive(options = {}) {
  const persistEmpty = options && Object.prototype.hasOwnProperty.call(options, "persistEmpty")
    ? Boolean(options.persistEmpty)
    : true;
  try {
    const response = await fetch("/api/mcps/whatsapp/contacts", { cache: "no-store" });
    if (!response.ok) {
      return { ok: false, contacts: [] };
    }
    const payload = await response.json();
    const contacts = normalizeWhatsappContacts(payload?.contacts);
    state.whatsappContacts = contacts;
    if (contacts.length > 0 || persistEmpty) {
      const cacheChanged = await persistWhatsappContactsCacheInConfig(contacts);
      if (cacheChanged) {
        const { scheduleMcpAutosave } = await import("./mcp-handlers.js");
        scheduleMcpAutosave("whatsapp");
      }
    }
    return { ok: true, contacts };
  } catch (_error) {
    return { ok: false, contacts: [] };
  }
}

export async function fetchWhatsappContacts() {
  const cachedBeforeFetch = Array.isArray(state.whatsappContacts) ? [...state.whatsappContacts] : [];
  const result = await fetchWhatsappContactsLive({ persistEmpty: false });
  if (result.ok) {
    if (result.contacts.length === 0 && cachedBeforeFetch.length > 0) {
      state.whatsappContacts = cachedBeforeFetch;
      return cachedBeforeFetch;
    }
    return result.contacts;
  }
  return state.whatsappContacts;
}

export async function fetchWhatsappRuntimeState() {
  try {
    const response = await fetch("/api/mcps/whatsapp/status", { cache: "no-store" });
    if (!response.ok) {
      return "unknown";
    }
    const payload = await response.json();
    return String(payload?.state || "unknown").toLowerCase();
  } catch (_error) {
    return "unknown";
  }
}

export async function syncWhatsappContactsWithRetry(maxAttempts = 8) {
  const attempts = Number.isFinite(maxAttempts) ? Math.max(1, Math.floor(maxAttempts)) : 8;
  const cachedBeforeSync = Array.isArray(state.whatsappContacts)
    ? [...state.whatsappContacts]
    : [];

  for (let attempt = 0; attempt < attempts; attempt += 1) {
    const liveResult = await fetchWhatsappContactsLive({ persistEmpty: false });
    if (liveResult.ok && liveResult.contacts.length > 0) {
      return { contacts: liveResult.contacts, cacheRetained: false, warning: "" };
    }
    if (liveResult.ok && liveResult.contacts.length === 0) {
      if (cachedBeforeSync.length > 0) {
        state.whatsappContacts = cachedBeforeSync;
        return {
          contacts: state.whatsappContacts,
          cacheRetained: true,
          warning: "Resync returned no contacts. Kept previously cached contacts.",
        };
      }
      return {
        contacts: [],
        cacheRetained: false,
        warning: "No WhatsApp contacts synced yet. Verify WhatsApp is ready, then retry.",
      };
    }

    const runtimeState = await fetchWhatsappRuntimeState();
    if (runtimeState !== "authenticated" && runtimeState !== "initializing") {
      if (cachedBeforeSync.length > 0) {
        state.whatsappContacts = cachedBeforeSync;
        return {
          contacts: state.whatsappContacts,
          cacheRetained: true,
          warning: "WhatsApp is not ready. Kept previously cached contacts.",
        };
      }
      return {
        contacts: state.whatsappContacts,
        cacheRetained: false,
        warning: "No WhatsApp contacts synced yet. Verify WhatsApp is ready, then retry.",
      };
    }
    await new Promise((resolve) => window.setTimeout(resolve, 1000));
  }

  if (cachedBeforeSync.length > 0) {
    state.whatsappContacts = cachedBeforeSync;
    return {
      contacts: state.whatsappContacts,
      cacheRetained: true,
      warning: "Resync timed out before contacts were returned. Kept previously cached contacts.",
    };
  }
  return {
    contacts: state.whatsappContacts,
    cacheRetained: false,
    warning: "No WhatsApp contacts synced yet. Verify WhatsApp is ready, then retry.",
  };
}
