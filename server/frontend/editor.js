"use strict";

const state = { csrf: "", modules: [], devices: [], pages: [], rules: [], ruleConflicts: [], editingRuleId: null, page: null, savedContentSignature: null, selected: null, inspectorDirty: false, assignment: null, refreshDeviceId: null, activeTab: "overview", layoutView: "canvas", drag: null, canvas: { width: 800, height: 480, scale: 1 } };
const el = (id) => document.getElementById(id);
const clone = (value) => value === undefined ? null : JSON.parse(JSON.stringify(value));
const modelLabel = { waveshare_4in26: "Waveshare 4.26 吋", waveshare_7in5_v2: "Waveshare 7.5 吋 e-Paper HAT V2（黑白）", inky_phat: "Pimoroni Inky pHAT", mock: "Mock 預覽裝置" };
const categoryLabel = { status: "狀態與時間", data: "數據與進度", planning: "規劃與提醒", visual: "視覺與素材", other: "其他" };
const requiredElementIds = ["asset-file", "asset-form", "asset-list", "assignment-status", "attendance-form", "attendance-status", "cancel-rule-edit", "canvas-device", "canvas-meta", "clock-in", "clock-out", "config-fields", "copy-token", "device-form", "device-list", "device-model", "device-name", "element-empty", "element-form", "identity", "layout-canvas", "layout-preview", "leave-note", "load-active-page", "logout", "module-palette", "new-page", "new-page-name", "new-page-preset", "on-leave", "overview-devices", "page-assignment-status", "page-name", "page-select", "preview-device-name", "preview-empty", "quiet-hours-enabled", "quiet-hours-end", "quiet-hours-fields", "quiet-hours-start", "quiet-weekends", "refresh-data", "refresh-daily-at", "refresh-daily-field", "refresh-device-name", "refresh-dialog", "refresh-interval-field", "refresh-interval-hours", "refresh-mode", "refresh-preview", "remove-element", "rule-attendance", "rule-conflict-help", "rule-device", "rule-end", "rule-form", "rule-form-title", "rule-holiday", "rule-list", "rule-model", "rule-name", "rule-page", "rule-priority", "rule-priority-field", "rule-start", "save-page", "save-refresh", "save-rule", "selected-module-name", "summary-cards", "toast", "token-dialog", "token-value", "weekdays"];

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (options.method && !["GET", "HEAD"].includes(options.method)) headers.set("X-CSRF-Token", state.csrf);
  const response = await fetch(path, { ...options, headers });
  if (!response.ok) {
    const raw = await response.text();
    let detail = raw;
    try { const body = JSON.parse(raw); detail = body.message || body.error || raw; } catch { /* 非 JSON 錯誤頁直接顯示原始文字。 */ }
    throw new Error(detail || response.statusText);
  }
  return response.status === 204 ? null : response.json();
}

function notify(text, isError = false) {
  const toast = el("toast"); toast.textContent = text; toast.className = `toast${isError ? " error" : ""}`; toast.hidden = false;
  clearTimeout(notify.timer); notify.timer = setTimeout(() => { toast.hidden = true; }, 3600);
}
function message(error) {
  const text = error instanceof Error ? error.message : String(error);
  // 舊版 HTML 快取時 toast 本身也可能不存在，避免錯誤處理又觸發第二個 null 例外。
  if (!el("toast")) { window.alert(text); return; }
  notify(text, true);
}
function assertDocumentContract() {
  const missing = requiredElementIds.filter((id) => !el(id));
  if (missing.length) throw new Error(`管理台檔案版本不一致，缺少：${missing.join(", ")}。請重新整理頁面；若仍持續，請重新部署 Server。`);
}
function option(select, values, label, selectedValue = select.value) {
  select.replaceChildren(...values.map((value) => Object.assign(document.createElement("option"), { value: value.id, textContent: label(value) })));
  if (values.some((value) => value.id === selectedValue)) select.value = selectedValue;
}
function moduleFor(item) { return state.modules.find((module) => module.module_id === item.module_id); }
function selectedElement() { return state.page?.content?.elements?.find((item) => item.instance_id === state.selected) || null; }
function partialRefreshMinimum(device = editorDevice()) {
  const value = Number(device?.profile?.partial_refresh_min_interval_seconds);
  return device?.profile?.partial_refresh && Number.isFinite(value) && value >= 1 ? value : null;
}
function isPartialRefreshSetting(schema) { return schema?.partial_refresh_interval === true; }
function validatePartialRefreshSettings(item, module) {
  const minimum = partialRefreshMinimum(); if (!minimum || !module) return null;
  for (const schema of module.config_schema || []) {
    if (!isPartialRefreshSetting(schema)) continue;
    const value = Number(item.config?.[schema.key]);
    if (!Number.isFinite(value)) return `「${schema.label}」必須是秒數`;
    if (schema.allow_zero && value === 0) continue;
    if (value < minimum) return `「${schema.label}」不得低於 ${minimum.toFixed(1)} 秒（目前面板的安全局刷下限）`;
  }
  return null;
}
function localTime(value) {
  if (!value) return "尚未收到回報";
  const date = new Date(value); return Number.isNaN(date.valueOf()) ? "時間格式異常" : date.toLocaleString("zh-TW", { hour12: false });
}
function connectionInfo(device) {
  const connection = device.connection || { state: "unknown", last_seen_at: null };
  const labels = { online: "已連線", offline: "離線", unknown: "尚未連線" };
  return { ...connection, label: labels[connection.state] || labels.unknown };
}

function switchTab(name) {
  state.activeTab = name;
  document.querySelectorAll(".tab").forEach((tab) => { const active = tab.dataset.tab === name; tab.setAttribute("aria-selected", String(active)); });
  document.querySelectorAll("[data-panel]").forEach((panel) => { panel.hidden = panel.dataset.panel !== name; });
  history.replaceState(null, "", `#${name}`);
  if (name === "content") Promise.all([loadAssets(), loadAttendance()]).catch(message);
  if (name === "layouts") renderPage();
}

function switchLayoutView(name) {
  state.layoutView = name === "preview" ? "preview" : "canvas";
  document.querySelectorAll("[data-layout-view]").forEach((tab) => {
    tab.setAttribute("aria-selected", String(tab.dataset.layoutView === state.layoutView));
  });
  document.querySelectorAll("[data-layout-pane]").forEach((pane) => {
    pane.hidden = pane.dataset.layoutPane !== state.layoutView;
  });
  if (state.layoutView === "preview") updatePreview();
}

function renderSummary() {
  const visible = state.devices.filter((device) => !device.hidden);
  const online = visible.filter((device) => connectionInfo(device).state === "online").length;
  const cards = [["已啟用設備", visible.length, "可接收版面資料的 Pi"], ["目前已連線", online, "最後三分鐘內有成功回報"], ["可用頁面", state.pages.length, "可供規則指定的版面"]];
  el("summary-cards").replaceChildren(...cards.map(([label, value, note]) => {
    const card = document.createElement("article"); card.className = "summary-card";
    const heading = document.createElement("span"); heading.textContent = label;
    const number = document.createElement("strong"); number.textContent = String(value);
    const detail = document.createElement("span"); detail.textContent = note;
    card.append(heading, number, detail); return card;
  }));
}

