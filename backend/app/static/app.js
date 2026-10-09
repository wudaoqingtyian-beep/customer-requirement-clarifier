"use strict";

const API = "";
let types = [];
let sources = [];
let currentProject = null;
let currentRequirement = null;

// ---------- utils ----------
async function api(path, options) {
  const res = await fetch(API + path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).detail || msg; } catch (e) { /* ignore */ }
    throw new Error(msg);
  }
  return res.json();
}

function show(view) {
  ["view-projects", "view-project", "view-requirement"].forEach((id) => {
    document.getElementById(id).classList.toggle("hidden", id !== view);
  });
}

function el(id) { return document.getElementById(id); }

function statusBadge(status) {
  if (status === "confirmed") return '<span class="badge confirmed">已确认</span>';
  return status === "ready"
    ? '<span class="badge ready">可进入方案评估</span>'
    : '<span class="badge incomplete">信息不足</span>';
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// ---------- projects ----------
async function loadProjects() {
  const projects = await api("/api/projects");
  const list = el("project-list");
  list.innerHTML = "";
  if (projects.length === 0) {
    list.innerHTML = '<li class="muted">暂无项目</li>';
    return;
  }
  projects.forEach((p) => {
    const li = document.createElement("li");
    li.innerHTML =
      '<div><span class="title" data-id="' + p.id + '">' + escapeHtml(p.name) + "</span>" +
      '<div class="muted">客户：' + escapeHtml(p.client_name || "-") +
      " · 需求数：" + p.requirement_count + " · " + escapeHtml(p.created_at) + "</div></div>" +
      '<div class="actions"><button class="danger" data-del="' + p.id + '">删除</button></div>';
    list.appendChild(li);
  });
  list.querySelectorAll(".title").forEach((t) =>
    t.addEventListener("click", () => openProject(parseInt(t.dataset.id, 10)))
  );
  list.querySelectorAll("[data-del]").forEach((b) =>
    b.addEventListener("click", async () => {
      if (!confirm("删除该项目及其全部需求？")) return;
      await api("/api/projects/" + b.dataset.del, { method: "DELETE" });
      loadProjects();
    })
  );
}

el("project-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  await api("/api/projects", {
    method: "POST",
    body: JSON.stringify({
      name: el("p-name").value.trim(),
      client_name: el("p-client").value.trim(),
      description: el("p-desc").value.trim(),
    }),
  });
  e.target.reset();
  loadProjects();
});

// ---------- project detail ----------
async function openProject(pid) {
  const p = await api("/api/projects/" + pid);
  currentProject = p;
  el("pd-name").textContent = p.name;
  el("pd-meta").textContent =
    "客户：" + (p.client_name || "-") + " · 状态：" + p.status + " · 创建时间：" + p.created_at;
  el("pd-desc").textContent = p.description || "";
  show("view-project");
  loadRequirements(p.id);
}

el("back-projects").addEventListener("click", () => {
  currentProject = null; show("view-projects"); loadProjects();
});

async function loadRequirements(pid) {
  const reqs = await api("/api/projects/" + pid + "/requirements");
  const list = el("requirement-list");
  list.innerHTML = "";
  if (reqs.length === 0) {
    list.innerHTML = '<li class="muted">暂无技术需求</li>';
    return;
  }
  reqs.forEach((r) => {
    const li = document.createElement("li");
    li.innerHTML =
      '<div><span class="title" data-id="' + r.id + '">' + escapeHtml(r.name) + "</span>" +
      '<div class="muted">类型：系统集成 · ' + escapeHtml(r.original_request || "（未填写原始描述）") + "</div></div>" +
      '<div class="actions">' + statusBadge(r.status) +
      '<button class="danger" data-del="' + r.id + '">删除</button></div>';
    list.appendChild(li);
  });
  list.querySelectorAll(".title").forEach((t) =>
    t.addEventListener("click", () => openRequirement(parseInt(t.dataset.id, 10)))
  );
  list.querySelectorAll("[data-del]").forEach((b) =>
    b.addEventListener("click", async () => {
      if (!confirm("删除该需求？")) return;
      await api("/api/requirements/" + b.dataset.del, { method: "DELETE" });
      loadRequirements(pid);
    })
  );
}

el("requirement-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const r = await api("/api/projects/" + currentProject.id + "/requirements", {
    method: "POST",
    body: JSON.stringify({
      name: el("r-name").value.trim(),
      type: el("r-type").value,
      original_request: el("r-original").value.trim(),
      structured_data: {},
    }),
  });
  e.target.reset();
  openRequirement(r.id);
});

