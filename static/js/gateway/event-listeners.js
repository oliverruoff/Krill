/*
 * All UI event-listener registrations for the gateway page.
 * This module runs as side-effects at import time — every addEventListener
 * call executes immediately when the module is evaluated.
 */

import { state } from "./state.js";
import {
  chatForm,
  chatInput,
  sendButton,
  stopButton,
  micButton,
  imageUploadButton,
  imageUploadInput,
  menuButton,
  menuPopover,
  compactButton,
  newChatButton,
  chatHistorySearchInput,
  showHiddenTimedJobChatsInput,
  chatHistoryList,
  mobileDrawerBackdrop,
  mobileLeftDrawerHandle,
  mobileRightDrawerHandle,
  mobileSettingsMenuButton,
  mobileSettingsPopover,
  mobileMemoryManagementButton,
  mobileShortTermMemoryButton,
  mobileTimedJobsButton,
  mobileTokenUsageButton,
  mobileChangePasswordButton,
  mobileThemeToggleButton,
  mobileBrainViewButton,
  memoryManagementButton,
  shortTermMemoryButton,
  timedJobsButton,
  tokenUsageButton,
  changePasswordButton,
  themeToggleButton,
  brainViewButton,
  memoryModal,
  memoryModalBackdrop,
  memoryModalCloseButton,
  brainModal,
  brainModalBackdrop,
  brainModalCloseButton,
  brainRefreshButton,
  brainTableList,
  shortTermMemoryModal,
  shortTermMemoryBackdrop,
  shortTermMemoryCloseButton,
  shortTermMemoryRefreshButton,
  shortTermMemoryListNode,
  timedJobsModal,
  timedJobsBackdrop,
  timedJobsCloseButton,
  timedJobSaveButton,
  timedJobResetButton,
  timedJobProviderSelect,
  timedJobsListNode,
  tokenUsageModal,
  tokenUsageBackdrop,
  tokenUsageCloseButton,
  tokenUsageRangeSelect,
  tokenUsageFromInput,
  tokenUsageToInput,
  tokenUsageIncludeZeroInput,
  changePasswordModal,
  changePasswordBackdrop,
  changePasswordCloseButton,
  changePasswordForm,
  mcpList,
  integrationList,
  systemTraceToggleButton,
  headerProviderSelect,
  headerModelSelect,
  mobileLeftProviderSelect,
  mobileLeftModelSelect,
  coreMemorySearchInput,
  normalMemorySearchInput,
  coreMemoryInput,
  normalMemoryInput,
  addCoreMemoryButton,
  addNormalMemoryButton,
  compactCoreMemoryButton,
  compactNormalMemoryButton,
  coreMemoryList,
  normalMemoryList,
} from "./dom.js";
import { setStatus, syncChatInputHeight, normalizeErrorMessage } from "./utils.js";
import { toggleThemePreference } from "./theme.js";
import {
  closeMobileDrawers,
  toggleMobileLeftDrawer,
  toggleMobileRightDrawer,
  handleMobileSwipeStart,
  handleMobileSwipeMove,
  handleMobileSwipeEnd,
  toggleMobileSettingsMenu,
  isMobileDrawerMode,
  syncMobileDrawerUi,
} from "./mobile-drawer.js";
import { toggleSpeechRecognition } from "./speech.js";
import { handleImageUploadInputChange, clearPendingImageAttachment } from "./image-upload.js";
import {
  openMemoryManagementModal,
  closeMemoryManagementModal,
  renderMemoryManagement,
  addMemory,
  deleteMemory,
  startMemoryInlineEdit,
  saveMemoryInlineEdit,
  cancelMemoryInlineEdit,
  updateMemoryEditDraft,
  compactMemoryType,
} from "./memory.js";
import {
  openBrainModal,
  closeBrainModal,
  loadBrainView,
  renderBrainTableList,
  renderSelectedBrainTable,
} from "./brain.js";
import {
  openShortTermMemoryModal,
  closeShortTermMemoryModal,
  loadShortTermMemories as loadShortTermMemory,
  handleShortTermAction,
} from "./short-term-memory.js";
import {
  openTimedJobsModal,
  closeTimedJobsModal,
  saveTimedJob,
  loadTimedJobs,
  resetTimedJobEditor,
  renderTimedJobModelOptions,
  handleTimedJobsListAction,
} from "./timed-jobs.js";
import {
  openTokenUsageModal,
  closeTokenUsageModal,
  applyTokenUsageFilters,
} from "./token-usage.js";
import {
  openChangePasswordModal,
  closeChangePasswordModal,
  handleChangePasswordSubmit,
  setChangePasswordFormEnabled,
} from "./change-password.js";
import {
  renderChatHistory,
  maybeLoadMoreChatHistory,
  deleteChat,
  editChatTitle,
  activateChat,
  startNewChat,
  updateSystemTraceToggleLabel,
} from "./chat-history.js";
import { renderActiveChat } from "./chat-render.js";
import { sendMessage } from "./chat-engine.js";
import { triggerManualCompaction } from "./chat-compact.js";
import { toggleMenu } from "./header.js";
import { handleMcpInputChange, handleMcpActionClick } from "./mcp-handlers.js";
import { renderModelSwitcher, switchActiveProviderModel } from "./providers.js";
import { stopActiveChatExecution } from "./chat-engine.js";
import { toggleSystemTraceVisibility } from "./chat-history.js";
import { ensureVisibleActiveChat } from "./chat-sync.js";

