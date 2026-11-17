"use strict";

const $ = id => document.getElementById(id);
const names = {I_case: "案例", I_model: "建模", I_run: "运行与结果", I_tool: "工具"};
const evidenceLabels = {
  publisher_catalog_locator: "章节索引 · 正文待核对",
  publisher_sample_paraphrase: "公开样章摘要",
  published_teaching_paraphrase: "教材原文摘要",
  historical_or_conceptual_reference: "旧版或理论参考",
  official_web_tutorial_paraphrase: "官方网页教程",
  R12_manual_definition: "R12 手册定义",
  official_original_static_inventory: "官方 K 文件 · 静态核对",
  official_deck_annotated_static: "K 文件步骤 · 静态核对",
  project_fixture_static_inventory: "项目 K 文件 · 静态核对",
};
const state = {index: "", source: "", selected: null};
let data;
let records;

function element(tag, value, className) {
  const node = document.createElement(tag);
  if (value) node.textContent = value;
  if (className) node.className = className;
  return node;
}

function button(label, className, callback) {
  const node = element("button", label, className);
  node.type = "button";
  node.addEventListener("click", callback);
  return node;
}

function action(label, href) {
  const node = element("a", label, "action");
  node.href = href;
  node.target = "_blank";
  node.rel = "noopener noreferrer";
  return node;
}

function setSource(value) {
  state.source = state.source === value ? "" : value;
  state.index = "";
  state.selected = null;
  $("query").value = "";
  updateList();
}

function refreshButtons() {
  for (const control of $("indexes").querySelectorAll("button")) {
    control.setAttribute("aria-pressed", String(control.dataset.filter === state.index));
  }
  for (const control of document.querySelectorAll("#sources button, #manuals button")) {
    control.setAttribute("aria-pressed", String(control.dataset.filter === state.source));
  }
}

function sourceMatches(record) {
  if (state.source === "books") return record.id.startsWith("book.");
  if (state.source === "primary" || state.source === "supplement") return record.collection === state.source;
  return !state.source || record.source === state.source;
}

function showDetails(record) {
  const panel = $("details");
  panel.replaceChildren();
  if (!record) {
    panel.append(element("p", "选择左侧条目以查看详情。"));
    return;
  }
  panel.append(element("h3", record.title), element("p", record.summary));
  const metadata = element("dl");
  for (const [key, value] of [
    ["记录", record.id], ["来源", record.source], ["版本", record.release], ["出处", record.locator],
    ["证据", evidenceLabels[record.evidence] || record.evidence], ["R12 求解", record.execution === "unverified" ? "待核验" : record.execution],
  ]) {
    if (value) metadata.append(element("dt", key), element("dd", value));
  }
  panel.append(metadata);
  if (record.pdf_url) panel.append(action("打开原文对应页", record.pdf_url));
  if (record.url) panel.append(action("查看公开来源", record.url));
  for (const [title, items] of [["操作参考", record.steps], ["检查点", record.checks]]) {
    if (!items.length) continue;
    const list = element("ul");
    for (const item of items) list.append(element("li", item));
    panel.append(element("h4", title), list);
  }
  if (record.related.length) {
    const links = element("div", null, "related");
    for (const key of record.related) {
      links.append(button(records.get(key).title, "", () => {
        state.index = "";
        state.source = "";
        $("query").value = key;
        state.selected = key;
        updateList();
        $("list").querySelector("button")?.focus();
      }));
    }
    panel.append(element("h4", "关联知识"), links);
  }
}

function updateList() {
  refreshButtons();
  const terms = $("query").value.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const filtered = data.records.filter(record => {
    const corpus = [record.title, record.id, record.source, record.locator, record.summary, ...record.aliases].join(" ").toLowerCase();
    return (!state.index || state.index === record.index) && sourceMatches(record) && terms.every(term => corpus.includes(term));
  });
  if (!filtered.some(record => record.id === state.selected)) state.selected = filtered[0]?.id ?? null;
  $("count").textContent = `显示 ${filtered.length} / ${data.records.length} 条`;
  const list = $("list");
  list.replaceChildren();
  for (const record of filtered) {
    const entry = element("li");
    const control = button(null, "item", () => {
      state.selected = record.id;
      list.querySelector('[aria-pressed="true"]')?.setAttribute("aria-pressed", "false");
      control.setAttribute("aria-pressed", "true");
      showDetails(record);
      if (matchMedia("(max-width: 720px)").matches) $("details").scrollIntoView({block: "start"});
    });
    control.setAttribute("aria-pressed", String(record.id === state.selected));
    control.append(element("strong", record.title), element("small", `${names[record.index]} · ${record.locator}`));
    entry.append(control);
    list.append(entry);
  }
  if (!filtered.length) list.append(element("li", "没有符合当前筛选条件的条目。"));
  showDetails(state.selected ? records.get(state.selected) : null);
}

function render() {
  records = new Map(data.records.map(record => [record.id, record]));
  $("total").textContent = data.records.length;
  $("snapshot").textContent = `目录 ${data.snapshot.slice(0, 12)}`;
  const max = Math.max(1, ...data.indexes.map(index => index.count));
  for (const index of data.indexes) {
    const card = button(null, "index-card", () => {
      state.index = state.index === index.id ? "" : index.id;
      state.source = "";
      state.selected = null;
      $("query").value = "";
      updateList();
    });
    card.dataset.filter = index.id;
    const bar = element("span", null, "bar");
    bar.setAttribute("aria-hidden", "true");
    const fill = element("span");
    fill.style.width = `${100 * index.count / max}%`;
    bar.append(fill);
    card.append(element("span", `${names[index.id]} · ${index.id}`, "card-title"), element("strong", String(index.count)),
      bar, element("small", `主库 ${index.primary} · 补充 ${index.supplement} · 向量${index.vector_ready ? "已校验" : "待重建"}`));
    $("indexes").append(card);
  }
  for (const manual of data.manuals) {
    const card = button(null, "manual-card", () => setSource(manual.file));
    card.dataset.filter = manual.file;
    card.append(element("strong", manual.file), element("small", `${manual.count} 条 · 引用 ${manual.indexed_pages} / ${manual.pages} 页 · ${manual.available ? "原件已校验" : "原件待核对"}`));
    $("manuals").append(card);
  }
  for (const [id, title] of [["", "全部"], ["primary", "R12 主库"], ["supplement", "补充库"], ["books", "教材与讲义"]]) {
    const filter = button(title, "filter", () => setSource(id));
    filter.dataset.filter = id;
    $("sources").append(filter);
  }
  $("query").addEventListener("input", updateList);
  updateList();
  $("load-status").hidden = true;
  $("dashboard").hidden = false;
}

async function load() {
  try {
    const response = await fetch("/api/knowledge/status", {cache: "no-store"});
    const payload = await response.json();
    if (!response.ok || !payload.ok) throw new Error(payload.error?.message || "读取失败");
    data = payload.result;
    render();
  } catch (error) {
    $("load-status").textContent = `知识库状态无法读取。${error.message}`;
  }
}

load();