// ---------- requirement detail ----------
async function openRequirement(rid) {
  const r = await api("/api/requirements/" + rid);
  currentRequirement = r;
  const typeDef = types.find((t) => t.type === r.type);
  el("rd-name").textContent = r.name;
  el("rd-type").textContent = typeDef ? typeDef.label : r.type;
  el("rd-status").innerHTML = statusBadge(r.status);
  el("rd-original").textContent = r.original_request || "（客户未提供原始描述）";

  el("rd-fields").innerHTML = '<div class="grid">' + typeDef.fields.map((f) => {
    const value = r.structured_data[f.key] || "";
    const source = r.structured_data[f.key + "_source"] || "";
    const opts = (typeDef.sources || sources).map((s) =>
      '<option value="' + s.value + '"' + (s.value === source ? " selected" : "") +
      ">" + s.label + "</option>").join("");
    return '<div class="field-block">' +
      '<label>' + f.label + '<input data-key="' + f.key + '" value="' +
      escapeHtml(value) + '" placeholder="待向客户确认" /></label>' +
      '<label class="src-label">信息来源：<select data-src="' + f.key + '"' +
      (value ? "" : " disabled") + '><option value="">未记录来源</option>' + opts +
      "</select></label></div>";
  }).join("") + "</div>";

  el("rd-fields").querySelectorAll("input[data-key]").forEach((i) => {
    i.addEventListener("input", () => {
      const sel = el("rd-fields").querySelector('select[data-src="' + i.dataset.key + '"]');
      // 字段清空 -> 来源禁用并清空；字段非空但来源失效 -> 提示重新选择
      if (!i.value.trim()) {
        sel.value = "";
        sel.disabled = true;
      } else {
        sel.disabled = false;
      }
    });
  });

  renderResult(r);
  renderClarifications(r);
  renderSummary(r);
  show("view-requirement");
}

function renderSourceOverview(res) {
  const s = res && res.source_summary;
  if (!s) return "";
  const missing = res.source_missing_labels || [];
  let html = "<p><strong>信息来源概览：</strong></p><ul class='source-list'>";
  s.counts.forEach((c) => {
    html += "<li>" + c.label + "：" + c.count + "</li>";
  });
  html += "</ul>";
  if (s.without_source > 0) {
    html += '<p class="result-incomplete">该信息尚未记录来源（' + s.without_source +
      " 项）：" + escapeHtml(missing.join("、")) +
      "。来源缺失不影响完整性判断，请尽量向客户核实。</p>";
  }
  html += '<p class="notice">' + s.notice + "</p>";
  return html;
}

function renderResult(r) {
  const box = el("rd-result");
  el("rd-status").innerHTML = statusBadge(r.status);
  const btn = el("confirm-requirement");
  if (r.status === "confirmed") {
    btn.disabled = true;
    el("confirm-hint").textContent = "该需求已由售前确认，如修改核心信息将需要重新确认。";
  } else if (r.status === "ready") {
    btn.disabled = false;
    el("confirm-hint").textContent = "信息已完整，可由售前人工确认需求。";
  } else {
    btn.disabled = true;
    el("confirm-hint").textContent = "信息不足，补全后进入 ready 才能确认。";
  }

  if (!r.check_result) {
    box.innerHTML = '<p class="muted">尚未执行检查。填写信息后点击「保存并检查」。</p>';
    return;
  }
  const res = r.check_result;
  let html = '<p class="' + (res.status === "ready" ? "result-ready" : "result-incomplete") + '">' +
    (res.status === "ready"
      ? "✓ 信息已基本完整，当前需求可进入方案评估阶段"
      : "⚠ 信息不足，当前无法进入方案评估") + "</p>";
  if (res.missing_fields.length) {
    html += "<p><strong>缺失信息：</strong></p><ul>" +
      res.missing_fields.map((f) => "<li>" + f.label + "</li>").join("") + "</ul>";
    html += "<p><strong>待澄清问题：</strong></p><ol>" +
      res.clarification_questions.map((q) => "<li>" + escapeHtml(q) + "</li>").join("") + "</ol>";
  } else {
    html += '<p class="muted">无缺失信息。</p>';
  }
  html += renderSourceOverview(res);
  html += '<p class="notice">' + res.notice + "</p>";
  box.innerHTML = html;
}

