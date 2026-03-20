/*
 * Gateway client: manages chat UI, queueing/stream handling, settings sync,
 * tool/integration panels, and header status indicators.
 */

const CHAT_TITLE_MAX_LENGTH = 24;
const EDITABLE_CHAT_TITLE_MAX_LENGTH = 24;
const CHAT_SYNC_INTERVAL_MS = 5000;
const INTEGRATION_STATUS_SYNC_INTERVAL_MS = 8000;
const RUNTIME_CONTEXT_SYSTEM_TYPE = "runtime_context_seed";
const MEMORY_MAX_LENGTH = 1000000;
const CHAT_HISTORY_PAGE_SIZE = 15;
const CHAT_HISTORY_SCROLL_LOAD_THRESHOLD_PX = 120;
const WHATSAPP_CONTACTS_CACHE_PARAM = "contacts_cache_json";
const SCRIPTS_DISABLED_TITLES_PARAM = "disabled_script_titles";

const chatForm = document.getElementById("chat-form");
const chatInput = document.getElementById("chat-input");
const sendButton = document.getElementById("send-btn");
const stopButton = document.getElementById("stop-btn");
const micButton = document.getElementById("mic-btn");
const imageUploadButton = document.getElementById("image-upload-btn");
const imageUploadInput = document.getElementById("image-upload-input");
const imageAttachmentPreview = document.getElementById("image-attachment-preview");
const chatThread = document.getElementById("chat-thread");
const providerIndicator = document.getElementById("provider-indicator");
const modelIndicator = document.getElementById("model-indicator");
const systemTraceToggleButton = document.getElementById("system-trace-toggle");
const tokenCounterNode = document.getElementById("token-counter");
const tokenCounterTotalNode = document.getElementById("token-counter-total");
const statusNode = document.getElementById("status");
const timedJobAuthAlertNode = document.getElementById("timed-job-auth-alert");
const menuButton = document.getElementById("menu-btn");
const menuPopover = document.getElementById("menu-popover");
const assistantTitleNode = document.getElementById("assistant-title");
const assistantMetaNode = document.getElementById("assistant-meta");
const mobileAssistantNameNode = document.getElementById("mobile-assistant-name");
const mobileLeftAssistantNameNode = document.getElementById("mobile-left-assistant-name");
const dailyTokenUsageNode = document.getElementById("daily-token-usage");
const mobileLeftDailyTokenUsageNode = document.getElementById("mobile-left-daily-token-usage");
const telegramStatusNode = document.getElementById("telegram-status");
const shortTermMemoryStatusNode = document.getElementById("short-term-memory-status");
const mobileLeftShortTermMemoryStatusNode = document.getElementById("mobile-left-short-term-memory-status");
const appVersionNode = document.getElementById("app-version");
const headerProviderSelect = document.getElementById("header-provider-select");
const headerModelSelect = document.getElementById("header-model-select");
const mobileLeftProviderSelect = document.getElementById("mobile-left-provider-select");
const mobileLeftModelSelect = document.getElementById("mobile-left-model-select");
const compactButton = document.getElementById("compact-btn");
const currentChatTitleNode = document.getElementById("current-chat-title");
const chatHistoryList = document.getElementById("chat-history-list");
const chatHistorySearchInput = document.getElementById("chat-history-search");
const showHiddenTimedJobChatsInput = document.getElementById("show-hidden-timed-job-chats");
const newChatButton = document.getElementById("new-chat-btn");
const mcpList = document.getElementById("mcp-list");
const integrationList = document.getElementById("integration-list");
const gatewayShell = document.querySelector(".gateway-shell");
const gatewayTopbar = document.querySelector(".gateway-topbar");
const chatHistoryPanel = document.querySelector(".chat-history-panel");
const mcpSidePanel = document.querySelector(".mcp-side-panel");
const mobileDrawerBackdrop = document.getElementById("mobile-drawer-backdrop");
const mobileLeftDrawerHandle = document.getElementById("mobile-left-drawer-handle");
const mobileRightDrawerHandle = document.getElementById("mobile-right-drawer-handle");
const mobileSettingsMenuButton = document.getElementById("mobile-settings-menu-btn");
const mobileSettingsPopover = document.getElementById("mobile-settings-popover");
const mobileMemoryManagementButton = document.getElementById("mobile-memory-management-btn");
const mobileShortTermMemoryButton = document.getElementById("mobile-short-term-memory-btn");
const mobileTimedJobsButton = document.getElementById("mobile-timed-jobs-btn");
const mobileTokenUsageButton = document.getElementById("mobile-token-usage-btn");
const mobileChangePasswordButton = document.getElementById("mobile-change-password-btn");
const mobileThemeToggleButton = document.getElementById("mobile-theme-toggle-btn");
const mobileBrainViewButton = document.getElementById("mobile-brain-view-btn");
const memoryManagementButton = document.getElementById("memory-management-btn");
const shortTermMemoryButton = document.getElementById("short-term-memory-btn");
const timedJobsButton = document.getElementById("timed-jobs-btn");
const tokenUsageButton = document.getElementById("token-usage-btn");
const changePasswordButton = document.getElementById("change-password-btn");
const themeToggleButton = document.getElementById("theme-toggle-btn");
const brainViewButton = document.getElementById("brain-view-btn");
const memoryModal = document.getElementById("memory-modal");
const memoryModalBackdrop = document.getElementById("memory-modal-backdrop");
const memoryModalCloseButton = document.getElementById("memory-modal-close");
const brainModal = document.getElementById("brain-modal");
const brainModalBackdrop = document.getElementById("brain-modal-backdrop");
const brainModalCloseButton = document.getElementById("brain-modal-close");
const brainModalMetaNode = document.getElementById("brain-modal-meta");
const brainRefreshButton = document.getElementById("brain-refresh-btn");
const brainTableList = document.getElementById("brain-table-list");
const brainTableTitle = document.getElementById("brain-table-title");
const brainTableColumns = document.getElementById("brain-table-columns");
const brainTableView = document.getElementById("brain-table-view");
const shortTermMemoryModal = document.getElementById("short-term-memory-modal");
const shortTermMemoryBackdrop = document.getElementById("short-term-memory-backdrop");
const shortTermMemoryCloseButton = document.getElementById("short-term-memory-close");
const shortTermMemoryMetaNode = document.getElementById("short-term-memory-meta");
const shortTermMemoryRefreshButton = document.getElementById("short-term-memory-refresh");
const shortTermMemoryListNode = document.getElementById("short-term-memory-list");
const timedJobsModal = document.getElementById("timed-jobs-modal");
const timedJobsBackdrop = document.getElementById("timed-jobs-backdrop");
const timedJobsCloseButton = document.getElementById("timed-jobs-close");
const timedJobsMetaNode = document.getElementById("timed-jobs-meta");
const timedJobsNowNode = document.getElementById("timed-jobs-now");
const timedJobsListNode = document.getElementById("timed-jobs-list");
const timedJobTitleInput = document.getElementById("timed-job-title");
const timedJobPromptInput = document.getElementById("timed-job-prompt");
const timedJobIntervalSelect = document.getElementById("timed-job-interval");
const timedJobStartDateInput = document.getElementById("timed-job-start-date");
const timedJobTimeInput = document.getElementById("timed-job-time");
const timedJobProviderSelect = document.getElementById("timed-job-provider");
const timedJobModelSelect = document.getElementById("timed-job-model");
const timedJobEnabledInput = document.getElementById("timed-job-enabled");
const timedJobOutputDecisionEnabledInput = document.getElementById("timed-job-output-decision-enabled");
const timedJobChannelsNode = document.getElementById("timed-job-channels");
const timedJobSaveButton = document.getElementById("timed-job-save");
const timedJobResetButton = document.getElementById("timed-job-reset");
const tokenUsageModal = document.getElementById("token-usage-modal");
const tokenUsageBackdrop = document.getElementById("token-usage-backdrop");
const tokenUsageCloseButton = document.getElementById("token-usage-close");
const tokenUsageMetaNode = document.getElementById("token-usage-meta");
const tokenUsageRangeSelect = document.getElementById("token-usage-range");
const tokenUsageFromInput = document.getElementById("token-usage-from");
const tokenUsageToInput = document.getElementById("token-usage-to");
const tokenUsageIncludeZeroInput = document.getElementById("token-usage-include-zero");
const tokenUsageTotalNode = document.getElementById("token-usage-total");
const tokenUsageAverageNode = document.getElementById("token-usage-average");
const tokenUsagePeakNode = document.getElementById("token-usage-peak");
const tokenUsageChartNode = document.getElementById("token-usage-chart");
const changePasswordModal = document.getElementById("change-password-modal");
const changePasswordBackdrop = document.getElementById("change-password-backdrop");
const changePasswordCloseButton = document.getElementById("change-password-close");
const changePasswordForm = document.getElementById("change-password-form");
const changePasswordOldInput = document.getElementById("change-password-old");
const changePasswordNewInput = document.getElementById("change-password-new");
const changePasswordConfirmInput = document.getElementById("change-password-confirm");
const changePasswordSubmitButton = document.getElementById("change-password-submit");
const scriptEditorModal = document.getElementById("script-editor-modal");
const scriptEditorBackdrop = document.getElementById("script-editor-backdrop");
const scriptEditorCloseButton = document.getElementById("script-editor-close");
const scriptEditorTextarea = document.getElementById("script-editor-textarea");
const scriptEditorHighlight = document.getElementById("script-editor-highlight");
const scriptEditorSaveButton = document.getElementById("script-editor-save");
const scriptEditorCancelButton = document.getElementById("script-editor-cancel");
const scriptEditorDeleteButton = document.getElementById("script-editor-delete");
const scriptEditorTitleNode = document.getElementById("script-editor-title");
const scriptEditorMetaNode = document.getElementById("script-editor-meta");
const memoryTokenTotalNode = document.getElementById("memory-token-total");
const coreMemoryTokenCountNode = document.getElementById("core-memory-token-count");
const normalMemoryTokenCountNode = document.getElementById("normal-memory-token-count");
const coreMemorySearchInput = document.getElementById("core-memory-search");
const normalMemorySearchInput = document.getElementById("normal-memory-search");
const coreMemoryInput = document.getElementById("core-memory-input");
const normalMemoryInput = document.getElementById("normal-memory-input");
const addCoreMemoryButton = document.getElementById("add-core-memory-btn");
const addNormalMemoryButton = document.getElementById("add-normal-memory-btn");
const compactCoreMemoryButton = document.getElementById("compact-core-memory-btn");
const compactNormalMemoryButton = document.getElementById("compact-normal-memory-btn");
const coreMemoryList = document.getElementById("core-memory-list");
const normalMemoryList = document.getElementById("normal-memory-list");
let toastNode = document.getElementById("toast");

const MOBILE_DRAWER_BREAKPOINT = 900;
const MOBILE_SWIPE_EDGE_PX = 24;
const MOBILE_SWIPE_OPEN_THRESHOLD = 70;
const MOBILE_SWIPE_CLOSE_THRESHOLD = 52;
const CHAT_INPUT_MAX_HEIGHT_PX = 160;

const providerSelectNodes = [headerProviderSelect, mobileLeftProviderSelect].filter((node) => node instanceof HTMLSelectElement);
const modelSelectNodes = [headerModelSelect, mobileLeftModelSelect].filter((node) => node instanceof HTMLSelectElement);

const state = {
  providers: [],
  activeProviderId: "",
  activeModelId: "",
  providerLabel: "",
  modelLabel: "",
  botName: "",
  modelTokenLimit: 0,
  usedTokens: 0,
  lastRequestTokens: 0,
  settings: null,
  dailyTokenUsage: [],
  mcps: [],
  scriptTitles: [],
  scripts: [],
  scriptEditorTitle: "",
  scriptEditorMode: "",
  mcpConfigs: {},
  integrations: [],
  integrationConfigs: {},
  chats: [],
  activeChatId: "",
  chatRuntimes: {},
  isCompacting: false,
  isSwitching: false,
  suppressSwitcherEvents: false,
  toastTimerId: null,
  compactionBubble: null,
  chatSyncTimerId: null,
  chatSyncInFlight: false,
  integrationStatusSyncTimerId: null,
  integrationStatusSyncInFlight: false,
  timedJobAuthAlertSyncTimerId: null,
  timedJobAuthAlertSyncInFlight: false,
  shortTermMemorySyncTimerId: null,
  shortTermMemorySyncInFlight: false,
  chatPersistInFlight: false,
  chatPersistQueued: false,
  chatPersistPromise: null,
  chatStateDirty: false,
  chatStateMutationVersion: 0,
  shortTermMemories: [],
  shortTermMemoryCount: 0,
  shortTermMemoryLastToastCount: 0,
  shortTermMemoryExtracting: false,
  timedJobs: [],
  timedJobChannels: [],
  timedJobEditingId: "",
  expandedTimedJobIds: {},
  timedJobsClockTimerId: null,
  serverTimezoneName: "UTC",
  serverTimezoneOffset: 0,
  lastChatStateSignature: "",

  telegramEnabled: false,
  telegramTokenConfigured: false,
  telegramOwnerUserId: "",
  telegramOwnerChatId: "",
  googleOauthStatus: null,
  whatsappContacts: [],
  whatsappAllowlistOnlySelected: false,
  mcpAutosaveTimerId: null,
  mcpAutosavePendingId: "",
  mcpAutosaveQueuedId: "",
  mcpAutosaveInFlight: false,
  googleGuideExpanded: false,
  expandedConfigs: {},
  coreMemories: [],
  normalMemories: [],
  coreMemorySearchTerm: "",
  normalMemorySearchTerm: "",
  coreMemoryEditingIndex: -1,
  normalMemoryEditingIndex: -1,
  coreMemoryEditDraft: "",
  normalMemoryEditDraft: "",
  memoryCompactionType: "",
  brainTables: [],
  selectedBrainTable: "",
  brainLoading: false,
  mobileLeftDrawerOpen: false,
  mobileRightDrawerOpen: false,
  mobileTouchGesture: null,
  speechRecognition: null,
  speechSupported: false,
  speechListening: false,
  speechBaseText: "",
  speechFinalText: "",
  speechInterimText: "",
  pendingImageAttachment: null,
  pendingEnqueueByChat: {},
  chatHistoryVisibleCount: CHAT_HISTORY_PAGE_SIZE,
  chatHistorySignature: "",
  chatHistorySearchTerm: "",
  showHiddenTimedJobChats: false,
  tokenUsageRangeMode: "7",
  tokenUsageCustomFrom: "",
  tokenUsageCustomTo: "",
  tokenUsageIncludeZeroDays: true,
  theme: normalizeThemeMode(document.documentElement.getAttribute("data-theme")),
};

if (chatHistorySearchInput instanceof HTMLInputElement) {
  state.chatHistorySearchTerm = chatHistorySearchInput.value || "";
}

if (showHiddenTimedJobChatsInput instanceof HTMLInputElement) {
  state.showHiddenTimedJobChats = showHiddenTimedJobChatsInput.checked;
}

function normalizeThemeMode(value) {
  return String(value || "").trim().toLowerCase() === "dark" ? "dark" : "light";
}

function renderThemeToggleLabels() {
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

function applyThemeMode(theme) {
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

function isMobileDrawerMode() {
  return window.matchMedia(`(max-width: ${MOBILE_DRAWER_BREAKPOINT}px)`).matches;
}

function isAnyModalOpen() {
  const memoryOpen = memoryModal instanceof HTMLElement && !memoryModal.classList.contains("hidden");
  const brainOpen = brainModal instanceof HTMLElement && !brainModal.classList.contains("hidden");
  const shortTermOpen = shortTermMemoryModal instanceof HTMLElement && !shortTermMemoryModal.classList.contains("hidden");
  const timedJobsOpen = timedJobsModal instanceof HTMLElement && !timedJobsModal.classList.contains("hidden");
  const tokenUsageOpen = tokenUsageModal instanceof HTMLElement && !tokenUsageModal.classList.contains("hidden");
  const changePasswordOpen = changePasswordModal instanceof HTMLElement && !changePasswordModal.classList.contains("hidden");
  return memoryOpen || brainOpen || shortTermOpen || timedJobsOpen || tokenUsageOpen || changePasswordOpen;
}

function syncMobileDrawerUi() {
  if (!(gatewayShell instanceof HTMLElement)) {
    return;
  }

  const mobileMode = isMobileDrawerMode();
  const leftOpen = mobileMode && state.mobileLeftDrawerOpen;
  const rightOpen = mobileMode && state.mobileRightDrawerOpen;
  gatewayShell.classList.toggle("mobile-left-open", leftOpen);
  gatewayShell.classList.toggle("mobile-right-open", rightOpen);

  if (mobileDrawerBackdrop instanceof HTMLElement) {
    const shouldShowBackdrop = leftOpen || rightOpen;
    mobileDrawerBackdrop.classList.toggle("hidden", !shouldShowBackdrop);
  }

  if (mobileLeftDrawerHandle instanceof HTMLButtonElement) {
    mobileLeftDrawerHandle.setAttribute("aria-expanded", leftOpen ? "true" : "false");
  }
  if (mobileRightDrawerHandle instanceof HTMLButtonElement) {
    mobileRightDrawerHandle.setAttribute("aria-expanded", rightOpen ? "true" : "false");
  }

  if (mobileMode && (leftOpen || rightOpen)) {
    document.body.style.overflow = "hidden";
    return;
  }

  if (!isAnyModalOpen()) {
    document.body.style.overflow = "";
  }
}

function closeMobileDrawers() {
  toggleMobileSettingsMenu(false);
  if (!state.mobileLeftDrawerOpen && !state.mobileRightDrawerOpen) {
    return;
  }

  state.mobileLeftDrawerOpen = false;
  state.mobileRightDrawerOpen = false;
  syncMobileDrawerUi();
}

function openMobileLeftDrawer() {
  if (!isMobileDrawerMode()) {
    return;
  }
  toggleMobileSettingsMenu(false);
  state.mobileLeftDrawerOpen = true;
  state.mobileRightDrawerOpen = false;
  syncMobileDrawerUi();
}

function openMobileRightDrawer() {
  if (!isMobileDrawerMode()) {
    return;
  }
  toggleMobileSettingsMenu(false);
  state.mobileRightDrawerOpen = true;
  state.mobileLeftDrawerOpen = false;
  syncMobileDrawerUi();
}

function toggleMobileLeftDrawer() {
  if (!isMobileDrawerMode()) {
    return;
  }

  if (state.mobileLeftDrawerOpen) {
    closeMobileDrawers();
    return;
  }

  openMobileLeftDrawer();
}

function toggleMobileRightDrawer() {
  if (!isMobileDrawerMode()) {
    return;
  }

  if (state.mobileRightDrawerOpen) {
    closeMobileDrawers();
    return;
  }

  openMobileRightDrawer();
}

function toggleMobileSettingsMenu(forceOpen) {
  if (!(mobileSettingsPopover instanceof HTMLElement) || !(mobileSettingsMenuButton instanceof HTMLButtonElement)) {
    return;
  }

  const shouldOpen = typeof forceOpen === "boolean" ? forceOpen : mobileSettingsPopover.classList.contains("hidden");
  mobileSettingsPopover.classList.toggle("hidden", !shouldOpen);
  mobileSettingsMenuButton.setAttribute("aria-expanded", shouldOpen ? "true" : "false");
}

function handleMobileSwipeStart(event) {
  if (!isMobileDrawerMode() || isAnyModalOpen()) {
    state.mobileTouchGesture = null;
    return;
  }

  const touch = event.touches?.[0];
  if (!touch) {
    state.mobileTouchGesture = null;
    return;
  }

  const startX = touch.clientX;
  const startY = touch.clientY;
  const target = event.target;
  const viewportWidth = window.innerWidth;
  let mode = "";

  if (!state.mobileLeftDrawerOpen && !state.mobileRightDrawerOpen) {
    if (startX <= MOBILE_SWIPE_EDGE_PX) {
      mode = "open-left";
    } else if (startX >= viewportWidth - MOBILE_SWIPE_EDGE_PX) {
      mode = "open-right";
    }
  } else if (state.mobileLeftDrawerOpen && target instanceof Node) {
    if ((gatewayTopbar instanceof HTMLElement && gatewayTopbar.contains(target))
      || (chatHistoryPanel instanceof HTMLElement && chatHistoryPanel.contains(target))) {
      mode = "close-left";
    }
  } else if (state.mobileRightDrawerOpen && target instanceof Node) {
    if (mcpSidePanel instanceof HTMLElement && mcpSidePanel.contains(target)) {
      mode = "close-right";
    }
  }

  if (!mode) {
    state.mobileTouchGesture = null;
    return;
  }

  state.mobileTouchGesture = {
    mode,
    startX,
    startY,
    handled: false,
  };
}

function handleMobileSwipeMove(event) {
  const gesture = state.mobileTouchGesture;
  if (!gesture || gesture.handled) {
    return;
  }

  const touch = event.touches?.[0];
  if (!touch) {
    return;
  }

  const deltaX = touch.clientX - gesture.startX;
  const deltaY = touch.clientY - gesture.startY;
  if (Math.abs(deltaX) <= Math.abs(deltaY)) {
    return;
  }

  if (gesture.mode === "open-left" && deltaX > MOBILE_SWIPE_OPEN_THRESHOLD) {
    openMobileLeftDrawer();
    gesture.handled = true;
    event.preventDefault();
    return;
  }

  if (gesture.mode === "open-right" && deltaX < -MOBILE_SWIPE_OPEN_THRESHOLD) {
    openMobileRightDrawer();
    gesture.handled = true;
    event.preventDefault();
    return;
  }

  if (gesture.mode === "close-left" && deltaX < -MOBILE_SWIPE_CLOSE_THRESHOLD) {
    closeMobileDrawers();
    gesture.handled = true;
    event.preventDefault();
    return;
  }

  if (gesture.mode === "close-right" && deltaX > MOBILE_SWIPE_CLOSE_THRESHOLD) {
    closeMobileDrawers();
    gesture.handled = true;
    event.preventDefault();
  }
}

function handleMobileSwipeEnd() {
  state.mobileTouchGesture = null;
}

function getChatRuntime(chatId) {
  if (!chatId) {
    return null;
  }

  if (!state.chatRuntimes[chatId] || typeof state.chatRuntimes[chatId] !== "object") {
    state.chatRuntimes[chatId] = {
      processing: false,
      queue: [],
      cancelledRequestIds: new Set(),
      activeRequestId: "",
      abortController: null,
    };
  }

  return state.chatRuntimes[chatId];
}

function removeChatRuntime(chatId) {
  const runtime = state.chatRuntimes[chatId];
  if (!runtime) {
    return;
  }

  runtime.queue.forEach((job) => {
    if (job && typeof job.requestId === "string") {
      runtime.cancelledRequestIds.add(job.requestId);
    }
  });

  runtime.queue = [];
  if (runtime.activeRequestId) {
    runtime.cancelledRequestIds.add(runtime.activeRequestId);
  }

  if (runtime.abortController instanceof AbortController) {
    runtime.abortController.abort();
  }
}

function isChatBusy(chatId) {
  const chat = state.chats.find((entry) => entry.id === chatId);
  if (!chat || !Array.isArray(chat.messages)) {
    return false;
  }
  return chat.messages.some((message) =>
    message
    && message.role === "assistant"
    && (message.status === "queued" || message.status === "processing")
  );
}

function isAnyChatBusy() {
  return state.chats.some((chat) => {
    if (!chat || !Array.isArray(chat.messages)) {
      return false;
    }
    return chat.messages.some((message) =>
      message
      && message.role === "assistant"
      && (message.status === "queued" || message.status === "processing")
    );
  });
}

function setStatus(message, isError = false) {
  statusNode.textContent = message;
  statusNode.className = isError ? "error" : "ok";
}

async function toggleThemePreference() {
  if (!state.settings) {
    return;
  }

  const nextTheme = state.theme === "dark" ? "light" : "dark";
  const nextSettings = JSON.parse(JSON.stringify(state.settings));
  nextSettings.theme = nextTheme;
  const persisted = await persistSettings(nextSettings);
  state.settings = persisted;
  applyThemeMode(persisted.theme);
  showToast(`Theme: ${state.theme}`);
}

function syncChatInputHeight() {
  if (!(chatInput instanceof HTMLTextAreaElement)) {
    return;
  }

  chatInput.style.height = "auto";
  const targetHeight = Math.min(chatInput.scrollHeight, CHAT_INPUT_MAX_HEIGHT_PX);
  chatInput.style.height = `${Math.max(targetHeight, 38)}px`;
  chatInput.style.overflowY = chatInput.scrollHeight > CHAT_INPUT_MAX_HEIGHT_PX ? "auto" : "hidden";
}

function clearPendingImageAttachment() {
  state.pendingImageAttachment = null;
  if (imageUploadInput instanceof HTMLInputElement) {
    imageUploadInput.value = "";
  }
  renderPendingImageAttachment();
}

function clonePendingImageAttachment(pendingImage) {
  if (!pendingImage || typeof pendingImage !== "object") {
    return null;
  }
  return {
    fileName: typeof pendingImage.fileName === "string" ? pendingImage.fileName : "image",
    mimeType: typeof pendingImage.mimeType === "string" ? pendingImage.mimeType : "image/jpeg",
    contentBase64: typeof pendingImage.contentBase64 === "string" ? pendingImage.contentBase64 : "",
    previewUrl: typeof pendingImage.previewUrl === "string" ? pendingImage.previewUrl : "",
  };
}

function renderPendingImageAttachment() {
  if (!(imageAttachmentPreview instanceof HTMLElement)) {
    return;
  }
  const pending = state.pendingImageAttachment;
  if (!pending) {
    imageAttachmentPreview.classList.add("hidden");
    imageAttachmentPreview.innerHTML = "";
    return;
  }

  const escapedName = String(pending.fileName || "image").replace(/[<>]/g, "");
  imageAttachmentPreview.classList.remove("hidden");
  imageAttachmentPreview.innerHTML = `
    <img src="${pending.previewUrl}" alt="Selected image" />
    <span>${escapedName}</span>
    <button type="button" class="image-attachment-remove" id="remove-image-attachment">Remove</button>
  `;
  const removeButton = document.getElementById("remove-image-attachment");
  if (removeButton instanceof HTMLButtonElement) {
    removeButton.addEventListener("click", () => {
      clearPendingImageAttachment();
    });
  }
}

function parseDataUrl(dataUrl) {
  const raw = String(dataUrl || "");
  const match = raw.match(/^data:([^;]+);base64,(.+)$/);
  if (!match) {
    return null;
  }
  return { mimeType: match[1], contentBase64: match[2] };
}

async function handleImageUploadInputChange(event) {
  const target = event.target;
  if (!(target instanceof HTMLInputElement) || !target.files || target.files.length === 0) {
    return;
  }

  const file = target.files[0];
  if (!file.type.startsWith("image/")) {
    setStatus("Only image files are supported.", true);
    clearPendingImageAttachment();
    return;
  }
  if (file.size > 10 * 1024 * 1024) {
    setStatus("Image exceeds 10MB limit.", true);
    clearPendingImageAttachment();
    return;
  }

  const dataUrl = await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error("Failed to read image file."));
    reader.readAsDataURL(file);
  });

  const parsed = parseDataUrl(dataUrl);
  if (!parsed) {
    setStatus("Invalid image data URL.", true);
    clearPendingImageAttachment();
    return;
  }

  state.pendingImageAttachment = {
    fileName: file.name || "image",
    mimeType: parsed.mimeType,
    contentBase64: parsed.contentBase64,
    previewUrl: dataUrl,
  };
  renderPendingImageAttachment();
  setStatus("Image attached. Send to analyze.");
}

function getSpeechRecognitionConstructor() {
  if (typeof window === "undefined") {
    return null;
  }
  if (typeof window.SpeechRecognition === "function") {
    return window.SpeechRecognition;
  }
  if (typeof window.webkitSpeechRecognition === "function") {
    return window.webkitSpeechRecognition;
  }
  return null;
}

function composeSpeechInputValue() {
  const base = typeof state.speechBaseText === "string" ? state.speechBaseText : "";
  const finalText = typeof state.speechFinalText === "string" ? state.speechFinalText.trim() : "";
  const interimText = typeof state.speechInterimText === "string" ? state.speechInterimText.trim() : "";
  const spokenText = [finalText, interimText].filter(Boolean).join(" ").trim();
  if (!spokenText) {
    return base;
  }
  if (!base.trim()) {
    return spokenText;
  }
  const separator = /[\s\n]$/.test(base) ? "" : " ";
  return `${base}${separator}${spokenText}`;
}

function applySpeechTranscriptToInput() {
  if (!(chatInput instanceof HTMLTextAreaElement)) {
    return;
  }
  chatInput.value = composeSpeechInputValue();
  syncChatInputHeight();
}

function pushUniqueSpeechChunk(chunks, transcript) {
  if (!transcript) {
    return;
  }
  if (chunks.length > 0 && chunks[chunks.length - 1] === transcript) {
    return;
  }
  chunks.push(transcript);
}

function setSpeechUiState() {
  if (!(micButton instanceof HTMLButtonElement)) {
    return;
  }

  if (!state.speechSupported) {
    micButton.disabled = true;
    micButton.classList.remove("is-listening");
    micButton.setAttribute("aria-pressed", "false");
    micButton.setAttribute("aria-label", "Voice dictation unavailable in this browser");
    micButton.title = "Voice dictation unavailable";
    return;
  }

  micButton.disabled = false;
  micButton.classList.toggle("is-listening", state.speechListening);
  micButton.setAttribute("aria-pressed", state.speechListening ? "true" : "false");
  micButton.setAttribute("aria-label", state.speechListening ? "Stop voice dictation" : "Start voice dictation");
  micButton.title = state.speechListening ? "Stop voice dictation" : "Start voice dictation";
}