// ---------------------------------------------------------------------------
// Event-listener registrations (copied verbatim from the monolith)
// ---------------------------------------------------------------------------

function initEventListeners() {

if (memoryManagementButton instanceof HTMLButtonElement) {
  memoryManagementButton.addEventListener("click", () => {
    toggleMenu(false);
    openMemoryManagementModal();
  });
}

if (shortTermMemoryButton instanceof HTMLButtonElement) {
  shortTermMemoryButton.addEventListener("click", () => {
    toggleMenu(false);
    openShortTermMemoryModal();
  });
}

if (timedJobsButton instanceof HTMLButtonElement) {
  timedJobsButton.addEventListener("click", async () => {
    toggleMenu(false);
    try {
      await openTimedJobsModal();
    } catch (error) {
      setStatus(normalizeErrorMessage(error, "Failed to open timed jobs."), true);
    }
  });
}

if (tokenUsageButton instanceof HTMLButtonElement) {
  tokenUsageButton.addEventListener("click", () => {
    toggleMenu(false);
    openTokenUsageModal();
  });
}

if (changePasswordButton instanceof HTMLButtonElement) {
  changePasswordButton.addEventListener("click", () => {
    toggleMenu(false);
    openChangePasswordModal();
  });
}

if (themeToggleButton instanceof HTMLButtonElement) {
  themeToggleButton.addEventListener("click", async () => {
    toggleMenu(false);
    try {
      await toggleThemePreference();
    } catch (error) {
      setStatus(normalizeErrorMessage(error, "Failed to switch theme."), true);
    }
  });
}

if (brainViewButton instanceof HTMLButtonElement) {
  brainViewButton.addEventListener("click", () => {
    toggleMenu(false);
    openBrainModal();
  });
}

if (memoryModalCloseButton instanceof HTMLButtonElement) {
  memoryModalCloseButton.addEventListener("click", closeMemoryManagementModal);
}

if (memoryModalBackdrop instanceof HTMLElement) {
  memoryModalBackdrop.addEventListener("click", closeMemoryManagementModal);
}

if (brainModalCloseButton instanceof HTMLButtonElement) {
  brainModalCloseButton.addEventListener("click", closeBrainModal);
}

if (brainModalBackdrop instanceof HTMLElement) {
  brainModalBackdrop.addEventListener("click", closeBrainModal);
}

if (shortTermMemoryCloseButton instanceof HTMLButtonElement) {
  shortTermMemoryCloseButton.addEventListener("click", closeShortTermMemoryModal);
}

if (shortTermMemoryBackdrop instanceof HTMLElement) {
  shortTermMemoryBackdrop.addEventListener("click", closeShortTermMemoryModal);
}

if (timedJobsCloseButton instanceof HTMLButtonElement) {
  timedJobsCloseButton.addEventListener("click", closeTimedJobsModal);
}

if (timedJobsBackdrop instanceof HTMLElement) {
  timedJobsBackdrop.addEventListener("click", closeTimedJobsModal);
}

if (tokenUsageCloseButton instanceof HTMLButtonElement) {
  tokenUsageCloseButton.addEventListener("click", closeTokenUsageModal);
}

if (tokenUsageBackdrop instanceof HTMLElement) {
  tokenUsageBackdrop.addEventListener("click", closeTokenUsageModal);
}

if (changePasswordCloseButton instanceof HTMLButtonElement) {
  changePasswordCloseButton.addEventListener("click", closeChangePasswordModal);
}

if (changePasswordBackdrop instanceof HTMLElement) {
  changePasswordBackdrop.addEventListener("click", closeChangePasswordModal);
}

if (changePasswordForm instanceof HTMLFormElement) {
  changePasswordForm.addEventListener("submit", handleChangePasswordSubmit);
}

if (tokenUsageRangeSelect instanceof HTMLSelectElement) {
  tokenUsageRangeSelect.addEventListener("change", () => {
    applyTokenUsageFilters();
  });
}

if (tokenUsageIncludeZeroInput instanceof HTMLInputElement) {
  tokenUsageIncludeZeroInput.addEventListener("change", () => {
    applyTokenUsageFilters();
  });
}

if (tokenUsageFromInput instanceof HTMLInputElement) {
  tokenUsageFromInput.addEventListener("change", () => {
    if (state.tokenUsageRangeMode === "custom") {
      applyTokenUsageFilters();
    }
  });
}

if (tokenUsageToInput instanceof HTMLInputElement) {
  tokenUsageToInput.addEventListener("change", () => {
    if (state.tokenUsageRangeMode === "custom") {
      applyTokenUsageFilters();
    }
  });
}

if (timedJobSaveButton instanceof HTMLButtonElement) {
  timedJobSaveButton.addEventListener("click", async () => {
    try {
      await saveTimedJob();
      await loadTimedJobs(true);
      resetTimedJobEditor();
      setStatus("Timed job saved.");
    } catch (error) {
      setStatus(normalizeErrorMessage(error, "Timed job save failed."), true);
    }
  });
}

if (timedJobResetButton instanceof HTMLButtonElement) {
  timedJobResetButton.addEventListener("click", () => {
    resetTimedJobEditor();
    setStatus("New timed job form ready.");
  });
}

if (timedJobProviderSelect instanceof HTMLSelectElement) {
  timedJobProviderSelect.addEventListener("change", () => {
    renderTimedJobModelOptions(timedJobProviderSelect.value, "");
  });
}

if (timedJobsListNode instanceof HTMLElement) {
  timedJobsListNode.addEventListener("click", async (event) => {
    await handleTimedJobsListAction(event);
  });
}

if (shortTermMemoryRefreshButton instanceof HTMLButtonElement) {
  shortTermMemoryRefreshButton.addEventListener("click", async () => {
    await loadShortTermMemory(true);
  });
}

if (shortTermMemoryListNode instanceof HTMLElement) {
  shortTermMemoryListNode.addEventListener("click", async (event) => {
    const target = event.target;
    if (!(target instanceof HTMLButtonElement)) {
      return;
    }

    const action = target.dataset.shortTermAction;
    const suggestionId = target.dataset.shortTermId;
    if (!action || !suggestionId) {
      return;
    }
    await handleShortTermAction(action, suggestionId);
  });
}

if (brainRefreshButton instanceof HTMLButtonElement) {
  brainRefreshButton.addEventListener("click", loadBrainView);
}

if (brainTableList instanceof HTMLElement) {
  brainTableList.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLButtonElement)) {
      return;
    }

    const tableName = target.dataset.tableName;
    if (!tableName) {
      return;
    }

    state.selectedBrainTable = tableName;
    renderBrainTableList();
    renderSelectedBrainTable();
  });
}

