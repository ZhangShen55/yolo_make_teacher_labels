const LABEL_TEXT = {
  sit: "sit 坐",
  stand: "stand 站",
  bbwriting: "bbwriting 写板书",
  teach: "teach 讲授演示",
  usephone: "usephone 使用手机",
  mic: "mic 手持麦克风",
};

const state = {
  mode: "single",
  page: 1,
  pageSize: 10,
  listPage: 1,
  listPageSize: 50,
  listTotal: 0,
  rows: [],
  currentIndex: 0,
  current: null,
  original: null,
  image: new Image(),
  canvasScale: 1,
  canvasOffsetX: 0,
  canvasOffsetY: 0,
  drag: null,
};

const el = {};

function $(id) {
  return document.getElementById(id);
}

function labelsFromControls(prefix = "") {
  const pose = document.querySelector(`${prefix} input[name="${prefix ? prefix : ""}pose"]:checked`)?.value;
  const labels = [];
  if (pose) labels.push(pose);
  const bb = document.querySelector(`${prefix} input[value="bbwriting"]`);
  const teach = document.querySelector(`${prefix} input[value="teach"]`);
  const usephone = document.querySelector(`${prefix} input[value="usephone"]`);
  const mic = document.querySelector(`${prefix} input[value="mic"]`);
  if (bb?.checked) labels.push("bbwriting");
  if (teach?.checked) labels.push("teach");
  if (usephone?.checked) labels.push("usephone");
  if (mic?.checked) labels.push("mic");
  return labels;
}

function setStatus(text) {
  el.statusText.textContent = text;
}

function formatValidationError(errorItem) {
  const loc = Array.isArray(errorItem.loc) ? errorItem.loc.join(".") : "";
  return [loc, errorItem.msg].filter(Boolean).join(": ");
}

function formatApiError(detail, fallback) {
  if (Array.isArray(detail)) {
    return detail.map(formatValidationError).join("; ");
  }
  if (detail && typeof detail === "object") {
    if (typeof detail.msg === "string") return formatValidationError(detail);
    return JSON.stringify(detail, null, 2);
  }
  return String(detail || fallback || "请求失败");
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    const text = await response.text();
    let detail = text;
    try {
      detail = JSON.parse(text).detail || text;
    } catch {
      detail = text;
    }
    throw new Error(formatApiError(detail, `HTTP ${response.status}`));
  }
  return response.json();
}

function queryParams(includePage = false) {
  const params = new URLSearchParams();
  if (el.searchInput.value.trim()) params.set("q", el.searchInput.value.trim());
  if (el.labelFilter.value) params.set("label", el.labelFilter.value);
  if (el.reviewFilter.value) params.set("needs_review", el.reviewFilter.value);
  if (includePage) {
    params.set("page", state.page);
    state.pageSize = Number(el.pageSizeSelect.value);
    params.set("page_size", state.pageSize);
  }
  return params.toString();
}

async function loadSummary() {
  const summary = await api("/api/dataset/summary");
  el.datasetRoot.textContent = summary.dataset_root;
  if (document.activeElement !== el.datasetPathInput) {
    el.datasetPathInput.value = summary.dataset_root;
  }
  el.summary.textContent = [
    `total ${summary.total}`,
    `active ${summary.active}`,
    `rejected ${summary.rejected}`,
    `sit ${summary.label_counts.sit}`,
    `stand ${summary.label_counts.stand}`,
    `bbwriting ${summary.label_counts.bbwriting}`,
    `teach ${summary.label_counts.teach}`,
    `usephone ${summary.label_counts.usephone}`,
    `mic ${summary.label_counts.mic}`,
  ].join(" | ");
}

