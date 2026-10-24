var state = {
  path: "",
  q: "",
  sort: "rel_path",
  direction: "asc",
  page: 1,
  pageSize: 100,
  total: 0,
  items: [],
  tree: null,
  stats: null,
  scan: null,
  scanTimer: null,
  searchTimer: null,
  listToken: 0,
  duplicates: false,
  sidebarCollapsed: false,
  hash: null,
  hashTimer: null,
  uploading: false,
  uploadPlan: [],
  previewSettings: null,
  previewTexts: {},
  previewCoverage: null,
  previewCaseStyle: null,
  previewExpanded: {},
  previewData: null,
  previewFaceIndex: 0,
  previewFontFace: null,
  previewFontFamily: "",
  previewRequestToken: 0,
  previewCustom: "",
  previewSize: 28,
  projectSettings: null,
  pendingDeleteId: null,
  pendingDeleteIds: [],
  selectedIds: [],
  recycleItems: []
};

function $(id) {
  return document.getElementById(id);
}

function esc(value) {
  return String(value === null || value === undefined ? "" : value).replace(/[&<>"']/g, function (ch) {
    if (ch === "&") return "&amp;";
    if (ch === "<") return "&lt;";
    if (ch === ">") return "&gt;";
    if (ch === '"') return "&quot;";
    return "&#39;";
  });
}

function formatBytes(bytes) {
  var n = Number(bytes || 0);
  if (!isFinite(n) || n <= 0) return "0 B";
  var units = ["B", "KB", "MB", "GB", "TB"];
  var i = 0;
  while (n >= 1024 && i < units.length - 1) {
    n = n / 1024;
    i++;
  }
  return (i === 0 ? String(Math.round(n)) : n.toFixed(1)) + " " + units[i];
}

function formatDate(ns) {
  if (!ns) return "-";
  try {
    return new Date(Number(ns) / 1000000).toLocaleString("zh-CN", { hour12: false });
  } catch (err) {
    return "-";
  }
}

function formatIsoDate(value) {
  if (!value) return "永久";
  try {
    return new Date(value).toLocaleString("zh-CN", { hour12: false });
  } catch (err) {
    return String(value);
  }
}

function statusBadge(item) {
  if (item.parse_status === "error") {
    var title = item.parse_error ? " title=\"" + esc(item.parse_error) + "\"" : "";
    return "<span class=\"badge error\"" + title + ">解析失败</span>";
  }
  if (item.parse_status === "ok") return "<span class=\"badge ok\">正常</span>";
  return "<span class=\"badge pending\">待解析</span>";
}

async function fetchJSON(url, options) {
  var response = await fetch(url, options);
  if (!response.ok) {
    var text = await response.text();
    var message = text || response.statusText;
    try {
      var parsed = JSON.parse(text);
      if (parsed && parsed.detail) {
        message = typeof parsed.detail === "string" ? parsed.detail : JSON.stringify(parsed.detail);
      }
    } catch (err) {}
    throw new Error(message);
  }
  return response.json();
}

var toastTimer = null;
function showToast(message, type) {
  var el = $("toast");
  el.textContent = message;
  el.className = "toast" + (type === "error" ? " error" : "");
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(function () {
    el.hidden = true;
  }, 3500);
}

function renderStats() {
  var s = state.stats;
  $("statTotal").textContent = s ? s.count : "-";
  $("statSize").textContent = s ? formatBytes(s.size) : "-";
  $("statFolders").textContent = s ? s.folders : "-";
  $("statErrors").textContent = s ? s.errors : "-";
  var banner = $("dupBanner");
  if (s && s.duplicate_groups) {
    banner.hidden = false;
    $("dupGroups").textContent = s.duplicate_groups;
    $("dupFiles").textContent = s.duplicate_files;
    $("dupWaste").textContent = formatBytes(s.wasted_size);
  } else {
    banner.hidden = true;
  }
}

function renderTree() {
  var root = state.tree;
  if (!root) {
    $("tree").innerHTML = "";
    return;
  }
  var html = "<button class=\"tree-item" + (state.path === "" ? " active" : "") + "\" data-path=\"\"><span class=\"tree-name\">全部字体</span><span class=\"tree-count\">" + root.count + "</span></button>";
  html += renderTreeNodes(root.children || [], "");
  $("tree").innerHTML = html;
}

function renderTreeNodes(nodes, parentPath) {
  var html = "";
  nodes.forEach(function (node) {
    var path = parentPath ? parentPath + "/" + node.name : node.name;
    html += "<div class=\"tree-group\">";
    html += "<button class=\"tree-item" + (state.path === path ? " active" : "") + "\" data-path=\"" + esc(path) + "\"><span class=\"tree-name\">▸ " + esc(node.name) + "</span><span class=\"tree-count\">" + node.count + "</span></button>";
    if (node.children && node.children.length) {
      html += "<div class=\"tree-children\">" + renderTreeNodes(node.children, path) + "</div>";
    }
    html += "</div>";
  });
  return html;
}

function renderList() {
  var tbody = $("fontRows");
  var empty = $("empty");
  if (!state.items.length) {
    tbody.innerHTML = "";
    empty.hidden = false;
    $("emptyText").textContent = state.q || state.path ? "当前筛选条件下没有字体。" : "点击右上角“扫描字体”开始索引。";
    updateBatchBar();
    return;
  }
  empty.hidden = true;
  var html = "";
  state.items.forEach(function (item) {
    var family = item.family || "—";
    var sub = item.subfamily ? "<div class=\"muted\">" + esc(item.subfamily) + "</div>" : "";
    var dup = item.duplicate_count > 1;
    var dupIndex = Number(item.duplicate_index || 0);
    var rowClass = dup ? (dupIndex === 0 ? "dup-original" : "dup-copy") : "";
    var dupBadge = "";
    if (dup) {
      dupBadge = dupIndex === 0
        ? '<span class="dup-badge original">原始</span>'
        : '<span class="dup-badge copy">重复x' + dupIndex + '</span>';
    }
    var checked = state.selectedIds.indexOf(item.id) !== -1 ? " checked" : "";
    html += rowClass ? '<tr class="' + rowClass + '">' : "<tr>";
    html += '<td class="select-cell"><input type="checkbox" class="row-check" data-id="' + item.id + '"' + checked + '></td>';
    html += "<td><button class=\"file-link\" data-id=\"" + item.id + "\">" + esc(item.name) + "</button>" + dupBadge + "<div class=\"path\" title=\"" + esc(item.rel_path) + "\">" + esc(item.rel_path) + "</div></td>";
    html += "<td>" + esc(family) + sub + "</td>";
    html += "<td><span class=\"badge\">" + esc(String(item.ext || "").replace(".", "").toUpperCase()) + "</span></td>";
    html += "<td class=\"num\">" + formatBytes(item.size) + "</td>";
    html += "<td>" + formatDate(item.created_ns) + "</td>";
    html += "<td>" + formatDate(item.mtime_ns) + "</td>";
    html += "<td>" + esc(item.version || "—") + "</td>";
    html += "<td class=\"num\">" + (item.face_count || 1) + "</td>";
    html += "<td>" + statusBadge(item) + (dup ? ' <button type="button" class="row-delete" data-delete-row="' + item.id + '">删除</button>' : "") + "</td>";
    html += "</tr>";
  });
  tbody.innerHTML = html;
  updateBatchBar();
}

function renderPager() {
  var pages = Math.max(1, Math.ceil(state.total / state.pageSize));
  $("pageInfo").textContent = "第 " + state.page + " / " + pages + " 页 · 共 " + state.total + " 个";
  $("prevBtn").disabled = state.page <= 1;
  $("nextBtn").disabled = state.page >= pages;
}