function renderClarifications(r) {
  const box = el("rd-clarifications");
  const items = (r.check_result && r.check_result.clarification_items) || [];
  if (items.length === 0) {
    box.innerHTML = '<p class="muted">执行检查后生成澄清项。</p>';
    return;
  }
  let html = "<ul class='cl-list'>";
  items.forEach((i) => {
    const st = i.status === "confirmed"
      ? '<span class="badge ready">已确认</span>'
      : '<span class="badge incomplete">待确认</span>';
    html +=
      '<li class="cl-item"><div>' +
      '<div class="cl-q">' + st + " " + escapeHtml(i.question) + "</div>" +
      '<div class="muted">对应字段：' + i.label + " · 客户回答：" +
      (i.answer ? escapeHtml(i.answer) : '<em>未回答</em>') + "</div></div></li>";
  });
  html += "</ul>";
  html += '<p class="notice">' +
    "澄清项状态由结构化字段自动派生：字段已填写即为「已确认」，清空后自动恢复为「待确认」。</p>";
  box.innerHTML = html;
}

async function renderSummary(r) {
  const s = await api("/api/requirements/" + r.id + "/summary");
  let html =
    "<p><strong>客户：</strong>" + escapeHtml(s.client || "-") + "</p>" +
    "<p><strong>需求名称：</strong>" + escapeHtml(s.requirement_name) + "</p>" +
    "<p><strong>客户原始描述：</strong>" +
    escapeHtml(s.original_request || "（未填写）") + "</p>" +
    "<p><strong>当前状态：</strong>" + escapeHtml(s.status_label) + "（" + s.status + "）</p>" +
    "<p><strong>信息来源概览</strong></p><ul class='source-list'>";
  s.source_summary.counts.forEach((c) => {
    html += "<li>" + c.label + "：" + c.count + "</li>";
  });
  html += "</ul>";
  if (s.source_summary.without_source > 0) {
    html += '<p class="result-incomplete">尚有 ' + s.source_summary.without_source +
      " 项信息未记录来源。</p>";
  }
  html += "<p><strong>已确认信息</strong></p><ul class='summary-list'>";
  s.confirmed_info.forEach((i) => {
    html += "<li>" + i.label + "：" +
      (i.value ? escapeHtml(i.value) : '<em class="result-incomplete">待确认</em>') +
      (i.value
        ? "（来源：" +
          (i.source_label ? escapeHtml(i.source_label) : '<em class="result-incomplete">未记录来源</em>') +
          "）"
        : "") + "</li>";
  });
  html += "</ul>";
  html += "<p><strong>待处理澄清项：</strong></p>";
  if (s.pending_count === 0) {
    html += '<p class="result-ready">无待处理澄清项。</p>';
  } else {
    html += "<ul>" + s.pending_items.map((i) =>
      "<li>" + escapeHtml(i.question) + "</li>").join("") + "</ul>";
  }
  html += '<p class="notice">' + escapeHtml(s.source_notice) + "</p>";
  html += '<p class="notice">' + escapeHtml(s.boundary_notice) + "</p>";
  el("rd-summary").innerHTML = html;
}

el("back-project").addEventListener("click", () => {
  if (currentProject) openProject(currentProject.id);
});

el("save-check").addEventListener("click", async () => {
  const data = {};
  el("rd-fields").querySelectorAll("input[data-key]").forEach((i) => {
    data[i.dataset.key] = i.value.trim();
  });
  el("rd-fields").querySelectorAll("select[data-src]").forEach((s) => {
    data[s.dataset.src + "_source"] = s.value;
  });
  try {
    const saved = await api("/api/requirements/" + currentRequirement.id, {
      method: "PATCH",
      body: JSON.stringify({ structured_data: data }),
    });
    const checked = await api("/api/requirements/" + saved.id + "/check", { method: "POST" });
    openRequirement(checked.id);
  } catch (e) {
    alert("保存失败：" + e.message);
  }
});

el("confirm-requirement").addEventListener("click", async () => {
  if (!confirm("确认该客户技术需求信息已整理完整？（仅代表需求信息确认，不代表方案可行）")) return;
  try {
    const r = await api("/api/requirements/" + currentRequirement.id + "/confirm", {
      method: "POST",
    });
    openRequirement(r.id);
  } catch (e) {
    alert("确认失败：" + e.message);
  }
});

// ---------- init ----------
(async function init() {
  types = await api("/api/requirement-types");
  sources = await api("/api/sources");
  el("r-type").innerHTML = types
    .map((t) => '<option value="' + t.type + '">' + t.label + "</option>")
    .join("");
  show("view-projects");
  loadProjects();
})();