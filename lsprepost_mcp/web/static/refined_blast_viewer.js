import { createModelViewer } from "./model_viewer_webgl.js";

const PREVIEW_LAYER_IDS = [
  "cavities_openings", "structure", "reinforcement_connections", "nonstructural",
  "exposed_surfaces", "blast_source", "fluid_domain", "boundaries", "support_ground",
];
const PREVIEW_COUNT_METRICS = [
  "building_nodes", "building_elements", "provider_nodes", "provider_elements",
  "provider_fsi_faces", "module_new_nodes", "module_new_elements", "symbolic_ids",
];
const LAYER_COLORS = ["#8ca3ad", "#d4d9dc", "#dc8d54", "#a7b77b", "#54a7a0", "#d94f64", "#478bc1", "#806db0", "#94785a"];
const MAX_SCENE_CACHE_ENTRIES = 8;
const MAX_NEUTRAL_PRIMITIVES_PER_LAYER = 4;
const MAX_NEUTRAL_PRIMITIVE_BYTES_PER_LAYER = 2_000_000;

function styleForPrimitive(layerId, primitiveId) {
  const ordinal = PREVIEW_LAYER_IDS.indexOf(layerId);
  const fallback = LAYER_COLORS[ordinal] ?? "#8ca3ad";
  if (primitiveId === "building-foundation-proxy") {
    return { color: "#a57b4f", opacity: 1.0, facesVisible: true };
  }
  if (primitiveId === "support-ground-proxy") {
    return { color: "#66513a", opacity: 0.78, facesVisible: true };
  }
  if (primitiveId === "coupling-buffer-proxy") {
    return { color: "#df9d45", opacity: 0.32, facesVisible: true };
  }
  if (primitiveId.endsWith("-mesh-grid")) {
    return { color: layerId === "fluid_domain" ? "#78c8e8" : "#e0c67d", opacity: 1.0, facesVisible: false };
  }
  if (primitiveId === "active-air-flow-boundary") {
    return { color: LAYER_COLORS[7], opacity: 1.0, facesVisible: false };
  }
  return {
    color: fallback,
    opacity: layerId === "fluid_domain" ? 0.14 : 1.0,
    facesVisible: true,
  };
}

function clone(value) { return structuredClone(value); }
function finitePoint(point) {
  return Array.isArray(point) && point.length === 3 && point.every((value) => Number.isFinite(Number(value)));
}

function validatePrimitive(primitive, layerId) {
  if (!primitive || typeof primitive !== "object" || Array.isArray(primitive)) {
    throw new Error(`refined preview ${layerId} primitive must be an object`);
  }
  if (typeof primitive.primitive_id !== "string" || !primitive.primitive_id) {
    throw new Error(`refined preview ${layerId} primitive_id is invalid`);
  }
  if (primitive.kind === "blast_source") {
    if (!finitePoint(primitive.position_m)) throw new Error(`refined preview ${layerId} blast source is invalid`);
    return;
  }
  if (primitive.kind !== "mesh") throw new Error(`refined preview ${layerId} primitive kind is invalid`);
  const nodes = Array.isArray(primitive.nodes) ? primitive.nodes : null;
  const faces = Array.isArray(primitive.faces) ? primitive.faces : null;
  const edges = Array.isArray(primitive.edges) ? primitive.edges : null;
  if (!nodes || !faces || !edges || !nodes.every(finitePoint)) {
    throw new Error(`refined preview ${layerId} neutral primitive geometry is invalid`);
  }
  const validIndex = (value) => Number.isInteger(value) && value >= 0 && value < nodes.length;
  if (!faces.every((face) => Array.isArray(face) && face.length >= 3 && face.every(validIndex))
      || !edges.every((edge) => Array.isArray(edge) && edge.length === 2 && edge.every(validIndex))) {
    throw new Error(`refined preview ${layerId} neutral primitive topology is invalid`);
  }
}

