import { state } from "./state.js";
import { chatThread, sendButton, chatInput, stopButton } from "./dom.js";
import { formatMessageTimestamp } from "./utils.js";
import { renderMarkdown } from "./markdown.js";
import { isChatBusy } from "./chat-runtime.js";
import { setSpeechUiState } from "./speech.js";
import { setSwitchersDisabled, setCompactButtonDisabled } from "./providers.js";
import { setHistoryControlsDisabled } from "./runtime-context.js";

const EMPTY_CHAT_GREETING = "Hi ✌️";

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

function hasVisibleConversation(chat) {
  if (!chat || !Array.isArray(chat.messages)) {
    return false;
  }

  return chat.messages.some((turn) => turn && (turn.role === "user" || turn.role === "assistant"));
}

async function renderActiveChat() {
  const { updateCurrentChatTitle, updateSystemTraceToggleLabel, getActiveChat } = await import("./chat-history.js");
  updateCurrentChatTitle();
  updateSystemTraceToggleLabel();
  const activeChat = getActiveChat();
  if (!activeChat) {
    renderEmptyChatView();
    return;
  }

  chatThread.innerHTML = "";
  if (!hasVisibleConversation(activeChat)) {
    addMessage("assistant", EMPTY_CHAT_GREETING);
  }
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

export {
  addMessage,
  normalizeToolUsage,
  getFrontendMcpLabel,
  getMcpDisplayLabel,
  renderToolUsageLine,
  renderEmptyChatView,
  renderActiveChat,
  updateComposerState,
};
