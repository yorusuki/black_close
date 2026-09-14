"use strict";
/* epagerPi 排版編輯器：純 vanilla JS，不依賴任何外部 CDN 套件
 * （Pi 上可能沒有網路，編輯器本身也要能離線用）。
 *
 * 核心概念：畫布上每個元件用「裝置實際像素座標」存在 state.layout.elements，
 * 畫面上顯示時乘上 zoom 倍率；拖曳/縮放時再除回 zoom，所以存檔內容永遠是
 * 裝置的真實像素座標，跟編輯器目前開多大縮放無關。
 */

const state = {
  devices: [],
  modules: [],
  deviceId: null,
  profile: null,
  layoutId: null,
  layout: { elements: [] },
  selectedId: null,
  zoom: 2,
};

const el = (id) => document.getElementById(id);

async function api(path, opts) {
  const resp = await fetch(path, opts);
  if (!resp.ok) {
    const text = await resp.text().catch(() => resp.statusText);
    throw new Error(`${path} -> ${resp.status}: ${text}`);
  }
  const ct = resp.headers.get("content-type") || "";
  return ct.includes("application/json") ? resp.json() : resp.text();
}

// ---------------- 初始化 ----------------

async function init() {
  state.modules = await api("/api/modules");
  renderModuleList();

  state.devices = await api("/api/devices");
  const sel = el("device-select");
  sel.innerHTML = state.devices.map((d) => `<option value="${d.id}">${d.id}（${d.driver}）</option>`).join("");
  sel.addEventListener("change", () => selectDevice(sel.value));

  el("zoom-input").addEventListener("change", (e) => {
    state.zoom = parseFloat(e.target.value) || 1;
    renderCanvas();
  });
  el("load-layout-btn").addEventListener("click", () => loadLayout(el("layout-id-input").value.trim()));
  el("save-layout-btn").addEventListener("click", saveLayout);
  el("apply-props-btn").addEventListener("click", applyProps);
  el("delete-el-btn").addEventListener("click", deleteSelected);
  el("save-scenes-btn").addEventListener("click", saveScenes);

  if (state.devices.length) {
    sel.value = state.devices[0].id;
    await selectDevice(state.devices[0].id);
  }

  startPreviewLoop();
}

async function selectDevice(deviceId) {
  state.deviceId = deviceId;
  state.profile = await api(`/api/devices/${deviceId}`);
  const layoutId = state.profile.default_layout_id || "";
  el("layout-id-input").value = layoutId;
  await loadLayout(layoutId);
  await loadScenes(deviceId);
  el("preview-img").src = `/api/devices/${deviceId}/frame.png?t=${Date.now()}`;
}

// ---------------- 模組面板 ----------------

function renderModuleList() {
  el("module-list").innerHTML = state.modules
    .map(
      (m) => `
      <div class="module-item" data-module-id="${m.module_id}">
        <b>${m.display_name}</b>
        <span>${m.description || ""}</span>
      </div>`
    )
    .join("");
  el("module-list").querySelectorAll(".module-item").forEach((node) => {
    node.addEventListener("click", () => addElement(node.dataset.moduleId));
  });
}

function defaultConfigFromSchema(manifest) {
  const cfg = {};
  for (const field of manifest.config_schema || []) {
    cfg[field.key] = field.default;
  }
  return cfg;
}

function addElement(moduleId) {
  const manifest = state.modules.find((m) => m.module_id === moduleId);
  if (!manifest) return;
  const instanceId = `${moduleId}-${Date.now().toString(36)}`;
  state.layout.elements.push({
    instance_id: instanceId,
    module_id: moduleId,
    x: 10,
    y: 10,
    w: manifest.default_size[0],
    h: manifest.default_size[1],
    z: state.layout.elements.length,
    refresh_interval: manifest.min_refresh_interval,
    config: defaultConfigFromSchema(manifest),
  });
  renderCanvas();
  selectElement(instanceId);
}

// ---------------- Layout 讀寫 ----------------

async function loadLayout(layoutId) {
  state.layoutId = layoutId;
  if (!layoutId) {
    state.layout = { elements: [] };
    renderCanvas();
    return;
  }
  try {
    state.layout = await api(`/api/layouts/${layoutId}`);
    if (!state.layout.elements) state.layout.elements = [];
  } catch (e) {
    console.warn("layout 不存在，建立空白 layout：", e.message);
    state.layout = { elements: [] };
  }
  renderCanvas();
}

