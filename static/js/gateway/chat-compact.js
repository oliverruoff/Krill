import { state, RUNTIME_CONTEXT_SYSTEM_TYPE } from "./state.js";
import { setStatus, createTimestamp } from "./utils.js";
import { showToast } from "./toast.js";
import { getChatRuntime, isChatBusy } from "./chat-runtime.js";

// Number of most-recent user+assistant message pairs kept verbatim after compaction
// so the model can continue an in-progress task exactly where it left off.
const COMPACTION_TAIL_SIZE = 6;

/**
 * Split chat messages into (headMessages, tailMessages) for tail-preserving compaction.
 *
 * headMessages: user/assistant messages to be summarised (all except the last COMPACTION_TAIL_SIZE).
 * tailMessages: the last COMPACTION_TAIL_SIZE user/assistant messages kept verbatim.
 *
 * Returns null when there is nothing in the head to compact (i.e. the entire
 * history would fit in the tail — no compaction benefit).
 *
 * @param {Array} messages  The full chat.messages array.
 * @returns {{ headMessages: Array, tailMessages: Array } | null}
 */
function splitCompactionHistory(messages) {
  const userAssistant = messages.filter(
    (turn) =>
      turn &&
      (turn.role === "user" || turn.role === "assistant") &&
      typeof turn.content === "string" &&
      turn.content.trim(),
  );

  if (userAssistant.length <= COMPACTION_TAIL_SIZE) {
    // Nothing to compact — the entire history fits in the tail.
    return null;
  }

  const splitIdx = userAssistant.length - COMPACTION_TAIL_SIZE;
  return {
    headMessages: userAssistant.slice(0, splitIdx),
    tailMessages: userAssistant.slice(splitIdx),
  };
}

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

    // Split history into head (to be summarised) and tail (kept verbatim).
    const split = splitCompactionHistory(chat.messages);
    if (!split) {
      // Not enough history to compact — nothing to do.
      return;
    }
    const { headMessages, tailMessages } = split;

    // Send only the head to the compaction API.
    const headForApi = headMessages.map((turn) => ({ role: turn.role, content: turn.content }));

    const response = await fetch("/api/chat/compact", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        history: headForApi,
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
      } catch (_err) {
        detail = "Compaction failed.";
      }
      throw new Error(detail);
    }

    const payload = await response.json();
    chat.memory_block = typeof payload.memory_block === "string" ? payload.memory_block : chat.memory_block;

    // Archive all head messages in chat.messages so they are hidden from the LLM
    // but remain visible in the UI (grayed out).
    const headSet = new Set(headMessages);
    for (const msg of chat.messages) {
      if (headSet.has(msg)) {
        msg.archived = true;
      }
    }

    // Find where the first tail message sits in chat.messages so we can insert
    // the compaction marker immediately before it.
    let insertPos = chat.messages.length;
    if (tailMessages.length > 0) {
      const firstTail = tailMessages[0];
      const idx = chat.messages.indexOf(firstTail);
      if (idx !== -1) {
        insertPos = idx;
      }
    }

    // Insert the compaction marker (summary bubble) before the tail messages.
    if (chat.memory_block.trim()) {
      chat.messages.splice(insertPos, 0, {
        role: "system",
        content: `Compacted memory\n\n${chat.memory_block.trim()}`,
        timestamp: createTimestamp(),
        system_type: "memory_compaction",
        archived: false,
        tool_usage: [],
        request_id: "",
        status: "",
      });
    }

    chat.updated_at = createTimestamp();

    if (state.activeChatId === chat.id) {
      const { estimateContextTokens } = await import("./providers.js");
      state.lastRequestTokens = estimateContextTokens(chat.messages, chat.memory_block);
    }
  } finally {
    state.isCompacting = false;
    const {
      setSwitchersDisabled: setSwitchersDisabledFinally,
      setCompactButtonDisabled: setCompactButtonDisabledFinally,
    } = await import("./providers.js");
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

  // Also skip if there is nothing in the head to compact (all history fits in tail).
  const split = splitCompactionHistory(chat.messages);
  if (!split) {
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