function validatePayload(payload) {
  if (!payload || typeof payload !== "object") throw new Error("authoritative refined preview is required");
  const layerIds = Array.isArray(payload.layers) ? payload.layers.map((row) => row?.layer_id) : [];
  if (JSON.stringify(layerIds) !== JSON.stringify(PREVIEW_LAYER_IDS)) throw new Error("refined preview layer order is invalid");
  const metricIds = Array.isArray(payload.counts) ? payload.counts.map((row) => row?.metric) : [];
  if (JSON.stringify(metricIds) !== JSON.stringify(PREVIEW_COUNT_METRICS)) throw new Error("refined preview metric order is invalid");
  for (const layer of payload.layers) {
    const evidence = layer.payload?.neutral_representation;
    if (!layer.payload || !Array.isArray(layer.payload.neutral_primitives)
        || !evidence || typeof evidence !== "object") {
      throw new Error(`refined preview ${layer.layer_id} has no authoritative neutral primitives`);
    }
    if (!Number.isInteger(evidence.primitive_count)
        || evidence.primitive_count !== layer.payload.neutral_primitives.length
        || evidence.primitive_count < 0
        || evidence.primitive_count > MAX_NEUTRAL_PRIMITIVES_PER_LAYER
        || !Number.isInteger(evidence.payload_byte_count)
        || evidence.payload_byte_count < 0
        || evidence.payload_byte_count > MAX_NEUTRAL_PRIMITIVE_BYTES_PER_LAYER
        || !["full_geometry", "deterministic_lod"].includes(evidence.representation)
        || typeof evidence.fingerprint !== "string" || !evidence.fingerprint) {
      throw new Error(`refined preview ${layer.layer_id} neutral primitive evidence is invalid`);
    }
    for (const primitive of layer.payload.neutral_primitives) validatePrimitive(primitive, layer.layer_id);
  }
  for (const row of payload.counts) {
    if (!Number.isInteger(row.value) || row.value < 0 || !["exact", "upper_bound"].includes(row.semantics)) {
      throw new Error("refined preview count semantics are invalid");
    }
  }
}

function boundsForParts(parts) {
  const points = parts.flatMap((part) => part.nodes);
  if (!points.length) return { min: [-0.5, -0.5, -0.5], max: [0.5, 0.5, 0.5] };
  const low = [Infinity, Infinity, Infinity]; const high = [-Infinity, -Infinity, -Infinity];
  for (const point of points) {
    for (let axis = 0; axis < 3; axis += 1) {
      low[axis] = Math.min(low[axis], Number(point[axis]));
      high[axis] = Math.max(high[axis], Number(point[axis]));
    }
  }
  return {
    min: low,
    max: high,
  };
}

function buildScene(payload, renderSignature) {
  const partsByLayer = new Map();
  const blastSourcesByLayer = new Map();
  for (const [ordinal, layer] of payload.layers.entries()) {
    const ids = new Set();
    const parts = []; const blastSources = [];
    for (const primitive of layer.payload.neutral_primitives) {
      const partId = `${layer.layer_id}::${primitive.primitive_id}`;
      if (ids.has(partId)) throw new Error(`duplicate refined preview primitive: ${partId}`);
      ids.add(partId);
      if (primitive.kind === "blast_source") {
        blastSources.push({ source_id: partId, position_m: primitive.position_m });
        continue;
      }
      const style = styleForPrimitive(layer.layer_id, primitive.primitive_id);
      parts.push({
        part_id: partId,
        name: primitive.primitive_id,
        color: style.color,
        opacity: style.opacity,
        nodes: primitive.nodes, faces: primitive.faces, edges: primitive.edges,
      });
    }
    partsByLayer.set(layer.layer_id, parts);
    blastSourcesByLayer.set(layer.layer_id, blastSources);
  }
  return {
    renderSignature,
    partsByLayer,
    blastSourcesByLayer,
    counts: clone(payload.counts),
    meshesByVisibility: new Map(),
  };
}

function meshForVisibility(scene, visible) {
  const key = PREVIEW_LAYER_IDS.filter((layerId) => visible.has(layerId)).join("|");
  if (scene.meshesByVisibility.has(key)) return scene.meshesByVisibility.get(key);
  const parts = PREVIEW_LAYER_IDS.flatMap((layerId) => visible.has(layerId) ? scene.partsByLayer.get(layerId) : []);
  const blastSources = PREVIEW_LAYER_IDS.flatMap((layerId) => visible.has(layerId) ? scene.blastSourcesByLayer.get(layerId) : []);
  const mesh = { parts, bounds: boundsForParts(parts), blast_sources: blastSources };
  scene.meshesByVisibility.set(key, mesh);
  return mesh;
}