async function loadFonts() {
  var token = ++state.listToken;
  state.selectedIds = [];
  var params = new URLSearchParams({
    path: state.path,
    q: state.q,
    sort: state.sort,
    direction: state.direction,
    page: String(state.page),
    page_size: String(state.pageSize),
    duplicates: state.duplicates ? "1" : "0"
  });
  try {
    var data = await fetchJSON("/api/fonts?" + params.toString());
    if (token !== state.listToken) return;
    state.items = data.items;
    state.total = data.total;
    state.page = data.page;
    state.pageSize = data.page_size;
    renderList();
    renderPager();
  } catch (err) {
    showToast("加载字体列表失败：" + err.message, "error");
  }
}

async function refreshAll() {
  try {
    var results = await Promise.all([fetchJSON("/api/stats"), fetchJSON("/api/tree")]);
    state.stats = results[0];
    state.tree = results[1];
    renderStats();
    renderTree();
    await loadFonts();
  } catch (err) {
    showToast("刷新失败：" + err.message, "error");
  }
}

function renderScan(scan) {
  var bar = $("scanbar");
  if (!scan || (!scan.running && !scan.total && !scan.finished_at)) {
    bar.hidden = true;
    return;
  }
  bar.hidden = false;
  var percent = scan.total ? Math.min(100, Math.round(scan.done * 100 / scan.total)) : 0;
  $("progressFill").style.width = percent + "%";
  var text = "";
  if (scan.running) {
    text = "正在扫描 " + scan.done + "/" + scan.total;
    if (scan.current) text += " · " + scan.current;
    if (scan.errors) text += " · 失败 " + scan.errors;
  } else if (scan.error) {
    text = "扫描失败：" + scan.error;
  } else {
    text = "扫描完成：" + scan.done + " 个文件";
    if (scan.errors) text += "，失败 " + scan.errors;
  }
  $("scanText").textContent = text;
}

async function pollScan() {
  try {
    var scan = await fetchJSON("/api/scan/status");
    var wasRunning = state.scan && state.scan.running;
    state.scan = scan;
    renderScan(scan);
    $("scanBtn").disabled = !!scan.running;
    $("hashBtn").disabled = !!scan.running || !!(state.hash && state.hash.running);
    $("uploadBtn").disabled = !!scan.running;
    if (scan.running) {
      clearTimeout(state.scanTimer);
      state.scanTimer = setTimeout(pollScan, 800);
    } else {
      if (wasRunning) {
        await refreshAll();
      }
      clearTimeout(state.scanTimer);
      state.scanTimer = setTimeout(function () {
        $("scanbar").hidden = true;
      }, 2500);
    }
  } catch (err) {
    showToast("读取扫描状态失败：" + err.message, "error");
  }
}

async function startScan() {
  try {
    $("scanBtn").disabled = true;
    var scan = await fetchJSON("/api/scan", { method: "POST" });
    state.scan = scan;
    renderScan(scan);
    pollScan();
  } catch (err) {
    showToast("启动扫描失败：" + err.message, "error");
    $("scanBtn").disabled = false;
  }
}

async function openDetail(id) {
  $("drawer").hidden = false;
  $("drawerBackdrop").hidden = false;
  $("drawerTitle").textContent = "加载中...";
  $("drawerBody").innerHTML = "<div class=\"muted\">正在读取字体信息...</div>";
  try {
    var data = await fetchJSON("/api/fonts/" + id);
    renderDetail(data);
  } catch (err) {
    $("drawerBody").innerHTML = "<div class=\"error-box\">加载失败：" + esc(err.message) + "</div>";
  }
}

function hashRow(label, value, error) {
  if (!value) {
    return "<div class=\"detail-grid\"><dt>" + label + "</dt><dd class=\"muted\">" + esc(error || "未计算") + "</dd></div>";
  }
  return "<div class=\"detail-grid\"><dt>" + label + "</dt><dd><div class=\"hash-row\"><code>" + esc(value) + "</code><button class=\"copy-btn\" data-copy=\"" + esc(value) + "\">复制</button></div></dd></div>";
}

function renderDetail(data) {
  $("drawerTitle").textContent = data.name;
  var html = "<dl class=\"detail-grid\">";
  html += "<dt>文件名</dt><dd>" + esc(data.name) + "</dd>";
  html += "<dt>相对路径</dt><dd>" + esc(data.rel_path) + "</dd>";
  html += "<dt>格式</dt><dd>" + esc(String(data.ext || "").replace(".", "").toUpperCase()) + "</dd>";
  html += "<dt>大小</dt><dd>" + formatBytes(data.size) + " (" + data.size + " 字节)</dd>";
  html += "<dt>修改时间</dt><dd>" + formatDate(data.mtime_ns) + "</dd>";
  html += "<dt>字体家族</dt><dd>" + esc(data.family || "—") + "</dd>";
  html += "<dt>子家族</dt><dd>" + esc(data.subfamily || "—") + "</dd>";
  html += "<dt>完整名称</dt><dd>" + esc(data.full_name || "—") + "</dd>";
  html += "<dt>版本</dt><dd>" + esc(data.version || "—") + "</dd>";
  html += "<dt>PostScript</dt><dd>" + esc(data.postscript_name || "—") + "</dd>";
  html += "<dt>面数</dt><dd>" + (data.face_count || 1) + "</dd>";
  html += "<dt>字形数</dt><dd>" + (data.glyph_count || "—") + "</dd>";
  html += "<dt>Units/Em</dt><dd>" + (data.units_per_em || "—") + "</dd>";
  html += "<dt>解析状态</dt><dd>" + statusBadge(data) + "</dd>";
  html += "</dl>";
  html += '<div class="detail-section preview-section">';
  html += '<h3>字体预览</h3>';
  html += '<div class="preview-controls"><label>字号 <input id="previewSize" type="range" min="12" max="72" value="28"></label>';
  if (data.faces && data.faces.length > 1) {
    html += '<label>Face <select id="previewFace">';
    data.faces.forEach(function (face) {
      html += '<option value="' + face.face_index + '">' + esc(face.family || ("Face " + face.face_index)) + ' · ' + esc(face.subfamily || "") + '</option>';
    });
    html += '</select></label>';
  }
  html += '</div>';
  if ((data.face_count || 1) > 1) {
    html += '<div class="preview-hint">TTC 首次预览需要抽取字体面，大文件可能要等几秒。</div>';
  }
  html += '<div id="previewLoading" class="preview-loading">正在加载字体...</div>';
  html += '<div id="previewError" class="preview-error" hidden></div>';
  html += '<div id="previewBlocks"></div>';
  html += '<label class="settings-field preview-custom">自定义预览<textarea id="previewCustom" rows="3" maxlength="2000" placeholder="输入自定义文本，实时检测缺字"></textarea></label>';
  html += '</div>';
  html += "<div class=\"detail-section\"><h3>文件特征</h3>";
  html += hashRow("MD5", data.md5, data.hash_error);
  html += hashRow("SHA1", data.sha1, data.hash_error);
  html += hashRow("SHA256", data.sha256, data.hash_error);
  html += "</div>";
  if (data.faces && data.faces.length > 1) {
    html += "<div class=\"detail-section\"><h3>TTC Faces</h3><table class=\"face-table\"><thead><tr><th>#</th><th>家族</th><th>子家族</th><th>版本</th><th>字形</th></tr></thead><tbody>";
    data.faces.forEach(function (face) {
      html += "<tr><td>" + face.face_index + "</td><td>" + esc(face.family || "—") + "</td><td>" + esc(face.subfamily || "—") + "</td><td>" + esc(face.version || "—") + "</td><td>" + (face.glyph_count || "—") + "</td></tr>";
    });
    html += "</tbody></table></div>";
  }
  if (data.parse_error) {
    html += "<div class=\"error-box\">" + esc(data.parse_error) + "</div>";
  }
  html += '<div class="detail-section detail-actions"><a class="btn ghost" href="/api/fonts/' + data.id + '/download" download>下载</a><button type="button" class="btn danger" data-delete-font="' + data.id + '">删除字体</button><span class="muted">默认移入回收站</span></div>';
  $("drawerBody").innerHTML = html;
  initPreview(data);
}

