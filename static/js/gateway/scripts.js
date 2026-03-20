/*
 * Script catalog helpers, editor UI, and Python syntax highlighting.
 */

import { state, SCRIPTS_DISABLED_TITLES_PARAM } from "./state.js";
import {
  scriptEditorModal,
  scriptEditorBackdrop,
  scriptEditorCloseButton,
  scriptEditorTextarea,
  scriptEditorHighlight,
  scriptEditorSaveButton,
  scriptEditorCancelButton,
  scriptEditorDeleteButton,
  scriptEditorTitleNode,
  scriptEditorMetaNode,
} from "./dom.js";
import { setStatus, buildHttpErrorDetail } from "./utils.js";
import { showToast } from "./toast.js";
import { escapeHtml } from "./markdown.js";

export function normalizeScriptTitles(value) {
  if (!Array.isArray(value)) {
    return [];
  }
  const seen = new Set();
  const titles = [];
  value.forEach((entry) => {
    const title = typeof entry === "string" ? entry.trim() : "";
    if (!title || seen.has(title)) {
      return;
    }
    seen.add(title);
    titles.push(title);
  });
  return titles;
}

export function normalizeScriptsCatalog(value) {
  if (!Array.isArray(value)) {
    return [];
  }
  const seen = new Set();
  const scripts = [];
  value.forEach((entry) => {
    if (!entry || typeof entry !== "object") {
      return;
    }
    const title = typeof entry.title === "string" ? entry.title.trim() : "";
    if (!title || seen.has(title)) {
      return;
    }
    seen.add(title);
    scripts.push({
      title: title,
      description: typeof entry.description === "string" ? entry.description : "",
      id: typeof entry.id === "string" ? entry.id : title,
    });
  });
  return scripts;
}

export async function getDisabledScriptTitlesFromConfig() {
  const { ensureMcpConfig } = await import("./mcp-handlers.js");
  const scriptsConfig = ensureMcpConfig("scripts");
  const rawValue = typeof scriptsConfig.params?.[SCRIPTS_DISABLED_TITLES_PARAM] === "string"
    ? scriptsConfig.params[SCRIPTS_DISABLED_TITLES_PARAM]
    : "";
  const trimmed = rawValue.trim();
  if (!trimmed) {
    return new Set();
  }

  try {
    const parsed = JSON.parse(trimmed);
    if (!Array.isArray(parsed)) {
      return new Set();
    }
    const disabledTitles = new Set();
    parsed.forEach((entry) => {
      const title = typeof entry === "string" ? entry.trim() : "";
      if (!title) {
        return;
      }
      disabledTitles.add(title);
    });
    return disabledTitles;
  } catch (error) {
    return new Set();
  }
}

export async function isScriptEnabledForExecution(scriptTitle) {
  const title = typeof scriptTitle === "string" ? scriptTitle.trim() : "";
  if (!title) {
    return false;
  }
  const disabledTitles = await getDisabledScriptTitlesFromConfig();
  return !disabledTitles.has(title);
}

export async function setScriptEnabledForExecution(scriptTitle, enabled) {
  const title = typeof scriptTitle === "string" ? scriptTitle.trim() : "";
  if (!title) {
    return;
  }

  const { ensureMcpConfig } = await import("./mcp-handlers.js");
  const scriptsConfig = ensureMcpConfig("scripts");
  const disabledTitles = await getDisabledScriptTitlesFromConfig();
  if (enabled) {
    disabledTitles.delete(title);
  } else {
    disabledTitles.add(title);
  }

  const availableTitles = new Set(state.scripts.map((script) => script.title));
  const persistedTitles = Array.from(disabledTitles).filter((entry) => availableTitles.has(entry));
  scriptsConfig.params[SCRIPTS_DISABLED_TITLES_PARAM] = JSON.stringify(persistedTitles);
}