function stopSpeechRecognition(silent = false) {
  if (!state.speechRecognition || !state.speechListening) {
    return;
  }
  state.speechListening = false;
  state.speechInterimText = "";
  applySpeechTranscriptToInput();
  setSpeechUiState();
  try {
    state.speechRecognition.stop();
  } catch (error) {
    // no-op
  }
  if (!silent) {
    setStatus("Voice dictation stopped.");
  }
}

function startSpeechRecognition() {
  if (!state.speechSupported || !state.speechRecognition) {
    setStatus("Voice dictation is not supported in this browser.", true);
    return;
  }
  if (state.speechListening) {
    return;
  }

  state.speechBaseText = chatInput instanceof HTMLTextAreaElement ? chatInput.value : "";
  state.speechFinalText = "";
  state.speechInterimText = "";

  try {
    state.speechRecognition.start();
  } catch (error) {
    setStatus("Could not start voice dictation. Check microphone permissions.", true);
  }
}

function toggleSpeechRecognition() {
  if (!state.speechSupported) {
    setStatus("Voice dictation is not supported in this browser.", true);
    return;
  }
  if (state.speechListening) {
    stopSpeechRecognition();
    return;
  }
  startSpeechRecognition();
}

function initializeSpeechRecognition() {
  const RecognitionConstructor = getSpeechRecognitionConstructor();
  state.speechSupported = Boolean(RecognitionConstructor);
  if (!state.speechSupported) {
    setSpeechUiState();
    return;
  }

  const recognition = new RecognitionConstructor();
  recognition.continuous = true;
  recognition.interimResults = true;
  recognition.maxAlternatives = 1;
  if (typeof navigator?.language === "string" && navigator.language) {
    recognition.lang = navigator.language;
  }

  recognition.onstart = () => {
    state.speechListening = true;
    setSpeechUiState();
    setStatus("Voice dictation listening...");
  };

  recognition.onresult = (event) => {
    const finalChunks = [];
    const interimChunks = [];
    for (let index = 0; index < event.results.length; index += 1) {
      const result = event.results[index];
      if (!result || !result[0]) {
        continue;
      }
      const transcript = String(result[0].transcript || "").trim();
      if (!transcript) {
        continue;
      }
      if (result.isFinal) {
        pushUniqueSpeechChunk(finalChunks, transcript);
      } else {
        pushUniqueSpeechChunk(interimChunks, transcript);
      }
    }
    state.speechFinalText = finalChunks.join(" ").trim();
    state.speechInterimText = interimChunks.join(" ").trim();
    applySpeechTranscriptToInput();
  };

  recognition.onerror = (event) => {
    const reason = typeof event?.error === "string" ? event.error : "unknown";
    if (reason === "not-allowed" || reason === "service-not-allowed") {
      setStatus("Microphone permission denied. Allow microphone access to use dictation.", true);
      return;
    }
    if (reason === "no-speech") {
      setStatus("No speech detected. Try again.", true);
      return;
    }
    if (reason === "aborted") {
      return;
    }
    setStatus(`Voice dictation failed: ${reason}.`, true);
  };

  recognition.onend = () => {
    state.speechListening = false;
    state.speechInterimText = "";
    applySpeechTranscriptToInput();
    setSpeechUiState();
  };

  state.speechRecognition = recognition;
  setSpeechUiState();
}

function normalizeErrorMessage(error, fallback = "Request failed.") {
  if (error instanceof DOMException && error.name === "AbortError") {
    return "Request was aborted.";
  }
  if (typeof error?.message === "string" && error.message.trim()) {
    return error.message.trim();
  }
  return fallback;
}

async function buildHttpErrorDetail(response, fallback = "Request failed.") {
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

function showToast(message) {
  if (!(toastNode instanceof HTMLElement)) {
    const fallbackToast = document.createElement("div");
    fallbackToast.id = "toast";
    fallbackToast.className = "toast hidden";
    fallbackToast.setAttribute("role", "status");
    fallbackToast.setAttribute("aria-live", "polite");
    document.body.appendChild(fallbackToast);
    toastNode = fallbackToast;
  }

  if (state.toastTimerId) {
    window.clearTimeout(state.toastTimerId);
  }

  toastNode.textContent = message;
  toastNode.classList.remove("hidden");
  state.toastTimerId = window.setTimeout(() => {
    toastNode.classList.add("hidden");
    state.toastTimerId = null;
  }, 1800);
}

function canUseBrowserNotifications() {
  return typeof window !== "undefined" && "Notification" in window;
}

function shouldNotifyForAssistantResponse() {
  return document.visibilityState !== "visible" || document.hidden;
}

async function requestNotificationPermissionIfNeeded() {
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

function sendAssistantResponseNotification(chat, assistantMessage) {
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
    icon: "/static/img/krill_icon.png",
    tag: `krill-chat-${chat?.id || "default"}`,
  });
  notification.onclick = () => {
    window.focus();
    notification.close();
  };
}

function getServerDate(rawValue) {
  const date = rawValue ? new Date(rawValue) : new Date();
  if (Number.isNaN(date.getTime())) {
    return new Date();
  }
  const serverOffsetMs = (state.serverTimezoneOffset || 0) * 60 * 1000;
  const browserOffsetMs = date.getTimezoneOffset() * 60 * 1000;
  return new Date(date.getTime() + serverOffsetMs + browserOffsetMs);
}

function formatMessageTimestamp(rawValue = "") {
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


function createTimestamp() {
  return new Date().toISOString();
}

function normalizeIncomingMemories(rawMemories) {
  if (!Array.isArray(rawMemories)) {
    return [];
  }

  return rawMemories
    .filter((memory) => memory && typeof memory === "object")
    .map((memory) => {
      const content = typeof memory.content === "string" ? memory.content.trim().slice(0, MEMORY_MAX_LENGTH) : "";
      const createdAt = typeof memory.created_at === "string" ? memory.created_at.trim() : "";
      return { content, created_at: createdAt };
    })
    .filter((memory) => memory.content.length > 0);
}

function estimateTextTokens(text) {
  const normalized = typeof text === "string" ? text.trim() : "";
  if (!normalized) {
    return 0;
  }
  return Math.max(1, Math.ceil(normalized.length / 4));
}

function estimateMemoryTokens(memories) {
  if (!Array.isArray(memories)) {
    return 0;
  }
  return memories.reduce((sum, memory) => sum + estimateTextTokens(memory?.content ?? ""), 0);
}

function formatMemoryTimestamp(rawValue) {
  const value = typeof rawValue === "string" ? rawValue.trim() : "";
  if (!value) {
    return "Unknown time";
  }

  const parsed = getServerDate(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }

  const year = parsed.getFullYear();
  const month = String(parsed.getMonth() + 1).padStart(2, "0");
  const day = String(parsed.getDate()).padStart(2, "0");
  const hours = String(parsed.getHours()).padStart(2, "0");
  const minutes = String(parsed.getMinutes()).padStart(2, "0");
  return `${year}-${month}-${day} ${hours}:${minutes}`;
}


function getFilteredMemories(memories, searchTerm) {
  const normalizedSearch = String(searchTerm || "").trim().toLowerCase();
  return memories
    .map((memory, index) => ({ memory, index }))
    .filter(({ memory }) => {
      if (!normalizedSearch) {
        return true;
      }
      return memory.content.toLowerCase().includes(normalizedSearch);
    });
}

function doesChatMatchSearch(chat, normalizedSearch) {
  if (!normalizedSearch) {
    return true;
  }

  const title = typeof chat?.title === "string" ? chat.title.toLowerCase() : "";
  if (title.includes(normalizedSearch)) {
    return true;
  }

  if (!Array.isArray(chat?.messages)) {
    return false;
  }

  return chat.messages.some((message) => {
    if (!message || (message.role !== "user" && message.role !== "assistant")) {
      return false;
    }
    const content = typeof message.content === "string" ? message.content.toLowerCase() : "";
    return content.includes(normalizedSearch);
  });
}

function isHiddenTimedJobDebugChat(chat) {
  const title = typeof chat?.title === "string" ? chat.title.trim() : "";
  return title.startsWith("[Hidden]");
}

function getFilteredChats(chats, searchTerm) {
  const normalizedSearch = String(searchTerm || "").trim().toLowerCase();
  return chats.filter((chat) => {
    if (!state.showHiddenTimedJobChats && isHiddenTimedJobDebugChat(chat)) {
      return false;
    }
    return doesChatMatchSearch(chat, normalizedSearch);
  });
}

function renderMemoryList(node, memories, searchTerm, type) {
  if (!(node instanceof HTMLElement)) {
    return;
  }

  node.innerHTML = "";
  const filtered = getFilteredMemories(memories, searchTerm);
  if (filtered.length === 0) {
    const emptyNode = document.createElement("p");
    emptyNode.className = "memory-modal-empty";
    emptyNode.textContent = searchTerm ? "No matching memories." : "No memories yet.";
    node.appendChild(emptyNode);
    return;
  }

  filtered.forEach(({ memory, index }) => {
    const card = document.createElement("article");
    card.className = "memory-modal-card-item";

    const timeNode = document.createElement("span");
    timeNode.className = "memory-modal-card-time";
    timeNode.textContent = formatMemoryTimestamp(memory.created_at);
    card.appendChild(timeNode);

    const deleteButton = document.createElement("button");
    deleteButton.type = "button";
    deleteButton.className = "memory-card-delete-btn";
    deleteButton.dataset.memoryType = type;
    deleteButton.dataset.memoryIndex = String(index);
    deleteButton.dataset.memoryAction = "delete";
    deleteButton.textContent = "x";
    deleteButton.setAttribute("aria-label", "Delete memory");
    card.appendChild(deleteButton);

    const editingIndex = type === "core" ? state.coreMemoryEditingIndex : state.normalMemoryEditingIndex;
    const isEditing = editingIndex === index;

    if (isEditing) {
      const draft = type === "core" ? state.coreMemoryEditDraft : state.normalMemoryEditDraft;
      const editInput = document.createElement("textarea");
      editInput.className = "memory-inline-editor";
      editInput.maxLength = MEMORY_MAX_LENGTH;
      editInput.rows = 3;
      editInput.value = draft;
      editInput.dataset.memoryType = type;
      editInput.dataset.memoryIndex = String(index);
      editInput.dataset.memoryAction = "draft";

      const actions = document.createElement("div");
      actions.className = "memory-inline-actions";

      const saveButton = document.createElement("button");
      saveButton.type = "button";
      saveButton.className = "memory-inline-btn";
      saveButton.dataset.memoryType = type;
      saveButton.dataset.memoryIndex = String(index);
      saveButton.dataset.memoryAction = "save";
      saveButton.textContent = "Save";

      const cancelButton = document.createElement("button");
      cancelButton.type = "button";
      cancelButton.className = "memory-inline-btn memory-inline-btn-secondary";
      cancelButton.dataset.memoryType = type;
      cancelButton.dataset.memoryIndex = String(index);
      cancelButton.dataset.memoryAction = "cancel";
      cancelButton.textContent = "Cancel";

      actions.appendChild(saveButton);
      actions.appendChild(cancelButton);
      card.appendChild(editInput);
      card.appendChild(actions);
    } else {
      const contentNode = document.createElement("p");
      contentNode.className = "memory-modal-card-content";
      contentNode.textContent = memory.content;
      contentNode.dataset.memoryType = type;
      contentNode.dataset.memoryIndex = String(index);
      contentNode.dataset.memoryAction = "edit";
      contentNode.setAttribute("role", "button");
      contentNode.setAttribute("tabindex", "0");
      card.appendChild(contentNode);

      const editHint = document.createElement("p");
      editHint.className = "memory-edit-hint";
      editHint.textContent = "Click to edit";
      card.appendChild(editHint);
    }

    node.appendChild(card);
  });
}

function renderMemoryTokenCounts() {
  const coreTokens = estimateMemoryTokens(state.coreMemories);
  const normalTokens = estimateMemoryTokens(state.normalMemories);
  const totalTokens = coreTokens + normalTokens;

  if (coreMemoryTokenCountNode instanceof HTMLElement) {
    coreMemoryTokenCountNode.textContent = `Estimated tokens: ${formatNumber(coreTokens)}`;
  }
  if (normalMemoryTokenCountNode instanceof HTMLElement) {
    normalMemoryTokenCountNode.textContent = `Estimated tokens: ${formatNumber(normalTokens)}`;
  }
  if (memoryTokenTotalNode instanceof HTMLElement) {
    memoryTokenTotalNode.textContent = `Total estimated memory tokens: ${formatNumber(totalTokens)}`;
  }
}

function renderMemoryManagement() {
  renderMemoryTokenCounts();
  renderMemoryList(coreMemoryList, state.coreMemories, state.coreMemorySearchTerm, "core");
  renderMemoryList(normalMemoryList, state.normalMemories, state.normalMemorySearchTerm, "normal");
  updateMemoryCompactionButtons();
}

function normalizeChatTitle(rawTitle) {
  if (typeof rawTitle !== "string") {
    return "New chat";
  }

  const trimmed = rawTitle.trim();
  return trimmed || "New chat";
}

function deriveChatTitle(firstMessage) {
  const normalized = String(firstMessage || "").trim().replace(/\s+/g, " ");
  if (!normalized) {
    return "New chat";
  }

  if (normalized.length <= CHAT_TITLE_MAX_LENGTH) {
    return normalized;
  }

  return `${normalized.slice(0, CHAT_TITLE_MAX_LENGTH).trimEnd()}...`;
}

function normalizeEditedChatTitle(rawTitle) {
  const normalized = String(rawTitle || "").trim().replace(/\s+/g, " ");
  if (!normalized) {
    return "New chat";
  }

  if (normalized.length <= EDITABLE_CHAT_TITLE_MAX_LENGTH) {
    return normalized;
  }

  return normalized.slice(0, EDITABLE_CHAT_TITLE_MAX_LENGTH).trimEnd();
}

function createChatId() {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }

  return `chat-${Date.now()}-${Math.random().toString(16).slice(2, 10)}`;
}

function createLocalRequestId() {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return `local-${crypto.randomUUID()}`;
  }

  return `local-${Date.now()}-${Math.random().toString(16).slice(2, 10)}`;
}

function createClientEnqueueId() {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return `enqueue-${crypto.randomUUID()}`;
  }

  return `enqueue-${Date.now()}-${Math.random().toString(16).slice(2, 10)}`;
}

function buildEnqueueDraftKey(message, pendingImage) {
  const textPart = typeof message === "string" ? message.trim() : "";
  if (!pendingImage || typeof pendingImage !== "object") {
    return textPart;
  }
  const fileName = typeof pendingImage.fileName === "string" ? pendingImage.fileName : "image";
  const mimeType = typeof pendingImage.mimeType === "string" ? pendingImage.mimeType : "image/jpeg";
  const contentBase64 = typeof pendingImage.contentBase64 === "string" ? pendingImage.contentBase64 : "";
  return `${textPart}::${fileName}::${mimeType}::${contentBase64}`;
}

function getLatestChatMessage(chat) {
  if (!chat || !Array.isArray(chat.messages) || chat.messages.length === 0) {
    return null;
  }

  return chat.messages[chat.messages.length - 1] ?? null;
}

function getLatestChatTimestamp(chat) {
  const latest = getLatestChatMessage(chat);
  if (latest && typeof latest.timestamp === "string" && latest.timestamp) {
    return latest.timestamp;
  }

  return "";
}

function sortChatsByLatestMessage(chats) {
  return [...chats].sort((left, right) => {
    const leftDate = new Date(getLatestChatTimestamp(left) || 0).getTime();
    const rightDate = new Date(getLatestChatTimestamp(right) || 0).getTime();
    if (rightDate !== leftDate) {
      return rightDate - leftDate;
    }
    return (left.title || "").localeCompare(right.title || "");
  });
}

function getActiveChat() {
  return state.chats.find((chat) => chat.id === state.activeChatId) ?? null;
}

function updateCurrentChatTitle() {
  if (!(currentChatTitleNode instanceof HTMLElement)) {
    return;
  }

  const activeChat = getActiveChat();
  currentChatTitleNode.textContent = activeChat ? deriveChatTitle(normalizeChatTitle(activeChat.title)) : "New chat";
}

function updateSystemTraceToggleLabel() {
  if (!(systemTraceToggleButton instanceof HTMLButtonElement)) {
    return;
  }

  const activeChat = getActiveChat();
  const isCollapsed = Boolean(activeChat?.collapse_system_trace);
  const mobileMode = isMobileDrawerMode();
  if (mobileMode) {
    systemTraceToggleButton.textContent = isCollapsed ? "Trace: Off" : "Trace: On";
  } else {
    systemTraceToggleButton.textContent = isCollapsed ? "Show system trace" : "Hide system trace";
  }
  systemTraceToggleButton.disabled = !activeChat;
}

function createChatEntry(firstMessage) {
  const timestamp = createTimestamp();
  return {
    id: createChatId(),
    title: deriveChatTitle(firstMessage),
    type: "normal",
    messages: [],
    memory_block: "",
    total_tokens_used: 0,
    collapse_system_trace: true,
    hidden_from_history: false,
    created_at: timestamp,
    updated_at: timestamp,
  };
}

function buildRuntimeContextSeed() {
  const botName = typeof state.settings?.bot_name === "string" ? state.settings.bot_name.trim() : "Krill";
  const userFullName = typeof state.settings?.user_full_name === "string"
    ? state.settings.user_full_name.trim()
    : "";
  const userCallName = typeof state.settings?.user_call_name === "string"
    ? state.settings.user_call_name.trim()
    : "";
  const behavior = typeof state.settings?.system_prompt === "string" ? state.settings.system_prompt.trim() : "";
  const coreMemories = Array.isArray(state.coreMemories) ? state.coreMemories : [];

  let seed = `You are Krill assistant named '${botName}'. `;
  seed += `You are the assistant of '${userFullName || "the user"}'. `;
  seed += `Call your human user '${userCallName || "the user"}'.`;

  if (behavior) {
    seed += ` This is the system prompt your user provided: ${behavior}`;
  }

  seed += "\n\nIdentity reminder:\n";
  seed += "- When memories mention this person, or mention 'the user', that always refers to your human user.";

  const memoryLines = coreMemories
    .map((memory) => (typeof memory?.content === "string" ? memory.content.trim() : ""))
    .filter((content) => Boolean(content))
    .map((content) => `- ${content}`);

  if (memoryLines.length > 0) {
    seed = (
      `${seed}\n\n`
      + "Core memories (background context from the user):\n"
      + "Use these memories subtly and only when they are relevant and helpful. "
      + "Do not repeatedly mention or announce these memories. "
      + "Keep the response natural, personal, and context-aware.\n"
      + memoryLines.join("\n")
    );
  }

  return seed;
}

function ensureRuntimeContextSeed(chat) {
  if (!chat || !Array.isArray(chat.messages)) {
    return;
  }

  const seedContent = buildRuntimeContextSeed();
  const existingSeed = chat.messages.find(
    (message) =>
      message
      && message.role === "system"
      && typeof message.system_type === "string"
      && message.system_type === RUNTIME_CONTEXT_SYSTEM_TYPE,
  );
  if (existingSeed) {
    if (existingSeed.content !== seedContent) {
      existingSeed.content = seedContent;
      chat.updated_at = createTimestamp();
    }
    return;
  }

  const timestamp = createTimestamp();
  chat.messages.unshift({
    role: "system",
    content: seedContent,
    timestamp,
    system_type: RUNTIME_CONTEXT_SYSTEM_TYPE,
    tool_usage: [],
    request_id: "",
    status: "",
  });
  chat.updated_at = timestamp;
}

function toApiChatHistory(messages) {
  return messages
    .filter((turn) => turn && (turn.role === "user" || turn.role === "assistant" || turn.role === "system"))
    .filter((turn) => typeof turn.content === "string" && turn.content.trim())
    .filter((turn) => {
      if (turn.role !== "system") {
        return true;
      }
      return turn.system_type === RUNTIME_CONTEXT_SYSTEM_TYPE;
    })
    .map((turn) => ({ role: turn.role, content: turn.content }));
}

function toApiCompactionHistory(messages) {
  return messages
    .filter((turn) => turn && (turn.role === "user" || turn.role === "assistant"))
    .filter((turn) => typeof turn.content === "string" && turn.content.trim())
    .map((turn) => ({ role: turn.role, content: turn.content }));
}

function setHistoryControlsDisabled(disabled) {
  if (newChatButton instanceof HTMLButtonElement) {
    newChatButton.disabled = disabled;
  }

  const buttons = chatHistoryList.querySelectorAll("button[data-chat-id]");
  buttons.forEach((button) => {
    const action = button.dataset.action;
    if (action === "delete" || action === "edit") {
      button.disabled = disabled;
      return;
    }
    button.disabled = false;
  });
}

function addMessage(role, text = "", timestamp = "", status = "") {
  const wrapper = document.createElement("div");
  wrapper.className = `chat-message ${role}`;
  if (status) {
    wrapper.classList.add(`status-${status}`);
  }

  const title = document.createElement("p");
  title.className = "chat-role";
  const roleLabel = role === "user" ? "You" : role === "system" ? "System" : state.botName || "Krill";
  const timeStr = (timestamp && status !== "queued" && status !== "processing")
    ? ` - ${formatMessageTimestamp(timestamp)}`
    : "";
  title.textContent = `${roleLabel}${timeStr}`;

  const bubble = document.createElement("div");
  bubble.className = "chat-bubble";

  if (role === "assistant" || role === "system") {
    const normalizedText = role === "assistant" && typeof text === "string" && text.trim().toLowerCase().startsWith("image analysis:")
      ? `📷 ${text.trim()}`
      : text;
    if ((status === "queued" || status === "processing") && !text) {
      const label = status === "queued" ? "Queued" : "Processing";
      bubble.innerHTML = `<span class="compaction-loading">${label} <span class="typing-dots" aria-label="${label}"><span></span><span></span><span></span></span></span>`;
    } else {
      bubble.innerHTML = renderMarkdown(normalizedText);
    }
  } else {
    bubble.textContent = text;
  }

  wrapper.appendChild(title);
  wrapper.appendChild(bubble);
  chatThread.appendChild(wrapper);
  chatThread.scrollTop = chatThread.scrollHeight;

  return bubble;
}

function normalizeToolUsage(toolUsage) {
  if (!Array.isArray(toolUsage)) {
    return [];
  }

  return toolUsage
    .filter((entry) => entry && typeof entry === "object")
    .map((entry) => ({
      mcp_id: typeof entry.mcp_id === "string" ? entry.mcp_id : "",
      mcp_label: typeof entry.mcp_label === "string" ? entry.mcp_label : "",
      tool_id: typeof entry.tool_id === "string" ? entry.tool_id : "",
      tool_label: typeof entry.tool_label === "string" ? entry.tool_label : "",
    }))
    .filter((entry) => entry.mcp_id && entry.tool_id);
}

function getFrontendMcpLabel(mcpId, fallbackLabel = "") {
  const normalizedId = typeof mcpId === "string" ? mcpId : "";
  if (normalizedId === "local_files") {
    return "Local Ops";
  }
  if (typeof fallbackLabel === "string" && fallbackLabel.trim()) {
    return fallbackLabel;
  }
  return normalizedId;
}

function getMcpDisplayLabel(mcpId) {
  const normalizedId = typeof mcpId === "string" ? mcpId : "";
  if (!normalizedId) {
    return "Tool";
  }
  const mcp = Array.isArray(state.mcps) ? state.mcps.find((entry) => entry?.id === normalizedId) : null;
  return getFrontendMcpLabel(normalizedId, typeof mcp?.label === "string" ? mcp.label : normalizedId);
}

function renderToolUsageLine(wrapper, toolUsage) {
  const normalized = normalizeToolUsage(toolUsage);
  if (normalized.length === 0) {
    return;
  }

  const usageNode = document.createElement("p");
  usageNode.className = "tool-usage-note";
  const labels = normalized.map((entry) => {
    const mcpLabel = getFrontendMcpLabel(entry.mcp_id, entry.mcp_label);
    const toolLabel = entry.tool_label || entry.tool_id;
    return `${mcpLabel} (${toolLabel})`;
  });
  usageNode.textContent = `used Tools: ${labels.join(", ")}`;
  wrapper.appendChild(usageNode);
}

function renderEmptyChatView() {
  chatThread.innerHTML = "";
  const emptyNode = document.createElement("p");
  emptyNode.className = "chat-history-empty";
  emptyNode.textContent = "Start a new chat with your first message.";
  chatThread.appendChild(emptyNode);
}

function renderActiveChat() {
  updateCurrentChatTitle();
  updateSystemTraceToggleLabel();
  const activeChat = getActiveChat();
  if (!activeChat) {
    renderEmptyChatView();
    return;
  }

  chatThread.innerHTML = "";
  activeChat.messages.forEach((turn) => {
    if (turn?.role !== "user" && turn?.role !== "assistant" && turn?.role !== "system") {
      return;
    }

    if (turn.role === "system" && activeChat.collapse_system_trace && turn.system_type !== "memory_compaction") {
      return;
    }

    const bubble = addMessage(turn.role, String(turn.content ?? ""), String(turn.timestamp ?? ""), String(turn.status ?? ""));
    if (turn.role === "assistant") {
      const wrapper = bubble.parentElement;
      if (wrapper instanceof HTMLElement) {
        renderToolUsageLine(wrapper, turn.tool_usage);
      }
    }
  });

}

function renderChatHistory(options = {}) {
  const preserveScroll = Boolean(options && options.preserveScroll);
  const previousScrollTop = preserveScroll ? chatHistoryList.scrollTop : 0;
  chatHistoryList.innerHTML = "";
  const sortedChats = sortChatsByLatestMessage(state.chats);
  const filteredChats = getFilteredChats(sortedChats, state.chatHistorySearchTerm);
  const normalizedSearch = String(state.chatHistorySearchTerm || "").trim().toLowerCase();
  const signature = `${normalizedSearch}::${filteredChats.map((chat) => String(chat?.id || "")).join("|")}`;
  const signatureChanged = state.chatHistorySignature !== signature;
  if (!state.chatHistorySignature) {
    state.chatHistoryVisibleCount = CHAT_HISTORY_PAGE_SIZE;
  }
  state.chatHistorySignature = signature;
  if (signatureChanged) {
    state.chatHistoryVisibleCount = CHAT_HISTORY_PAGE_SIZE;
  }

  if (filteredChats.length === 0) {
    state.chatHistoryVisibleCount = CHAT_HISTORY_PAGE_SIZE;
    const emptyNode = document.createElement("p");
    emptyNode.className = "chat-history-empty";
    emptyNode.textContent = sortedChats.length === 0 ? "No chats yet." : "No matching chats.";
    chatHistoryList.appendChild(emptyNode);
    if (preserveScroll) {
      chatHistoryList.scrollTop = previousScrollTop;
    }
    return;
  }

  let visibleCount = Math.max(CHAT_HISTORY_PAGE_SIZE, Math.floor(Number(state.chatHistoryVisibleCount) || CHAT_HISTORY_PAGE_SIZE));
  visibleCount = Math.min(visibleCount, filteredChats.length);
  state.chatHistoryVisibleCount = visibleCount;

  filteredChats.slice(0, visibleCount).forEach((chat) => {
    const item = document.createElement("div");
    item.className = "chat-history-item";
    if (chat.id === state.activeChatId) {
      item.classList.add("active");
    }
    item.dataset.chatId = chat.id;

    const selectButton = document.createElement("button");
    selectButton.type = "button";
    selectButton.className = "chat-history-main";
    selectButton.dataset.chatId = chat.id;
    selectButton.dataset.action = "open";
    selectButton.disabled = false;

    const titleNode = document.createElement("p");
    titleNode.className = "chat-history-title";
    titleNode.textContent = normalizeChatTitle(chat.title);

    const timeNode = document.createElement("p");
    timeNode.className = "chat-history-time";
    const latestTimestamp = getLatestChatTimestamp(chat);
    const pendingMessages = Array.isArray(chat.messages)
      ? chat.messages.filter((message) => message && message.role === "assistant" && (message.status === "queued" || message.status === "processing"))
      : [];
    const queuedCount = pendingMessages.filter((message) => message.status === "queued").length;
    const processingCount = pendingMessages.filter((message) => message.status === "processing").length;
    timeNode.textContent = latestTimestamp ? formatMessageTimestamp(latestTimestamp) : "No messages yet";

    const queueBadgeNode = document.createElement("p");
    queueBadgeNode.className = "chat-history-queue-badge";
    if (processingCount > 0 && queuedCount > 0) {
      queueBadgeNode.textContent = `${queuedCount} queued`;
    } else if (processingCount > 0) {
      queueBadgeNode.textContent = "processing";
    } else if (queuedCount > 0) {
      queueBadgeNode.textContent = `${queuedCount} queued`;
    } else {
      queueBadgeNode.textContent = "";
    }

    selectButton.appendChild(titleNode);
    selectButton.appendChild(timeNode);
    if (queueBadgeNode.textContent) {
      selectButton.appendChild(queueBadgeNode);
    }

    const actionsNode = document.createElement("div");
    actionsNode.className = "chat-history-actions";

    const editButton = document.createElement("button");
    editButton.type = "button";
    editButton.className = "chat-history-action-btn";
    editButton.dataset.chatId = chat.id;
    editButton.dataset.action = "edit";
    editButton.disabled = state.isSwitching || state.isCompacting;
    editButton.setAttribute("aria-label", "Edit chat title");
    editButton.textContent = "✎";

    const deleteButton = document.createElement("button");
    deleteButton.type = "button";
    deleteButton.className = "chat-history-action-btn danger";
    deleteButton.dataset.chatId = chat.id;
    deleteButton.dataset.action = "delete";
    deleteButton.disabled = state.isSwitching || state.isCompacting;
    deleteButton.setAttribute("aria-label", "Delete chat");
    deleteButton.textContent = "×";

    actionsNode.appendChild(deleteButton);
    actionsNode.appendChild(editButton);

    item.appendChild(selectButton);
    item.appendChild(actionsNode);
    chatHistoryList.appendChild(item);
  });

  if (visibleCount < filteredChats.length) {
    const moreNode = document.createElement("p");
    moreNode.className = "chat-history-more";
    moreNode.textContent = `Showing ${visibleCount} of ${filteredChats.length}. Scroll for more...`;
    chatHistoryList.appendChild(moreNode);
  }

  if (preserveScroll) {
    chatHistoryList.scrollTop = previousScrollTop;
  }
}