function closeDrawer() {
  state.previewRequestToken++;
  clearTimeout(state.previewTimer);
  if (state.previewFontFace) {
    try { document.fonts.delete(state.previewFontFace); } catch (err) {}
    state.previewFontFace = null;
  }
  state.previewFontFamily = "";
  state.previewData = null;
  state.previewResults = null;
  state.previewCoverage = null;
  state.previewCaseStyle = null;
  state.previewExpanded = {};
  state.previewCustom = "";
  $("drawer").hidden = true;
  $("drawerBackdrop").hidden = true;
}

function fallbackCopy(text) {
  var area = document.createElement("textarea");
  area.value = text;
  area.style.position = "fixed";
  area.style.opacity = "0";
  document.body.appendChild(area);
  area.select();
  try {
    document.execCommand("copy");
    showToast("已复制");
  } catch (err) {
    showToast("复制失败", "error");
  }
  document.body.removeChild(area);
}

function applySidebarState() {
  var layout = document.querySelector(".layout");
  if (!layout) return;
  layout.classList.toggle("sidebar-collapsed", state.sidebarCollapsed);
  var show = document.getElementById("sidebarShow");
  if (show) show.hidden = !state.sidebarCollapsed;
}

function setSidebarCollapsed(value) {
  state.sidebarCollapsed = !!value;
  try {
    localStorage.setItem("fontHub.sidebarCollapsed", value ? "1" : "0");
  } catch (err) {}
  applySidebarState();
}

function bindEvents() {
  try {
    state.sidebarCollapsed = localStorage.getItem("fontHub.sidebarCollapsed") === "1";
  } catch (err) {}
  applySidebarState();
  $("sidebarToggle").addEventListener("click", function () { setSidebarCollapsed(true); });
  $("sidebarShow").addEventListener("click", function () { setSidebarCollapsed(false); });
  $("scanBtn").addEventListener("click", startScan);
  $("hashBtn").addEventListener("click", startHashFlow);
  $("hashStop").addEventListener("click", stopHash);
  $("uploadBtn").addEventListener("click", openUpload);
  $("settingsBtn").addEventListener("click", openSettings);
  $("recycleBtn").addEventListener("click", openRecycle);
  $("settingsClose").addEventListener("click", closeSettings);
  $("settingsSave").addEventListener("click", saveSettings);
  $("settingsReset").addEventListener("click", resetSettings);
  $("settingsModal").addEventListener("click", function (event) {
    if (event.target === $("settingsModal")) closeSettings();
  });
  $("recyclePermanent").addEventListener("change", function () {
    $("recycleDays").disabled = this.checked;
  });
  $("recycleClose").addEventListener("click", closeRecycle);
  $("recycleModal").addEventListener("click", function (event) {
    if (event.target === $("recycleModal")) closeRecycle();
  });
  $("recycleList").addEventListener("click", function (event) {
    var restore = event.target.closest("[data-recycle-restore]");
    if (restore) {
      restoreRecycle(Number(restore.getAttribute("data-recycle-restore")));
      return;
    }
    var remove = event.target.closest("[data-recycle-delete]");
    if (remove) {
      permanentDeleteRecycle(Number(remove.getAttribute("data-recycle-delete")));
    }
  });
  $("deleteClose").addEventListener("click", closeDeleteModal);
  $("deleteCancel").addEventListener("click", closeDeleteModal);
  $("deleteModal").addEventListener("click", function (event) {
    if (event.target === $("deleteModal")) closeDeleteModal();
  });
  $("deletePermanent").addEventListener("change", updateDeleteHint);
  $("deleteConfirm").addEventListener("click", confirmDelete);
  $("uploadClose").addEventListener("click", closeUpload);
  $("uploadStart").addEventListener("click", startUpload);
  $("uploadModal").addEventListener("click", function (event) {
    if (event.target === $("uploadModal")) closeUpload();
  });
  $("fileInput").addEventListener("change", function (event) {
    addUploadFiles(event.target.files);
    event.target.value = "";
  });
  $("folderInput").addEventListener("change", function (event) {
    addUploadFiles(event.target.files);
    event.target.value = "";
  });
  $("applyAll").addEventListener("change", function () {
    if (!this.checked) return;
    var first = document.querySelector("#uploadList select.mini");
    if (!first) return;
    var value = first.value;
    var selects = document.querySelectorAll("#uploadList select.mini");
    for (var i = 0; i < selects.length; i++) selects[i].value = value;
  });
  var drop = $("dropzone");
  drop.addEventListener("dragover", function (event) {
    event.preventDefault();
    drop.classList.add("dragover");
  });
  drop.addEventListener("dragleave", function () {
    drop.classList.remove("dragover");
  });
  drop.addEventListener("drop", function (event) {
    event.preventDefault();
    drop.classList.remove("dragover");
    addUploadFiles(event.dataTransfer.files);
  });
  $("dedupeBtn").addEventListener("click", function () {
    state.duplicates = !state.duplicates;
    state.page = 1;
    $("dedupeBtn").classList.toggle("primary", state.duplicates);
    $("sort").disabled = state.duplicates;
    $("dirBtn").disabled = state.duplicates;
    loadFonts();
  });
  $("emptyScan").addEventListener("click", startScan);
  $("search").addEventListener("input", function (event) {
    var value = event.target.value;
    clearTimeout(state.searchTimer);
    state.searchTimer = setTimeout(function () {
      state.q = value.trim();
      state.page = 1;
      loadFonts();
    }, 250);
  });
  $("sort").addEventListener("change", function (event) {
    state.sort = event.target.value;
    state.page = 1;
    loadFonts();
  });
  $("dirBtn").addEventListener("click", function () {
    state.direction = state.direction === "asc" ? "desc" : "asc";
    $("dirBtn").textContent = state.direction === "asc" ? "↑ 升序" : "↓ 降序";
    state.page = 1;
    loadFonts();
  });
  $("prevBtn").addEventListener("click", function () {
    if (state.page > 1) {
      state.page--;
      loadFonts();
    }
  });
  $("nextBtn").addEventListener("click", function () {
    var pages = Math.max(1, Math.ceil(state.total / state.pageSize));
    if (state.page < pages) {
      state.page++;
      loadFonts();
    }
  });
  $("tree").addEventListener("click", function (event) {
    var button = event.target.closest(".tree-item");
    if (!button) return;
    state.path = button.getAttribute("data-path") || "";
    state.page = 1;
    renderTree();
    loadFonts();
  });
  $("fontRows").addEventListener("click", function (event) {
    var rowDelete = event.target.closest("[data-delete-row]");
    if (rowDelete) {
      openDeleteModal(Number(rowDelete.getAttribute("data-delete-row")));
      return;
    }
    var button = event.target.closest(".file-link");
    if (!button) return;
    openDetail(button.getAttribute("data-id"));
  });
  $("selectAll").addEventListener("change", function () {
    var checked = this.checked;
    var boxes = document.querySelectorAll("#fontRows .row-check");
    for (var i = 0; i < boxes.length; i++) boxes[i].checked = checked;
    state.selectedIds = checked
      ? Array.from(boxes).map(function (box) { return Number(box.getAttribute("data-id")); })
      : [];
    updateBatchBar();
  });
  $("fontRows").addEventListener("change", function (event) {
    var box = event.target.closest(".row-check");
    if (!box) return;
    var id = Number(box.getAttribute("data-id"));
    if (box.checked) {
      if (state.selectedIds.indexOf(id) === -1) state.selectedIds.push(id);
    } else {
      state.selectedIds = state.selectedIds.filter(function (value) { return value !== id; });
    }
    updateBatchBar();
  });
  $("batchRecycle").addEventListener("click", function () { openBatchDelete(false); });
  $("batchDelete").addEventListener("click", function () { openBatchDelete(true); });
  $("batchClear").addEventListener("click", clearSelection);
  $("drawerClose").addEventListener("click", closeDrawer);
  $("drawerBackdrop").addEventListener("click", closeDrawer);
  $("drawerBody").addEventListener("click", function (event) {
    var remove = event.target.closest("[data-delete-font]");
    if (remove) {
      openDeleteModal(Number(remove.getAttribute("data-delete-font")));
      return;
    }
    var button = event.target.closest("[data-preview-toggle]");
    if (!button) return;
    var key = button.getAttribute("data-preview-toggle");
    state.previewExpanded[key] = !state.previewExpanded[key];
    renderPreviewBlocks();
  });
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") {
      closeDrawer();
      closeSettings();
      closeRecycle();
      closeDeleteModal();
    }
  });
  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-copy]");
    if (!button) return;
    var text = button.getAttribute("data-copy");
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(function () {
        showToast("已复制");
      }).catch(function () {
        fallbackCopy(text);
      });
    } else {
      fallbackCopy(text);
    }
  });
}