export function renderRefinedBlastPreview(container, payload, options = {}) {
  const sceneCache = new Map();
  let currentPayload = null; let scene = null; let disposed = false;
  const visible = new Set(Array.isArray(options.visibleLayerIds) ? options.visibleLayerIds : PREVIEW_LAYER_IDS);
  let cameraPreset = "iso";
  const canvas = document.createElement("canvas");
  canvas.className = "refined-blast-preview-surface";
  canvas.setAttribute?.("aria-label", "精细化建筑爆炸九层预览");
  container.replaceChildren(canvas);
  let sourceEditorPosition = finitePoint(options.blastSourceEditor?.position_m)
    ? options.blastSourceEditor.position_m.map(Number) : null;
  let sourceId = null;
  let sourceEditor = null;
  let placeButton = null;
  const commitSourcePosition = (point) => {
    if (!sourceEditorPosition || !finitePoint(point)) return false;
    sourceEditorPosition = point.map(Number);
    if (sourceId) modelViewer?.updateBlastSourcePosition?.(sourceId, sourceEditorPosition);
    options.blastSourceEditor?.onCommit?.(sourceEditorPosition.slice());
    modelViewer?.setPointSelectionEnabled?.(false);
    placeButton?.setAttribute?.("aria-pressed", "false");
    return true;
  };
  const modelViewer = createModelViewer({ canvas, onPointSelected: commitSourcePosition });

  function buildSourceEditor() {
    if (!sourceEditorPosition || !options.blastSourceEditor) return;
    sourceEditor = document.createElement("div");
    sourceEditor.className = "refined-blast-source-editor";
    sourceEditor.setAttribute?.("aria-label", "爆源三维位置编辑器");
    placeButton = document.createElement("button");
    placeButton.type = "button";
    placeButton.className = "refined-blast-source-place";
    placeButton.dataset.refinedSourcePlace = "true";
    placeButton.setAttribute?.("aria-pressed", "false");
    placeButton.textContent = "在视图中放置";
    placeButton.addEventListener("click", () => {
      const next = placeButton.getAttribute?.("aria-pressed") !== "true";
      placeButton.setAttribute?.("aria-pressed", next ? "true" : "false");
      modelViewer?.setPointSelectionEnabled?.(next);
    });
    const hint = document.createElement("span");
    hint.textContent = "或拖动轴向调整";
    sourceEditor.append(placeButton, hint);
    const dragStep = Number.isFinite(Number(options.blastSourceEditor.drag_step_m))
      ? Math.max(Number(options.blastSourceEditor.drag_step_m), 1e-9) : 0.01;
    for (const [axis, axisIndex] of [["X", 0], ["Y", 1], ["Z", 2]]) {
      const handle = document.createElement("button");
      handle.type = "button";
      handle.className = `refined-blast-source-axis axis-${axis.toLowerCase()}`;
      handle.dataset.refinedSourceAxis = axis;
      handle.textContent = `${axis} 拖动`;
      let drag = null;
      handle.addEventListener("pointerdown", (event) => {
        drag = { x: event.clientX, y: event.clientY, pointerId: event.pointerId, origin: sourceEditorPosition.slice() };
        handle.setPointerCapture?.(event.pointerId);
        event.preventDefault?.();
      });
      handle.addEventListener("pointermove", (event) => {
        if (!drag) return;
        const pixels = axis === "Z" ? drag.y - event.clientY : event.clientX - drag.x;
        const next = drag.origin.slice();
        next[axisIndex] += pixels * dragStep;
        sourceEditorPosition = next;
        if (sourceId) modelViewer?.updateBlastSourcePosition?.(sourceId, next);
      });
      const releaseDragCapture = (activeDrag) => {
        const pointerId = activeDrag?.pointerId;
        if (!Number.isInteger(pointerId)) return;
        if (handle.hasPointerCapture?.(pointerId) === false) return;
        handle.releasePointerCapture?.(pointerId);
      };
      const finish = () => {
        if (!drag) return;
        const activeDrag = drag;
        drag = null;
        releaseDragCapture(activeDrag);
        options.blastSourceEditor.onCommit?.(sourceEditorPosition.slice());
      };
      const cancel = () => {
        if (!drag) return;
        const activeDrag = drag;
        sourceEditorPosition = activeDrag.origin.slice();
        if (sourceId) modelViewer?.updateBlastSourcePosition?.(sourceId, sourceEditorPosition);
        drag = null;
        releaseDragCapture(activeDrag);
      };
      handle.addEventListener("pointerup", finish);
      handle.addEventListener("pointercancel", cancel);
      handle.addEventListener("keydown", (event) => {
        if (event.key === "Escape") { cancel(event); event.preventDefault?.(); return; }
        const direction = ["ArrowRight", "ArrowUp"].includes(event.key) ? 1
          : ["ArrowLeft", "ArrowDown"].includes(event.key) ? -1 : 0;
        if (!direction) return;
        const next = sourceEditorPosition.slice();
        next[axisIndex] += direction * dragStep;
        commitSourcePosition(next);
        event.preventDefault?.();
      });
      sourceEditor.append(handle);
    }
    container.append(sourceEditor);
    modelViewer?.setPointSelectionEnabled?.(false);
  }

  function loadPayload(nextPayload) {
    validatePayload(nextPayload);
    const key = String(nextPayload.cache_key || "");
    const renderSignature = [
      nextPayload.fingerprint,
      ...nextPayload.layers.flatMap((layer) => [
        layer.fingerprint, layer.payload.neutral_representation.fingerprint,
      ]),
    ].join("|");
    const cached = sceneCache.get(key);
    scene = cached?.renderSignature === renderSignature ? cached : buildScene(nextPayload, renderSignature);
    sceneCache.set(key, scene);
    while (sceneCache.size > MAX_SCENE_CACHE_ENTRIES) sceneCache.delete(sceneCache.keys().next().value);
    currentPayload = {
      cache_key: nextPayload.cache_key,
      project_revision: nextPayload.project_revision,
      fingerprint: nextPayload.fingerprint,
    };
  }

  function syncScene({ preserveCamera = false } = {}) {
    if (disposed || !modelViewer?.supported) return false;
    modelViewer.sync({
      mesh: meshForVisibility(scene, visible), hiddenParts: new Set(),
      displayMode: "solid", showGrid: true, showBlastSources: true,
      preserveCamera,
    });
    sourceId = PREVIEW_LAYER_IDS.flatMap((layerId) => scene.blastSourcesByLayer.get(layerId) ?? [])[0]?.source_id ?? null;
    if (sourceId && sourceEditorPosition) modelViewer.updateBlastSourcePosition?.(sourceId, sourceEditorPosition);
    return true;
  }

  loadPayload(payload);
  syncScene();
  buildSourceEditor();
  if (modelViewer?.supported) modelViewer.fitView(cameraPreset);

  return {
    get cacheKey() { return String(currentPayload.cache_key); },
    get projectRevision() { return currentPayload.project_revision; },
    get fingerprint() { return currentPayload.fingerprint; },
    layerOrder: PREVIEW_LAYER_IDS.slice(),
    update(nextPayload) {
      if (disposed) return false;
      loadPayload(nextPayload); syncScene();
      if (modelViewer?.supported) modelViewer.fitView(cameraPreset);
      return true;
    },
    setLayerVisible(layerId, isVisible) {
      if (disposed || !PREVIEW_LAYER_IDS.includes(layerId)) return false;
      if (isVisible) visible.add(layerId); else visible.delete(layerId);
      syncScene({ preserveCamera: true }); return true;
    },
    getVisibleLayerIds() { return PREVIEW_LAYER_IDS.filter((layerId) => visible.has(layerId)); },
    getCountBadges() { return clone(scene.counts); },
    fitView(preset = "iso") {
      if (disposed || !modelViewer?.supported) return false;
      cameraPreset = ["iso", "front", "top"].includes(preset) ? preset : "iso";
      modelViewer.fitView(cameraPreset); return true;
    },
    dispose() {
      if (disposed) return;
      disposed = true; sceneCache.clear();
      modelViewer?.destroy?.();
      sourceEditor?.remove?.();
      canvas.remove();
    },
  };
}

export { PREVIEW_COUNT_METRICS, PREVIEW_LAYER_IDS };