export function highlightPython(source) {
  const escaped = escapeHtml(source);
  const lines = escaped.split("\n");
  const result = [];
  const kwSet = new Set([
    "False", "None", "True", "and", "as", "assert", "async", "await",
    "break", "class", "continue", "def", "del", "elif", "else", "except",
    "finally", "for", "from", "global", "if", "import", "in", "is",
    "lambda", "nonlocal", "not", "or", "pass", "raise", "return", "try",
    "while", "with", "yield",
  ]);
  const builtinSet = new Set([
    "print", "len", "range", "int", "str", "float", "list", "dict", "set",
    "tuple", "bool", "type", "isinstance", "hasattr", "getattr", "setattr",
    "open", "enumerate", "zip", "map", "filter", "sorted", "reversed",
    "any", "all", "min", "max", "sum", "abs", "round", "input", "super",
    "staticmethod", "classmethod", "property",
  ]);
  let inMultiLine = false;
  let multiDelim = "";
  for (let i = 0; i < lines.length; i++) {
    let line = lines[i];
    let highlighted = "";
    let pos = 0;
    if (inMultiLine) {
      const endIdx = line.indexOf(multiDelim);
      if (endIdx === -1) {
        highlighted += '<span class="py-str">' + line + "</span>";
        pos = line.length;
      } else {
        const end = endIdx + multiDelim.length;
        highlighted += '<span class="py-str">' + line.substring(0, end) + "</span>";
        pos = end;
        inMultiLine = false;
      }
    }
    while (pos < line.length) {
      const ch = line[pos];
      const rest = line.substring(pos);
      // Comments
      if (ch === "#") {
        highlighted += '<span class="py-cmt">' + rest + "</span>";
        pos = line.length;
        break;
      }
      // Triple-quoted strings
      if (rest.startsWith("&quot;&quot;&quot;") || rest.startsWith("&#x27;&#x27;&#x27;")) {
        const delim = rest.startsWith("&quot;&quot;&quot;") ? "&quot;&quot;&quot;" : "&#x27;&#x27;&#x27;";
        const after = rest.substring(delim.length);
        const closeIdx = after.indexOf(delim);
        if (closeIdx === -1) {
          highlighted += '<span class="py-str">' + rest + "</span>";
          inMultiLine = true;
          multiDelim = delim;
          pos = line.length;
        } else {
          const end = delim.length + closeIdx + delim.length;
          highlighted += '<span class="py-str">' + rest.substring(0, end) + "</span>";
          pos += end;
        }
        continue;
      }
      // Single/double quoted strings (escaped entities)
      if (rest.startsWith("&quot;") || rest.startsWith("&#x27;")) {
        const delim = rest.startsWith("&quot;") ? "&quot;" : "&#x27;";
        let j = delim.length;
        let closed = false;
        while (j < rest.length) {
          if (rest.substring(j).startsWith(delim)) {
            j += delim.length;
            closed = true;
            break;
          }
          if (rest[j] === "\\") {
            j += 2;
          } else {
            j++;
          }
        }
        if (!closed) {
          j = rest.length;
        }
        highlighted += '<span class="py-str">' + rest.substring(0, j) + "</span>";
        pos += j;
        continue;
      }
      // Numbers
      if (/[0-9]/.test(ch)) {
        const numMatch = rest.match(/^(0[xXoObB])?[0-9a-fA-F._]+/);
        if (numMatch) {
          highlighted += '<span class="py-num">' + numMatch[0] + "</span>";
          pos += numMatch[0].length;
          continue;
        }
      }
      // Identifiers / keywords
      if (/[a-zA-Z_]/.test(ch)) {
        const idMatch = rest.match(/^[a-zA-Z_]\w*/);
        if (idMatch) {
          const word = idMatch[0];
          if (kwSet.has(word)) {
            highlighted += '<span class="py-kw">' + word + "</span>";
          } else if (builtinSet.has(word)) {
            highlighted += '<span class="py-bi">' + word + "</span>";
          } else if (rest.startsWith("@")) {
            highlighted += '<span class="py-dec">' + word + "</span>";
          } else {
            highlighted += word;
          }
          pos += word.length;
          continue;
        }
      }
      // Decorators
      if (ch === "@") {
        const decMatch = rest.match(/^@[a-zA-Z_]\w*/);
        if (decMatch) {
          highlighted += '<span class="py-dec">' + decMatch[0] + "</span>";
          pos += decMatch[0].length;
          continue;
        }
      }
      highlighted += ch;
      pos++;
    }
    result.push('<span class="py-line">' + highlighted + "</span>");
  }
  return result.join("");
}