function deviceCard(device, controls = true) {
  const info = connectionInfo(device); const card = document.createElement("article"); card.className = `device-card${device.hidden ? " hidden-device" : ""}`;
  const title = document.createElement("div"); title.className = "device-title";
  const text = document.createElement("div"); const name = document.createElement("h3"); name.textContent = device.name; const model = document.createElement("p"); model.className = "device-model"; model.textContent = modelLabel[device.model_id] || device.model_id; text.append(name, model);
  const badge = document.createElement("span"); badge.className = `status-badge status-${info.state}`; badge.textContent = info.label; title.append(text, badge);
  const detail = document.createElement("p"); detail.className = "device-detail"; detail.textContent = `最後成功回報：${localTime(info.last_seen_at)}${info.refresh_mode ? ` · ${info.refresh_mode} 刷新` : ""}`;
  card.append(title, detail);
  if (controls) {
    const actions = document.createElement("div"); actions.className = "device-actions";
    const visibility = document.createElement("button"); visibility.className = "button button-secondary"; visibility.type = "button"; visibility.textContent = device.hidden ? "恢復使用" : "暫時隱藏";
    visibility.onclick = async () => { try { await api(`/api/workspace/devices/${device.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ hidden: !device.hidden }) }); await refresh(); notify(device.hidden ? "設備已恢復" : "設備已隱藏"); } catch (error) { message(error); } };
    const rotate = document.createElement("button"); rotate.className = "button button-secondary"; rotate.type = "button"; rotate.textContent = "重配發 token";
    rotate.onclick = async () => { if (!confirm("重配發後，舊 token 會立即失效。")) return; try { const result = await api(`/api/workspace/devices/${device.id}/token`, { method: "POST" }); showToken(result.token); await refresh(); } catch (error) { message(error); } };
    const refreshSettings = document.createElement("button"); refreshSettings.className = "button button-secondary"; refreshSettings.type = "button"; refreshSettings.textContent = "刷新設定"; refreshSettings.disabled = !device.profile?.partial_refresh; refreshSettings.title = refreshSettings.disabled ? "此面板只支援全刷，無法使用局刷政策" : "";
    refreshSettings.onclick = () => openRefreshSettings(device);
    actions.append(visibility, rotate, refreshSettings); card.append(actions);
  }
  return card;
}
function renderDevices() { el("device-list").replaceChildren(...state.devices.map((device) => deviceCard(device))); el("overview-devices").replaceChildren(...state.devices.filter((device) => !device.hidden).map((device) => deviceCard(device, false))); }

function renderRules() {
  const devices = new Map(state.devices.map((device) => [device.id, device])); const pages = new Map(state.pages.map((page) => [page.id, page.name]));
  const warnings = new Map(); for (const pair of state.ruleConflicts) { for (const [self, other] of [[pair.left, pair.right], [pair.right, pair.left]]) { if (!warnings.has(self.id)) warnings.set(self.id, []); warnings.get(self.id).push(other); } }
  const grouped = new Map();
  for (const rule of state.rules) {
    const modelId = devices.get(rule.device_id)?.model_id || "missing";
    if (!grouped.has(modelId)) grouped.set(modelId, []);
    grouped.get(modelId).push(rule);
  }
  el("rule-list").replaceChildren(...[...grouped.entries()].map(([modelId, rules]) => {
    const group = document.createElement("section"); group.className = "rule-model-group";
    const heading = document.createElement("h3"); heading.textContent = `${modelLabel[modelId] || "已移除型號"}（${rules.length} 條規則）`;
    const list = document.createElement("div"); list.className = "list-stack";
    list.replaceChildren(...rules.map((rule) => {
    const row = document.createElement("article"); row.className = "list-row";
    const device = devices.get(rule.device_id); const text = document.createElement("div"); const title = document.createElement("h3"); title.textContent = rule.name; const detail = document.createElement("p"); detail.textContent = `${device?.name || "已移除設備"} · ${pages.get(rule.page_id) || "已移除頁面"}`; const condition = document.createElement("p"); condition.textContent = ruleConditionSummary(rule); text.append(title, detail, condition);
    const overlaps = warnings.get(rule.id) || []; if (overlaps.length) { const warning = document.createElement("p"); warning.className = "rule-conflict"; warning.textContent = `時段衝突：${overlaps.map((item) => `「${item.name}」（優先 ${item.priority}）`).join("、")}；請用不同優先序決定顯示。`; text.append(warning); }
    const edit = document.createElement("button"); edit.className = "button button-secondary"; edit.type = "button"; edit.textContent = "編輯"; edit.onclick = () => { state.editingRuleId = rule.id; el("rule-form-title").textContent = `編輯規則：${rule.name}`; el("save-rule").textContent = "儲存規則"; el("cancel-rule-edit").hidden = false; el("rule-name").value = rule.name; el("rule-model").value = device?.model_id || ""; syncRuleDeviceOptions(rule.device_id); el("rule-page").value = rule.page_id; el("rule-priority").value = String(rule.priority); el("rule-start").value = rule.start_time || ""; el("rule-end").value = rule.end_time || ""; el("rule-attendance").value = rule.attendance_status || ""; el("rule-holiday").value = rule.holiday === null ? "" : String(rule.holiday); el("weekdays").querySelectorAll("input").forEach((box) => { box.checked = rule.weekdays.includes(Number(box.value)); }); updateRuleConflictHelp(); switchTab("rules"); };
    const remove = document.createElement("button"); remove.className = "button button-danger"; remove.type = "button"; remove.textContent = "刪除"; remove.onclick = async () => { if (!confirm(`刪除規則「${rule.name}」？`)) return; try { await api(`/api/workspace/rules/${rule.id}`, { method: "DELETE" }); await refresh(); await loadDeviceAssignment(); notify("規則已刪除，已重新判定目前套用頁面"); } catch (error) { message(error); } };
    const actions = document.createElement("div"); actions.className = "button-row"; actions.append(edit, remove); row.append(text, actions); return row;
    }));
    group.append(heading, list); return group;
  }));
}

function renderModulePalette() {
  const groups = new Map();
  for (const module of state.modules) { const key = module.category || "other"; if (!groups.has(key)) groups.set(key, []); groups.get(key).push(module); }
  const palette = el("module-palette"); palette.replaceChildren(...[...groups.entries()].map(([category, modules]) => {
    const group = document.createElement("section"); group.className = "module-group"; const heading = document.createElement("h3"); heading.textContent = categoryLabel[category] || category; const list = document.createElement("div"); list.className = "module-list";
    for (const module of modules) { const button = document.createElement("button"); button.type = "button"; button.className = "module-card"; const title = document.createElement("strong"); title.textContent = module.display_name; const detail = document.createElement("span"); detail.textContent = module.description || "加入畫布"; button.append(title, detail); button.onclick = () => addModule(module.module_id); list.append(button); }
    group.append(heading, list); return group;
  }));
}

function editorDevice() { return state.devices.find((device) => device.id === el("canvas-device").value) || state.devices.find((device) => !device.hidden) || state.devices[0] || null; }
function pagesForDevice(device) { return device ? state.pages.filter((page) => page.model_id === device.model_id) : []; }
function syncPageOptions() {
  const pages = pagesForDevice(editorDevice());
  option(el("page-select"), pages, (page) => page.name, state.page?.id);
  const supports7in5Presets = editorDevice()?.model_id === "waveshare_7in5_v2";
  el("new-page-preset").querySelectorAll("[data-7in5-preset]").forEach((preset) => { preset.hidden = !supports7in5Presets; });
  if (!supports7in5Presets) el("new-page-preset").value = "blank";
}
function syncRulePageOptions() {
  const device = state.devices.find((entry) => entry.id === el("rule-device").value);
  option(el("rule-page"), pagesForDevice(device), (page) => page.name);
}
function syncRuleDeviceOptions(selectedDeviceId = el("rule-device").value) {
  const modelId = el("rule-model").value;
  const devices = state.devices.filter((device) => device.model_id === modelId && (!device.hidden || device.id === selectedDeviceId));
  option(el("rule-device"), devices, (device) => device.name, selectedDeviceId);
  syncRulePageOptions();
}
function ruleFormData() {
  return {
    device_id: el("rule-device").value, page_id: el("rule-page").value,
    start_time: el("rule-start").value || null, end_time: el("rule-end").value || null,
    attendance_status: el("rule-attendance").value || null,
    holiday: el("rule-holiday").value === "" ? null : el("rule-holiday").value === "true",
    weekdays: [...el("weekdays").querySelectorAll("input:checked")].map((box) => Number(box.value)),
  };
}
function ruleRangesOverlap(left, right) {
  const ranges = (rule) => {
    if (!rule.start_time || !rule.end_time) return [[0, 1440]];
    const minutes = (value) => { const [hour, minute] = value.split(":").map(Number); return hour * 60 + minute; };
    const start = minutes(rule.start_time); const end = minutes(rule.end_time);
    return start <= end ? [[start, end]] : [[start, 1440], [0, end]];
  };
  return ranges(left).some(([leftStart, leftEnd]) => ranges(right).some(([rightStart, rightEnd]) => Math.max(leftStart, rightStart) <= Math.min(leftEnd, rightEnd)));
}
function rulesCouldOverlap(left, right) {
  if (!left.device_id || left.device_id !== right.device_id || left.page_id === right.page_id) return false;
  const leftDays = new Set(left.weekdays?.length ? left.weekdays : [0, 1, 2, 3, 4, 5, 6]);
  const rightDays = new Set(right.weekdays?.length ? right.weekdays : [0, 1, 2, 3, 4, 5, 6]);
  if (![...leftDays].some((day) => rightDays.has(day))) return false;
  if (left.attendance_status && right.attendance_status && left.attendance_status !== right.attendance_status) return false;
  if (left.holiday !== null && right.holiday !== null && left.holiday !== right.holiday) return false;
  return ruleRangesOverlap(left, right);
}
function updateRuleConflictHelp() {
  const candidate = ruleFormData(); const priorityField = el("rule-priority-field"); const hint = el("rule-conflict-help");
  const conflicts = state.rules.filter((rule) => rule.id !== state.editingRuleId && rulesCouldOverlap(candidate, rule));
  priorityField.hidden = conflicts.length === 0;
  if (!conflicts.length) {
    hint.textContent = "目前時段沒有和其他頁面重疊，優先序不會影響顯示。一般工作頁可維持最低值 0。";
    return;
  }
  const names = conflicts.map((rule) => `「${rule.name}」`).join("、");
  hint.textContent = `時段會與 ${names} 同時符合；請用不同優先序決定顯示。建議工作頁為 0，午休 10，下班 20，請假 30，週末／假日 40。`;
}
function ruleConditionSummary(rule) {
  const days = rule.weekdays.length ? rule.weekdays.map((day) => "一二三四五六日"[day]).join("、") : "每天";
  const period = rule.start_time && rule.end_time ? `${rule.start_time}–${rule.end_time}` : "全天";
  const attendance = { pending: "未打卡", working: "上班中", off_work: "已下班", leave: "請假" }[rule.attendance_status] || "不限出勤";
  const holiday = rule.holiday === null ? "不限假日" : (rule.holiday ? "僅假日" : "僅非假日");
  return `${days} · ${period} · ${attendance} · ${holiday}`;
}
function renderAssignment() {
  const device = editorDevice(); const assignment = state.assignment?.device_id === device?.id ? state.assignment : null;
  const status = el("assignment-status"); const pageStatus = el("page-assignment-status"); const load = el("load-active-page"); const previewName = el("preview-device-name");
  previewName.textContent = device ? `目前編輯／預覽：${device.name}` : "尚未選擇設備";
  if (!device) { status.textContent = "請先建立或選擇一台設備。"; pageStatus.textContent = ""; load.disabled = true; return; }
  if (!assignment) { status.textContent = "正在讀取此 Pi 的套用規則…"; pageStatus.textContent = ""; load.disabled = true; return; }
  const active = assignment.active_rule; const activePage = assignment.active_page;
  const attendanceLabels = { pending: "待打卡", working: "上班中", off_work: "已下班", leave: "請假" };
  const attendance = assignment.attendance_status_source === "auto_off_work" ? "已下班（下班保護時間）" : (attendanceLabels[assignment.attendance_status] || assignment.attendance_status);
  if (!active || !activePage) {
    status.textContent = `目前沒有符合條件的規則（出勤：${attendance}）。Pi 會收到空白版面。`;
    pageStatus.textContent = "此頁面尚未確認為該 Pi 的目前套用頁面；請在「顯示規則」建立或調整指派。";
    load.disabled = true;
    return;
  }
  status.textContent = `目前套用「${activePage.name}」：規則「${active.name}」（出勤：${attendance}）。${assignment.selection_reason || ""}`;
  load.disabled = false;
  if (state.page?.id === activePage.id) pageStatus.textContent = "這就是目前套用到此 Pi 的頁面；儲存後，Pi 下次向 Server 取得版面時會使用新內容。";
  else if (assignment.rules.some((rule) => rule.page_id === state.page?.id)) pageStatus.textContent = "此頁面已指派給該 Pi，但目前條件不符合；現在正在套用另一頁。";
  else pageStatus.textContent = "目前編輯的頁面尚未指派給這台 Pi；儲存不會改變它的顯示內容。";
}
async function loadDeviceAssignment(loadActive = false) {
  const device = editorDevice(); state.assignment = device ? await api(`/api/workspace/devices/${encodeURIComponent(device.id)}/assignment`) : null;
  if (loadActive && state.assignment?.active_page && state.page?.id !== state.assignment.active_page.id) await loadPage(state.assignment.active_page.id);
  renderAssignment();
}
function updateCanvasDimensions() {
  const profile = editorDevice()?.profile || { resolution: [800, 480] }; const [width, height] = profile.resolution || [800, 480]; const scale = Math.min(1, 680 / Math.max(width, 1)); state.canvas = { width, height, scale };
  const canvas = el("layout-canvas"); canvas.style.width = `${Math.max(1, Math.round(width * scale))}px`; canvas.style.height = `${Math.max(1, Math.round(height * scale))}px`;
  el("canvas-meta").textContent = `${width} × ${height} px · 畫面以 ${Math.round(scale * 100)}% 顯示 · 拖曳與縮放採 8px 吸附`;
}
function boundsFor(item) {
  return { x: Number(item.x), y: Number(item.y), w: Number(item.w), h: Number(item.h) };
}
function overflowFor(item) {
  const { x, y, w, h } = boundsFor(item);
  if (![x, y, w, h].every(Number.isFinite) || w < 1 || h < 1) return "位置或尺寸不是有效數字";
  const messages = [];
  if (x < 0) messages.push(`左側 ${Math.abs(x)}px`);
  if (y < 0) messages.push(`頂部 ${Math.abs(y)}px`);
  if (x + w > state.canvas.width) messages.push(`右側 ${x + w - state.canvas.width}px`);
  if (y + h > state.canvas.height) messages.push(`底部 ${y + h - state.canvas.height}px`);
  return messages.join("、");
}
function outOfBoundsElements() {
  return (state.page?.content?.elements || []).filter((item) => overflowFor(item));
}
function contentSignature(content) { return JSON.stringify(content || { elements: [] }); }
function hasUnsavedContent() {
  return Boolean(state.page) && state.savedContentSignature !== null && contentSignature(state.page.content) !== state.savedContentSignature;
}
function renderElementList() {
  // 選取狀態已直接呈現在畫布；此函式保留為畫布重繪的單一入口。
}
function renderCanvas() {
  updateCanvasDimensions(); const canvas = el("layout-canvas"); canvas.replaceChildren();
  for (const item of state.page?.content?.elements || []) {
    const module = moduleFor(item); const overflow = overflowFor(item); const node = document.createElement("button"); node.type = "button"; node.className = `canvas-element${item.instance_id === state.selected ? " selected" : ""}${overflow ? " out-of-bounds" : ""}`; node.dataset.id = item.instance_id;
    const scale = state.canvas.scale; Object.assign(node.style, { left: `${item.x * scale}px`, top: `${item.y * scale}px`, width: `${Math.max(8, item.w * scale)}px`, height: `${Math.max(8, item.h * scale)}px`, zIndex: String((item.z || 0) + 1) });
    const title = document.createElement("strong"); title.textContent = module?.display_name || item.module_id; const info = document.createElement("small"); info.textContent = `${item.x}, ${item.y} · ${item.w}×${item.h}${overflow ? ` · 超出：${overflow}` : ""}`; const handle = document.createElement("span"); handle.className = "resize-handle"; handle.setAttribute("aria-label", "縮放元件"); node.append(title, info, handle);
    node.addEventListener("pointerdown", (event) => beginDrag(event, item.instance_id, event.target === handle ? "resize" : "move")); canvas.append(node);
  }
  const invalid = outOfBoundsElements();
  if (invalid.length) el("canvas-meta").textContent += ` · ⚠ ${invalid.length} 個元件超出面板，請在儲存前修正`;
  renderElementList(); renderInspector();
}
function field(labelText, value = "", type = "text", data = {}) {
  const label = document.createElement("label"); label.textContent = labelText;
  let input;
  if (type === "textarea") input = document.createElement("textarea");
  else if (type === "select") { input = document.createElement("select"); for (const [optionValue, optionText] of data.options || []) input.append(new Option(optionText, optionValue)); }
  else { input = document.createElement("input"); input.type = type; }
  input.value = value ?? "";
  for (const [key, entry] of Object.entries(data)) if (key !== "options") input.dataset[key] = String(entry);
  label.append(input); return label;
}
function check(labelText, checked, data = {}) {
  const label = document.createElement("label"); label.className = "checkbox-field";
  const input = document.createElement("input"); input.type = "checkbox"; input.checked = Boolean(checked);
  for (const [key, entry] of Object.entries(data)) input.dataset[key] = String(entry);
  label.append(input, document.createTextNode(labelText)); return label;
}
function sourceConfig(value, fallback = "") {
  return value && typeof value === "object" && !Array.isArray(value) ? value : { type: "manual", value: value ?? fallback };
}
function sourceEditor(value, fallback = "") {
  const source = sourceConfig(value, fallback); const root = document.createElement("fieldset"); root.className = "source-editor";
  const legend = document.createElement("legend"); legend.textContent = "數值來源"; root.append(legend);
  const type = document.createElement("select"); type.dataset.sourceType = "true";
  [["manual", "手動填寫"], ["battery", "Pi 電池資料"], ["time_until", "距離指定時間"], ["time_progress", "時間進度"], ["attendance_workday_until", "距離打卡後下班"], ["attendance_workday_progress", "打卡後工作進度"], ["http", "HTTP API"]].forEach(([value, text]) => type.append(new Option(text, value)));
  type.value = source.type || "manual"; const kind = document.createElement("label"); kind.textContent = "資料類型"; kind.append(type); root.append(kind);
  const details = document.createElement("div"); details.className = "source-fields";
  details.append(
    field("手動數值／文字", source.value, "text", { sourceField: "value", sourceFor: "manual" }),
    field("電池欄位", source.field || "percent", "text", { sourceField: "field", sourceFor: "battery" }),
    field("無資料時顯示", source.fallback ?? fallback, "text", { sourceField: "fallback", sourceFor: "battery,time_until,time_progress,attendance_workday_until,attendance_workday_progress,http" }),
    field("目標時間", source.target, "time", { sourceField: "target", sourceFor: "time_until" }),
    field("開始時間", source.start, "time", { sourceField: "start", sourceFor: "time_progress" }),
    field("結束時間", source.end, "time", { sourceField: "end", sourceFor: "time_progress" }),
    field("未打卡時起始", source.fallback_start || "09:00", "time", { sourceField: "fallbackStart", sourceFor: "attendance_workday_until,attendance_workday_progress" }),
    field("未打卡時下班", source.fallback_end || "18:30", "time", { sourceField: "fallbackEnd", sourceFor: "attendance_workday_until,attendance_workday_progress" }),
    field("打卡後工時（分鐘）", source.work_minutes ?? 541, "number", { sourceField: "workMinutes", sourceFor: "attendance_workday_until,attendance_workday_progress" }),
    field("API 網址", source.url, "text", { sourceField: "url", sourceFor: "http" }),
    field("資料路徑（選填）", source.path, "text", { sourceField: "path", sourceFor: "http" }),
    field("逾時秒數", source.timeout ?? 5, "number", { sourceField: "timeout", sourceFor: "http" }),
  );
  const update = () => details.querySelectorAll("[data-source-for]").forEach((input) => { input.parentElement.hidden = !input.dataset.sourceFor.split(",").includes(type.value); });
  type.onchange = update; update(); root.append(details); return root;
}
function readSource(root) {
  const get = (name) => root.querySelector(`[data-source-field="${name}"]`)?.value ?? ""; const type = root.querySelector("[data-source-type]")?.value || "manual";
  if (type === "manual") return { type, value: get("value") };
  if (type === "battery") return { type, field: get("field") || "percent", fallback: get("fallback") };
  if (type === "time_until") return { type, target: get("target"), fallback: get("fallback") };
  if (type === "time_progress") return { type, start: get("start"), end: get("end"), fallback: get("fallback") };
  if (["attendance_workday_until", "attendance_workday_progress"].includes(type)) return { type, work_minutes: Number(get("workMinutes")) || 541, fallback_start: get("fallbackStart") || "09:00", fallback_end: get("fallbackEnd") || "18:30", fallback: get("fallback") };
  return { type: "http", url: get("url"), path: get("path"), fallback: get("fallback"), timeout: Number(get("timeout")) || 5 };
}
function complexButton(text, action) {
  const button = document.createElement("button"); button.type = "button"; button.className = "button button-secondary button-small"; button.textContent = text; button.onclick = action; return button;
}
function updateComplex(mutator) {
  const item = selectedElement(); if (!item) return; collectModuleConfig(item); mutator(item.config); renderInspector();
}
function footerLinesEditor(schema, item) {
  const root = document.createElement("fieldset"); root.className = "complex-editor"; root.dataset.complex = "footer_lines"; root.dataset.key = schema.key;
  const legend = document.createElement("legend"); legend.textContent = schema.label; root.append(legend);
  const lines = Array.isArray(item.config?.[schema.key]) ? item.config[schema.key] : (schema.default || []);
  lines.forEach((line, index) => { const row = document.createElement("section"); row.className = "complex-row"; row.dataset.line = String(index); const dynamic = Boolean(line?.value_source);
    const mode = document.createElement("select"); mode.dataset.lineMode = "true"; mode.append(new Option("固定文字", "text"), new Option("動態數值", "source")); mode.value = dynamic ? "source" : "text";
    const modeLabel = document.createElement("label"); modeLabel.textContent = "內容"; modeLabel.append(mode); const text = field("文字", line?.text || "", "text", { lineField: "text" }); const source = sourceEditor(line?.value_source, ""); source.dataset.lineSource = "true";
    const sync = () => { text.hidden = mode.value !== "text"; source.hidden = mode.value !== "source"; }; mode.onchange = sync; sync();
    const remove = complexButton("移除此列", () => updateComplex((config) => { config[schema.key] = (config[schema.key] || []).filter((_, position) => position !== index); }));
    row.append(modeLabel, text, source, check("大字", line?.big, { lineField: "big" }), check("置中", line?.center !== false, { lineField: "center" }), remove); root.append(row);
  });
  root.append(complexButton("新增附註列", () => updateComplex((config) => { (config[schema.key] ||= []).push({ text: "" }); }))); return root;
}
function rowsEditor(schema, item) {
  const root = document.createElement("fieldset"); root.className = "complex-editor"; root.dataset.complex = "rows"; root.dataset.key = schema.key;
  const legend = document.createElement("legend"); legend.textContent = schema.label; root.append(legend);
  const rows = Array.isArray(item.config?.[schema.key]) ? item.config[schema.key] : (schema.default || []);
  rows.forEach((rowData, index) => { const row = document.createElement("section"); row.className = "complex-row"; row.dataset.row = String(index); const remove = complexButton("移除此列", () => updateComplex((config) => { config[schema.key] = (config[schema.key] || []).filter((_, position) => position !== index); })); row.append(field("標籤", rowData?.label || "", "text", { rowField: "label" }), sourceEditor(rowData?.value_source, ""), field("單位／尾碼", rowData?.suffix || "", "text", { rowField: "suffix" }), check("大字顯示", rowData?.big, { rowField: "big" }), remove); root.append(row); });
  root.append(complexButton("新增資料列", () => updateComplex((config) => { (config[schema.key] ||= []).push({ label: "項目", value_source: { type: "manual", value: "" } }); }))); return root;
}
function framesEditor(schema, item) {
  const root = document.createElement("fieldset"); root.className = "complex-editor"; root.dataset.complex = "frames"; root.dataset.key = schema.key;
  const legend = document.createElement("legend"); legend.textContent = schema.label; root.append(legend);
  const frames = Array.isArray(item.config?.[schema.key]) ? item.config[schema.key] : (schema.default || []);
  frames.forEach((frame, index) => {
    const card = document.createElement("section"); card.className = "frame-card"; card.dataset.frame = String(index);
    const header = document.createElement("div"); header.className = "frame-card-header";
    const title = document.createElement("strong"); title.textContent = `影格 ${index + 1}`;
    const remove = complexButton("移除此影格", () => updateComplex((config) => { config[schema.key] = (config[schema.key] || []).filter((_, position) => position !== index); }));
    header.append(title, remove);
    const fields = document.createElement("div"); fields.className = "frame-fields";
    const art = field("AA 人物／動作（可換行）", frame?.art || frame?.face || "", "textarea", { frameField: "art" }); art.classList.add("frame-art-field");
    const line = field("台詞", frame?.line || "", "textarea", { frameField: "line" }); line.classList.add("frame-line-field");
    fields.append(art, line); card.append(header, fields); root.append(card);
  });
  root.append(complexButton("新增影格", () => updateComplex((config) => { (config[schema.key] ||= []).push({ art: "  (・ω・)\\n   |   |\\n  _| |_ ", line: "" }); }))); return root;
}
function messagesEditor(schema, item) {
  const root = document.createElement("fieldset"); root.className = "complex-editor"; root.dataset.complex = "messages"; root.dataset.key = schema.key;
  const legend = document.createElement("legend"); legend.textContent = schema.label; root.append(legend);
  const messages = Array.isArray(item.config?.[schema.key]) ? item.config[schema.key] : (schema.default || []);
  messages.forEach((text, index) => {
    const card = document.createElement("section"); card.className = "message-card"; card.dataset.message = String(index);
    const header = document.createElement("div"); header.className = "frame-card-header";
    const title = document.createElement("strong"); title.textContent = `台詞 ${index + 1}`;
    const remove = complexButton("移除這句", () => updateComplex((config) => { config[schema.key] = (config[schema.key] || []).filter((_, position) => position !== index); }));
    header.append(title, remove);
    const message = field("顯示文字", typeof text === "string" ? text : "", "textarea", { messageField: "text" }); message.classList.add("message-text-field");
    card.append(header, message); root.append(card);
  });
  root.append(complexButton("新增台詞", () => updateComplex((config) => { (config[schema.key] ||= []).push("新的下班台詞"); })));
  return root;
}
function todosEditor(schema, item) {
  const root = document.createElement("fieldset"); root.className = "complex-editor"; root.dataset.complex = "todos"; root.dataset.key = schema.key;
  const legend = document.createElement("legend"); legend.textContent = schema.label; root.append(legend);
  const items = Array.isArray(item.config?.[schema.key]) ? item.config[schema.key] : (schema.default || []);
  items.forEach((todo, index) => {
    const row = document.createElement("section"); row.className = "complex-row compact-complex-row"; row.dataset.todo = String(index);
    const remove = complexButton("移除", () => updateComplex((config) => { config[schema.key] = (config[schema.key] || []).filter((_, position) => position !== index); }));
    row.append(field("待辦內容", todo?.text || "", "text", { todoField: "text" }), check("已完成", todo?.done, { todoField: "done" }), remove); root.append(row);
  });
  root.append(complexButton("新增待辦", () => updateComplex((config) => { (config[schema.key] ||= []).push({ text: "新的待辦", done: false }); })));
  return root;
}
function countdownsEditor(schema, item) {
  const root = document.createElement("fieldset"); root.className = "complex-editor"; root.dataset.complex = "countdowns"; root.dataset.key = schema.key;
  const legend = document.createElement("legend"); legend.textContent = schema.label; root.append(legend);
  const events = Array.isArray(item.config?.[schema.key]) ? item.config[schema.key] : (schema.default || []);
  events.forEach((event, index) => {
    const card = document.createElement("section"); card.className = "frame-card"; card.dataset.countdown = String(index);
    const header = document.createElement("div"); header.className = "frame-card-header"; const title = document.createElement("strong"); title.textContent = `事件 ${index + 1}`;
    const remove = complexButton("移除事件", () => updateComplex((config) => { config[schema.key] = (config[schema.key] || []).filter((_, position) => position !== index); })); header.append(title, remove);
    const fields = document.createElement("div"); fields.className = "frame-fields";
    const kind = field("倒數模式", event?.kind || "daily_time", "select", { countdownField: "kind", options: [["daily_time", "每日固定時間"], ["date_time", "指定日期時間"], ["attendance_workday", "依上班打卡（9 小時 1 分）"]] });
    const time = field("每天目標時間", event?.time || "18:30", "time", { countdownField: "time" });
    const dateTime = field("指定日期時間", event?.datetime || "", "datetime-local", { countdownField: "datetime" });
    const fallback = field("未打卡時下班", event?.fallback_time || "18:30", "time", { countdownField: "fallback_time" });
    const sync = () => { const value = kind.querySelector("select").value; time.hidden = value !== "daily_time"; dateTime.hidden = value !== "date_time"; fallback.hidden = value !== "attendance_workday"; };
    kind.querySelector("select").onchange = sync; sync();
    fields.append(field("事件名稱", event?.label || "", "text", { countdownField: "label" }), kind, time, dateTime, fallback); card.append(header, fields); root.append(card);
  });
  root.append(complexButton("新增倒數事件", () => updateComplex((config) => { (config[schema.key] ||= []).push({ label: "新的目標", kind: "daily_time", time: "18:30" }); })));
  return root;
}
function complexEditor(schema, item) {
  if (schema.editor === "value_source") { const root = sourceEditor(item.config?.[schema.key] ?? schema.default); root.dataset.complex = "value_source"; root.dataset.key = schema.key; return root; }
  if (schema.editor === "footer_lines") return footerLinesEditor(schema, item);
  if (schema.editor === "rows") return rowsEditor(schema, item);
  if (schema.editor === "frames") return framesEditor(schema, item);
  if (schema.editor === "messages") return messagesEditor(schema, item);
  if (schema.editor === "todos") return todosEditor(schema, item);
  if (schema.editor === "countdowns") return countdownsEditor(schema, item);
  const note = document.createElement("p"); note.className = "hint"; note.textContent = "此設定尚未提供專用表單，為避免覆蓋既有資料，暫時不在管理台修改。"; return note;
}
function collectModuleConfig(item) {
  const fields = el("config-fields"); item.config ||= {};
  for (const input of fields.querySelectorAll("[data-key]")) item.config[input.dataset.key] = input.dataset.type === "number" ? Number(input.value) : input.dataset.type === "boolean" ? input.checked : input.value;
  for (const root of fields.querySelectorAll("[data-complex]")) {
    const key = root.dataset.key; if (root.dataset.complex === "value_source") item.config[key] = readSource(root);
    if (root.dataset.complex === "footer_lines") item.config[key] = [...root.querySelectorAll("[data-line]")].map((line) => { const result = { big: line.querySelector('[data-line-field="big"]')?.checked, center: line.querySelector('[data-line-field="center"]')?.checked }; return line.querySelector("[data-line-mode]")?.value === "source" ? { ...result, value_source: readSource(line.querySelector(".source-editor")) } : { ...result, text: line.querySelector('[data-line-field="text"]')?.value || "" }; });
    if (root.dataset.complex === "rows") item.config[key] = [...root.querySelectorAll("[data-row]")].map((row) => ({ label: row.querySelector('[data-row-field="label"]')?.value || "", value_source: readSource(row.querySelector(".source-editor")), suffix: row.querySelector('[data-row-field="suffix"]')?.value || "", big: row.querySelector('[data-row-field="big"]')?.checked }));
    if (root.dataset.complex === "frames") item.config[key] = [...root.querySelectorAll("[data-frame]")].map((frame) => ({ art: frame.querySelector('[data-frame-field="art"]')?.value || "", line: frame.querySelector('[data-frame-field="line"]')?.value || "" }));
    if (root.dataset.complex === "messages") item.config[key] = [...root.querySelectorAll("[data-message]")].map((message) => message.querySelector('[data-message-field="text"]')?.value || "").filter(Boolean);
    if (root.dataset.complex === "todos") item.config[key] = [...root.querySelectorAll("[data-todo]")].map((todo) => ({ text: todo.querySelector('[data-todo-field="text"]')?.value || "", done: todo.querySelector('[data-todo-field="done"]')?.checked })).filter((todo) => todo.text.trim());
    if (root.dataset.complex === "countdowns") item.config[key] = [...root.querySelectorAll("[data-countdown]")].map((event) => ({ label: event.querySelector('[data-countdown-field="label"]')?.value || "", kind: event.querySelector('[data-countdown-field="kind"]')?.value || "daily_time", time: event.querySelector('[data-countdown-field="time"]')?.value || "", datetime: event.querySelector('[data-countdown-field="datetime"]')?.value || "", fallback_time: event.querySelector('[data-countdown-field="fallback_time"]')?.value || "18:30", work_minutes: 541 }));
  }
}
function renderInspector() {
  const item = selectedElement(); state.inspectorDirty = false; el("element-form").hidden = !item; el("element-empty").hidden = Boolean(item); if (!item) return;
  const module = moduleFor(item); el("selected-module-name").textContent = module ? `${module.display_name} · ${module.description}` : item.module_id;
  for (const [id, value] of [["el-x", item.x], ["el-y", item.y], ["el-w", item.w], ["el-h", item.h], ["el-z", item.z || 0], ["el-refresh", item.refresh_interval || 30]]) el(id).value = String(value);
  const fields = el("config-fields"); fields.replaceChildren();
  for (const schema of module?.config_schema || []) {
    if (schema.type === "json") { fields.append(complexEditor(schema, item)); continue; }
    if (schema.type === "boolean") { fields.append(check(schema.label || schema.key, item.config?.[schema.key] ?? schema.default, { key: schema.key, type: "boolean" })); continue; }
    const input = field(schema.label || schema.key, item.config?.[schema.key] ?? schema.default ?? "", schema.type === "number" ? "number" : schema.type === "select" ? "select" : "text", { key: schema.key, type: schema.type || "text", options: schema.options || [] });
    const control = input.querySelector("input, select"); if (schema.type === "number") {
      if (schema.min !== undefined) control.min = String(schema.min); if (schema.max !== undefined) control.max = String(schema.max);
      if (isPartialRefreshSetting(schema)) {
        const minimum = partialRefreshMinimum();
        control.step = "0.1";
        if (minimum !== null) {
          control.min = String(minimum);
          const safety = document.createElement("span"); safety.className = "field-help";
          safety.textContent = `此 ${modelLabel[editorDevice()?.model_id] || "面板"} 的安全局刷下限為 ${minimum.toFixed(1)} 秒。${schema.allow_zero ? "0 表示固定不輪替。" : ""}`;
          input.append(safety);
        }
      }
    }
    if (schema.help) { const help = document.createElement("span"); help.className = "field-help"; help.textContent = schema.help; input.append(help); }
    fields.append(input);
  }
  const refreshField = el("el-refresh").closest("label");
  refreshField.hidden = ["mascot", "countdown", "ticker"].includes(module?.module_id);
}
function renderPage() { syncPageOptions(); if (!state.page) { renderAssignment(); return; } el("page-name").value = state.page.name; renderCanvas(); renderAssignment(); }
function snap(value) { return Math.round(value / 8) * 8; }
function clamp(value, lower, upper) { return Math.min(Math.max(value, lower), Math.max(lower, upper)); }
function beginDrag(event, id, mode) {
  event.preventDefault(); event.stopPropagation(); const item = state.page?.content?.elements?.find((entry) => entry.instance_id === id); if (!item) return; state.selected = id;
  state.drag = { id, mode, startX: event.clientX, startY: event.clientY, origin: { x: item.x, y: item.y, w: item.w, h: item.h } }; renderPage();
  window.addEventListener("pointermove", moveDrag); window.addEventListener("pointerup", endDrag, { once: true });
}
function moveDrag(event) {
  const drag = state.drag; const item = selectedElement(); if (!drag || !item) return; const dx = (event.clientX - drag.startX) / state.canvas.scale; const dy = (event.clientY - drag.startY) / state.canvas.scale;
  if (drag.mode === "move") { item.x = clamp(snap(drag.origin.x + dx), 0, state.canvas.width - item.w); item.y = clamp(snap(drag.origin.y + dy), 0, state.canvas.height - item.h); }
  else { item.w = clamp(snap(drag.origin.w + dx), 8, state.canvas.width - item.x); item.h = clamp(snap(drag.origin.h + dy), 8, state.canvas.height - item.y); }
  renderCanvas();
}
function endDrag() { state.drag = null; window.removeEventListener("pointermove", moveDrag); notify("版面位置已調整，記得儲存"); }
function addModule(moduleId) {
  if (!state.page) { notify("請先建立頁面", true); return; } const module = state.modules.find((entry) => entry.module_id === moduleId); if (!module) return;
  const index = state.page.content.elements.length; const [defaultWidth, defaultHeight] = module.default_size; const width = Math.min(defaultWidth, state.canvas.width); const height = Math.min(defaultHeight, state.canvas.height);
  const item = { instance_id: `${module.module_id}-${crypto.randomUUID()}`, module_id: module.module_id, x: snap(index * 8), y: snap(index * 8), w: width, h: height, z: index, refresh_interval: module.min_refresh_interval, refresh_policy: module.refresh_policy, config: Object.fromEntries((module.config_schema || []).map((field) => [field.key, clone(field.default)])) };
  item.x = clamp(item.x, 0, state.canvas.width - item.w); item.y = clamp(item.y, 0, state.canvas.height - item.h); state.page.content.elements.push(item); state.selected = item.instance_id; renderPage(); notify(`${module.display_name} 已加入畫布`);
}
function applyElement(event) {
  event.preventDefault(); const item = selectedElement(); if (!item) return;
  const previous = clone(item);
  const values = ["el-x", "el-y", "el-w", "el-h", "el-z", "el-refresh"].map((id) => Number(el(id).value)); if (values.some((value) => !Number.isFinite(value))) { notify("位置與尺寸必須是數字", true); return; }
  const [x, y, width, height, z, refresh] = values; if (x < 0 || y < 0 || width < 1 || height < 1 || refresh < 1) { notify("位置、尺寸與更新秒數不正確", true); return; }
  item.x = clamp(x, 0, state.canvas.width - width); item.y = clamp(y, 0, state.canvas.height - height); item.w = Math.min(width, state.canvas.width - item.x); item.h = Math.min(height, state.canvas.height - item.y); item.z = z; item.refresh_interval = refresh;
  collectModuleConfig(item);
  const partialError = validatePartialRefreshSettings(item, moduleFor(item));
  if (partialError) { Object.assign(item, previous); notify(partialError, true); return; }
  state.inspectorDirty = false;
  renderPage(); notify("元件設定已套用，記得儲存");
}

async function loadPage(id) { state.page = await api(`/api/workspace/pages/${id}`); state.savedContentSignature = contentSignature(state.page.content); state.selected = null; renderPage(); updatePreview(); }
async function savePage() {
  if (!state.page) return; const invalid = outOfBoundsElements(); if (invalid.length) { switchLayoutView("canvas"); notify(`有 ${invalid.length} 個元件超出目前面板範圍，請先調整紅色元件。`, true); return; } try { const name = el("page-name").value.trim(); const page = await api(`/api/workspace/pages/${state.page.id}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name, content: state.page.content }) }); state.page = page; state.savedContentSignature = contentSignature(page.content); await refresh(false); await loadDeviceAssignment(); renderPage(); updatePreview(); const activePageId = state.assignment?.active_page?.id; const assigned = state.assignment?.rules?.some((rule) => rule.page_id === state.page.id); notify(activePageId === state.page.id ? "版面已儲存；此 Pi 下次取得版面時會套用新內容" : assigned ? "版面已儲存；此頁面會在對應規則符合時套用" : "版面已儲存；尚未指派給目前這台 Pi"); } catch (error) { message(error); }
}
function updatePreview() {
  const deviceId = editorDevice()?.id; const image = el("layout-preview"); const empty = el("preview-empty");
  if (!state.page || !deviceId || !pagesForDevice(editorDevice()).some((page) => page.id === state.page.id)) { image.hidden = true; empty.hidden = false; empty.textContent = "請選擇與目前 Pi 面板型號相符的頁面。"; return; }
  if (state.inspectorDirty) { image.hidden = true; empty.hidden = false; empty.textContent = "元件設定尚未套用。請先按「套用設定」，再按「儲存版面」後更新預覽。"; return; }
  if (hasUnsavedContent()) { image.hidden = true; empty.hidden = false; empty.textContent = "目前有未儲存的內容變更。請先按「儲存版面」，再更新預覽；預覽只會顯示 Server 已儲存、Pi 實際會取得的版本。"; return; }
  const invalid = outOfBoundsElements();
  if (invalid.length) { image.hidden = true; empty.hidden = false; empty.textContent = `有 ${invalid.length} 個元件超出面板範圍；請回到「編輯畫布」修正紅色元件後再預覽。`; return; }
  image.hidden = false; empty.hidden = true; image.src = `/api/workspace/devices/${encodeURIComponent(deviceId)}/preview?page_id=${encodeURIComponent(state.page.id)}&t=${Date.now()}`;
  image.onerror = () => { image.hidden = true; empty.hidden = false; empty.textContent = "預覽產生失敗，請確認設備與版面仍存在。"; };
}

