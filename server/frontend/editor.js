"use strict";

const state = { csrf: "", modules: [], devices: [], pages: [], rules: [], page: null, selected: null, activeTab: "overview", drag: null, canvas: { width: 800, height: 480, scale: 1 } };
const el = (id) => document.getElementById(id);
const clone = (value) => value === undefined ? null : JSON.parse(JSON.stringify(value));
const modelLabel = { waveshare_4in26: "Waveshare 4.26 吋", inky_phat: "Pimoroni Inky pHAT", mock: "Mock 預覽裝置" };
const categoryLabel = { status: "狀態與時間", data: "數據與進度", visual: "視覺與素材", other: "其他" };

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (options.method && !["GET", "HEAD"].includes(options.method)) headers.set("X-CSRF-Token", state.csrf);
  const response = await fetch(path, { ...options, headers });
  if (!response.ok) {
    let detail = "";
    try { const body = await response.json(); detail = body.message || body.error || ""; } catch { detail = await response.text(); }
    throw new Error(detail || response.statusText);
  }
  return response.status === 204 ? null : response.json();
}

function notify(text, isError = false) {
  const toast = el("toast"); toast.textContent = text; toast.className = `toast${isError ? " error" : ""}`; toast.hidden = false;
  clearTimeout(notify.timer); notify.timer = setTimeout(() => { toast.hidden = true; }, 3600);
}
function message(error) { notify(error instanceof Error ? error.message : String(error), true); }
function option(select, values, label, selectedValue = select.value) {
  select.replaceChildren(...values.map((value) => Object.assign(document.createElement("option"), { value: value.id, textContent: label(value) })));
  if (values.some((value) => value.id === selectedValue)) select.value = selectedValue;
}
function moduleFor(item) { return state.modules.find((module) => module.module_id === item.module_id); }
function selectedElement() { return state.page?.content?.elements?.find((item) => item.instance_id === state.selected) || null; }
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
    actions.append(visibility, rotate); card.append(actions);
  }
  return card;
}
function renderDevices() { el("device-list").replaceChildren(...state.devices.map((device) => deviceCard(device))); el("overview-devices").replaceChildren(...state.devices.filter((device) => !device.hidden).map((device) => deviceCard(device, false))); }