if (coreMemorySearchInput instanceof HTMLInputElement) {
  coreMemorySearchInput.addEventListener("input", () => {
    state.coreMemorySearchTerm = coreMemorySearchInput.value;
    renderMemoryManagement();
  });
}

if (normalMemorySearchInput instanceof HTMLInputElement) {
  normalMemorySearchInput.addEventListener("input", () => {
    state.normalMemorySearchTerm = normalMemorySearchInput.value;
    renderMemoryManagement();
  });
}

if (addCoreMemoryButton instanceof HTMLButtonElement) {
  addCoreMemoryButton.addEventListener("click", async () => {
    await addMemory("core");
  });
}

if (addNormalMemoryButton instanceof HTMLButtonElement) {
  addNormalMemoryButton.addEventListener("click", async () => {
    await addMemory("normal");
  });
}

if (compactCoreMemoryButton instanceof HTMLButtonElement) {
  compactCoreMemoryButton.addEventListener("click", async () => {
    await compactMemoryType("core");
  });
}

if (compactNormalMemoryButton instanceof HTMLButtonElement) {
  compactNormalMemoryButton.addEventListener("click", async () => {
    await compactMemoryType("normal");
  });
}

if (coreMemoryInput instanceof HTMLInputElement) {
  coreMemoryInput.addEventListener("keydown", async (event) => {
    if (event.key !== "Enter") {
      return;
    }
    event.preventDefault();
    await addMemory("core");
  });
}

