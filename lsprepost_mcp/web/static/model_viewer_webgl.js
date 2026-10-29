import * as THREE from "three";
import { OrbitControls } from "/vendor/three/addons/controls/OrbitControls.js";

const DEFAULT_COLOR = "#d94157";
const EDGE_COLOR = "#10191f";
const SELECTED_EDGE_COLOR = "#ffe36e";

function finitePoint(point) {
  return Array.isArray(point)
    && point.length >= 3
    && point.slice(0, 3).every((value) => Number.isFinite(Number(value)));
}

function colorValue(value, fallback = DEFAULT_COLOR) {
  try {
    return new THREE.Color(value || fallback);
  } catch (_error) {
    return new THREE.Color(fallback);
  }
}

function disposeObject(root) {
  root.traverse((child) => {
    child.geometry?.dispose();
    if (Array.isArray(child.material)) {
      child.material.forEach((material) => material.dispose());
    } else {
      child.material?.dispose();
    }
  });
}

function surfaceGeometry(part) {
  const nodes = Array.isArray(part.nodes) ? part.nodes : [];
  const positions = new Float32Array(nodes.length * 3);
  for (let index = 0; index < nodes.length; index += 1) {
    const point = finitePoint(nodes[index]) ? nodes[index] : [0, 0, 0];
    positions[index * 3] = Number(point[0]);
    positions[index * 3 + 1] = Number(point[1]);
    positions[index * 3 + 2] = Number(point[2]);
  }

  const indices = [];
  for (const face of Array.isArray(part.faces) ? part.faces : []) {
    if (!Array.isArray(face) || face.length < 3) continue;
    const valid = face.every((value) => Number.isInteger(value) && value >= 0 && value < nodes.length);
    if (!valid) continue;
    for (let index = 1; index < face.length - 1; index += 1) {
      indices.push(face[0], face[index], face[index + 1]);
    }
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  // Optional sRGB vertex colors; legacy parts without a complete valid array keep flat colors.
  if (Array.isArray(part.vertex_colors) && part.vertex_colors.length === nodes.length
      && part.vertex_colors.every(rgb => Array.isArray(rgb) && rgb.length === 3
        && rgb.every(v => Number.isFinite(v) && v >= 0 && v <= 1))) {
    const linear = part.vertex_colors.flatMap(rgb => rgb.map(v =>
      v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4));
    geometry.setAttribute("color", new THREE.Float32BufferAttribute(linear, 3));
  }
  geometry.setIndex(indices);
  geometry.computeVertexNormals();
  geometry.computeBoundingSphere();
  return geometry;
}

function edgeGeometry(part) {
  const nodes = Array.isArray(part.nodes) ? part.nodes : [];
  const positions = [];
  // The backend edge list contains every preview mesh edge. Do not replace this
  // with EdgesGeometry: feature-edge extraction would hide internal grid lines.
  for (const edge of Array.isArray(part.edges) ? part.edges : []) {
    if (!Array.isArray(edge) || edge.length < 2) continue;
    const first = nodes[edge[0]];
    const second = nodes[edge[1]];
    if (!finitePoint(first) || !finitePoint(second)) continue;
    positions.push(
      Number(first[0]), Number(first[1]), Number(first[2]),
      Number(second[0]), Number(second[1]), Number(second[2]),
    );
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  geometry.computeBoundingSphere();
  return geometry;
}

function meshBounds(mesh) {
  const low = mesh?.bounds?.min;
  const high = mesh?.bounds?.max;
  if (finitePoint(low) && finitePoint(high)) {
    const box = new THREE.Box3(
      new THREE.Vector3(Number(low[0]), Number(low[1]), Number(low[2])),
      new THREE.Vector3(Number(high[0]), Number(high[1]), Number(high[2])),
    );
    if (!box.isEmpty()) return box;
  }
  return new THREE.Box3(
    new THREE.Vector3(-0.5, -0.5, -0.5),
    new THREE.Vector3(0.5, 0.5, 0.5),
  );
}

function createBlastSource(source, scale) {
  const group = new THREE.Group();
  group.userData.sourceId = String(source.source_id || "");
  const radius = Math.max(Number(source.radius_m || 0), scale * 0.008);
  const material = new THREE.LineBasicMaterial({ color: 0xffd54a });
  const ring = new THREE.LineLoop(
    new THREE.BufferGeometry().setFromPoints(
      Array.from({ length: 48 }, (_, index) => {
        const angle = (index / 48) * Math.PI * 2;
        return new THREE.Vector3(Math.cos(angle) * radius, Math.sin(angle) * radius, 0);
      }),
    ),
    material,
  );
  const cross = new THREE.LineSegments(
    new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(-radius * 1.3, 0, 0),
      new THREE.Vector3(radius * 1.3, 0, 0),
      new THREE.Vector3(0, -radius * 1.3, 0),
      new THREE.Vector3(0, radius * 1.3, 0),
      new THREE.Vector3(0, 0, -radius * 1.3),
      new THREE.Vector3(0, 0, radius * 1.3),
    ]),
    material.clone(),
  );
  const position = finitePoint(source.position_m) ? source.position_m : [0, 0, 0];
  group.position.set(Number(position[0]), Number(position[1]), Number(position[2]));
  group.add(ring, cross);
  return group;
}

