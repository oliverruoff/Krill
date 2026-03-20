/*
 * Provider/model selection: load, render, switch, verify, persist.
 */

import { state } from "./state.js";
import { providerSelectNodes, modelSelectNodes, compactButton } from "./dom.js";
import { setStatus } from "./utils.js";

export function getProviderById(providerId) {
  return state.providers.find((provider) => provider.id === providerId);
}

export function getConfiguredProviderIds() {
  return Object.keys(state.settings?.provider_configs ?? {});
}

export function getModelTokenLimit(providerId, modelId) {
  const provider = getProviderById(providerId);
  const model = provider?.models?.find((entry) => entry.id === modelId);
  if (model?.token_limit) {
    return Number(model.token_limit);
  }

  return 0;
}

export function estimateContextTokens(messages, memoryBlock = "") {
  const memoryTokens = Math.ceil((memoryBlock || "").length / 4);
  const historyTokens = messages.reduce((total, item) => {
    const role = typeof item?.role === "string" ? item.role : "";
    const content = typeof item?.content === "string" ? item.content : "";
    if (role !== "user" && role !== "assistant") {
      return total;
    }
    return total + Math.ceil((role.length + content.length) / 4);
  }, 0);
  return Math.max(0, memoryTokens + historyTokens);
}

export async function syncUsedTokensToContext() {
  const { getActiveChat } = await import("./chat-history.js");
  const { updateTokenCounter } = await import("./token-usage.js");
  const activeChat = getActiveChat();
  if (!activeChat) {
    updateTokenCounter(0, state.modelTokenLimit);
    return;
  }

  const estimatedContext = estimateContextTokens(activeChat.messages, activeChat.memory_block || "");
  const contextTokens = Math.max(estimatedContext, Number(state.lastRequestTokens || 0));
  state.usedTokens = Math.max(0, contextTokens);
  updateTokenCounter(state.usedTokens, state.modelTokenLimit);
}

export function shouldCompactForLimit(messages, memoryBlock, tokenLimit) {
  const safeLimit = Math.max(0, Number(tokenLimit || 0));
  if (safeLimit <= 0) {
    return false;
  }

  const observedContext = Math.max(0, Number(state.lastRequestTokens || 0));
  const estimatedContext = estimateContextTokens(messages, memoryBlock);
  const contextTokens = Math.max(observedContext, estimatedContext);
  return contextTokens >= safeLimit * 0.75;
}

export function setSwitchersDisabled(disabled) {
  providerSelectNodes.forEach((selectNode) => {
    selectNode.disabled = disabled;
  });
  modelSelectNodes.forEach((selectNode) => {
    selectNode.disabled = disabled;
  });
}

export function setCompactButtonDisabled(disabled) {
  if (compactButton instanceof HTMLButtonElement) {
    compactButton.disabled = disabled;
  }
}

export function renderProviderSwitcher(selectedProviderId = state.activeProviderId) {
  const configuredProviderIds = getConfiguredProviderIds();
  state.suppressSwitcherEvents = true;
  providerSelectNodes.forEach((selectNode) => {
    selectNode.innerHTML = "";
  });

  configuredProviderIds.forEach((providerId) => {
    const provider = getProviderById(providerId);
    providerSelectNodes.forEach((selectNode) => {
      const option = document.createElement("option");
      option.value = providerId;
      option.textContent = provider?.label ?? providerId;
      selectNode.appendChild(option);
    });
  });

  if (configuredProviderIds.length === 0) {
    providerSelectNodes.forEach((selectNode) => {
      selectNode.value = "";
      selectNode.disabled = true;
    });
    state.suppressSwitcherEvents = false;
    return "";
  }

  const normalizedProvider = configuredProviderIds.includes(selectedProviderId)
    ? selectedProviderId
    : configuredProviderIds[0];
  providerSelectNodes.forEach((selectNode) => {
    selectNode.disabled = false;
    selectNode.value = normalizedProvider;
  });
  state.suppressSwitcherEvents = false;
  return normalizedProvider;
}

export function renderModelSwitcher(providerId, selectedModelId = "") {
  const provider = getProviderById(providerId);
  const configModel = state.settings?.provider_configs?.[providerId]?.model ?? "";
  const modelCandidates = provider?.models ?? [];
  const normalizedSelected = selectedModelId || configModel || modelCandidates[0]?.id || "";

  state.suppressSwitcherEvents = true;
  modelSelectNodes.forEach((selectNode) => {
    selectNode.innerHTML = "";
  });

  modelCandidates.forEach((model) => {
    modelSelectNodes.forEach((selectNode) => {
      const option = document.createElement("option");
      option.value = model.id;
      option.textContent = model.label;
      selectNode.appendChild(option);
    });
  });

  if (normalizedSelected && !modelCandidates.some((model) => model.id === normalizedSelected)) {
    modelSelectNodes.forEach((selectNode) => {
      const customOption = document.createElement("option");
      customOption.value = normalizedSelected;
      customOption.textContent = normalizedSelected;
      selectNode.appendChild(customOption);
    });
  }

  modelSelectNodes.forEach((selectNode) => {
    selectNode.disabled = !providerId;
    if (normalizedSelected) {
      selectNode.value = normalizedSelected;
    }
  });
  state.suppressSwitcherEvents = false;

  const primaryModelSelect = modelSelectNodes[0];
  return (primaryModelSelect instanceof HTMLSelectElement ? primaryModelSelect.value : "") || normalizedSelected;
}

