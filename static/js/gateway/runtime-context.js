import { state, RUNTIME_CONTEXT_SYSTEM_TYPE } from "./state.js";
import { createTimestamp } from "./utils.js";
import { newChatButton, chatHistoryList } from "./dom.js";

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

export {
  buildRuntimeContextSeed,
  ensureRuntimeContextSeed,
  toApiChatHistory,
  toApiCompactionHistory,
  setHistoryControlsDisabled,
};
