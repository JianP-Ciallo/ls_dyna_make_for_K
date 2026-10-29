// Independent demo controller: no project store, localStorage or real assessment route.
import { createDemoView, gradeOf, GRADE_COLORS, MISSING_COLOR } from './damage_demo_view.js';
import { createDemoField } from './damage_demo_field.js';

const el = name => document.querySelector('[data-demo-' + name + ']');
const links = ['report', 'download', 'building-csv', 'ground-csv', 'evidence'];
const warning = '合成数据演示，非真实求解预测；不能用于实际爆源设计、毁伤预测或建筑安全鉴定。';
const state = { scene: null, input: null, result: null, field: null, selected: '', view: null, busy: false, alive: true, urls: [] };
const lifecycle = new AbortController();
const numeric = value => typeof value === 'number' && Number.isFinite(value) ? value.toPrecision(4) : '未提供';
const labelGrade = record => gradeOf(record) === null ? '不可评估 · 无等级' : '等级 ' + gradeOf(record) + ' · 研究参考';
function setStatus(kind, text) { document.querySelector('main').dataset.demoState = kind; el('status').textContent = text; }
function clearExports() {
  state.urls.forEach(url => URL.revokeObjectURL(url)); state.urls = [];
  links.forEach(name => { el(name).removeAttribute('href'); el(name).setAttribute('aria-disabled', 'true'); });
}
function componentRecord(component) {
  return component.role === 'ground' ? state.result?.snapshot.ground
    : state.result?.snapshot.building.components.find(c => c.component_id === component.component_id);
}
function updateView() {
  state.view?.update(state.input, state.result?.snapshot, state.selected, el('hide-walls').checked, state.field);
}
function selectComponent(partId) {
  state.selected = String(partId);
  updateView();
  showDetail();
  el('components').querySelectorAll('[data-component-id]').forEach(row =>
    row.setAttribute('aria-pressed', String(row.dataset.partId === state.selected)));
}
function showDetail() {
  const host = el('detail');
  host.replaceChildren();
  const component = state.scene?.components.find(c => String(c.part_id) === state.selected);
  if (!component) { host.textContent = '选择模型构件或右侧明细行，查看对应结果。'; return; }
  const heading = document.createElement('strong'); heading.textContent = component.label; host.append(heading);
  const record = componentRecord(component);
  const grade = document.createElement('p');
  grade.textContent = state.result ? labelGrade(record) : '未评估 / 结果待更新'; host.append(grade);
  if (gradeOf(record) === null) {
    const note = document.createElement('p');
    note.textContent = state.result ? '数据不足，未输出该对象的等级。请查看右侧数据限制。' : '重新评估后显示指标和判定依据。';
    host.append(note); return;
  }
  const metrics = component.role === 'ground'
    ? { '末态凹陷深度（m）': record.final?.crater?.maximum_depth,
        '末态沉降深度（m）': record.final?.settlement?.maximum_depth }
    : { '相对变形 P99': record.p99_relative_deformation, '受影响比例': record.affected_fraction,
        '连续受影响单元': record.connected_affected_count, ...record.response_metrics };
  const list = document.createElement('dl');
  Object.entries(metrics).forEach(([key, value]) => {
    const term = document.createElement('dt'), definition = document.createElement('dd');
    term.textContent = key; definition.textContent = numeric(value); list.append(term, definition);
  });
  host.append(list);
  const local = state.field?.parts.find(p => p.component_id === component.component_id);
  if (local?.values) {
    const note = document.createElement('p'); note.dataset.demoLocalRange = '';
    note.textContent = '表面演示影响值：' + numeric(local.minimum) + '—' + numeric(local.maximum)
      + '（固定 0—1 标尺，无量纲）。连续云图不等于局部损伤等级，不参与上方整体定级。';
    host.append(note);
  }
  const basis = document.createElement('p');
  const hits = component.role === 'ground'
    ? Object.values(record.subratings ?? {}).flatMap(r => r.rule_hits ?? []) : record.rule_hits;
  basis.textContent = '判定依据：' + (hits?.join('；') || '当前研究规则未命中更高等级条件。');
  host.append(basis);
}
function renderComponents() {
  const host = el('components'); host.replaceChildren();
  state.scene.components.forEach(component => {
    const grade = gradeOf(componentRecord(component));
    const row = document.createElement('button'); row.type = 'button'; row.className = 'component-row';
    row.dataset.componentId = component.component_id; row.dataset.componentRole = component.role;
    row.dataset.partId = String(component.part_id); row.dataset.grade = grade === null ? 'missing' : String(grade);
    row.setAttribute('aria-pressed', String(row.dataset.partId === state.selected));
    const dot = document.createElement('i'); dot.className = 'grade-dot'; dot.style.background = grade === null ? MISSING_COLOR : GRADE_COLORS[grade];
    const name = document.createElement('span'); name.textContent = component.label;
    const badge = document.createElement('span'); badge.className = 'grade-label'; badge.textContent = grade === null ? '无等级' : '等级 ' + grade;
    row.append(dot, name, badge); row.addEventListener('click', () => selectComponent(component.part_id)); host.append(row);
  });
  el('count').textContent = '(' + state.scene.components.length + ')';
}
function clearResults(message = '参数已修改，旧结果已清除，请重新评估。', kind = 'stale') {
  state.result = null; state.field = null; clearExports();
  ['overall', 'building', 'ground'].forEach(name => { el(name).textContent = '未评估'; });
  el('identity').textContent = '尚未生成当前设置的演示评估。';
  el('ground-metrics').textContent = '评估后显示实际引擎输出。';
  el('limitations').textContent = '尚未评估。'; el('rules').textContent = '评估后可查看规则命中和完整证据包。';
  renderComponents(); showDetail(); updateView(); setStatus(kind, message);
}
function renderSources() {
  const host = el('sources'); host.replaceChildren();
  state.input.sources.forEach((source, index) => {
    const row = document.createElement('section'); row.className = 'source-row'; row.dataset.sourceRow = '';
    const heading = document.createElement('div'); heading.className = 'source-heading';
    const title = document.createElement('strong'); title.textContent = '爆源 ' + (index + 1);
    const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'secondary';
    remove.dataset.sourceRemove = ''; remove.textContent = '移除'; remove.disabled = state.input.sources.length === 1;
    remove.addEventListener('click', () => { state.input.sources.splice(index, 1); renderSources(); clearResults(); });
    heading.append(title, remove); row.append(heading);
    const grid = document.createElement('div'); grid.className = 'source-grid';
    [['x', 'X（m）', -15, 15], ['y', 'Y（m）', -15, 15], ['z', '高度（m）', 0, 15], ['quantity', '当量（kg）', 1, 1000]].forEach(([key, text, min, max], axis) => {
      const label = document.createElement('label'); label.textContent = text;
      const input = document.createElement('input'); input.type = 'number'; input.min = min; input.max = max;
      input.step = key === 'quantity' ? '1' : '.1'; input.required = true; input.setAttribute('data-source-' + key, '');
      input.setAttribute('aria-label', '爆源 ' + (index + 1) + ' ' + text);
      input.value = axis === 3 ? source.equivalent_kg : source.position_m[axis];
      input.addEventListener('input', () => {
        if (axis === 3) source.equivalent_kg = input.valueAsNumber; else source.position_m[axis] = input.valueAsNumber;
        clearResults();
      });
      label.append(input); grid.append(label);
    });
    row.append(grid); host.append(row);
  });
  el('add-source').disabled = state.input.sources.length >= 5;
}
async function request(path, options = {}) {
  const response = await fetch(path, { cache: 'no-store', ...options, signal: lifecycle.signal });
  const body = await response.json();
  if (!response.ok || body.ok !== true) throw new Error(body.error?.message || '演示接口暂不可用，请重试。');
  return body.result;
}
async function validateResult(result, input) {
  if (result?.schema_version !== 'lsprepost_mcp.synthetic_damage_result@1' || result.synthetic_demo !== true
      || JSON.stringify(result.input) !== JSON.stringify(input)
      || result.snapshot?.identity?.project_id !== 'synthetic-demo-only'
      || result.snapshot?.adapter?.id !== 'synthetic_demo') throw new Error('演示响应与当前设置不一致，未显示结果。');
  for (const subject of ['overall', 'building', 'ground']) {
    const record = result.snapshot[subject];
    if (!record || !['blocked', 'provisional'].includes(record.gate)
        || (record.gate === 'blocked' ? record.severity !== null : gradeOf(record) === null))
      throw new Error('评估门禁或等级不合法，未显示结果。');
  }
  const names = ['assessment_request.json', 'assessment_result.json', 'assessment_snapshot.json', 'evidence_index.json',
    'rule_snapshot.json', 'damage_report.html', 'building_components.csv', 'ground_regions.csv'];
  if (Object.keys(result.artifacts ?? {}).sort().join() !== [...names].sort().join()) throw new Error('演示工件不完整。');
  for (const name of names) {
    const artifact = result.artifacts[name];
    if (typeof artifact.text !== 'string') throw new Error('演示工件格式错误。');
    const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(artifact.text));
    const hex = [...new Uint8Array(digest)].map(v => v.toString(16).padStart(2, '0')).join('');
    if (hex !== artifact.sha256) throw new Error('演示工件校验失败，未显示结果。');
  }
  if (JSON.stringify(JSON.parse(result.artifacts['assessment_snapshot.json'].text)) !== JSON.stringify(result.snapshot))
    throw new Error('演示快照与报告来源不一致。');
  return result;
}
function bindExport(name, content, type) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  state.urls.push(url); el(name).href = url; el(name).setAttribute('aria-disabled', 'false');
}
function renderResult() {
  const result = state.result, snapshot = result.snapshot;
  ['building', 'ground'].forEach(name => { el(name).textContent = labelGrade(snapshot[name]); });
  el('overall').textContent = snapshot.overall.gate === 'blocked' ? '不可整体评估' : '暂定 · 研究参考';
  const ground = snapshot.ground;
  el('ground-metrics').textContent = gradeOf(ground) === null ? '地面数据不可核验，未输出几何指标。'
    : '末态凹陷深度：' + numeric(ground.final.crater.maximum_depth) + ' m；沉降深度：'
      + numeric(ground.final.settlement.maximum_depth) + ' m；凹陷投影面积：'
      + numeric(ground.final.crater.plan_area) + ' m²。合成尾段：' + (ground.stability?.stable ? '稳定' : '未稳定') + '。';
  const notes = [warning,
    state.field.warning,
    '未覆盖真实 d3plot 解析链路验证和正式工程鉴定。多爆源仅驱动合成数据，不模拟实际传播和叠加。',
    '地面几何的径向统计以第一个演示爆源为参考，不代表每个爆源独立形成的爆坑。',
    ...(state.input.mode === 'partial' ? ['当前模式故意提供无法核验的地面 Part 身份：建筑保留结果，地面拒绝定级。'] : []),
    ...(state.input.mode === 'blocked' ? ['当前模式故意缺失位移数据：现有门禁拒绝整体、建筑及地面定级。'] : []),
    ...(snapshot.limitations ?? []), ...['building', 'ground'].flatMap(key => (snapshot[key].issues ?? []).map(i =>
      i.code + '：' + i.message + (i.details?.remediation ? ' / ' + i.details.remediation : '')))];
  const list = document.createElement('ul');
  [...new Set(notes)].forEach(text => { const item = document.createElement('li'); item.textContent = text; list.append(item); });
  el('limitations').replaceChildren(list);
  const rule = document.createElement('pre');
  rule.textContent = result.artifacts['rule_snapshot.json'].text;
  el('rules').replaceChildren(rule);
  el('identity').textContent = '演示评估 ID：' + snapshot.assessment_id + ' · 指纹：' + snapshot.assessment_fingerprint;
  const banner = '<section style="padding:20px;background:#fff0cf;border:3px solid #d8a438;color:#63450c"><h1>合成演示 · 损伤评估报告</h1><p>'
    + warning + '</p><p>以下为现有评估规则处理合成输入的结果，不是求解完成证据。</p><p>'
    + state.field.warning + ' 表面采样值另存于完整证据包 display_field，不包含在原始评估工件内。</p></section>';
  const report = result.artifacts['damage_report.html'].text.replace(/<body[^>]*>/i, match => match + banner);
  bindExport('report', report, 'text/html;charset=utf-8'); bindExport('download', report, 'text/html;charset=utf-8');
  for (const [name, artifact] of [['building-csv', 'building_components.csv'], ['ground-csv', 'ground_regions.csv']])
    bindExport(name, '\ufeff"' + warning + '"\r\n' + result.artifacts[artifact].text.replace(/^\ufeff/, ''), 'text/csv;charset=utf-8');
  bindExport('evidence', JSON.stringify({ ...result, display_field: state.field }, null, 2), 'application/json;charset=utf-8');
  renderComponents(); showDetail(); updateView();
}
async function evaluate() {
  if (state.busy) return;
  const invalid = [...el('inputs').querySelectorAll('input')].find(input => !input.checkValidity());
  if (invalid) { invalid.reportValidity(); setStatus('error', '请先修正超出范围或缺失的爆源参数。'); return; }
  clearResults('正在评估合成输入…', 'running'); state.busy = true; el('inputs').disabled = true;
  const input = structuredClone(state.input);
  try {
    const result = await request('/api/damage-assessment/demo/evaluate', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(input),
    });
    await validateResult(result, input);
    if (!state.alive || JSON.stringify(state.input) !== JSON.stringify(input)) return;
    state.result = result; state.field = createDemoField(state.scene, input, result.snapshot); renderResult();
    setStatus('evaluated', '评估完成 · 合成数据 · ' + (result.snapshot.overall.gate === 'blocked' ? '存在不可评估对象，请查看原因。' : '仅研究参考。'));
  } catch (error) {
    if (state.alive) clearResults(error.message || '演示评估失败，请重试。', 'error');
  } finally {
    state.busy = false; if (state.alive) el('inputs').disabled = false;
  }
}
async function start() {
  try {
    state.scene = await request('/api/damage-assessment/demo/scene');
    if (state.scene.synthetic_demo !== true || state.scene.schema_version !== 'lsprepost_mcp.synthetic_damage_scene@1')
      throw new Error('演示场景版本不兼容，请刷新页面。');
    state.input = structuredClone(state.scene.defaults);
    state.view = createDemoView(state.scene, document.querySelector('canvas'), selectComponent);
    renderSources(); clearResults('场景已就绪。修改爆源或数据状态，然后点击开始评估。', 'ready');
    state.view.fit(); el('fit').disabled = false; el('inputs').disabled = false;
    el('fit').addEventListener('click', () => state.view.fit());
    el('hide-walls').addEventListener('change', updateView);
    el('mode').addEventListener('change', () => { state.input.mode = el('mode').value; clearResults(); });
    el('add-source').addEventListener('click', () => {
      if (state.input.sources.length >= 5) return;
      state.input.sources.push({ position_m: [6, 4, 2], equivalent_kg: 100 }); renderSources(); clearResults();
    });
    el('reset').addEventListener('click', () => {
      state.input = structuredClone(state.scene.defaults); el('mode').value = state.input.mode;
      renderSources(); clearResults('已恢复默认设置，点击开始评估。', 'ready');
    });
    el('evaluate').addEventListener('click', evaluate);
    await registerDemoNavigation();
  } catch (error) {
    state.view?.destroy(); setStatus('error', error.message + ' 请退出演示后重试。');
  }
}
window.addEventListener('pagehide', () => {
  state.alive = false; lifecycle.abort(); clearExports(); state.view?.destroy();
}, { once: true });
start();

async function registerDemoNavigation(){
 const n=window.WorkbenchNavigation;if(!n)return;
 await n.register('assessment',{
  restoreIdentity:()=> 'synthetic-demo',context:()=>({identity:'synthetic-demo',label:'合成场景 · 评估参数',url:'/damage_assessment_demo.html'}),
  capture:()=>({input:structuredClone(state.input),fields:n.captureFields(document.querySelector('.demo-shell')),selected:state.selected}),
  restore:s=>{if(!Array.isArray(s.input?.sources)||s.input.sources.length<1||s.input.sources.length>5)throw Error('演示参数不兼容');state.input=structuredClone(s.input);renderSources();n.restoreFields(document.querySelector('.demo-shell'),s.fields);state.selected=s.selected||'';clearResults('已恢复本标签页参数，点击开始评估后才更新结果。','ready');},
 });
}
