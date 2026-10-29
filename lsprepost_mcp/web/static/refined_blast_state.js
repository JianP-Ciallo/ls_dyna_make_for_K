const REFINED_BLAST_API_PREFIX = "/api/refined-building-blast";

function clone(value) { return structuredClone(value); }
function equal(left, right) { return JSON.stringify(left) === JSON.stringify(right); }
function asObject(value) { return value && typeof value === "object" && !Array.isArray(value) ? value : {}; }

function normalizedBuildingCompilationState(value) {
  return value === "compiled" ? "compiled" : "pending";
}

function providerEntry(schema, providerId) {
  const providers = schema?.providers ?? {};
  return Array.isArray(providers)
    ? providers.find((entry) => entry?.provider_id === providerId) ?? {}
    : asObject(providers)[providerId] ?? {};
}

function matchesSchemaShape(value, descriptor) {
  if (!descriptor) return false;
  if (Object.hasOwn(descriptor, "const") && value !== descriptor.const) return false;
  if ((descriptor.type === "object" || descriptor.properties) && (!value || typeof value !== "object" || Array.isArray(value))) return false;
  if ((descriptor.type === "object" || descriptor.properties) && Array.isArray(descriptor.required) && descriptor.required.some((key) => !Object.hasOwn(value, key))) return false;
  return true;
}

function normalizeSchemaValue(value, descriptor) {
  if (!descriptor || value === undefined || value === null) return undefined;
  if (Array.isArray(descriptor.oneOf)) {
    const branches = descriptor.oneOf.slice().sort((left, right) => (
      Object.keys(asObject(right.properties)).length + (right.required?.length ?? 0)
      - Object.keys(asObject(left.properties)).length - (left.required?.length ?? 0)
    ));
    for (const branch of branches) {
      if (!matchesSchemaShape(value, branch)) continue;
      const normalized = normalizeSchemaValue(value, branch);
      if (normalized !== undefined) return normalized;
    }
    return undefined;
  }
  if (Object.hasOwn(descriptor, "const") && value !== descriptor.const) return undefined;
  if (descriptor.type === "object" || descriptor.properties) {
    if (!value || typeof value !== "object" || Array.isArray(value)) return undefined;
    const result = {};
    for (const [key, property] of Object.entries(asObject(descriptor.properties))) {
      const normalized = normalizeSchemaValue(value[key], property);
      if (normalized !== undefined) result[key] = normalized;
    }
    if (descriptor.additionalProperties && typeof descriptor.additionalProperties === "object") {
      for (const [key, nested] of Object.entries(value)) {
        if (Object.hasOwn(asObject(descriptor.properties), key)) continue;
        const normalized = normalizeSchemaValue(nested, descriptor.additionalProperties);
        if (normalized !== undefined) result[key] = normalized;
      }
    }
    if (Array.isArray(descriptor.required) && descriptor.required.some((key) => !Object.hasOwn(result, key))) return undefined;
    return result;
  }
  if (descriptor.type === "array" || descriptor.items) {
    if (!Array.isArray(value)) return undefined;
    if (descriptor.minItems !== undefined && value.length < descriptor.minItems) return undefined;
    if (descriptor.maxItems !== undefined && value.length > descriptor.maxItems) return undefined;
    const items = value.map((item) => normalizeSchemaValue(item, descriptor.items)).filter((item) => item !== undefined);
    if (items.length !== value.length && (descriptor.minItems !== undefined || descriptor.maxItems !== undefined)) return undefined;
    return items;
  }
  if (descriptor.type === "number" || descriptor.type === "integer") {
    if (typeof value !== "number" || !Number.isFinite(value) || (descriptor.type === "integer" && !Number.isInteger(value))) return undefined;
    if (descriptor.minimum !== undefined && value < descriptor.minimum) return undefined;
    if (descriptor.maximum !== undefined && value > descriptor.maximum) return undefined;
  } else if (descriptor.type === "boolean") {
    if (typeof value !== "boolean") return undefined;
  } else if (descriptor.type === "string") {
    if (typeof value !== "string") return undefined;
    if (descriptor.minLength !== undefined && value.length < descriptor.minLength) return undefined;
  }
  if (Array.isArray(descriptor.enum) && !descriptor.enum.includes(value)) return undefined;
  return clone(value);
}

function schemaValuesEqual(left, right) {
  if (Object.is(left, right)) return true;
  if (Array.isArray(left) || Array.isArray(right)) {
    return Array.isArray(left) && Array.isArray(right) && left.length === right.length
      && left.every((value, index) => schemaValuesEqual(value, right[index]));
  }
  if (left && right && typeof left === "object" && typeof right === "object") {
    const leftKeys = Object.keys(left).sort();
    const rightKeys = Object.keys(right).sort();
    return leftKeys.length === rightKeys.length
      && leftKeys.every((key, index) => key === rightKeys[index] && schemaValuesEqual(left[key], right[key]));
  }
  return false;
}