async function loadDatasetFromInput() {
  const datasetRoot = el.datasetPathInput.value.trim();
  if (!datasetRoot) {
    setStatus("请输入数据集目录");
    return;
  }
  try {
    setStatus("正在加载数据集...");
    const result = await api("/api/dataset/load", {
      method: "POST",
      body: JSON.stringify({ dataset_root: datasetRoot }),
    });
    state.page = 1;
    state.listPage = 1;
    state.rows = [];
    state.currentIndex = 0;
    state.current = null;
    state.original = null;
    await refreshAll();
    setStatus(`已加载目录：${result.validation.dataset_root}，图片 ${result.validation.image_count} 张`);
  } catch (error) {
    setStatus(error.message);
  }
}

async function loadRows() {
  const data = await api(`/api/images?${queryParams(false)}&page=${state.listPage}&page_size=${state.listPageSize}`);
  state.rows = data.items;
  state.listTotal = data.total;
  renderImageList();
  renderListPager(data);
  if (state.rows.length && !state.current) {
    await loadDetail(0);
  }
}

async function resetListAndRefresh() {
  state.listPage = 1;
  state.current = null;
  state.original = null;
  await refreshAll();
}

function renderImageList() {
  el.imageList.innerHTML = "";
  for (const [index, row] of state.rows.entries()) {
    const div = document.createElement("div");
    div.className = `image-row ${index === state.currentIndex ? "active" : ""}`;
    div.innerHTML = `<div class="mono">${row.file_name}</div><div class="labels">${row.labels.map(label => `<span class="tag">${label}</span>`).join("")}</div>`;
    div.onclick = () => loadDetail(index);
    el.imageList.appendChild(div);
  }
}

function renderListPager(data) {
  const totalPages = Math.max(1, Math.ceil(data.total / data.page_size));
  el.listPageInfo.textContent = `${data.page}/${totalPages}`;
  el.listPrevPageBtn.disabled = data.page <= 1;
  el.listNextPageBtn.disabled = data.page >= totalPages;
}

async function loadDetail(index) {
  if (!state.rows[index]) return;
  state.currentIndex = index;
  const imageId = state.rows[index].image_id;
  state.current = await api(`/api/images/${imageId}`);
  state.original = structuredClone(state.current);
  state.image = new Image();
  state.image.onload = drawCanvas;
  state.image.src = `/api/images/${imageId}/file?ts=${Date.now()}`;
  updateInspector();
  renderImageList();
}

function currentBox() {
  if (!state.current?.boxes?.length) {
    state.current.boxes = [{ box_id: "0", box_xyxy: [10, 10, 100, 100], labels: ["stand"] }];
  }
  return state.current.boxes[0];
}

function updateInspector() {
  if (!state.current) return;
  el.currentFile.textContent = state.current.file_name;
  const box = currentBox();
  const labels = box.labels || [];
  document.querySelectorAll('input[name="pose"]').forEach(input => {
    input.checked = labels.includes(input.value);
  });
  el.bbwritingCheck.checked = labels.includes("bbwriting");
  el.teachCheck.checked = labels.includes("teach");
  el.usephoneCheck.checked = labels.includes("usephone");
  el.micCheck.checked = labels.includes("mic");
  const [x1, y1, x2, y2] = box.box_xyxy;
  el.x1Input.value = x1;
  el.y1Input.value = y1;
  el.x2Input.value = x2;
  el.y2Input.value = y2;
  updateNormPreview();
}

function syncBoxFromInputs() {
  const box = currentBox();
  box.box_xyxy = [el.x1Input, el.y1Input, el.x2Input, el.y2Input].map(input => Number(input.value));
  box.labels = labelsFromControls();
  clampBox(box.box_xyxy);
  drawCanvas();
  updateNormPreview();
}

function clampBox(box) {
  box[0] = Math.round(Math.max(0, Math.min(state.current.width - 1, box[0])));
  box[1] = Math.round(Math.max(0, Math.min(state.current.height - 1, box[1])));
  box[2] = Math.round(Math.max(0, Math.min(state.current.width - 1, box[2])));
  box[3] = Math.round(Math.max(0, Math.min(state.current.height - 1, box[3])));
  if (box[2] < box[0]) [box[0], box[2]] = [box[2], box[0]];
  if (box[3] < box[1]) [box[1], box[3]] = [box[3], box[1]];
  if (box[2] - box[0] < 4) box[2] = Math.min(state.current.width - 1, box[0] + 4);
  if (box[3] - box[1] < 4) box[3] = Math.min(state.current.height - 1, box[1] + 4);
}