if (normalMemoryInput instanceof HTMLInputElement) {
  normalMemoryInput.addEventListener("keydown", async (event) => {
    if (event.key !== "Enter") {
      return;
    }
    event.preventDefault();
    await addMemory("normal");
  });
}

async function handleMemoryListClick(event) {
  const target = event.target;
  if (!(target instanceof HTMLElement)) {
    return;
  }

  const actionable = target.closest("[data-memory-type][data-memory-index][data-memory-action]");
  if (!(actionable instanceof HTMLElement)) {
    return;
  }

  const memoryType = actionable.dataset.memoryType;
  const memoryIndex = actionable.dataset.memoryIndex;
  const memoryAction = actionable.dataset.memoryAction;
  if (!memoryType || typeof memoryIndex !== "string" || !memoryAction) {
    return;
  }

  if (memoryAction === "delete") {
    await deleteMemory(memoryType, memoryIndex);
    return;
  }

  if (memoryAction === "edit") {
    startMemoryInlineEdit(memoryType, memoryIndex);
    return;
  }

  if (memoryAction === "save") {
    await saveMemoryInlineEdit(memoryType, memoryIndex);
    return;
  }

  if (memoryAction === "cancel") {
    cancelMemoryInlineEdit(memoryType);
  }
}

function handleMemoryListInput(event) {
  const target = event.target;
  if (!(target instanceof HTMLTextAreaElement)) {
    return;
  }

  const memoryType = target.dataset.memoryType;
  const memoryAction = target.dataset.memoryAction;
  if (!memoryType || memoryAction !== "draft") {
    return;
  }

  updateMemoryEditDraft(memoryType, target.value);
}

function handleMemoryListKeydown(event) {
  const target = event.target;
  if (!(target instanceof HTMLElement)) {
    return;
  }

  const isEnterOnEditableText =
    (event.key === "Enter" || event.key === " ") &&
    target.dataset.memoryAction === "edit" &&
    target.dataset.memoryType &&
    target.dataset.memoryIndex;

  if (!isEnterOnEditableText) {
    return;
  }

  event.preventDefault();
  startMemoryInlineEdit(target.dataset.memoryType, target.dataset.memoryIndex);
}

