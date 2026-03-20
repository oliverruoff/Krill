/*
 * Speech recognition / voice dictation.
 */

import { state } from "./state.js";
import { chatInput, micButton } from "./dom.js";
import { setStatus, syncChatInputHeight } from "./utils.js";

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

export function setSpeechUiState() {
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

export function stopSpeechRecognition(silent = false) {
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

export function startSpeechRecognition() {
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

export function toggleSpeechRecognition() {
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

export function initializeSpeechRecognition() {
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
