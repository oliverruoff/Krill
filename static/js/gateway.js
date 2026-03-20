/*
 * Gateway client entrypoint.
 *
 * All logic lives in ./gateway/ ES modules.
 * This file wires up event listeners and kicks off the application boot.
 */

import { initEventListeners } from "./gateway/event-listeners.js";
import { initBoot } from "./gateway/boot.js";

initEventListeners();
initBoot();
