"use strict";
/* epagerPi 排版編輯器：純 vanilla JS，不依賴任何外部 CDN 套件
 * （Pi 上可能沒有網路，編輯器本身也要能離線用）。
 *
 * 核心概念：#canvas 這個 DOM 元素的實際尺寸永遠等於「裝置真實像素解析度」
 * （2.13" pHAT 是 212x104，4.26" 微雪是 800x480，兩者各自照自己的實際輸出範圍），
 * 畫布上每個元件的 x/y/w/h 也都直接用裝置真實像素存放、直接當成 CSS px 套用，
 * 完全不用乘 zoom；「縮放」這件事整個交給 #canvas 本身的 CSS transform: scale()，
 * 所以存進 layout 的座標永遠是實際像素，跟編輯器目前開多大縮放無關，畫面上看起來
 * 多大純粹是視覺呈現問題。
 *
 * 切換裝置或視窗大小改變時，會自動算一個「符合可視範圍」的縮放倍率（放大很小的
 * 2.13" 畫面方便編輯、縮小較大的 4.26" 畫面避免超出螢幕），使用者手動改縮放輸入框
 * 之後就不會再自動覆蓋，除非按「符合視窗」。
 *
 * 格線貼齊：拖曳/縮放元件時，x/y/w/h 會貼齊 state.gridSize 這個固定間距（單位是裝置
 * 實際像素，不受縮放倍率影響）。存進 layout 的座標格式完全沒變，仍然是實際像素整數，
 * 格線只影響「拖曳時怎麼取整數」。縮放不能小於 MIN_ELEMENT_W/MIN_ELEMENT_H，避免
 * 拖出太細碎、對不齊的區塊。
 */

const MIN_ELEMENT_W = 16;
const MIN_ELEMENT_H = 16;

const state = {
  devices: [],
  modules: [],
  deviceId: null,
  profile: null,
  layoutId: null,
  layout: { elements: [] },
  selectedId: null,
  zoom: 1,
  autoFit: true,
  snapEnabled: true,
  gridSize: 4,
  assets: [],
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
    // 使用者自己打縮放值 = 手動接管，之後視窗改變大小不會再自動幫他改掉。
    state.autoFit = false;
    state.zoom = Math.max(0.1, parseFloat(e.target.value) || 1);
    renderCanvas();
  });
  el("fit-zoom-btn").addEventListener("click", () => {
    state.autoFit = true;
    applyFitZoom();
  });
  el("load-layout-btn").addEventListener("click", () => loadLayout(el("layout-id-input").value.trim()));
  el("save-layout-btn").addEventListener("click", saveLayout);
  el("apply-props-btn").addEventListener("click", applyProps);
  el("delete-el-btn").addEventListener("click", deleteSelected);
  el("save-scenes-btn").addEventListener("click", saveScenes);

  el("snap-toggle").addEventListener("change", (e) => {
    state.snapEnabled = e.target.checked;
    renderCanvas();
  });
  el("grid-size-input").addEventListener("change", (e) => {
    state.gridSize = Math.max(1, parseInt(e.target.value, 10) || 4);
    renderCanvas();
  });
  el("asset-upload-btn").addEventListener("click", uploadSelectedAsset);

  let resizeTimer = null;
  window.addEventListener("resize", () => {
    // 視窗大小改變時，只有在使用者還沒手動接管縮放的情況下才重新符合視窗，
    // debounce 一下避免拖動視窗邊框時瘋狂重算。
    if (!state.autoFit) return;
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(applyFitZoom, 150);
  });

  if (state.devices.length) {
    sel.value = state.devices[0].id;
    await selectDevice(state.devices[0].id);
  }

  await loadAssets();
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
  // 每個裝置的實際輸出解析度差很多（212x104 vs 800x480），切換裝置一律重新符合視窗，
  // 不然沿用上一個裝置的縮放倍率很容易一個爆版一個看不清楚。
  state.autoFit = true;
  applyFitZoom();
}