export function schemaValueIsValid(value, descriptor) {
  const normalized = normalizeSchemaValue(value, descriptor);
  return normalized !== undefined && schemaValuesEqual(value, normalized);
}

function legacyProviderSchema(provider) {
  const fields = provider.provider_input_fields ?? provider.fields ?? provider.schema?.exact_root_keys ?? [];
  return { type: "object", additionalProperties: false, properties: Object.fromEntries(
    fields.map((field) => typeof field === "string" ? [field, {}] : [field.path, field])
  ) };
}

function providerInputSchema(schema, providerId) {
  const provider = providerEntry(schema, providerId);
  return provider.provider_input_schema ?? provider.input_schema ?? legacyProviderSchema(provider);
}

function assetEntry(schema, assetId) {
  return (schema?.assets ?? []).find((asset) => asset?.asset_id === assetId) ?? null;
}

function structuralEntry(schema, system) { return asObject(schema?.structural_systems)[system] ?? {}; }

function allowedSystems(schema, assetId) {
  return assetEntry(schema, assetId)?.allowed_structural_systems ?? Object.keys(asObject(schema?.structural_systems));
}

function normalizedStructuralSystem(schema, assetId, supplied) {
  const allowed = allowedSystems(schema, assetId);
  if (allowed.includes(supplied)) return supplied;
  const asset = assetEntry(schema, assetId);
  return asset?.default_structural_system && allowed.includes(asset.default_structural_system)
    ? asset.default_structural_system : allowed[0];
}

function normalizeBuildingPlacement(draft, schema, assetId) {
  const scenarioSchema = schema?.scenario_draft_schema;
  if (scenarioSchema?.properties?.building_placement) {
    return normalizeSchemaValue(asObject(draft.building_placement), scenarioSchema.properties.building_placement) ?? {};
  }
  const placement = asObject(draft.building_placement);
  const structuralSystem = normalizedStructuralSystem(schema, assetId, placement.structural_system);
  if (!structuralSystem) return clone(placement);
  const structural = structuralEntry(schema, structuralSystem);
  const fields = structural.draft_fields;
  if (!Array.isArray(fields)) return { ...clone(placement), structural_system: structuralSystem };
  const result = { structural_system: structuralSystem };
  for (const field of fields) {
    if (field !== "structural_system" && Object.hasOwn(placement, field)) result[field] = clone(placement[field]);
  }
  return result;
}

function allowedScenarioKinds(schema, providerId) {
  const provider = providerEntry(schema, providerId);
  return provider.supported_scenario_kinds ?? provider.capabilities?.scenario_kinds ?? [];
}

function visibleSections(schema, building, assetId) {
  const system = asObject(building).structural_system;
  const asset = assetEntry(schema, assetId);
  const declared = asset?.ui_sections_by_structural_system?.[system];
  if (Array.isArray(declared)) return ["building_space", "structural_system", ...declared, "load"];
  const structural = structuralEntry(schema, system);
  if (Array.isArray(structural.visible_sections)) return [...structural.visible_sections];
  const legacy = schema?.building?.sections_by_structural_system ?? {};
  return Array.isArray(legacy[system]) ? [...legacy[system]] : [];
}

function normalizeBuildingForAsset(building, schema, assetId) {
  const asset = assetEntry(schema, assetId);
  if (!asset?.building_recipe_schema) return clone(asObject(building));
  const current = asObject(building);
  const candidate = {
    legacy_geometry: { ...asObject(asset.default_geometry), ...asObject(current.legacy_geometry) },
    origin_m: [0, 0, 0],
    rotation_deg: [0, 0, 0],
    structural_system: asset.default_structural_system,
    fidelity_profile: asset.default_fidelity_profile,
    mesh_profile: asset.default_mesh_profile,
    generation_options: {},
    material_overrides: {},
    ...current,
    asset_id: asset.asset_id,
  };
  const system = normalizedStructuralSystem(schema, asset.asset_id, candidate.structural_system);
  if (system) candidate.structural_system = system;
  const projected = normalizeSchemaValue(candidate, asset.building_recipe_schema) ?? {};
  const generationSchema = asset.generation_options_schema_by_structural_system?.[projected.structural_system];
  if (generationSchema && Object.hasOwn(candidate, "generation_options")) {
    const generation = normalizeSchemaValue(candidate.generation_options, generationSchema);
    if (generation !== undefined) projected.generation_options = generation;
    else delete projected.generation_options;
  }
  return projected;
}

