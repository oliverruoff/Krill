/*
 * Change password modal: open, close, form handling, and submission.
 */

import { state } from "./state.js";
import {
  changePasswordModal,
  changePasswordForm,
  changePasswordOldInput,
  changePasswordNewInput,
  changePasswordConfirmInput,
  changePasswordSubmitButton,
  memoryModal,
  brainModal,
  timedJobsModal,
  shortTermMemoryModal,
  tokenUsageModal,
} from "./dom.js";
import {
  setStatus,
  normalizeErrorMessage,
  buildHttpErrorDetail,
} from "./utils.js";
import { showToast } from "./toast.js";

export function resetChangePasswordForm() {
  if (changePasswordForm instanceof HTMLFormElement) {
    changePasswordForm.reset();
  }
}

export function setChangePasswordSubmitting(submitting) {
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

export function setChangePasswordFormEnabled(enabled) {
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

export function openChangePasswordModal() {
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

export function closeChangePasswordModal() {
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

export async function handleChangePasswordSubmit(event) {
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