async function init() {
  bindEvents();
  await refreshAll();
  pollScan();
  pollHash();
}

document.addEventListener("DOMContentLoaded", init);


function renderHash(hash) {
  var bar = $("hashbar");
  if (!hash || (!hash.running && !hash.total && !hash.finished_at)) {
    bar.hidden = true;
    $("hashStop").hidden = true;
    return;
  }
  bar.hidden = false;
  var percent = hash.total_bytes ? Math.round(hash.done_bytes * 100 / hash.total_bytes) : 0;
  $("hashFill").style.width = Math.max(0, Math.min(100, percent)) + "%";
  var text = "";
  if (hash.running) {
    text = "正在计算哈希 " + hash.done + "/" + hash.total + " · " + formatBytes(hash.done_bytes) + " / " + formatBytes(hash.total_bytes);
    if (hash.current) text += " · " + hash.current;
    if (hash.errors) text += " · 失败 " + hash.errors;
    $("hashStop").hidden = false;
  } else if (hash.error) {
    text = "哈希失败：" + hash.error;
    $("hashStop").hidden = true;
  } else if (hash.cancel_requested) {
    text = "哈希已停止：" + hash.done + "/" + hash.total;
    $("hashStop").hidden = true;
  } else {
    text = "哈希完成：" + hash.done + " 个文件";
    if (hash.errors) text += "，失败 " + hash.errors;
    $("hashStop").hidden = true;
  }
  $("hashText").textContent = text;
}

async function pollHash() {
  try {
    var hash = await fetchJSON("/api/hash/status");
    var wasRunning = state.hash && state.hash.running;
    state.hash = hash;
    renderHash(hash);
    $("hashBtn").disabled = !!hash.running;
    $("scanBtn").disabled = !!hash.running || !!(state.scan && state.scan.running);
    if (hash.running) {
      clearTimeout(state.hashTimer);
      state.hashTimer = setTimeout(pollHash, 800);
    } else if (wasRunning) {
      await refreshAll();
      clearTimeout(state.hashTimer);
      state.hashTimer = setTimeout(function () {
        $("hashbar").hidden = true;
      }, 2500);
    }
  } catch (err) {
    showToast("读取哈希状态失败：" + err.message, "error");
  }
}

async function startHashFlow() {
  try {
    var estimate = await fetchJSON("/api/hash/estimate");
    if (!estimate.files) {
      showToast("没有需要计算的文件，哈希已是最新");
      return;
    }
    if (estimate.needs_confirm) {
      var message = "将读取 " + formatBytes(estimate.bytes) + " 字体数据，预计约 " + estimate.estimated_seconds + " 秒。任务会占用磁盘和 CPU，是否继续？";
      if (!window.confirm(message)) return;
    }
    var hash = await fetchJSON("/api/hash/start", { method: "POST" });
    state.hash = hash;
    renderHash(hash);
    pollHash();
  } catch (err) {
    showToast("启动哈希失败：" + err.message, "error");
  }
}

async function stopHash() {
  try {
    var hash = await fetchJSON("/api/hash/stop", { method: "POST" });
    state.hash = hash;
    renderHash(hash);
    showToast("已请求停止，当前文件处理完后停止");
  } catch (err) {
    showToast("停止哈希失败：" + err.message, "error");
  }
}

function openUpload() {
  if (state.scan && state.scan.running) {
    showToast("扫描进行中，请稍后再上传", "error");
    return;
  }
  state.uploadPlan = [];
  state.uploading = false;
  $("uploadModal").hidden = false;
  $("uploadTarget").textContent = state.path ? "/" + state.path : "/";
  $("uploadList").innerHTML = '<div class="muted">尚未选择文件</div>';
  $("uploadSummary").hidden = true;
  $("uploadStart").disabled = true;
  $("applyAll").checked = false;
  $("fileInput").value = "";
  $("folderInput").value = "";
}

function closeUpload() {
  if (state.uploading) {
    showToast("正在上传，请等待完成", "error");
    return;
  }
  $("uploadModal").hidden = true;
}

function addUploadFiles(files) {
  var list = Array.prototype.slice.call(files || []);
  if (!list.length) return;
  state.uploadPlan = list.map(function (file) {
    return {
      file: file,
      name: file.webkitRelativePath || file.name,
      size: file.size,
      status: "checking",
      message: "检查中",
      percent: 0,
      result: null,
      uploadName: null
    };
  });
  state.uploading = false;
  $("uploadSummary").hidden = true;
  $("uploadStart").disabled = true;
  renderUploadPlan();
  runUploadPreflight();
}

async function runUploadPreflight() {
  try {
    var files = state.uploadPlan.map(function (p) {
      return { name: p.name, size: p.size };
    });
    var data = await fetchJSON("/api/upload/preflight", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: state.path, files: files })
    });
    data.files.forEach(function (result, index) {
      var p = state.uploadPlan[index];
      if (!p) return;
      p.result = result;
      if (result.status === "invalid") {
        p.status = "invalid";
        p.message = result.error || "无效文件";
      } else if (result.status === "conflict") {
        p.status = "conflict";
        p.message = "同名文件已存在";
      } else {
        p.status = "ok";
        p.message = "就绪";
      }
    });
    renderUploadPlan();
    updateUploadStart();
  } catch (err) {
    showToast("预检失败：" + err.message, "error");
  }
}

function renderUploadPlan() {
  var list = $("uploadList");
  if (!state.uploadPlan.length) {
    list.innerHTML = '<div class="muted">尚未选择文件</div>';
    return;
  }
  var html = "";
  state.uploadPlan.forEach(function (p, index) {
    var cls = p.status === "uploaded" ? "ok" : p.status === "error" ? "err" : p.status === "skipped" ? "warn" : "";
    html += '<div class="upload-row">';
    html += '<div><div class="upload-name" title="' + esc(p.name) + '">' + esc(p.name) + '</div><div class="upload-meta">' + formatBytes(p.size);
    if (p.status === "conflict" && p.result && p.result.existing) {
      html += ' · 已存在：' + esc(p.result.existing.rel_path);
    } else if (p.message && (p.status === "skipped" || p.status === "invalid" || p.status === "error")) {
      html += ' · ' + esc(p.message);
    }
    html += '</div></div>';
    if (p.status === "conflict") {
      html += '<div><select class="mini" data-index="' + index + '"><option value="rename">重命名并上传</option><option value="skip">跳过</option></select>';
      if (p.result && p.result.suggested_name) {
        html += '<div class="upload-meta">建议：' + esc(p.result.suggested_name) + '</div>';
      }
      html += '</div>';
    } else {
      html += '<div></div>';
    }
    var label = p.status === "checking" ? "检查中" : p.message;
    html += '<div class="upload-status ' + cls + '">' + esc(label) + '<div class="upload-progress"><div data-progress="' + index + '" style="width:' + (p.percent || 0) + '%"></div></div></div>';
    html += '</div>';
  });
  list.innerHTML = html;
}

function updateUploadStart() {
  var canUpload = !state.uploading && state.uploadPlan.some(function (p) {
    return p.status === "ok" || p.status === "conflict";
  });
  $("uploadStart").disabled = !canUpload;
  $("uploadStart").textContent = state.uploading ? "上传中..." : "开始上传";
}