export function syncScriptEditorHighlight() {
  if (!(scriptEditorTextarea instanceof HTMLTextAreaElement) || !(scriptEditorHighlight instanceof HTMLElement)) {
    return;
  }
  const source = scriptEditorTextarea.value;
  scriptEditorHighlight.innerHTML = highlightPython(source);
}

export function syncScriptEditorScroll() {
  if (!(scriptEditorTextarea instanceof HTMLTextAreaElement) || !(scriptEditorHighlight instanceof HTMLElement)) {
    return;
  }
  scriptEditorHighlight.scrollTop = scriptEditorTextarea.scrollTop;
  scriptEditorHighlight.scrollLeft = scriptEditorTextarea.scrollLeft;
}

export function applyScriptEditorMode() {
  const isCreate = state.scriptEditorMode === "create";
  if (scriptEditorSaveButton instanceof HTMLElement) {
    scriptEditorSaveButton.textContent = isCreate ? "Create" : "Save";
  }
  if (scriptEditorDeleteButton instanceof HTMLElement) {
    scriptEditorDeleteButton.style.display = isCreate ? "none" : "";
  }
}

export const SCRIPT_TEMPLATE = [
  "# krill-script-title: my-new-script",
  "# krill-script-description: A short description of what this script does",
  "# krill-script-instructions: Tell the AI when and how to use this script",
  "# krill-script-python-requirements: ",
  "",
  "import argparse",
  "import json",
  "",
  "def main():",
  "    parser = argparse.ArgumentParser()",
  "    parser.add_argument(\"--name\", default=\"world\")",
  "    args = parser.parse_args()",
  "    result = {\"message\": f\"Hello, {args.name}!\"}",
  "    print(json.dumps(result))",
  "",
  "if __name__ == \"__main__\":",
  "    main()",
  "",
].join("\n");

export function openNewScriptEditor() {
  if (!(scriptEditorModal instanceof HTMLElement) || !(scriptEditorTextarea instanceof HTMLTextAreaElement)) {
    return;
  }
  state.scriptEditorTitle = "";
  state.scriptEditorMode = "create";
  if (scriptEditorTitleNode instanceof HTMLElement) {
    scriptEditorTitleNode.textContent = "New Script";
  }
  if (scriptEditorMetaNode instanceof HTMLElement) {
    scriptEditorMetaNode.textContent = "Fill in the metadata headers and write your script code below.";
  }
  scriptEditorTextarea.value = SCRIPT_TEMPLATE;
  syncScriptEditorHighlight();
  applyScriptEditorMode();

  scriptEditorModal.classList.remove("hidden");
  document.body.style.overflow = "hidden";

  scriptEditorTextarea.focus({ preventScroll: true });
  // Place cursor at end of title value for quick editing
  const titleEnd = SCRIPT_TEMPLATE.indexOf("my-new-script") + "my-new-script".length;
  scriptEditorTextarea.setSelectionRange(titleEnd, titleEnd);
}

export async function openScriptEditor(title) {
  if (!(scriptEditorModal instanceof HTMLElement) || !(scriptEditorTextarea instanceof HTMLTextAreaElement)) {
    return;
  }
  state.scriptEditorTitle = title;
  state.scriptEditorMode = "edit";
  if (scriptEditorTitleNode instanceof HTMLElement) {
    scriptEditorTitleNode.textContent = "Script: " + title;
  }
  if (scriptEditorMetaNode instanceof HTMLElement) {
    scriptEditorMetaNode.textContent = "Loading...";
  }
  scriptEditorTextarea.value = "";
  syncScriptEditorHighlight();
  applyScriptEditorMode();

  scriptEditorModal.classList.remove("hidden");
  document.body.style.overflow = "hidden";

  try {
    const response = await fetch("/api/mcps/scripts/" + encodeURIComponent(title), { cache: "no-store" });
    if (!response.ok) {
      throw new Error(await buildHttpErrorDetail(response, "Failed to load script."));
    }
    const data = await response.json();
    scriptEditorTextarea.value = typeof data.source === "string" ? data.source : "";
    syncScriptEditorHighlight();
    if (scriptEditorMetaNode instanceof HTMLElement) {
      scriptEditorMetaNode.textContent = "Edit the full script source including metadata headers.";
    }
  } catch (error) {
    if (scriptEditorMetaNode instanceof HTMLElement) {
      scriptEditorMetaNode.textContent = "Error: " + error.message;
    }
  }

  if (scriptEditorCloseButton instanceof HTMLElement) {
    scriptEditorCloseButton.focus({ preventScroll: true });
  }
}