function updateNormPreview() {
  if (!state.current) return;
  const [x1, y1, x2, y2] = currentBox().box_xyxy;
  const x = ((x1 + x2) / 2 / state.current.width).toFixed(6);
  const y = ((y1 + y2) / 2 / state.current.height).toFixed(6);
  const w = ((x2 - x1) / state.current.width).toFixed(6);
  const h = ((y2 - y1) / state.current.height).toFixed(6);
  el.normPreview.textContent = `YOLO: ${x} ${y} ${w} ${h}`;
}

function imageToCanvas([x, y]) {
  return [state.canvasOffsetX + x * state.canvasScale, state.canvasOffsetY + y * state.canvasScale];
}

function canvasToImage([x, y]) {
  return [(x - state.canvasOffsetX) / state.canvasScale, (y - state.canvasOffsetY) / state.canvasScale];
}

function drawCanvas() {
  const canvas = el.imageCanvas;
  const panel = canvas.parentElement;
  if (!state.current || !state.image.complete) return;
  const maxW = panel.clientWidth - 24;
  const maxH = panel.clientHeight - 24;
  state.canvasScale = Math.min(maxW / state.current.width, maxH / state.current.height);
  canvas.width = Math.round(state.current.width * state.canvasScale);
  canvas.height = Math.round(state.current.height * state.canvasScale);
  state.canvasOffsetX = 0;
  state.canvasOffsetY = 0;
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(state.image, 0, 0, canvas.width, canvas.height);
  const box = currentBox();
  const [x1, y1] = imageToCanvas([box.box_xyxy[0], box.box_xyxy[1]]);
  const [x2, y2] = imageToCanvas([box.box_xyxy[2], box.box_xyxy[3]]);
  ctx.strokeStyle = "red";
  ctx.lineWidth = 4;
  ctx.strokeRect(x1, y1, x2 - x1, y2 - y1);
  ctx.fillStyle = "blue";
  ctx.font = "bold 18px sans-serif";
  ctx.textAlign = "center";
  box.labels.forEach((label, i) => ctx.fillText(label, (x1 + x2) / 2, (y1 + y2) / 2 + i * 20));
  for (const [hx, hy] of handlePoints([x1, y1, x2, y2])) {
    ctx.fillStyle = "#fff";
    ctx.strokeStyle = "red";
    ctx.lineWidth = 2;
    ctx.fillRect(hx - 5, hy - 5, 10, 10);
    ctx.strokeRect(hx - 5, hy - 5, 10, 10);
  }
}

function handlePoints([x1, y1, x2, y2]) {
  const mx = (x1 + x2) / 2;
  const my = (y1 + y2) / 2;
  return [[x1, y1], [mx, y1], [x2, y1], [x2, my], [x2, y2], [mx, y2], [x1, y2], [x1, my]];
}

function hitTest(event) {
  const rect = el.imageCanvas.getBoundingClientRect();
  const x = event.clientX - rect.left;
  const y = event.clientY - rect.top;
  const box = currentBox();
  const [x1, y1] = imageToCanvas([box.box_xyxy[0], box.box_xyxy[1]]);
  const [x2, y2] = imageToCanvas([box.box_xyxy[2], box.box_xyxy[3]]);
  const handles = ["nw", "n", "ne", "e", "se", "s", "sw", "w"];
  const points = handlePoints([x1, y1, x2, y2]);
  for (let i = 0; i < points.length; i++) {
    if (Math.abs(x - points[i][0]) <= 8 && Math.abs(y - points[i][1]) <= 8) return { type: handles[i], x, y };
  }
  if (x >= x1 && x <= x2 && y >= y1 && y <= y2) return { type: "move", x, y };
  return null;
}