async function saveLayout() {
  const layoutId = el("layout-id-input").value.trim();
  if (!layoutId) {
    alert("請先填 layout id");
    return;
  }
  state.layoutId = layoutId;
  await api(`/api/layouts/${layoutId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(state.layout),
  });
  alert(`已儲存 layout「${layoutId}」`);
}

// ---------------- 畫布渲染 / 拖曳縮放 ----------------

function renderCanvas() {
  const canvas = el("canvas");
  if (!state.profile) return;
  const [w, h] = state.profile.resolution;
  const z = state.zoom;
  canvas.style.width = `${w * z}px`;
  canvas.style.height = `${h * z}px`;
  canvas.innerHTML = "";

  const elements = [...state.layout.elements].sort((a, b) => (a.z || 0) - (b.z || 0));
  for (const item of elements) {
    const div = document.createElement("div");
    div.className = "el" + (item.instance_id === state.selectedId ? " selected" : "");
    div.style.left = `${item.x * z}px`;
    div.style.top = `${item.y * z}px`;
    div.style.width = `${item.w * z}px`;
    div.style.height = `${item.h * z}px`;
    div.style.zIndex = String(item.z || 0);
    div.innerHTML = `<span class="el-label">${item.module_id}</span>`;

    const handle = document.createElement("div");
    handle.className = "resize-handle";
    div.appendChild(handle);

    div.addEventListener("pointerdown", (evt) => {
      if (evt.target === handle) return;
      selectElement(item.instance_id);
      startDrag(evt, item);
    });
    handle.addEventListener("pointerdown", (evt) => {
      evt.stopPropagation();
      selectElement(item.instance_id);
      startResize(evt, item);
    });

    canvas.appendChild(div);
  }
}

function startDrag(evt, item) {
  evt.preventDefault();
  const startX = evt.clientX;
  const startY = evt.clientY;
  const origX = item.x;
  const origY = item.y;
  const z = state.zoom;

  function onMove(e) {
    item.x = Math.max(0, Math.round(origX + (e.clientX - startX) / z));
    item.y = Math.max(0, Math.round(origY + (e.clientY - startY) / z));
    renderCanvas();
  }
  function onUp() {
    window.removeEventListener("pointermove", onMove);
    window.removeEventListener("pointerup", onUp);
    if (state.selectedId === item.instance_id) fillPropsForm(item);
  }
  window.addEventListener("pointermove", onMove);
  window.addEventListener("pointerup", onUp);
}

function startResize(evt, item) {
  evt.preventDefault();
  const startX = evt.clientX;
  const startY = evt.clientY;
  const origW = item.w;
  const origH = item.h;
  const z = state.zoom;

  function onMove(e) {
    item.w = Math.max(10, Math.round(origW + (e.clientX - startX) / z));
    item.h = Math.max(10, Math.round(origH + (e.clientY - startY) / z));
    renderCanvas();
  }
  function onUp() {
    window.removeEventListener("pointermove", onMove);
    window.removeEventListener("pointerup", onUp);
    if (state.selectedId === item.instance_id) fillPropsForm(item);
  }
  window.addEventListener("pointermove", onMove);
  window.addEventListener("pointerup", onUp);
}

// ---------------- 屬性面板 ----------------

function findElement(instanceId) {
  return state.layout.elements.find((e) => e.instance_id === instanceId);
}

function selectElement(instanceId) {
  state.selectedId = instanceId;
  renderCanvas();
  const item = findElement(instanceId);
  if (item) fillPropsForm(item);
}

function fillPropsForm(item) {
  el("props-empty").hidden = true;
  el("props-form").hidden = false;
  el("p-instance-id").value = item.instance_id;
  el("p-module-id").value = item.module_id;
  el("p-x").value = item.x;
  el("p-y").value = item.y;
  el("p-w").value = item.w;
  el("p-h").value = item.h;
  el("p-z").value = item.z || 0;
  el("p-refresh").value = item.refresh_interval;
  el("p-config").value = JSON.stringify(item.config || {}, null, 2);
}

function applyProps() {
  const item = findElement(state.selectedId);
  if (!item) return;
  item.x = parseInt(el("p-x").value, 10) || 0;
  item.y = parseInt(el("p-y").value, 10) || 0;
  item.w = parseInt(el("p-w").value, 10) || 10;
  item.h = parseInt(el("p-h").value, 10) || 10;
  item.z = parseInt(el("p-z").value, 10) || 0;
  item.refresh_interval = parseInt(el("p-refresh").value, 10) || 30;
  try {
    item.config = JSON.parse(el("p-config").value);
  } catch (e) {
    alert("config 不是合法的 JSON：" + e.message);
    return;
  }
  renderCanvas();
}

function deleteSelected() {
  if (!state.selectedId) return;
  state.layout.elements = state.layout.elements.filter((e) => e.instance_id !== state.selectedId);
  state.selectedId = null;
  el("props-form").hidden = true;
  el("props-empty").hidden = false;
  renderCanvas();
}

// ---------------- 情境設定 ----------------

async function loadScenes(deviceId) {
  const scenes = await api(`/api/devices/${deviceId}/scenes`);
  el("scenes-json").value = JSON.stringify(scenes, null, 2);
}

async function saveScenes() {
  if (!state.deviceId) return;
  let parsed;
  try {
    parsed = JSON.parse(el("scenes-json").value);
  } catch (e) {
    alert("情境設定不是合法的 JSON：" + e.message);
    return;
  }
  await api(`/api/devices/${state.deviceId}/scenes`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(parsed),
  });
  alert("已儲存情境設定");
}

// ---------------- 即時預覽 ----------------

function startPreviewLoop() {
  setInterval(async () => {
    if (!state.deviceId) return;
    el("preview-img").src = `/api/devices/${state.deviceId}/frame.png?t=${Date.now()}`;
    try {
      const meta = await api(`/api/devices/${state.deviceId}/frame-meta`);
      el("preview-meta").textContent =
        `scene: ${meta.scene || "(default)"} / layout: ${meta.layout_id || "-"} / ` +
        `refresh: ${meta.refresh_mode} / dirty: ${meta.dirty_boxes.length}`;
    } catch (e) {
      el("preview-meta").textContent = "預覽讀取失敗：" + e.message;
    }
  }, 3000);
}

init().catch((e) => {
  console.error(e);
  alert("初始化失敗：" + e.message);
});
