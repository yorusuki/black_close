"use strict";

const state = { csrf: "", modules: [], devices: [], pages: [], rules: [], page: null, selected: null };
const el = (id) => document.getElementById(id);

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (options.method && !["GET", "HEAD"].includes(options.method)) headers.set("X-CSRF-Token", state.csrf);
  const response = await fetch(path, { ...options, headers });
  if (!response.ok) throw new Error((await response.text()) || response.statusText);
  return response.status === 204 ? null : response.json();
}
function option(select, values, label) { select.replaceChildren(...values.map((value) => Object.assign(document.createElement("option"), { value: value.id, textContent: label(value) }))); }
function message(error) { alert(error instanceof Error ? error.message : String(error)); }

async function refresh() {
  [state.devices, state.pages, state.rules] = await Promise.all([api("/api/workspace/devices"), api("/api/workspace/pages"), api("/api/workspace/rules")]);
  option(el("page-select"), state.pages, (page) => page.name);
  option(el("rule-page"), state.pages, (page) => page.name);
  option(el("rule-device"), state.devices.filter((device) => !device.hidden), (device) => `${device.name} (${device.model_id})`);
  renderDevices(); renderRules();
  if (state.page) {
    const current = state.pages.find((page) => page.id === state.page.id);
    if (current) await loadPage(current.id);
  } else if (state.pages[0]) await loadPage(state.pages[0].id);
}