function onCanvasDown(event) {
  const hit = hitTest(event);
  if (!hit) return;
  state.drag = { ...hit, original: [...currentBox().box_xyxy] };
}

function onCanvasMove(event) {
  if (!state.drag) return;
  const rect = el.imageCanvas.getBoundingClientRect();
  const [ix, iy] = canvasToImage([event.clientX - rect.left, event.clientY - rect.top]);
  const [sx, sy] = canvasToImage([state.drag.x, state.drag.y]);
  const dx = ix - sx;
  const dy = iy - sy;
  const box = currentBox().box_xyxy;
  const original = state.drag.original;
  box.splice(0, 4, ...resizeBox(original, state.drag.type, dx, dy));
  clampBox(box);
  updateInspector();
  drawCanvas();
}

function resizeBox(original, type, dx, dy) {
  let [x1, y1, x2, y2] = original;
  if (type === "move") return [x1 + dx, y1 + dy, x2 + dx, y2 + dy];
  if (type.includes("w")) x1 += dx;
  if (type.includes("e")) x2 += dx;
  if (type.includes("n")) y1 += dy;
  if (type.includes("s")) y2 += dy;
  return [x1, y1, x2, y2];
}

async function saveCurrent(goNext = false) {
  if (!state.current) return;
  try {
    syncBoxFromInputs();
    const payload = { boxes: state.current.boxes, needs_review: state.current.needs_review };
    const saved = await api(`/api/images/${state.current.image_id}/annotation`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
    state.current = saved;
    state.original = structuredClone(saved);
    setStatus(`已保存 ${saved.file_name}：${saved.labels.join(" + ")}`);
    await loadSummary();
    await loadRows();
    if (goNext) await nextImage();
  } catch (error) {
    console.error(error);
    setStatus(`保存失败：${error.message}`);
  }
}

async function rejectCurrent(imageId = state.current?.image_id) {
  if (!imageId) return;
  if (!confirm(`确认移到 rejected：${imageId}？`)) return;
  try {
    await api(`/api/images/${imageId}/reject`, { method: "POST", body: JSON.stringify({ reason: "manual_reject" }) });
    setStatus(`已移到 rejected：${imageId}`);
    state.current = null;
    await loadSummary();
    if (state.mode === "batch") await loadBatch();
    await loadRows();
  } catch (error) {
    console.error(error);
    setStatus(`拒收失败：${error.message}`);
  }
}

async function nextImage() {
  if (state.currentIndex < state.rows.length - 1) {
    await loadDetail(state.currentIndex + 1);
    return;
  }
  if (state.listPage * state.listPageSize < state.listTotal) {
    state.listPage += 1;
    state.current = null;
    await loadRows();
  }
}

async function prevImage() {
  if (state.currentIndex > 0) {
    await loadDetail(state.currentIndex - 1);
    return;
  }
  if (state.listPage > 1) {
    state.listPage -= 1;
    state.current = null;
    await loadRows();
    if (state.rows.length) await loadDetail(state.rows.length - 1);
  }
}

async function loadBatch() {
  const data = await api(`/api/images/batch?${queryParams(true)}`);
  el.pageInfo.textContent = `第 ${data.page} 页 / 共 ${Math.max(1, Math.ceil(data.total / data.page_size))} 页，总 ${data.total}`;
  el.batchGrid.innerHTML = "";
  for (const item of data.items) {
    el.batchGrid.appendChild(batchCard(item));
  }
}

function batchCard(item) {
  const card = document.createElement("div");
  card.className = "batch-card";
  const box = item.boxes[0];
  const labels = box?.labels || [];
  card.innerHTML = `
    <div class="batch-image-wrap">
      <img src="${item.image_url}?ts=${Date.now()}" alt="${item.file_name}">
    </div>
    <div class="batch-body">
      <div class="mono">${item.file_name}</div>
      <label><input type="radio" name="${item.image_id}pose" value="sit" ${labels.includes("sit") ? "checked" : ""}> sit 坐</label>
      <label><input type="radio" name="${item.image_id}pose" value="stand" ${labels.includes("stand") ? "checked" : ""}> stand 站</label>
      <label><input type="checkbox" value="bbwriting" ${labels.includes("bbwriting") ? "checked" : ""}> bbwriting 写板书</label>
      <label><input type="checkbox" value="teach" ${labels.includes("teach") ? "checked" : ""}> teach 讲授演示</label>
      <label><input type="checkbox" value="usephone" ${labels.includes("usephone") ? "checked" : ""}> usephone 使用手机</label>
      <label><input type="checkbox" value="mic" ${labels.includes("mic") ? "checked" : ""}> mic 手持麦克风</label>
      <div class="batch-actions">
        <button data-action="save">保存</button>
        <button data-action="detail">精修</button>
        <button data-action="reject" class="danger">拒收</button>
      </div>
    </div>`;
  const wrap = card.querySelector(".batch-image-wrap");
  if (box) {
    const [x1, y1, x2, y2] = box.box_xyxy;
    const overlay = document.createElement("div");
    overlay.className = "batch-box";
    overlay.style.left = `${(x1 / item.width) * 100}%`;
    overlay.style.top = `${(y1 / item.height) * 100}%`;
    overlay.style.width = `${((x2 - x1) / item.width) * 100}%`;
    overlay.style.height = `${((y2 - y1) / item.height) * 100}%`;
    wrap.appendChild(overlay);
    const label = document.createElement("div");
    label.className = "batch-label";
    label.style.left = `${(((x1 + x2) / 2) / item.width) * 100}%`;
    label.style.top = `${(((y1 + y2) / 2) / item.height) * 100}%`;
    label.textContent = labels.join(" + ");
    wrap.appendChild(label);
  }
  card.querySelector('[data-action="save"]').onclick = async () => {
    try {
      if (!box) {
        setStatus(`保存失败：${item.file_name} 无 bbox，请进入精修模式先画框`);
        return;
      }
      const newLabels = labelsFromBatchCard(card, item.image_id);
      const saved = await api(`/api/images/${item.image_id}/annotation`, {
        method: "PATCH",
        body: JSON.stringify({ boxes: [{ ...box, labels: newLabels }], needs_review: item.needs_review }),
      });
      setStatus(`已保存 ${saved.file_name}：${saved.labels.join(" + ")}`);
      await loadSummary();
      await loadRows();
      await loadBatch();
    } catch (error) {
      console.error(error);
      setStatus(`保存失败：${error.message}`);
    }
  };
  card.querySelector('[data-action="detail"]').onclick = async () => {
    switchMode("single");
    const index = state.rows.findIndex(row => row.image_id === item.image_id);
    await loadDetail(Math.max(0, index));
  };
  card.querySelector('[data-action="reject"]').onclick = () => rejectCurrent(item.image_id);
  return card;
}

function labelsFromBatchCard(card, imageId) {
  const labels = [];
  const pose = card.querySelector(`input[name="${imageId}pose"]:checked`)?.value;
  if (pose) labels.push(pose);
  if (card.querySelector('input[value="bbwriting"]').checked) labels.push("bbwriting");
  if (card.querySelector('input[value="teach"]').checked) labels.push("teach");
  if (card.querySelector('input[value="usephone"]').checked) labels.push("usephone");
  if (card.querySelector('input[value="mic"]').checked) labels.push("mic");
  return labels;
}

async function switchMode(mode) {
  state.mode = mode;
  el.singleModeBtn.classList.toggle("active", mode === "single");
  el.batchModeBtn.classList.toggle("active", mode === "batch");
  el.singleView.classList.toggle("hidden", mode !== "single");
  el.batchView.classList.toggle("hidden", mode !== "batch");
  if (mode === "batch") await loadBatch();
}

async function refreshAll() {
  await loadSummary();
  await loadRows();
  if (state.mode === "batch") await loadBatch();
}

function bindEvents() {
  el.singleModeBtn.onclick = () => switchMode("single");
  el.batchModeBtn.onclick = () => switchMode("batch");
  el.refreshBtn.onclick = refreshAll;
  el.loadDatasetBtn.onclick = loadDatasetFromInput;
  el.datasetPathInput.addEventListener("keydown", async event => {
    if (event.key === "Enter") await loadDatasetFromInput();
  });
  el.searchInput.oninput = resetListAndRefresh;
  el.labelFilter.onchange = resetListAndRefresh;
  el.reviewFilter.onchange = resetListAndRefresh;
  el.listPrevPageBtn.onclick = async () => {
    state.listPage = Math.max(1, state.listPage - 1);
    state.current = null;
    await loadRows();
  };
  el.listNextPageBtn.onclick = async () => {
    if (state.listPage * state.listPageSize >= state.listTotal) return;
    state.listPage += 1;
    state.current = null;
    await loadRows();
  };
  el.pageSizeSelect.onchange = async () => {
    state.pageSize = Number(el.pageSizeSelect.value);
    state.page = 1;
    await loadBatch();
  };
  el.saveBtn.onclick = () => saveCurrent(false);
  el.saveNextBtn.onclick = () => saveCurrent(true);
  el.rejectBtn.onclick = () => rejectCurrent();
  el.resetBtn.onclick = () => {
    state.current = structuredClone(state.original);
    updateInspector();
    drawCanvas();
  };
  el.prevPageBtn.onclick = async () => {
    state.page = Math.max(1, state.page - 1);
    await loadBatch();
  };
  el.nextPageBtn.onclick = async () => {
    state.page += 1;
    await loadBatch();
  };
  [el.x1Input, el.y1Input, el.x2Input, el.y2Input, el.bbwritingCheck, el.teachCheck, el.usephoneCheck, el.micCheck].forEach(input => {
    input.onchange = syncBoxFromInputs;
  });
  document.querySelectorAll('input[name="pose"]').forEach(input => {
    input.onchange = syncBoxFromInputs;
  });
  el.imageCanvas.addEventListener("mousedown", onCanvasDown);
  window.addEventListener("mousemove", onCanvasMove);
  window.addEventListener("mouseup", () => { state.drag = null; });
  window.addEventListener("resize", drawCanvas);
  document.addEventListener("keydown", async event => {
    if (event.key === "ArrowRight") await nextImage();
    if (event.key === "ArrowLeft") await prevImage();
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
      event.preventDefault();
      await saveCurrent(false);
    }
    if (event.shiftKey && event.key === "Enter") await saveCurrent(true);
    if (event.key === "Delete") await rejectCurrent();
    if (event.key === "Escape" && state.original) {
      state.current = structuredClone(state.original);
      updateInspector();
      drawCanvas();
    }
  });
}

function collectElements() {
  for (const id of [
    "datasetRoot", "summary", "statusText", "imageList", "imageCanvas", "currentFile",
    "bbwritingCheck", "teachCheck", "usephoneCheck", "micCheck", "x1Input", "y1Input", "x2Input", "y2Input",
    "normPreview", "saveBtn", "saveNextBtn", "rejectBtn", "resetBtn", "singleModeBtn",
    "batchModeBtn", "singleView", "batchView", "batchGrid", "prevPageBtn", "nextPageBtn",
    "pageInfo", "searchInput", "labelFilter", "reviewFilter", "refreshBtn",
    "pageSizeSelect", "datasetPathInput", "loadDatasetBtn", "listPrevPageBtn",
    "listNextPageBtn", "listPageInfo",
  ]) {
    el[id] = $(id);
  }
}

collectElements();
bindEvents();
refreshAll().catch(error => setStatus(error.message));