// ---------------- 縮放：符合可視範圍，不超出螢幕 ----------------

function computeAvailableCanvasArea() {
  const wrap = el("canvas-wrap");
  const topbar = document.querySelector(".topbar");
  const rect = wrap.getBoundingClientRect();
  const style = getComputedStyle(wrap);
  const padX = parseFloat(style.paddingLeft || "0") + parseFloat(style.paddingRight || "0");
  const padY = parseFloat(style.paddingTop || "0") + parseFloat(style.paddingBottom || "0");
  const topbarH = topbar ? topbar.getBoundingClientRect().height : 0;

  // wrap 目前的高度可能還沒被 CSS 的 max-height 限制生效（例如畫面還沒重排），
  // 保守一點直接用「視窗高度 - topbar - 一點邊界」當高度上限，避免算出超出螢幕的結果。
  const availW = Math.max(100, rect.width - padX - 6);
  const availH = Math.max(100, window.innerHeight - topbarH - padY - 40);
  return { w: availW, h: availH };
}

function computeFitZoom() {
  if (!state.profile) return 1;
  const [devW, devH] = state.profile.resolution;
  const { w: availW, h: availH } = computeAvailableCanvasArea();
  let zoom = Math.min(availW / devW, availH / devH);
  zoom = Math.max(0.1, Math.min(8, zoom));
  return Math.round(zoom * 100) / 100;
}

function applyFitZoom() {
  state.zoom = computeFitZoom();
  el("zoom-input").value = state.zoom;
  renderCanvas();
}

function updateZoomReadout() {
  const pct = Math.round(state.zoom * 100);
  el("zoom-readout").textContent = `${pct}%${state.autoFit ? "（已符合視窗）" : "（手動）"}`;
}

// ---------------- 格線貼齊 ----------------

function snapVal(v) {
  if (!state.snapEnabled) return Math.round(v);
  const g = state.gridSize || 1;
  return Math.round(v / g) * g;
}