function renderDevices() {
  el("device-list").replaceChildren(...state.devices.map((device) => {
    const row = document.createElement("div"); row.className = "list-row";
    row.append(`${device.name} · ${device.model_id}${device.hidden ? "（已隱藏）" : ""}`);
    const hide = document.createElement("button"); hide.textContent = device.hidden ? "顯示" : "隱藏";
    hide.onclick = async () => { try { await api(`/api/workspace/devices/${device.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ hidden: !device.hidden }) }); await refresh(); } catch (error) { message(error); } };
    const rotate = document.createElement("button"); rotate.textContent = "重配發 token";
    rotate.onclick = async () => { if (!confirm("重配發後，舊 token 會立即失效。")) return; try { const result = await api(`/api/workspace/devices/${device.id}/token`, { method: "POST" }); prompt("請立即複製並安全保存此 token（僅顯示這一次）", result.token); } catch (error) { message(error); } };
    row.append(hide, rotate); return row;
  }));
}

async function loadPage(id) {
  state.page = await api(`/api/workspace/pages/${id}`); state.selected = null; el("page-select").value = id; renderPage();
}
function currentElement() { return state.page?.content.elements.find((item) => item.instance_id === state.selected); }
function renderPage() {
  const list = el("element-list"); list.replaceChildren();
  for (const item of state.page?.content.elements || []) {
    const button = document.createElement("button"); button.className = item.instance_id === state.selected ? "selected" : "";
    button.textContent = `${item.module_id} (${item.x}, ${item.y})`; button.onclick = () => { state.selected = item.instance_id; renderPage(); fillElement(); }; list.append(button);
  }
  el("element-form").hidden = !currentElement(); if (currentElement()) fillElement();
}
function fillElement() {
  const item = currentElement(); if (!item) return;
  for (const [id, value] of [["el-x", item.x], ["el-y", item.y], ["el-w", item.w], ["el-h", item.h], ["el-z", item.z || 0], ["el-refresh", item.refresh_interval || 30]]) el(id).value = value;
  const fields = el("config-fields"); fields.replaceChildren(); const module = state.modules.find((candidate) => candidate.module_id === item.module_id);
  for (const schema of module?.config_schema || []) {
    const label = document.createElement("label"); label.textContent = schema.label || schema.key;
    if (schema.type === "json") { const note = document.createElement("p"); note.className = "hint"; note.textContent = "此複合設定沿用頁面預設值；目前不提供原始 JSON 編輯。"; label.append(note); fields.append(label); continue; }
    const input = document.createElement("input"); input.type = schema.type === "number" ? "number" : "text"; input.dataset.key = schema.key; input.dataset.type = schema.type || "text"; input.value = item.config?.[schema.key] ?? schema.default ?? ""; label.append(input); fields.append(label);
  }
}
function addModule() {
  if (!state.page) return; const module = state.modules.find((item) => item.module_id === el("module-select").value); if (!module) return;
  const index = state.page.content.elements.length, [w, h] = module.default_size;
  state.page.content.elements.push({ instance_id: `${module.module_id}-${crypto.randomUUID()}`, module_id: module.module_id, x: 0, y: 0, w, h, z: index, refresh_interval: module.min_refresh_interval, refresh_policy: module.refresh_policy, config: Object.fromEntries((module.config_schema || []).map((field) => [field.key, field.default])) });
  state.selected = state.page.content.elements.at(-1).instance_id; renderPage();
}
function applyElement(event) {
  event.preventDefault(); const item = currentElement(); if (!item) return;
  item.x = Number(el("el-x").value); item.y = Number(el("el-y").value); item.w = Number(el("el-w").value); item.h = Number(el("el-h").value); item.z = Number(el("el-z").value); item.refresh_interval = Number(el("el-refresh").value);
  item.config ||= {}; for (const input of el("config-fields").querySelectorAll("[data-key]")) item.config[input.dataset.key] = input.dataset.type === "number" ? Number(input.value) : input.value;
  renderPage();
}

function renderRules() {
  el("rule-list").replaceChildren(...state.rules.map((rule) => { const row = document.createElement("div"); row.className = "list-row"; const days = rule.weekdays.length ? rule.weekdays.map((day) => "一二三四五六日"[day]).join("") : "每天"; row.append(`${rule.name} · 優先 ${rule.priority} · ${days}`); const remove = document.createElement("button"); remove.textContent = "刪除"; remove.className = "danger"; remove.onclick = async () => { try { await api(`/api/workspace/rules/${rule.id}`, { method: "DELETE" }); await refresh(); } catch (error) { message(error); } }; row.append(remove); return row; }));
}

async function loadAssets() { const assets = await api("/api/workspace/assets"); el("asset-list").replaceChildren(...assets.map((asset) => { const image = document.createElement("img"); image.className = "asset"; image.src = `/api/workspace/assets/${asset.id}`; image.alt = asset.original_filename; return image; })); }
async function loadAttendance() { const attendance = await api("/api/workspace/attendance/today"); el("clock-in").value = attendance.clock_in || ""; el("clock-out").value = attendance.clock_out || ""; el("on-leave").checked = attendance.on_leave; el("leave-note").value = attendance.leave_note; el("attendance-status").textContent = `${attendance.date}：${attendance.status}`; }

async function init() {
  const me = await api("/api/workspace/me"); state.csrf = me.csrf_token; el("identity").textContent = `${me.display_name}（${me.role}）`;
  state.modules = await api("/api/modules"); option(el("module-select"), state.modules, (module) => module.display_name);
  el("device-form").onsubmit = async (event) => { event.preventDefault(); try { const result = await api("/api/workspace/devices", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: el("device-name").value, model_id: el("device-model").value }) }); el("device-name").value = ""; prompt("請立即複製並安全保存此 token（僅顯示這一次）", result.token); await refresh(); } catch (error) { message(error); } };
  el("new-page").onclick = async () => { try { const page = await api("/api/workspace/pages", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: el("new-page-name").value }) }); el("new-page-name").value = ""; await refresh(); await loadPage(page.id); } catch (error) { message(error); } };
  el("page-select").onchange = () => loadPage(el("page-select").value); el("add-module").onclick = addModule;
  el("element-form").onsubmit = applyElement; el("remove-element").onclick = () => { state.page.content.elements = state.page.content.elements.filter((item) => item.instance_id !== state.selected); state.selected = null; renderPage(); };
  el("save-page").onclick = async () => { if (!state.page) return; try { await api(`/api/workspace/pages/${state.page.id}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: state.page.name, content: state.page.content }) }); await refresh(); } catch (error) { message(error); } };
  el("rule-form").onsubmit = async (event) => { event.preventDefault(); try { await api("/api/workspace/rules", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: el("rule-name").value, device_id: el("rule-device").value, page_id: el("rule-page").value, priority: Number(el("rule-priority").value), start_time: el("rule-start").value || null, end_time: el("rule-end").value || null, attendance_status: el("rule-attendance").value || null, holiday: el("rule-holiday").value === "" ? null : el("rule-holiday").value === "true", weekdays: [...el("weekdays").querySelectorAll("input:checked")].map((box) => Number(box.value)) }) }); event.target.reset(); await refresh(); } catch (error) { message(error); } };
  el("asset-form").onsubmit = async (event) => { event.preventDefault(); try { const data = new FormData(); data.append("file", el("asset-file").files[0]); await api("/api/workspace/assets", { method: "POST", body: data }); event.target.reset(); await loadAssets(); } catch (error) { message(error); } };
  el("attendance-form").onsubmit = async (event) => { event.preventDefault(); try { await api("/api/workspace/attendance/today", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ clock_in: el("clock-in").value || null, clock_out: el("clock-out").value || null, on_leave: el("on-leave").checked, leave_note: el("leave-note").value }) }); await loadAttendance(); } catch (error) { message(error); } };
  el("logout").onclick = async () => { await api("/auth/logout", { method: "POST" }); location.reload(); };
  await refresh(); await Promise.all([loadAssets(), loadAttendance()]);
}
init().catch(message);