function schemaFieldRows(section, schema, draft) {
  const provider = providerEntry(schema, asObject(draft.load_provider).provider_id);
  const rows = [...(Array.isArray(schema?.fields) ? schema.fields : []), ...(Array.isArray(provider.fields) ? provider.fields : [])]
    .filter((field) => asObject(field).section === section);
  if (section !== "load" || rows.length) return rows;
  const input = asObject(draft.load_provider).provider_input;
  function branchFor(value, descriptor) {
    if (!Array.isArray(descriptor?.oneOf)) return descriptor;
    return descriptor.oneOf.find((branch) => matchesSchemaShape(value, branch)) ?? descriptor.oneOf[0];
  }
  function visit(value, descriptor, path) {
    const selected = branchFor(value, descriptor);
    if (selected?.type === "object" || selected?.properties) {
      for (const [key, nested] of Object.entries(asObject(selected.properties))) visit(asObject(value)[key], nested, `${path}.${key}`);
      return;
    }
    rows.push({ path, section: "load", label: selected?.title ?? path.split(".").at(-1), schema: selected });
  }
  visit(input, providerInputSchema(schema, asObject(draft.load_provider).provider_id), "load_provider.provider_input");
  return rows;
}

function readPath(value, path) { return path.split(".").reduce((current, key) => asObject(current)[key], value); }

export function validationBudgetRows(preview) {
  if (!Array.isArray(preview?.counts)) return [];
  return preview.counts
    .filter((row) => typeof row?.metric === "string"
      && Number.isInteger(row?.value) && row.value >= 0
      && (row.semantics === "exact" || row.semantics === "upper_bound"))
    .map((row) => ({ metric: row.metric, value: row.value, semantics: row.semantics }));
}

export function canGenerate(candidate) {
  const current = asObject(candidate);
  const validation = asObject(current.validation);
  const gate = asObject(current.generation_gate);
  if (typeof current.project_id !== "string" || !current.project_id || current.conflict?.blocking) return false;
  if (!Number.isInteger(current.persisted_draft_revision)
      || current.persisted_draft_revision !== current.draft_revision) return false;
  if (validation.project_id !== current.project_id || validation.project_revision !== current.revision) return false;
  if (typeof validation.fingerprint !== "string" || !validation.fingerprint) return false;
  if (gate.allowed !== true || gate.project_id !== current.project_id
      || gate.project_revision !== current.revision
      || gate.validation_fingerprint !== validation.fingerprint) return false;
  if (!Array.isArray(gate.blocking_error_ids) || gate.blocking_error_ids.length
      || !Array.isArray(gate.unacknowledged_warning_ids) || gate.unacknowledged_warning_ids.length) return false;
  if (!Array.isArray(validation.findings) || validation.findings.some((row) => row?.severity === "error")) return false;
  const acknowledgements = asObject(current.acknowledgements);
  return validation.findings.filter((row) => row?.severity === "warning").every((row) => {
    const record = asObject(acknowledgements[row.finding_id]);
    return record.finding_id === row.finding_id
      && record.finding_content_hash === row.content_hash
      && record.project_revision === current.revision
      && record.validation_fingerprint === validation.fingerprint;
  });
}

export function normalizeDraftForSchema(draft, schema, assetId) {
  const scenarioSchema = schema?.scenario_draft_schema;
  if (scenarioSchema) {
    const projected = normalizeSchemaValue(draft, scenarioSchema);
    if (projected) return projected;
  }
  const normalized = clone(asObject(draft));
  const loadProvider = asObject(normalized.load_provider);
  const providerId = loadProvider.provider_id;
  if (typeof providerId === "string" && providerId) {
    const providerInput = normalizeSchemaValue(loadProvider.provider_input, providerInputSchema(schema, providerId));
    normalized.load_provider = { provider_id: providerId, provider_input: providerInput ?? {} };
    const kinds = allowedScenarioKinds(schema, providerId);
    if (kinds.length && !kinds.includes(normalized.scenario_kind)) normalized.scenario_kind = kinds[0];
  } else normalized.load_provider = {};
  normalized.building_placement = normalizeBuildingPlacement(normalized, schema, assetId);
  return normalized;
}

