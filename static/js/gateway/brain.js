import { state } from "./state.js";
import {
  brainModal,
  brainModalBackdrop,
  brainModalMetaNode,
  brainRefreshButton,
  brainTableList,
  brainTableTitle,
  brainTableColumns,
  brainTableView,
  memoryModal,
  timedJobsModal,
  shortTermMemoryModal,
  tokenUsageModal,
  changePasswordModal,
} from "./dom.js";
import { normalizeErrorMessage } from "./utils.js";

function renderBrainTableList() {
  if (!(brainTableList instanceof HTMLElement)) {
    return;
  }

  brainTableList.innerHTML = "";

  if (!Array.isArray(state.brainTables) || state.brainTables.length === 0) {
    const emptyNode = document.createElement("p");
    emptyNode.className = "memory-empty";
    emptyNode.textContent = "No tables found.";
    brainTableList.appendChild(emptyNode);
    return;
  }

  state.brainTables.forEach((table) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "brain-table-item";
    if (table.name === state.selectedBrainTable) {
      button.classList.add("active");
    }
    button.dataset.tableName = table.name;
    button.textContent = `${table.name} (${table.row_count})`;
    brainTableList.appendChild(button);
  });
}

function renderSelectedBrainTable() {
  if (!(brainTableTitle instanceof HTMLElement) || !(brainTableColumns instanceof HTMLElement) || !(brainTableView instanceof HTMLElement)) {
    return;
  }

  const table = state.brainTables.find((entry) => entry.name === state.selectedBrainTable);
  if (!table) {
    brainTableTitle.textContent = "Select a table";
    brainTableColumns.textContent = "";
    brainTableView.innerHTML = "";
    return;
  }

  brainTableTitle.textContent = `${table.name} (${table.row_count} rows)`;
  const columnLabels = Array.isArray(table.columns)
    ? table.columns.map((column) => `${column.name}:${column.type || "text"}`)
    : [];
  brainTableColumns.textContent = columnLabels.length > 0 ? columnLabels.join(" | ") : "No columns";

  brainTableView.innerHTML = "";
  const rows = Array.isArray(table.rows) ? table.rows : [];
  const columns = Array.isArray(table.columns) ? table.columns : [];
  if (rows.length === 0 || columns.length === 0) {
    const emptyNode = document.createElement("p");
    emptyNode.className = "memory-empty";
    emptyNode.textContent = "No rows in this table.";
    brainTableView.appendChild(emptyNode);
    return;
  }

  const tableNode = document.createElement("table");
  tableNode.className = "brain-grid";

  const thead = document.createElement("thead");
  const headRow = document.createElement("tr");
  columns.forEach((column) => {
    const th = document.createElement("th");
    th.textContent = column.name;
    headRow.appendChild(th);
  });
  thead.appendChild(headRow);
  tableNode.appendChild(thead);

  const tbody = document.createElement("tbody");
  rows.forEach((row) => {
    const tr = document.createElement("tr");
    columns.forEach((column) => {
      const td = document.createElement("td");
      const value = row[column.name];
      td.textContent = value === null || value === undefined ? "" : String(value);
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
  tableNode.appendChild(tbody);
  brainTableView.appendChild(tableNode);
}

async function loadBrainView() {
  if (state.brainLoading) {
    return;
  }

  state.brainLoading = true;
  if (brainModalMetaNode instanceof HTMLElement) {
    brainModalMetaNode.textContent = "Loading brain tables...";
  }
  if (brainRefreshButton instanceof HTMLButtonElement) {
    brainRefreshButton.disabled = true;
  }

  try {
    const response = await fetch("/api/braindump/view", { cache: "no-store" });
    if (!response.ok) {
      throw new Error("Failed to load brain view.");
    }

    const payload = await response.json();
    const tables = Array.isArray(payload.tables) ? payload.tables : [];
    state.brainTables = tables;
    if (!tables.some((table) => table.name === state.selectedBrainTable)) {
      state.selectedBrainTable = tables[0]?.name ?? "";
    }

    if (brainModalMetaNode instanceof HTMLElement) {
      brainModalMetaNode.textContent = `${payload.table_count ?? tables.length} tables loaded`;
    }
    renderBrainTableList();
    renderSelectedBrainTable();
  } catch (error) {
    if (brainModalMetaNode instanceof HTMLElement) {
      brainModalMetaNode.textContent = normalizeErrorMessage(error, "Failed to load brain tables.");
    }
    state.brainTables = [];
    state.selectedBrainTable = "";
    renderBrainTableList();
    renderSelectedBrainTable();
  } finally {
    state.brainLoading = false;
    if (brainRefreshButton instanceof HTMLButtonElement) {
      brainRefreshButton.disabled = false;
    }
  }
}

function openBrainModal() {
  if (!(brainModal instanceof HTMLElement)) {
    return;
  }
  brainModal.classList.remove("hidden");
  document.body.style.overflow = "hidden";
  loadBrainView();
}

function closeBrainModal() {
  if (!(brainModal instanceof HTMLElement)) {
    return;
  }
  brainModal.classList.add("hidden");
  if ((!(memoryModal instanceof HTMLElement) || memoryModal.classList.contains("hidden"))
    && (!state.mobileLeftDrawerOpen && !state.mobileRightDrawerOpen)
    && (!(timedJobsModal instanceof HTMLElement) || timedJobsModal.classList.contains("hidden"))
    && (!(shortTermMemoryModal instanceof HTMLElement) || shortTermMemoryModal.classList.contains("hidden"))
    && (!(tokenUsageModal instanceof HTMLElement) || tokenUsageModal.classList.contains("hidden"))
    && (!(changePasswordModal instanceof HTMLElement) || changePasswordModal.classList.contains("hidden"))) {
    document.body.style.overflow = "";
  }
}

export {
  renderBrainTableList,
  renderSelectedBrainTable,
  loadBrainView,
  openBrainModal,
  closeBrainModal,
};