export function createModelViewer({
  canvas,
  onPartSelected = () => {},
  onPointSelected = () => {},
  onContextLost = () => {},
  onContextRestored = () => {},
} = {}) {
  if (!(canvas instanceof HTMLCanvasElement)) {
    throw new Error("WebGL model viewer requires a canvas element.");
  }

  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: false });
  } catch (error) {
    return { supported: false, reason: error instanceof Error ? error.message : String(error) };
  }

  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
  const themeBackground = typeof getComputedStyle === "function"
    ? getComputedStyle(canvas).getPropertyValue("--wb-viewport").trim() : "";
  renderer.setClearColor(themeBackground || 0x20282e, 1);
  renderer.outputColorSpace = THREE.SRGBColorSpace;

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(45, 1, 0.001, 100000);
  camera.up.set(0, 0, 1);
  const controls = new OrbitControls(camera, canvas);
  controls.enableDamping = false;
  controls.screenSpacePanning = true;
  controls.zoomToCursor = true;

  scene.add(new THREE.HemisphereLight(0xeaf2f5, 0x25343c, 2.0));
  const keyLight = new THREE.DirectionalLight(0xffffff, 1.35);
  keyLight.position.set(30, -25, 55);
  scene.add(keyLight);

  const modelRoot = new THREE.Group();
  const blastRoot = new THREE.Group();
  scene.add(modelRoot, blastRoot);

  const state = {
    mesh: null,
    bounds: meshBounds(null),
    partObjects: new Map(),
    blastSourceObjects: new Map(),
    pickables: [],
    grid: null,
    axes: null,
    frameRequested: false,
    contextLost: false,
    disposed: false,
    pointerDown: null,
    pointSelectionEnabled: false,
    metrics: {
      backend: "webgl",
      frames: 0,
      geometryBuilds: 0,
      contextLosses: 0,
      lastGeometryBuildMs: 0,
      lastRenderMs: 0,
      partCount: 0,
      transparentPartCount: 0,
      faceCount: 0,
      edgeCount: 0,
    },
  };
  window.__MODEL_VIEWER_METRICS__ = state.metrics;

  function resize() {
    const rect = canvas.getBoundingClientRect();
    const width = Math.max(1, Math.floor(rect.width));
    const height = Math.max(1, Math.floor(rect.height));
    if (canvas.width !== Math.floor(width * renderer.getPixelRatio())
        || canvas.height !== Math.floor(height * renderer.getPixelRatio())) {
      renderer.setSize(width, height, false);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
    }
  }

  function renderNow() {
    state.frameRequested = false;
    if (state.contextLost || state.disposed) return;
    const start = performance.now();
    resize();
    renderer.render(scene, camera);
    state.metrics.frames += 1;
    state.metrics.lastRenderMs = performance.now() - start;
  }

  function invalidate() {
    if (state.frameRequested || state.contextLost || state.disposed) return;
    state.frameRequested = true;
    requestAnimationFrame(renderNow);
  }

  controls.addEventListener("change", invalidate);

  function clearModel() {
    for (const child of [...modelRoot.children]) {
      modelRoot.remove(child);
      disposeObject(child);
    }
    for (const child of [...blastRoot.children]) {
      blastRoot.remove(child);
      disposeObject(child);
    }
    state.partObjects.clear();
    state.blastSourceObjects.clear();
    state.pickables = [];
    if (state.grid) {
      scene.remove(state.grid);
      disposeObject(state.grid);
      state.grid = null;
    }
    if (state.axes) {
      scene.remove(state.axes);
      disposeObject(state.axes);
      state.axes = null;
    }
  }

  function buildModel(mesh, preserveCamera = false) {
    const started = performance.now();
    clearModel();
    state.mesh = mesh || null;
    state.bounds = meshBounds(mesh);
    state.metrics.partCount = 0;
    state.metrics.transparentPartCount = 0;
    state.metrics.faceCount = 0;
    state.metrics.edgeCount = 0;

    for (const part of Array.isArray(mesh?.parts) ? mesh.parts : []) {
      const partId = String(part.part_id);
      const group = new THREE.Group();
      group.userData.partId = partId;

      const requestedOpacity = Number(part.opacity);
      const opacity = Number.isFinite(requestedOpacity) && requestedOpacity > 0
        ? Math.min(requestedOpacity, 1) : 1;
      const transparent = opacity < 1;

      const surfaceMaterial = new THREE.MeshStandardMaterial({
        color: colorValue(part.color),
        opacity,
        transparent,
        depthWrite: !transparent,
        roughness: 0.78,
        metalness: 0.02,
        side: THREE.DoubleSide,
        polygonOffset: true,
        polygonOffsetFactor: 1,
        polygonOffsetUnits: 1,
      });
      const surface = new THREE.Mesh(surfaceGeometry(part), surfaceMaterial);
      surfaceMaterial.vertexColors = Boolean(surface.geometry.getAttribute("color"));
      surface.userData.partId = partId;
      const edges = new THREE.LineSegments(
        edgeGeometry(part),
        new THREE.LineBasicMaterial({ color: EDGE_COLOR }),
      );
      edges.userData.partId = partId;
      group.add(surface, edges);
      modelRoot.add(group);
      state.partObjects.set(partId, { group, surface, edges, part });
      state.pickables.push(surface);
      state.metrics.faceCount += Array.isArray(part.faces) ? part.faces.length : 0;
      state.metrics.edgeCount += Array.isArray(part.edges) ? part.edges.length : 0;
      if (transparent) state.metrics.transparentPartCount += 1;
    }
    state.metrics.partCount = state.partObjects.size;

    const size = state.bounds.getSize(new THREE.Vector3());
    const center = state.bounds.getCenter(new THREE.Vector3());
    const span = Math.max(size.x, size.y, size.z, 1e-6);
    const divisions = Math.max(10, Math.min(100, Math.round(span / Math.max(span / 40, 1e-6))));
    state.grid = new THREE.GridHelper(span * 1.6, divisions, 0x3d8b78, 0x44545c);
    state.grid.rotation.x = Math.PI / 2;
    state.grid.position.set(center.x, center.y, state.bounds.min.z - span * 0.002);
    scene.add(state.grid);
    state.axes = new THREE.AxesHelper(span * 0.12);
    state.axes.position.copy(state.bounds.min);
    scene.add(state.axes);

    for (const source of Array.isArray(mesh?.blast_sources) ? mesh.blast_sources : []) {
      const sourceObject = createBlastSource(source, span);
      blastRoot.add(sourceObject);
      state.blastSourceObjects.set(String(source.source_id || ""), sourceObject);
    }

    state.metrics.geometryBuilds += 1;
    state.metrics.lastGeometryBuildMs = performance.now() - started;
    if (!preserveCamera) fitView("iso");
    invalidate();
  }

  function fitView(preset = "iso") {
    const size = state.bounds.getSize(new THREE.Vector3());
    const center = state.bounds.getCenter(new THREE.Vector3());
    const span = Math.max(size.x, size.y, size.z, 1e-6);
    const fov = THREE.MathUtils.degToRad(camera.fov);
    const distance = Math.max(span * 1.2, (span * 0.65) / Math.tan(fov * 0.5));
    const directions = {
      iso: new THREE.Vector3(1, -1, 0.78),
      top: new THREE.Vector3(0, 0, 1),
      front: new THREE.Vector3(0, -1, 0.05),
    };
    const direction = (directions[preset] || directions.iso).normalize();
    camera.up.set(0, preset === "top" ? 1 : 0, preset === "top" ? 0 : 1);
    controls.target.copy(center);
    camera.position.copy(center).addScaledVector(direction, distance);
    camera.near = Math.max(span / 10000, 0.0001);
    camera.far = Math.max(span * 100, 1000);
    camera.updateProjectionMatrix();
    controls.minDistance = span * 0.005;
    controls.maxDistance = span * 100;
    controls.update();
    invalidate();
  }

  function setLegacyView(yaw, pitch) {
    const center = controls.target.clone();
    const distance = Math.max(camera.position.distanceTo(center), 1e-6);
    const cosine = Math.cos(Number(pitch));
    const direction = new THREE.Vector3(
      Math.cos(Number(yaw)) * cosine,
      Math.sin(Number(yaw)) * cosine,
      Math.sin(Number(pitch)),
    ).normalize();
    camera.position.copy(center).addScaledVector(direction, distance);
    controls.update();
    invalidate();
  }

  function sync(view) {
    if (view.mesh !== state.mesh) buildModel(view.mesh, Boolean(view.preserveCamera));
    const hidden = view.hiddenParts instanceof Set ? view.hiddenParts : new Set(view.hiddenParts || []);
    const risks = view.riskByPartId instanceof Map ? view.riskByPartId : new Map();
    const impactIds = view.selectedImpactPartIds instanceof Set
      ? view.selectedImpactPartIds
      : new Set(view.selectedImpactPartIds || []);
    for (const [partId, record] of state.partObjects) {
      record.group.visible = !hidden.has(partId);
      const selected = String(view.selectedPartId || "") === partId || impactIds.has(partId);
      const color = colorValue(view.riskColors?.[risks.get(partId)] || record.part.color);
      const vertexColors = record.surface.material.vertexColors;
      record.surface.material.color.copy(vertexColors ? colorValue("#ffffff") : color);
      record.surface.material.emissive.set(selected && !vertexColors ? 0x3b3100 : 0x000000);
      record.surface.material.emissiveIntensity = selected && !vertexColors ? 0.55 : 0;
      record.edges.material.color.set(selected ? SELECTED_EDGE_COLOR : EDGE_COLOR);
      record.surface.visible = view.displayMode !== "wireframe";
      record.edges.visible = true;
    }
    if (state.grid) state.grid.visible = Boolean(view.showGrid);
    if (state.axes) state.axes.visible = true;
    blastRoot.visible = Boolean(view.showBlastSources);
    invalidate();
  }

  const raycaster = new THREE.Raycaster();
  const pointer = new THREE.Vector2();
  function pick(event) {
    const rect = canvas.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
    raycaster.setFromCamera(pointer, camera);
    const hit = raycaster.intersectObjects(state.pickables, false)
      .find((item) => item.object.visible && item.object.parent?.visible);
    onPartSelected(hit ? String(hit.object.userData.partId) : "");
    if (state.pointSelectionEnabled && hit?.point) {
      onPointSelected([hit.point.x, hit.point.y, hit.point.z]);
    }
  }

  const canvasListeners = [];
  function listenCanvas(type, handler) {
    canvas.addEventListener(type, handler);
    canvasListeners.push([type, handler]);
  }

  listenCanvas("pointerdown", (event) => {
    state.pointerDown = { x: event.clientX, y: event.clientY, button: event.button };
  });
  listenCanvas("pointerup", (event) => {
    const start = state.pointerDown;
    state.pointerDown = null;
    if (!start || start.button !== 0) return;
    if (Math.hypot(event.clientX - start.x, event.clientY - start.y) <= 4) pick(event);
  });
  listenCanvas("contextmenu", (event) => event.preventDefault());

  listenCanvas("webglcontextlost", (event) => {
    event.preventDefault();
    state.contextLost = true;
    state.metrics.contextLosses += 1;
    onContextLost();
  });
  listenCanvas("webglcontextrestored", () => {
    state.contextLost = false;
    if (state.mesh) buildModel(state.mesh, true);
    onContextRestored();
    invalidate();
  });

  const resizeObserver = new ResizeObserver(invalidate);
  resizeObserver.observe(canvas);
  fitView("iso");

  return {
    supported: true,
    sync,
    fitView,
    setLegacyView,
    setPointSelectionEnabled(enabled) {
      state.pointSelectionEnabled = Boolean(enabled);
      canvas.classList?.toggle("is-point-selecting", state.pointSelectionEnabled);
    },
    updateBlastSourcePosition(sourceId, position) {
      if (!finitePoint(position)) return false;
      const source = state.blastSourceObjects.get(String(sourceId));
      if (!source) return false;
      source.position.set(Number(position[0]), Number(position[1]), Number(position[2]));
      invalidate();
      return true;
    },
    invalidate,
    metrics: state.metrics,
    destroy() {
      state.disposed = true;
      controls.removeEventListener("change", invalidate);
      for (const [type, handler] of canvasListeners) canvas.removeEventListener(type, handler);
      canvasListeners.length = 0;
      resizeObserver.disconnect();
      controls.dispose();
      clearModel();
      renderer.dispose();
    },
  };
}