export function closeScriptEditor() {
  if (!(scriptEditorModal instanceof HTMLElement)) {
    return;
  }
  scriptEditorModal.classList.add("hidden");
  document.body.style.overflow = "";
  state.scriptEditorTitle = "";
  state.scriptEditorMode = "";
}

export async function refreshScriptsCatalog() {
  const listResponse = await fetch("/api/mcps/scripts", { cache: "no-store" });
  if (listResponse.ok) {
    const payload = await listResponse.json();
    state.scriptTitles = normalizeScriptTitles(payload?.titles);
    state.scripts = normalizeScriptsCatalog(payload?.scripts);
    const { renderMcpPanel } = await import("./mcp-panel.js");
    renderMcpPanel();
  }
}

export async function saveScriptEditor() {
  if (!(scriptEditorTextarea instanceof HTMLTextAreaElement)) {
    return;
  }
  const source = scriptEditorTextarea.value;
  const isCreate = state.scriptEditorMode === "create";

  try {
    if (isCreate) {
      const response = await fetch("/api/mcps/scripts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source: source }),
      });
      if (!response.ok) {
        throw new Error(await buildHttpErrorDetail(response, "Failed to create script."));
      }
      showToast("Script created.");
    } else {
      const title = state.scriptEditorTitle;
      if (!title) {
        return;
      }
      const response = await fetch("/api/mcps/scripts/" + encodeURIComponent(title), {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source: source }),
      });
      if (!response.ok) {
        throw new Error(await buildHttpErrorDetail(response, "Failed to save script."));
      }
      showToast("Script saved.");
    }
    closeScriptEditor();
    await refreshScriptsCatalog();
  } catch (error) {
    setStatus(error.message, true);
    showToast((isCreate ? "Create" : "Save") + " failed: " + error.message);
  }
}

export async function deleteScriptFromEditor() {
  const title = state.scriptEditorTitle;
  if (!title) {
    return;
  }
  if (!window.confirm("Delete script \"" + title + "\"? This cannot be undone.")) {
    return;
  }
  try {
    const response = await fetch("/api/mcps/scripts/" + encodeURIComponent(title), {
      method: "DELETE",
    });
    if (!response.ok) {
      throw new Error(await buildHttpErrorDetail(response, "Failed to delete script."));
    }
    showToast("Script deleted.");
    closeScriptEditor();
    await refreshScriptsCatalog();
  } catch (error) {
    setStatus(error.message, true);
    showToast("Delete failed: " + error.message);
  }
}

// Script editor event listeners
if (scriptEditorTextarea instanceof HTMLTextAreaElement) {
  scriptEditorTextarea.addEventListener("input", syncScriptEditorHighlight);
  scriptEditorTextarea.addEventListener("scroll", syncScriptEditorScroll);
  scriptEditorTextarea.addEventListener("keydown", (event) => {
    // Tab key inserts spaces
    if (event.key === "Tab") {
      event.preventDefault();
      const start = scriptEditorTextarea.selectionStart;
      const end = scriptEditorTextarea.selectionEnd;
      scriptEditorTextarea.value =
        scriptEditorTextarea.value.substring(0, start) + "    " + scriptEditorTextarea.value.substring(end);
      scriptEditorTextarea.selectionStart = scriptEditorTextarea.selectionEnd = start + 4;
      syncScriptEditorHighlight();
    }
  });
}
if (scriptEditorSaveButton instanceof HTMLElement) {
  scriptEditorSaveButton.addEventListener("click", saveScriptEditor);
}
if (scriptEditorCancelButton instanceof HTMLElement) {
  scriptEditorCancelButton.addEventListener("click", closeScriptEditor);
}
if (scriptEditorDeleteButton instanceof HTMLElement) {
  scriptEditorDeleteButton.addEventListener("click", deleteScriptFromEditor);
}
if (scriptEditorCloseButton instanceof HTMLElement) {
  scriptEditorCloseButton.addEventListener("click", closeScriptEditor);
}
if (scriptEditorBackdrop instanceof HTMLElement) {
  scriptEditorBackdrop.addEventListener("click", closeScriptEditor);
}
