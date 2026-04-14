/*
 * Shared mutable state singleton and app-level constants.
 */

import { normalizeThemeMode } from "./theme.js";

export const CHAT_TITLE_MAX_LENGTH = 24;
export const EDITABLE_CHAT_TITLE_MAX_LENGTH = 24;
export const CHAT_SYNC_INTERVAL_MS = 5000;
export const INTEGRATION_STATUS_SYNC_INTERVAL_MS = 8000;
export const RUNTIME_CONTEXT_SYSTEM_TYPE = "runtime_context_seed";
export const MEMORY_MAX_LENGTH = 1000000;
export const CHAT_HISTORY_PAGE_SIZE = 15;
export const CHAT_HISTORY_SCROLL_LOAD_THRESHOLD_PX = 120;
export const WHATSAPP_CONTACTS_CACHE_PARAM = "contacts_cache_json";
export const SCRIPTS_DISABLED_TITLES_PARAM = "disabled_script_titles";

export const MOBILE_DRAWER_BREAKPOINT = 900;
export const MOBILE_SWIPE_EDGE_PX = 24;
export const MOBILE_SWIPE_OPEN_THRESHOLD = 70;
export const MOBILE_SWIPE_CLOSE_THRESHOLD = 52;
export const CHAT_INPUT_MAX_HEIGHT_PX = 160;

export const state = {
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
  bootLoading: true,
  bootError: "",
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