function uploadOne(p, index) {
  return new Promise(function (resolve) {
    var xhr = new XMLHttpRequest();
    var url = "/api/upload?path=" + encodeURIComponent(state.path) + "&name=" + encodeURIComponent(p.uploadName || p.name);
    xhr.open("POST", url);
    xhr.setRequestHeader("Content-Type", "application/octet-stream");
    xhr.upload.onprogress = function (event) {
      if (!event.lengthComputable) return;
      p.percent = Math.round(event.loaded * 100 / event.total);
      var bar = document.querySelector('#uploadList [data-progress="' + index + '"]');
      if (bar) bar.style.width = p.percent + "%";
    };
    xhr.onload = function () {
      var data;
      try {
        data = JSON.parse(xhr.responseText || "{}");
      } catch (err) {
        data = { status: "error", error: xhr.responseText || "服务器返回无法解析" };
      }
      if (xhr.status >= 400) {
        data = { status: "error", error: data.detail || data.error || ("HTTP " + xhr.status) };
      }
      resolve(data);
    };
    xhr.onerror = function () {
      resolve({ status: "error", error: "网络错误" });
    };
    xhr.send(p.file);
  });
}

async function startUpload() {
  if (state.uploading) return;
  state.uploading = true;
  updateUploadStart();
  $("uploadClose").disabled = true;
  $("fileInput").disabled = true;
  $("folderInput").disabled = true;
  $("applyAll").disabled = true;
  var stats = { uploaded: 0, renamed: 0, duplicate: 0, skipped: 0, failed: 0 };
  for (var index = 0; index < state.uploadPlan.length; index++) {
    var p = state.uploadPlan[index];
    if (p.status === "invalid") {
      stats.failed++;
      p.status = "error";
      p.message = p.result && p.result.error ? p.result.error : "无效文件";
      renderUploadPlan();
      continue;
    }
    if (p.status === "conflict") {
      var select = document.querySelector('#uploadList select[data-index="' + index + '"]');
      var choice = select ? select.value : "rename";
      if (choice === "skip") {
        stats.skipped++;
        p.status = "skipped";
        p.message = "按选择跳过";
        renderUploadPlan();
        continue;
      }
      p.uploadName = p.result && p.result.suggested_name ? p.result.suggested_name : p.name;
    } else if (p.status === "ok") {
      p.uploadName = p.name;
    } else {
      continue;
    }
    p.status = "uploading";
    p.percent = 0;
    p.message = "上传中";
    renderUploadPlan();
    var result = await uploadOne(p, index);
    if (result.status === "uploaded") {
      stats.uploaded++;
      if (result.name && result.name !== p.name) stats.renamed++;
      p.status = "uploaded";
      p.percent = 100;
      p.message = "已上传" + (result.name && result.name !== p.name ? "（" + result.name + "）" : "");
    } else if (result.status === "skipped_duplicate") {
      stats.duplicate++;
      p.status = "skipped";
      p.message = "内容重复，已跳过：" + (result.existing_path || "");
    } else if (result.status === "conflict") {
      stats.failed++;
      p.status = "error";
      p.message = "目标已存在" + (result.suggested_name ? "，建议 " + result.suggested_name : "");
    } else {
      stats.failed++;
      p.status = "error";
      p.message = result.error || "上传失败";
    }
    renderUploadPlan();
  }
  state.uploading = false;
  $("uploadClose").disabled = false;
  $("fileInput").disabled = false;
  $("folderInput").disabled = false;
  $("applyAll").disabled = false;
  updateUploadStart();
  var summary = "上传完成：成功 " + stats.uploaded + "，重命名 " + stats.renamed + "，重复跳过 " + stats.duplicate + "，手动跳过 " + stats.skipped + "，失败 " + stats.failed;
  $("uploadSummary").hidden = false;
  $("uploadSummary").textContent = summary;
  showToast(summary, stats.failed ? "error" : "info");
  await refreshAll();
}

function fillPreviewSettings(data) {
  state.previewSettings = data;
  ["preview_cn", "preview_en", "preview_punct", "preview_special"].forEach(function (key) {
    var el = $(key);
    el.value = data.preview[key] || "";
    el.placeholder = data.defaults[key] || "";
  });
}

function fillProjectSettings(data) {
  state.projectSettings = data;
  var days = Number(data.recycle_days);
  var permanent = days === 0;
  $("recyclePermanent").checked = permanent;
  $("recycleDays").value = permanent ? (data.default_recycle_days || 30) : days;
  $("recycleDays").disabled = permanent;
}

async function loadVersionInfo() {
  var box = $("versionInfo");
  if (!box) return;
  try {
    var info = await fetchJSON("/api/version");
    var parts = ["运行版本 " + (info.version || "dev")];
    if (info.commit) parts.push("提交 " + String(info.commit).slice(0, 7));
    if (info.build_time) parts.push("构建 " + info.build_time);
    parts.push("页面资源 v=3");
    box.innerHTML = parts.map(function (item) {
      return '<span class="version-chip">' + esc(item) + '</span>';
    }).join("");
  } catch (err) {
    box.textContent = "版本信息读取失败：" + err.message;
  }
}

async function openSettings() {
  $("settingsModal").hidden = false;
  loadVersionInfo();
  $("settingsHint").textContent = "加载中...";
  try {
    var results = await Promise.all([
      fetchJSON("/api/settings/project"),
      fetchJSON("/api/settings/preview")
    ]);
    fillProjectSettings(results[0]);
    fillPreviewSettings(results[1]);
    $("settingsHint").textContent = "删除的字体默认进入回收站；预览文本留空时使用默认值。";
  } catch (err) {
    $("settingsHint").textContent = "加载失败：" + err.message;
    showToast("加载设置失败：" + err.message, "error");
  }
}

function closeSettings() {
  $("settingsModal").hidden = true;
}

async function saveSettings() {
  var permanent = $("recyclePermanent").checked;
  var maxDays = (state.projectSettings && state.projectSettings.max_recycle_days) || 3650;
  var days = permanent ? 0 : Number($("recycleDays").value);
  if (!permanent && (!Number.isInteger(days) || days < 1 || days > maxDays)) {
    showToast("保留天数范围是 1-" + maxDays + " 天，或勾选永久保留", "error");
    return;
  }
  try {
    var previewBody = {
      preview_cn: $("preview_cn").value,
      preview_en: $("preview_en").value,
      preview_punct: $("preview_punct").value,
      preview_special: $("preview_special").value
    };
    var results = await Promise.all([
      fetchJSON("/api/settings/project", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ recycle_days: days })
      }),
      fetchJSON("/api/settings/preview", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(previewBody)
      })
    ]);
    fillProjectSettings(results[0]);
    fillPreviewSettings(results[1]);
    $("settingsHint").textContent = "已保存。留空项会在预览时使用默认字符串。";
    showToast("设置已保存");
  } catch (err) {
    showToast("保存设置失败：" + err.message, "error");
  }
}

async function resetSettings() {
  if (!window.confirm("恢复默认预览文本？当前自定义内容会被覆盖。")) return;
  try {
    var data = await fetchJSON("/api/settings/preview/reset", { method: "POST" });
    fillPreviewSettings(data);
    $("settingsHint").textContent = "已恢复默认预览文本。";
    showToast("已恢复默认");
  } catch (err) {
    showToast("恢复默认失败：" + err.message, "error");
  }
}

function updateBatchBar() {
  var count = state.selectedIds.length;
  $("batchBar").hidden = count === 0;
  $("selectedCount").textContent = count;
  var boxes = document.querySelectorAll("#fontRows .row-check");
  var checked = 0;
  for (var i = 0; i < boxes.length; i++) {
    if (boxes[i].checked) checked += 1;
  }
  $("selectAll").checked = boxes.length > 0 && checked === boxes.length;
  $("selectAll").indeterminate = checked > 0 && checked < boxes.length;
}