export function syncSwitcherControls() {
  const providerId = renderProviderSwitcher(state.activeProviderId);
  renderModelSwitcher(providerId, state.activeModelId);
}

export async function verifyProviderModel(providerId, modelId, apiKey) {
  const response = await fetch("/api/providers/verify", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      provider_id: providerId,
      model: modelId,
      api_key: apiKey,
    }),
  });

  if (response.ok) {
    return;
  }

  let detail = "Provider verification failed.";
  try {
    const payload = await response.json();
    if (typeof payload.detail === "string" && payload.detail) {
      detail = payload.detail;
    }
  } catch (error) {
    detail = "Provider verification failed.";
  }

  throw new Error(detail);
}

export async function persistActiveProviderModel(providerId, modelId) {
  const response = await fetch("/api/settings/active-provider-model", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      provider_id: providerId,
      model_id: modelId,
    }),
  });

  if (!response.ok) {
    let detail = "Failed to save active provider/model.";
    try {
      const payload = await response.json();
      if (typeof payload.detail === "string" && payload.detail) {
        detail = payload.detail;
      }
    } catch (error) {
      detail = "Failed to save active provider/model.";
    }
    throw new Error(detail);
  }

  return response.json();
}

export async function switchActiveProviderModel(nextProviderId, nextModelId) {
  if (state.isSwitching || !state.settings) {
    return;
  }

  if (!nextProviderId || !nextModelId) {
    setStatus("Please choose a provider and model.", true);
    return;
  }

  const previousProviderId = state.activeProviderId;
  const previousModelId = state.activeModelId;

  state.isSwitching = true;
  setSwitchersDisabled(true);
  setCompactButtonDisabled(true);
    const { setHistoryControlsDisabled } = await import("./runtime-context.js");
  setHistoryControlsDisabled(true);

  try {
    const { getActiveChat } = await import("./chat-history.js");
    const activeChat = getActiveChat();
    const targetLimit = getModelTokenLimit(nextProviderId, nextModelId);
    const currentContextTokens = activeChat
      ? Math.max(Number(state.usedTokens || 0), estimateContextTokens(activeChat.messages, activeChat.memory_block || ""))
      : 0;
    if (targetLimit > 0 && currentContextTokens > targetLimit && activeChat) {
      const { maybeAutoCompact } = await import("./chat-compact.js");
      const compactResult = await maybeAutoCompact(activeChat, "provider/model switch", targetLimit);
      if (!compactResult.ok) {
        throw new Error("Model switch could not be performed because compaction failed.");
      }
    }

    const nextProviderConfig = state.settings.provider_configs?.[nextProviderId];
    if (!nextProviderConfig) {
      throw new Error("Selected provider is not configured.");
    }

    await verifyProviderModel(nextProviderId, nextModelId, nextProviderConfig.api_key || "");
    const persisted = await persistActiveProviderModel(nextProviderId, nextModelId);

    state.settings = persisted;
    const { normalizeDailyTokenUsage } = await import("./chat-sync.js");
    state.dailyTokenUsage = normalizeDailyTokenUsage(persisted.daily_token_usage);
    const { updateDailyTokenUsageLabel } = await import("./header.js");
    updateDailyTokenUsageLabel();
    state.activeProviderId = nextProviderId;
    state.activeModelId = nextModelId;
    state.modelTokenLimit = getModelTokenLimit(nextProviderId, nextModelId);
    state.providerLabel = getProviderById(nextProviderId)?.label ?? nextProviderId;
    state.modelLabel = getProviderById(nextProviderId)?.models?.find((model) => model.id === nextModelId)?.label ?? nextModelId;

    syncSwitcherControls();
    const { updateMetaIndicators, updateAssistantHeader } = await import("./header.js");
    updateMetaIndicators();
    updateAssistantHeader(state.settings);
    await syncUsedTokensToContext();
    setStatus("Active provider/model updated.");
  } catch (error) {
    state.activeProviderId = previousProviderId;
    state.activeModelId = previousModelId;
    syncSwitcherControls();
    const { updateMetaIndicators } = await import("./header.js");
    updateMetaIndicators();
    setStatus(error instanceof Error ? error.message : "Provider switch failed.", true);
  } finally {
    state.isSwitching = false;
    setSwitchersDisabled(state.isCompacting);
    setCompactButtonDisabled(state.isCompacting);
    const { setHistoryControlsDisabled: setHCD } = await import("./runtime-context.js");
    const { updateComposerState } = await import("./chat-render.js");
    setHCD(state.isCompacting);
    updateComposerState();
  }
}
