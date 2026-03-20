/*
 * MCP / integration config panel rendering.
 */

import { state } from "./state.js";
import { mcpList, integrationList } from "./dom.js";
import { getFrontendMcpLabel, isConfigExpanded, parseMultiselectParam, parseBooleanConfigParam, getMcpConfig, getIntegrationConfig } from "./mcp-handlers.js";
import { getGoogleOauthStatusLabel, getGoogleSetupGuideItems } from "./google-oauth.js";

function renderConfigPanel(container, items, getConfig, options) {
  if (!(container instanceof HTMLElement)) {
    return;
  }

  container.innerHTML = "";
  if (!Array.isArray(items) || items.length === 0) {
    const emptyNode = document.createElement("p");
    emptyNode.className = "chat-history-empty";
    emptyNode.textContent = options.emptyLabel;
    container.appendChild(emptyNode);
    return;
  }

  items.forEach((item) => {
    const card = document.createElement("div");
    card.className = "mcp-card";
    card.dataset.configKind = options.kind;
    card.dataset.configId = item.id;

    const config = getConfig(item.id);

    const titleRow = document.createElement("div");
    titleRow.className = "mcp-title-row";

    const titleMain = document.createElement("div");
    titleMain.className = "mcp-title-main";
    titleMain.dataset.action = "expand";
    titleMain.dataset.configKind = options.kind;
    titleMain.dataset.configId = item.id;

    const title = document.createElement("p");
    title.className = "mcp-title";
    title.textContent = options.kind === "mcp"
      ? getFrontendMcpLabel(item.id, item.label)
      : item.label;

    titleMain.appendChild(title);

    const titleControls = document.createElement("div");
    titleControls.className = "mcp-title-controls";

    const toggleLabel = document.createElement("label");
    toggleLabel.className = "mcp-toggle";

    const toggleInput = document.createElement("input");
    toggleInput.type = "checkbox";
    toggleInput.checked = Boolean(config.enabled);
    toggleInput.dataset.action = "toggle";
    toggleInput.dataset.configKind = options.kind;
    toggleInput.dataset.configId = item.id;

    const toggleText = document.createElement("span");
    toggleText.textContent = "Enabled";

    toggleLabel.appendChild(toggleInput);
    toggleLabel.appendChild(toggleText);

    const expanded = isConfigExpanded(options.kind, item.id);
    const expandButton = document.createElement("button");
    expandButton.type = "button";
    expandButton.className = "mcp-expand-btn";
    expandButton.textContent = expanded ? "\u25B4" : "\u25BE";
    expandButton.setAttribute("aria-label", expanded ? "Collapse" : "Expand");
    expandButton.title = expanded ? "Collapse" : "Expand";
    expandButton.dataset.action = "expand";
    expandButton.dataset.configKind = options.kind;
    expandButton.dataset.configId = item.id;

    titleControls.appendChild(toggleLabel);
    titleControls.appendChild(expandButton);

    titleRow.appendChild(titleMain);
    titleRow.appendChild(titleControls);

    const cardBody = document.createElement("div");
    cardBody.className = "mcp-card-body";
    cardBody.classList.toggle("hidden", !expanded);

    const description = document.createElement("p");
    description.className = "mcp-description";
    description.textContent = typeof item.description === "string" ? item.description : "";

    card.appendChild(titleRow);
    cardBody.appendChild(description);

    const fields = Array.isArray(item.config_fields) ? item.config_fields : [];
    fields.forEach((field) => {
      const fieldId = typeof field.id === "string" ? field.id : "";
      if (!fieldId) {
        return;
      }

      let activeField = field;
      if (options.kind === "mcp" && item.id === "whatsapp" && (fieldId === "allowed_numbers_send" || fieldId === "allowed_numbers_receive")) {
        const contactOptions = Array.isArray(state.whatsappContacts)
          ? state.whatsappContacts.map((entry) => ({
            value: String(entry.number || ""),
            label: `${String(entry.name || "").trim() || String(entry.number || "")} (${String(entry.number || "")})`,
          })).filter((entry) => entry.value)
          : [];
        activeField = {
          ...field,
          type: "multiselect",
          options: contactOptions,
          description: contactOptions.length > 0
            ? "Select allowlisted WhatsApp contacts."
            : "No contacts loaded yet. Connect WhatsApp, then click Resync or Verify.",
        };
      }

      const fieldWrapper = document.createElement("div");
      fieldWrapper.className = "mcp-field";

      const fieldLabel = document.createElement("label");
      fieldLabel.textContent = activeField.label || fieldId;
      fieldLabel.setAttribute("for", `${options.kind}-${item.id}-${fieldId}`);

      let fieldInput;
      if (activeField.type === "select") {
        const selectNode = document.createElement("select");
        const optionsList = Array.isArray(activeField.options) ? activeField.options : [];
        optionsList.forEach((optionItem) => {
          const optionValue = typeof optionItem?.value === "string" ? optionItem.value : "";
          if (!optionValue) {
            return;
          }
          const optionLabel = typeof optionItem?.label === "string" && optionItem.label
            ? optionItem.label
            : optionValue;
          const optionNode = document.createElement("option");
          optionNode.value = optionValue;
          optionNode.textContent = optionLabel;
          selectNode.appendChild(optionNode);
        });
        const storedValue = typeof config.params?.[fieldId] === "string" ? config.params[fieldId] : "";
        if (storedValue && Array.from(selectNode.options).some((optionNode) => optionNode.value === storedValue)) {
          selectNode.value = storedValue;
        } else if (selectNode.options.length > 0) {
          selectNode.value = selectNode.options[0].value;
          config.params[fieldId] = selectNode.value;
        }
        fieldInput = selectNode;
      } else if (activeField.type === "multiselect") {
        const fieldsetNode = document.createElement("div");
        fieldsetNode.className = "mcp-multiselect";
        fieldsetNode.dataset.action = "param-multiselect";
        fieldsetNode.dataset.configKind = options.kind;
        fieldsetNode.dataset.configId = item.id;
        fieldsetNode.dataset.fieldId = fieldId;

        const optionsList = Array.isArray(activeField.options) ? activeField.options : [];
        const storedValues = parseMultiselectParam(config.params?.[fieldId]);
        const selectedSet = new Set(storedValues);
        const isWhatsappAllowedNumbers = options.kind === "mcp" && item.id === "whatsapp" && (fieldId === "allowed_numbers_send" || fieldId === "allowed_numbers_receive");
        let contactListNode = fieldsetNode;
        const existingOptionValues = new Set(
          optionsList
            .map((optionItem) => (typeof optionItem?.value === "string" ? optionItem.value : ""))
            .filter((value) => value),
        );
        const renderOptions = [...optionsList];
        if (isWhatsappAllowedNumbers) {
          storedValues.forEach((value) => {
            if (!value || existingOptionValues.has(value)) {
              return;
            }
            existingOptionValues.add(value);
            renderOptions.push({ value, label: `${value} (saved)` });
          });
        }

        if (isWhatsappAllowedNumbers) {
          const filterInput = document.createElement("input");
          filterInput.type = "search";
          filterInput.className = "mcp-contact-filter";
          filterInput.placeholder = "Filter contacts";
          filterInput.autocomplete = "off";
          filterInput.spellcheck = false;

          const selectedOnlyToggleLabel = document.createElement("label");
          selectedOnlyToggleLabel.className = "mcp-toggle";

          const selectedOnlyToggleInput = document.createElement("input");
          selectedOnlyToggleInput.type = "checkbox";
          selectedOnlyToggleInput.checked = Boolean(state[`whatsappAllowlistOnlySelected_${fieldId}`]);

          const selectedOnlyToggleText = document.createElement("span");
          selectedOnlyToggleText.textContent = "Only show allow list contacts";

          const selectedOnlyCount = document.createElement("span");
          selectedOnlyCount.textContent = "(0)";

          contactListNode = document.createElement("div");
          contactListNode.className = "mcp-multiselect-list";

          const updateSelectedOnlyCount = () => {
            const selectedCount = contactListNode.querySelectorAll("input[type='checkbox'][data-multiselect-value]:checked").length;
            selectedOnlyCount.textContent = `(${selectedCount})`;
          };

          const applyContactFilter = () => {
            const query = filterInput.value.trim().toLowerCase();
            const onlySelected = selectedOnlyToggleInput.checked;
            const rows = contactListNode.querySelectorAll(".mcp-multiselect-option");
            rows.forEach((rowNode) => {
              if (!(rowNode instanceof HTMLElement)) {
                return;
              }
              const haystack = String(rowNode.dataset.searchText || "").toLowerCase();
              const matchesQuery = !query || haystack.includes(query);
              if (!matchesQuery) {
                rowNode.classList.add("hidden");
                return;
              }

              if (onlySelected) {
                const rowInput = rowNode.querySelector("input[type='checkbox'][data-multiselect-value]");
                const isSelected = rowInput instanceof HTMLInputElement && rowInput.checked;
                rowNode.classList.toggle("hidden", !isSelected);
                return;
              }

              rowNode.classList.remove("hidden");
            });
            updateSelectedOnlyCount();
          };

          filterInput.addEventListener("input", applyContactFilter);
          selectedOnlyToggleInput.addEventListener("change", () => {
            state[`whatsappAllowlistOnlySelected_${fieldId}`] = selectedOnlyToggleInput.checked;
            applyContactFilter();
          });

          selectedOnlyToggleLabel.appendChild(selectedOnlyToggleInput);
          selectedOnlyToggleLabel.appendChild(selectedOnlyToggleText);
          selectedOnlyToggleLabel.appendChild(selectedOnlyCount);

          fieldsetNode.appendChild(filterInput);
          fieldsetNode.appendChild(selectedOnlyToggleLabel);
          fieldsetNode.appendChild(contactListNode);

          fieldsetNode.dataset.whatsappFilterHooked = "true";
          fieldsetNode._applyContactFilter = applyContactFilter;
        }

        renderOptions.forEach((optionItem) => {
          const optionValue = typeof optionItem?.value === "string" ? optionItem.value : "";
          if (!optionValue) {
            return;
          }

          const optionLabel = typeof optionItem?.label === "string" && optionItem.label
            ? optionItem.label
            : optionValue;
          const optionDisabled = Boolean(optionItem?.disabled);

          const optionRow = document.createElement("label");
          optionRow.className = "mcp-toggle";
          if (isWhatsappAllowedNumbers) {
            optionRow.classList.add("mcp-multiselect-option");
            optionRow.dataset.searchText = `${optionLabel} ${optionValue}`.trim();
          }

          const optionInput = document.createElement("input");
          optionInput.type = "checkbox";
          optionInput.checked = selectedSet.has(optionValue) || optionDisabled;
          optionInput.disabled = optionDisabled;
          optionInput.dataset.action = "param-multiselect";
          optionInput.dataset.configKind = options.kind;
          optionInput.dataset.configId = item.id;
          optionInput.dataset.fieldId = fieldId;
          optionInput.dataset.multiselectValue = optionValue;

          if (isWhatsappAllowedNumbers && typeof fieldsetNode._applyContactFilter === "function") {
            optionInput.addEventListener("change", () => {
              fieldsetNode._applyContactFilter();
            });
          }

          const optionText = document.createElement("span");
          optionText.textContent = optionLabel;

          optionRow.appendChild(optionInput);
          optionRow.appendChild(optionText);
          contactListNode.appendChild(optionRow);
        });

        if (isWhatsappAllowedNumbers && typeof fieldsetNode._applyContactFilter === "function") {
          fieldsetNode._applyContactFilter();
        }

        fieldInput = fieldsetNode;
      } else if (activeField.type === "checkbox") {
        const checkboxNode = document.createElement("input");
        checkboxNode.type = "checkbox";
        checkboxNode.checked = parseBooleanConfigParam(config.params?.[fieldId]);
        fieldInput = checkboxNode;
      } else if (activeField.type === "textarea") {
        const textNode = document.createElement("textarea");
        textNode.rows = 4;
        textNode.value = typeof config.params?.[fieldId] === "string" ? config.params[fieldId] : "";
        textNode.placeholder = typeof activeField.placeholder === "string" ? activeField.placeholder : "";
        fieldInput = textNode;
       } else {
         const inputNode = document.createElement("input");
         inputNode.type = activeField.type === "password" ? "password" : "text";
         // Suppress password managers and browser autofill for ALL config inputs
         // (not just password types) to prevent unwanted credential-save prompts
         inputNode.autocomplete = activeField.type === "password" ? "new-password" : "off";
         inputNode.name = `krill-ignore-${options.kind}-${item.id}-${fieldId}`;
         inputNode.setAttribute("autocapitalize", "off");
         inputNode.setAttribute("autocorrect", "off");
         inputNode.spellcheck = false;
         inputNode.setAttribute("data-lpignore", "true");
         inputNode.setAttribute("data-1p-ignore", "true");
         inputNode.setAttribute("data-form-type", "other");
         inputNode.value = typeof config.params?.[fieldId] === "string" ? config.params[fieldId] : "";
         inputNode.placeholder = typeof activeField.placeholder === "string" ? activeField.placeholder : "";
         fieldInput = inputNode;
       }

      fieldInput.id = `${options.kind}-${item.id}-${fieldId}`;
      fieldInput.dataset.action = "param";
      fieldInput.dataset.configKind = options.kind;
      fieldInput.dataset.configId = item.id;
      fieldInput.dataset.fieldId = fieldId;

      fieldWrapper.appendChild(fieldLabel);
      fieldWrapper.appendChild(fieldInput);
      if (typeof activeField.description === "string" && activeField.description.trim()) {
        const helpText = document.createElement("small");
        helpText.className = "mcp-description";
        helpText.textContent = activeField.description.trim();
        fieldWrapper.appendChild(helpText);
      }
      cardBody.appendChild(fieldWrapper);
    });

    const actions = document.createElement("div");
    actions.className = "mcp-card-actions";

    if (options.kind === "mcp" && item.id === "git_ops") {
      const sshKeyButton = document.createElement("button");
      sshKeyButton.type = "button";
      sshKeyButton.className = "mcp-link-btn";
      sshKeyButton.textContent = "SSH key";
      sshKeyButton.dataset.action = "ssh-key";
      sshKeyButton.dataset.configKind = options.kind;
      sshKeyButton.dataset.configId = item.id;

      const verifyButton = document.createElement("button");
      verifyButton.type = "button";
      verifyButton.className = "mcp-link-btn";
      verifyButton.textContent = "Verify";
      verifyButton.dataset.action = "verify-ssh";
      verifyButton.dataset.configKind = options.kind;
      verifyButton.dataset.configId = item.id;

      actions.appendChild(sshKeyButton);
      actions.appendChild(verifyButton);
      cardBody.appendChild(actions);
    } else if (options.kind === "mcp" && item.id === "google_services") {
      const guideNode = document.createElement("div");
      guideNode.className = "mcp-guide";

      const guideHeader = document.createElement("div");
      guideHeader.className = "mcp-guide-header";
      guideHeader.dataset.action = "google-guide-toggle";
      guideHeader.dataset.configKind = options.kind;
      guideHeader.dataset.configId = item.id;

      const guideTitle = document.createElement("p");
      guideTitle.className = "mcp-guide-title";
      guideTitle.textContent = "Google setup";

      const guideToggle = document.createElement("button");
      guideToggle.type = "button";
      guideToggle.className = "mcp-expand-btn";
      guideToggle.textContent = state.googleGuideExpanded ? "\u25B4" : "\u25BE";
      guideToggle.setAttribute("aria-label", state.googleGuideExpanded ? "Collapse Google setup" : "Expand Google setup");
      guideToggle.title = state.googleGuideExpanded ? "Collapse" : "Expand";
      guideToggle.dataset.action = "google-guide-toggle";
      guideToggle.dataset.configKind = options.kind;
      guideToggle.dataset.configId = item.id;

      guideHeader.appendChild(guideTitle);
      guideHeader.appendChild(guideToggle);
      guideNode.appendChild(guideHeader);

      const consoleLink = document.createElement("a");
      consoleLink.className = "mcp-guide-link";
      consoleLink.href = "https://console.cloud.google.com/apis/credentials";
      consoleLink.target = "_blank";
      consoleLink.rel = "noopener noreferrer";
      consoleLink.textContent = "Open Google Cloud Console";

      const apiLibraryLink = document.createElement("a");
      apiLibraryLink.className = "mcp-guide-link";
      apiLibraryLink.href = "https://console.cloud.google.com/apis/library";
      apiLibraryLink.target = "_blank";
      apiLibraryLink.rel = "noopener noreferrer";
      apiLibraryLink.textContent = "Open API Library (enable Gmail + Calendar + Drive APIs)";

      const guideBody = document.createElement("div");
      guideBody.className = "mcp-guide-body";
      guideBody.classList.toggle("hidden", !state.googleGuideExpanded);

      const guideList = document.createElement("ol");
      guideList.className = "mcp-guide-list";
      getGoogleSetupGuideItems().forEach((itemText) => {
        const li = document.createElement("li");
        li.textContent = itemText;
        guideList.appendChild(li);
      });

      guideBody.appendChild(consoleLink);
      guideBody.appendChild(apiLibraryLink);
      guideBody.appendChild(guideList);
      guideNode.appendChild(guideBody);
      cardBody.appendChild(guideNode);

      const statusNode = document.createElement("p");
      statusNode.className = "mcp-description";
      statusNode.textContent = getGoogleOauthStatusLabel();
      cardBody.appendChild(statusNode);

      if (config.params.access_mode !== "read_write" && config.params.access_mode !== "read_only") {
        config.params.access_mode = "read_only";
      }

      const writeAccessLabel = document.createElement("label");
      writeAccessLabel.className = "mcp-toggle";

      const writeAccessInput = document.createElement("input");
      writeAccessInput.type = "checkbox";
      writeAccessInput.checked = config.params.access_mode === "read_write";
      writeAccessInput.dataset.action = "google-write-access";
      writeAccessInput.dataset.configKind = options.kind;
      writeAccessInput.dataset.configId = item.id;

      const writeAccessText = document.createElement("span");
      writeAccessText.textContent = "write access (Mail, Calendar & Drive)";

      writeAccessLabel.appendChild(writeAccessInput);
      writeAccessLabel.appendChild(writeAccessText);
      cardBody.appendChild(writeAccessLabel);

      const loginButton = document.createElement("button");
      loginButton.type = "button";
      loginButton.className = "mcp-link-btn";
      loginButton.textContent = (Boolean(state.googleOauthStatus?.connected) || Boolean(state.googleOauthStatus?.needs_relogin))
        ? "Relogin"
        : "Login Google";
      loginButton.dataset.action = "google-login";
      loginButton.dataset.configKind = options.kind;
      loginButton.dataset.configId = item.id;

      const verifyButton = document.createElement("button");
      verifyButton.type = "button";
      verifyButton.className = "mcp-link-btn";
      verifyButton.textContent = "Verify";
      verifyButton.dataset.action = "verify";
      verifyButton.dataset.configKind = options.kind;
      verifyButton.dataset.configId = item.id;

      actions.appendChild(loginButton);
      actions.appendChild(verifyButton);
      cardBody.appendChild(actions);
    } else if (options.kind === "mcp" && item.id === "scripts") {
      const scriptsBox = document.createElement("div");
      scriptsBox.className = "mcp-guide";

      const scriptsTitle = document.createElement("p");
      scriptsTitle.className = "mcp-guide-title";
      scriptsTitle.textContent = `Loaded scripts (${state.scripts.length})`;
      scriptsBox.appendChild(scriptsTitle);

      if (state.scripts.length === 0) {
        const emptyNode = document.createElement("p");
        emptyNode.className = "mcp-description";
        emptyNode.textContent = "No scripts loaded yet.";
        scriptsBox.appendChild(emptyNode);
      } else {
        const scriptsList = document.createElement("ul");
        scriptsList.className = "mcp-scripts-list";
        state.scripts.forEach((scriptItem) => {
          const scriptNode = document.createElement("li");
          scriptNode.className = "mcp-script-item";

          const enabledToggleLabel = document.createElement("label");
          enabledToggleLabel.className = "mcp-toggle";

          const enabledToggleInput = document.createElement("input");
          enabledToggleInput.type = "checkbox";
          enabledToggleInput.checked = false;
          enabledToggleInput.dataset.action = "script-toggle";
          enabledToggleInput.dataset.configKind = "mcp";
          enabledToggleInput.dataset.configId = "scripts";
          enabledToggleInput.dataset.scriptTitle = scriptItem.title;

          // Async check for script enabled state — update checkbox once resolved
          void (async () => {
            const { isScriptEnabledForExecution } = await import("./scripts.js");
            enabledToggleInput.checked = await isScriptEnabledForExecution(scriptItem.title);
          })();

          const enabledToggleText = document.createElement("span");
          enabledToggleText.textContent = "Enabled";

          enabledToggleLabel.appendChild(enabledToggleInput);
          enabledToggleLabel.appendChild(enabledToggleText);
          scriptNode.appendChild(enabledToggleLabel);

          const scriptLabel = document.createElement("span");
          scriptLabel.className = "mcp-script-label";
          scriptLabel.textContent = scriptItem.title;
          if (scriptItem.description) {
            scriptLabel.title = scriptItem.description;
          }
          scriptNode.appendChild(scriptLabel);

          const editBtn = document.createElement("button");
          editBtn.type = "button";
          editBtn.className = "mcp-script-edit-btn";
          editBtn.title = "Edit script";
          editBtn.textContent = "\u270E";
          editBtn.dataset.action = "script-open";
          editBtn.dataset.configKind = "mcp";
          editBtn.dataset.configId = "scripts";
          editBtn.dataset.scriptTitle = scriptItem.title;
          scriptNode.appendChild(editBtn);

          const dlBtn = document.createElement("button");
          dlBtn.type = "button";
          dlBtn.className = "mcp-script-dl-btn";
          dlBtn.title = "Download script";
          dlBtn.textContent = "\u2193";
          dlBtn.addEventListener("click", async (e) => {
            e.stopPropagation();
            try {
              const resp = await fetch(`/api/mcps/scripts/${encodeURIComponent(scriptItem.title)}`);
              if (!resp.ok) return;
              const data = await resp.json();
              const blob = new Blob([data.source], { type: "text/x-python" });
              const url = URL.createObjectURL(blob);
              const a = document.createElement("a");
              a.href = url;
              a.download = `${scriptItem.title}.py`;
              document.body.appendChild(a);
              a.click();
              a.remove();
              URL.revokeObjectURL(url);
            } catch { /* silent */ }
          });
          scriptNode.appendChild(dlBtn);

          scriptsList.appendChild(scriptNode);
        });
        scriptsBox.appendChild(scriptsList);
      }

      cardBody.appendChild(scriptsBox);

      const newScriptButton = document.createElement("button");
      newScriptButton.type = "button";
      newScriptButton.className = "mcp-link-btn";
      newScriptButton.textContent = "New Script";
      newScriptButton.dataset.action = "script-new";
      newScriptButton.dataset.configKind = options.kind;
      newScriptButton.dataset.configId = item.id;

      const verifyButton = document.createElement("button");
      verifyButton.type = "button";
      verifyButton.className = "mcp-link-btn";
      verifyButton.textContent = "Verify";
      verifyButton.dataset.action = "verify";
      verifyButton.dataset.configKind = options.kind;
      verifyButton.dataset.configId = item.id;

      actions.appendChild(newScriptButton);
      actions.appendChild(verifyButton);
      cardBody.appendChild(actions);
    } else if (options.kind === "mcp") {
      if (item.id === "local_files") {
        card.appendChild(cardBody);
        container.appendChild(card);
        return;
      }
      if (item.id === "whatsapp") {
        const connectButton = document.createElement("button");
        connectButton.type = "button";
        connectButton.className = "mcp-link-btn";
        connectButton.textContent = "Connect";
        connectButton.dataset.action = "whatsapp-connect";
        connectButton.dataset.configKind = options.kind;
        connectButton.dataset.configId = item.id;

        const verifyButton = document.createElement("button");
        verifyButton.type = "button";
        verifyButton.className = "mcp-link-btn";
        verifyButton.textContent = "Verify";
        verifyButton.dataset.action = "verify";
        verifyButton.dataset.configKind = options.kind;
        verifyButton.dataset.configId = item.id;

        const resyncButton = document.createElement("button");
        resyncButton.type = "button";
        resyncButton.className = "mcp-link-btn";
        resyncButton.textContent = "Resync";
        resyncButton.dataset.action = "whatsapp-resync";
        resyncButton.dataset.configKind = options.kind;
        resyncButton.dataset.configId = item.id;

        actions.appendChild(connectButton);
        actions.appendChild(resyncButton);
        actions.appendChild(verifyButton);
        cardBody.appendChild(actions);
        card.appendChild(cardBody);
        container.appendChild(card);
        return;
      }
      const verifyButton = document.createElement("button");
      verifyButton.type = "button";
      verifyButton.className = "mcp-link-btn";
      verifyButton.textContent = "Verify";
      verifyButton.dataset.action = "verify";
      verifyButton.dataset.configKind = options.kind;
      verifyButton.dataset.configId = item.id;

      actions.appendChild(verifyButton);
      cardBody.appendChild(actions);
    } else {
      const saveButton = document.createElement("button");
      saveButton.type = "button";
      saveButton.className = "mcp-link-btn";
      saveButton.textContent = "Save";
      saveButton.dataset.action = "save";
      saveButton.dataset.configKind = options.kind;
      saveButton.dataset.configId = item.id;

      const verifyButton = document.createElement("button");
      verifyButton.type = "button";
      verifyButton.className = "mcp-link-btn";
      verifyButton.textContent = "Verify";
      verifyButton.dataset.action = "verify";
      verifyButton.dataset.configKind = options.kind;
      verifyButton.dataset.configId = item.id;

      actions.appendChild(saveButton);
      actions.appendChild(verifyButton);
      cardBody.appendChild(actions);
    }

    card.appendChild(cardBody);

    container.appendChild(card);
  });
}

export function renderMcpPanel() {
  renderConfigPanel(mcpList, state.mcps, getMcpConfig, {
    kind: "mcp",
    emptyLabel: "No tools available.",
  });
}

export function renderIntegrationPanel() {
  renderConfigPanel(integrationList, state.integrations, getIntegrationConfig, {
    kind: "integration",
    emptyLabel: "No integrations available.",
  });
}
