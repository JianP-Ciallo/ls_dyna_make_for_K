import * as THREE from "three";
import { OrbitControls } from "/vendor/three/addons/controls/OrbitControls.js";
import { TransformControls } from "/vendor/three/addons/controls/TransformControls.js";

const byId = (id) => document.getElementById(id);
const state = {
  active: false,
  draft: null,
  initialDraft: null,
  preview: null,
  selectedId: "",
  selectedRecord: null,
  objectById: new Map(),
  pickables: [],
  history: [],
  future: [],
  requestToken: 0,
  revisionCounter: 0,
  pendingPreviewJob: null,
  previewWorker: null,
  previewReadyRevision: 0,
  generationToken: 0,
  generating: false,
  startToken: 0,
  starting: false,
  dirty: false,
  savedStateSignature: "",
  generatedProjectName: "",
  generatedProjectChecksOk: false,
  validatingLspp: false,
  validationImageUrl: "",
  cameraInitialized: false,
  cityComponentCatalog: [],
  componentMutating: false,
};

const canvas = byId("phase17Canvas");
const renderer = new THREE.WebGLRenderer({
  canvas,
  antialias: true,
  alpha: false,
});
renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
renderer.setClearColor(0x20282e, 1);

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(45, 1, 0.01, 10000);
camera.position.set(55, -65, 45);
camera.up.set(0, 0, 1);
const orbit = new OrbitControls(camera, canvas);
orbit.enableDamping = true;
orbit.dampingFactor = 0.08;
orbit.target.set(0, 0, 4);
scene.add(new THREE.HemisphereLight(0xe8f2f5, 0x27343b, 2.1));
const keyLight = new THREE.DirectionalLight(0xffffff, 1.4);
keyLight.position.set(30, -20, 50);
scene.add(keyLight);
const grid = new THREE.GridHelper(100, 40, 0x3d8b78, 0x44545c);
grid.rotation.x = Math.PI / 2;
scene.add(grid);

const transform = new TransformControls(camera, canvas);
const transformHelper = transform.getHelper();
scene.add(transformHelper);
transform.setSpace("world");
transform.setSize(0.85);
transform.addEventListener("dragging-changed", (event) => {
  orbit.enabled = !event.value;
});
transform.addEventListener("mouseDown", () => {
  rememberDraft();
});
transform.addEventListener("objectChange", () => {
  updateInputsFromSelection();
});
transform.addEventListener("mouseUp", async () => {
  applySelectionToDraft();
  syncDirty();
  await refreshPreview();
});

const raycaster = new THREE.Raycaster();
const pointer = new THREE.Vector2();
canvas.addEventListener("pointerdown", (event) => {
  if (transform.dragging) return;
  const rect = canvas.getBoundingClientRect();
  pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
  pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
  raycaster.setFromCamera(pointer, camera);
  const hit = raycaster.intersectObjects(state.pickables, true)[0];
  if (hit) selectObject(hit.object.userData.selectionId);
});

function status(message, kind = "info") {
  const box = byId("phase17EditorStatus");
  box.textContent = message;
  box.dataset.state = kind;
}

function setEditorPanel(panel) {
  const showLibrary = panel === "library";
  byId("phase17ObjectsPanel").classList.toggle("hidden", showLibrary);
  byId("phase17LibraryPanel").classList.toggle("hidden", !showLibrary);
  byId("phase17ObjectsTab").classList.toggle("active", !showLibrary);
  byId("phase17LibraryTab").classList.toggle("active", showLibrary);
  byId("phase17ObjectsTab").setAttribute(
    "aria-selected",
    String(!showLibrary),
  );
  byId("phase17LibraryTab").setAttribute(
    "aria-selected",
    String(showLibrary),
  );
}

async function request(path, options = {}) {
  const response = await fetch(path, {
    headers: options.body ? { "Content-Type": "application/json" } : undefined,
    ...options,
  });
  const payload = await response.json();
  if (!response.ok || !payload.ok) {
    throw new Error(payload.error?.message || `请求失败：${response.status}`);
  }
  return payload.result;
}

async function loadCityComponentCatalog() {
  const result = await request("/api/components");
  state.cityComponentCatalog = (result.components || []).filter(
    (item) => item.city_editor?.placeable,
  );
  renderCityComponentCatalog();
}

