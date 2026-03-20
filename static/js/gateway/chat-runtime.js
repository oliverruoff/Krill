/*
 * Per-chat runtime state management (processing queue, abort controllers).
 */

import { state } from "./state.js";

export function getChatRuntime(chatId) {
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

export function removeChatRuntime(chatId) {
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

export function isChatBusy(chatId) {
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

export function isAnyChatBusy() {
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