function assetSize(bytes) {
  if (!Number.isFinite(Number(bytes))) return "大小未知";
  const value = Number(bytes);
  return value < 1024 * 1024 ? `${Math.max(1, Math.round(value / 1024))} KB` : `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

async function copyAssetId(assetId) {
  try { await navigator.clipboard.writeText(assetId); notify("素材 ID 已複製；可貼入圖片模組"); }
  catch { notify(`請手動複製素材 ID：${assetId}`, true); }
}

async function loadAssets() {
  const assets = await api("/api/workspace/assets");
  const cards = assets.map((asset) => {
    const card = document.createElement("article"); card.className = "asset-card";
    const image = document.createElement("img"); image.className = "asset";
    image.src = `/api/workspace/assets/${encodeURIComponent(asset.id)}`; image.alt = asset.original_filename || "圖片素材";
    const details = document.createElement("div"); details.className = "asset-details";
    const name = document.createElement("strong"); name.textContent = asset.original_filename || "未命名圖片";
    const meta = document.createElement("span"); meta.textContent = `${assetSize(asset.size)} · 已最佳化`;
    const id = document.createElement("code"); id.textContent = asset.id;
    const copy = document.createElement("button"); copy.type = "button"; copy.className = "button button-secondary button-small"; copy.textContent = "複製 ID";
    copy.onclick = () => { copyAssetId(asset.id); };
    details.append(name, meta, id, copy); card.append(image, details); return card;
  });
  el("asset-list").replaceChildren(...cards);
}
async function loadAttendance() { const attendance = await api("/api/workspace/attendance/today"); el("clock-in").value = attendance.clock_in || ""; el("clock-out").value = attendance.clock_out || ""; el("on-leave").checked = attendance.on_leave; el("leave-note").value = attendance.leave_note; el("attendance-status").textContent = `${attendance.date}：${attendance.status}`; }
function showToken(token) { el("token-value").textContent = token; el("token-dialog").showModal(); }
function syncRefreshFields() {
  const daily = el("refresh-mode").value === "daily";
  el("refresh-interval-field").hidden = daily; el("refresh-daily-field").hidden = !daily;
  el("quiet-hours-fields").hidden = !el("quiet-hours-enabled").checked;
}
function openRefreshSettings(device) {
  state.refreshDeviceId = device.id; const profile = device.profile || {}; const dailyAt = profile.server_full_refresh_daily_at;
  el("refresh-device-name").textContent = `${device.name}（${modelLabel[device.model_id] || device.model_id}）`;
  el("refresh-mode").value = dailyAt ? "daily" : "interval";
  el("refresh-interval-hours").value = String((Number(profile.full_refresh_interval_seconds) || 1200) / 3600);
  el("refresh-daily-at").value = dailyAt || "12:00";
  const quiet = profile.display_quiet_hours || { enabled: true, start: "20:00", end: "08:30", pause_weekends: true };
  el("quiet-hours-enabled").checked = quiet.enabled === true;
  el("quiet-hours-start").value = quiet.start || "20:00";
  el("quiet-hours-end").value = quiet.end || "08:30";
  el("quiet-weekends").checked = quiet.pause_weekends !== false;
  syncRefreshFields(); el("refresh-dialog").showModal();
}

async function refresh(loadSelected = true) {
  const currentPageId = state.page?.id; [state.devices, state.pages, state.rules, state.ruleConflicts] = await Promise.all([api("/api/workspace/devices"), api("/api/workspace/pages"), api("/api/workspace/rules"), api("/api/workspace/rules/conflicts")]);
  const activeDevices = state.devices.filter((device) => !device.hidden); const modelIds = [...new Set(activeDevices.map((device) => device.model_id))]; option(el("canvas-device"), state.devices, (device) => device.name); option(el("rule-model"), modelIds.map((id) => ({ id })), (model) => modelLabel[model.id] || model.id); syncPageOptions(); syncRuleDeviceOptions(); updateRuleConflictHelp();
  renderSummary(); renderDevices(); renderRules(); renderModulePalette();
  if (loadSelected && currentPageId && state.pages.some((page) => page.id === currentPageId)) await loadPage(currentPageId);
  else if (loadSelected && !state.page && state.pages[0]) await loadPage(state.pages[0].id);
}

function bindEvents() {
  document.querySelectorAll(".tab").forEach((tab) => tab.addEventListener("click", () => switchTab(tab.dataset.tab))); document.querySelectorAll("[data-open-tab]").forEach((button) => button.addEventListener("click", () => switchTab(button.dataset.openTab))); document.querySelectorAll("[data-layout-view]").forEach((tab) => tab.addEventListener("click", () => switchLayoutView(tab.dataset.layoutView)));
  el("device-form").onsubmit = async (event) => { event.preventDefault(); try { const result = await api("/api/workspace/devices", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: el("device-name").value, model_id: el("device-model").value }) }); el("device-name").value = ""; await refresh(); showToken(result.token); notify("設備已建立"); } catch (error) { message(error); } };
  el("new-page").onclick = async () => { try { const device = editorDevice(); if (!device) throw new Error("請先選擇要建立版型的 Pi"); const page = await api("/api/workspace/pages", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: el("new-page-name").value, model_id: device.model_id, preset: el("new-page-preset").value }) }); el("new-page-name").value = ""; el("new-page-preset").value = "blank"; state.page = page; state.savedContentSignature = contentSignature(page.content); await refresh(false); renderPage(); switchTab("layouts"); notify("新頁面已建立，僅可用於目前面板型號"); } catch (error) { message(error); } };
  el("page-select").onchange = () => loadPage(el("page-select").value).catch(message); el("save-page").onclick = savePage; el("canvas-device").onchange = async () => { try { await loadDeviceAssignment(true); if (!state.assignment?.active_page) { const fallback = pagesForDevice(editorDevice())[0]; if (fallback) await loadPage(fallback.id); } renderPage(); } catch (error) { message(error); } }; el("rule-model").onchange = () => { syncRuleDeviceOptions(""); updateRuleConflictHelp(); }; el("rule-device").onchange = () => { syncRulePageOptions(); updateRuleConflictHelp(); }; ["rule-page", "rule-start", "rule-end", "rule-attendance", "rule-holiday", "weekdays"].forEach((id) => el(id).addEventListener("change", updateRuleConflictHelp)); el("load-active-page").onclick = () => { const pageId = state.assignment?.active_page?.id; if (pageId) loadPage(pageId).catch(message); }; el("refresh-preview").onclick = updatePreview; el("element-form").onsubmit = applyElement; el("element-form").addEventListener("input", () => { state.inspectorDirty = true; }); el("element-form").addEventListener("change", () => { state.inspectorDirty = true; });
  el("remove-element").onclick = () => { const item = selectedElement(); if (!item || !confirm("刪除此元件？")) return; state.page.content.elements = state.page.content.elements.filter((entry) => entry.instance_id !== item.instance_id); state.selected = null; renderPage(); notify("元件已刪除，記得儲存"); };
  el("rule-form").onsubmit = async (event) => { event.preventDefault(); try { const payload = { name: el("rule-name").value, priority: Number(el("rule-priority").value), ...ruleFormData() }; const editing = state.editingRuleId; await api(editing ? `/api/workspace/rules/${encodeURIComponent(editing)}` : "/api/workspace/rules", { method: editing ? "PUT" : "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }); state.editingRuleId = null; event.target.reset(); el("rule-form-title").textContent = "新增規則"; el("save-rule").textContent = "新增規則"; el("cancel-rule-edit").hidden = true; await refresh(); await loadDeviceAssignment(); notify(editing ? "規則已更新，已重新判定目前套用頁面" : "規則已新增，已重新判定目前套用頁面"); } catch (error) { message(error); } };
  el("cancel-rule-edit").onclick = () => { state.editingRuleId = null; el("rule-form").reset(); el("rule-form-title").textContent = "新增規則"; el("save-rule").textContent = "新增規則"; el("cancel-rule-edit").hidden = true; syncRuleDeviceOptions(); updateRuleConflictHelp(); };
  el("asset-form").onsubmit = async (event) => { event.preventDefault(); try { const file = el("asset-file").files[0]; if (!file) throw new Error("請先選擇圖片檔案"); const data = new FormData(); data.append("file", file); const result = await api("/api/workspace/assets", { method: "POST", body: data }); event.target.reset(); await loadAssets(); notify(result.deduplicated ? "相同圖片已在圖庫中，直接沿用既有素材" : "圖片已上傳、最佳化並加入圖庫"); } catch (error) { message(error); } };
  el("attendance-form").onsubmit = async (event) => { event.preventDefault(); try { await api("/api/workspace/attendance/today", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ clock_in: el("clock-in").value || null, clock_out: el("clock-out").value || null, on_leave: el("on-leave").checked, leave_note: el("leave-note").value }) }); await loadAttendance(); await loadDeviceAssignment(); notify("出勤資料已儲存，已重新判定目前 Pi 頁面"); } catch (error) { message(error); } };
  el("refresh-data").onclick = async () => { try { await refresh(); notify("資料已重新整理"); } catch (error) { message(error); } };
  el("logout").onclick = async () => { try { await api("/auth/logout", { method: "POST" }); location.reload(); } catch (error) { message(error); } };
  el("copy-token").onclick = async () => { try { await navigator.clipboard.writeText(el("token-value").textContent); notify("token 已複製"); } catch { notify("無法自動複製，請手動選取 token", true); } };
  el("token-dialog").addEventListener("close", () => { el("token-value").textContent = ""; });
  el("refresh-mode").onchange = syncRefreshFields; el("quiet-hours-enabled").onchange = syncRefreshFields;
  el("save-refresh").onclick = async () => { try { if (!state.refreshDeviceId) throw new Error("找不到要設定的 Pi"); const mode = el("refresh-mode").value; const quietHours = { enabled: el("quiet-hours-enabled").checked, start: el("quiet-hours-start").value, end: el("quiet-hours-end").value, pause_weekends: el("quiet-weekends").checked }; const refreshPayload = mode === "daily" ? { mode, daily_at: el("refresh-daily-at").value, quiet_hours: quietHours } : { mode, interval_seconds: Math.round(Number(el("refresh-interval-hours").value) * 3600), quiet_hours: quietHours }; await api(`/api/workspace/devices/${encodeURIComponent(state.refreshDeviceId)}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ refresh: refreshPayload }) }); el("refresh-dialog").close(); await refresh(); notify(quietHours.enabled ? "刷新設定已更新；靜默時段會停止面板輸出" : "刷新設定已更新；未啟用靜默時段"); } catch (error) { message(error); } };
  el("refresh-dialog").addEventListener("close", () => { state.refreshDeviceId = null; });
}

async function init() {
  assertDocumentContract();
  const me = await api("/api/workspace/me"); state.csrf = me.csrf_token; el("identity").textContent = `${me.display_name}（${me.role}）`; state.modules = await api("/api/modules"); bindEvents(); await refresh(); await loadDeviceAssignment(true); const initial = location.hash.slice(1); switchTab(["overview", "devices", "layouts", "rules", "content"].includes(initial) ? initial : "overview");
}
init().catch(message);