function maybeLoadMoreChatHistory() {
  if (!(chatHistoryList instanceof HTMLElement)) {
    return;
  }
  const sortedChats = sortChatsByLatestMessage(state.chats);
  const filteredChats = getFilteredChats(sortedChats, state.chatHistorySearchTerm);
  if (filteredChats.length <= state.chatHistoryVisibleCount) {
    return;
  }
  if (chatHistoryList.scrollHeight <= chatHistoryList.clientHeight) {
    return;
  }
  const distanceFromBottom = chatHistoryList.scrollHeight - chatHistoryList.clientHeight - chatHistoryList.scrollTop;
  if (distanceFromBottom > CHAT_HISTORY_SCROLL_LOAD_THRESHOLD_PX) {
    return;
  }
  state.chatHistoryVisibleCount = Math.min(
    filteredChats.length,
    state.chatHistoryVisibleCount + CHAT_HISTORY_PAGE_SIZE,
  );
  renderChatHistory({ preserveScroll: true });
}

async function deleteChat(chatId) {
  const index = state.chats.findIndex((chat) => chat.id === chatId);
  if (index === -1) {
    return;
  }

  removeChatRuntime(chatId);
  delete state.pendingEnqueueByChat[chatId];

  state.chats.splice(index, 1);

  if (state.activeChatId === chatId) {
    const nextActiveChat = sortChatsByLatestMessage(state.chats)[0] ?? null;
    state.activeChatId = nextActiveChat?.id ?? "";
    state.lastRequestTokens = 0;
  }

  renderChatHistory();
  renderActiveChat();
  syncUsedTokensToContext();
  updateComposerState();

  try {
    await persistChatsToSettings();
    setStatus("Chat deleted.");
  } catch (error) {
    setStatus(`Chat deleted locally, but save failed: ${error.message}`, true);
  }
}

async function editChatTitle(chatId) {
  const chat = state.chats.find((entry) => entry.id === chatId);
  if (!chat) {
    return;
  }

  const nextTitleRaw = window.prompt(
    `Edit chat title (max ${EDITABLE_CHAT_TITLE_MAX_LENGTH} characters):`,
    normalizeChatTitle(chat.title),
  );

  if (nextTitleRaw === null) {
    return;
  }

  chat.title = normalizeEditedChatTitle(nextTitleRaw);
  chat.updated_at = createTimestamp();
  renderChatHistory();
  updateCurrentChatTitle();

  try {
    await persistChatsToSettings();
    setStatus("Chat title updated.");
  } catch (error) {
    setStatus(`Title updated locally, but save failed: ${error.message}`, true);
  }
}

function activateChat(chatId) {
  state.activeChatId = chatId;
  state.lastRequestTokens = 0;
  closeMobileDrawers();
  renderChatHistory();
  renderActiveChat();
  syncUsedTokensToContext();
  updateComposerState();
  persistChatsToSettings().catch((error) => {
    setStatus(`Active chat changed locally, but save failed: ${error.message}`, true);
  });
}

function startNewChat() {
  if (state.isSwitching || state.isCompacting) {
    return;
  }

  closeMobileDrawers();
  const chat = createChatEntry("");
  chat.title = "New chat";
  state.chats.push(chat);
  state.activeChatId = chat.id;
  state.lastRequestTokens = 0;
  renderChatHistory();
  renderActiveChat();
  updateTokenCounter(0, state.modelTokenLimit);
  setStatus("New chat ready. Send a first message to create it.");
  updateComposerState();
  persistChatsToSettings().catch((error) => {
    setStatus(`New chat context set locally, but save failed: ${error.message}`, true);
  });
  chatInput.focus();
}

function setAssistantLoading(bubble, isLoading) {
  if (isLoading) {
    bubble.classList.add("is-loading");
    bubble.innerHTML = '<span class="typing-dots" aria-label="Krill is thinking"><span></span><span></span><span></span></span>';
    return;
  }

  bubble.classList.remove("is-loading");
}

function showCompactionProgressBubble() {
  if (state.compactionBubble instanceof HTMLElement) {
    return;
  }

  const bubble = addMessage("assistant", "");
  bubble.classList.add("is-loading");
  bubble.innerHTML =
    '<span class="compaction-loading">Chat compaction ongoing <span class="typing-dots" aria-label="Chat compaction ongoing"><span></span><span></span><span></span></span></span>';
  state.compactionBubble = bubble;
}

function clearCompactionProgressBubble() {
  if (!(state.compactionBubble instanceof HTMLElement)) {
    return;
  }

  const wrapper = state.compactionBubble.parentElement;
  if (wrapper instanceof HTMLElement) {
    wrapper.remove();
  }

  state.compactionBubble = null;
}

function escapeHtml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function handleTtsAudioError(container) {
  container.innerHTML = '<span class="voice-msg-expired">Audio no longer available</span>';
}

function createVoiceMessagePlayerHtml(audioUrl) {
  const id = "tts-" + audioUrl.replace(/[^a-z0-9]/gi, "-");
  return (
    '<div class="voice-msg-player" data-audio-url="' + audioUrl + '" id="' + id + '">' +
      '<button class="voice-msg-play-btn" onclick="toggleVoicePlayer(this)" aria-label="Play voice message">' +
        '<svg class="voice-msg-icon-play" viewBox="0 0 24 24" width="20" height="20" fill="currentColor"><polygon points="6,4 20,12 6,20"/></svg>' +
        '<svg class="voice-msg-icon-pause" viewBox="0 0 24 24" width="20" height="20" fill="currentColor" style="display:none"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>' +
      '</button>' +
      '<div class="voice-msg-track">' +
        '<div class="voice-msg-progress"><div class="voice-msg-progress-fill"></div></div>' +
        '<span class="voice-msg-time">0:00</span>' +
      '</div>' +
      '<audio preload="metadata" src="' + audioUrl + '" ' +
        'onerror="handleTtsAudioError(this.closest(\'.voice-msg-player\'))">' +
      '</audio>' +
    '</div>'
  );
}

/* exported */ function toggleVoicePlayer(btn) {
  const player = btn.closest(".voice-msg-player");
  if (!player) return;
  const audio = player.querySelector("audio");
  if (!audio) return;
  const iconPlay = player.querySelector(".voice-msg-icon-play");
  const iconPause = player.querySelector(".voice-msg-icon-pause");
  if (audio.paused) {
    // Pause all other active voice players first
    document.querySelectorAll(".voice-msg-player audio").forEach(function (other) {
      if (other !== audio && !other.paused) {
        other.pause();
        const otherPlayer = other.closest(".voice-msg-player");
        if (otherPlayer) {
          const op = otherPlayer.querySelector(".voice-msg-icon-play");
          const opp = otherPlayer.querySelector(".voice-msg-icon-pause");
          if (op) op.style.display = "";
          if (opp) opp.style.display = "none";
        }
      }
    });
    audio.play();
    if (iconPlay) iconPlay.style.display = "none";
    if (iconPause) iconPause.style.display = "";
  } else {
    audio.pause();
    if (iconPlay) iconPlay.style.display = "";
    if (iconPause) iconPause.style.display = "none";
  }
  // Wire up events if not already wired
  if (!audio.dataset.wired) {
    audio.dataset.wired = "1";
    var progressFill = player.querySelector(".voice-msg-progress-fill");
    var timeLabel = player.querySelector(".voice-msg-time");
    var progressTrack = player.querySelector(".voice-msg-progress");
    audio.addEventListener("timeupdate", function () {
      if (!audio.duration) return;
      var pct = (audio.currentTime / audio.duration) * 100;
      if (progressFill) progressFill.style.width = pct + "%";
      if (timeLabel) timeLabel.textContent = formatVoiceDuration(audio.currentTime);
    });
    audio.addEventListener("loadedmetadata", function () {
      if (timeLabel && audio.duration && isFinite(audio.duration)) {
        timeLabel.textContent = formatVoiceDuration(audio.duration);
      }
    });
    audio.addEventListener("ended", function () {
      if (iconPlay) iconPlay.style.display = "";
      if (iconPause) iconPause.style.display = "none";
      if (progressFill) progressFill.style.width = "0%";
      if (timeLabel && audio.duration && isFinite(audio.duration)) {
        timeLabel.textContent = formatVoiceDuration(audio.duration);
      }
    });
    if (progressTrack) {
      progressTrack.addEventListener("click", function (e) {
        if (!audio.duration) return;
        var rect = progressTrack.getBoundingClientRect();
        var ratio = (e.clientX - rect.left) / rect.width;
        audio.currentTime = ratio * audio.duration;
      });
    }
  }
}

function formatVoiceDuration(seconds) {
  var m = Math.floor(seconds / 60);
  var s = Math.floor(seconds % 60);
  return m + ":" + (s < 10 ? "0" : "") + s;
}

function handleInlineImageError(img) {
  const url = img.src;
  const alt = img.alt || url;
  const link = document.createElement("a");
  link.href = url;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  link.textContent = alt;
  const wrapper = img.parentElement;
  if (wrapper && wrapper.tagName === "A") {
    wrapper.replaceWith(link);
  } else {
    img.replaceWith(link);
  }
}

function renderInlineMarkdown(text) {
  let output = text;
  // Replace TTS audio URLs with voice message player (before other link processing)
  output = output.replace(/(?:\[([^\]]*)\]\()?\/api\/tts\/audio\/[a-f0-9\-]+\.mp3\)?/gi, function (match, linkText) {
    var urlMatch = match.match(/\/api\/tts\/audio\/[a-f0-9\-]+\.mp3/i);
    if (urlMatch) return createVoiceMessagePlayerHtml(urlMatch[0]);
    return match;
  });
  output = output.replace(/~~([^~]+)~~/g, "<del>$1</del>");
  output = output.replace(/\*\*\*([^*]+)\*\*\*/g, "<strong><em>$1</em></strong>");
  output = output.replace(/`([^`]+)`/g, "<code>$1</code>");
  output = output.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  output = output.replace(/\*([^*]+)\*/g, "<em>$1</em>");
  output = output.replace(/!\[([^\]]*)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer"><img src="$2" alt="$1" referrerpolicy="no-referrer" loading="lazy" onerror="handleInlineImageError(this)" /></a>');
  output = output.replace(/\[([^\]]+)\]\((\/api\/files\/shared\/[A-Za-z0-9_-]{10,200})\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer" download>$1</a>');
  output = output.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+\/api\/files\/shared\/[A-Za-z0-9_-]{10,200})\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer" download>$1</a>');
  output = output.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
  output = output.replace(/(^|[^"=])(https?:\/\/[^\s<>]+\.(?:png|jpe?g|gif|webp|svg|bmp|ico)(?:\?[^\s<>]*)?)(?=$|[\s,;)\]&])/gi, '$1<a href="$2" target="_blank" rel="noopener noreferrer"><img src="$2" alt="$2" referrerpolicy="no-referrer" loading="lazy" onerror="handleInlineImageError(this)" /></a>');
  output = output.replace(/(^|[\s(])(\/api\/files\/shared\/[A-Za-z0-9_-]{10,200})(?=$|[\s,;)\]])/g, '$1<a href="$2" target="_blank" rel="noopener noreferrer" download>$2</a>');
  output = output.replace(/(^|[\s(])(https?:\/\/[^\s)\]]+\/api\/files\/shared\/[A-Za-z0-9_-]{10,200})(?=$|[\s,;)\]])/g, '$1<a href="$2" target="_blank" rel="noopener noreferrer" download>$2</a>');
  return output;
}

function isTableSeparatorRow(line) {
  const normalized = line.trim().replace(/^\|/, "").replace(/\|$/, "");
  if (!normalized) {
    return false;
  }

  const parts = normalized.split("|").map((part) => part.trim());
  if (parts.length === 0) {
    return false;
  }

  return parts.every((part) => /^:?-{3,}:?$/.test(part));
}

function parseTableCells(line) {
  const normalized = line.trim().replace(/^\|/, "").replace(/\|$/, "");
  return normalized.split("|").map((cell) => renderInlineMarkdown(cell.trim()));
}

function renderMarkdown(rawText) {
  const escaped = escapeHtml(rawText || "");
  const lines = escaped.split("\n");
  const html = [];
  let inCodeBlock = false;
  let inUlList = false;
  let inOlList = false;

  function closeOpenLists() {
    if (inUlList) {
      html.push("</ul>");
      inUlList = false;
    }

    if (inOlList) {
      html.push("</ol>");
      inOlList = false;
    }
  }

  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i];
    const trimmed = line.trim();

    if (trimmed.startsWith("```")) {
      if (!inCodeBlock) {
        closeOpenLists();
        html.push("<pre><code>");
        inCodeBlock = true;
      } else {
        html.push("</code></pre>");
        inCodeBlock = false;
      }
      continue;
    }

    if (inCodeBlock) {
      html.push(`${line}\n`);
      continue;
    }

    if (trimmed.includes("|") && i + 1 < lines.length && isTableSeparatorRow(lines[i + 1])) {
      closeOpenLists();

      const headerCells = parseTableCells(trimmed);
      html.push("<table><thead><tr>");
      headerCells.forEach((cell) => {
        html.push(`<th>${cell}</th>`);
      });
      html.push("</tr></thead><tbody>");

      i += 2;
      while (i < lines.length) {
        const rowLine = lines[i];
        if (!rowLine.trim() || !rowLine.includes("|")) {
          i -= 1;
          break;
        }

        const rowCells = parseTableCells(rowLine);
        html.push("<tr>");
        rowCells.forEach((cell) => {
          html.push(`<td>${cell}</td>`);
        });
        html.push("</tr>");
        i += 1;
      }

      html.push("</tbody></table>");
      continue;
    }

    const unorderedMatch = trimmed.match(/^[-*+]\s+(.*)$/);
    if (unorderedMatch) {
      if (!inUlList) {
        if (inOlList) {
          html.push("</ol>");
          inOlList = false;
        }
        html.push("<ul>");
        inUlList = true;
      }
      html.push(`<li>${renderInlineMarkdown(unorderedMatch[1])}</li>`);
      continue;
    }

    const orderedMatch = trimmed.match(/^\d+\.\s+(.*)$/);
    if (orderedMatch) {
      if (!inOlList) {
        if (inUlList) {
          html.push("</ul>");
          inUlList = false;
        }
        html.push("<ol>");
        inOlList = true;
      }
      html.push(`<li>${renderInlineMarkdown(orderedMatch[1])}</li>`);
      continue;
    }

    closeOpenLists();

    if (/^---+$/.test(trimmed) || /^\*\*\*+$/.test(trimmed)) {
      html.push("<hr>");
      continue;
    }

    if (trimmed.startsWith("> ")) {
      html.push(`<blockquote>${renderInlineMarkdown(trimmed.slice(2))}</blockquote>`);
      continue;
    }

    if (trimmed.length === 0) {
      html.push("<br>");
      continue;
    }

    const headingMatch = trimmed.match(/^(#{1,6})\s+(.*)$/);
    if (headingMatch) {
      const level = headingMatch[1].length;
      html.push(`<h${level}>${renderInlineMarkdown(headingMatch[2])}</h${level}>`);
      continue;
    }

    html.push(`<p>${renderInlineMarkdown(trimmed)}</p>`);
  }

  closeOpenLists();

  if (inCodeBlock) {
    html.push("</code></pre>");
  }

  return html.join("");
}

function updateMetaIndicators() {
  providerIndicator.textContent = state.providerLabel || "Not configured";
  modelIndicator.textContent = state.modelLabel || "Not configured";
}

