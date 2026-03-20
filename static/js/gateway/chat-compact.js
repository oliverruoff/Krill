import { state, RUNTIME_CONTEXT_SYSTEM_TYPE } from "./state.js";
import { setStatus, createTimestamp } from "./utils.js";
import { showToast } from "./toast.js";
import { getChatRuntime, isChatBusy } from "./chat-runtime.js";

async function compactHistoryForLimit(chat, targetTokenLimit, reasonLabel) {
  if (state.isCompacting || !chat) {
    return;
  }

  state.isCompacting = true;
  const { setSwitchersDisabled, setCompactButtonDisabled } = await import("./providers.js");
  const { setHistoryControlsDisabled } = await import("./runtime-context.js");
  setSwitchersDisabled(true);
  setCompactButtonDisabled(true);
  setHistoryControlsDisabled(true);

  try {
    setStatus(`Compacting memory for ${reasonLabel}...`);
    const { toApiCompactionHistory } = await import("./runtime-context.js");
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
    const { buildRuntimeContextSeed } = await import("./runtime-context.js");
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
      const { estimateContextTokens } = await import("./providers.js");
      state.lastRequestTokens = estimateContextTokens(chat.messages, chat.memory_block);
    }
  } finally {
    state.isCompacting = false;
    const { setSwitchersDisabled: setSwitchersDisabledFinally, setCompactButtonDisabled: setCompactButtonDisabledFinally } = await import("./providers.js");
    const { setHistoryControlsDisabled: setHistoryControlsDisabledFinally } = await import("./runtime-context.js");
    setSwitchersDisabledFinally(state.isSwitching);
    setCompactButtonDisabledFinally(state.isSwitching);
    setHistoryControlsDisabledFinally(state.isSwitching);
    const { updateComposerState } = await import("./chat-render.js");
    updateComposerState();
  }
}

async function maybeAutoCompact(chat, reasonLabel, targetTokenLimit = state.modelTokenLimit) {
  if (!chat) {
    return { ok: true, compacted: false };
  }

  const { shouldCompactForLimit } = await import("./providers.js");
  if (!shouldCompactForLimit(chat.messages, chat.memory_block || "", targetTokenLimit)) {
    return { ok: true, compacted: false };
  }

  try {
    await compactHistoryForLimit(chat, targetTokenLimit, reasonLabel);
    const { renderActiveChat } = await import("./chat-render.js");
    renderActiveChat();
    const { renderChatHistory } = await import("./chat-history.js");
    renderChatHistory();
    const { syncUsedTokensToContext } = await import("./providers.js");
    syncUsedTokensToContext();
    showToast("Compaction complete. Chat context was reduced.");
    return { ok: true, compacted: true };
  } catch (error) {
    setStatus(error.message, true);
    return { ok: false, compacted: false };
  }
}

async function triggerManualCompaction() {
  if (state.isCompacting || state.isSwitching) {
    return;
  }

  const { getActiveChat } = await import("./chat-history.js");
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
    const { renderActiveChat } = await import("./chat-render.js");
    renderActiveChat();
    const { renderChatHistory } = await import("./chat-history.js");
    renderChatHistory();
    const { syncUsedTokensToContext } = await import("./providers.js");
    syncUsedTokensToContext();
    const { persistChatsToSettings } = await import("./chat-sync.js");
    await persistChatsToSettings();
    showToast("Compaction complete. Chat context was reduced.");
    setStatus("Memory compacted.");
  } catch (error) {
    setStatus(error.message, true);
  }
}

export {
  compactHistoryForLimit,
  maybeAutoCompact,
  triggerManualCompaction,
};