if (coreMemoryList instanceof HTMLElement) {
  coreMemoryList.addEventListener("click", handleMemoryListClick);
  coreMemoryList.addEventListener("input", handleMemoryListInput);
  coreMemoryList.addEventListener("keydown", handleMemoryListKeydown);
}

if (normalMemoryList instanceof HTMLElement) {
  normalMemoryList.addEventListener("click", handleMemoryListClick);
  normalMemoryList.addEventListener("input", handleMemoryListInput);
  normalMemoryList.addEventListener("keydown", handleMemoryListKeydown);
}

chatInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    if (!sendButton.disabled) {
      chatForm.requestSubmit();
    }
  }
});

chatInput.addEventListener("input", () => {
  syncChatInputHeight();
});

if (mobileLeftDrawerHandle instanceof HTMLButtonElement) {
  mobileLeftDrawerHandle.addEventListener("click", toggleMobileLeftDrawer);
}

if (mobileRightDrawerHandle instanceof HTMLButtonElement) {
  mobileRightDrawerHandle.addEventListener("click", toggleMobileRightDrawer);
}

if (mobileDrawerBackdrop instanceof HTMLElement) {
  mobileDrawerBackdrop.addEventListener("click", closeMobileDrawers);
}

if (mobileSettingsMenuButton instanceof HTMLButtonElement) {
  mobileSettingsMenuButton.addEventListener("click", () => {
    toggleMobileSettingsMenu();
  });
}

if (mobileMemoryManagementButton instanceof HTMLButtonElement) {
  mobileMemoryManagementButton.addEventListener("click", () => {
    toggleMobileSettingsMenu(false);
    closeMobileDrawers();
    openMemoryManagementModal();
  });
}

if (mobileShortTermMemoryButton instanceof HTMLButtonElement) {
  mobileShortTermMemoryButton.addEventListener("click", () => {
    toggleMobileSettingsMenu(false);
    closeMobileDrawers();
    openShortTermMemoryModal();
  });
}

if (mobileTimedJobsButton instanceof HTMLButtonElement) {
  mobileTimedJobsButton.addEventListener("click", async () => {
    toggleMobileSettingsMenu(false);
    closeMobileDrawers();
    try {
      await openTimedJobsModal();
    } catch (error) {
      setStatus(normalizeErrorMessage(error, "Failed to open timed jobs."), true);
    }
  });
}

if (mobileTokenUsageButton instanceof HTMLButtonElement) {
  mobileTokenUsageButton.addEventListener("click", () => {
    toggleMobileSettingsMenu(false);
    closeMobileDrawers();
    openTokenUsageModal();
  });
}

if (mobileChangePasswordButton instanceof HTMLButtonElement) {
  mobileChangePasswordButton.addEventListener("click", () => {
    toggleMobileSettingsMenu(false);
    closeMobileDrawers();
    openChangePasswordModal();
  });
}

if (mobileThemeToggleButton instanceof HTMLButtonElement) {
  mobileThemeToggleButton.addEventListener("click", async () => {
    toggleMobileSettingsMenu(false);
    closeMobileDrawers();
    try {
      await toggleThemePreference();
    } catch (error) {
      setStatus(normalizeErrorMessage(error, "Failed to switch theme."), true);
    }
  });
}

if (mobileBrainViewButton instanceof HTMLButtonElement) {
  mobileBrainViewButton.addEventListener("click", () => {
    toggleMobileSettingsMenu(false);
    closeMobileDrawers();
    openBrainModal();
  });
}

document.addEventListener("touchstart", handleMobileSwipeStart, { passive: true });
document.addEventListener("touchmove", handleMobileSwipeMove, { passive: false });
document.addEventListener("touchend", handleMobileSwipeEnd, { passive: true });
document.addEventListener("touchcancel", handleMobileSwipeEnd, { passive: true });