function updateAssistantHeader(settings) {
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

function formatNumber(value) {
  return Number(value || 0).toLocaleString("de-DE");
}

function getTodayDateKey() {
  const now = getServerDate();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}


function addDaysToDateKey(dateKey, daysDelta) {
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

function formatDateShort(dateKey) {
  const parts = String(dateKey || "").split("-");
  if (parts.length !== 3) {
    return dateKey;
  }
  return `${parts[2]}.${parts[1]}`;
}

function normalizeDailyTokenUsage(rawUsage) {
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

function updateDailyTokenUsageLabel() {
  const hasDesktopNode = dailyTokenUsageNode instanceof HTMLElement;
  const hasMobileNode = mobileLeftDailyTokenUsageNode instanceof HTMLElement;
  if (!hasDesktopNode && !hasMobileNode) {
    return;
  }

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
    renderTokenUsageModal();
  }
}

function updateTelegramStatusLabel() {
  if (!(telegramStatusNode instanceof HTMLElement)) {
    return;
  }

  if (!state.telegramEnabled) {
    telegramStatusNode.textContent = "Telegram: disabled";
    return;
  }

  if (!state.telegramTokenConfigured) {
    telegramStatusNode.textContent = "Telegram: enabled, token missing";
    return;
  }

  if (!state.telegramOwnerUserId) {
    telegramStatusNode.textContent = "Telegram: waiting for first owner message";
    return;
  }

  if (!state.telegramOwnerChatId) {
    telegramStatusNode.textContent = "Telegram: owner bound, waiting for chat target";
    return;
  }

  telegramStatusNode.textContent = "Telegram: connected";
}

function updateShortTermMemoryBadge() {
  const hasDesktopNode = shortTermMemoryStatusNode instanceof HTMLElement;
  const hasMobileNode = mobileLeftShortTermMemoryStatusNode instanceof HTMLElement;
  if (!hasDesktopNode && !hasMobileNode) {
    return;
  }
  const pending = Math.max(0, Number(state.shortTermMemoryCount || 0));
  const suffix = state.shortTermMemoryExtracting ? " - identifying..." : "";
  const label = `Short Term Memory: ${formatNumber(pending)} pending${suffix}`;
  if (hasDesktopNode) {
    shortTermMemoryStatusNode.textContent = label;
  }
  if (hasMobileNode) {
    mobileLeftShortTermMemoryStatusNode.textContent = label;
  }
  if (hasDesktopNode) {
    shortTermMemoryStatusNode.classList.toggle("assistant-meta-alert", pending > 0);
  }
  if (hasMobileNode) {
    mobileLeftShortTermMemoryStatusNode.classList.toggle("assistant-meta-alert", pending > 0);
  }
}

async function loadAppVersion() {
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

function syncTelegramFlagsFromIntegrationConfig() {
  const telegramConfig = getIntegrationConfig("telegram");
  state.telegramEnabled = Boolean(telegramConfig.enabled);
  state.telegramTokenConfigured = Boolean(
    typeof telegramConfig.params?.bot_token === "string" && telegramConfig.params.bot_token.trim(),
  );
}

function applyIntegrationStatusPayload(payload) {
  const statuses = payload?.statuses;
  const telegramStatus = statuses && typeof statuses === "object" ? statuses.telegram : null;
  if (!telegramStatus || typeof telegramStatus !== "object") {
    return;
  }

  state.telegramEnabled = Boolean(telegramStatus.enabled);
  state.telegramTokenConfigured = Boolean(telegramStatus.token_configured);
  state.telegramOwnerUserId = typeof telegramStatus.owner_user_id === "string" ? telegramStatus.owner_user_id : "";
  state.telegramOwnerChatId = typeof telegramStatus.owner_chat_id === "string" ? telegramStatus.owner_chat_id : "";
  updateTelegramStatusLabel();
}

function renderTimedJobAuthAlert(payload) {
  if (!(timedJobAuthAlertNode instanceof HTMLElement)) {
    return;
  }
  const active = Boolean(payload?.active);
  if (!active) {
    timedJobAuthAlertNode.textContent = "";
    timedJobAuthAlertNode.classList.add("hidden");
    return;
  }
  const providerIds = Array.isArray(payload?.provider_ids)
    ? payload.provider_ids.map((entry) => String(entry || "").trim()).filter(Boolean)
    : [];
  const providerLabel = providerIds.length > 0 ? providerIds.join(", ") : "current provider";
  const detail = typeof payload?.detail === "string" ? payload.detail.trim() : "";
  timedJobAuthAlertNode.textContent = detail
    || `Timed jobs are suppressing repeated auth-expired alerts for ${providerLabel}. Reconnect the provider in Setup.`;
  timedJobAuthAlertNode.classList.remove("hidden");
}

async function syncTimedJobAuthAlertStatus() {
  if (state.timedJobAuthAlertSyncInFlight) {
    return;
  }
  state.timedJobAuthAlertSyncInFlight = true;
  try {
    const response = await fetch("/api/timed-jobs/auth-alert-status", { cache: "no-store" });
    if (!response.ok) {
      return;
    }
    const payload = await response.json();
    renderTimedJobAuthAlert(payload);
  } catch (error) {
    // Keep sync best-effort and silent.
  } finally {
    state.timedJobAuthAlertSyncInFlight = false;
  }
}

async function syncIntegrationStatus() {
  if (state.integrationStatusSyncInFlight) {
    return;
  }

  state.integrationStatusSyncInFlight = true;
  try {
    const response = await fetch("/api/integrations/status", { cache: "no-store" });
    if (!response.ok) {
      return;
    }
    const payload = await response.json();
    applyIntegrationStatusPayload(payload);
  } catch (error) {
    // Keep sync best-effort and silent.
  } finally {
    state.integrationStatusSyncInFlight = false;
  }
}

function addDailyTokenUsage(tokensToAdd) {
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

  updateDailyTokenUsageLabel();
}

function updateTokenCounter(usedTokens = state.usedTokens, tokenLimit = state.modelTokenLimit) {
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

function getProviderById(providerId) {
  return state.providers.find((provider) => provider.id === providerId);
}

function getConfiguredProviderIds() {
  return Object.keys(state.settings?.provider_configs ?? {});
}

function getModelTokenLimit(providerId, modelId) {
  const provider = getProviderById(providerId);
  const model = provider?.models?.find((entry) => entry.id === modelId);
  if (model?.token_limit) {
    return Number(model.token_limit);
  }

  return 0;
}

function estimateContextTokens(messages, memoryBlock = "") {
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

function syncUsedTokensToContext() {
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

function shouldCompactForLimit(messages, memoryBlock, tokenLimit) {
  const safeLimit = Math.max(0, Number(tokenLimit || 0));
  if (safeLimit <= 0) {
    return false;
  }

  const observedContext = Math.max(0, Number(state.lastRequestTokens || 0));
  const estimatedContext = estimateContextTokens(messages, memoryBlock);
  const contextTokens = Math.max(observedContext, estimatedContext);
  return contextTokens >= safeLimit * 0.75;
}

function setSwitchersDisabled(disabled) {
  providerSelectNodes.forEach((selectNode) => {
    selectNode.disabled = disabled;
  });
  modelSelectNodes.forEach((selectNode) => {
    selectNode.disabled = disabled;
  });
}

function setCompactButtonDisabled(disabled) {
  if (compactButton instanceof HTMLButtonElement) {
    compactButton.disabled = disabled;
  }
}

function renderProviderSwitcher(selectedProviderId = state.activeProviderId) {
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

function renderModelSwitcher(providerId, selectedModelId = "") {
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

function syncSwitcherControls() {
  const providerId = renderProviderSwitcher(state.activeProviderId);
  renderModelSwitcher(providerId, state.activeModelId);
}

async function verifyProviderModel(providerId, modelId, apiKey) {
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

async function persistSettings(nextSettings) {
  const response = await fetch("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(nextSettings),
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

async function persistActiveProviderModel(providerId, modelId) {
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

async function persistChatState(chats, activeChatId, dailyTokenUsage) {
  const response = await fetch("/api/chat/state", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      chats,
      active_chat_id: activeChatId,
      daily_token_usage: dailyTokenUsage,
    }),
  });

  if (!response.ok) {
    const detail = await buildHttpErrorDetail(response, "Failed to save chat state.");
    throw new Error(detail);
  }

  return response.json();
}

async function registerCompletedTurnForMemory(sourceChannel, sourceChatId, userMessage, assistantMessage) {
  const response = await fetch("/api/memory/turn-complete", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      source_channel: sourceChannel,
      source_chat_id: sourceChatId || "",
      user_message: userMessage,
      assistant_message: assistantMessage || "",
    }),
  });
  if (!response.ok) {
    return;
  }
}

async function persistChatsToSettingsDirect() {
  if (!state.settings) {
    return;
  }

  const persisted = await persistChatState(state.chats, state.activeChatId, state.dailyTokenUsage);
  state.chats = mergeSessionOnlySystemMessages(normalizeIncomingChats(persisted.chats), state.chats);
  if (typeof persisted.active_chat_id === "string") {
    state.activeChatId = persisted.active_chat_id;
  }
  state.dailyTokenUsage = normalizeDailyTokenUsage(persisted.daily_token_usage);
  if (state.settings && typeof state.settings === "object") {
    state.settings.chats = state.chats;
    state.settings.active_chat_id = state.activeChatId;
    state.settings.daily_token_usage = state.dailyTokenUsage;
  }
  refreshLocalChatStateSignature();
  updateDailyTokenUsageLabel();
}

async function persistChatsToSettings() {
  if (!state.settings) {
    return;
  }

  markLocalChatStatePending();

  if (state.chatPersistInFlight) {
    state.chatPersistQueued = true;
    if (state.chatPersistPromise) {
      await state.chatPersistPromise;
    }
    return;
  }

  state.chatPersistInFlight = true;
  state.chatPersistPromise = (async () => {
    let lastError = null;
    do {
      state.chatPersistQueued = false;
      try {
        await persistChatsToSettingsDirect();
        lastError = null;
      } catch (error) {
        lastError = error;
      }
    } while (state.chatPersistQueued);

    if (lastError) {
      throw lastError;
    }
  })();

  try {
    await state.chatPersistPromise;
  } finally {
    state.chatPersistInFlight = false;
    state.chatPersistPromise = null;
    state.chatStateDirty = false;
  }
}

async function persistMemoriesToSettings() {
  if (!state.settings) {
    return;
  }

  const nextSettings = JSON.parse(JSON.stringify(state.settings));
  nextSettings.core_memories = state.coreMemories;
  nextSettings.normal_memories = state.normalMemories;
  nextSettings.chats = state.chats;
  nextSettings.active_chat_id = state.activeChatId;
  nextSettings.daily_token_usage = state.dailyTokenUsage;

  const persisted = await persistSettings(nextSettings);
  state.settings = persisted;
  state.coreMemories = normalizeIncomingMemories(persisted.core_memories);
  state.normalMemories = normalizeIncomingMemories(persisted.normal_memories);
}

function updateMemoryCompactionButtons() {
  if (compactCoreMemoryButton instanceof HTMLButtonElement) {
    const busy = state.memoryCompactionType === "core";
    compactCoreMemoryButton.disabled = busy;
    compactCoreMemoryButton.textContent = busy ? "Compacting..." : "Compaction";
  }
  if (compactNormalMemoryButton instanceof HTMLButtonElement) {
    const busy = state.memoryCompactionType === "normal";
    compactNormalMemoryButton.disabled = busy;
    compactNormalMemoryButton.textContent = busy ? "Compacting..." : "Compaction";
  }
}

async function compactMemoryType(memoryType) {
  if (!state.settings || state.memoryCompactionType) {
    return;
  }

  const targetType = memoryType === "core" ? "core" : "normal";
  state.memoryCompactionType = targetType;
  updateMemoryCompactionButtons();

  try {
    setStatus(`Compacting ${targetType} memories...`);
    const response = await fetch("/api/memory/compact", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ memory_type: targetType }),
    });

    if (!response.ok) {
      const detail = await buildHttpErrorDetail(response, "Memory compaction failed.");
      throw new Error(detail);
    }

    const payload = await response.json();
    state.coreMemories = normalizeIncomingMemories(payload.core_memories);
    state.normalMemories = normalizeIncomingMemories(payload.normal_memories);
    if (state.settings) {
      state.settings.core_memories = state.coreMemories;
      state.settings.normal_memories = state.normalMemories;
    }
    renderMemoryManagement();

    const compactedCount = Number.isFinite(Number(payload.compacted_count)) ? Number(payload.compacted_count) : 0;
    const typeLabel = targetType === "core" ? "Core" : "Normal";
    const message = compactedCount > 0
      ? `${typeLabel} memories compacted (${compactedCount} -> 1).`
      : `${typeLabel} memories compacted.`;
    setStatus(message);
    showToast(message);
  } catch (error) {
    setStatus(normalizeErrorMessage(error, "Memory compaction failed."), true);
  } finally {
    state.memoryCompactionType = "";
    updateMemoryCompactionButtons();
  }
}

function openMemoryManagementModal() {
  if (!(memoryModal instanceof HTMLElement)) {
    return;
  }

  if (coreMemorySearchInput instanceof HTMLInputElement) {
    coreMemorySearchInput.value = "";
    state.coreMemorySearchTerm = "";
  }
  if (normalMemorySearchInput instanceof HTMLInputElement) {
    normalMemorySearchInput.value = "";
    state.normalMemorySearchTerm = "";
  }
  state.coreMemoryEditingIndex = -1;
  state.normalMemoryEditingIndex = -1;
  state.coreMemoryEditDraft = "";
  state.normalMemoryEditDraft = "";

  renderMemoryManagement();
  memoryModal.classList.remove("hidden");
  document.body.style.overflow = "hidden";
  refreshMemoriesFromServer().catch(() => {});

  if (coreMemorySearchInput instanceof HTMLInputElement) {
    coreMemorySearchInput.focus();
  }
}

function closeMemoryManagementModal() {
  if (!(memoryModal instanceof HTMLElement)) {
    return;
  }

  memoryModal.classList.add("hidden");
  if ((!(brainModal instanceof HTMLElement) || brainModal.classList.contains("hidden"))
    && (!(timedJobsModal instanceof HTMLElement) || timedJobsModal.classList.contains("hidden"))
    && (!(tokenUsageModal instanceof HTMLElement) || tokenUsageModal.classList.contains("hidden"))
    && (!(changePasswordModal instanceof HTMLElement) || changePasswordModal.classList.contains("hidden"))
    && (!state.mobileLeftDrawerOpen && !state.mobileRightDrawerOpen)) {
    document.body.style.overflow = "";
  }
}

function renderBrainTableList() {
  if (!(brainTableList instanceof HTMLElement)) {
    return;
  }

  brainTableList.innerHTML = "";

  if (!Array.isArray(state.brainTables) || state.brainTables.length === 0) {
    const emptyNode = document.createElement("p");
    emptyNode.className = "memory-empty";
    emptyNode.textContent = "No tables found.";
    brainTableList.appendChild(emptyNode);
    return;
  }

  state.brainTables.forEach((table) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "brain-table-item";
    if (table.name === state.selectedBrainTable) {
      button.classList.add("active");
    }
    button.dataset.tableName = table.name;
    button.textContent = `${table.name} (${table.row_count})`;
    brainTableList.appendChild(button);
  });
}

function renderSelectedBrainTable() {
  if (!(brainTableTitle instanceof HTMLElement) || !(brainTableColumns instanceof HTMLElement) || !(brainTableView instanceof HTMLElement)) {
    return;
  }

  const table = state.brainTables.find((entry) => entry.name === state.selectedBrainTable);
  if (!table) {
    brainTableTitle.textContent = "Select a table";
    brainTableColumns.textContent = "";
    brainTableView.innerHTML = "";
    return;
  }

  brainTableTitle.textContent = `${table.name} (${table.row_count} rows)`;
  const columnLabels = Array.isArray(table.columns)
    ? table.columns.map((column) => `${column.name}:${column.type || "text"}`)
    : [];
  brainTableColumns.textContent = columnLabels.length > 0 ? columnLabels.join(" | ") : "No columns";

  brainTableView.innerHTML = "";
  const rows = Array.isArray(table.rows) ? table.rows : [];
  const columns = Array.isArray(table.columns) ? table.columns : [];
  if (rows.length === 0 || columns.length === 0) {
    const emptyNode = document.createElement("p");
    emptyNode.className = "memory-empty";
    emptyNode.textContent = "No rows in this table.";
    brainTableView.appendChild(emptyNode);
    return;
  }

  const tableNode = document.createElement("table");
  tableNode.className = "brain-grid";

  const thead = document.createElement("thead");
  const headRow = document.createElement("tr");
  columns.forEach((column) => {
    const th = document.createElement("th");
    th.textContent = column.name;
    headRow.appendChild(th);
  });
  thead.appendChild(headRow);
  tableNode.appendChild(thead);

  const tbody = document.createElement("tbody");
  rows.forEach((row) => {
    const tr = document.createElement("tr");
    columns.forEach((column) => {
      const td = document.createElement("td");
      const value = row[column.name];
      td.textContent = value === null || value === undefined ? "" : String(value);
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
  tableNode.appendChild(tbody);
  brainTableView.appendChild(tableNode);
}

async function loadBrainView() {
  if (state.brainLoading) {
    return;
  }

  state.brainLoading = true;
  if (brainModalMetaNode instanceof HTMLElement) {
    brainModalMetaNode.textContent = "Loading brain tables...";
  }
  if (brainRefreshButton instanceof HTMLButtonElement) {
    brainRefreshButton.disabled = true;
  }

  try {
    const response = await fetch("/api/braindump/view", { cache: "no-store" });
    if (!response.ok) {
      throw new Error("Failed to load brain view.");
    }

    const payload = await response.json();
    const tables = Array.isArray(payload.tables) ? payload.tables : [];
    state.brainTables = tables;
    if (!tables.some((table) => table.name === state.selectedBrainTable)) {
      state.selectedBrainTable = tables[0]?.name ?? "";
    }

    if (brainModalMetaNode instanceof HTMLElement) {
      brainModalMetaNode.textContent = `${payload.table_count ?? tables.length} tables loaded`;
    }
    renderBrainTableList();
    renderSelectedBrainTable();
  } catch (error) {
    if (brainModalMetaNode instanceof HTMLElement) {
      brainModalMetaNode.textContent = normalizeErrorMessage(error, "Failed to load brain tables.");
    }
    state.brainTables = [];
    state.selectedBrainTable = "";
    renderBrainTableList();
    renderSelectedBrainTable();
  } finally {
    state.brainLoading = false;
    if (brainRefreshButton instanceof HTMLButtonElement) {
      brainRefreshButton.disabled = false;
    }
  }
}

function openBrainModal() {
  if (!(brainModal instanceof HTMLElement)) {
    return;
  }
  brainModal.classList.remove("hidden");
  document.body.style.overflow = "hidden";
  loadBrainView();
}

function closeBrainModal() {
  if (!(brainModal instanceof HTMLElement)) {
    return;
  }
  brainModal.classList.add("hidden");
  if ((!(memoryModal instanceof HTMLElement) || memoryModal.classList.contains("hidden"))
    && (!state.mobileLeftDrawerOpen && !state.mobileRightDrawerOpen)
    && (!(timedJobsModal instanceof HTMLElement) || timedJobsModal.classList.contains("hidden"))
    && (!(shortTermMemoryModal instanceof HTMLElement) || shortTermMemoryModal.classList.contains("hidden"))
    && (!(tokenUsageModal instanceof HTMLElement) || tokenUsageModal.classList.contains("hidden"))
    && (!(changePasswordModal instanceof HTMLElement) || changePasswordModal.classList.contains("hidden"))) {
    document.body.style.overflow = "";
  }
}

async function fetchShortTermMemory() {
  const response = await fetch("/api/memory/short-term", { cache: "no-store" });
  if (!response.ok) {
    const detail = await buildHttpErrorDetail(response, "Failed to load short term memory.");
    throw new Error(detail);
  }
  return response.json();
}

async function resolveShortTermMemory(items) {
  const response = await fetch("/api/memory/short-term/resolve", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ items }),
  });
  if (!response.ok) {
    const detail = await buildHttpErrorDetail(response, "Failed to resolve short term memory.");
    throw new Error(detail);
  }
  return response.json();
}

async function refreshMemoriesFromServer() {
  const response = await fetch("/api/settings", { cache: "no-store" });
  if (!response.ok) {
    const detail = await buildHttpErrorDetail(response, "Failed to refresh memories.");
    throw new Error(detail);
  }

  const settings = await response.json();
  state.settings = settings;
  state.coreMemories = normalizeIncomingMemories(settings?.core_memories);
  state.normalMemories = normalizeIncomingMemories(settings?.normal_memories);

  if (memoryModal instanceof HTMLElement && !memoryModal.classList.contains("hidden")) {
    renderMemoryManagement();
  }
}

function renderShortTermMemory() {
  if (!(shortTermMemoryListNode instanceof HTMLElement)) {
    return;
  }
  shortTermMemoryListNode.innerHTML = "";

  if (!Array.isArray(state.shortTermMemories) || state.shortTermMemories.length === 0) {
    const emptyNode = document.createElement("p");
    emptyNode.className = "memory-empty";
    emptyNode.textContent = "No short term memories pending.";
    shortTermMemoryListNode.appendChild(emptyNode);
    return;
  }

  state.shortTermMemories.forEach((item) => {
    const wrapper = document.createElement("article");
    wrapper.className = "short-term-item";
    wrapper.dataset.shortTermId = String(item.id);

    const contentNode = document.createElement("p");
    contentNode.className = "short-term-item-content";
    contentNode.textContent = item.content;

    const row = document.createElement("div");
    row.className = "short-term-item-row";

    const typeSelect = document.createElement("select");
    typeSelect.className = "short-term-item-type";
    typeSelect.dataset.shortTermType = "1";
    typeSelect.dataset.shortTermId = String(item.id);

    ["core", "normal"].forEach((type) => {
      const option = document.createElement("option");
      option.value = type;
      option.textContent = type;
      typeSelect.appendChild(option);
    });
    typeSelect.value = item.memory_type === "core" ? "core" : "normal";

    const actions = document.createElement("div");
    actions.className = "short-term-item-actions";

    const confirmButton = document.createElement("button");
    confirmButton.type = "button";
    confirmButton.className = "short-term-action-btn short-term-action-confirm";
    confirmButton.dataset.shortTermAction = "accept";
    confirmButton.dataset.shortTermId = String(item.id);
    confirmButton.textContent = "Confirm";

    const declineButton = document.createElement("button");
    declineButton.type = "button";
    declineButton.className = "short-term-action-btn short-term-action-decline";
    declineButton.dataset.shortTermAction = "decline";
    declineButton.dataset.shortTermId = String(item.id);
    declineButton.textContent = "Decline";

    actions.appendChild(confirmButton);
    actions.appendChild(declineButton);
    row.appendChild(typeSelect);
    row.appendChild(actions);
    wrapper.appendChild(contentNode);
    wrapper.appendChild(row);
    shortTermMemoryListNode.appendChild(wrapper);
  });
}

function openShortTermMemoryModal() {
  if (!(shortTermMemoryModal instanceof HTMLElement)) {
    return;
  }
  shortTermMemoryModal.classList.remove("hidden");
  document.body.style.overflow = "hidden";
  loadShortTermMemory(true);
}

function closeShortTermMemoryModal() {
  if (!(shortTermMemoryModal instanceof HTMLElement)) {
    return;
  }
  shortTermMemoryModal.classList.add("hidden");
  if (
    (!(memoryModal instanceof HTMLElement) || memoryModal.classList.contains("hidden"))
    && (!(brainModal instanceof HTMLElement) || brainModal.classList.contains("hidden"))
    && (!(timedJobsModal instanceof HTMLElement) || timedJobsModal.classList.contains("hidden"))
    && (!(tokenUsageModal instanceof HTMLElement) || tokenUsageModal.classList.contains("hidden"))
    && (!(changePasswordModal instanceof HTMLElement) || changePasswordModal.classList.contains("hidden"))
    && (!state.mobileLeftDrawerOpen && !state.mobileRightDrawerOpen)
  ) {
    document.body.style.overflow = "";
  }
}

async function loadShortTermMemory(renderModal = false) {
  if (state.shortTermMemorySyncInFlight) {
    return;
  }
  state.shortTermMemorySyncInFlight = true;
  if (renderModal && shortTermMemoryMetaNode instanceof HTMLElement) {
    shortTermMemoryMetaNode.textContent = "Loading short term memory...";
  }
  const shouldTouchRefreshButton = renderModal
    || (shortTermMemoryModal instanceof HTMLElement && !shortTermMemoryModal.classList.contains("hidden"));
  if (shouldTouchRefreshButton && shortTermMemoryRefreshButton instanceof HTMLButtonElement) {
    shortTermMemoryRefreshButton.disabled = true;
  }

  try {
    const payload = await fetchShortTermMemory();
    const items = Array.isArray(payload.items) ? payload.items : [];
    state.shortTermMemoryExtracting = Boolean(payload?.extraction?.in_progress);
    const previousCount = state.shortTermMemoryCount;
    state.shortTermMemories = items;
    state.shortTermMemoryCount = Number.isFinite(Number(payload.count)) ? Number(payload.count) : items.length;

    if (state.shortTermMemoryCount > previousCount && state.shortTermMemoryCount > state.shortTermMemoryLastToastCount) {
      showToast("Memories identified - check Short Term Memory.");
      state.shortTermMemoryLastToastCount = state.shortTermMemoryCount;
    }

    updateShortTermMemoryBadge();

    if (shortTermMemoryMetaNode instanceof HTMLElement) {
      shortTermMemoryMetaNode.textContent = state.shortTermMemoryExtracting
        ? `${state.shortTermMemoryCount} pending - identifying...`
        : `${state.shortTermMemoryCount} pending`;
    }
    updateShortTermMemoryBadge();

    if (renderModal || (shortTermMemoryModal instanceof HTMLElement && !shortTermMemoryModal.classList.contains("hidden"))) {
      renderShortTermMemory();
    }
  } catch (error) {
    if (renderModal && shortTermMemoryMetaNode instanceof HTMLElement) {
      shortTermMemoryMetaNode.textContent = normalizeErrorMessage(error, "Failed to load short term memory.");
    }
  } finally {
    state.shortTermMemorySyncInFlight = false;
    if (shouldTouchRefreshButton && shortTermMemoryRefreshButton instanceof HTMLButtonElement) {
      shortTermMemoryRefreshButton.disabled = false;
    }
  }
}

function buildTokenUsageSeries() {
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

function renderTokenUsageModal() {
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

function openTokenUsageModal() {
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

function closeTokenUsageModal() {
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

function resetChangePasswordForm() {
  if (changePasswordForm instanceof HTMLFormElement) {
    changePasswordForm.reset();
  }
}

function setChangePasswordSubmitting(submitting) {
  const disabled = Boolean(submitting);
  if (changePasswordOldInput instanceof HTMLInputElement) {
    changePasswordOldInput.disabled = disabled;
  }
  if (changePasswordNewInput instanceof HTMLInputElement) {
    changePasswordNewInput.disabled = disabled;
  }
  if (changePasswordConfirmInput instanceof HTMLInputElement) {
    changePasswordConfirmInput.disabled = disabled;
  }
  if (changePasswordSubmitButton instanceof HTMLButtonElement) {
    changePasswordSubmitButton.disabled = disabled;
  }
}

function setChangePasswordFormEnabled(enabled) {
  const allowInput = Boolean(enabled);
  if (changePasswordOldInput instanceof HTMLInputElement) {
    changePasswordOldInput.disabled = !allowInput;
  }
  if (changePasswordNewInput instanceof HTMLInputElement) {
    changePasswordNewInput.disabled = !allowInput;
  }
  if (changePasswordConfirmInput instanceof HTMLInputElement) {
    changePasswordConfirmInput.disabled = !allowInput;
  }
  if (changePasswordSubmitButton instanceof HTMLButtonElement) {
    changePasswordSubmitButton.disabled = !allowInput;
  }
}

function openChangePasswordModal() {
  if (!(changePasswordModal instanceof HTMLElement)) {
    return;
  }
  resetChangePasswordForm();
  setChangePasswordFormEnabled(true);
  setChangePasswordSubmitting(false);
  changePasswordModal.classList.remove("hidden");
  document.body.style.overflow = "hidden";
  if (changePasswordOldInput instanceof HTMLInputElement) {
    changePasswordOldInput.focus();
  }
}

function closeChangePasswordModal() {
  if (!(changePasswordModal instanceof HTMLElement)) {
    return;
  }
  changePasswordModal.classList.add("hidden");
  setChangePasswordSubmitting(false);
  resetChangePasswordForm();
  setChangePasswordFormEnabled(false);
  if (
    (!(memoryModal instanceof HTMLElement) || memoryModal.classList.contains("hidden"))
    && (!(brainModal instanceof HTMLElement) || brainModal.classList.contains("hidden"))
    && (!(timedJobsModal instanceof HTMLElement) || timedJobsModal.classList.contains("hidden"))
    && (!(shortTermMemoryModal instanceof HTMLElement) || shortTermMemoryModal.classList.contains("hidden"))
    && (!(tokenUsageModal instanceof HTMLElement) || tokenUsageModal.classList.contains("hidden"))
    && (!state.mobileLeftDrawerOpen && !state.mobileRightDrawerOpen)
  ) {
    document.body.style.overflow = "";
  }
}

async function submitPasswordChange(oldPassword, newPassword, confirmNewPassword) {
  const response = await fetch("/api/auth/change-password", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      old_password: oldPassword,
      new_password: newPassword,
      confirm_new_password: confirmNewPassword,
    }),
  });
  if (!response.ok) {
    const detail = await buildHttpErrorDetail(response, "Failed to change password.");
    throw new Error(detail);
  }
}

async function handleChangePasswordSubmit(event) {
  event.preventDefault();
  if (!(changePasswordOldInput instanceof HTMLInputElement)
    || !(changePasswordNewInput instanceof HTMLInputElement)
    || !(changePasswordConfirmInput instanceof HTMLInputElement)) {
    return;
  }

  const oldPassword = String(changePasswordOldInput.value || "");
  const newPassword = String(changePasswordNewInput.value || "");
  const confirmNewPassword = String(changePasswordConfirmInput.value || "");
  if (!oldPassword || !newPassword || !confirmNewPassword) {
    setStatus("All password fields are required.", true);
    return;
  }
  if (newPassword !== confirmNewPassword) {
    setStatus("New password and confirmation do not match.", true);
    return;
  }

  setChangePasswordSubmitting(true);
  try {
    await submitPasswordChange(oldPassword, newPassword, confirmNewPassword);
    closeChangePasswordModal();
    setStatus("Password updated.");
    showToast("Password updated.");
  } catch (error) {
    setStatus(normalizeErrorMessage(error, "Failed to change password."), true);
  } finally {
    setChangePasswordSubmitting(false);
  }
}

function applyTokenUsageFilters() {
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

async function handleShortTermAction(action, suggestionId) {
  const itemId = Number.parseInt(String(suggestionId), 10);
  if (!Number.isFinite(itemId)) {
    return;
  }

  const wrapper = shortTermMemoryListNode instanceof HTMLElement
    ? shortTermMemoryListNode.querySelector(`[data-short-term-id="${itemId}"]`)
    : null;
  const selectNode = wrapper instanceof HTMLElement
    ? wrapper.querySelector("select[data-short-term-type='1']")
    : null;
  const selectedType = selectNode instanceof HTMLSelectElement && selectNode.value === "core" ? "core" : "normal";

  try {
    await resolveShortTermMemory([{ id: itemId, action, memory_type: selectedType }]);
    state.shortTermMemories = state.shortTermMemories.filter((entry) => Number(entry.id) !== itemId);
    state.shortTermMemoryCount = Math.max(0, state.shortTermMemories.length);
    if (shortTermMemoryMetaNode instanceof HTMLElement) {
      shortTermMemoryMetaNode.textContent = state.shortTermMemoryExtracting
        ? `${state.shortTermMemoryCount} pending - identifying...`
        : `${state.shortTermMemoryCount} pending`;
    }
    renderShortTermMemory();
    if (action === "accept") {
      await refreshMemoriesFromServer();
      setStatus("Memory accepted.");
    } else {
      setStatus("Memory declined.");
    }
  } catch (error) {
    setStatus(normalizeErrorMessage(error, "Short term memory update failed."), true);
  }
}

function formatNowWithSeconds() {
  const now = getServerDate();
  const yyyy = now.getFullYear();
  const mm = String(now.getMonth() + 1).padStart(2, "0");
  const dd = String(now.getDate()).padStart(2, "0");
  const hh = String(now.getHours()).padStart(2, "0");
  const mi = String(now.getMinutes()).padStart(2, "0");
  const ss = String(now.getSeconds()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd} ${hh}:${mi}:${ss}`;
}


function updateTimedJobsNowLabel() {
  if (!(timedJobsNowNode instanceof HTMLElement)) {
    return;
  }
  const zone = state.serverTimezoneName ? ` (${state.serverTimezoneName})` : "";
  timedJobsNowNode.innerHTML = `<strong>Now:</strong> ${formatNowWithSeconds()}${zone}`;
}


function startTimedJobsClock() {
  updateTimedJobsNowLabel();
  if (state.timedJobsClockTimerId) {
    window.clearInterval(state.timedJobsClockTimerId);
  }
  state.timedJobsClockTimerId = window.setInterval(updateTimedJobsNowLabel, 1000);
}

function stopTimedJobsClock() {
  if (state.timedJobsClockTimerId) {
    window.clearInterval(state.timedJobsClockTimerId);
    state.timedJobsClockTimerId = null;
  }
}

function todayDateInputValue() {
  const now = getServerDate();
  const yyyy = now.getFullYear();
  const mm = String(now.getMonth() + 1).padStart(2, "0");
  const dd = String(now.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}


function normalizeIncomingTimedJobs(rawJobs) {
  if (!Array.isArray(rawJobs)) {
    return [];
  }
  return rawJobs
    .filter((entry) => entry && typeof entry === "object")
    .map((entry) => ({
      id: typeof entry.id === "string" ? entry.id : "",
      title: typeof entry.title === "string" ? entry.title : "",
      prompt: typeof entry.prompt === "string" ? entry.prompt : "",
      interval: typeof entry.interval === "string" ? entry.interval : "daily",
      start_date: typeof entry.start_date === "string" ? entry.start_date : todayDateInputValue(),
      time_of_day: typeof entry.time_of_day === "string" ? entry.time_of_day.slice(0, 5) : "09:00",
      enabled: Boolean(entry.enabled),
      output_decision_enabled: Boolean(entry.output_decision_enabled),
      channels: Array.isArray(entry.channels) ? entry.channels.map((channel) => String(channel)) : ["gateway"],
      provider_id: typeof entry.provider_id === "string" ? entry.provider_id : "",
      model: typeof entry.model === "string" ? entry.model : "",
      next_run_at: typeof entry.next_run_at === "string" ? entry.next_run_at : "",
      last_run_at: typeof entry.last_run_at === "string" ? entry.last_run_at : "",
      updated_at: typeof entry.updated_at === "string" ? entry.updated_at : "",
    }))
    .filter((entry) => Boolean(entry.id));
}

function normalizeTimedJobChannels(rawChannels) {
  if (!Array.isArray(rawChannels)) {
    return [];
  }
  return rawChannels
    .filter((entry) => entry && typeof entry === "object")
    .map((entry) => ({
      id: typeof entry.id === "string" ? entry.id : "",
      label: typeof entry.label === "string" ? entry.label : "",
      description: typeof entry.description === "string" ? entry.description : "",
      available: Boolean(entry.available),
      default: Boolean(entry.default),
    }))
    .filter((entry) => Boolean(entry.id));
}

function renderTimedJobProviderOptions(selectedProviderId = "") {
  if (!(timedJobProviderSelect instanceof HTMLSelectElement)) {
    return "";
  }

  const configuredProviderIds = getConfiguredProviderIds();
  timedJobProviderSelect.innerHTML = "";

  const useActiveOption = document.createElement("option");
  useActiveOption.value = "";
  useActiveOption.textContent = "Use active provider/model";
  timedJobProviderSelect.appendChild(useActiveOption);

  configuredProviderIds.forEach((providerId) => {
    const provider = getProviderById(providerId);
    const option = document.createElement("option");
    option.value = providerId;
    option.textContent = provider?.label ?? providerId;
    timedJobProviderSelect.appendChild(option);
  });

  const normalizedSelected = configuredProviderIds.includes(selectedProviderId) ? selectedProviderId : "";
  timedJobProviderSelect.value = normalizedSelected;
  return normalizedSelected;
}

function renderTimedJobModelOptions(providerId, selectedModel = "") {
  if (!(timedJobModelSelect instanceof HTMLSelectElement)) {
    return "";
  }

  timedJobModelSelect.innerHTML = "";
  const normalizedProviderId = String(providerId || "").trim();
  if (!normalizedProviderId) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "Use active provider model";
    timedJobModelSelect.appendChild(option);
    timedJobModelSelect.disabled = true;
    timedJobModelSelect.value = "";
    return "";
  }

  const provider = getProviderById(normalizedProviderId);
  const configuredModel = state.settings?.provider_configs?.[normalizedProviderId]?.model ?? "";
  const modelCandidates = provider?.models ?? [];
  const normalizedSelected = selectedModel || configuredModel || modelCandidates[0]?.id || "";

  modelCandidates.forEach((model) => {
    const option = document.createElement("option");
    option.value = model.id;
    option.textContent = model.label;
    timedJobModelSelect.appendChild(option);
  });

  if (normalizedSelected && !modelCandidates.some((model) => model.id === normalizedSelected)) {
    const customOption = document.createElement("option");
    customOption.value = normalizedSelected;
    customOption.textContent = normalizedSelected;
    timedJobModelSelect.appendChild(customOption);
  }

  timedJobModelSelect.disabled = false;
  if (normalizedSelected) {
    timedJobModelSelect.value = normalizedSelected;
  }
  return (timedJobModelSelect.value || normalizedSelected || "").trim();
}

function resetTimedJobEditor() {
  state.timedJobEditingId = "";
  if (timedJobTitleInput instanceof HTMLInputElement) {
    timedJobTitleInput.value = "";
  }
  if (timedJobPromptInput instanceof HTMLTextAreaElement) {
    timedJobPromptInput.value = "";
  }
  if (timedJobIntervalSelect instanceof HTMLSelectElement) {
    timedJobIntervalSelect.value = "daily";
  }
  if (timedJobStartDateInput instanceof HTMLInputElement) {
    timedJobStartDateInput.value = todayDateInputValue();
  }
  if (timedJobTimeInput instanceof HTMLInputElement) {
    const now = getServerDate();
    const hh = String(now.getHours()).padStart(2, "0");
    const mm = String(now.getMinutes()).padStart(2, "0");
    timedJobTimeInput.value = `${hh}:${mm}`;
  }

  if (timedJobEnabledInput instanceof HTMLInputElement) {
    timedJobEnabledInput.checked = true;
  }
  if (timedJobOutputDecisionEnabledInput instanceof HTMLInputElement) {
    timedJobOutputDecisionEnabledInput.checked = false;
  }
  renderTimedJobProviderOptions("");
  renderTimedJobModelOptions("", "");
  renderTimedJobChannelOptions(["gateway"]);
}

function renderTimedJobChannelOptions(selectedChannels = ["gateway"]) {
  if (!(timedJobChannelsNode instanceof HTMLElement)) {
    return;
  }
  timedJobChannelsNode.innerHTML = "";
  if (!Array.isArray(state.timedJobChannels) || state.timedJobChannels.length === 0) {
    const emptyNode = document.createElement("p");
    emptyNode.className = "memory-modal-empty";
    emptyNode.textContent = "No output channels available.";
    timedJobChannelsNode.appendChild(emptyNode);
    return;
  }

  const selectedSet = new Set(selectedChannels.map((entry) => String(entry)));
  state.timedJobChannels.forEach((channel) => {
    const wrapper = document.createElement("label");
    wrapper.className = "timed-job-check";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.dataset.timedJobChannelId = channel.id;
    input.disabled = !channel.available;
    input.checked = channel.available && (selectedSet.has(channel.id) || (selectedSet.size === 0 && channel.default));

    const text = document.createElement("span");
    const suffix = channel.available ? "" : " (unavailable)";
    text.textContent = `${channel.label || channel.id}${suffix}`;
    if (channel.description) {
      text.title = channel.description;
    }

    wrapper.appendChild(input);
    wrapper.appendChild(text);
    timedJobChannelsNode.appendChild(wrapper);
  });
}

function populateTimedJobEditor(job) {
  if (!job || typeof job !== "object") {
    resetTimedJobEditor();
    return;
  }
  state.timedJobEditingId = typeof job.id === "string" ? job.id : "";
  if (state.timedJobEditingId) {
    state.expandedTimedJobIds[state.timedJobEditingId] = true;
  }
  if (timedJobTitleInput instanceof HTMLInputElement) {
    timedJobTitleInput.value = typeof job.title === "string" ? job.title : "";
  }
  if (timedJobPromptInput instanceof HTMLTextAreaElement) {
    timedJobPromptInput.value = typeof job.prompt === "string" ? job.prompt : "";
  }
  if (timedJobIntervalSelect instanceof HTMLSelectElement) {
    timedJobIntervalSelect.value = typeof job.interval === "string" ? job.interval : "daily";
  }
  if (timedJobStartDateInput instanceof HTMLInputElement) {
    timedJobStartDateInput.value = typeof job.start_date === "string" && job.start_date ? job.start_date : todayDateInputValue();
  }
  if (timedJobTimeInput instanceof HTMLInputElement) {
    timedJobTimeInput.value = typeof job.time_of_day === "string" && job.time_of_day ? job.time_of_day.slice(0, 5) : "09:00";
  }
  if (timedJobEnabledInput instanceof HTMLInputElement) {
    timedJobEnabledInput.checked = Boolean(job.enabled);
  }
  if (timedJobOutputDecisionEnabledInput instanceof HTMLInputElement) {
    timedJobOutputDecisionEnabledInput.checked = Boolean(job.output_decision_enabled);
  }
  const selectedProviderId = renderTimedJobProviderOptions(typeof job.provider_id === "string" ? job.provider_id : "");
  renderTimedJobModelOptions(selectedProviderId, typeof job.model === "string" ? job.model : "");
  renderTimedJobChannelOptions(Array.isArray(job.channels) ? job.channels : ["gateway"]);
}

function formatTimedJobMeta(job) {
  const interval = typeof job.interval === "string" ? job.interval : "daily";
  const nextRun = typeof job.next_run_at === "string" && job.next_run_at
    ? formatMessageTimestamp(job.next_run_at)
    : "-";
  const channels = Array.isArray(job.channels) && job.channels.length > 0
    ? job.channels.join(", ")
    : "gateway";
  const status = job.enabled ? "enabled" : "disabled";
  const outputMode = job.output_decision_enabled ? "output: AI decision" : "output: always";
  const providerModel = job.provider_id
    ? `${job.provider_id}${job.model ? `/${job.model}` : ""}`
    : "active provider/model";
  return `${interval} | ${status} | next: ${nextRun} | channels: ${channels} | run: ${providerModel} | ${outputMode}`;
}

function isTimedJobExpanded(jobId) {
  return Boolean(state.expandedTimedJobIds[String(jobId || "")]);
}

function setTimedJobExpanded(jobId, expanded) {
  const normalizedJobId = String(jobId || "").trim();
  if (!normalizedJobId) {
    return;
  }
  if (expanded) {
    state.expandedTimedJobIds[normalizedJobId] = true;
    return;
  }
  delete state.expandedTimedJobIds[normalizedJobId];
}

function renderTimedJobsList() {
  if (!(timedJobsListNode instanceof HTMLElement)) {
    return;
  }
  timedJobsListNode.innerHTML = "";
  if (!Array.isArray(state.timedJobs) || state.timedJobs.length === 0) {
    const emptyNode = document.createElement("p");
    emptyNode.className = "memory-modal-empty";
    emptyNode.textContent = "No timed jobs yet.";
    timedJobsListNode.appendChild(emptyNode);
    return;
  }

  state.timedJobs.forEach((job) => {
    const isExpanded = isTimedJobExpanded(job.id);
    const card = document.createElement("article");
    card.className = "timed-job-item";
    card.dataset.timedJobId = job.id;
    card.classList.toggle("is-expanded", isExpanded);

    const titleRow = document.createElement("div");
    titleRow.className = "timed-job-item-row";

    const titleNode = document.createElement("button");
    titleNode.type = "button";
    titleNode.className = "timed-job-item-title";
    titleNode.textContent = job.title || "Untitled timed job";
    titleNode.dataset.timedJobAction = "toggle-expand";
    titleNode.dataset.timedJobId = job.id;
    titleNode.setAttribute("aria-expanded", isExpanded ? "true" : "false");

    const actions = document.createElement("div");
    actions.className = "short-term-item-actions";

    const triggerNowButton = document.createElement("button");
    triggerNowButton.type = "button";
    triggerNowButton.className = "timed-job-trigger-link";
    triggerNowButton.dataset.timedJobAction = "trigger-now";
    triggerNowButton.dataset.timedJobId = job.id;
    triggerNowButton.textContent = "trigger";

    const editButton = document.createElement("button");
    editButton.type = "button";
    editButton.className = "chat-history-action-btn";
    editButton.dataset.timedJobAction = "edit";
    editButton.dataset.timedJobId = job.id;
    editButton.setAttribute("aria-label", "Edit timed job");
    editButton.textContent = "✎";

    const deleteButton = document.createElement("button");
    deleteButton.type = "button";
    deleteButton.className = "chat-history-action-btn danger";
    deleteButton.dataset.timedJobAction = "delete";
    deleteButton.dataset.timedJobId = job.id;
    deleteButton.setAttribute("aria-label", "Delete timed job");
    deleteButton.textContent = "×";

    actions.appendChild(triggerNowButton);
    actions.appendChild(editButton);
    actions.appendChild(deleteButton);
    titleRow.appendChild(titleNode);
    titleRow.appendChild(actions);

    const metaNode = document.createElement("p");
    metaNode.className = "timed-job-item-meta";
    metaNode.textContent = formatTimedJobMeta(job);

    const promptNode = document.createElement("p");
    promptNode.className = "short-term-item-content";
    promptNode.textContent = job.prompt || "(No prompt)";

    const detailsNode = document.createElement("div");
    detailsNode.className = "timed-job-item-details";
    detailsNode.classList.toggle("hidden", !isExpanded);
    detailsNode.appendChild(promptNode);

    card.appendChild(titleRow);
    card.appendChild(metaNode);
    card.appendChild(detailsNode);
    timedJobsListNode.appendChild(card);
  });
}

async function fetchTimedJobs() {
  const response = await fetch("/api/timed-jobs", { cache: "no-store" });
  if (!response.ok) {
    throw new Error(await buildHttpErrorDetail(response, "Failed to load timed jobs."));
  }
  return response.json();
}

function collectTimedJobPayload() {
  const title = timedJobTitleInput instanceof HTMLInputElement ? timedJobTitleInput.value.trim() : "";
  const prompt = timedJobPromptInput instanceof HTMLTextAreaElement ? timedJobPromptInput.value.trim() : "";
  const interval = timedJobIntervalSelect instanceof HTMLSelectElement ? timedJobIntervalSelect.value : "daily";
  const startDate = timedJobStartDateInput instanceof HTMLInputElement ? timedJobStartDateInput.value : "";
  const timeOfDay = timedJobTimeInput instanceof HTMLInputElement ? timedJobTimeInput.value : "";
  const providerId = timedJobProviderSelect instanceof HTMLSelectElement ? timedJobProviderSelect.value.trim() : "";
  const model = timedJobModelSelect instanceof HTMLSelectElement ? timedJobModelSelect.value.trim() : "";
  const enabled = timedJobEnabledInput instanceof HTMLInputElement ? timedJobEnabledInput.checked : false;
  const outputDecisionEnabled =
    timedJobOutputDecisionEnabledInput instanceof HTMLInputElement ? timedJobOutputDecisionEnabledInput.checked : false;

  const channels = [];
  if (timedJobChannelsNode instanceof HTMLElement) {
    const checkboxes = timedJobChannelsNode.querySelectorAll("input[type='checkbox'][data-timed-job-channel-id]");
    checkboxes.forEach((checkbox) => {
      if (!(checkbox instanceof HTMLInputElement)) {
        return;
      }
      if (checkbox.checked && !checkbox.disabled && checkbox.dataset.timedJobChannelId) {
        channels.push(checkbox.dataset.timedJobChannelId);
      }
    });
  }

  return {
    title,
    prompt,
    interval,
    start_date: startDate,
    time_of_day: timeOfDay,
    enabled,
    output_decision_enabled: outputDecisionEnabled,
    channels,
    provider_id: providerId,
    model: providerId ? model : "",
  };
}

async function saveTimedJob() {
  const payload = collectTimedJobPayload();
  if (!payload.prompt) {
    setStatus("Timed job prompt is required.", true);
    return;
  }
  if (!payload.start_date) {
    setStatus("Timed job start date is required.", true);
    return;
  }
  if (!payload.time_of_day) {
    setStatus("Timed job time is required.", true);
    return;
  }
  if (!Array.isArray(payload.channels) || payload.channels.length === 0) {
    setStatus("Select at least one output channel.", true);
    return;
  }

  const method = state.timedJobEditingId ? "PUT" : "POST";
  const path = state.timedJobEditingId ? `/api/timed-jobs/${encodeURIComponent(state.timedJobEditingId)}` : "/api/timed-jobs";
  const response = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(await buildHttpErrorDetail(response, "Failed to save timed job."));
  }
}

async function deleteTimedJob(jobId) {
  const response = await fetch(`/api/timed-jobs/${encodeURIComponent(jobId)}`, { method: "DELETE" });
  if (!response.ok) {
    throw new Error(await buildHttpErrorDetail(response, "Failed to delete timed job."));
  }
}

async function triggerTimedJobNow(jobId) {
  const response = await fetch(`/api/timed-jobs/${encodeURIComponent(jobId)}/trigger`, { method: "POST" });
  if (!response.ok) {
    throw new Error(await buildHttpErrorDetail(response, "Failed to trigger timed job."));
  }
}

async function loadTimedJobs(renderModal = false) {
  try {
    const payload = await fetchTimedJobs();
    state.timedJobs = normalizeIncomingTimedJobs(payload.jobs);
    state.timedJobChannels = normalizeTimedJobChannels(payload.channels);
    if (renderModal) {
      renderTimedJobChannelOptions(Array.isArray(collectTimedJobPayload().channels) ? collectTimedJobPayload().channels : ["gateway"]);
      renderTimedJobsList();
      if (timedJobsMetaNode instanceof HTMLElement) {
        timedJobsMetaNode.textContent = `${state.timedJobs.length} jobs configured.`;
      }
    }
  } catch (error) {
    if (renderModal && timedJobsMetaNode instanceof HTMLElement) {
      timedJobsMetaNode.textContent = normalizeErrorMessage(error, "Failed to load timed jobs.");
    }
    if (renderModal) {
      throw error;
    }
  }
}

async function refreshTimedJobsAfterMcpUsage(toolUsage) {
  if (!Array.isArray(toolUsage) || toolUsage.length === 0) {
    return;
  }
  const usedTimedJobsMcp = toolUsage.some(
    (entry) => entry && typeof entry === "object" && String(entry.mcp_id || "") === "timed_jobs",
  );
  if (!usedTimedJobsMcp) {
    return;
  }
  const renderModal = timedJobsModal instanceof HTMLElement && !timedJobsModal.classList.contains("hidden");
  await loadTimedJobs(renderModal);
}

async function refreshScriptsAfterMcpUsage(toolUsage) {
  if (!Array.isArray(toolUsage) || toolUsage.length === 0) {
    return;
  }
  const usedScriptsMcp = toolUsage.some((entry) => {
    if (!entry || typeof entry !== "object") {
      return false;
    }
    if (String(entry.mcp_id || "") !== "scripts") {
      return false;
    }
    const toolId = String(entry.tool_id || "");
    return (
      toolId === "create_script"
      || toolId === "edit_script"
      || toolId === "check_script_requirements"
      || toolId === "install_script_requirements"
      || toolId === "execute_script"
      || toolId === "remove_script"
    );
  });
  if (!usedScriptsMcp) {
    return;
  }

  const response = await fetch("/api/mcps/scripts", { cache: "no-store" });
  if (!response.ok) {
    throw new Error(await buildHttpErrorDetail(response, "Failed to refresh scripts list."));
  }
  const payload = await response.json();
  state.scriptTitles = normalizeScriptTitles(payload?.titles);
  state.scripts = normalizeScriptsCatalog(payload?.scripts);
  renderMcpPanel();
}

async function openTimedJobsModal() {
  if (!(timedJobsModal instanceof HTMLElement)) {
    return;
  }
  resetTimedJobEditor();
  timedJobsModal.classList.remove("hidden");
  document.body.style.overflow = "hidden";
  startTimedJobsClock();
  await loadTimedJobs(true);
  if (timedJobsCloseButton instanceof HTMLButtonElement) {
    timedJobsCloseButton.focus({ preventScroll: true });
  }
}

function closeTimedJobsModal() {
  if (!(timedJobsModal instanceof HTMLElement)) {
    return;
  }
  timedJobsModal.classList.add("hidden");
  stopTimedJobsClock();
  if (
    (!(memoryModal instanceof HTMLElement) || memoryModal.classList.contains("hidden"))
    && (!(brainModal instanceof HTMLElement) || brainModal.classList.contains("hidden"))
    && (!(shortTermMemoryModal instanceof HTMLElement) || shortTermMemoryModal.classList.contains("hidden"))
    && (!(tokenUsageModal instanceof HTMLElement) || tokenUsageModal.classList.contains("hidden"))
    && (!(changePasswordModal instanceof HTMLElement) || changePasswordModal.classList.contains("hidden"))
    && (!state.mobileLeftDrawerOpen && !state.mobileRightDrawerOpen)
  ) {
    document.body.style.overflow = "";
  }
}

async function handleTimedJobsListAction(event) {
  const target = event.target;
  if (!(target instanceof HTMLElement)) {
    return;
  }
  const actionNode = target.closest("[data-timed-job-action][data-timed-job-id]");
  if (!(actionNode instanceof HTMLElement)) {
    return;
  }
  const action = actionNode.dataset.timedJobAction;
  const jobId = actionNode.dataset.timedJobId;
  if (!action || !jobId) {
    return;
  }

  const job = state.timedJobs.find((entry) => entry.id === jobId);
  if (!job) {
    return;
  }

  if (action === "edit") {
    populateTimedJobEditor(job);
    renderTimedJobsList();
    setStatus("Editing timed job.");
    return;
  }

  if (action === "toggle-expand") {
    setTimedJobExpanded(jobId, !isTimedJobExpanded(jobId));
    renderTimedJobsList();
    return;
  }

  if (action === "delete") {
    try {
      await deleteTimedJob(jobId);
      await loadTimedJobs(true);
      if (state.timedJobEditingId === jobId) {
        resetTimedJobEditor();
      }
      setStatus("Timed job deleted.");
    } catch (error) {
      setStatus(normalizeErrorMessage(error, "Timed job delete failed."), true);
    }
    return;
  }

  if (action === "trigger-now") {
    try {
      await triggerTimedJobNow(jobId);
      setStatus("Timed job triggered now.");
      window.setTimeout(() => {
        loadTimedJobs(true).catch(() => {});
      }, 600);
    } catch (error) {
      setStatus(normalizeErrorMessage(error, "Timed job trigger failed."), true);
    }
  }
}

async function addMemory(type) {
  const isCore = type === "core";
  const inputNode = isCore ? coreMemoryInput : normalMemoryInput;
  if (!(inputNode instanceof HTMLInputElement)) {
    return;
  }

  const text = inputNode.value.trim();
  if (!text) {
    setStatus(`Please enter a ${isCore ? "core" : "normal"} memory.`, true);
    return;
  }

  if (text.length > MEMORY_MAX_LENGTH) {
    setStatus(`Memory must be at most ${formatNumber(MEMORY_MAX_LENGTH)} characters.`, true);
    return;
  }

  const targetList = isCore ? state.coreMemories : state.normalMemories;
  targetList.push({ content: text, created_at: createTimestamp() });
  inputNode.value = "";
  renderMemoryManagement();

  try {
    await persistMemoriesToSettings();
    state.coreMemoryEditingIndex = -1;
    state.normalMemoryEditingIndex = -1;
    renderMemoryManagement();
    setStatus(`${isCore ? "Core" : "Normal"} memory added.`);
  } catch (error) {
    targetList.pop();
    renderMemoryManagement();
    setStatus(`Memory add failed: ${error.message}`, true);
  }
}

async function deleteMemory(type, indexValue) {
  const parsedIndex = Number.parseInt(String(indexValue), 10);
  if (!Number.isFinite(parsedIndex) || parsedIndex < 0) {
    return;
  }

  const targetList = type === "core" ? state.coreMemories : state.normalMemories;
  if (parsedIndex >= targetList.length) {
    return;
  }

  const [removed] = targetList.splice(parsedIndex, 1);
  renderMemoryManagement();

  try {
    await persistMemoriesToSettings();
    state.coreMemoryEditingIndex = -1;
    state.normalMemoryEditingIndex = -1;
    renderMemoryManagement();
    setStatus(`${type === "core" ? "Core" : "Normal"} memory deleted.`);
  } catch (error) {
    if (removed) {
      targetList.splice(parsedIndex, 0, removed);
    }
    renderMemoryManagement();
    setStatus(`Memory delete failed: ${error.message}`, true);
  }
}

function startMemoryInlineEdit(type, indexValue) {
  const parsedIndex = Number.parseInt(String(indexValue), 10);
  if (!Number.isFinite(parsedIndex) || parsedIndex < 0) {
    return;
  }

  const targetList = type === "core" ? state.coreMemories : state.normalMemories;
  if (parsedIndex >= targetList.length) {
    return;
  }

  const content = targetList[parsedIndex]?.content ?? "";
  if (type === "core") {
    state.coreMemoryEditingIndex = parsedIndex;
    state.coreMemoryEditDraft = content;
    state.normalMemoryEditingIndex = -1;
    state.normalMemoryEditDraft = "";
  } else {
    state.normalMemoryEditingIndex = parsedIndex;
    state.normalMemoryEditDraft = content;
    state.coreMemoryEditingIndex = -1;
    state.coreMemoryEditDraft = "";
  }

  renderMemoryManagement();
}

function updateMemoryEditDraft(type, nextValue) {
  const normalized = String(nextValue || "").slice(0, MEMORY_MAX_LENGTH);
  if (type === "core") {
    state.coreMemoryEditDraft = normalized;
  } else {
    state.normalMemoryEditDraft = normalized;
  }
}

function cancelMemoryInlineEdit(type) {
  if (type === "core") {
    state.coreMemoryEditingIndex = -1;
    state.coreMemoryEditDraft = "";
  } else {
    state.normalMemoryEditingIndex = -1;
    state.normalMemoryEditDraft = "";
  }
  renderMemoryManagement();
}

async function saveMemoryInlineEdit(type, indexValue) {
  const parsedIndex = Number.parseInt(String(indexValue), 10);
  if (!Number.isFinite(parsedIndex) || parsedIndex < 0) {
    return;
  }

  const targetList = type === "core" ? state.coreMemories : state.normalMemories;
  if (parsedIndex >= targetList.length) {
    return;
  }

  const draft = type === "core" ? state.coreMemoryEditDraft : state.normalMemoryEditDraft;
  const updatedText = String(draft || "").trim();
  if (!updatedText) {
    setStatus("Memory cannot be empty.", true);
    return;
  }

  const previousText = targetList[parsedIndex].content;
  targetList[parsedIndex].content = updatedText;
  renderMemoryManagement();

  try {
    await persistMemoriesToSettings();
    cancelMemoryInlineEdit(type);
    setStatus(`${type === "core" ? "Core" : "Normal"} memory updated.`);
  } catch (error) {
    targetList[parsedIndex].content = previousText;
    renderMemoryManagement();
    setStatus(`Memory update failed: ${error.message}`, true);
  }
}

function normalizeIncomingMcpConfigs(rawConfigs) {
  if (!rawConfigs || typeof rawConfigs !== "object") {
    return {};
  }

  const normalized = {};
  Object.entries(rawConfigs).forEach(([mcpId, rawValue]) => {
    if (!rawValue || typeof rawValue !== "object") {
      return;
    }

    const params = rawValue.params && typeof rawValue.params === "object" ? rawValue.params : {};
    const normalizedParams = {};
    Object.entries(params).forEach(([key, value]) => {
      if (typeof key !== "string") {
        return;
      }
      normalizedParams[key] = typeof value === "string" ? value : String(value ?? "");
    });

    normalized[mcpId] = {
      enabled: Boolean(rawValue.enabled),
      params: normalizedParams,
    };
  });

  return normalized;
}

function getMcpDefaultEnabled(mcpId) {
  const mcp = Array.isArray(state.mcps) ? state.mcps.find((entry) => entry?.id === mcpId) : null;
  return Boolean(mcp?.default_enabled);
}

function getMcpConfig(mcpId) {
  const config = state.mcpConfigs[mcpId];
  if (config && typeof config === "object") {
    return config;
  }

  return { enabled: getMcpDefaultEnabled(mcpId), params: {} };
}

async function persistMcpConfigsToSettings() {
  if (!state.settings) {
    return;
  }

  const nextSettings = JSON.parse(JSON.stringify(state.settings));
  nextSettings.mcp_configs = state.mcpConfigs;
  nextSettings.integration_configs = state.integrationConfigs;
  nextSettings.chats = state.chats;
  nextSettings.active_chat_id = state.activeChatId;
  nextSettings.daily_token_usage = state.dailyTokenUsage;
  const persisted = await persistSettings(nextSettings);
  state.settings = persisted;
  if (typeof persisted.active_chat_id === "string") {
    state.activeChatId = persisted.active_chat_id;
  }
  state.mcpConfigs = normalizeIncomingMcpConfigs(persisted.mcp_configs);
  state.integrationConfigs = normalizeIncomingMcpConfigs(persisted.integration_configs);
  syncTelegramFlagsFromIntegrationConfig();
  state.dailyTokenUsage = normalizeDailyTokenUsage(persisted.daily_token_usage);
  refreshLocalChatStateSignature();
  updateDailyTokenUsageLabel();
  updateTelegramStatusLabel();
}

async function verifyMcpConfig(mcpId) {
  const config = getMcpConfig(mcpId);
  const response = await fetch("/api/mcps/verify", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      mcp_id: mcpId,
      params: config.params,
    }),
  });

  if (!response.ok) {
    let detail = "Tool verification failed.";
    try {
      const payload = await response.json();
      if (typeof payload.detail === "string" && payload.detail) {
        detail = payload.detail;
      }
    } catch (error) {
      detail = "Tool verification failed.";
    }

    throw new Error(detail);
  }

  const payload = await response.json();
  return payload;
}

async function verifyIntegrationConfig(integrationId) {
  const config = getIntegrationConfig(integrationId);
  const response = await fetch("/api/integrations/verify", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      integration_id: integrationId,
      params: config.params,
    }),
  });

  if (!response.ok) {
    let detail = "Integration verification failed.";
    try {
      const payload = await response.json();
      if (typeof payload.detail === "string" && payload.detail) {
        detail = payload.detail;
      }
    } catch (error) {
      detail = "Integration verification failed.";
    }
    throw new Error(detail);
  }

  const payload = await response.json();
  if (integrationId === "telegram") {
    await syncIntegrationStatus();
  }
  return payload;
}

async function fetchGitSshKey() {
  const response = await fetch("/api/mcps/git/ssh-key");
  if (!response.ok) {
    let detail = "Failed to load SSH key.";
    try {
      const payload = await response.json();
      if (typeof payload.detail === "string" && payload.detail) {
        detail = payload.detail;
      }
    } catch (error) {
      detail = "Failed to load SSH key.";
    }
    throw new Error(detail);
  }

  const payload = await response.json();
  const publicKey = typeof payload.public_key === "string" ? payload.public_key : "";
  if (!publicKey) {
    throw new Error("SSH key response was empty.");
  }

  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(publicKey);
    return;
  }

  throw new Error("Clipboard API unavailable. Use a modern browser context.");
}

async function verifyGitSshAccess() {
  const response = await fetch("/api/mcps/git/verify-ssh", { method: "POST" });
  if (!response.ok) {
    let detail = "GitHub SSH verification failed.";
    try {
      const payload = await response.json();
      if (typeof payload.detail === "string" && payload.detail) {
        detail = payload.detail;
      }
    } catch (error) {
      detail = "GitHub SSH verification failed.";
    }
    throw new Error(detail);
  }

  const payload = await response.json();
  return payload;
}

async function fetchGoogleOauthStatus() {
  const response = await fetch("/api/mcps/google/oauth/status", { cache: "no-store" });
  if (!response.ok) {
    throw new Error("Failed to load Google OAuth status.");
  }
  const payload = await response.json();
  state.googleOauthStatus = payload && typeof payload === "object" ? payload : null;
  return state.googleOauthStatus;
}

function normalizeWhatsappContacts(rawContacts) {
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

function getWhatsappContactsCacheFromConfig() {
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

function persistWhatsappContactsCacheInConfig(contacts) {
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

function hydrateWhatsappContactsFromCache() {
  const cached = getWhatsappContactsCacheFromConfig();
  state.whatsappContacts = cached;
  return cached;
}

async function fetchWhatsappContactsLive(options = {}) {
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
      const cacheChanged = persistWhatsappContactsCacheInConfig(contacts);
      if (cacheChanged) {
        scheduleMcpAutosave("whatsapp");
      }
    }
    return { ok: true, contacts };
  } catch (_error) {
    return { ok: false, contacts: [] };
  }
}

async function fetchWhatsappContacts() {
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

async function fetchWhatsappRuntimeState() {
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

async function syncWhatsappContactsWithRetry(maxAttempts = 8) {
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

async function startGoogleOauthLogin() {
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
  renderMcpPanel();
}

async function runMcpAutosave(mcpId) {
  if (!mcpId) {
    return;
  }

  if (state.mcpAutosaveInFlight) {
    state.mcpAutosaveQueuedId = mcpId;
    return;
  }

  state.mcpAutosaveInFlight = true;
  try {
    await persistMcpConfigsToSettings();
    const label = getMcpDisplayLabel(mcpId);
    const message = `MCP: ${label} saved.`;
    setStatus(message);
    showToast(message);
  } catch (error) {
    setStatus(`MCP save failed: ${error.message}`, true);
  } finally {
    state.mcpAutosaveInFlight = false;
    if (state.mcpAutosaveQueuedId) {
      const queuedId = state.mcpAutosaveQueuedId;
      state.mcpAutosaveQueuedId = "";
      scheduleMcpAutosave(queuedId);
    }
  }
}

function scheduleMcpAutosave(mcpId) {
  const normalizedId = typeof mcpId === "string" ? mcpId.trim() : "";
  if (!normalizedId) {
    return;
  }

  state.mcpAutosavePendingId = normalizedId;
  if (state.mcpAutosaveTimerId) {
    window.clearTimeout(state.mcpAutosaveTimerId);
  }

  state.mcpAutosaveTimerId = window.setTimeout(async () => {
    state.mcpAutosaveTimerId = null;
    const pendingId = state.mcpAutosavePendingId;
    state.mcpAutosavePendingId = "";
    await runMcpAutosave(pendingId);
  }, 300);
}

function getGoogleOauthStatusLabel() {
  if (!state.googleOauthStatus || typeof state.googleOauthStatus !== "object") {
    return "Google: not connected";
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

function getGoogleSetupGuideItems() {
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

function getConfigExpandKey(kind, configId) {
  return `${kind}:${configId}`;
}

function parseMultiselectParam(rawValue) {
  if (typeof rawValue !== "string") {
    return [];
  }
  const trimmed = rawValue.trim();
  if (!trimmed) {
    return [];
  }

  try {
    const parsed = JSON.parse(trimmed);
    if (Array.isArray(parsed)) {
      return parsed.map((item) => String(item || "").trim()).filter((item) => item.length > 0);
    }
  } catch (error) {
    // Fallback to comma-separated legacy values.
  }

  return trimmed.split(",").map((item) => item.trim()).filter((item) => item.length > 0);
}

function encodeMultiselectParam(values) {
  if (!Array.isArray(values)) {
    return "[]";
  }
  const normalized = [];
  values.forEach((value) => {
    const item = String(value || "").trim();
    if (!item || normalized.includes(item)) {
      return;
    }
    normalized.push(item);
  });
  return JSON.stringify(normalized);
}

function parseBooleanConfigParam(rawValue) {
  const normalized = String(rawValue || "").trim().toLowerCase();
  return normalized === "1" || normalized === "true" || normalized === "yes" || normalized === "on";
}

function readMultiselectSelection(fieldsetNode) {
  if (!(fieldsetNode instanceof HTMLElement)) {
    return [];
  }
  const selected = [];
  const boxes = fieldsetNode.querySelectorAll("input[type='checkbox'][data-multiselect-value]");
  boxes.forEach((boxNode) => {
    if (!(boxNode instanceof HTMLInputElement)) {
      return;
    }
    if (!boxNode.checked) {
      return;
    }
    const optionValue = String(boxNode.dataset.multiselectValue || "").trim();
    if (!optionValue || selected.includes(optionValue)) {
      return;
    }
    selected.push(optionValue);
  });
  return selected;
}

function isConfigExpanded(kind, configId) {
  const key = getConfigExpandKey(kind, configId);
  return Boolean(state.expandedConfigs[key]);
}

function toggleConfigExpanded(kind, configId) {
  const key = getConfigExpandKey(kind, configId);
  state.expandedConfigs[key] = !Boolean(state.expandedConfigs[key]);
}

function renderConfigPanel(container, items, getConfig, options) {
  if (!(container instanceof HTMLElement)) {
    return;
  }

  container.innerHTML = "";
  if (!Array.isArray(items) || items.length === 0) {
    const emptyNode = document.createElement("p");
    emptyNode.className = "chat-history-empty";
    emptyNode.textContent = options.emptyLabel;
    container.appendChild(emptyNode);
    return;
  }

  items.forEach((item) => {
    const card = document.createElement("div");
    card.className = "mcp-card";
    card.dataset.configKind = options.kind;
    card.dataset.configId = item.id;

    const config = getConfig(item.id);

    const titleRow = document.createElement("div");
    titleRow.className = "mcp-title-row";

    const titleMain = document.createElement("div");
    titleMain.className = "mcp-title-main";
    titleMain.dataset.action = "expand";
    titleMain.dataset.configKind = options.kind;
    titleMain.dataset.configId = item.id;

    const title = document.createElement("p");
    title.className = "mcp-title";
    title.textContent = options.kind === "mcp"
      ? getFrontendMcpLabel(item.id, item.label)
      : item.label;

    titleMain.appendChild(title);

    const titleControls = document.createElement("div");
    titleControls.className = "mcp-title-controls";

    const toggleLabel = document.createElement("label");
    toggleLabel.className = "mcp-toggle";

    const toggleInput = document.createElement("input");
    toggleInput.type = "checkbox";
    toggleInput.checked = Boolean(config.enabled);
    toggleInput.dataset.action = "toggle";
    toggleInput.dataset.configKind = options.kind;
    toggleInput.dataset.configId = item.id;

    const toggleText = document.createElement("span");
    toggleText.textContent = "Enabled";

    toggleLabel.appendChild(toggleInput);
    toggleLabel.appendChild(toggleText);

    const expanded = isConfigExpanded(options.kind, item.id);
    const expandButton = document.createElement("button");
    expandButton.type = "button";
    expandButton.className = "mcp-expand-btn";
    expandButton.textContent = expanded ? "▴" : "▾";
    expandButton.setAttribute("aria-label", expanded ? "Collapse" : "Expand");
    expandButton.title = expanded ? "Collapse" : "Expand";
    expandButton.dataset.action = "expand";
    expandButton.dataset.configKind = options.kind;
    expandButton.dataset.configId = item.id;

    titleControls.appendChild(toggleLabel);
    titleControls.appendChild(expandButton);

    titleRow.appendChild(titleMain);
    titleRow.appendChild(titleControls);

    const cardBody = document.createElement("div");
    cardBody.className = "mcp-card-body";
    cardBody.classList.toggle("hidden", !expanded);

    const description = document.createElement("p");
    description.className = "mcp-description";
    description.textContent = typeof item.description === "string" ? item.description : "";

    card.appendChild(titleRow);
    cardBody.appendChild(description);

    const fields = Array.isArray(item.config_fields) ? item.config_fields : [];
    fields.forEach((field) => {
      const fieldId = typeof field.id === "string" ? field.id : "";
      if (!fieldId) {
        return;
      }

      let activeField = field;
      if (options.kind === "mcp" && item.id === "whatsapp" && (fieldId === "allowed_numbers_send" || fieldId === "allowed_numbers_receive")) {
        const contactOptions = Array.isArray(state.whatsappContacts)
          ? state.whatsappContacts.map((entry) => ({
            value: String(entry.number || ""),
            label: `${String(entry.name || "").trim() || String(entry.number || "")} (${String(entry.number || "")})`,
          })).filter((entry) => entry.value)
          : [];
        activeField = {
          ...field,
          type: "multiselect",
          options: contactOptions,
          description: contactOptions.length > 0
            ? "Select allowlisted WhatsApp contacts."
            : "No contacts loaded yet. Connect WhatsApp, then click Resync or Verify.",
        };
      }

      const fieldWrapper = document.createElement("div");
      fieldWrapper.className = "mcp-field";

      const fieldLabel = document.createElement("label");
      fieldLabel.textContent = activeField.label || fieldId;
      fieldLabel.setAttribute("for", `${options.kind}-${item.id}-${fieldId}`);

      let fieldInput;
      if (activeField.type === "select") {
        const selectNode = document.createElement("select");
        const optionsList = Array.isArray(activeField.options) ? activeField.options : [];
        optionsList.forEach((optionItem) => {
          const optionValue = typeof optionItem?.value === "string" ? optionItem.value : "";
          if (!optionValue) {
            return;
          }
          const optionLabel = typeof optionItem?.label === "string" && optionItem.label
            ? optionItem.label
            : optionValue;
          const optionNode = document.createElement("option");
          optionNode.value = optionValue;
          optionNode.textContent = optionLabel;
          selectNode.appendChild(optionNode);
        });
        const storedValue = typeof config.params?.[fieldId] === "string" ? config.params[fieldId] : "";
        if (storedValue && Array.from(selectNode.options).some((optionNode) => optionNode.value === storedValue)) {
          selectNode.value = storedValue;
        } else if (selectNode.options.length > 0) {
          selectNode.value = selectNode.options[0].value;
          config.params[fieldId] = selectNode.value;
        }
        fieldInput = selectNode;
      } else if (activeField.type === "multiselect") {
        const fieldsetNode = document.createElement("div");
        fieldsetNode.className = "mcp-multiselect";
        fieldsetNode.dataset.action = "param-multiselect";
        fieldsetNode.dataset.configKind = options.kind;
        fieldsetNode.dataset.configId = item.id;
        fieldsetNode.dataset.fieldId = fieldId;

        const optionsList = Array.isArray(activeField.options) ? activeField.options : [];
        const storedValues = parseMultiselectParam(config.params?.[fieldId]);
        const selectedSet = new Set(storedValues);
        const isWhatsappAllowedNumbers = options.kind === "mcp" && item.id === "whatsapp" && (fieldId === "allowed_numbers_send" || fieldId === "allowed_numbers_receive");
        let contactListNode = fieldsetNode;
        const existingOptionValues = new Set(
          optionsList
            .map((optionItem) => (typeof optionItem?.value === "string" ? optionItem.value : ""))
            .filter((value) => value),
        );
        const renderOptions = [...optionsList];
        if (isWhatsappAllowedNumbers) {
          storedValues.forEach((value) => {
            if (!value || existingOptionValues.has(value)) {
              return;
            }
            existingOptionValues.add(value);
            renderOptions.push({ value, label: `${value} (saved)` });
          });
        }

        if (isWhatsappAllowedNumbers) {
          const filterInput = document.createElement("input");
          filterInput.type = "search";
          filterInput.className = "mcp-contact-filter";
          filterInput.placeholder = "Filter contacts";
          filterInput.autocomplete = "off";
          filterInput.spellcheck = false;

          const selectedOnlyToggleLabel = document.createElement("label");
          selectedOnlyToggleLabel.className = "mcp-toggle";

          const selectedOnlyToggleInput = document.createElement("input");
          selectedOnlyToggleInput.type = "checkbox";
          selectedOnlyToggleInput.checked = Boolean(state[`whatsappAllowlistOnlySelected_${fieldId}`]);

          const selectedOnlyToggleText = document.createElement("span");
          selectedOnlyToggleText.textContent = "Only show allow list contacts";

          const selectedOnlyCount = document.createElement("span");
          selectedOnlyCount.textContent = "(0)";

          contactListNode = document.createElement("div");
          contactListNode.className = "mcp-multiselect-list";

          const updateSelectedOnlyCount = () => {
            const selectedCount = contactListNode.querySelectorAll("input[type='checkbox'][data-multiselect-value]:checked").length;
            selectedOnlyCount.textContent = `(${selectedCount})`;
          };

          const applyContactFilter = () => {
            const query = filterInput.value.trim().toLowerCase();
            const onlySelected = selectedOnlyToggleInput.checked;
            const rows = contactListNode.querySelectorAll(".mcp-multiselect-option");
            rows.forEach((rowNode) => {
              if (!(rowNode instanceof HTMLElement)) {
                return;
              }
              const haystack = String(rowNode.dataset.searchText || "").toLowerCase();
              const matchesQuery = !query || haystack.includes(query);
              if (!matchesQuery) {
                rowNode.classList.add("hidden");
                return;
              }

              if (onlySelected) {
                const rowInput = rowNode.querySelector("input[type='checkbox'][data-multiselect-value]");
                const isSelected = rowInput instanceof HTMLInputElement && rowInput.checked;
                rowNode.classList.toggle("hidden", !isSelected);
                return;
              }

              rowNode.classList.remove("hidden");
            });
            updateSelectedOnlyCount();
          };

          filterInput.addEventListener("input", applyContactFilter);
          selectedOnlyToggleInput.addEventListener("change", () => {
            state[`whatsappAllowlistOnlySelected_${fieldId}`] = selectedOnlyToggleInput.checked;
            applyContactFilter();
          });

          selectedOnlyToggleLabel.appendChild(selectedOnlyToggleInput);
          selectedOnlyToggleLabel.appendChild(selectedOnlyToggleText);
          selectedOnlyToggleLabel.appendChild(selectedOnlyCount);

          fieldsetNode.appendChild(filterInput);
          fieldsetNode.appendChild(selectedOnlyToggleLabel);
          fieldsetNode.appendChild(contactListNode);

          fieldsetNode.dataset.whatsappFilterHooked = "true";
          fieldsetNode._applyContactFilter = applyContactFilter;
        }

        renderOptions.forEach((optionItem) => {
          const optionValue = typeof optionItem?.value === "string" ? optionItem.value : "";
          if (!optionValue) {
            return;
          }

          const optionLabel = typeof optionItem?.label === "string" && optionItem.label
            ? optionItem.label
            : optionValue;
          const optionDisabled = Boolean(optionItem?.disabled);

          const optionRow = document.createElement("label");
          optionRow.className = "mcp-toggle";
          if (isWhatsappAllowedNumbers) {
            optionRow.classList.add("mcp-multiselect-option");
            optionRow.dataset.searchText = `${optionLabel} ${optionValue}`.trim();
          }

          const optionInput = document.createElement("input");
          optionInput.type = "checkbox";
          optionInput.checked = selectedSet.has(optionValue) || optionDisabled;
          optionInput.disabled = optionDisabled;
          optionInput.dataset.action = "param-multiselect";
          optionInput.dataset.configKind = options.kind;
          optionInput.dataset.configId = item.id;
          optionInput.dataset.fieldId = fieldId;
          optionInput.dataset.multiselectValue = optionValue;

          if (isWhatsappAllowedNumbers && typeof fieldsetNode._applyContactFilter === "function") {
            optionInput.addEventListener("change", () => {
              fieldsetNode._applyContactFilter();
            });
          }

          const optionText = document.createElement("span");
          optionText.textContent = optionLabel;

          optionRow.appendChild(optionInput);
          optionRow.appendChild(optionText);
          contactListNode.appendChild(optionRow);
        });

        if (isWhatsappAllowedNumbers && typeof fieldsetNode._applyContactFilter === "function") {
          fieldsetNode._applyContactFilter();
        }

        fieldInput = fieldsetNode;
      } else if (activeField.type === "checkbox") {
        const checkboxNode = document.createElement("input");
        checkboxNode.type = "checkbox";
        checkboxNode.checked = parseBooleanConfigParam(config.params?.[fieldId]);
        fieldInput = checkboxNode;
      } else if (activeField.type === "textarea") {
        const textNode = document.createElement("textarea");
        textNode.rows = 4;
        textNode.value = typeof config.params?.[fieldId] === "string" ? config.params[fieldId] : "";
        textNode.placeholder = typeof activeField.placeholder === "string" ? activeField.placeholder : "";
        fieldInput = textNode;
       } else {
         const inputNode = document.createElement("input");
         inputNode.type = activeField.type === "password" ? "password" : "text";
         // Suppress password managers and browser autofill for ALL config inputs
         // (not just password types) to prevent unwanted credential-save prompts
         inputNode.autocomplete = activeField.type === "password" ? "new-password" : "off";
         inputNode.name = `krill-ignore-${options.kind}-${item.id}-${fieldId}`;
         inputNode.setAttribute("autocapitalize", "off");
         inputNode.setAttribute("autocorrect", "off");
         inputNode.spellcheck = false;
         inputNode.setAttribute("data-lpignore", "true");
         inputNode.setAttribute("data-1p-ignore", "true");
         inputNode.setAttribute("data-form-type", "other");
         inputNode.value = typeof config.params?.[fieldId] === "string" ? config.params[fieldId] : "";
         inputNode.placeholder = typeof activeField.placeholder === "string" ? activeField.placeholder : "";
         fieldInput = inputNode;
       }

      fieldInput.id = `${options.kind}-${item.id}-${fieldId}`;
      fieldInput.dataset.action = "param";
      fieldInput.dataset.configKind = options.kind;
      fieldInput.dataset.configId = item.id;
      fieldInput.dataset.fieldId = fieldId;

      fieldWrapper.appendChild(fieldLabel);
      fieldWrapper.appendChild(fieldInput);
      if (typeof activeField.description === "string" && activeField.description.trim()) {
        const helpText = document.createElement("small");
        helpText.className = "mcp-description";
        helpText.textContent = activeField.description.trim();
        fieldWrapper.appendChild(helpText);
      }
      cardBody.appendChild(fieldWrapper);
    });

    const actions = document.createElement("div");
    actions.className = "mcp-card-actions";

    if (options.kind === "mcp" && item.id === "git_ops") {
      const sshKeyButton = document.createElement("button");
      sshKeyButton.type = "button";
      sshKeyButton.className = "mcp-link-btn";
      sshKeyButton.textContent = "SSH key";
      sshKeyButton.dataset.action = "ssh-key";
      sshKeyButton.dataset.configKind = options.kind;
      sshKeyButton.dataset.configId = item.id;

      const verifyButton = document.createElement("button");
      verifyButton.type = "button";
      verifyButton.className = "mcp-link-btn";
      verifyButton.textContent = "Verify";
      verifyButton.dataset.action = "verify-ssh";
      verifyButton.dataset.configKind = options.kind;
      verifyButton.dataset.configId = item.id;

      actions.appendChild(sshKeyButton);
      actions.appendChild(verifyButton);
      cardBody.appendChild(actions);
    } else if (options.kind === "mcp" && item.id === "google_services") {
      const guideNode = document.createElement("div");
      guideNode.className = "mcp-guide";

      const guideHeader = document.createElement("div");
      guideHeader.className = "mcp-guide-header";
      guideHeader.dataset.action = "google-guide-toggle";
      guideHeader.dataset.configKind = options.kind;
      guideHeader.dataset.configId = item.id;

      const guideTitle = document.createElement("p");
      guideTitle.className = "mcp-guide-title";
      guideTitle.textContent = "Google setup";

      const guideToggle = document.createElement("button");
      guideToggle.type = "button";
      guideToggle.className = "mcp-expand-btn";
      guideToggle.textContent = state.googleGuideExpanded ? "▴" : "▾";
      guideToggle.setAttribute("aria-label", state.googleGuideExpanded ? "Collapse Google setup" : "Expand Google setup");
      guideToggle.title = state.googleGuideExpanded ? "Collapse" : "Expand";
      guideToggle.dataset.action = "google-guide-toggle";
      guideToggle.dataset.configKind = options.kind;
      guideToggle.dataset.configId = item.id;

      guideHeader.appendChild(guideTitle);
      guideHeader.appendChild(guideToggle);
      guideNode.appendChild(guideHeader);

      const consoleLink = document.createElement("a");
      consoleLink.className = "mcp-guide-link";
      consoleLink.href = "https://console.cloud.google.com/apis/credentials";
      consoleLink.target = "_blank";
      consoleLink.rel = "noopener noreferrer";
      consoleLink.textContent = "Open Google Cloud Console";

      const apiLibraryLink = document.createElement("a");
      apiLibraryLink.className = "mcp-guide-link";
      apiLibraryLink.href = "https://console.cloud.google.com/apis/library";
      apiLibraryLink.target = "_blank";
      apiLibraryLink.rel = "noopener noreferrer";
      apiLibraryLink.textContent = "Open API Library (enable Gmail + Calendar + Drive APIs)";

      const guideBody = document.createElement("div");
      guideBody.className = "mcp-guide-body";
      guideBody.classList.toggle("hidden", !state.googleGuideExpanded);

      const guideList = document.createElement("ol");
      guideList.className = "mcp-guide-list";
      getGoogleSetupGuideItems().forEach((itemText) => {
        const li = document.createElement("li");
        li.textContent = itemText;
        guideList.appendChild(li);
      });

      guideBody.appendChild(consoleLink);
      guideBody.appendChild(apiLibraryLink);
      guideBody.appendChild(guideList);
      guideNode.appendChild(guideBody);
      cardBody.appendChild(guideNode);

      const statusNode = document.createElement("p");
      statusNode.className = "mcp-description";
      statusNode.textContent = getGoogleOauthStatusLabel();
      cardBody.appendChild(statusNode);

      if (config.params.access_mode !== "read_write" && config.params.access_mode !== "read_only") {
        config.params.access_mode = "read_only";
      }

      const writeAccessLabel = document.createElement("label");
      writeAccessLabel.className = "mcp-toggle";

      const writeAccessInput = document.createElement("input");
      writeAccessInput.type = "checkbox";
      writeAccessInput.checked = config.params.access_mode === "read_write";
      writeAccessInput.dataset.action = "google-write-access";
      writeAccessInput.dataset.configKind = options.kind;
      writeAccessInput.dataset.configId = item.id;

      const writeAccessText = document.createElement("span");
      writeAccessText.textContent = "write access (Mail, Calendar & Drive)";

      writeAccessLabel.appendChild(writeAccessInput);
      writeAccessLabel.appendChild(writeAccessText);
      cardBody.appendChild(writeAccessLabel);

      const loginButton = document.createElement("button");
      loginButton.type = "button";
      loginButton.className = "mcp-link-btn";
      loginButton.textContent = Boolean(state.googleOauthStatus?.connected) ? "Relogin" : "Login Google";
      loginButton.dataset.action = "google-login";
      loginButton.dataset.configKind = options.kind;
      loginButton.dataset.configId = item.id;

      const verifyButton = document.createElement("button");
      verifyButton.type = "button";
      verifyButton.className = "mcp-link-btn";
      verifyButton.textContent = "Verify";
      verifyButton.dataset.action = "verify";
      verifyButton.dataset.configKind = options.kind;
      verifyButton.dataset.configId = item.id;

      actions.appendChild(loginButton);
      actions.appendChild(verifyButton);
      cardBody.appendChild(actions);
    } else if (options.kind === "mcp" && item.id === "scripts") {
      const scriptsBox = document.createElement("div");
      scriptsBox.className = "mcp-guide";

      const scriptsTitle = document.createElement("p");
      scriptsTitle.className = "mcp-guide-title";
      scriptsTitle.textContent = `Loaded scripts (${state.scripts.length})`;
      scriptsBox.appendChild(scriptsTitle);

      if (state.scripts.length === 0) {
        const emptyNode = document.createElement("p");
        emptyNode.className = "mcp-description";
        emptyNode.textContent = "No scripts loaded yet.";
        scriptsBox.appendChild(emptyNode);
      } else {
        const scriptsList = document.createElement("ul");
        scriptsList.className = "mcp-scripts-list";
        state.scripts.forEach((scriptItem) => {
          const scriptNode = document.createElement("li");
          scriptNode.className = "mcp-script-item";

          const enabledToggleLabel = document.createElement("label");
          enabledToggleLabel.className = "mcp-toggle";

          const enabledToggleInput = document.createElement("input");
          enabledToggleInput.type = "checkbox";
          enabledToggleInput.checked = isScriptEnabledForExecution(scriptItem.title);
          enabledToggleInput.dataset.action = "script-toggle";
          enabledToggleInput.dataset.configKind = "mcp";
          enabledToggleInput.dataset.configId = "scripts";
          enabledToggleInput.dataset.scriptTitle = scriptItem.title;

          const enabledToggleText = document.createElement("span");
          enabledToggleText.textContent = "Enabled";

          enabledToggleLabel.appendChild(enabledToggleInput);
          enabledToggleLabel.appendChild(enabledToggleText);
          scriptNode.appendChild(enabledToggleLabel);

          const scriptLabel = document.createElement("span");
          scriptLabel.className = "mcp-script-label";
          scriptLabel.textContent = scriptItem.title;
          if (scriptItem.description) {
            scriptLabel.title = scriptItem.description;
          }
          scriptNode.appendChild(scriptLabel);

          const editBtn = document.createElement("button");
          editBtn.type = "button";
          editBtn.className = "mcp-script-edit-btn";
          editBtn.title = "Edit script";
          editBtn.textContent = "\u270E";
          editBtn.dataset.action = "script-open";
          editBtn.dataset.configKind = "mcp";
          editBtn.dataset.configId = "scripts";
          editBtn.dataset.scriptTitle = scriptItem.title;
          scriptNode.appendChild(editBtn);

          const dlBtn = document.createElement("button");
          dlBtn.type = "button";
          dlBtn.className = "mcp-script-dl-btn";
          dlBtn.title = "Download script";
          dlBtn.textContent = "\u2193";
          dlBtn.addEventListener("click", async (e) => {
            e.stopPropagation();
            try {
              const resp = await fetch(`/api/mcps/scripts/${encodeURIComponent(scriptItem.title)}`);
              if (!resp.ok) return;
              const data = await resp.json();
              const blob = new Blob([data.source], { type: "text/x-python" });
              const url = URL.createObjectURL(blob);
              const a = document.createElement("a");
              a.href = url;
              a.download = `${scriptItem.title}.py`;
              document.body.appendChild(a);
              a.click();
              a.remove();
              URL.revokeObjectURL(url);
            } catch { /* silent */ }
          });
          scriptNode.appendChild(dlBtn);

          scriptsList.appendChild(scriptNode);
        });
        scriptsBox.appendChild(scriptsList);
      }

      cardBody.appendChild(scriptsBox);

      const newScriptButton = document.createElement("button");
      newScriptButton.type = "button";
      newScriptButton.className = "mcp-link-btn";
      newScriptButton.textContent = "New Script";
      newScriptButton.dataset.action = "script-new";
      newScriptButton.dataset.configKind = options.kind;
      newScriptButton.dataset.configId = item.id;

      const verifyButton = document.createElement("button");
      verifyButton.type = "button";
      verifyButton.className = "mcp-link-btn";
      verifyButton.textContent = "Verify";
      verifyButton.dataset.action = "verify";
      verifyButton.dataset.configKind = options.kind;
      verifyButton.dataset.configId = item.id;

      actions.appendChild(newScriptButton);
      actions.appendChild(verifyButton);
      cardBody.appendChild(actions);
    } else if (options.kind === "mcp") {
      if (item.id === "local_files") {
        card.appendChild(cardBody);
        container.appendChild(card);
        return;
      }
      if (item.id === "whatsapp") {
        const connectButton = document.createElement("button");
        connectButton.type = "button";
        connectButton.className = "mcp-link-btn";
        connectButton.textContent = "Connect";
        connectButton.dataset.action = "whatsapp-connect";
        connectButton.dataset.configKind = options.kind;
        connectButton.dataset.configId = item.id;

        const verifyButton = document.createElement("button");
        verifyButton.type = "button";
        verifyButton.className = "mcp-link-btn";
        verifyButton.textContent = "Verify";
        verifyButton.dataset.action = "verify";
        verifyButton.dataset.configKind = options.kind;
        verifyButton.dataset.configId = item.id;

        const resyncButton = document.createElement("button");
        resyncButton.type = "button";
        resyncButton.className = "mcp-link-btn";
        resyncButton.textContent = "Resync";
        resyncButton.dataset.action = "whatsapp-resync";
        resyncButton.dataset.configKind = options.kind;
        resyncButton.dataset.configId = item.id;

        actions.appendChild(connectButton);
        actions.appendChild(resyncButton);
        actions.appendChild(verifyButton);
        cardBody.appendChild(actions);
        card.appendChild(cardBody);
        container.appendChild(card);
        return;
      }
      const verifyButton = document.createElement("button");
      verifyButton.type = "button";
      verifyButton.className = "mcp-link-btn";
      verifyButton.textContent = "Verify";
      verifyButton.dataset.action = "verify";
      verifyButton.dataset.configKind = options.kind;
      verifyButton.dataset.configId = item.id;

      actions.appendChild(verifyButton);
      cardBody.appendChild(actions);
    } else {
      const saveButton = document.createElement("button");
      saveButton.type = "button";
      saveButton.className = "mcp-link-btn";
      saveButton.textContent = "Save";
      saveButton.dataset.action = "save";
      saveButton.dataset.configKind = options.kind;
      saveButton.dataset.configId = item.id;

      const verifyButton = document.createElement("button");
      verifyButton.type = "button";
      verifyButton.className = "mcp-link-btn";
      verifyButton.textContent = "Verify";
      verifyButton.dataset.action = "verify";
      verifyButton.dataset.configKind = options.kind;
      verifyButton.dataset.configId = item.id;

      actions.appendChild(saveButton);
      actions.appendChild(verifyButton);
      cardBody.appendChild(actions);
    }

    card.appendChild(cardBody);

    container.appendChild(card);
  });
}

function renderMcpPanel() {
  renderConfigPanel(mcpList, state.mcps, getMcpConfig, {
    kind: "mcp",
    emptyLabel: "No tools available.",
  });
}

function renderIntegrationPanel() {
  renderConfigPanel(integrationList, state.integrations, getIntegrationConfig, {
    kind: "integration",
    emptyLabel: "No integrations available.",
  });
}

function normalizeScriptTitles(value) {
  if (!Array.isArray(value)) {
    return [];
  }
  const seen = new Set();
  const titles = [];
  value.forEach((entry) => {
    const title = typeof entry === "string" ? entry.trim() : "";
    if (!title || seen.has(title)) {
      return;
    }
    seen.add(title);
    titles.push(title);
  });
  return titles;
}

function normalizeScriptsCatalog(value) {
  if (!Array.isArray(value)) {
    return [];
  }
  const seen = new Set();
  const scripts = [];
  value.forEach((entry) => {
    if (!entry || typeof entry !== "object") {
      return;
    }
    const title = typeof entry.title === "string" ? entry.title.trim() : "";
    if (!title || seen.has(title)) {
      return;
    }
    seen.add(title);
    scripts.push({
      title: title,
      description: typeof entry.description === "string" ? entry.description : "",
      id: typeof entry.id === "string" ? entry.id : title,
    });
  });
  return scripts;
}

function getDisabledScriptTitlesFromConfig() {
  const scriptsConfig = ensureMcpConfig("scripts");
  const rawValue = typeof scriptsConfig.params?.[SCRIPTS_DISABLED_TITLES_PARAM] === "string"
    ? scriptsConfig.params[SCRIPTS_DISABLED_TITLES_PARAM]
    : "";
  const trimmed = rawValue.trim();
  if (!trimmed) {
    return new Set();
  }

  try {
    const parsed = JSON.parse(trimmed);
    if (!Array.isArray(parsed)) {
      return new Set();
    }
    const disabledTitles = new Set();
    parsed.forEach((entry) => {
      const title = typeof entry === "string" ? entry.trim() : "";
      if (!title) {
        return;
      }
      disabledTitles.add(title);
    });
    return disabledTitles;
  } catch (error) {
    return new Set();
  }
}

function isScriptEnabledForExecution(scriptTitle) {
  const title = typeof scriptTitle === "string" ? scriptTitle.trim() : "";
  if (!title) {
    return false;
  }
  const disabledTitles = getDisabledScriptTitlesFromConfig();
  return !disabledTitles.has(title);
}

function setScriptEnabledForExecution(scriptTitle, enabled) {
  const title = typeof scriptTitle === "string" ? scriptTitle.trim() : "";
  if (!title) {
    return;
  }

  const scriptsConfig = ensureMcpConfig("scripts");
  const disabledTitles = getDisabledScriptTitlesFromConfig();
  if (enabled) {
    disabledTitles.delete(title);
  } else {
    disabledTitles.add(title);
  }

  const availableTitles = new Set(state.scripts.map((script) => script.title));
  const persistedTitles = Array.from(disabledTitles).filter((entry) => availableTitles.has(entry));
  scriptsConfig.params[SCRIPTS_DISABLED_TITLES_PARAM] = JSON.stringify(persistedTitles);
}

async function compactHistoryForLimit(chat, targetTokenLimit, reasonLabel) {
  if (state.isCompacting || !chat) {
    return;
  }

  state.isCompacting = true;
  setSwitchersDisabled(true);
  setCompactButtonDisabled(true);
  setHistoryControlsDisabled(true);
  showCompactionProgressBubble();

  try {
    setStatus(`Compacting memory for ${reasonLabel}...`);
    const response = await fetch("/api/chat/compact", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        history: toApiCompactionHistory(chat.messages),
        target_token_limit: Math.max(0, Number(targetTokenLimit || 0)),
        memory_block: chat.memory_block || "",
      }),
    });

    if (!response.ok) {
      let detail = "Compaction failed.";
      try {
        const payload = await response.json();
        if (typeof payload.detail === "string" && payload.detail) {
          detail = payload.detail;
        }
      } catch (error) {
        detail = "Compaction failed.";
      }
      throw new Error(detail);
    }

    const payload = await response.json();
    chat.memory_block = typeof payload.memory_block === "string" ? payload.memory_block : chat.memory_block;
    const contextTimestamp = createTimestamp();
    const runtimeContextMessage = {
      role: "system",
      content: buildRuntimeContextSeed(),
      timestamp: contextTimestamp,
      system_type: RUNTIME_CONTEXT_SYSTEM_TYPE,
      tool_usage: [],
      request_id: "",
      status: "",
    };
    if (chat.memory_block.trim()) {
      const timestamp = createTimestamp();
      chat.messages = [
        runtimeContextMessage,
        {
          role: "system",
          content: `Compacted memory\n\n${chat.memory_block.trim()}`,
          timestamp,
          system_type: "memory_compaction",
          tool_usage: [],
          request_id: "",
          status: "",
        },
      ];
    } else {
      chat.messages = [runtimeContextMessage];
    }
    chat.updated_at = createTimestamp();
    if (state.activeChatId === chat.id) {
      state.lastRequestTokens = estimateContextTokens(chat.messages, chat.memory_block);
    }
  } finally {
    clearCompactionProgressBubble();
    state.isCompacting = false;
    setSwitchersDisabled(state.isSwitching);
    setCompactButtonDisabled(state.isSwitching);
    setHistoryControlsDisabled(state.isSwitching);
    updateComposerState();
  }
}

async function maybeAutoCompact(chat, reasonLabel, targetTokenLimit = state.modelTokenLimit) {
  if (!chat) {
    return { ok: true, compacted: false };
  }

  if (!shouldCompactForLimit(chat.messages, chat.memory_block || "", targetTokenLimit)) {
    return { ok: true, compacted: false };
  }

  try {
    await compactHistoryForLimit(chat, targetTokenLimit, reasonLabel);
    renderActiveChat();
    renderChatHistory();
    syncUsedTokensToContext();
    showToast("Compaction complete. Chat context was reduced.");
    return { ok: true, compacted: true };
  } catch (error) {
    setStatus(error.message, true);
    return { ok: false, compacted: false };
  }
}

async function switchActiveProviderModel(nextProviderId, nextModelId) {
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
  setHistoryControlsDisabled(true);

  try {
    const activeChat = getActiveChat();
    const targetLimit = getModelTokenLimit(nextProviderId, nextModelId);
    const currentContextTokens = activeChat
      ? Math.max(Number(state.usedTokens || 0), estimateContextTokens(activeChat.messages, activeChat.memory_block || ""))
      : 0;
    if (targetLimit > 0 && currentContextTokens > targetLimit && activeChat) {
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
    state.dailyTokenUsage = normalizeDailyTokenUsage(persisted.daily_token_usage);
    updateDailyTokenUsageLabel();
    state.activeProviderId = nextProviderId;
    state.activeModelId = nextModelId;
    state.modelTokenLimit = getModelTokenLimit(nextProviderId, nextModelId);
    state.providerLabel = getProviderById(nextProviderId)?.label ?? nextProviderId;
    state.modelLabel = getProviderById(nextProviderId)?.models?.find((model) => model.id === nextModelId)?.label ?? nextModelId;

    syncSwitcherControls();
    updateMetaIndicators();
    updateAssistantHeader(state.settings);
    syncUsedTokensToContext();
    setStatus("Active provider/model updated.");
  } catch (error) {
    state.activeProviderId = previousProviderId;
    state.activeModelId = previousModelId;
    syncSwitcherControls();
    updateMetaIndicators();
    setStatus(error instanceof Error ? error.message : "Provider switch failed.", true);
  } finally {
    state.isSwitching = false;
    setSwitchersDisabled(state.isCompacting);
    setCompactButtonDisabled(state.isCompacting);
    setHistoryControlsDisabled(state.isCompacting);
    updateComposerState();
  }
}

function normalizeIncomingChats(rawChats) {
  if (!Array.isArray(rawChats)) {
    return [];
  }

  const normalized = [];
  rawChats.forEach((rawChat) => {
    if (!rawChat || typeof rawChat !== "object") {
      return;
    }

    const chatId = typeof rawChat.id === "string" ? rawChat.id.trim() : "";
    if (!chatId) {
      return;
    }

    const messages = Array.isArray(rawChat.messages)
      ? rawChat.messages
          .filter((message) => message && (message.role === "user" || message.role === "assistant" || message.role === "system"))
          .map((message) => ({
            role: message.role,
            content: typeof message.content === "string" ? message.content : "",
            timestamp: typeof message.timestamp === "string" ? message.timestamp : createTimestamp(),
            system_type: typeof message.system_type === "string" ? message.system_type : "",
            tool_usage: normalizeToolUsage(message.tool_usage),
            request_id: typeof message.request_id === "string" ? message.request_id : "",
            status: typeof message.status === "string" ? message.status : "",
          }))
      : [];

    normalized.push({
      id: chatId,
      title: normalizeChatTitle(rawChat.title),
      type: "normal",
      messages,
      memory_block: typeof rawChat.memory_block === "string" ? rawChat.memory_block : "",
      total_tokens_used:
        Number.isFinite(Number(rawChat.total_tokens_used)) && Number(rawChat.total_tokens_used) > 0
          ? Number(rawChat.total_tokens_used)
          : 0,
      collapse_system_trace:
        typeof rawChat.collapse_system_trace === "boolean" ? rawChat.collapse_system_trace : true,
      hidden_from_history: Boolean(rawChat.hidden_from_history),
      created_at: typeof rawChat.created_at === "string" ? rawChat.created_at : "",
      updated_at: typeof rawChat.updated_at === "string" ? rawChat.updated_at : "",
    });
  });

  return normalized;
}

function mergeSessionOnlySystemMessages(incomingChats, currentChats = []) {
  const currentById = new Map(
    Array.isArray(currentChats)
      ? currentChats
          .filter((chat) => chat && typeof chat.id === "string" && chat.id)
          .map((chat) => [chat.id, chat])
      : [],
  );

  return (Array.isArray(incomingChats) ? incomingChats : []).map((chat) => {
    const current = currentById.get(chat.id);
    if (!current || !Array.isArray(current.messages)) {
      return chat;
    }

    const transientSystemMessages = current.messages.filter((message) => message && message.role === "system");
    if (transientSystemMessages.length === 0) {
      return chat;
    }

    const mergedMessages = Array.isArray(chat.messages) ? [...chat.messages] : [];
    transientSystemMessages.forEach((message) => {
      const duplicate = mergedMessages.some(
        (entry) => entry
          && entry.role === "system"
          && entry.request_id === message.request_id
          && entry.system_type === message.system_type
          && entry.content === message.content,
      );
      if (!duplicate) {
        mergedMessages.push({ ...message, tool_usage: normalizeToolUsage(message.tool_usage) });
      }
    });

    mergedMessages.sort((left, right) => {
      const leftTime = new Date(typeof left?.timestamp === "string" ? left.timestamp : 0).getTime();
      const rightTime = new Date(typeof right?.timestamp === "string" ? right.timestamp : 0).getTime();
      return leftTime - rightTime;
    });

    return {
      ...chat,
      messages: mergedMessages,
    };
  });
}

function ensureVisibleActiveChat() {
  if (state.showHiddenTimedJobChats) {
    return;
  }
  const activeChat = state.chats.find((chat) => chat.id === state.activeChatId);
  if (activeChat && !isHiddenTimedJobDebugChat(activeChat)) {
    return;
  }
  const sortedChats = sortChatsByLatestMessage(state.chats);
  const nextVisibleChat = sortedChats.find((chat) => !isHiddenTimedJobDebugChat(chat));
  state.activeChatId = nextVisibleChat?.id ?? "";
}

function findReusableNewChatDraft(chats) {
  const entries = Array.isArray(chats) ? chats : [];
  return entries.find((chat) => {
    if (!chat || isHiddenTimedJobDebugChat(chat)) {
      return false;
    }
    if (normalizeChatTitle(chat.title).toLowerCase() !== "new chat") {
      return false;
    }
    return !Array.isArray(chat.messages) || chat.messages.length === 0;
  }) ?? null;
}

async function loadGatewayMeta() {
  try {
    loadAppVersion();
    const [providersResponse, settingsResponse, mcpsResponse, integrationsResponse, scriptsResponse] = await Promise.all([
      fetch("/api/providers"),
      fetch("/api/settings"),
      fetch("/api/mcps"),
      fetch("/api/integrations"),
      fetch("/api/mcps/scripts", { cache: "no-store" }),
    ]);

    if (!providersResponse.ok || !settingsResponse.ok || !mcpsResponse.ok || !integrationsResponse.ok || !scriptsResponse.ok) {
      throw new Error("Failed to load gateway metadata.");
    }

    const providers = await providersResponse.json();
    const settings = await settingsResponse.json();
    const mcps = await mcpsResponse.json();
    const integrations = await integrationsResponse.json();
    const scriptsCatalog = await scriptsResponse.json();

    const activeProvider = providers.find((provider) => provider.id === settings.active_provider_id);
    const activeConfig = settings.provider_configs?.[settings.active_provider_id];

    state.providers = providers;
    state.settings = settings;
    applyThemeMode(settings.theme);
    state.activeProviderId = settings.active_provider_id ?? "";
    state.activeModelId = activeConfig?.model ?? "";
    state.botName = typeof settings?.bot_name === "string" ? settings.bot_name.trim() : "";
    state.coreMemories = normalizeIncomingMemories(settings.core_memories);
    state.normalMemories = normalizeIncomingMemories(settings.normal_memories);
    state.chats = mergeSessionOnlySystemMessages(normalizeIncomingChats(settings.chats), state.chats);
    state.dailyTokenUsage = normalizeDailyTokenUsage(settings.daily_token_usage);
    state.mcps = Array.isArray(mcps) ? mcps : [];
    state.scriptTitles = normalizeScriptTitles(scriptsCatalog?.titles);
    state.scripts = normalizeScriptsCatalog(scriptsCatalog?.scripts);
    state.integrations = Array.isArray(integrations) ? integrations : [];
    state.mcpConfigs = normalizeIncomingMcpConfigs(settings.mcp_configs);
    state.integrationConfigs = normalizeIncomingMcpConfigs(settings.integration_configs);
    hydrateWhatsappContactsFromCache();
    try {
      await fetchGoogleOauthStatus();
    } catch (error) {
      state.googleOauthStatus = null;
    }
    await fetchWhatsappContacts();
    syncTelegramFlagsFromIntegrationConfig();
    state.telegramOwnerUserId = typeof settings?.telegram_state?.owner_user_id === "string"
      ? settings.telegram_state.owner_user_id
      : "";
    state.telegramOwnerChatId = typeof settings?.telegram_state?.owner_chat_id === "string"
      ? settings.telegram_state.owner_chat_id
      : "";

    state.providerLabel = activeProvider?.label ?? settings.active_provider_id ?? "";
    state.modelLabel = activeProvider?.models?.find((model) => model.id === activeConfig?.model)?.label ?? activeConfig?.model ?? "";
    state.modelTokenLimit = getModelTokenLimit(state.activeProviderId, state.activeModelId);

    const reusableNewChatDraft = findReusableNewChatDraft(state.chats);
    let createdNewChatDraft = false;
    if (reusableNewChatDraft) {
      state.activeChatId = reusableNewChatDraft.id;
    } else {
      const freshChat = createChatEntry("");
      freshChat.title = "New chat";
      state.chats.push(freshChat);
      state.activeChatId = freshChat.id;
      createdNewChatDraft = true;
    }
    ensureVisibleActiveChat();
    if (createdNewChatDraft) {
      try {
        await persistChatsToSettings();
      } catch (error) {
      }
    }

    syncSwitcherControls();
    updateMetaIndicators();
    updateAssistantHeader(settings);
    renderChatHistory();
    renderActiveChat();
    renderMcpPanel();
    renderIntegrationPanel();
    syncUsedTokensToContext();
    updateDailyTokenUsageLabel();
    updateTelegramStatusLabel();
    updateShortTermMemoryBadge();
    refreshLocalChatStateSignature();
    startChatStateSync();
    startIntegrationStatusSync();
    startTimedJobAuthAlertSync();
    startShortTermMemorySync();
    loadShortTermMemory(false);
    loadTimedJobs(false);
    syncIntegrationStatus();
    syncTimedJobAuthAlertStatus();
    updateComposerState();
    setStatus("");
  } catch (error) {
    updateMetaIndicators();
    assistantTitleNode.textContent = "This is your personal assistant";
    if (mobileAssistantNameNode instanceof HTMLElement) {
      mobileAssistantNameNode.textContent = "Assistant";
    }
    assistantMetaNode.textContent = "Assistant metadata unavailable.";
    syncSwitcherControls();
    renderChatHistory();
    renderEmptyChatView();
    renderMcpPanel();
    renderIntegrationPanel();
    updateTokenCounter(0, 0);
    updateDailyTokenUsageLabel();
    updateTelegramStatusLabel();
    updateShortTermMemoryBadge();
    startChatStateSync();
    startIntegrationStatusSync();
    startTimedJobAuthAlertSync();
    startShortTermMemorySync();
    loadShortTermMemory(false);
    loadTimedJobs(false);
    renderTimedJobAuthAlert({ active: false });
    updateComposerState();
    setStatus(error.message, true);
  }
}

function buildChatStateSignature(payload) {
  const chats = Array.isArray(payload?.chats)
    ? payload.chats.map((chat) => {
      if (!chat || typeof chat !== "object") {
        return chat;
      }
      const messages = Array.isArray(chat.messages)
        ? chat.messages.filter((message) => message && message.role !== "system")
        : [];
      return {
        ...chat,
        messages,
      };
    })
    : [];
  const activeChatId = typeof payload?.active_chat_id === "string" ? payload.active_chat_id : "";
  const dailyTokenUsage = Array.isArray(payload?.daily_token_usage) ? payload.daily_token_usage : [];
  return JSON.stringify({ chats, activeChatId, dailyTokenUsage });
}

function refreshLocalChatStateSignature() {
  state.lastChatStateSignature = buildChatStateSignature({
    chats: state.chats,
    active_chat_id: state.activeChatId,
    daily_token_usage: state.dailyTokenUsage,
  });
}

function markLocalChatStatePending() {
  state.chatStateDirty = true;
  state.chatStateMutationVersion += 1;
  refreshLocalChatStateSignature();
}

function applyRemoteChatState(payload) {
  const incomingChats = mergeSessionOnlySystemMessages(normalizeIncomingChats(payload?.chats), state.chats);
  const incomingActiveChatId = typeof payload?.active_chat_id === "string" ? payload.active_chat_id : "";
  const incomingDailyUsage = normalizeDailyTokenUsage(payload?.daily_token_usage);
  const currentActiveChatId = state.activeChatId;

  state.chats = incomingChats;
  state.dailyTokenUsage = incomingDailyUsage;
  updateDailyTokenUsageLabel();

  if (currentActiveChatId && state.chats.some((chat) => chat.id === currentActiveChatId)) {
    state.activeChatId = currentActiveChatId;
  } else if (state.chats.some((chat) => chat.id === incomingActiveChatId)) {
    state.activeChatId = incomingActiveChatId;
  } else {
    const sorted = sortChatsByLatestMessage(state.chats);
    state.activeChatId = sorted[0]?.id ?? "";
  }
  ensureVisibleActiveChat();

  renderChatHistory();
  renderActiveChat();
  syncUsedTokensToContext();
  updateComposerState();
}

async function syncRemoteChatState() {
  if (state.chatSyncInFlight || state.isCompacting || state.isSwitching || state.chatPersistInFlight || state.chatStateDirty) {
    return;
  }

  const startedAtMutationVersion = state.chatStateMutationVersion;
  state.chatSyncInFlight = true;
  try {
    const response = await fetch("/api/chat/state", { cache: "no-store" });
    if (!response.ok) {
      return;
    }
    const payload = await response.json();

    if (startedAtMutationVersion !== state.chatStateMutationVersion || state.chatPersistInFlight || state.chatStateDirty) {
      return;
    }

    const signature = buildChatStateSignature(payload);
    if (signature === state.lastChatStateSignature) {
      return;
    }

    state.lastChatStateSignature = signature;
    applyRemoteChatState(payload);
  } catch (error) {
    // Keep sync best-effort and silent.
  } finally {
    state.chatSyncInFlight = false;
  }
}

function startChatStateSync() {
  if (state.chatSyncTimerId) {
    window.clearInterval(state.chatSyncTimerId);
  }
  state.chatSyncTimerId = window.setInterval(syncRemoteChatState, CHAT_SYNC_INTERVAL_MS);
}

function startIntegrationStatusSync() {
  if (state.integrationStatusSyncTimerId) {
    window.clearInterval(state.integrationStatusSyncTimerId);
  }
  state.integrationStatusSyncTimerId = window.setInterval(syncIntegrationStatus, INTEGRATION_STATUS_SYNC_INTERVAL_MS);
}

function startTimedJobAuthAlertSync() {
  if (state.timedJobAuthAlertSyncTimerId) {
    window.clearInterval(state.timedJobAuthAlertSyncTimerId);
  }
  state.timedJobAuthAlertSyncTimerId = window.setInterval(
    syncTimedJobAuthAlertStatus,
    INTEGRATION_STATUS_SYNC_INTERVAL_MS,
  );
}

function startShortTermMemorySync() {
  if (state.shortTermMemorySyncTimerId) {
    window.clearInterval(state.shortTermMemorySyncTimerId);
  }
  state.shortTermMemorySyncTimerId = window.setInterval(() => {
    loadShortTermMemory(false);
  }, CHAT_SYNC_INTERVAL_MS);
}

function toggleMenu(forceOpen) {
  const shouldOpen = typeof forceOpen === "boolean" ? forceOpen : menuPopover.classList.contains("hidden");
  menuPopover.classList.toggle("hidden", !shouldOpen);
  menuButton.setAttribute("aria-expanded", shouldOpen ? "true" : "false");
}

function updateComposerState() {
  const activeChatId = state.activeChatId;
  const isBusy = activeChatId ? isChatBusy(activeChatId) : false;
  sendButton.disabled = false;
  chatInput.disabled = false;
  if (stopButton instanceof HTMLButtonElement) {
    stopButton.disabled = !isBusy;
  }
  setSpeechUiState();
  setSwitchersDisabled(state.isSwitching || state.isCompacting);
  setCompactButtonDisabled(state.isSwitching || state.isCompacting || isBusy);
  setHistoryControlsDisabled(state.isSwitching || state.isCompacting);
}

function processSseBlock(block, context) {
  const lines = block.split("\n");
  let eventName = "message";
  let data = "";

  lines.forEach((line) => {
    if (line.startsWith("event:")) {
      eventName = line.slice(6).trim();
      return;
    }

    if (line.startsWith("data:")) {
      data += line.slice(5).trim();
    }
  });

  if (!data) {
    return { done: false, hasError: false };
  }

  let payload = {};
  try {
    payload = JSON.parse(data);
  } catch (error) {
    const preview = data.length > 160 ? `${data.slice(0, 160)}...` : data;
    return { done: false, hasError: true, errorMessage: `Invalid stream payload: ${preview}` };
  }

  if (eventName === "token") {
    context.assistantMessage.content = `${context.assistantMessage.content || ""}${payload.text ?? ""}`;
    context.assistantMessage.status = "processing";
    if (state.activeChatId === context.chatId) {
      renderActiveChat();
    }
    return { done: false, hasError: false };
  }

  if (eventName === "meta") {
    const requestUsedTokens = Number(payload.used_tokens ?? 0);
    if (Number.isFinite(requestUsedTokens) && requestUsedTokens > 0) {
      context.usedTokens = requestUsedTokens;
      if (state.activeChatId === context.chatId) {
        state.lastRequestTokens = requestUsedTokens;
        syncUsedTokensToContext();
      }
    }

    context.toolUsage = normalizeToolUsage(payload.used_mcp_tools);
    const metaTrace = Array.isArray(payload.system_trace_messages)
      ? payload.system_trace_messages
          .filter((entry) => entry && typeof entry === "object")
          .map((entry) => ({
            system_type: typeof entry.system_type === "string" ? entry.system_type : "orchestrator",
            content: typeof entry.content === "string" ? entry.content : "",
          }))
          .filter((entry) => entry.content)
      : [];
    if (metaTrace.length > 0) {
      const merged = [...context.systemTrace];
      metaTrace.forEach((entry) => {
        const exists = merged.some((item) => item.system_type === entry.system_type && item.content === entry.content);
        if (!exists) {
          merged.push(entry);
        }
      });
      context.systemTrace = merged;
    }

    if (payload.token_limit && state.activeChatId === context.chatId) {
      updateTokenCounter(state.usedTokens, payload.token_limit ?? state.modelTokenLimit);
    }
    return { done: false, hasError: false };
  }

  if (eventName === "tool_step") {
    const entry = {
      system_type: typeof payload.system_type === "string" ? payload.system_type : "tool_step",
      content: typeof payload.content === "string" ? payload.content : "",
    };

    if (entry.content) {
      const duplicate = context.systemTrace.some(
        (item) => item.system_type === entry.system_type && item.content === entry.content,
      );
      if (!duplicate) {
        context.systemTrace.push(entry);
        const chat = state.chats.find((entryChat) => entryChat.id === context.chatId);
        if (chat) {
          appendSystemTraceMessages(chat, [entry], createTimestamp(), context.requestId);
          chat.updated_at = createTimestamp();
          if (state.activeChatId === context.chatId) {
            renderActiveChat();
          }
          renderChatHistory();
        }
      }
    }
    return { done: false, hasError: false };
  }

  if (eventName === "done") {
    return { done: true, hasError: false };
  }

  if (eventName === "error") {
    return {
      done: true,
      hasError: true,
      errorMessage: payload.detail ?? "Chat failed.",
    };
  }

  return { done: false, hasError: false };
}

function appendSystemTraceMessages(chat, traceMessages, timestamp, requestId = "") {
  if (!Array.isArray(traceMessages) || traceMessages.length === 0) {
    return;
  }

  traceMessages.forEach((entry) => {
    if (!entry || typeof entry !== "object") {
      return;
    }

    const content = typeof entry.content === "string" ? entry.content.trim() : "";
    if (!content) {
      return;
    }

    const duplicate = chat.messages.some(
      (message) =>
        message.role === "system" &&
        message.request_id === requestId &&
        message.system_type === (typeof entry.system_type === "string" ? entry.system_type : "orchestrator") &&
        message.content === content,
    );
    if (duplicate) {
      return;
    }

    chat.messages.push({
      role: "system",
      content,
      timestamp,
      system_type: typeof entry.system_type === "string" ? entry.system_type : "orchestrator",
      tool_usage: [],
      request_id: requestId,
      status: "",
    });
  });
}

async function finalizeSuccessfulResponse(chat, assistantMessage, context) {
  if (!chat || !assistantMessage) {
    return;
  }

  const assistantTimestamp = createTimestamp();
  appendSystemTraceMessages(chat, context.systemTrace, assistantTimestamp, context.requestId);

  assistantMessage.timestamp = assistantTimestamp;
  assistantMessage.status = "done";
  assistantMessage.tool_usage = context.toolUsage;
  if (Number.isFinite(Number(context.usedTokens)) && Number(context.usedTokens) > 0) {
    const currentTotal = Number(chat.total_tokens_used || 0);
    chat.total_tokens_used = Math.max(0, currentTotal) + Number(context.usedTokens);
    addDailyTokenUsage(Number(context.usedTokens));
  }
  chat.updated_at = assistantTimestamp;

  if (state.activeChatId === chat.id) {
    state.lastRequestTokens = Number.isFinite(Number(context.usedTokens)) ? Number(context.usedTokens) : 0;
  }

  const compactResult = await maybeAutoCompact(chat, "ongoing chat", state.modelTokenLimit);
  if (!compactResult.ok) {
    return;
  }

  if (state.activeChatId === chat.id) {
    renderActiveChat();
  }
  renderChatHistory();
  if (state.activeChatId === chat.id) {
    syncUsedTokensToContext();
  }

  try {
    await persistChatsToSettings();
  } catch (error) {
    setStatus(`Response complete, but chat history was not saved: ${error.message}`, true);
    return;
  }

  try {
    await refreshTimedJobsAfterMcpUsage(context.toolUsage);
  } catch {
    // Best-effort sync only.
  }

  try {
    await refreshScriptsAfterMcpUsage(context.toolUsage);
  } catch {
    // Best-effort sync only.
  }

  const userMessages = Array.isArray(chat.messages)
    ? chat.messages.filter((message) => message && message.role === "user" && typeof message.content === "string")
    : [];
  const lastUserMessage = userMessages.length > 0 ? userMessages[userMessages.length - 1].content : "";
  registerCompletedTurnForMemory("gateway", chat.id, lastUserMessage, assistantMessage.content || "").catch(() => {});
  sendAssistantResponseNotification(chat, assistantMessage);

  if (compactResult.compacted) {
    setStatus("Response complete. Memory compacted.");
    return;
  }

  setStatus("Response complete.");
}

function buildQueueSnapshot(chat) {
  const activeProviderId = state.activeProviderId;
  const providerConfig = state.settings?.provider_configs?.[activeProviderId] ?? null;
  return {
    history: toApiChatHistory(chat.messages),
    memoryBlock: chat.memory_block || "",
    providerId: activeProviderId,
    model: providerConfig?.model ?? "",
    apiKey: providerConfig?.api_key ?? "",
    botName: state.settings?.bot_name ?? "",
    systemPrompt: state.settings?.system_prompt ?? "",
  };
}

function findMessageByRequestId(chat, requestId) {
  return chat.messages.find((message) => message.request_id === requestId) ?? null;
}

async function executeQueuedJob(chat, job, runtime) {
  const assistantMessage = findMessageByRequestId(chat, job.requestId);
  if (!assistantMessage) {
    return;
  }

  assistantMessage.status = "processing";
  const context = {
    chatId: chat.id,
    requestId: job.requestId,
    assistantMessage,
    usedTokens: 0,
    toolUsage: [],
    systemTrace: [],
  };
  if (state.activeChatId === chat.id) {
    renderActiveChat();
    setStatus("Processing...");
  }
  renderChatHistory();

  try {
    runtime.abortController = new AbortController();
    const response = await fetch("/api/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      signal: runtime.abortController.signal,
      body: JSON.stringify({
        message: job.message,
        history: job.snapshot.history,
        memory_block: job.snapshot.memoryBlock,
        provider_id: job.snapshot.providerId,
        model: job.snapshot.model,
        api_key: job.snapshot.apiKey,
        bot_name: job.snapshot.botName,
        system_prompt: job.snapshot.systemPrompt,
        source_channel: "gateway",
        source_chat_id: chat.id,
      }),
    });

    if (!response.ok) {
      const detail = await buildHttpErrorDetail(response, "Chat request failed.");
      throw new Error(detail);
    }

    if (!response.body) {
      throw new Error("Chat request failed. HTTP 200 but response body stream was empty.");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        break;
      }

      if (runtime.cancelledRequestIds.has(job.requestId)) {
        return;
      }

      buffer += decoder.decode(value, { stream: true });
      const blocks = buffer.split("\n\n");
      buffer = blocks.pop() ?? "";

      for (const block of blocks) {
        const result = processSseBlock(block, context);
        if (result.hasError) {
          throw new Error(result.errorMessage);
        }

        if (result.done) {
          break;
        }
      }
    }

    if (runtime.cancelledRequestIds.has(job.requestId)) {
      return;
    }

    await finalizeSuccessfulResponse(chat, assistantMessage, context);
  } catch (error) {
    if (runtime.cancelledRequestIds.has(job.requestId)) {
      return;
    }

    if (error instanceof DOMException && error.name === "AbortError") {
      return;
    }

    const hardErrorText = normalizeErrorMessage(error, "Hard error.");
    console.error("Gateway chat request failed", {
      chatId: chat.id,
      requestId: job.requestId,
      providerId: job.snapshot.providerId,
      model: job.snapshot.model,
      messagePreview: typeof job.message === "string" ? job.message.slice(0, 160) : "",
      error: hardErrorText,
    });
    if (assistantMessage.content) {
      assistantMessage.content = `${assistantMessage.content}\n\nHard error: ${hardErrorText}`;
    } else {
      assistantMessage.content = hardErrorText;
    }

    const errorTimestamp = createTimestamp();
    appendSystemTraceMessages(chat, context.systemTrace, errorTimestamp, context.requestId);
    assistantMessage.timestamp = errorTimestamp;
    assistantMessage.status = "error";
    assistantMessage.tool_usage = context.toolUsage;
    if (Number.isFinite(Number(context.usedTokens)) && Number(context.usedTokens) > 0) {
      const currentTotal = Number(chat.total_tokens_used || 0);
      chat.total_tokens_used = Math.max(0, currentTotal) + Number(context.usedTokens);
      addDailyTokenUsage(Number(context.usedTokens));
    }
    chat.updated_at = errorTimestamp;

    if (state.activeChatId === chat.id) {
      state.lastRequestTokens = Number.isFinite(Number(context.usedTokens)) ? Number(context.usedTokens) : 0;
      renderActiveChat();
      syncUsedTokensToContext();
    }
    renderChatHistory();
    setStatus(hardErrorText, true);

    try {
      await persistChatsToSettings();
    } catch (persistError) {
      setStatus(`Response failed and save failed: ${persistError.message}`, true);
    }
  } finally {
    runtime.abortController = null;
  }
}

async function processChatQueue(chatId) {
  const runtime = getChatRuntime(chatId);
  if (!runtime || runtime.processing) {
    return;
  }

  runtime.processing = true;
  try {
    while (runtime.queue.length > 0) {
      const job = runtime.queue.shift();
      if (!job || runtime.cancelledRequestIds.has(job.requestId)) {
        continue;
      }

      const chat = state.chats.find((entry) => entry.id === chatId);
      if (!chat) {
        runtime.cancelledRequestIds.add(job.requestId);
        continue;
      }

      runtime.activeRequestId = job.requestId;
      await executeQueuedJob(chat, job, runtime);
      runtime.activeRequestId = "";

      try {
        await persistChatsToSettings();
      } catch (error) {
        setStatus(`Queued response save failed: ${error.message}`, true);
      }
    }
  } finally {
    runtime.processing = false;
    runtime.activeRequestId = "";
    renderChatHistory();
    if (state.activeChatId === chatId) {
      updateComposerState();
    }
  }
}

async function sendMessage(event) {
  event.preventDefault();

  if (state.speechListening) {
    stopSpeechRecognition(true);
  }

  requestNotificationPermissionIfNeeded().catch(() => {});

  if (state.isSwitching || state.isCompacting) {
    setStatus("Please wait for current gateway operation to finish.", true);
    return;
  }

  const message = chatInput.value.trim();
  const pendingImage = clonePendingImageAttachment(state.pendingImageAttachment);
  if (!message && !pendingImage) {
    setStatus("Please enter a message or attach an image.", true);
    return;
  }

  let chat = getActiveChat();
  if (!chat) {
    chat = createChatEntry(message);
    state.chats.push(chat);
    state.activeChatId = chat.id;
    updateCurrentChatTitle();
    updateSystemTraceToggleLabel();
  } else if ((!Array.isArray(chat.messages) || chat.messages.length === 0) && normalizeChatTitle(chat.title).toLowerCase() === "new chat") {
    chat.title = deriveChatTitle(message);
  }

  ensureRuntimeContextSeed(chat);
  const chatExistsInPersistedSettings = Array.isArray(state.settings?.chats)
    && state.settings.chats.some((entry) => entry && entry.id === chat.id);
  if (!chatExistsInPersistedSettings) {
    try {
      await persistChatsToSettings();
    } catch (error) {
      setStatus(normalizeErrorMessage(error, "Failed to prepare chat."), true);
      return;
    }
  }

  const userContent = pendingImage
    ? (message ? `${message}\n\n[Image attached]` : "[Image attached]")
    : message;
  const draftKey = buildEnqueueDraftKey(message, pendingImage);
  if (state.pendingEnqueueByChat[chat.id] === draftKey) {
    setStatus("This message is already being queued.", true);
    return;
  }

  const clientEnqueueId = createClientEnqueueId();
  state.pendingEnqueueByChat[chat.id] = draftKey;
  const localRequestId = createLocalRequestId();
  const queuedTimestamp = createTimestamp();
  const optimisticUserMessage = {
    role: "user",
    content: userContent,
    timestamp: queuedTimestamp,
    system_type: "",
    tool_usage: [],
    request_id: localRequestId,
    status: "",
  };
  const optimisticAssistantMessage = {
    role: "assistant",
    content: "",
    timestamp: "",
    system_type: "",
    tool_usage: [],
    request_id: localRequestId,
    status: "queued",
  };
  chat.messages.push(optimisticUserMessage);
  chat.messages.push(optimisticAssistantMessage);
  chat.updated_at = queuedTimestamp;

  if (state.activeChatId === chat.id) {
    renderActiveChat();
  }
  renderChatHistory();
  chatInput.value = "";
  clearPendingImageAttachment();
  syncChatInputHeight();
  updateComposerState();

  try {
    const snapshot = buildQueueSnapshot(chat);
    const response = await fetch("/api/chat/enqueue", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        chat_id: chat.id,
        message,
        client_enqueue_id: clientEnqueueId,
        image: pendingImage
          ? {
            file_name: String(pendingImage.fileName || "image"),
            mime_type: String(pendingImage.mimeType || "image/jpeg"),
            content_base64: String(pendingImage.contentBase64 || ""),
          }
          : null,
        provider_id: snapshot.providerId,
        model: snapshot.model,
        api_key: snapshot.apiKey,
        bot_name: snapshot.botName,
        system_prompt: snapshot.systemPrompt,
      }),
    });
    if (!response.ok) {
      const detail = await buildHttpErrorDetail(response, "Chat request failed.");
      throw new Error(detail);
    }
    const payload = await response.json();
    const serverRequestId = typeof payload?.request_id === "string" ? payload.request_id.trim() : "";
    if (serverRequestId) {
      optimisticAssistantMessage.request_id = serverRequestId;
      optimisticUserMessage.request_id = "";
    }
    setStatus("Queued.");
    void syncRemoteChatState();
  } catch (error) {
    const filteredMessages = chat.messages.filter((entry) => entry?.request_id !== localRequestId);
    chat.messages = filteredMessages;
    chat.updated_at = createTimestamp();
    if (state.activeChatId === chat.id) {
      renderActiveChat();
    }
    renderChatHistory();
    if (state.activeChatId === chat.id && !chatInput.value && !state.pendingImageAttachment) {
      chatInput.value = message;
      state.pendingImageAttachment = pendingImage;
      renderPendingImageAttachment();
      syncChatInputHeight();
    }
    updateComposerState();
    setStatus(normalizeErrorMessage(error, "Failed to queue message."), true);
    delete state.pendingEnqueueByChat[chat.id];
    return;
  }

  delete state.pendingEnqueueByChat[chat.id];
  chatInput.focus();
}

async function triggerManualCompaction() {
  if (state.isCompacting || state.isSwitching) {
    return;
  }

  const activeChat = getActiveChat();
  if (!activeChat) {
    setStatus("No active chat to compact.", true);
    return;
  }

  const runtime = getChatRuntime(activeChat.id);
  if (runtime?.processing || isChatBusy(activeChat.id)) {
    setStatus("Cannot compact while this chat is processing queued messages.", true);
    return;
  }

  try {
    await compactHistoryForLimit(activeChat, state.modelTokenLimit, "manual request");
    renderActiveChat();
    renderChatHistory();
    syncUsedTokensToContext();
    await persistChatsToSettings();
    showToast("Compaction complete. Chat context was reduced.");
    setStatus("Memory compacted.");
  } catch (error) {
    setStatus(error.message, true);
  }
}

async function stopActiveChatExecution() {
  const activeChat = getActiveChat();
  if (!activeChat) {
    return;
  }
  try {
    const response = await fetch("/api/chat/stop", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chat_id: activeChat.id }),
    });
    if (!response.ok) {
      const detail = await buildHttpErrorDetail(response, "Failed to stop chat execution.");
      throw new Error(detail);
    }
    await syncRemoteChatState();
    setStatus("Execution stopped. Queued messages were cleared.", true);
  } catch (error) {
    setStatus(normalizeErrorMessage(error, "Failed to stop chat execution."), true);
  }
}

function ensureMcpConfig(mcpId) {
  if (!state.mcpConfigs[mcpId] || typeof state.mcpConfigs[mcpId] !== "object") {
    state.mcpConfigs[mcpId] = { enabled: getMcpDefaultEnabled(mcpId), params: {} };
  }

  if (!state.mcpConfigs[mcpId].params || typeof state.mcpConfigs[mcpId].params !== "object") {
    state.mcpConfigs[mcpId].params = {};
  }

  return state.mcpConfigs[mcpId];
}

function ensureIntegrationConfig(integrationId) {
  if (!state.integrationConfigs[integrationId] || typeof state.integrationConfigs[integrationId] !== "object") {
    state.integrationConfigs[integrationId] = { enabled: false, params: {} };
  }

  if (!state.integrationConfigs[integrationId].params || typeof state.integrationConfigs[integrationId].params !== "object") {
    state.integrationConfigs[integrationId].params = {};
  }

  return state.integrationConfigs[integrationId];
}

function getIntegrationConfig(integrationId) {
  const config = state.integrationConfigs[integrationId];
  if (config && typeof config === "object") {
    return config;
  }

  return { enabled: false, params: {} };
}

function handleMcpInputChange(event) {
  const target = event.target;
  if (!(target instanceof HTMLInputElement) && !(target instanceof HTMLSelectElement) && !(target instanceof HTMLTextAreaElement)) {
    return;
  }

  const action = target.dataset.action;
  const configKind = target.dataset.configKind;
  const configId = target.dataset.configId;
  if (!action || !configKind || !configId) {
    return;
  }

  const config = configKind === "integration" ? ensureIntegrationConfig(configId) : ensureMcpConfig(configId);
  if (action === "toggle") {
    config.enabled = target.checked;
    if (configKind === "mcp") {
      scheduleMcpAutosave(configId);
    }
    if (configKind === "integration" && configId === "telegram") {
      syncTelegramFlagsFromIntegrationConfig();
      updateTelegramStatusLabel();
    }
    return;
  }

  if (action === "param") {
    const fieldId = target.dataset.fieldId;
    if (!fieldId) {
      return;
    }
    let persistImmediately = false;
    if (target instanceof HTMLInputElement && target.type === "checkbox") {
      config.params[fieldId] = target.checked ? "true" : "false";
      if (configKind === "mcp" && configId === "whatsapp" && fieldId === "auto_answer" && !target.checked) {
        persistImmediately = true;
      }
    } else {
      config.params[fieldId] = target.value;
    }
    if (configKind === "mcp") {
      if (persistImmediately) {
        if (state.mcpAutosaveTimerId) {
          window.clearTimeout(state.mcpAutosaveTimerId);
          state.mcpAutosaveTimerId = null;
        }
        state.mcpAutosavePendingId = "";
        void runMcpAutosave(configId);
      } else {
        scheduleMcpAutosave(configId);
      }
    }
    if (configKind === "integration" && configId === "telegram") {
      syncTelegramFlagsFromIntegrationConfig();
      updateTelegramStatusLabel();
    }
    return;
  }

  if (action === "param-multiselect") {
    const fieldId = target.dataset.fieldId;
    if (!fieldId) {
      return;
    }
    const cardNode = target.closest(".mcp-card");
    if (!(cardNode instanceof HTMLElement)) {
      return;
    }
    const fieldsetNode = cardNode.querySelector(`.mcp-multiselect[data-field-id='${fieldId}']`);
    config.params[fieldId] = encodeMultiselectParam(readMultiselectSelection(fieldsetNode));
    if (configKind === "mcp") {
      scheduleMcpAutosave(configId);
    }
    return;
  }

  if (action === "script-toggle" && configKind === "mcp" && configId === "scripts") {
    if (!(target instanceof HTMLInputElement)) {
      return;
    }
    const scriptTitle = typeof target.dataset.scriptTitle === "string" ? target.dataset.scriptTitle : "";
    setScriptEnabledForExecution(scriptTitle, target.checked);
    scheduleMcpAutosave(configId);
    return;
  }

  if (action === "google-write-access" && configKind === "mcp" && configId === "google_services") {
    if (!(target instanceof HTMLInputElement)) {
      return;
    }
    config.params.access_mode = target.checked ? "read_write" : "read_only";
    scheduleMcpAutosave(configId);
  }
}

async function handleMcpActionClick(event) {
  const target = event.target;
  if (!(target instanceof HTMLElement)) {
    return;
  }

  const actionNode = target.closest("[data-action][data-config-kind][data-config-id]");
  if (!(actionNode instanceof HTMLElement)) {
    return;
  }

  const action = actionNode.dataset.action;
  const configKind = actionNode.dataset.configKind;
  const configId = actionNode.dataset.configId;
  if (!action || !configKind || !configId) {
    return;
  }

  try {
    if (action === "expand") {
      toggleConfigExpanded(configKind, configId);
      if (configKind === "integration") {
        renderIntegrationPanel();
      } else {
        renderMcpPanel();
      }
      return;
    }

    if (action === "google-guide-toggle" && configKind === "mcp" && configId === "google_services") {
      state.googleGuideExpanded = !Boolean(state.googleGuideExpanded);
      renderMcpPanel();
      return;
    }

    if (action === "save") {
      await persistMcpConfigsToSettings();
      setStatus(configKind === "integration" ? "Integration settings saved." : "Tool settings saved.");
      return;
    }

    if (action === "ssh-key") {
      await fetchGitSshKey();
      setStatus("GitHub SSH public key copied to clipboard.");
      return;
    }

    if (action === "verify-ssh") {
      const result = await verifyGitSshAccess();
      const detail = typeof result?.detail === "string" ? result.detail.trim() : "";
      const message = detail ? `GitHub SSH verified: ${detail}` : "GitHub SSH access verified.";
      setStatus(message);
      showToast(message);
      return;
    }

    if (action === "google-login") {
      await startGoogleOauthLogin();
      setStatus(Boolean(state.googleOauthStatus?.connected) ? "Google account connected." : "Google login was closed.");
      return;
    }

    if (action === "whatsapp-connect" && configKind === "mcp" && configId === "whatsapp") {
      const popup = window.open("/api/mcps/whatsapp/connect", "krill-whatsapp-connect", "width=560,height=760");
      if (!popup) {
        setStatus("Popup blocked. Allow popups for this site to connect WhatsApp.", true);
        return;
      }
      popup.focus();
      setStatus("WhatsApp connect window opened.");
      const checkTimer = window.setInterval(async () => {
        if (!popup || popup.closed) {
          window.clearInterval(checkTimer);
          await syncWhatsappContactsWithRetry();
          renderMcpPanel();
        }
      }, 1200);
      return;
    }

    if (action === "whatsapp-resync" && configKind === "mcp" && configId === "whatsapp") {
      const syncResult = await syncWhatsappContactsWithRetry();
      renderMcpPanel();
      const contacts = Array.isArray(syncResult?.contacts) ? syncResult.contacts : [];
      const count = contacts.length;
      if (count > 0) {
        if (syncResult?.cacheRetained) {
          const warning = typeof syncResult.warning === "string" && syncResult.warning.trim()
            ? syncResult.warning.trim()
            : "Resync returned no contacts. Kept previously cached contacts.";
          setStatus(`${warning} Cached contacts: ${count}.`, true);
          showToast(`Kept cached WhatsApp contacts (${count}).`);
        } else {
          setStatus(`WhatsApp contacts synced (${count}).`);
          showToast(`WhatsApp contacts synced (${count}).`);
        }
      } else {
        const warning = typeof syncResult?.warning === "string" && syncResult.warning.trim()
          ? syncResult.warning.trim()
          : "No WhatsApp contacts synced yet. Verify WhatsApp is ready, then retry.";
        setStatus(warning, true);
      }
      return;
    }

    if (action === "script-open" && configKind === "mcp" && configId === "scripts") {
      const scriptTitle = actionNode.dataset.scriptTitle;
      if (scriptTitle) {
        await openScriptEditor(scriptTitle);
      }
      return;
    }

    if (action === "script-new" && configKind === "mcp" && configId === "scripts") {
      openNewScriptEditor();
      return;
    }

    if (action === "verify") {
      if (configKind === "integration") {
        const result = await verifyIntegrationConfig(configId);
        const detail = typeof result?.detail === "string" ? result.detail.trim() : "";
        const message = detail ? `Integration verified: ${detail}` : "Integration verified.";
        setStatus(message);
        showToast(message);
        if (configId === "telegram" && timedJobsModal instanceof HTMLElement && !timedJobsModal.classList.contains("hidden")) {
          await loadTimedJobs(true);
        }
      } else {
        const result = await verifyMcpConfig(configId);
        const detail = typeof result?.detail === "string" ? result.detail.trim() : "";
        const message = detail ? `Tool verified: ${detail}` : "Tool verified.";
        if (configId === "whatsapp") {
          await syncWhatsappContactsWithRetry();
          renderMcpPanel();
        }
        setStatus(message);
        showToast(message);
      }
      return;
    }
  } catch (error) {
    setStatus(error.message, true);
  }
}

async function toggleSystemTraceVisibility() {
  const activeChat = getActiveChat();
  if (!activeChat) {
    return;
  }

  activeChat.collapse_system_trace = !Boolean(activeChat.collapse_system_trace);
  renderActiveChat();

  try {
    await persistChatsToSettings();
  } catch (error) {
    setStatus(`System trace toggle saved locally only: ${error.message}`, true);
  }
}

// ---------------------------------------------------------------------------
// Script Editor
// ---------------------------------------------------------------------------

function highlightPython(source) {
  const escaped = escapeHtml(source);
  const lines = escaped.split("\n");
  const result = [];
  const kwSet = new Set([
    "False", "None", "True", "and", "as", "assert", "async", "await",
    "break", "class", "continue", "def", "del", "elif", "else", "except",
    "finally", "for", "from", "global", "if", "import", "in", "is",
    "lambda", "nonlocal", "not", "or", "pass", "raise", "return", "try",
    "while", "with", "yield",
  ]);
  const builtinSet = new Set([
    "print", "len", "range", "int", "str", "float", "list", "dict", "set",
    "tuple", "bool", "type", "isinstance", "hasattr", "getattr", "setattr",
    "open", "enumerate", "zip", "map", "filter", "sorted", "reversed",
    "any", "all", "min", "max", "sum", "abs", "round", "input", "super",
    "staticmethod", "classmethod", "property",
  ]);
  let inMultiLine = false;
  let multiDelim = "";
  for (let i = 0; i < lines.length; i++) {
    let line = lines[i];
    let highlighted = "";
    let pos = 0;
    if (inMultiLine) {
      const endIdx = line.indexOf(multiDelim);
      if (endIdx === -1) {
        highlighted += '<span class="py-str">' + line + "</span>";
        pos = line.length;
      } else {
        const end = endIdx + multiDelim.length;
        highlighted += '<span class="py-str">' + line.substring(0, end) + "</span>";
        pos = end;
        inMultiLine = false;
      }
    }
    while (pos < line.length) {
      const ch = line[pos];
      const rest = line.substring(pos);
      // Comments
      if (ch === "#") {
        highlighted += '<span class="py-cmt">' + rest + "</span>";
        pos = line.length;
        break;
      }
      // Triple-quoted strings
      if (rest.startsWith("&quot;&quot;&quot;") || rest.startsWith("&#x27;&#x27;&#x27;")) {
        const delim = rest.startsWith("&quot;&quot;&quot;") ? "&quot;&quot;&quot;" : "&#x27;&#x27;&#x27;";
        const after = rest.substring(delim.length);
        const closeIdx = after.indexOf(delim);
        if (closeIdx === -1) {
          highlighted += '<span class="py-str">' + rest + "</span>";
          inMultiLine = true;
          multiDelim = delim;
          pos = line.length;
        } else {
          const end = delim.length + closeIdx + delim.length;
          highlighted += '<span class="py-str">' + rest.substring(0, end) + "</span>";
          pos += end;
        }
        continue;
      }
      // Single/double quoted strings (escaped entities)
      if (rest.startsWith("&quot;") || rest.startsWith("&#x27;")) {
        const delim = rest.startsWith("&quot;") ? "&quot;" : "&#x27;";
        let j = delim.length;
        let closed = false;
        while (j < rest.length) {
          if (rest.substring(j).startsWith(delim)) {
            j += delim.length;
            closed = true;
            break;
          }
          if (rest[j] === "\\") {
            j += 2;
          } else {
            j++;
          }
        }
        if (!closed) {
          j = rest.length;
        }
        highlighted += '<span class="py-str">' + rest.substring(0, j) + "</span>";
        pos += j;
        continue;
      }
      // Numbers
      if (/[0-9]/.test(ch)) {
        const numMatch = rest.match(/^(0[xXoObB])?[0-9a-fA-F._]+/);
        if (numMatch) {
          highlighted += '<span class="py-num">' + numMatch[0] + "</span>";
          pos += numMatch[0].length;
          continue;
        }
      }
      // Identifiers / keywords
      if (/[a-zA-Z_]/.test(ch)) {
        const idMatch = rest.match(/^[a-zA-Z_]\w*/);
        if (idMatch) {
          const word = idMatch[0];
          if (kwSet.has(word)) {
            highlighted += '<span class="py-kw">' + word + "</span>";
          } else if (builtinSet.has(word)) {
            highlighted += '<span class="py-bi">' + word + "</span>";
          } else if (rest.startsWith("@")) {
            highlighted += '<span class="py-dec">' + word + "</span>";
          } else {
            highlighted += word;
          }
          pos += word.length;
          continue;
        }
      }
      // Decorators
      if (ch === "@") {
        const decMatch = rest.match(/^@[a-zA-Z_]\w*/);
        if (decMatch) {
          highlighted += '<span class="py-dec">' + decMatch[0] + "</span>";
          pos += decMatch[0].length;
          continue;
        }
      }
      highlighted += ch;
      pos++;
    }
    result.push('<span class="py-line">' + highlighted + "</span>");
  }
  return result.join("");
}

function syncScriptEditorHighlight() {
  if (!(scriptEditorTextarea instanceof HTMLTextAreaElement) || !(scriptEditorHighlight instanceof HTMLElement)) {
    return;
  }
  const source = scriptEditorTextarea.value;
  scriptEditorHighlight.innerHTML = highlightPython(source);
}

function syncScriptEditorScroll() {
  if (!(scriptEditorTextarea instanceof HTMLTextAreaElement) || !(scriptEditorHighlight instanceof HTMLElement)) {
    return;
  }
  scriptEditorHighlight.scrollTop = scriptEditorTextarea.scrollTop;
  scriptEditorHighlight.scrollLeft = scriptEditorTextarea.scrollLeft;
}

function applyScriptEditorMode() {
  const isCreate = state.scriptEditorMode === "create";
  if (scriptEditorSaveButton instanceof HTMLElement) {
    scriptEditorSaveButton.textContent = isCreate ? "Create" : "Save";
  }
  if (scriptEditorDeleteButton instanceof HTMLElement) {
    scriptEditorDeleteButton.style.display = isCreate ? "none" : "";
  }
}

const SCRIPT_TEMPLATE = [
  "# krill-script-title: my-new-script",
  "# krill-script-description: A short description of what this script does",
  "# krill-script-instructions: Tell the AI when and how to use this script",
  "# krill-script-python-requirements: ",
  "",
  "import argparse",
  "import json",
  "",
  "def main():",
  "    parser = argparse.ArgumentParser()",
  "    parser.add_argument(\"--name\", default=\"world\")",
  "    args = parser.parse_args()",
  "    result = {\"message\": f\"Hello, {args.name}!\"}",
  "    print(json.dumps(result))",
  "",
  "if __name__ == \"__main__\":",
  "    main()",
  "",
].join("\n");

function openNewScriptEditor() {
  if (!(scriptEditorModal instanceof HTMLElement) || !(scriptEditorTextarea instanceof HTMLTextAreaElement)) {
    return;
  }
  state.scriptEditorTitle = "";
  state.scriptEditorMode = "create";
  if (scriptEditorTitleNode instanceof HTMLElement) {
    scriptEditorTitleNode.textContent = "New Script";
  }
  if (scriptEditorMetaNode instanceof HTMLElement) {
    scriptEditorMetaNode.textContent = "Fill in the metadata headers and write your script code below.";
  }
  scriptEditorTextarea.value = SCRIPT_TEMPLATE;
  syncScriptEditorHighlight();
  applyScriptEditorMode();

  scriptEditorModal.classList.remove("hidden");
  document.body.style.overflow = "hidden";

  scriptEditorTextarea.focus({ preventScroll: true });
  // Place cursor at end of title value for quick editing
  const titleEnd = SCRIPT_TEMPLATE.indexOf("my-new-script") + "my-new-script".length;
  scriptEditorTextarea.setSelectionRange(titleEnd, titleEnd);
}

async function openScriptEditor(title) {
  if (!(scriptEditorModal instanceof HTMLElement) || !(scriptEditorTextarea instanceof HTMLTextAreaElement)) {
    return;
  }
  state.scriptEditorTitle = title;
  state.scriptEditorMode = "edit";
  if (scriptEditorTitleNode instanceof HTMLElement) {
    scriptEditorTitleNode.textContent = "Script: " + title;
  }
  if (scriptEditorMetaNode instanceof HTMLElement) {
    scriptEditorMetaNode.textContent = "Loading...";
  }
  scriptEditorTextarea.value = "";
  syncScriptEditorHighlight();
  applyScriptEditorMode();

  scriptEditorModal.classList.remove("hidden");
  document.body.style.overflow = "hidden";

  try {
    const response = await fetch("/api/mcps/scripts/" + encodeURIComponent(title), { cache: "no-store" });
    if (!response.ok) {
      throw new Error(await buildHttpErrorDetail(response, "Failed to load script."));
    }
    const data = await response.json();
    scriptEditorTextarea.value = typeof data.source === "string" ? data.source : "";
    syncScriptEditorHighlight();
    if (scriptEditorMetaNode instanceof HTMLElement) {
      scriptEditorMetaNode.textContent = "Edit the full script source including metadata headers.";
    }
  } catch (error) {
    if (scriptEditorMetaNode instanceof HTMLElement) {
      scriptEditorMetaNode.textContent = "Error: " + error.message;
    }
  }

  if (scriptEditorCloseButton instanceof HTMLElement) {
    scriptEditorCloseButton.focus({ preventScroll: true });
  }
}

function closeScriptEditor() {
  if (!(scriptEditorModal instanceof HTMLElement)) {
    return;
  }
  scriptEditorModal.classList.add("hidden");
  document.body.style.overflow = "";
  state.scriptEditorTitle = "";
  state.scriptEditorMode = "";
}

async function refreshScriptsCatalog() {
  const listResponse = await fetch("/api/mcps/scripts", { cache: "no-store" });
  if (listResponse.ok) {
    const payload = await listResponse.json();
    state.scriptTitles = normalizeScriptTitles(payload?.titles);
    state.scripts = normalizeScriptsCatalog(payload?.scripts);
    renderMcpPanel();
  }
}

async function saveScriptEditor() {
  if (!(scriptEditorTextarea instanceof HTMLTextAreaElement)) {
    return;
  }
  const source = scriptEditorTextarea.value;
  const isCreate = state.scriptEditorMode === "create";

  try {
    if (isCreate) {
      const response = await fetch("/api/mcps/scripts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source: source }),
      });
      if (!response.ok) {
        throw new Error(await buildHttpErrorDetail(response, "Failed to create script."));
      }
      showToast("Script created.");
    } else {
      const title = state.scriptEditorTitle;
      if (!title) {
        return;
      }
      const response = await fetch("/api/mcps/scripts/" + encodeURIComponent(title), {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source: source }),
      });
      if (!response.ok) {
        throw new Error(await buildHttpErrorDetail(response, "Failed to save script."));
      }
      showToast("Script saved.");
    }
    closeScriptEditor();
    await refreshScriptsCatalog();
  } catch (error) {
    setStatus(error.message, true);
    showToast((isCreate ? "Create" : "Save") + " failed: " + error.message);
  }
}

async function deleteScriptFromEditor() {
  const title = state.scriptEditorTitle;
  if (!title) {
    return;
  }
  if (!window.confirm("Delete script \"" + title + "\"? This cannot be undone.")) {
    return;
  }
  try {
    const response = await fetch("/api/mcps/scripts/" + encodeURIComponent(title), {
      method: "DELETE",
    });
    if (!response.ok) {
      throw new Error(await buildHttpErrorDetail(response, "Failed to delete script."));
    }
    showToast("Script deleted.");
    closeScriptEditor();
    await refreshScriptsCatalog();
  } catch (error) {
    setStatus(error.message, true);
    showToast("Delete failed: " + error.message);
  }
}

// Script editor event listeners
if (scriptEditorTextarea instanceof HTMLTextAreaElement) {
  scriptEditorTextarea.addEventListener("input", syncScriptEditorHighlight);
  scriptEditorTextarea.addEventListener("scroll", syncScriptEditorScroll);
  scriptEditorTextarea.addEventListener("keydown", (event) => {
    // Tab key inserts spaces
    if (event.key === "Tab") {
      event.preventDefault();
      const start = scriptEditorTextarea.selectionStart;
      const end = scriptEditorTextarea.selectionEnd;
      scriptEditorTextarea.value =
        scriptEditorTextarea.value.substring(0, start) + "    " + scriptEditorTextarea.value.substring(end);
      scriptEditorTextarea.selectionStart = scriptEditorTextarea.selectionEnd = start + 4;
      syncScriptEditorHighlight();
    }
  });
}
if (scriptEditorSaveButton instanceof HTMLElement) {
  scriptEditorSaveButton.addEventListener("click", saveScriptEditor);
}
if (scriptEditorCancelButton instanceof HTMLElement) {
  scriptEditorCancelButton.addEventListener("click", closeScriptEditor);
}
if (scriptEditorDeleteButton instanceof HTMLElement) {
  scriptEditorDeleteButton.addEventListener("click", deleteScriptFromEditor);
}
if (scriptEditorCloseButton instanceof HTMLElement) {
  scriptEditorCloseButton.addEventListener("click", closeScriptEditor);
}
if (scriptEditorBackdrop instanceof HTMLElement) {
  scriptEditorBackdrop.addEventListener("click", closeScriptEditor);
}

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
window.addEventListener("message", (event) => {
  if (event.origin !== window.location.origin) {
    return;
  }
  const payload = event.data;
  if (!payload || typeof payload !== "object") {
    return;
  }
  if (payload.type !== "krill-whatsapp-connected") {
    return;
  }
  const stateLabel = typeof payload.state === "string" ? payload.state : "ready";
  void (async () => {
    const syncResult = await syncWhatsappContactsWithRetry();
    renderMcpPanel();
    const contactCount = Array.isArray(syncResult?.contacts) ? syncResult.contacts.length : 0;
    if (syncResult?.cacheRetained) {
      const warning = typeof syncResult.warning === "string" && syncResult.warning.trim()
        ? syncResult.warning.trim()
        : "Kept previously cached contacts.";
      setStatus(`WhatsApp connected (${stateLabel}). ${warning} Cached contacts: ${contactCount}.`, true);
    } else {
      setStatus(`WhatsApp connected (${stateLabel}). Contacts synced (${contactCount}).`);
    }
    showToast("WhatsApp connected.");
  })();
});
window.addEventListener("beforeunload", () => {
  stopSpeechRecognition(true);
  if (state.chatSyncTimerId) {
    window.clearInterval(state.chatSyncTimerId);
    state.chatSyncTimerId = null;
  }
  if (state.integrationStatusSyncTimerId) {
    window.clearInterval(state.integrationStatusSyncTimerId);
    state.integrationStatusSyncTimerId = null;
  }
  if (state.timedJobAuthAlertSyncTimerId) {
    window.clearInterval(state.timedJobAuthAlertSyncTimerId);
    state.timedJobAuthAlertSyncTimerId = null;
  }
  if (state.shortTermMemorySyncTimerId) {
    window.clearInterval(state.shortTermMemorySyncTimerId);
    state.shortTermMemorySyncTimerId = null;
  }
});
window.addEventListener("load", () => {
  applyThemeMode(state.theme);
  initializeSpeechRecognition();
  syncChatInputHeight();
  renderPendingImageAttachment();
  syncMobileDrawerUi();
  loadGatewayMeta();
});