function renderCityComponentCatalog() {
  const list = byId("phase17LibraryList");
  list.innerHTML = "";
  for (const definition of state.cityComponentCatalog) {
    const card = document.createElement("div");
    card.className = "phase17-library-item";
    const copy = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent =
      {
        parked_vehicle: "停车场车辆",
        subway_entrance: "地铁入口",
        shell_box: "钢制防护箱",
      }[definition.name] || definition.name.replaceAll("_", " ");
    const note = document.createElement("small");
    note.textContent =
      {
        parked_vehicle: "求解中保持自由，可受冲击波推动。",
        subway_entrance: "固定于地基并参与 ALE/FSI，可创建多个独立入口。",
        shell_box: "现有模型库壳体组件；固定于地基并参与 ALE/FSI。",
      }[definition.name] || "受控城市组件。";
    copy.append(title, note);
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.cityAdd = definition.name;
    const canAdd = (definition.city_editor?.instance_operations || []).includes(
      "add",
    );
    button.textContent =
      canAdd ? "添加" : "已包含";
    button.disabled =
      !canAdd ||
      !state.draft ||
      state.starting ||
      state.componentMutating ||
      Number(state.previewReadyRevision) !== Number(state.draft?.revision);
    button.addEventListener("click", () => {
      addCityComponent(definition.name).catch((error) => {
        status(error.message, "error");
      });
    });
    card.append(copy, button);
    list.appendChild(card);
  }
  if (!state.cityComponentCatalog.length) {
    list.textContent = "当前没有通过城市场景兼容登记的可添加组件。";
  }
}

async function addCityComponent(template) {
  await mutateCityComponent({ action: "add", template });
}

