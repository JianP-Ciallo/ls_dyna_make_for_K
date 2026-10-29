const assert = require('node:assert/strict');
const path = require('node:path');
const { pathToFileURL } = require('node:url');

(async () => {
  const { createDemoField, fieldMeshParts } = await import(pathToFileURL(path.resolve('lsprepost_mcp/web/static/damage_demo_field.js')));
  const column = { component_id: 'c', part_id: 1, role: 'column', low: [-.2, -.2, 0], high: [.2, .2, 3] };
  const ground = { component_id: 'g', part_id: 2, role: 'ground', low: [-3, -3, -.5], high: [3, 3, 0] };
  const scene = { components: [column, ground] };
  const input = { sources: [{ position_m: [0, -1, 1.5], equivalent_kg: 100 }] };
  const snapshot = { assessment_id: 'a', building: { components: [{ component_id: 'c', gate: 'provisional', severity: 2 }] }, ground: { gate: 'provisional', severity: 1 } };
  const field = createDemoField(scene, input, snapshot);
  const values = field.parts[0].values;
  assert.equal(field.synthetic_demo, true);
  assert.equal(field.assessment_id, 'a');
  assert(values.length > 100, 'A column needs surface samples, not only eight corners');
  const at = z => values.filter((v, i) => Math.abs(field.parts[0].nodes[i][2] - z) < .001);
  assert(Math.min(...at(1.5)) > Math.max(...at(0)) + .15, 'Mid-height must be stronger than lower end for a mid-height source');
  assert(Math.min(...at(1.5)) > Math.max(...at(3)) + .15, 'Mid-height must be stronger than upper end');
  assert(values.every(v => Number.isFinite(v) && v >= 0 && v <= 1));
  assert.deepEqual(createDemoField(scene, input, snapshot), field, 'Same accepted input must be repeatable');
  for (const changed of [
    { position_m: [2, -1, 1.5], equivalent_kg: 100 },
    { position_m: [0, -4, 1.5], equivalent_kg: 100 },
    { position_m: [0, -1, 3], equivalent_kg: 100 },
    { position_m: [0, -1, 1.5], equivalent_kg: 500 },
  ]) assert.notDeepEqual(createDemoField(scene, { sources: [changed] }, snapshot).parts[0].values, values);
  const raised = createDemoField(scene, { sources: [{ position_m: [0, -1, 3], equivalent_kg: 100 }] }, snapshot).parts[0];
  assert(raised.values[raised.nodes.findIndex(p => p[2] === 3)] > raised.values[raised.nodes.findIndex(p => p[2] === 1.5)], 'Peak must follow height, not stay at column middle');
  assert.notDeepEqual(createDemoField(scene, { sources: [...input.sources, { position_m: [2, 0, 1], equivalent_kg: 100 }] }, snapshot).parts[0].values, values);
  const partial = createDemoField(scene, input, { ...snapshot, ground: { gate: 'blocked', severity: null } });
  assert.equal(partial.parts[1].values, null, 'Missing ground must remain gray');
  assert.equal(createDemoField(scene, input, null), null, 'Stale or unassessed input must have no field');
  const mesh = fieldMeshParts(field);
  assert.equal(mesh[0].vertex_colors.length, mesh[0].nodes.length);
  assert(new Set(mesh[0].vertex_colors.map(c => c.join(','))).size > 20, 'Continuous colors, not five grade bands');
  assert(mesh.every(p => p.faces.every(f => f.every(i => i >= 0 && i < p.nodes.length))));
  assert(mesh.every(p => p.edges.length >= 12 && p.edges.every(e => e.every(i => i >= 0 && i < p.nodes.length))), 'Selected components need valid outer edges without painting over the field');
  assert.equal(fieldMeshParts(partial)[1].vertex_colors, undefined);
  assert(new Set(field.parts[1].values.map(v => v.toFixed(5))).size > 20, 'Ground must also vary locally');
  console.log('Surface gradients, moving sources, stable scale, gates and mesh mapping passed.');
})().catch(error => { console.error(error); process.exit(1); });
