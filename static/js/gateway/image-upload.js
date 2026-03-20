/*
 * Image upload / attachment handling.
 */

import { state } from "./state.js";
import { imageUploadInput, imageAttachmentPreview } from "./dom.js";
import { setStatus } from "./utils.js";

export function clearPendingImageAttachment() {
  state.pendingImageAttachment = null;
  if (imageUploadInput instanceof HTMLInputElement) {
    imageUploadInput.value = "";
  }
  renderPendingImageAttachment();
}

export function clonePendingImageAttachment(pendingImage) {
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

export function renderPendingImageAttachment() {
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

export function parseDataUrl(dataUrl) {
  const raw = String(dataUrl || "");
  const match = raw.match(/^data:([^;]+);base64,(.+)$/);
  if (!match) {
    return null;
  }
  return { mimeType: match[1], contentBase64: match[2] };
}

export async function handleImageUploadInputChange(event) {
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