function applyGridBackground(canvas) {
  if (!state.snapEnabled) {
    canvas.style.backgroundImage = "none";
    return;
  }
  const g = state.gridSize || 4;
  canvas.style.backgroundImage =
    "linear-gradient(to right, rgba(0,0,0,.07) 1px, transparent 1px)," +
    "linear-gradient(to bottom, rgba(0,0,0,.07) 1px, transparent 1px)";
  canvas.style.backgroundSize = `${g}px ${g}px`;
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
  const canvasScale = el("canvas-scale");
  if (!state.profile) return;
  const [w, h] = state.profile.resolution;
  const z = state.zoom;

  // #canvas 本身永遠是裝置的實際像素尺寸（畫布尺寸照實際尺寸），縮放完全交給 transform；
  // #canvas-scale 這個外層容器要另外撐出「縮放後的視覺尺寸」，滾動/版面計算才會正確，
  // 不然 transform 不影響版面尺寸，容器還是會維持未縮放前的大小。
  canvas.style.width = `${w}px`;
  canvas.style.height = `${h}px`;
  canvas.style.transform = `scale(${z})`;
  canvasScale.style.width = `${w * z}px`;
  canvasScale.style.height = `${h * z}px`;
  canvas.innerHTML = "";
  applyGridBackground(canvas);

  const elements = [...state.layout.elements].sort((a, b) => (a.z || 0) - (b.z || 0));
  for (const item of elements) {
    const div = document.createElement("div");
    div.className = "el" + (item.instance_id === state.selectedId ? " selected" : "");
    div.style.left = `${item.x}px`;
    div.style.top = `${item.y}px`;
    div.style.width = `${item.w}px`;
    div.style.height = `${item.h}px`;
    div.style.zIndex = String(item.z || 0);
    div.innerHTML = `<span class="el-label">${item.module_id}</span>`;

    const handle = document.createElement("div");
    handle.className = "resize-handle";
    // 抵銷外層 #canvas 的 scale(z)，讓縮放手把在任何縮放倍率下視覺大小都一樣好抓。
    handle.style.transform = `scale(${1 / z})`;
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

  updateZoomReadout();
}

function startDrag(evt, item) {
  evt.preventDefault();
  const startX = evt.clientX;
  const startY = evt.clientY;
  const origX = item.x;
  const origY = item.y;
  const z = state.zoom;

  function onMove(e) {
    item.x = Math.max(0, snapVal(origX + (e.clientX - startX) / z));
    item.y = Math.max(0, snapVal(origY + (e.clientY - startY) / z));
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
    item.w = Math.max(MIN_ELEMENT_W, snapVal(origW + (e.clientX - startX) / z));
    item.h = Math.max(MIN_ELEMENT_H, snapVal(origH + (e.clientY - startY) / z));
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

// ---------------- 圖片素材庫 ----------------

async function loadAssets() {
  try {
    state.assets = await api("/api/assets");
  } catch (e) {
    console.warn("素材庫讀取失敗：", e.message);
    state.assets = [];
  }
  renderAssetList();
}

function formatBytes(n) {
  if (!n && n !== 0) return "";
  if (n < 1024) return `${n}B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)}KB`;
  return `${(n / 1024 / 1024).toFixed(1)}MB`;
}

function renderAssetList() {
  const container = el("asset-list");
  if (!state.assets.length) {
    container.innerHTML = `<p class="hint">還沒有上傳過素材。</p>`;
    return;
  }
  container.innerHTML = state.assets
    .map(
      (a) => `
      <div class="asset-item" data-asset-id="${a.id}">
        <img src="/api/assets/${a.id}" alt="${a.original_filename || a.id}" loading="lazy" />
        <div class="asset-item-meta">
          <span title="${a.original_filename || ""}">${a.original_filename || a.id}</span>
          <span class="hint">${formatBytes(a.size)}</span>
        </div>
        <div class="asset-item-actions">
          <button type="button" class="asset-apply-btn" data-asset-id="${a.id}">套用</button>
          <button type="button" class="asset-delete-btn danger" data-asset-id="${a.id}">刪除</button>
        </div>
      </div>`
    )
    .join("");

  container.querySelectorAll(".asset-apply-btn").forEach((btn) => {
    btn.addEventListener("click", () => applyAssetToSelected(btn.dataset.assetId));
  });
  container.querySelectorAll(".asset-delete-btn").forEach((btn) => {
    btn.addEventListener("click", () => deleteAsset(btn.dataset.assetId));
  });
}

async function uploadSelectedAsset() {
  const input = el("asset-file-input");
  const file = input.files && input.files[0];
  if (!file) {
    alert("請先選一個圖片檔案");
    return;
  }
  const form = new FormData();
  form.append("file", file);
  try {
    await api("/api/assets", { method: "POST", body: form });
  } catch (e) {
    alert("上傳失敗：" + e.message);
    return;
  }
  input.value = "";
  await loadAssets();
}

async function deleteAsset(assetId) {
  if (!confirm("確定要刪除這個素材嗎？如果還有元件在用它，畫面會顯示「找不到素材」。")) return;
  try {
    await api(`/api/assets/${assetId}`, { method: "DELETE" });
  } catch (e) {
    alert("刪除失敗：" + e.message);
    return;
  }
  await loadAssets();
}

function applyAssetToSelected(assetId) {
  const item = findElement(state.selectedId);
  if (!item) {
    alert("請先在畫布上選取一個「圖片」元件");
    return;
  }
  if (item.module_id !== "image") {
    alert(`目前選取的是「${item.module_id}」元件，只有「圖片」模組的元件可以套用素材`);
    return;
  }
  item.config = item.config || {};
  item.config.asset_id = assetId;
  fillPropsForm(item);
  renderCanvas();
}

init().catch((e) => {
  console.error(e);
  alert("初始化失敗：" + e.message);
});
