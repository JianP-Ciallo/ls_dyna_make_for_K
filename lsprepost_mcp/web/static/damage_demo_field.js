// Presentation-only scalar field. No pressure, impulse, blast scaling or damage law.
// Fixed scales avoid per-frame normalization: identical values always have identical colors.
export const IMPACT_COLORS = ['#279b79', '#d4cb3e', '#ed8735', '#d4474e'];
const GRAY = '#9aa8b2';

function surface(component) {
  const { low, high } = component;
  const nodes = [], faces = [], edges = [];
  const step = component.role === 'ground' ? .75 : .25;
  for (let axis = 0; axis < 3; axis++) {
    const u = (axis + 1) % 3, v = (axis + 2) % 3;
    const nu = Math.max(1, Math.ceil((high[u] - low[u]) / step));
    const nv = Math.max(1, Math.ceil((high[v] - low[v]) / step));
    for (const side of [low[axis], high[axis]]) {
      const start = nodes.length;
      for (let j = 0; j <= nv; j++) for (let i = 0; i <= nu; i++) {
        const point = [...low]; point[axis] = side;
        point[u] += (high[u] - low[u]) * i / nu;
        point[v] += (high[v] - low[v]) * j / nv;
        nodes.push(point);
      }
      for (let j = 0; j < nv; j++) for (let i = 0; i < nu; i++) {
        const a = start + j * (nu + 1) + i;
        const face = [a, a + 1, a + nu + 2, a + nu + 1];
        faces.push(side === low[axis] ? face.reverse() : face);
      }
      const corners = [start, start + nu, start + nv * (nu + 1) + nu, start + nv * (nu + 1)];
      corners.forEach((a, i) => edges.push([a, corners[(i + 1) % 4]]));
    }
  }
  return { nodes, faces, edges };
}

function intensity(point, sources) {
  let total = 0;
  for (const source of sources) {
    const [dx, dy, dz] = point.map((value, i) => value - source.position_m[i]);
    // Deliberately arbitrary display envelope; height controls where a local peak appears.
    total += (.65 + source.equivalent_kg / 1000)
      * Math.exp(-.5 * ((dx / 9) ** 2 + (dy / 9) ** 2 + (dz / 1.5) ** 2));
  }
  return Math.min(1, Math.max(0, total));
}

function rgb(value) {
  const position = value * (IMPACT_COLORS.length - 1);
  const index = Math.min(IMPACT_COLORS.length - 2, Math.floor(position));
  const mix = position - index;
  const channel = (hex, offset) => parseInt(hex.slice(offset, offset + 2), 16) / 255;
  return [1, 3, 5].map(offset => channel(IMPACT_COLORS[index], offset) * (1 - mix)
    + channel(IMPACT_COLORS[index + 1], offset) * mix);
}

export function createDemoField(scene, input, snapshot) {
  if (!snapshot) return null;
  const records = new Map(snapshot.building.components.map(c => [c.component_id, c]));
  return {
    schema_version: 'lsprepost_mcp.synthetic_surface_field@1', synthetic_demo: true,
    assessment_id: snapshot.assessment_id, input: structuredClone(input),
    quantity: 'dimensionless_display_influence', range: [0, 1], colors: IMPACT_COLORS,
    warning: '演示影响分布：独立合成显示值，不是冲击波压力、求解响应或局部损伤等级；不参与右侧定级。',
    parts: scene.components.map(component => {
      const mesh = surface(component);
      const record = component.role === 'ground' ? snapshot.ground : records.get(component.component_id);
      const available = record?.gate === 'provisional' && Number.isInteger(record.severity)
        && record.severity >= 0 && record.severity <= 4;
      const values = available ? mesh.nodes.map(p => intensity(p, input.sources)) : null;
      return { part_id: component.part_id, component_id: component.component_id, ...mesh, values,
        minimum: values ? Math.min(...values) : null, maximum: values ? Math.max(...values) : null };
    }),
  };
}

export function fieldMeshParts(field) {
  return field.parts.map(part => ({ part_id: part.part_id, nodes: part.nodes, faces: part.faces, edges: part.edges,
    color: part.values ? '#ffffff' : GRAY,
    ...(part.values ? { vertex_colors: part.values.map(rgb) } : {}),
  }));
}