function clearSelection() {
  state.selectedIds = [];
  var boxes = document.querySelectorAll("#fontRows .row-check");
  for (var i = 0; i < boxes.length; i++) boxes[i].checked = false;
  updateBatchBar();
}

async function openBatchDelete(permanent) {
  if (!state.selectedIds.length) return;
  state.pendingDeleteId = null;
  state.pendingDeleteIds = state.selectedIds.slice();
  $("deleteTarget").textContent = "已选择 " + state.pendingDeleteIds.length + " 个字体";
  $("deletePermanent").checked = !!permanent;
  $("deleteModal").hidden = false;
  if (!state.projectSettings) {
    try {
      state.projectSettings = await fetchJSON("/api/settings/project");
    } catch (err) {
      state.projectSettings = { recycle_days: 30 };
    }
  }
  updateDeleteHint();
}

async function openDeleteModal(id) {
  state.pendingDeleteId = Number(id);
  state.pendingDeleteIds = [Number(id)];
  var rowItem = state.items.filter(function (item) { return item.id === Number(id); })[0];
  var drawerTitle = $("drawerTitle").textContent;
  $("deleteTarget").textContent = rowItem ? rowItem.name : (drawerTitle && drawerTitle !== "-" ? drawerTitle : ("字体 #" + id));
  $("deletePermanent").checked = false;
  $("deleteModal").hidden = false;
  if (!state.projectSettings) {
    try {
      state.projectSettings = await fetchJSON("/api/settings/project");
    } catch (err) {
      state.projectSettings = { recycle_days: 30 };
    }
  }
  updateDeleteHint();
}

function updateDeleteHint() {
  var permanent = $("deletePermanent").checked;
  var days = state.projectSettings ? state.projectSettings.recycle_days : 30;
  var count = state.pendingDeleteIds.length || (state.pendingDeleteId ? 1 : 0);
  $("deleteConfirm").textContent = permanent
    ? (count > 1 ? "永久删除 " + count + " 项" : "永久删除")
    : "移入回收站";
  if (count > 1) {
    $("deleteHint").textContent = permanent
      ? "将永久删除 " + count + " 个字体，无法恢复。"
      : (days === 0
        ? "将 " + count + " 个字体移入回收站，永久保留。"
        : "将 " + count + " 个字体移入回收站，保留 " + days + " 天。");
  } else {
    $("deleteHint").textContent = permanent
      ? "永久删除后无法恢复。"
      : (days === 0 ? "移入回收站，永久保留。" : "移入回收站，保留 " + days + " 天。");
  }
}

function closeDeleteModal() {
  $("deleteModal").hidden = true;
  state.pendingDeleteId = null;
  state.pendingDeleteIds = [];
  $("deleteConfirm").disabled = false;
}

async function confirmDelete() {
  var ids = state.pendingDeleteIds.length
    ? state.pendingDeleteIds.slice()
    : (state.pendingDeleteId ? [state.pendingDeleteId] : []);
  if (!ids.length) return;
  var permanent = $("deletePermanent").checked;
  $("deleteConfirm").disabled = true;
  try {
    if (ids.length > 1 || !state.pendingDeleteId) {
      var result = await fetchJSON("/api/fonts/batch-delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ids: ids, permanent: permanent })
      });
      closeDeleteModal();
      closeDrawer();
      state.selectedIds = [];
      await refreshAll();
      var failed = result.failed ? result.failed.length : 0;
      var summary = "批量处理：回收站 " + result.recycled + "，永久删除 " + result.deleted + (failed ? "，失败 " + failed : "");
      showToast(summary, failed ? "error" : "info");
    } else {
      await fetchJSON("/api/fonts/" + ids[0] + "?permanent=" + (permanent ? "true" : "false"), {
        method: "DELETE"
      });
      closeDeleteModal();
      closeDrawer();
      await refreshAll();
      showToast(permanent ? "已永久删除" : "已移入回收站");
    }
  } catch (err) {
    showToast("删除失败：" + err.message, "error");
  } finally {
    $("deleteConfirm").disabled = false;
  }
}

async function openRecycle() {
  $("recycleModal").hidden = false;
  $("recycleHint").textContent = "加载中...";
  $("recycleList").innerHTML = "";
  try {
    var data = await fetchJSON("/api/recycle");
    state.recycleItems = data.items || [];
    renderRecycle(data);
    if (data.purged) showToast("已自动清理 " + data.purged + " 个过期项目");
  } catch (err) {
    $("recycleHint").textContent = "加载失败：" + err.message;
    showToast("加载回收站失败：" + err.message, "error");
  }
}

function closeRecycle() {
  $("recycleModal").hidden = true;
}

function renderRecycle(data) {
  var items = data.items || [];
  var hint = data.recycle_days === 0
    ? "永久保留，不自动清理。"
    : "保留 " + data.recycle_days + " 天，到期自动清理。";
  if (items.length) {
    hint += " 共 " + items.length + " 项，占用 " + formatBytes(data.total_size) + "。";
  }
  $("recycleHint").textContent = hint;
  if (!items.length) {
    $("recycleList").innerHTML = '<div class="recycle-empty">回收站为空</div>';
    return;
  }
  var html = "";
  items.forEach(function (item) {
    var expiry = item.expires_at
      ? ("剩余 " + (item.days_left === null ? "-" : item.days_left) + " 天 · " + formatIsoDate(item.expires_at))
      : "永久保留";
    html += '<div class="recycle-row"><div class="recycle-main">';
    html += '<div class="recycle-name">' + esc(item.name) + '</div>';
    html += '<div class="muted">' + esc(item.rel_path) + ' · ' + formatBytes(item.size) + '</div>';
    html += '<div class="muted">删除于 ' + esc(formatIsoDate(item.deleted_at)) + ' · ' + esc(expiry) + '</div>';
    html += '</div><div class="recycle-actions">';
    html += '<button class="btn ghost" data-recycle-restore="' + item.id + '">恢复</button>';
    html += '<button class="btn danger" data-recycle-delete="' + item.id + '">永久删除</button>';
    html += '</div></div>';
  });
  $("recycleList").innerHTML = html;
}

async function restoreRecycle(id) {
  var item = state.recycleItems.filter(function (candidate) { return candidate.id === id; })[0];
  if (!window.confirm("恢复 " + (item ? item.name : "该字体") + " 到原路径？")) return;
  try {
    await fetchJSON("/api/recycle/" + id + "/restore", { method: "POST" });
    showToast("已恢复正常");
    await refreshAll();
    await openRecycle();
  } catch (err) {
    showToast("恢复失败：" + err.message, "error");
  }
}

async function permanentDeleteRecycle(id) {
  var item = state.recycleItems.filter(function (candidate) { return candidate.id === id; })[0];
  if (!window.confirm("永久删除 " + (item ? item.name : "该字体") + "？此操作无法恢复。")) return;
  try {
    await fetchJSON("/api/recycle/" + id, { method: "DELETE" });
    showToast("已永久删除");
    await refreshAll();
    await openRecycle();
  } catch (err) {
    showToast("永久删除失败：" + err.message, "error");
  }
}

async function loadPreviewSettings() {
  if (!state.previewSettings) {
    state.previewSettings = await fetchJSON("/api/settings/preview");
  }
  var s = state.previewSettings;
  state.previewTexts = {
    preview_cn: s.preview.preview_cn || s.defaults.preview_cn || "",
    preview_en: s.preview.preview_en || s.defaults.preview_en || "",
    preview_punct: s.preview.preview_punct || s.defaults.preview_punct || "",
    preview_special: s.preview.preview_special || s.defaults.preview_special || ""
  };
}