export function renderSchemaFields(section, schema, draft) {
  const fragment = document.createDocumentFragment();
  for (const field of schemaFieldRows(section, schema, draft)) {
    const descriptor = asObject(field);
    if (!descriptor.path) continue;
    const fieldSchema = asObject(descriptor.schema ?? descriptor);
    const fixedNumberVectorSize = fieldSchema.type === "array"
      && Number.isInteger(fieldSchema.minItems)
      && fieldSchema.minItems === fieldSchema.maxItems
      && [3, 5].includes(fieldSchema.minItems)
      && asObject(fieldSchema.items).type === "number"
      ? fieldSchema.minItems : 0;
    if (fixedNumberVectorSize) {
      const fieldset = document.createElement("fieldset");
      fieldset.className = "refined-blast-schema-field refined-blast-vector-field";
      fieldset.dataset.refinedFieldPath = descriptor.path;
      fieldset.dataset.refinedVectorSize = String(fixedNumberVectorSize);
      const legend = document.createElement("legend");
      legend.textContent = descriptor.label ?? descriptor.path;
      const value = readPath(draft, descriptor.path);
      fieldset.append(legend);
      const axes = fixedNumberVectorSize === 3
        ? ["X", "Y", "Z"] : ["X−", "X+", "Y−", "Y+", "顶部"];
      for (const [index, axis] of axes.entries()) {
        const input = document.createElement("input");
        input.type = "number";
        input.name = descriptor.path;
        input.dataset.refinedDraftPath = descriptor.path;
        input.dataset.refinedSchemaType = "number";
        input.dataset.refinedSchema = JSON.stringify(fieldSchema);
        input.dataset.refinedVectorAxis = axis;
        input.dataset.refinedVectorIndex = String(index);
        input.setAttribute?.("aria-label", `${legend.textContent} ${axis}`);
        input.setAttribute?.("title", axis);
        if (Array.isArray(value) && Number.isFinite(Number(value[index]))) input.value = String(value[index]);
        fieldset.append(input);
      }
      fragment.append(fieldset);
      continue;
    }
    const label = document.createElement("label");
    label.className = "refined-blast-schema-field";
    label.dataset.refinedFieldPath = descriptor.path;
    label.textContent = descriptor.label ?? descriptor.path;
    const structured = fieldSchema.type === "array" || fieldSchema.type === "object";
    const input = Array.isArray(fieldSchema.enum) ? document.createElement("select")
      : structured ? document.createElement("textarea") : document.createElement("input");
    if (Array.isArray(fieldSchema.enum)) {
      for (const optionValue of fieldSchema.enum) {
        const option = document.createElement("option"); option.value = String(optionValue); option.textContent = String(optionValue); input.append(option);
      }
    } else {
      if (structured) input.rows = 4;
      else input.type = fieldSchema.type === "number" || fieldSchema.type === "integer" ? "number" : fieldSchema.type === "boolean" ? "checkbox" : "text";
    }
    input.name = descriptor.path;
    input.dataset.refinedDraftPath = descriptor.path;
    input.dataset.refinedSchemaType = fieldSchema.type ?? "string";
    input.dataset.refinedSchema = JSON.stringify(fieldSchema);
    if (fieldSchema.minimum !== undefined) input.min = String(fieldSchema.minimum);
    if (fieldSchema.maximum !== undefined) input.max = String(fieldSchema.maximum);
    if (fieldSchema.exclusiveMinimum !== undefined) input.min = String(fieldSchema.exclusiveMinimum);
    if (fieldSchema.type === "integer") input.step = "1";
    else if (fieldSchema.type === "number") input.step = "any";
    const value = readPath(draft, descriptor.path);
    if (fieldSchema.type === "boolean") input.checked = Boolean(value);
    else if (value !== undefined && value !== null) input.value = typeof value === "object" ? JSON.stringify(value) : String(value);
    label.append(input);
    fragment.append(label);
  }
  return fragment;
}