async function mutateCityComponent(operation) {
  if (!state.draft || !state.preview?.resolved_spec) {
    throw new Error("请先加载并完成城市场景草案检查。");
  }
  if (
    Number(state.previewReadyRevision) !== Number(state.draft.revision) ||
    state.pendingPreviewJob
  ) {
    throw new Error("请等待当前草案检查完成后再修改组件。");
  }
  if (state.componentMutating) return;

  const previousDraft = clone(state.draft);
  const revision = ++state.revisionCounter;
  const payload = {
    ...clone(state.draft),
    revision,
    spec: clone(state.preview.resolved_spec),
    transforms: {},
    operation: clone(operation),
  };
  state.componentMutating = true;
  state.requestToken += 1;
  state.previewReadyRevision = 0;
  invalidateGeneratedProject();
  status("正在重建组件及其接触、支承和结果映射...");
  updateActionAvailability();
  try {
    const result = await request("/api/editor/city-component", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    state.history.push(previousDraft);
    if (state.history.length > 100) state.history.shift();
    state.future = [];
    state.draft = result.draft;
    state.preview = result.preview;
    state.previewReadyRevision = revision;
    state.selectedId = result.selected_component_id || "";
    buildScene(result.preview);
    syncDirty();
    status(
      operation.action === "delete"
        ? `草案 r${revision} 已编译；组件已删除，相关接触和结果映射已重建。`
        : `草案 r${revision} 已编译；组件已加入，支承、碰撞和物理映射检查通过。`,
      "ok",
    );
    setEditorPanel("objects");
  } finally {
    state.componentMutating = false;
    updateActionAvailability();
  }
}

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function rememberDraft() {
  if (!state.draft) return;
  state.history.push(clone(state.draft));
  if (state.history.length > 100) state.history.shift();
  state.future = [];
  updateActionAvailability();
}

function invalidateGeneratedProject() {
  state.generationToken += 1;
  state.generatedProjectName = "";
  state.generatedProjectChecksOk = false;
  state.validationImageUrl = "";
  byId("phase17LsppEvidence").classList.add("hidden");
  byId("phase17ValidationImage").classList.add("hidden");
  updateActionAvailability();
}

function stateSignature() {
  if (!state.draft) return "";
  return JSON.stringify({
    project_name: byId("phase17ProjectName").value.trim(),
    spec: state.draft.spec,
    blast_source: state.draft.blast_source,
    transforms: state.draft.transforms,
    component_operations: state.draft.component_operations,
  });
}

function syncDirty() {
  state.dirty =
    Boolean(state.savedStateSignature) &&
    stateSignature() !== state.savedStateSignature;
  updateActionAvailability();
}

function markSaved() {
  state.savedStateSignature = stateSignature();
  state.dirty = false;
  updateActionAvailability();
}

function updateActionAvailability() {
  const hasDraft = Boolean(state.draft);
  const previewIsCurrent =
    hasDraft &&
    Number(state.previewReadyRevision) === Number(state.draft.revision) &&
    !state.pendingPreviewJob;
  const editable = Boolean(state.selectedRecord?.editable);
  const selectedTemplate = state.selectedRecord?.template || "";
  const instanceOperations = state.selectedRecord?.instance_operations || [];
  const selectedInstance = instanceOperations.length > 0;
  const instanceCount = Array.from(state.objectById.values()).filter(
    (object) => object.userData.record?.template === selectedTemplate,
  ).length;
  byId("startPhase17City").disabled = state.starting;
  byId("phase17ApplyTransform").disabled = !editable || state.starting;
  byId("phase17Undo").disabled =
    !hasDraft || state.history.length === 0 || state.starting;
  byId("phase17Redo").disabled =
    !hasDraft || state.future.length === 0 || state.starting;
  byId("phase17Reset").disabled = !hasDraft || state.starting;
  byId("phase17Generate").disabled =
    !previewIsCurrent ||
    state.generating ||
    !byId("phase17ProjectName").value.trim();
  byId("phase17ValidateLspp").disabled =
    !state.generatedProjectName ||
    !state.generatedProjectChecksOk ||
    state.validatingLspp;
  byId("phase17DuplicateComponent").disabled =
    !previewIsCurrent ||
    !selectedInstance ||
    !instanceOperations.includes("duplicate") ||
    state.componentMutating ||
    state.starting;
  const minimumInstances = ["parked_vehicle", "subway_entrance"].includes(
    selectedTemplate,
  )
    ? 1
    : 0;
  byId("phase17DeleteComponent").disabled =
    !previewIsCurrent ||
    !selectedInstance ||
    !instanceOperations.includes("delete") ||
    instanceCount <= minimumInstances ||
    state.componentMutating ||
    state.starting;
  renderCityComponentCatalog();
}

function clearSceneObjects() {
  transform.detach();
  for (const object of [...state.objectById.values()]) {
    scene.remove(object);
    object.traverse((child) => {
      child.geometry?.dispose();
      if (Array.isArray(child.material)) {
        child.material.forEach((material) => material.dispose());
      } else {
        child.material?.dispose();
      }
    });
  }
  state.objectById.clear();
  state.pickables = [];
}

function partGeometry(part, pivot) {
  const positions = [];
  for (const point of part.nodes || []) {
    positions.push(
      Number(point[0]) - pivot[0],
      Number(point[1]) - pivot[1],
      Number(point[2]) - pivot[2],
    );
  }
  const indices = [];
  for (const face of part.faces || []) {
    for (let index = 1; index + 1 < face.length; index += 1) {
      indices.push(face[0], face[index], face[index + 1]);
    }
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute(
    "position",
    new THREE.Float32BufferAttribute(positions, 3),
  );
  geometry.setIndex(indices);
  geometry.computeVertexNormals();
  return geometry;
}

function materialForPart(part, editable) {
  return new THREE.MeshStandardMaterial({
    color: new THREE.Color(part.color || (editable ? "#4ea68d" : "#70838c")),
    metalness: 0.05,
    roughness: 0.78,
    side: THREE.DoubleSide,
    transparent: !editable,
    opacity: editable ? 0.94 : 0.72,
  });
}

function buildScene(preview) {
  clearSceneObjects();
  const components = new Map(
    (preview.components || []).map((item) => [item.component_id, item]),
  );
  const partToComponent = new Map();
  for (const component of components.values()) {
    for (const partId of component.part_ids || []) {
      partToComponent.set(String(partId), component);
    }
  }
  for (const part of preview.parts || []) {
    if ((preview.default_hidden_part_ids || []).includes(part.part_id)) continue;
    const component = partToComponent.get(String(part.part_id));
    const id = component?.component_id || `fixed_part_${part.part_id}`;
    let group = state.objectById.get(id);
    if (!group) {
      group = new THREE.Group();
      group.userData = {
        selectionId: id,
        record: component || {
          component_id: id,
          editable: false,
          mobility_profile: "fixed",
          allowed_dofs: [],
          pivot_world_m: [0, 0, 0],
        },
      };
      const pivot = component?.pivot_world_m || [0, 0, 0];
      group.position.fromArray(pivot);
      group.userData.previewPosition = group.position.clone();
      group.userData.previewRotationZ = 0;
      scene.add(group);
      state.objectById.set(id, group);
    }
    const pivot = group.userData.record.pivot_world_m || [0, 0, 0];
    const mesh = new THREE.Mesh(
      partGeometry(part, pivot),
      materialForPart(part, Boolean(component?.editable)),
    );
    mesh.userData.selectionId = id;
    group.add(mesh);
    state.pickables.push(mesh);
  }

  for (const source of preview.editable_sources || []) {
    const geometry = new THREE.CylinderGeometry(
      Number(source.radius_m || 0.2),
      Number(source.radius_m || 0.2),
      Number(source.length_m || 0.5),
      32,
    );
    geometry.rotateX(Math.PI / 2);
    const mesh = new THREE.Mesh(
      geometry,
      new THREE.MeshStandardMaterial({
        color: 0xf0b429,
        emissive: 0x5a3500,
        emissiveIntensity: 0.45,
        roughness: 0.52,
      }),
    );
    mesh.position.fromArray(source.position_m);
    mesh.userData = {
      selectionId: source.source_id,
      record: source,
      basePosition: mesh.position.clone(),
      previewPosition: mesh.position.clone(),
      previewRotationZ: 0,
    };
    scene.add(mesh);
    state.objectById.set(source.source_id, mesh);
    state.pickables.push(mesh);
  }
  populateObjectSelect();
  if (!state.cameraInitialized) {
    fitCamera(preview.bounds, "fit");
  }
  selectObject(
    state.objectById.has(state.selectedId)
      ? state.selectedId
      : (preview.editable_sources?.[0]?.source_id || ""),
  );
}

const CAMERA_VIEWS = Object.freeze({
  fit: {
    direction: [1, -1.18, 0.62],
    up: [0, 0, 1],
  },
  iso: {
    direction: [1, -1, 1],
    up: [0, 0, 1],
  },
  top: {
    direction: [0, 0, 1],
    up: [0, 1, 0],
  },
  front: {
    direction: [0, -1, 0],
    up: [0, 0, 1],
  },
});

function fitCamera(bounds, view = "fit") {
  if (!bounds?.min || !bounds?.max) return;
  const min = new THREE.Vector3().fromArray(bounds.min);
  const max = new THREE.Vector3().fromArray(bounds.max);
  const center = min.clone().add(max).multiplyScalar(0.5);
  const size = max.clone().sub(min);
  const radius = Math.max(size.length() * 0.5, 0.5);
  const verticalFov = THREE.MathUtils.degToRad(camera.fov);
  const horizontalFov =
    2 * Math.atan(Math.tan(verticalFov * 0.5) * Math.max(camera.aspect, 0.1));
  const limitingFov = Math.min(verticalFov, horizontalFov);
  const distance = (radius / Math.sin(limitingFov * 0.5)) * 1.08;
  const preset = CAMERA_VIEWS[view] || CAMERA_VIEWS.fit;
  const direction = new THREE.Vector3(...preset.direction).normalize();
  orbit.target.copy(center);
  camera.position.copy(center).add(direction.multiplyScalar(distance));
  camera.up.fromArray(preset.up);
  camera.near = Math.max(radius / 1000, 0.01);
  camera.far = Math.max(distance + radius * 10, 100);
  camera.updateProjectionMatrix();
  camera.lookAt(center);
  orbit.update();
  state.cameraInitialized = true;
}

function cameraPose() {
  return {
    position: camera.position.toArray(),
    target: orbit.target.toArray(),
    up: camera.up.toArray(),
    zoom: camera.zoom,
  };
}

function populateObjectSelect() {
  const select = byId("phase17ObjectSelect");
  select.innerHTML = "";
  const objectLabels = {
    city_tnt: "城市 TNT 爆源",
    commercial_supermarket: "商业超市",
    residential_community: "住宅小区",
    subway_entrance: "地铁入口",
    parked_vehicle_1: "停车场车辆 1",
    parked_vehicle_2: "停车场车辆 2",
    parked_vehicle_3: "停车场车辆 3",
    parked_vehicle_4: "停车场车辆 4",
  };
  for (const [id, object] of state.objectById) {
    const record = object.userData.record;
    if (!record.editable) continue;
    const option = document.createElement("option");
    option.value = id;
    option.textContent =
      objectLabels[id] ||
      (id.startsWith("parked_vehicle_")
        ? `停车场车辆 ${id.slice("parked_vehicle_".length)}`
        : id.startsWith("subway_entrance_")
          ? `地铁入口 ${id.slice("subway_entrance_".length)}`
          : id.startsWith("shell_box_")
            ? `钢制防护箱 ${id.slice("shell_box_".length)}`
          : id.replaceAll("_", " "));
    select.appendChild(option);
  }
}

function selectObject(id) {
  state.selectedId = id;
  const object = state.objectById.get(id);
  state.selectedRecord = object?.userData.record || null;
  renderComponentSummary();
  byId("phase17ObjectSelect").value = id;
  transform.detach();
  if (!object || !state.selectedRecord?.editable) {
    updateEditorAvailability();
    return;
  }
  transform.attach(object);
  updateEditorAvailability();
  updateInputsFromSelection();
}

function renderComponentSummary() {
  const box = byId("phase17ComponentSummary");
  box.innerHTML = "";
  const record = state.selectedRecord;
  if (!record || record.source_id) return;
  const labels = [
    record.constraint_mode === "free" ? "求解中自由运动" : "求解中固定",
    record.support_object_id
      ? `支承：${supportLabel(record.support_object_id)}`
      : "未声明支承",
    record.supports_ale_fsi ? "参与 ALE/FSI" : "不参与 ALE/FSI",
  ];
  const row = document.createElement("div");
  row.className = "phase17-component-summary-row";
  for (const label of labels) {
    const chip = document.createElement("span");
    chip.textContent = label;
    row.appendChild(chip);
  }
  box.appendChild(row);
}

function supportLabel(value) {
  return {
    ground_foundation: "城市地基",
    parking_lot: "停车场",
  }[value] || value;
}

function syncGroundCraterControls() {
  const ground = state.draft?.spec?.ground_response;
  const enabled = ground?.mode === "validation_crater";
  byId("phase17GroundCraterEnabled").checked = enabled;
  byId("phase17GroundCraterDepth").disabled = !enabled;
  byId("phase17GroundOverlapLayers").disabled = !enabled;
  if (enabled) {
    byId("phase17GroundCraterDepth").value = Number(
      ground.anticipated_crater_depth_m || 0.6,
    ).toFixed(2);
    byId("phase17GroundOverlapLayers").value = String(
      ground.ale_overlap_layers || 5,
    );
  }
  const summary = byId("phase17GroundCraterStatus");
  summary.textContent = enabled
    ? "将生成 ALE 重叠、K&C 实体地面和单元侵蚀；求解后必须通过实际破坑证据门禁。"
    : "当前使用表面地面，不计算破坑。";
  summary.dataset.state = enabled ? "attention" : "info";
}

async function applyGroundCraterControls() {
  if (!state.draft?.spec) return;
  const enabled = byId("phase17GroundCraterEnabled").checked;
  const depth = Number(byId("phase17GroundCraterDepth").value);
  const overlapLayers = Number(byId("phase17GroundOverlapLayers").value);
  if (enabled && (!Number.isFinite(depth) || depth <= 0 || depth > 2)) {
    throw new Error("预期坑深必须大于 0 且不超过 2 m。");
  }
  if (enabled && ![5, 7].includes(overlapLayers)) {
    throw new Error("ALE 重叠层数只能是 5 或 7。");
  }
  rememberDraft();
  if (enabled) {
    state.draft.spec.ground_response = {
      mode: "validation_crater",
      anticipated_crater_depth_m: depth,
      ale_overlap_layers: overlapLayers,
      erosion_mode: "standard_observation",
      material_preset: "kc_a1_automatic_reference",
      capability_version: "city_ground_crater_v1",
    };
  } else {
    delete state.draft.spec.ground_response;
  }
  syncGroundCraterControls();
  syncDirty();
  await refreshPreview();
}

function updateEditorAvailability() {
  const record = state.selectedRecord;
  const allowed = new Set(record?.allowed_dofs || []);
  const source = record?.mobility_profile === "blast_source";
  const surfaceConstrained = ["grounded", "surface_dynamic"].includes(
    record?.mobility_profile,
  );
  byId("phase17X").disabled = !allowed.has("tx");
  byId("phase17Y").disabled = !allowed.has("ty");
  byId("phase17Z").disabled = !allowed.has("tz");
  byId("phase17Rz").disabled = !allowed.has("rz");
  byId("phase17RotateMode").disabled = source || !allowed.has("rz");
  if (source && transform.mode === "rotate") setTransformMode("translate");
  transform.showX = transform.mode === "translate" ? allowed.has("tx") : false;
  transform.showY = transform.mode === "translate" ? allowed.has("ty") : false;
  transform.showZ =
    transform.mode === "translate" ? allowed.has("tz") : surfaceConstrained;
  updateActionAvailability();
}

function updateInputsFromSelection() {
  const object = state.objectById.get(state.selectedId);
  if (!object) return;
  byId("phase17X").value = object.position.x.toFixed(6);
  byId("phase17Y").value = object.position.y.toFixed(6);
  byId("phase17Z").value = object.position.z.toFixed(6);
  const existing = state.draft?.transforms?.[state.selectedId];
  const existingRz = Number(existing?.rotate_deg?.[2] || 0);
  const previewRotation = Number(object.userData.previewRotationZ || 0);
  const pendingRotation = THREE.MathUtils.radToDeg(
    object.rotation.z - previewRotation,
  );
  byId("phase17Rz").value = (existingRz + pendingRotation).toFixed(3);
}

function applySelectionToDraft() {
  const object = state.objectById.get(state.selectedId);
  const record = state.selectedRecord;
  if (!object || !record || !state.draft) return;
  if (record.mobility_profile === "blast_source") {
    state.draft.blast_source.position_m = object.position.toArray();
    return;
  }
  const previewPosition = object.userData.previewPosition;
  const previewRotation = Number(object.userData.previewRotationZ || 0);
  const existing = state.draft.transforms[record.component_id] || {
    translate_m: [0, 0, 0],
    rotate_deg: [0, 0, 0],
  };
  state.draft.transforms[record.component_id] = {
    translate_m: [
      Number(existing.translate_m?.[0] || 0) +
        object.position.x -
        previewPosition.x,
      Number(existing.translate_m?.[1] || 0) +
        object.position.y -
        previewPosition.y,
      0,
    ],
    rotate_deg: [
      0,
      0,
      Number(existing.rotate_deg?.[2] || 0) +
        THREE.MathUtils.radToDeg(object.rotation.z - previewRotation),
    ],
  };
}

function setTransformMode(mode) {
  transform.setMode(mode);
  byId("phase17TranslateMode").classList.toggle("active", mode === "translate");
  byId("phase17RotateMode").classList.toggle("active", mode === "rotate");
  updateEditorAvailability();
}

async function refreshPreview() {
  if (!state.draft) return;
  invalidateGeneratedProject();
  const token = ++state.requestToken;
  const revision = ++state.revisionCounter;
  state.draft.revision = revision;
  state.previewReadyRevision = 0;
  state.pendingPreviewJob = {
    token,
    revision,
    body: JSON.stringify(state.draft),
  };
  status("正在重新划分 ALE 网格并检查模型...");
  updateActionAvailability();
  if (!state.previewWorker) {
    state.previewWorker = runPreviewQueue().finally(() => {
      state.previewWorker = null;
      updateActionAvailability();
    });
  }
  return state.previewWorker;
}

async function runPreviewQueue() {
  while (state.pendingPreviewJob) {
    const job = state.pendingPreviewJob;
    state.pendingPreviewJob = null;
    try {
      const preview = await request("/api/editor/preview", {
        method: "POST",
        body: job.body,
      });
      if (
        job.token !== state.requestToken ||
        preview.revision !== job.revision
      ) {
        continue;
      }
      state.preview = preview;
      state.previewReadyRevision = job.revision;
      buildScene(preview);
      status(
        `草案 r${preview.revision} 已编译；ALE 网格 ${String(preview.ale_mesh?.mesh_fingerprint || "").slice(0, 12)}。`,
        "ok",
      );
    } catch (error) {
      if (job.token !== state.requestToken) continue;
      state.previewReadyRevision = 0;
      status(error.message, "error");
    } finally {
      updateActionAvailability();
    }
  }
}

async function startCityEditor() {
  if (state.starting) return;
  if (
    state.dirty &&
    !window.confirm("当前城市场景有未保存修改，确认重新加载模板吗？")
  ) {
    return;
  }
  const token = ++state.startToken;
  state.starting = true;
  updateActionAvailability();
  const projectName =
    byId("phase17ProjectName").value.trim() ||
    "web_phase17_city_street_blast";
  status("正在加载受控城市场景...");
  try {
    const template = await request(
      `/api/editor/city-template?project_name=${encodeURIComponent(projectName)}`,
    );
    if (token !== state.startToken) return;
    state.active = true;
    state.draft = template;
    state.initialDraft = clone(template);
    state.history = [];
    state.future = [];
    state.previewReadyRevision = 0;
    state.cameraInitialized = false;
    state.revisionCounter = Math.max(
      state.revisionCounter,
      Number(template.revision || 0),
    );
    markSaved();
    syncGroundCraterControls();
    canvas.classList.remove("hidden");
    byId("modelCanvas").classList.add("hidden");
    byId("viewerHint").classList.add("hidden");
    byId("phase17EditorTab").classList.remove("hidden");
    byId("phase17EditorTab").click();
    setEditorPanel("objects");
    await refreshPreview();
  } finally {
    if (token === state.startToken) {
      state.starting = false;
      updateActionAvailability();
    }
  }
}

async function undo() {
  if (!state.history.length || !state.draft) return;
  state.future.push(clone(state.draft));
  state.draft = state.history.pop();
  syncGroundCraterControls();
  syncDirty();
  await refreshPreview();
}

async function redo() {
  if (!state.future.length || !state.draft) return;
  state.history.push(clone(state.draft));
  state.draft = state.future.pop();
  syncGroundCraterControls();
  syncDirty();
  await refreshPreview();
}

async function resetDraft() {
  if (!state.initialDraft || !state.draft) return;
  rememberDraft();
  state.draft = clone(state.initialDraft);
  syncGroundCraterControls();
  syncDirty();
  await refreshPreview();
}

function finiteInputValue(id) {
  const raw = byId(id).value.trim();
  if (!raw) {
    throw new Error("变换值不能为空。");
  }
  const value = Number(raw);
  if (!Number.isFinite(value)) {
    throw new Error("变换值必须是有限数字。");
  }
  return value;
}

async function applyNumericTransform() {
  const object = state.objectById.get(state.selectedId);
  if (!object) return;
  const values = {
    x: finiteInputValue("phase17X"),
    y: finiteInputValue("phase17Y"),
    z: finiteInputValue("phase17Z"),
    rz: finiteInputValue("phase17Rz"),
  };
  rememberDraft();
  if (!byId("phase17X").disabled) object.position.x = values.x;
  if (!byId("phase17Y").disabled) object.position.y = values.y;
  if (!byId("phase17Z").disabled) object.position.z = values.z;
  if (!byId("phase17Rz").disabled) {
    const existingRz = Number(
      state.draft.transforms?.[state.selectedId]?.rotate_deg?.[2] || 0,
    );
    object.rotation.z =
      Number(object.userData.previewRotationZ || 0) +
      THREE.MathUtils.degToRad(values.rz - existingRz);
  }
  applySelectionToDraft();
  syncDirty();
  await refreshPreview();
}

async function generateProject() {
  if (!state.draft) return;
  if (state.generating) return;
  const projectName = byId("phase17ProjectName").value.trim();
  if (!projectName) {
    status("新项目名称不能为空。", "error");
    updateActionAvailability();
    return;
  }
  if (Number(state.previewReadyRevision) !== Number(state.draft.revision)) {
    status("请等待当前草案检查完成后再生成项目。", "error");
    updateActionAvailability();
    return;
  }
  state.generatedProjectName = "";
  state.generatedProjectChecksOk = false;
  const token = ++state.generationToken;
  const revision = Number(state.draft.revision);
  state.generating = true;
  updateActionAvailability();
  const payload = clone(state.draft);
  payload.project_name = projectName;
  payload.spec.project_name = projectName;
  status("正在生成新项目并执行静态检查...");
  try {
    const result = await request("/api/editor/generate", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    if (
      token !== state.generationToken ||
      revision !== Number(state.draft.revision) ||
      projectName !== byId("phase17ProjectName").value.trim()
    ) {
      if (!state.previewWorker && !state.pendingPreviewJob) {
        status("草案或项目名称已更改，旧生成结果已忽略。");
      }
      return;
    }
    byId("projectName").value = result.project;
    state.generatedProjectName = result.project;
    state.generatedProjectChecksOk = Boolean(result.checks?.ok);
    markSaved();
    status(
      result.checks?.ok
        ? `项目 ${result.project} 已生成，静态门禁通过。`
        : `项目 ${result.project} 已生成，但静态门禁未通过。`,
      result.checks?.ok ? "ok" : "error",
    );
  } catch (error) {
    if (token === state.generationToken) {
      status(error.message, "error");
    }
  } finally {
    state.generating = false;
    updateActionAvailability();
  }
}

async function validateGeneratedProject() {
  if (!state.generatedProjectName) return;
  if (!(await preflightLsppConfiguration())) return;
  state.validatingLspp = true;
  updateActionAvailability();
  status("正在执行受控 LS-PrePost 导入检查...");
  try {
    const result = await request("/api/editor/validate-lsprepost", {
      method: "POST",
      body: JSON.stringify({
        project_name: state.generatedProjectName,
        output_filename: "phase17_import_validation_iso.png",
        view: "iso",
        display_mode: "validation",
        timeout_s: 90,
        if_exists: "overwrite",
      }),
    });
    renderLsppEvidence(result);
    status(
      result.ok
        ? `项目 ${state.generatedProjectName} 已通过 LS-PrePost 导入检查。`
        : `项目 ${state.generatedProjectName} 未通过 LS-PrePost 导入检查。`,
      result.ok ? "ok" : "error",
    );
  } catch (error) {
    status(error.message, "error");
  } finally {
    state.validatingLspp = false;
    updateActionAvailability();
  }
}

const LSPP_NOT_CONFIGURED = "lsprepost_not_configured";

async function preflightLsppConfiguration() {
  const config = await request("/api/config");
  if (config.doctor?.ok) return true;
  status(
    `未配置有效的 LS-PrePost（${LSPP_NOT_CONFIGURED}）。请先在左上工作区导入 lsprepost*.exe。`,
    "error",
  );
  focusLsppConfiguration();
  return false;
}

function focusLsppConfiguration() {
  document
    .querySelector('[data-resource-panel="lsppResourcePanel"]')
    ?.click();
  byId("importLspp")?.focus();
}

function renderLsppEvidence(result) {
  const validation = result.validation || {};
  const reader = result.preview_result?.keyword_reader || {};
  const fingerprint = result.model_fingerprint || {};
  const evidence = byId("phase17LsppEvidence");
  evidence.textContent = [
    `静态门禁：${validation.static_checks_ok ? "通过" : "失败"}`,
    `Keyword Reader：${reader.errors ?? "?"} 错误 / ${reader.warnings ?? "?"} 警告`,
    `PNG：${validation.preview_png_ok ? "有效" : "无效"}`,
    `model.k：${String(fingerprint.model_k_sha256 || "").slice(0, 12) || "无哈希"}`,
  ].join("；");
  evidence.classList.remove("hidden");
  if (result.output_relative_path) {
    state.validationImageUrl =
      `/api/artifact?project_name=${encodeURIComponent(result.project_name)}` +
      `&relative_path=${encodeURIComponent(result.output_relative_path)}`;
    byId("phase17ValidationImage").classList.remove("hidden");
  }
}

function resize() {
  const rect = canvas.getBoundingClientRect();
  if (!rect.width || !rect.height) return;
  renderer.setSize(rect.width, rect.height, false);
  camera.aspect = rect.width / rect.height;
  camera.updateProjectionMatrix();
}

function animate() {
  if (state.active && !canvas.classList.contains("hidden")) {
    resize();
    orbit.update();
    renderer.render(scene, camera);
  }
  requestAnimationFrame(animate);
}

byId("startPhase17City").addEventListener("click", () => {
  startCityEditor().catch((error) => status(error.message, "error"));
});
byId("phase17ObjectsTab").addEventListener("click", () => {
  setEditorPanel("objects");
});
byId("phase17LibraryTab").addEventListener("click", () => {
  setEditorPanel("library");
});
byId("phase17ObjectSelect").addEventListener("change", (event) => {
  selectObject(event.target.value);
});
byId("phase17TranslateMode").addEventListener("click", () => {
  setTransformMode("translate");
});
byId("phase17RotateMode").addEventListener("click", () => {
  setTransformMode("rotate");
});
byId("phase17ApplyTransform").addEventListener("click", () => {
  applyNumericTransform().catch((error) => status(error.message, "error"));
});
byId("phase17DuplicateComponent").addEventListener("click", () => {
  mutateCityComponent({
    action: "duplicate",
    component_id: state.selectedId,
  }).catch((error) => status(error.message, "error"));
});
byId("phase17DeleteComponent").addEventListener("click", () => {
  mutateCityComponent({
    action: "delete",
    component_id: state.selectedId,
  }).catch((error) => status(error.message, "error"));
});
byId("phase17Undo").addEventListener("click", () => {
  undo().catch((error) => status(error.message, "error"));
});
byId("phase17Redo").addEventListener("click", () => {
  redo().catch((error) => status(error.message, "error"));
});
byId("phase17Reset").addEventListener("click", () => {
  resetDraft().catch((error) => status(error.message, "error"));
});
byId("phase17Generate").addEventListener("click", () => {
  generateProject().catch((error) => status(error.message, "error"));
});
byId("phase17ValidateLspp").addEventListener("click", () => {
  validateGeneratedProject().catch((error) => status(error.message, "error"));
});
byId("phase17ValidationImage").addEventListener("click", () => {
  if (state.validationImageUrl) {
    window.open(state.validationImageUrl, "_blank", "noopener");
  }
});
for (const id of [
  "phase17GroundCraterEnabled",
  "phase17GroundCraterDepth",
  "phase17GroundOverlapLayers",
]) {
  byId(id).addEventListener("change", () => {
    applyGroundCraterControls().catch((error) => status(error.message, "error"));
  });
}
byId("phase17ProjectName").addEventListener("input", () => {
  invalidateGeneratedProject();
  syncDirty();
});
window.addEventListener("beforeunload", (event) => {
  if (!state.dirty || window.WorkbenchNavigation?.canLeaveWithoutLoss()) return;
  event.preventDefault();
  event.returnValue = "";
});
window.addEventListener("phase17:view", (event) => {
  if (!state.active || canvas.classList.contains("hidden") || !state.preview) return;
  fitCamera(state.preview.bounds, event.detail?.view || "fit");
});
window.addEventListener("phase17:get-camera-pose", (event) => {
  if (!event.detail || !state.active) return;
  event.detail.pose = cameraPose();
});

window.addEventListener('phase17:get-navigation-state',event=>{
  if(!event.detail||!state.draft)return;
  event.detail.snapshot=clone({draft:state.draft,initialDraft:state.initialDraft,preview:state.preview,selectedId:state.selectedId,history:state.history,future:state.future,dirty:state.dirty,savedStateSignature:state.savedStateSignature,generatedProjectName:state.generatedProjectName,active:state.active});
});
window.addEventListener('phase17:restore-navigation-state',event=>{
  const s=event.detail?.snapshot;if(!s?.draft||typeof s.draft!=='object')return;
  state.draft=clone(s.draft);state.initialDraft=clone(s.initialDraft||s.draft);state.preview=s.preview?clone(s.preview):null;
  state.history=clone(s.history||[]);state.future=clone(s.future||[]);state.savedStateSignature=s.savedStateSignature||'';
  state.generatedProjectName=s.generatedProjectName||'';state.generatedProjectChecksOk=false;
  state.active=!!s.active;state.revisionCounter=Number(state.draft.revision)||0;state.previewReadyRevision=0;
  syncGroundCraterControls();
  if(state.preview){buildScene(state.preview);if(s.selectedId)selectObject(s.selectedId);}
  if(state.active){canvas.classList.remove('hidden');byId('modelCanvas').classList.add('hidden');byId('viewerHint').classList.add('hidden');byId('phase17EditorTab').classList.remove('hidden');}
  syncDirty();updateActionAvailability();status('城市场景草稿已恢复；重新生成前请手动更新预览。');
});
window.dispatchEvent(new Event('phase17:navigation-ready'));

loadCityComponentCatalog().catch((error) => status(error.message, "error"));
updateActionAvailability();
animate();