function renderRules() {
  const devices = new Map(state.devices.map((device) => [device.id, device.name])); const pages = new Map(state.pages.map((page) => [page.id, page.name]));
  el("rule-list").replaceChildren(...state.rules.map((rule) => {
    const row = document.createElement("article"); row.className = "list-row"; const days = rule.weekdays.length ? rule.weekdays.map((day) => "一二三四五六日"[day]).join("、") : "每天";
    const text = document.createElement("div"); const title = document.createElement("h3"); title.textContent = rule.name; const detail = document.createElement("p"); detail.textContent = `${devices.get(rule.device_id) || "已移除設備"} · ${pages.get(rule.page_id) || "已移除頁面"} · 優先 ${rule.priority} · ${days}`; text.append(title, detail);
    const remove = document.createElement("button"); remove.className = "button button-danger"; remove.type = "button"; remove.textContent = "刪除"; remove.onclick = async () => { if (!confirm(`刪除規則「${rule.name}」？`)) return; try { await api(`/api/workspace/rules/${rule.id}`, { method: "DELETE" }); await refresh(); notify("規則已刪除"); } catch (error) { message(error); } };
    row.append(text, remove); return row;
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
function updateCanvasDimensions() {
  const profile = editorDevice()?.profile || { resolution: [800, 480] }; const [width, height] = profile.resolution || [800, 480]; const scale = Math.min(1, 680 / Math.max(width, 1)); state.canvas = { width, height, scale };
  const canvas = el("layout-canvas"); canvas.style.width = `${Math.max(1, Math.round(width * scale))}px`; canvas.style.height = `${Math.max(1, Math.round(height * scale))}px`;
  el("canvas-meta").textContent = `${width} × ${height} px · 畫面以 ${Math.round(scale * 100)}% 顯示 · 拖曳與縮放採 8px 吸附`;
}
function renderElementList() {
  // 選取狀態已直接呈現在畫布；此函式保留為畫布重繪的單一入口。
}
function renderCanvas() {
  updateCanvasDimensions(); const canvas = el("layout-canvas"); canvas.replaceChildren();
  for (const item of state.page?.content?.elements || []) {
    const module = moduleFor(item); const node = document.createElement("button"); node.type = "button"; node.className = `canvas-element${item.instance_id === state.selected ? " selected" : ""}`; node.dataset.id = item.instance_id;
    const scale = state.canvas.scale; Object.assign(node.style, { left: `${item.x * scale}px`, top: `${item.y * scale}px`, width: `${Math.max(8, item.w * scale)}px`, height: `${Math.max(8, item.h * scale)}px`, zIndex: String((item.z || 0) + 1) });
    const title = document.createElement("strong"); title.textContent = module?.display_name || item.module_id; const info = document.createElement("small"); info.textContent = `${item.x}, ${item.y} · ${item.w}×${item.h}`; const handle = document.createElement("span"); handle.className = "resize-handle"; handle.setAttribute("aria-label", "縮放元件"); node.append(title, info, handle);
    node.addEventListener("pointerdown", (event) => beginDrag(event, item.instance_id, event.target === handle ? "resize" : "move")); canvas.append(node);
  }
  renderElementList(); renderInspector();
}
function renderInspector() {
  const item = selectedElement(); el("element-form").hidden = !item; el("element-empty").hidden = Boolean(item); if (!item) return;
  const module = moduleFor(item); el("selected-module-name").textContent = module ? `${module.display_name} · ${module.description}` : item.module_id;
  for (const [id, value] of [["el-x", item.x], ["el-y", item.y], ["el-w", item.w], ["el-h", item.h], ["el-z", item.z || 0], ["el-refresh", item.refresh_interval || 30]]) el(id).value = String(value);
  const fields = el("config-fields"); fields.replaceChildren();
  for (const schema of module?.config_schema || []) {
    const label = document.createElement("label"); label.textContent = schema.label || schema.key;
    if (schema.type === "json") { const note = document.createElement("p"); note.className = "hint"; note.textContent = "此為複合型設定，保留既有值；需要專用操作面板時可依模組個別擴充。"; label.append(note); fields.append(label); continue; }
    const input = document.createElement("input"); input.type = schema.type === "number" ? "number" : "text"; input.dataset.key = schema.key; input.dataset.type = schema.type || "text"; input.value = item.config?.[schema.key] ?? schema.default ?? ""; label.append(input); fields.append(label);
  }
}
function renderPage() { if (!state.page) return; el("page-name").value = state.page.name; el("page-select").value = state.page.id; renderCanvas(); }
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
  const values = ["el-x", "el-y", "el-w", "el-h", "el-z", "el-refresh"].map((id) => Number(el(id).value)); if (values.some((value) => !Number.isFinite(value))) { notify("位置與尺寸必須是數字", true); return; }
  const [x, y, width, height, z, refresh] = values; if (x < 0 || y < 0 || width < 1 || height < 1 || refresh < 1) { notify("位置、尺寸與更新秒數不正確", true); return; }
  item.x = clamp(x, 0, state.canvas.width - width); item.y = clamp(y, 0, state.canvas.height - height); item.w = Math.min(width, state.canvas.width - item.x); item.h = Math.min(height, state.canvas.height - item.y); item.z = z; item.refresh_interval = refresh; item.config ||= {};
  for (const input of el("config-fields").querySelectorAll("[data-key]")) item.config[input.dataset.key] = input.dataset.type === "number" ? Number(input.value) : input.value;
  renderPage(); notify("元件設定已套用，記得儲存");
}

async function loadPage(id) { state.page = await api(`/api/workspace/pages/${id}`); state.selected = null; renderPage(); updatePreview(); }
async function savePage() {
  if (!state.page) return; try { const name = el("page-name").value.trim(); const page = await api(`/api/workspace/pages/${state.page.id}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name, content: state.page.content }) }); state.page = page; await refresh(false); renderPage(); updatePreview(); notify("版面已儲存並更新預覽"); } catch (error) { message(error); }
}
function updatePreview() {
  const deviceId = el("preview-device").value; const image = el("layout-preview"); const empty = el("preview-empty");
  if (!state.page || !deviceId) { image.hidden = true; empty.hidden = false; return; }
  image.hidden = false; empty.hidden = true; image.src = `/api/workspace/devices/${encodeURIComponent(deviceId)}/preview?page_id=${encodeURIComponent(state.page.id)}&t=${Date.now()}`;
  image.onerror = () => { image.hidden = true; empty.hidden = false; empty.textContent = "預覽產生失敗，請確認設備與版面仍存在。"; };
}

async function loadAssets() { const assets = await api("/api/workspace/assets"); el("asset-list").replaceChildren(...assets.map((asset) => { const image = document.createElement("img"); image.className = "asset"; image.src = `/api/workspace/assets/${encodeURIComponent(asset.id)}`; image.alt = asset.original_filename; return image; })); }
async function loadAttendance() { const attendance = await api("/api/workspace/attendance/today"); el("clock-in").value = attendance.clock_in || ""; el("clock-out").value = attendance.clock_out || ""; el("on-leave").checked = attendance.on_leave; el("leave-note").value = attendance.leave_note; el("attendance-status").textContent = `${attendance.date}：${attendance.status}`; }
function showToken(token) { el("token-value").textContent = token; el("token-dialog").showModal(); }

async function refresh(loadSelected = true) {
  const currentPageId = state.page?.id; [state.devices, state.pages, state.rules] = await Promise.all([api("/api/workspace/devices"), api("/api/workspace/pages"), api("/api/workspace/rules")]);
  const activeDevices = state.devices.filter((device) => !device.hidden); option(el("page-select"), state.pages, (page) => page.name, currentPageId); option(el("rule-page"), state.pages, (page) => page.name); option(el("rule-device"), activeDevices, (device) => device.name); option(el("canvas-device"), state.devices, (device) => device.name); option(el("preview-device"), state.devices, (device) => device.name);
  renderSummary(); renderDevices(); renderRules(); renderModulePalette();
  if (loadSelected && currentPageId && state.pages.some((page) => page.id === currentPageId)) await loadPage(currentPageId);
  else if (loadSelected && !state.page && state.pages[0]) await loadPage(state.pages[0].id);
}

function bindEvents() {
  document.querySelectorAll(".tab").forEach((tab) => tab.addEventListener("click", () => switchTab(tab.dataset.tab))); document.querySelectorAll("[data-open-tab]").forEach((button) => button.addEventListener("click", () => switchTab(button.dataset.openTab)));
  el("device-form").onsubmit = async (event) => { event.preventDefault(); try { const result = await api("/api/workspace/devices", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: el("device-name").value, model_id: el("device-model").value }) }); el("device-name").value = ""; await refresh(); showToken(result.token); notify("設備已建立"); } catch (error) { message(error); } };
  el("new-page").onclick = async () => { try { const page = await api("/api/workspace/pages", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: el("new-page-name").value }) }); el("new-page-name").value = ""; state.page = page; await refresh(false); renderPage(); switchTab("layouts"); notify("新頁面已建立"); } catch (error) { message(error); } };
  el("page-select").onchange = () => loadPage(el("page-select").value).catch(message); el("save-page").onclick = savePage; el("canvas-device").onchange = renderPage; el("preview-device").onchange = updatePreview; el("refresh-preview").onclick = updatePreview; el("element-form").onsubmit = applyElement;
  el("remove-element").onclick = () => { const item = selectedElement(); if (!item || !confirm("刪除此元件？")) return; state.page.content.elements = state.page.content.elements.filter((entry) => entry.instance_id !== item.instance_id); state.selected = null; renderPage(); notify("元件已刪除，記得儲存"); };
  el("rule-form").onsubmit = async (event) => { event.preventDefault(); try { await api("/api/workspace/rules", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: el("rule-name").value, device_id: el("rule-device").value, page_id: el("rule-page").value, priority: Number(el("rule-priority").value), start_time: el("rule-start").value || null, end_time: el("rule-end").value || null, attendance_status: el("rule-attendance").value || null, holiday: el("rule-holiday").value === "" ? null : el("rule-holiday").value === "true", weekdays: [...el("weekdays").querySelectorAll("input:checked")].map((box) => Number(box.value)) }) }); event.target.reset(); await refresh(); notify("規則已新增"); } catch (error) { message(error); } };
  el("asset-form").onsubmit = async (event) => { event.preventDefault(); try { const data = new FormData(); data.append("file", el("asset-file").files[0]); await api("/api/workspace/assets", { method: "POST", body: data }); event.target.reset(); await loadAssets(); notify("圖片已上傳"); } catch (error) { message(error); } };
  el("attendance-form").onsubmit = async (event) => { event.preventDefault(); try { await api("/api/workspace/attendance/today", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ clock_in: el("clock-in").value || null, clock_out: el("clock-out").value || null, on_leave: el("on-leave").checked, leave_note: el("leave-note").value }) }); await loadAttendance(); notify("出勤資料已儲存"); } catch (error) { message(error); } };
  el("refresh-data").onclick = async () => { try { await refresh(); notify("資料已重新整理"); } catch (error) { message(error); } };
  el("logout").onclick = async () => { try { await api("/auth/logout", { method: "POST" }); location.reload(); } catch (error) { message(error); } };
  el("copy-token").onclick = async () => { try { await navigator.clipboard.writeText(el("token-value").textContent); notify("token 已複製"); } catch { notify("無法自動複製，請手動選取 token", true); } };
  el("token-dialog").addEventListener("close", () => { el("token-value").textContent = ""; });
}

async function init() {
  const me = await api("/api/workspace/me"); state.csrf = me.csrf_token; el("identity").textContent = `${me.display_name}（${me.role}）`; state.modules = await api("/api/modules"); bindEvents(); await refresh(); const initial = location.hash.slice(1); switchTab(["overview", "devices", "layouts", "rules", "content"].includes(initial) ? initial : "overview");
}
init().catch(message);