export function createRefinedBlastStore(options = {}) {
  const initialDraftRevision = Number.isInteger(options.draft_revision) ? options.draft_revision : 0;
  let state = {
    activeSchema: clone(options.schema ?? {}),
    asset_id: options.asset_id ?? null,
    building: clone(options.building ?? {}), project_id: options.project_id ?? null,
    building_compilation_state: normalizedBuildingCompilationState(
      options.building_compilation_state,
    ),
    draft: {}, revision: Number.isInteger(options.revision) && options.revision > 0 ? options.revision : 1,
    draft_revision: initialDraftRevision,
    persisted_draft_revision: options.project_id
      ? (Number.isInteger(options.persisted_draft_revision) ? options.persisted_draft_revision : initialDraftRevision)
      : null,
    validation: options.validation ?? null,
    acknowledgements: clone(options.acknowledgements ?? {}),
    generation_gate: options.generation_gate ?? options.validation?.generation_gate ?? null,
    provider_input_migrations: normalizeProviderInputMigrations(
      options.provider_input_migrations,
    ),
    preview: options.preview ?? null, conflict: null, visible_sections: []
  };
  state.draft = normalizeDraftForSchema(options.draft ?? {}, state.activeSchema, state.asset_id);
  // Compatibility for the pre-18F test-only shell shape.  Production schemas
  // always carry building separately and never read placement structural data.
  if (!state.activeSchema?.scenario_draft_schema && !state.building.structural_system) {
    state.building = { ...state.building, structural_system: asObject(options.draft?.building_placement).structural_system };
  }
  state.building = normalizeBuildingForAsset(state.building, state.activeSchema, state.asset_id);
  state.visible_sections = visibleSections(state.activeSchema, state.building, state.asset_id);
  const fetchImpl = options.fetch ?? (typeof window === "undefined" ? () => Promise.reject(new Error("fetch is unavailable")) : window.fetch.bind(window));
  let latestSaveToken = 0;
  let latestPreviewToken = 0;
  let activePreviewMountToken = null;
  let latestValidationToken = 0;
  let activeValidationMountToken = null;
  let latestAcknowledgementToken = 0;
  const acknowledgementTokens = new Map();

  function refreshVisibleSections() { state.visible_sections = visibleSections(state.activeSchema, state.building, state.asset_id); }
  function getState() { return clone(state); }
  function invalidateValidation() {
    latestValidationToken += 1;
    latestAcknowledgementToken += 1;
    acknowledgementTokens.clear();
    state.validation = null;
    state.acknowledgements = {};
    state.generation_gate = null;
  }
  function updateDraft(mutator) {
    const next = clone(state.draft); mutator(next);
    const normalized = normalizeDraftForSchema(next, state.activeSchema, state.asset_id);
    if (equal(state.draft, normalized)) return getState();
    state.draft = normalized; state.draft_revision += 1; invalidateValidation(); state.preview = null; state.conflict = null;
    refreshVisibleSections(); return getState();
  }
  function updateBuilding(mutator) {
    if (state.project_id) return getState();
    const next = clone(state.building);
    mutator(next);
    const normalized = normalizeBuildingForAsset(next, state.activeSchema, state.asset_id);
    if (equal(state.building, normalized)) return getState();
    state.building = normalized;
    state.draft_revision += 1;
    invalidateValidation();
    state.preview = null;
    state.conflict = null;
    refreshVisibleSections();
    return getState();
  }
  function setProvider(providerId) {
    const provider = providerEntry(state.activeSchema, providerId);
    const input = normalizeSchemaValue(provider.default_input, providerInputSchema(state.activeSchema, providerId)) ?? {};
    updateDraft((draft) => { draft.load_provider = { provider_id: providerId, provider_input: input }; });
  }
  function replaceDraft(nextDraft) {
    const normalized = normalizeDraftForSchema(nextDraft, state.activeSchema, state.asset_id);
    if (equal(state.draft, normalized)) return getState();
    state.draft = normalized; state.draft_revision += 1;
    invalidateValidation(); state.preview = null; state.conflict = null;
    refreshVisibleSections(); return getState();
  }
  function beginBuildingEditCopy() {
    if (!state.project_id) return getState();
    latestSaveToken += 1;
    latestPreviewToken += 1;
    latestValidationToken += 1;
    latestAcknowledgementToken += 1;
    acknowledgementTokens.clear();
    state.project_id = null;
    state.revision = 1;
    state.persisted_draft_revision = null;
    state.building_compilation_state = "pending";
    state.validation = null;
    state.acknowledgements = {};
    state.generation_gate = null;
    state.provider_input_migrations = [];
    state.preview = null;
    state.conflict = null;
    return getState();
  }
  function setStructuralSystem(structuralSystem) {
    if (state.project_id) return getState();
    const asset = assetEntry(state.activeSchema, state.asset_id);
    if (asset?.allowed_structural_systems && !asset.allowed_structural_systems.includes(structuralSystem)) return getState();
    const nextBuilding = normalizeBuildingForAsset({ ...asObject(state.building), structural_system: structuralSystem }, state.activeSchema, state.asset_id);
    if (equal(nextBuilding, state.building)) return getState();
    state.building = nextBuilding;
    state.draft_revision += 1; invalidateValidation(); state.preview = null; state.conflict = null;
    refreshVisibleSections(); return getState();
  }
  function setAsset(assetId) {
    if (state.project_id) return getState();
    const priorBuilding = clone(state.building);
    const priorDraft = clone(state.draft);
    state.asset_id = assetEntry(state.activeSchema, assetId) ? assetId : null;
    const normalized = normalizeDraftForSchema(state.draft, state.activeSchema, state.asset_id);
    if (!equal(state.draft, normalized)) state.draft = normalized;
    const asset = assetEntry(state.activeSchema, state.asset_id);
    if (asset) state.building = normalizeBuildingForAsset({ ...asObject(state.building), asset_id: asset.asset_id, structural_system: asObject(state.building).structural_system ?? asset.default_structural_system }, state.activeSchema, state.asset_id);
    if (!equal(priorDraft, state.draft) || !equal(priorBuilding, state.building)) {
      state.draft_revision += 1; invalidateValidation(); state.preview = null; state.conflict = null;
    }
    refreshVisibleSections(); return getState();
  }
  function setSchema(schema) {
    state.activeSchema = clone(schema ?? {});
    const normalized = normalizeDraftForSchema(state.draft, state.activeSchema, state.asset_id);
    if (!equal(state.draft, normalized)) { state.draft = normalized; state.draft_revision += 1; invalidateValidation(); state.preview = null; }
    state.building = normalizeBuildingForAsset(state.building, state.activeSchema, state.asset_id);
    refreshVisibleSections(); return getState();
  }
  function restorePersistedProject(stored, expectedProjectId = null, metadata = {}) {
    const project = asObject(stored?.project);
    const draft = Array.isArray(project.scenario_set) && project.scenario_set.length === 1 ? project.scenario_set[0] : null;
    const building = asObject(stored?.building);
    if (typeof stored?.project_id !== "string" || !stored.project_id
        || (expectedProjectId !== null && stored.project_id !== expectedProjectId)
        || !Number.isInteger(stored.revision) || stored.revision < 1 || !draft) {
      throw new Error("persisted refined project response is invalid");
    }
    const assetId = asObject(project.building_reference).asset_id;
    if (typeof assetId !== "string" || !assetId || building.asset_id !== assetId) {
      throw new Error("persisted refined project building identity is invalid");
    }
    const migrationRows = normalizeProviderInputMigrations(
      stored?.provider_input_migrations,
    );
    if (migrationRows.some((row) => (
      row.scenario_id !== draft.scenario_id
      || row.provider_id !== asObject(draft.load_provider).provider_id
    ))) {
      throw new Error("persisted provider migration source is invalid");
    }
    if (typeof assetId === "string" && assetEntry(state.activeSchema, assetId)) state.asset_id = assetId;
    state.project_id = stored.project_id;
    state.revision = stored.revision;
    state.building_compilation_state = normalizedBuildingCompilationState(
      metadata?.building_compilation_state ?? stored?.building_compilation_state,
    );
    state.building = normalizeBuildingForAsset(building, state.activeSchema, state.asset_id);
    state.draft = normalizeDraftForSchema(draft, state.activeSchema, state.asset_id);
    state.draft_revision = 0;
    state.persisted_draft_revision = 0;
    state.validation = null; state.acknowledgements = {}; state.generation_gate = null;
    state.provider_input_migrations = migrationRows;
    state.preview = null; state.conflict = null;
    refreshVisibleSections(); return getState();
  }
  async function save(projectId, createPayload, requestOptions = {}) {
    const token = ++latestSaveToken;
    const expectedRevision = state.revision;
    const draftRevision = state.draft_revision;
    const draftSnapshot = clone(state.draft);
    const creating = !projectId;
    invalidateValidation();
    const response = await fetchImpl(creating ? `${REFINED_BLAST_API_PREFIX}/projects` : `${REFINED_BLAST_API_PREFIX}/projects/${encodeURIComponent(projectId)}/save`, {
      method: "POST", headers: { Accept: "application/json", "Content-Type": "application/json" },
      body: JSON.stringify(creating ? createPayload : { expected_revision: expectedRevision, draft: draftSnapshot }),
      ...(requestOptions.signal ? { signal: requestOptions.signal } : {}),
    });
    const payload = await response.json();
    if (token !== latestSaveToken) return getState();
    const snapshotCurrent = state.draft_revision === draftRevision && equal(state.draft, draftSnapshot);
    if (response.status === 409) {
      if (snapshotCurrent) state.conflict = { blocking: true, status: 409, expected_revision: expectedRevision, detail: payload };
      return getState();
    }
    if (!response.ok) throw new Error(payload?.message ?? `save failed with HTTP ${response.status}`);
    const project = payload?.result?.project ?? payload?.project;
    if (Number.isInteger(project?.revision) && project.revision > 0) state.revision = project.revision;
    if (creating && typeof project?.project?.project_id === "string") state.project_id = project.project.project_id;
    if (creating && typeof project?.project_id === "string") state.project_id = project.project_id;
    if (project?.building_compilation_state !== undefined) {
      state.building_compilation_state = normalizedBuildingCompilationState(
        project.building_compilation_state,
      );
    } else if (creating) state.building_compilation_state = "pending";
    state.persisted_draft_revision = draftRevision;
    if (snapshotCurrent) state.conflict = null;
    return getState();
  }
  function projectCreatePayload(project, createSchemaVersion = "refined_blast_create@1") {
    return { schema_version: createSchemaVersion, building: clone(state.building), project: { ...clone(project), scenario_set: [clone(state.draft)] } };
  }
  function savePayload() { return { expected_revision: state.revision, draft: clone(state.draft) }; }
  function applyGeneratedRevision(artifact, issuedRevision) {
    if (!artifact || artifact.project_id !== state.project_id
        || artifact.scenario_id !== state.draft?.scenario_id
        || !Number.isInteger(issuedRevision) || issuedRevision !== state.revision
        || artifact.revision !== issuedRevision + 1
        || state.persisted_draft_revision !== state.draft_revision
        || state.conflict?.blocking) return false;
    state.revision = artifact.revision;
    state.building_compilation_state = "compiled";
    invalidateValidation();
    state.preview = null;
    state.conflict = null;
    return true;
  }
  function beginPreviewRequest({ mount_token: mountToken, project_id: projectId } = {}) {
    if (typeof mountToken !== "string" && typeof mountToken !== "number") throw new Error("preview mount token is required");
    if (typeof projectId !== "string" || !projectId || projectId !== state.project_id) throw new Error("preview project identity is not current");
    activePreviewMountToken = mountToken;
    return {
      mount_token: mountToken,
      project_id: projectId,
      request_token: ++latestPreviewToken,
      persisted_revision: state.revision,
      draft_revision: state.draft_revision,
      draft_snapshot: clone(state.draft),
    };
  }
  function previewRequestIsCurrent(issue, payload = null) {
    if (!issue || issue.request_token !== latestPreviewToken || issue.mount_token !== activePreviewMountToken) return false;
    if (issue.project_id !== state.project_id || issue.persisted_revision !== state.revision) return false;
    if (issue.draft_revision !== state.draft_revision || !equal(issue.draft_snapshot, state.draft)) return false;
    if (payload) {
      if (payload.project_id !== issue.project_id) return false;
      if (payload.project_revision !== issue.persisted_revision) return false;
    }
    return true;
  }
  function applyPreview(payload, issue) {
    if (!previewRequestIsCurrent(issue, payload)) return false;
    state.preview = clone(payload);
    return true;
  }
  function rejectPreviewRequest(issue, status = 0, detail = null) {
    if (!previewRequestIsCurrent(issue)) return false;
    state.preview = null;
    if (status === 409) {
      state.conflict = { blocking: true, status, expected_revision: issue.persisted_revision, detail: clone(detail) };
      invalidateValidation();
    }
    return true;
  }
  function disposePreviewRequests(mountToken) {
    if (mountToken !== activePreviewMountToken) return false;
    latestPreviewToken += 1;
    activePreviewMountToken = null;
    state.preview = null;
    return true;
  }
  function beginValidationRequest({ mount_token: mountToken, project_id: projectId } = {}) {
    if (typeof mountToken !== "string" && typeof mountToken !== "number") throw new Error("validation mount token is required");
    if (typeof projectId !== "string" || !projectId || projectId !== state.project_id) throw new Error("validation project identity is not current");
    if (state.conflict?.blocking || state.persisted_draft_revision !== state.draft_revision) throw new Error("validation requires a current persisted draft");
    activeValidationMountToken = mountToken;
    invalidateValidation();
    return {
      mount_token: mountToken,
      project_id: projectId,
      request_token: ++latestValidationToken,
      persisted_revision: state.revision,
      draft_revision: state.draft_revision,
      scenario_id: state.draft?.scenario_id,
      draft_snapshot: clone(state.draft),
    };
  }
  function validationRequestIsCurrent(issue, payload = null) {
    if (!issue || issue.request_token !== latestValidationToken || issue.mount_token !== activeValidationMountToken) return false;
    if (issue.project_id !== state.project_id || issue.persisted_revision !== state.revision) return false;
    if (issue.draft_revision !== state.draft_revision || state.persisted_draft_revision !== state.draft_revision) return false;
    if (issue.scenario_id !== state.draft?.scenario_id || !equal(issue.draft_snapshot, state.draft)) return false;
    if (payload && (payload.project_id !== issue.project_id || payload.project_revision !== issue.persisted_revision)) return false;
    return true;
  }
  function applyValidation(payload, issue) {
    if (!validationRequestIsCurrent(issue, payload)) return false;
    const gate = asObject(payload?.generation_gate);
    if (typeof payload?.fingerprint !== "string" || !payload.fingerprint || !Array.isArray(payload.findings)) return false;
    if (gate.project_id !== payload.project_id || gate.project_revision !== payload.project_revision
        || gate.validation_fingerprint !== payload.fingerprint || typeof gate.allowed !== "boolean"
        || !Array.isArray(gate.blocking_error_ids) || !Array.isArray(gate.unacknowledged_warning_ids)) return false;
    const validFindings = payload.findings.every((row) => row
      && ["error", "warning", "info"].includes(row.severity)
      && ["finding_id", "module", "field_path", "message", "correction", "content_hash"]
        .every((key) => typeof row[key] === "string" && row[key]));
    if (!validFindings) return false;
    state.validation = clone(payload);
    state.generation_gate = clone(gate);
    state.acknowledgements = {};
    state.conflict = null;
    return true;
  }
  function rejectValidationRequest(issue, status, detail) {
    if (!validationRequestIsCurrent(issue)) return false;
    invalidateValidation();
    if (status === 409) state.conflict = { blocking: true, status, expected_revision: issue.persisted_revision, detail: clone(detail) };
    return true;
  }
  function beginAcknowledgementRequest(findingId, { mount_token: mountToken } = {}) {
    if (mountToken !== activeValidationMountToken || !state.validation) throw new Error("acknowledgement validation identity is not current");
    const row = state.validation.findings.find((finding) => finding.finding_id === findingId && finding.severity === "warning");
    if (!row) throw new Error("acknowledgement requires one current warning");
    const token = ++latestAcknowledgementToken;
    acknowledgementTokens.set(findingId, token);
    return {
      mount_token: mountToken,
      project_id: state.project_id,
      request_token: token,
      persisted_revision: state.revision,
      draft_revision: state.draft_revision,
      scenario_id: state.draft?.scenario_id,
      validation_fingerprint: state.validation.fingerprint,
      finding_id: row.finding_id,
      finding_content_hash: row.content_hash,
    };
  }
  function acknowledgementRequestIsCurrent(issue) {
    if (!issue || issue.mount_token !== activeValidationMountToken) return false;
    if (acknowledgementTokens.get(issue.finding_id) !== issue.request_token) return false;
    if (issue.project_id !== state.project_id || issue.persisted_revision !== state.revision) return false;
    if (issue.draft_revision !== state.draft_revision || state.persisted_draft_revision !== state.draft_revision) return false;
    if (issue.scenario_id !== state.draft?.scenario_id || issue.validation_fingerprint !== state.validation?.fingerprint) return false;
    const row = state.validation?.findings?.find((finding) => finding.finding_id === issue.finding_id && finding.severity === "warning");
    return row?.content_hash === issue.finding_content_hash;
  }
  function applyAcknowledgement(payload, issue) {
    if (!acknowledgementRequestIsCurrent(issue)) return false;
    const record = asObject(payload?.acknowledgement);
    const gate = asObject(payload?.generation_gate);
    if (record.finding_id !== issue.finding_id || record.finding_content_hash !== issue.finding_content_hash
        || record.project_revision !== issue.persisted_revision
        || record.validation_fingerprint !== issue.validation_fingerprint) return false;
    if (gate.project_id !== issue.project_id || gate.project_revision !== issue.persisted_revision
        || gate.validation_fingerprint !== issue.validation_fingerprint || typeof gate.allowed !== "boolean"
        || !Array.isArray(gate.blocking_error_ids) || !Array.isArray(gate.unacknowledged_warning_ids)) return false;
    state.acknowledgements[issue.finding_id] = clone(record);
    state.generation_gate = clone(gate);
    acknowledgementTokens.delete(issue.finding_id);
    return true;
  }
  function rejectAcknowledgementRequest(issue, status, detail) {
    if (!acknowledgementRequestIsCurrent(issue)) return false;
    acknowledgementTokens.delete(issue.finding_id);
    if (status === 409) {
      state.conflict = { blocking: true, status, expected_revision: issue.persisted_revision, detail: clone(detail) };
      invalidateValidation();
    }
    return true;
  }
  function disposeValidationRequests(mountToken) {
    if (mountToken !== activeValidationMountToken) return false;
    invalidateValidation();
    activeValidationMountToken = null;
    return true;
  }
  return {
    getState, updateDraft, updateBuilding, beginBuildingEditCopy, replaceDraft, setProvider, setStructuralSystem, setAsset, setSchema, restorePersistedProject,
    save, projectCreatePayload, savePayload, applyGeneratedRevision, beginPreviewRequest, applyPreview,
    rejectPreviewRequest, disposePreviewRequests,
    beginValidationRequest, applyValidation, rejectValidationRequest,
    beginAcknowledgementRequest, applyAcknowledgement, rejectAcknowledgementRequest,
    disposeValidationRequests,
    schemaValueIsValid,
    canGenerate: () => canGenerate(state),
    validationBudgetRows: () => validationBudgetRows(state.preview),
  };
}

function normalizeProviderInputMigrations(value) {
  if (value === undefined || value === null) return [];
  if (!Array.isArray(value)) {
    throw new Error("provider input migrations must be an array");
  }
  const required = [
    "scenario_id", "provider_id", "source_schema_version", "target_schema_version",
  ];
  return value.map((candidate) => {
    const row = asObject(candidate);
    if (
      Object.keys(row).length !== required.length
      || required.some((key) => typeof row[key] !== "string" || !row[key])
    ) {
      throw new Error("provider input migration record is invalid");
    }
    return clone(row);
  });
}
