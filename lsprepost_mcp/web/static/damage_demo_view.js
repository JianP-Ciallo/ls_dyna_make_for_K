import { createModelViewer } from './model_viewer_webgl.js';
import { fieldMeshParts } from './damage_demo_field.js';

export const GRADE_COLORS = ['#279b79', '#a5b840', '#e7b13d', '#e4773b', '#bb4256'];
export const MISSING_COLOR = '#9aa8b2';
export function gradeOf(record) {
  return record && record.gate !== 'blocked' && Number.isInteger(record.severity)
    && record.severity >= 0 && record.severity <= 4 ? record.severity : null;
}

export function createDemoView(scene, canvas, onSelect) {
  const viewer = createModelViewer({ canvas, onPartSelected: onSelect });
  if (!viewer.supported) throw new Error('当前浏览器无法启用 WebGL，请使用支持三维显示的浏览器。');
  let mesh = null, sourceKey = '', lastField = null;
  return {
    update(input, snapshot, selected, hideWalls, field = null) {
      const key = JSON.stringify(input.sources);
      if (!mesh || key !== sourceKey || field !== lastField) {
        lastField = field;
        sourceKey = key;
        mesh = { ...scene.mesh, parts: field ? fieldMeshParts(field) : scene.mesh.parts.map(p => ({ ...p, color: MISSING_COLOR })),
          bounds: { min: [-13, -13, -1], max: [13, 13, 11] },
          blast_sources: input.sources.filter(s => s.position_m.every(Number.isFinite)).map((s, i) => ({
            source_id: '演示爆源-' + (i + 1), position_m: s.position_m, radius_m: .45,
          })) };
        for (const source of mesh.blast_sources) {
          source.position_m.forEach((value, i) => {
            mesh.bounds.min[i] = Math.min(mesh.bounds.min[i], value - 1);
            mesh.bounds.max[i] = Math.max(mesh.bounds.max[i], value + 1);
          });
        }
      }
      viewer.sync({ mesh, preserveCamera: true,
        hiddenParts: new Set(hideWalls ? scene.components.filter(c => c.role === 'wall').map(c => String(c.part_id)) : []),
        selectedPartId: selected, displayMode: 'solid', showGrid: true, showBlastSources: true });
    },
    fit: () => viewer.fitView('iso'),
    destroy: () => viewer.destroy(),
  };
}
