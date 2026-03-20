/*
 * Mobile drawer / swipe gesture system.
 */

import { state, MOBILE_DRAWER_BREAKPOINT, MOBILE_SWIPE_EDGE_PX, MOBILE_SWIPE_OPEN_THRESHOLD, MOBILE_SWIPE_CLOSE_THRESHOLD } from "./state.js";
import {
  gatewayShell, gatewayTopbar, chatHistoryPanel, mcpSidePanel,
  mobileDrawerBackdrop, mobileLeftDrawerHandle, mobileRightDrawerHandle,
  mobileSettingsPopover, mobileSettingsMenuButton,
  memoryModal, brainModal, shortTermMemoryModal, timedJobsModal,
  tokenUsageModal, changePasswordModal,
} from "./dom.js";

export function isMobileDrawerMode() {
  return window.matchMedia(`(max-width: ${MOBILE_DRAWER_BREAKPOINT}px)`).matches;
}

export function isAnyModalOpen() {
  const memoryOpen = memoryModal instanceof HTMLElement && !memoryModal.classList.contains("hidden");
  const brainOpen = brainModal instanceof HTMLElement && !brainModal.classList.contains("hidden");
  const shortTermOpen = shortTermMemoryModal instanceof HTMLElement && !shortTermMemoryModal.classList.contains("hidden");
  const timedJobsOpen = timedJobsModal instanceof HTMLElement && !timedJobsModal.classList.contains("hidden");
  const tokenUsageOpen = tokenUsageModal instanceof HTMLElement && !tokenUsageModal.classList.contains("hidden");
  const changePasswordOpen = changePasswordModal instanceof HTMLElement && !changePasswordModal.classList.contains("hidden");
  return memoryOpen || brainOpen || shortTermOpen || timedJobsOpen || tokenUsageOpen || changePasswordOpen;
}

export function syncMobileDrawerUi() {
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

export function toggleMobileSettingsMenu(forceOpen) {
  if (!(mobileSettingsPopover instanceof HTMLElement) || !(mobileSettingsMenuButton instanceof HTMLButtonElement)) {
    return;
  }

  const shouldOpen = typeof forceOpen === "boolean" ? forceOpen : mobileSettingsPopover.classList.contains("hidden");
  mobileSettingsPopover.classList.toggle("hidden", !shouldOpen);
  mobileSettingsMenuButton.setAttribute("aria-expanded", shouldOpen ? "true" : "false");
}

export function closeMobileDrawers() {
  toggleMobileSettingsMenu(false);
  if (!state.mobileLeftDrawerOpen && !state.mobileRightDrawerOpen) {
    return;
  }

  state.mobileLeftDrawerOpen = false;
  state.mobileRightDrawerOpen = false;
  syncMobileDrawerUi();
}

export function openMobileLeftDrawer() {
  if (!isMobileDrawerMode()) {
    return;
  }
  toggleMobileSettingsMenu(false);
  state.mobileLeftDrawerOpen = true;
  state.mobileRightDrawerOpen = false;
  syncMobileDrawerUi();
}

export function openMobileRightDrawer() {
  if (!isMobileDrawerMode()) {
    return;
  }
  toggleMobileSettingsMenu(false);
  state.mobileRightDrawerOpen = true;
  state.mobileLeftDrawerOpen = false;
  syncMobileDrawerUi();
}

export function toggleMobileLeftDrawer() {
  if (!isMobileDrawerMode()) {
    return;
  }

  if (state.mobileLeftDrawerOpen) {
    closeMobileDrawers();
    return;
  }

  openMobileLeftDrawer();
}

export function toggleMobileRightDrawer() {
  if (!isMobileDrawerMode()) {
    return;
  }

  if (state.mobileRightDrawerOpen) {
    closeMobileDrawers();
    return;
  }

  openMobileRightDrawer();
}

export function handleMobileSwipeStart(event) {
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

export function handleMobileSwipeMove(event) {
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

export function handleMobileSwipeEnd() {
  state.mobileTouchGesture = null;
}