window.addEventListener("resize", () => {
  if (!isMobileDrawerMode()) {
    closeMobileDrawers();
  } else {
    syncMobileDrawerUi();
  }
  updateSystemTraceToggleLabel();
});

menuButton.addEventListener("click", () => {
  toggleMenu();
});

document.addEventListener("click", (event) => {
  const target = event.target;
  if (!(target instanceof Node)) {
    return;
  }

  const desktopMenuTargeted = (menuPopover instanceof HTMLElement && menuPopover.contains(target))
    || (menuButton instanceof HTMLButtonElement && menuButton.contains(target));
  if (desktopMenuTargeted) {
    return;
  }

  const mobileMenuTargeted = (mobileSettingsPopover instanceof HTMLElement && mobileSettingsPopover.contains(target))
    || (mobileSettingsMenuButton instanceof HTMLButtonElement && mobileSettingsMenuButton.contains(target));
  if (mobileMenuTargeted) {
    return;
  }

  toggleMenu(false);
  toggleMobileSettingsMenu(false);
});

document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") {
    return;
  }

  if (state.mobileLeftDrawerOpen || state.mobileRightDrawerOpen) {
    toggleMobileSettingsMenu(false);
    closeMobileDrawers();
    return;
  }

  if (mobileSettingsPopover instanceof HTMLElement && !mobileSettingsPopover.classList.contains("hidden")) {
    toggleMobileSettingsMenu(false);
    return;
  }

  if (timedJobsModal instanceof HTMLElement && !timedJobsModal.classList.contains("hidden")) {
    closeTimedJobsModal();
    return;
  }

  if (brainModal instanceof HTMLElement && !brainModal.classList.contains("hidden")) {
    closeBrainModal();
    return;
  }

  if (shortTermMemoryModal instanceof HTMLElement && !shortTermMemoryModal.classList.contains("hidden")) {
    closeShortTermMemoryModal();
    return;
  }

  if (tokenUsageModal instanceof HTMLElement && !tokenUsageModal.classList.contains("hidden")) {
    closeTokenUsageModal();
    return;
  }

  if (changePasswordModal instanceof HTMLElement && !changePasswordModal.classList.contains("hidden")) {
    closeChangePasswordModal();
    return;
  }

  if (memoryModal instanceof HTMLElement && !memoryModal.classList.contains("hidden")) {
    closeMemoryManagementModal();
  }
});

menuPopover.addEventListener("click", () => {
  toggleMenu(false);
});

async function handleProviderSelectChange(providerId) {
  if (state.suppressSwitcherEvents) {
    return;
  }

  const nextProviderId = providerId;
  const configuredModel = state.settings?.provider_configs?.[nextProviderId]?.model ?? "";
  const nextModelId = renderModelSwitcher(nextProviderId, configuredModel);
  await switchActiveProviderModel(nextProviderId, nextModelId);
}

async function handleModelSelectChange(providerId, modelId) {
  if (state.suppressSwitcherEvents) {
    return;
  }

  const nextProviderId = providerId;
  const nextModelId = modelId;
  await switchActiveProviderModel(nextProviderId, nextModelId);
}

if (headerProviderSelect instanceof HTMLSelectElement) {
  headerProviderSelect.addEventListener("change", async () => {
    await handleProviderSelectChange(headerProviderSelect.value);
  });
}

if (mobileLeftProviderSelect instanceof HTMLSelectElement) {
  mobileLeftProviderSelect.addEventListener("change", async () => {
    await handleProviderSelectChange(mobileLeftProviderSelect.value);
  });
}

if (headerModelSelect instanceof HTMLSelectElement) {
  headerModelSelect.addEventListener("change", async () => {
    const providerFromTopbar = headerProviderSelect instanceof HTMLSelectElement
      ? headerProviderSelect.value
      : state.activeProviderId;
    await handleModelSelectChange(providerFromTopbar, headerModelSelect.value);
  });
}