async function initPreview(data) {
  var token = ++state.previewRequestToken;
  state.previewData = data;
  state.previewFaceIndex = 0;
  state.previewCustom = "";
  state.previewCoverage = null;
  state.previewResults = null;
  state.previewCaseStyle = "unknown";
  state.previewExpanded = {};
  state.previewFontFamily = "";
  clearTimeout(state.previewTimer);
  if (state.previewFontFace) {
    try { document.fonts.delete(state.previewFontFace); } catch (err) {}
    state.previewFontFace = null;
  }
  $("previewError").hidden = true;
  $("previewError").textContent = "";
  $("previewLoading").hidden = false;
  $("previewLoading").textContent = "正在加载字体...";
  $("previewBlocks").innerHTML = "";
  var size = $("previewSize");
  if (size) {
    state.previewSize = 28;
    size.value = "28";
    size.oninput = function () {
      state.previewSize = Number(size.value);
      applyPreviewStyles();
    };
  }
  var custom = $("previewCustom");
  if (custom) {
    custom.value = "";
    custom.oninput = function () {
      state.previewCustom = custom.value;
      if (state.previewResults) delete state.previewResults.custom;
      renderPreviewBlocks();
      clearTimeout(state.previewTimer);
      state.previewTimer = setTimeout(refreshPreviewCoverage, 300);
    };
  }
  var faceSelect = $("previewFace");
  if (faceSelect) {
    faceSelect.value = "0";
    faceSelect.onchange = function () {
      var face = Number(faceSelect.value);
      state.previewExpanded = {};
      var faceToken = ++state.previewRequestToken;
      loadPreviewFont(data, face, faceToken)
        .then(function () {
          if (faceToken !== state.previewRequestToken) return;
          return loadPreviewCaseStyle(data, face, faceToken).then(function () {
            if (faceToken !== state.previewRequestToken) return;
            return refreshPreviewCoverage();
          });
        })
        .catch(function (err) {
          if (faceToken === state.previewRequestToken) showPreviewError(err);
        });
    };
  }
  try {
    await loadPreviewSettings();
    if (token !== state.previewRequestToken) return;
    await loadPreviewFont(data, 0, token);
    if (token !== state.previewRequestToken) return;
    await loadPreviewCaseStyle(data, 0, token);
    if (token !== state.previewRequestToken) return;
    await refreshPreviewCoverage();
  } catch (err) {
    if (token === state.previewRequestToken) showPreviewError(err);
  }
}

async function loadPreviewFont(data, face, token) {
  if (state.previewFontFace) {
    try { document.fonts.delete(state.previewFontFace); } catch (err) {}
    state.previewFontFace = null;
  }
  state.previewFontFamily = "";
  state.previewFaceIndex = face;
  $("previewLoading").hidden = false;
  $("previewLoading").textContent = (data.face_count || 1) > 1
    ? "正在加载字体，TTC 首次预览需要抽面，可能等待数秒..."
    : "正在加载字体...";
  $("previewError").hidden = true;
  var version = "p2-" + (data.sha1 || data.sha256 || data.md5 || data.mtime_ns || "");
  var url = "/api/fonts/" + data.id + "/preview?face=" + face + "&v=" + encodeURIComponent(version);
  var family = "font-hub-preview-" + data.id + "-" + face + "-" + Date.now();
  var loaded = await new Promise(function (resolve, reject) {
    if (typeof FontFace === "undefined") {
      reject(new Error("浏览器不支持 FontFace"));
      return;
    }
    var previewFace = new FontFace(family, 'url("' + url + '")');
    previewFace.load().then(function (font) {
      document.fonts.add(font);
      resolve(font);
    }).catch(function () {
      reject(new Error("字体文件无法用于网页预览，可能已损坏或格式不受支持"));
    });
  });
  if (token !== undefined && token !== state.previewRequestToken) {
    try { document.fonts.delete(loaded); } catch (err) {}
    return;
  }
  state.previewFontFace = loaded;
  state.previewFontFamily = family;
  $("previewLoading").hidden = true;
  applyPreviewStyles();
}

async function loadPreviewCaseStyle(data, face, token) {
  try {
    var result = await fetchJSON("/api/fonts/" + data.id + "/case-style?face=" + face);
    if (token !== undefined && token !== state.previewRequestToken) return;
    state.previewCaseStyle = result && result.style ? result.style : "unknown";
  } catch (err) {
    if (token !== undefined && token !== state.previewRequestToken) return;
    state.previewCaseStyle = "unknown";
  }
}

async function refreshPreviewCoverage() {
  if (!state.previewData) return;
  var token = ++state.previewRequestToken;
  var texts = Object.assign({}, state.previewTexts);
  var custom = state.previewCustom.trim();
  if (custom) texts.custom = custom;
  try {
    var data = await fetchJSON("/api/fonts/" + state.previewData.id + "/coverage", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ face: state.previewFaceIndex, texts: texts })
    });
    if (token !== state.previewRequestToken) return;
    state.previewCoverage = data;
    state.previewResults = data.results;
    renderPreviewBlocks();
  } catch (err) {
    if (token === state.previewRequestToken) showPreviewError(err);
  }
}

function isPreviewSpace(ch) {
  var cp = ch.codePointAt(0);
  if (/\s/.test(ch)) return true;
  if (cp < 0x20 || (cp >= 0x7F && cp <= 0x9F)) return true;
  if (cp >= 0xFE00 && cp <= 0xFE0F) return true;
  if (cp >= 0xE0100 && cp <= 0xE01EF) return true;
  return false;
}

function previewChars(text) {
  var seen = {};
  var list = [];
  Array.from(text).forEach(function (ch) {
    if (isPreviewSpace(ch) || seen[ch]) return;
    seen[ch] = true;
    list.push(ch);
  });
  return list;
}

function previewLineStats(line, missingMap) {
  var total = 0;
  var missing = 0;
  Array.from(line).forEach(function (ch) {
    if (isPreviewSpace(ch)) return;
    total += 1;
    if (missingMap[ch]) missing += 1;
  });
  return {
    total: total,
    missing: missing,
    coverage: total ? (total - missing) / total : 1
  };
}

function previewMissingRatio(chars, missingMap) {
  if (!chars.length) return 0;
  var missing = 0;
  chars.forEach(function (ch) {
    if (missingMap[ch]) missing += 1;
  });
  return missing / chars.length;
}

function chineseLinePlan(lines, missingMap) {
  if (lines.length !== 2) return null;
  var first = previewChars(lines[0]);
  var second = previewChars(lines[1]);
  var firstSet = {};
  var secondSet = {};
  first.forEach(function (ch) { firstSet[ch] = true; });
  second.forEach(function (ch) { secondSet[ch] = true; });
  var onlyFirst = first.filter(function (ch) { return !secondSet[ch]; });
  var onlySecond = second.filter(function (ch) { return !firstSet[ch]; });
  if (onlyFirst.length < 3 || onlySecond.length < 3) return null;
  var firstMissing = previewMissingRatio(onlyFirst, missingMap);
  var secondMissing = previewMissingRatio(onlySecond, missingMap);
  if (secondMissing >= 0.75 && firstMissing <= 0.25) {
    return { visible: [0], label: "中文（仅简体）", note: "字体缺少繁体字形，已只显示简体行。" };
  }
  if (firstMissing >= 0.75 && secondMissing <= 0.25) {
    return { visible: [1], label: "中文（仅繁体）", note: "字体缺少简体字形，已只显示繁体行。" };
  }
  return null;
}

function englishLinePlan(lines, missingMap, caseStyle) {
  if (lines.length !== 2) return null;
  if (caseStyle === "upper" || caseStyle === "upper-only") {
    return {
      visible: [0],
      label: "英文（仅大写）",
      note: caseStyle === "upper"
        ? "字体小写字形使用大写设计，已只显示大写行。"
        : "字体缺少小写字形，已只显示大写行。"
    };
  }
  if (caseStyle === "lower" || caseStyle === "lower-only") {
    return {
      visible: [1],
      label: "英文（仅小写）",
      note: caseStyle === "lower"
        ? "字体大写字形使用小写设计，已只显示小写行。"
        : "字体缺少大写字形，已只显示小写行。"
    };
  }
  if (caseStyle === "unicase") {
    return { visible: [0], label: "英文（大小写同形）", note: "大小写字形外观相同，已只显示大写行。" };
  }
  var stats = lines.map(function (line) { return previewLineStats(line, missingMap); });
  var upperStrong = stats[0].total > 0 && stats[0].coverage >= 0.75;
  var lowerStrong = stats[1].total > 0 && stats[1].coverage >= 0.75;
  var upperWeak = stats[0].total > 0 && stats[0].coverage < 0.25;
  var lowerWeak = stats[1].total > 0 && stats[1].coverage < 0.25;
  if (upperStrong && lowerWeak) {
    return { visible: [0], label: "英文（仅大写）", note: "字体缺少小写字形，已只显示大写行。" };
  }
  if (lowerStrong && upperWeak) {
    return { visible: [1], label: "英文（仅小写）", note: "字体缺少大写字形，已只显示小写行。" };
  }
  return null;
}