if (mobileLeftModelSelect instanceof HTMLSelectElement) {
  mobileLeftModelSelect.addEventListener("change", async () => {
    const providerFromLeftPanel = mobileLeftProviderSelect instanceof HTMLSelectElement
      ? mobileLeftProviderSelect.value
      : state.activeProviderId;
    await handleModelSelectChange(providerFromLeftPanel, mobileLeftModelSelect.value);
  });
}

if (compactButton instanceof HTMLButtonElement) {
  compactButton.addEventListener("click", triggerManualCompaction);
}

if (newChatButton instanceof HTMLButtonElement) {
  newChatButton.addEventListener("click", startNewChat);
}

if (chatHistorySearchInput instanceof HTMLInputElement) {
  chatHistorySearchInput.addEventListener("input", () => {
    state.chatHistorySearchTerm = chatHistorySearchInput.value || "";
    renderChatHistory();
  });
}

if (showHiddenTimedJobChatsInput instanceof HTMLInputElement) {
  showHiddenTimedJobChatsInput.addEventListener("change", () => {
    state.showHiddenTimedJobChats = showHiddenTimedJobChatsInput.checked;
    ensureVisibleActiveChat();
    renderChatHistory();
    renderActiveChat();
  });
}

if (stopButton instanceof HTMLButtonElement) {
  stopButton.addEventListener("click", stopActiveChatExecution);
}

if (micButton instanceof HTMLButtonElement) {
  micButton.addEventListener("click", toggleSpeechRecognition);
}

if (imageUploadButton instanceof HTMLButtonElement && imageUploadInput instanceof HTMLInputElement) {
  imageUploadButton.addEventListener("click", () => {
    imageUploadInput.click();
  });
  imageUploadInput.addEventListener("change", async (event) => {
    try {
      await handleImageUploadInputChange(event);
    } catch (error) {
      setStatus(normalizeErrorMessage(error, "Failed to attach image."), true);
      clearPendingImageAttachment();
    }
  });
}

if (systemTraceToggleButton instanceof HTMLButtonElement) {
  systemTraceToggleButton.addEventListener("click", toggleSystemTraceVisibility);
}

if (mcpList instanceof HTMLElement) {
  mcpList.addEventListener("input", handleMcpInputChange);
  mcpList.addEventListener("change", handleMcpInputChange);
  mcpList.addEventListener("click", handleMcpActionClick);
}

if (integrationList instanceof HTMLElement) {
  integrationList.addEventListener("input", handleMcpInputChange);
  integrationList.addEventListener("change", handleMcpInputChange);
  integrationList.addEventListener("click", handleMcpActionClick);
}

chatHistoryList.addEventListener("click", (event) => {
  const target = event.target;
  if (!(target instanceof Node)) {
    return;
  }

  const actionButton = target instanceof HTMLElement ? target.closest("button[data-chat-id][data-action]") : null;
  if (actionButton instanceof HTMLButtonElement) {
    const chatId = actionButton.dataset.chatId;
    const action = actionButton.dataset.action;
    if (!chatId || !action) {
      return;
    }

    if (action === "delete") {
      deleteChat(chatId);
      return;
    }

    if (action === "edit") {
      editChatTitle(chatId);
      return;
    }

    if (action === "open") {
      if (chatId === state.activeChatId) {
        return;
      }
      activateChat(chatId);
      return;
    }
  }

  const chatCard = target instanceof HTMLElement ? target.closest(".chat-history-item[data-chat-id]") : null;
  if (!(chatCard instanceof HTMLElement)) {
    return;
  }

  const chatId = chatCard.dataset.chatId;
  if (!chatId || chatId === state.activeChatId) {
    return;
  }

  activateChat(chatId);
});

chatHistoryList.addEventListener("scroll", () => {
  maybeLoadMoreChatHistory();
});

chatForm.addEventListener("submit", sendMessage);
setChangePasswordFormEnabled(false);

}

export { initEventListeners };