function joinLineNames(names) {
  if (names.length <= 1) return names[0] || "";
  if (names.length === 2) return names[0] + "和" + names[1];
  return names.slice(0, -1).join("、") + "和" + names[names.length - 1];
}

function punctuationLinePlan(lines, missingMap) {
  if (lines.length !== 3) return null;
  var fullNames = ["中文标点", "英文标点", "数字"];
  var shortNames = ["中", "英", "数字"];
  var singleNames = ["中文", "英文", "数字"];
  var stats = lines.map(function (line) { return previewLineStats(line, missingMap); });
  var strong = [];
  var weak = [];
  stats.forEach(function (stat, index) {
    if (stat.total === 0) return;
    if (stat.coverage >= 0.75) strong.push(index);
    else if (stat.coverage < 0.25) weak.push(index);
  });
  if (!strong.length || !weak.length) return null;
  var visible = [0, 1, 2].filter(function (index) { return weak.indexOf(index) === -1; });
  var label = visible.length === 1
    ? "标点（仅" + singleNames[visible[0]] + "）"
    : "标点（" + visible.map(function (index) { return shortNames[index]; }).join("/") + "）";
  var hiddenNames = weak.map(function (index) { return fullNames[index]; });
  var note = "字体缺少" + joinLineNames(hiddenNames) + "，已隐藏" + (weak.length > 1 ? "对应行" : "该行") + "。";
  return { visible: visible, label: label, note: note };
}

function previewLinePlan(key, lines, missingMap, caseStyle) {
  if (key === "preview_cn") return chineseLinePlan(lines, missingMap);
  if (key === "preview_en") return englishLinePlan(lines, missingMap, caseStyle);
  if (key === "preview_punct") return punctuationLinePlan(lines, missingMap);
  return null;
}

function renderPreviewBlock(key, label, text, result) {
  var missing = result ? result.missing || [] : [];
  var missingMap = {};
  missing.forEach(function (item) {
    missingMap[item.char] = item.codepoint;
  });
  var normalized = text ? text.replace(/\r\n?/g, "\n") : "";
  var lines = normalized ? normalized.split("\n") : [];
  var blockLabel = label;
  var note = "";
  var missingCount = result ? result.missing_count : 0;
  var coverage = result && typeof result.coverage === "number" ? result.coverage : null;
  var plan = null;
  var canToggle = false;
  var expanded = !!state.previewExpanded[key];
  if (result) {
    plan = previewLinePlan(key, lines, missingMap, key === "preview_en" ? state.previewCaseStyle : null);
  }
  canToggle = !!(plan && plan.visible.length < lines.length);
  if (canToggle && !expanded) {
    blockLabel = plan.label;
    note = plan.note;
    lines = plan.visible.map(function (index) { return lines[index]; });
    var visibleText = lines.join("\n");
    var visibleSet = {};
    Array.from(visibleText).forEach(function (ch) {
      if (!isPreviewSpace(ch)) visibleSet[ch] = true;
    });
    missing = missing.filter(function (item) { return visibleSet[item.char]; });
    var stats = previewLineStats(visibleText, missingMap);
    missingCount = missing.length;
    coverage = stats.coverage;
  }
  var inner = "";
  if (!text) {
    inner = '<span class="muted">未设置文本</span>';
  } else {
    lines.forEach(function (line) {
      var lineHtml = "";
      Array.from(line).forEach(function (ch) {
        if (missingMap[ch]) {
          lineHtml += '<span class="missing-glyph" title="' + esc(missingMap[ch]) + '">' + esc(ch) + "</span>";
        } else {
          lineHtml += esc(ch);
        }
      });
      inner += '<span class="preview-line">' + (lineHtml || "&nbsp;") + "</span>";
    });
  }
  var status = "检测中";
  if (result) {
    if (missingCount) {
      status = "缺字 " + missingCount + " 种";
      if (coverage !== null) {
        status += " · " + Math.round(coverage * 1000) / 10 + "%";
      }
    } else {
      status = "字形完整";
    }
  }
  var html = '<div class="preview-block" data-key="' + key + '">';
  html += '<div class="preview-label"><span>' + esc(blockLabel) + '</span><span>' + esc(status) + '</span></div>';
  html += '<div class="preview-text' + (missingCount ? " has-missing" : "") + '" data-preview-text>' + inner + '</div>';
  if (missingCount) {
    html += '<div class="preview-missing">缺字：' + missing.slice(0, 30).map(function (item) {
      return "<code>" + esc(item.char) + " " + esc(item.codepoint) + "</code>";
    }).join(" ") + (missing.length > 30 ? " …" : "") + '</div>';
  } else if (result && !canToggle) {
    html += '<div class="preview-missing ok">字形完整</div>';
  }
  if (note) {
    html += '<div class="preview-note">' + esc(note) + '</div>';
  }
  if (canToggle) {
    html += '<button type="button" class="preview-toggle" data-preview-toggle="' + key + '">' + (expanded ? "收起为单列" : "展开全部行") + '</button>';
  }
  html += '</div>';
  return html;
}
function renderPreviewBlocks() {
  var labels = {
    preview_cn: "中文",
    preview_en: "英文",
    preview_punct: "标点（中/英/数字）",
    preview_special: "特殊"
  };
  var html = "";
  if (state.previewCoverage && state.previewCoverage.no_cmap) {
    html += '<div class="preview-warning">该字体没有可用的 Unicode cmap 字符映射表，无法判断字形覆盖，所有文字都会标记为缺字。</div>';
  }
  var cnResult = state.previewResults ? state.previewResults.preview_cn : null;
  var hideChinese = !!(cnResult && cnResult.total > 0 && cnResult.coverage === 0 && !(state.previewCoverage && state.previewCoverage.no_cmap));
  Object.keys(labels).forEach(function (key) {
    var result = state.previewResults ? state.previewResults[key] : null;
    if (key === "preview_cn" && hideChinese) {
      html += '<div class="preview-block preview-empty" data-key="preview_cn">';
      html += '<div class="preview-label"><span>中文</span><span>不含中文字形</span></div>';
      html += '<div class="preview-note">该字体没有中文字形，已隐藏中文预览。</div>';
      html += '</div>';
      return;
    }
    html += renderPreviewBlock(key, labels[key], state.previewTexts[key] || "", result);
  });
  var custom = state.previewCustom.trim();
  if (custom) {
    html += renderPreviewBlock("custom", "自定义", custom, state.previewResults ? state.previewResults.custom : null);
  }
  $("previewBlocks").innerHTML = html;
  applyPreviewStyles();
}

function applyPreviewStyles() {
  var family = state.previewFontFamily ? '"' + state.previewFontFamily + '", sans-serif' : "sans-serif";
  var texts = document.querySelectorAll("#previewBlocks [data-preview-text]");
  for (var i = 0; i < texts.length; i++) {
    texts[i].style.fontFamily = family;
    texts[i].style.fontSize = state.previewSize + "px";
  }
}

function showPreviewError(err) {
  $("previewLoading").hidden = true;
  var box = $("previewError");
  if (box) {
    box.hidden = false;
    box.textContent = "预览失败：" + (err && err.message ? err.message : String(err));
  }
}
