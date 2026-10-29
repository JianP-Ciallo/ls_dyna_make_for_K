const fs = require("fs");
const path = require("path");
const vm = require("vm");

const root = path.resolve(__dirname, "..", "..");
const statePath = path.join(root, "lsprepost_mcp", "web", "static", "refined_blast_state.js");

function loadStateModule() {
  const source = fs.readFileSync(statePath, "utf8")
    .replace(/export function /g, "function ")
    .concat("\nmodule.exports = { createRefinedBlastStore, normalizeDraftForSchema, renderSchemaFields, schemaValueIsValid };\n");
  const element = (tagName = "div") => {
    const node = {
      tagName: String(tagName).toUpperCase(), dataset: {}, children: [],
      append(...children) { this.children.push(...children); },
      addEventListener() {}, setAttribute(name, value) { this[name] = value; },
      querySelectorAll() { return []; },
    };
    if (node.tagName === "TEXTAREA") {
      Object.defineProperty(node, "type", {
        get() { return "textarea"; },
        set() { throw new TypeError("HTMLTextAreaElement.type is read-only"); },
      });
    }
    return node;
  };
  const document = { createElement: element, createDocumentFragment() { return element("fragment"); } };
  const context = vm.createContext({ module: { exports: {} }, structuredClone, JSON, Object, Array, Set, Map, document });
  new vm.Script(source, { filename: statePath }).runInContext(context);
  return context.module.exports;
}

function schema() {
  return {
    common_fields: ["scenario_id", "scenario_kind", "building_placement", "load_provider"],
    building: {
      sections_by_structural_system: {
        rc_box: ["building_space", "structural_system", "rebar", "load"],
        steel_frame: ["building_space", "structural_system", "steel_connections", "load"]
      }
    },
    providers: {
      explicit_ale_fsi: { schema: { exact_root_keys: ["source_id", "ale_mesh_size_m"] } },
      lbe_segment: { schema: { exact_root_keys: ["source_id", "surface_categories"] } }
    }
  };
}

async function runCase(caseName) {
  const { createRefinedBlastStore, renderSchemaFields, schemaValueIsValid } = loadStateModule();
  if (caseName === "provider-switch") {
    const store = createRefinedBlastStore({
      schema: schema(),
      draft: {
        scenario_id: "scenario-1",
        scenario_kind: "external",
        building_placement: { structural_system: "rc_box" },
        load_provider: {
          provider_id: "explicit_ale_fsi",
          ale_mesh_size_m: 0.25,
          provider_input: { source_id: "charge-1", ale_mesh_size_m: 0.25 }
        }
      }
    });
    store.setProvider("lbe_segment");
    const state = store.getState();
    return { provider_id: state.draft.load_provider.provider_id, draft: state.draft };
  }
  if (caseName === "structural-system") {
    const store = createRefinedBlastStore({
      schema: schema(),
      draft: {
        scenario_id: "scenario-1", scenario_kind: "external",
        building_placement: { structural_system: "rc_box" },
        load_provider: { provider_id: "lbe_segment", provider_input: { source_id: "charge-1" } }
      }
    });
    const rc_visible = store.getState().visible_sections;
    store.setStructuralSystem("steel_frame");
    return { rc_visible, steel_visible: store.getState().visible_sections };
  }
  if (caseName === "revision-invalidation") {
    const store = createRefinedBlastStore({
      schema: schema(), revision: 7, validation: { fingerprint: "old" }, preview: { fingerprint: "old" },
      draft: {
        scenario_id: "scenario-1", scenario_kind: "external",
        building_placement: { structural_system: "rc_box" },
        load_provider: { provider_id: "lbe_segment", provider_input: { source_id: "charge-1" } }
      }
    });
    store.updateDraft((draft) => { draft.scenario_kind = "internal"; });
    const changed = store.getState();
    store.updateDraft(() => {});
    return { revision: changed.revision, draft_revision: changed.draft_revision, validation: changed.validation, preview: changed.preview, no_op_revision: store.getState().revision };
  }
  if (caseName === "save-conflict") {
    let request;
    const store = createRefinedBlastStore({
      schema: schema(), revision: 5,
      draft: {
        scenario_id: "scenario-local", scenario_kind: "external",
        building_placement: { structural_system: "rc_box" },
        load_provider: { provider_id: "lbe_segment", provider_input: { source_id: "charge-1" } }
      },
      fetch: async (url, options) => {
        request = { url, expected_revision: JSON.parse(options.body).expected_revision };
        return { ok: false, status: 409, json: async () => ({ code: "revision_conflict" }) };
      }
    });
    await store.save("project-1");
    const state = store.getState();
    return { request, conflict: state.conflict, draft: state.draft };
  }
  if (caseName === "stale-save") {
    const deferred = [];
    const store = createRefinedBlastStore({
      schema: schema(), revision: 5,
      draft: {
        scenario_id: "scenario-old", scenario_kind: "external",
        building_placement: { structural_system: "rc_box" },
        load_provider: { provider_id: "lbe_segment", provider_input: { source_id: "charge-1" } }
      },
      fetch: () => new Promise((resolve) => deferred.push(resolve))
    });
    const first = store.save("project-1");
    store.updateDraft((draft) => { draft.scenario_id = "scenario-newer"; });
    const second = store.save("project-1");
    deferred[1]({ ok: true, status: 200, json: async () => ({ project: { revision: 7, project: { scenario_set: [{ scenario_id: "server-second" }] } } }) });
    await second;
    deferred[0]({ ok: false, status: 409, json: async () => ({ code: "revision_conflict" }) });
    await first;
    return store.getState();
  }
  if (caseName === "deep-provider-pruning") {
    const store = createRefinedBlastStore({
      schema: {
        providers: {
          lbe_segment: {
            provider_input_schema: {
              type: "object", additionalProperties: false, properties: {
                source: { type: "object", additionalProperties: false, properties: {
                  source_id: { type: "string" }, position_m: { type: "array", items: { type: "number" } }
                } },
                selection: { type: "object", additionalProperties: false, properties: {
                  surface_categories: { type: "array", items: { type: "string", enum: ["exterior_surfaces", "interior_cavity_surfaces"] } }
                } },
                targets: { type: "array", items: { type: "object", additionalProperties: false, properties: { face_id: { type: "string" } } } }
              }
            }
          }
        }
      },
      draft: {
        scenario_id: "scenario-1", scenario_kind: "external", building_placement: {},
        load_provider: { provider_id: "lbe_segment", provider_input: {
          source: { source_id: "charge-1", position_m: [1, 2, 3, "drop"], stale: true },
          selection: { surface_categories: ["exterior_surfaces", "not-a-category"], policy: "none" },
          targets: [{ face_id: "face-1", selected: true }], stale_root: "drop"
        } }
      }
    });
    return store.getState();
  }
  if (caseName === "selected-asset") {
    const store = createRefinedBlastStore({
      schema: {
        assets: [
          { asset_id: "first", allowed_structural_systems: ["steel_frame"], default_structural_system: "steel_frame" },
          { asset_id: "subway_entrance_detailed_building", allowed_structural_systems: ["rc_box"], default_structural_system: "rc_box" }
        ],
        structural_systems: {
          rc_box: { visible_sections: ["rebar"], draft_fields: ["structural_system", "rebar"] },
          steel_frame: { visible_sections: ["steel_connections"], draft_fields: ["structural_system", "steel_connections"] }
        },
        providers: { lbe_segment: { supported_scenario_kinds: ["external"], provider_input_schema: { type: "object", properties: {} } } }
      },
      asset_id: "subway_entrance_detailed_building",
      draft: {
        scenario_id: "scenario-1", scenario_kind: "internal",
        building_placement: { structural_system: "steel_frame", rebar: { bar: "drop" }, steel_connections: { bolt: "drop" } },
        load_provider: { provider_id: "lbe_segment", provider_input: {} }
      }
    });
    store.setStructuralSystem("rc_box");
    const state = store.getState();
    return { asset_id: state.asset_id, structural_system: state.draft.building_placement.structural_system, draft: state.draft, scenario_kind: state.draft.scenario_kind };
  }
  if (caseName === "closed-payloads") {
    const store = createRefinedBlastStore({
      schema: { scenario_draft_schema: { type: "object", additionalProperties: false, required: ["scenario_id", "scenario_kind", "building_placement", "load_provider"], properties: { scenario_id: { type: "string" }, scenario_kind: { type: "string" }, building_placement: { type: "object", additionalProperties: false, properties: {} }, load_provider: { type: "object", additionalProperties: false, required: ["provider_id", "provider_input"], properties: { provider_id: { type: "string" }, provider_input: { type: "object", additionalProperties: false, properties: {} } } } } }, assets: [{ asset_id: "subway", allowed_structural_systems: ["rc_box"], default_structural_system: "rc_box", building_recipe_schema: { type: "object", properties: { asset_id: {}, structural_system: {}, generation_options: {} } } }], providers: { lbe_segment: { provider_input_schema: { type: "object", properties: {} } } } },
      asset_id: "subway", building: { asset_id: "subway", structural_system: "rc_box", rebar: { stale: true } },
      draft: { scenario_id: "scenario-1", scenario_kind: "external", building_placement: { structural_system: "rc_box", rebar: { stale: true } }, load_provider: { provider_id: "lbe_segment", provider_input: {} } }
    });
    const project = { schema_version: "refined_building_blast@1", project_id: "project-1", preset_reference: "none", preset_version: "1", project_overrides: {}, expert_extensions: {}, confirmation_records: [], provenance: {}, created_at: "2026-08-11T00:00:00Z", updated_at: "2026-08-11T00:00:00Z" };
    const payload = store.projectCreatePayload(project);
    return { building: payload.building, scenario: payload.project.scenario_set[0] };
  }
  if (caseName === "building-field-update") {
    const recipe = { type: "object", additionalProperties: false, properties: { asset_id: { type: "string" }, structural_system: { type: "string" }, mesh_profile: { type: "string", enum: ["standard", "fine"] } } };
    const base = { asset_id: "asset", structural_system: "rc_box", mesh_profile: "standard" };
    const common = { schema: { assets: [{ asset_id: "asset", default_structural_system: "rc_box", allowed_structural_systems: ["rc_box"], building_recipe_schema: recipe }] }, asset_id: "asset", building: base, draft: { scenario_id: "one", scenario_kind: "external", building_placement: {}, load_provider: {} }, validation: { fingerprint: "old" }, preview: { fingerprint: "old" } };
    const store = createRefinedBlastStore(common);
    store.updateBuilding((building) => { building.mesh_profile = "fine"; });
    const state = store.getState();
    const project = { schema_version: "refined_building_blast@1", project_id: "project-1", preset_reference: "none", preset_version: "1", project_overrides: {}, expert_extensions: {}, confirmation_records: [], provenance: {}, created_at: "2026-08-11T00:00:00Z", updated_at: "2026-08-11T00:00:00Z" };
    const payload = store.projectCreatePayload(project);
    const persisted = createRefinedBlastStore({ ...common, project_id: "project-1" });
    persisted.updateBuilding((building) => { building.mesh_profile = "fine"; });
    return { mesh_profile: state.building.mesh_profile, draft_revision: state.draft_revision, validation: state.validation, preview: state.preview, payload_mesh_profile: payload.building.mesh_profile, persisted_mesh_profile: persisted.getState().building.mesh_profile };
  }
  if (caseName === "persisted-revision") {
    const requests = [];
    const store = createRefinedBlastStore({ schema: schema(), draft: { scenario_id: "scenario-1", scenario_kind: "external", building_placement: {}, load_provider: { provider_id: "lbe_segment", provider_input: {} } }, fetch: async (url, options) => {
      requests.push({ url, body: JSON.parse(options.body) });
      return { ok: true, status: 200, json: async () => ({ project: { project_id: "project-1", revision: requests.length === 1 ? 1 : 2 } }) };
    }});
    const project = { schema_version: "refined_building_blast@1", project_id: "project-1", preset_reference: "none", preset_version: "1", project_overrides: {}, expert_extensions: {}, confirmation_records: [], provenance: {}, created_at: "2026-08-11T00:00:00Z", updated_at: "2026-08-11T00:00:00Z" };
    await store.save(null, store.projectCreatePayload(project));
    store.updateDraft((draft) => { draft.scenario_kind = "internal"; });
    store.updateDraft((draft) => { draft.scenario_kind = "external"; });
    await store.save("project-1");
    return { requests, state: store.getState() };
  }
  if (caseName === "save-signal") {
    const signal = { marker: "save-signal" };
    let forwarded = null;
    const store = createRefinedBlastStore({
      project_id: "project-1", revision: 1,
      draft: { scenario_id: "one", scenario_kind: "external", building_placement: {}, load_provider: {} },
      fetch: async (_url, options) => {
        forwarded = options.signal;
        return { ok: true, status: 200, json: async () => ({ project: { revision: 2 } }) };
      },
    });
    await store.save("project-1", undefined, { signal });
    return { forwarded: forwarded === signal };
  }
  if (caseName === "persisted-building-immutable") {
    const recipe = { type: "object", additionalProperties: false, properties: { asset_id: { type: "string" }, structural_system: { type: "string" } } };
    const store = createRefinedBlastStore({
      project_id: "project-1", asset_id: "asset-a", building: { asset_id: "asset-a", structural_system: "rc_box" },
      schema: { assets: [
        { asset_id: "asset-a", default_structural_system: "rc_box", allowed_structural_systems: ["rc_box"], building_recipe_schema: recipe },
        { asset_id: "asset-b", default_structural_system: "steel_frame", allowed_structural_systems: ["steel_frame"], building_recipe_schema: recipe },
      ] },
    });
    const before = store.getState();
    store.setStructuralSystem("steel_frame");
    store.setAsset("asset-b");
    return { before, after: store.getState() };
  }
  if (caseName === "building-edit-copy") {
    const recipe = {
      type: "object", additionalProperties: false,
      properties: {
        asset_id: { type: "string" },
        structural_system: { type: "string" },
        mesh_profile: { type: "string", enum: ["standard", "fine"] },
      },
    };
    const store = createRefinedBlastStore({
      project_id: "project-original", revision: 9,
      draft_revision: 2, persisted_draft_revision: 2,
      building_compilation_state: "pending",
      schema: { assets: [{
        asset_id: "asset-a", default_structural_system: "rc_box",
        allowed_structural_systems: ["rc_box"], building_recipe_schema: recipe,
      }] },
      asset_id: "asset-a",
      building: { asset_id: "asset-a", structural_system: "rc_box", mesh_profile: "standard" },
      draft: {
        scenario_id: "scenario-1", scenario_kind: "external",
        building_placement: {}, load_provider: {},
      },
      validation: { fingerprint: "old" }, preview: { fingerprint: "old" },
    });
    const source = store.getState();
    const detached = store.beginBuildingEditCopy();
    store.updateBuilding((building) => { building.mesh_profile = "fine"; });
    const edited = store.getState();
    return {
      source: {
        project_id: source.project_id, revision: source.revision,
        mesh_profile: source.building.mesh_profile,
      },
      detached: {
        project_id: detached.project_id, revision: detached.revision,
        persisted_draft_revision: detached.persisted_draft_revision,
        compilation_state: detached.building_compilation_state,
        scenario_id: detached.draft.scenario_id,
        mesh_profile: detached.building.mesh_profile,
        validation: detached.validation, preview: detached.preview,
      },
      edited: {
        project_id: edited.project_id, mesh_profile: edited.building.mesh_profile,
        draft_revision: edited.draft_revision,
      },
    };
  }
  if (caseName === "building-compilation-state") {
    const recipe = {
      type: "object", properties: {
        asset_id: { type: "string" }, structural_system: { type: "string" },
      },
    };
    const store = createRefinedBlastStore({
      schema: { assets: [{
        asset_id: "asset-a", default_structural_system: "rc_box",
        allowed_structural_systems: ["rc_box"], building_recipe_schema: recipe,
      }] },
      asset_id: "asset-a",
      building: { asset_id: "asset-a", structural_system: "rc_box" },
      draft: { scenario_id: "scenario-1", scenario_kind: "external", building_placement: {}, load_provider: {} },
    });
    store.restorePersistedProject({
      project_id: "project-1", revision: 7,
      building: { asset_id: "asset-a", structural_system: "rc_box" },
      project: {
        building_reference: { asset_id: "asset-a" },
        scenario_set: [{ scenario_id: "scenario-1", scenario_kind: "external", building_placement: {}, load_provider: {} }],
      },
    }, "project-1", { building_compilation_state: "pending" });
    const restored = store.getState();
    const applied = store.applyGeneratedRevision({
      project_id: "project-1", scenario_id: "scenario-1", revision: 8,
    }, 7);
    return {
      restored: restored.building_compilation_state,
      applied,
      generated: store.getState().building_compilation_state,
    };
  }
  if (caseName === "array-cardinality") {
    const store = createRefinedBlastStore({ schema: { providers: { demo: { supported_scenario_kinds: ["external"], input_schema: { type: "object", additionalProperties: false, properties: { vector: { type: "array", minItems: 3, maxItems: 3, items: { type: "number" } }, bounds: { type: "array", minItems: 6, maxItems: 6, items: { type: "number" } }, rows: { type: "array", items: { type: "array", minItems: 2, maxItems: 2, items: { type: "number" } } } } } } } }, draft: { scenario_id: "one", scenario_kind: "external", building_placement: {}, load_provider: { provider_id: "demo", provider_input: { vector: [1, 2], bounds: [1, 2, 3, 4, 5, 6, 7], rows: [[0, 1, 2], [3]] } } } });
    return store.getState().draft.load_provider.provider_input;
  }
  if (caseName === "provider-default") {
    const store = createRefinedBlastStore({ schema: { providers: {
      lbe_segment: { supported_scenario_kinds: ["external"], input_schema: { type: "object", additionalProperties: false, required: ["seed"], properties: { seed: { type: "string", const: "lbe" } } }, default_input: { seed: "lbe", stale: true } },
      imported_pressure_history: { supported_scenario_kinds: ["external"], input_schema: { type: "object", additionalProperties: false, required: ["seed"], properties: { seed: { type: "string", const: "imported" } } }, default_input: { seed: "imported" } }
    } }, draft: { scenario_id: "one", scenario_kind: "external", building_placement: {}, load_provider: { provider_id: "lbe_segment", provider_input: { seed: "lbe" } } } });
    store.setProvider("imported_pressure_history");
    return store.getState().draft.load_provider;
  }
  if (caseName === "rendered-provider-leaves") {
    const schema = { providers: { lbe_segment: { input_schema: { type: "object", properties: {
      source: { type: "object", properties: { position_m: { type: "array", items: { type: "number" } }, maximum_range_m: { type: "number" } } },
      load: { type: "object", properties: { peak_pressure_pa: { type: "number" } } }
    } } } } };
    const draft = { load_provider: { provider_id: "lbe_segment", provider_input: { source: { position_m: [1, 2, 3], maximum_range_m: 10 }, load: { peak_pressure_pa: 250000 } } } };
    const fragment = renderSchemaFields("load", schema, draft);
    return fragment.children.map((field) => field.dataset.refinedFieldPath ?? field.children[0].name);
  }
  if (caseName === "rendered-position-vector") {
    const schema = { providers: { lbe_segment: { input_schema: { type: "object", properties: {
      source: { type: "object", properties: { position_m: { type: "array", items: { type: "number" }, minItems: 3, maxItems: 3 } } }
    } } } } };
    const draft = { load_provider: { provider_id: "lbe_segment", provider_input: { source: { position_m: [1.25, -2.5, 3.75] } } } };
    const field = renderSchemaFields("load", schema, draft).children[0];
    return {
      tag: field.tagName,
      legend: field.children[0]?.textContent,
      inputs: field.children.slice(1).map((input) => ({
        type: input.type, value: Number(input.value), path: input.dataset.refinedDraftPath,
        axis: input.dataset.refinedVectorAxis, index: Number(input.dataset.refinedVectorIndex),
      })),
    };
  }
  if (caseName === "rendered-air-margins-vector") {
    const schema = { fields: [{
      path: "draft.load_provider.provider_input.air_margins_m",
      section: "workbench",
      label: "空气域五向余量",
      schema: { type: "array", items: { type: "number" }, minItems: 5, maxItems: 5 },
    }] };
    const draft = { draft: { load_provider: { provider_input: {
      air_margins_m: [2, 4, 3, 5, 6],
    } } } };
    const field = renderSchemaFields("workbench", schema, draft).children[0];
    return {
      tag: field.tagName,
      size: Number(field.dataset.refinedVectorSize),
      inputs: field.children.slice(1).map((input) => ({
        value: Number(input.value), axis: input.dataset.refinedVectorAxis,
        index: Number(input.dataset.refinedVectorIndex),
      })),
    };
  }
  if (caseName === "rendered-structured-array") {
    const schema = { providers: { imported_pressure_history: { input_schema: { type: "object", properties: {
      source: { type: "object", properties: { structured_rows: { type: "array", items: { type: "array", items: { type: "number" } } } } }
    } } } } };
    const draft = { load_provider: { provider_id: "imported_pressure_history", provider_input: { source: { structured_rows: [[0, 0], [0.1, 2]] } } } };
    const field = renderSchemaFields("load", schema, draft).children[0];
    return { tag: field.children[0].tagName, schema_type: field.children[0].dataset.refinedSchemaType, value: field.children[0].value };
  }
  if (caseName === "structured-schema-validation") {
    const descriptor = {
      type: "array", minItems: 1, maxItems: 3,
      items: { type: "array", minItems: 2, maxItems: 2, items: { type: "number" } },
    };
    return {
      valid: schemaValueIsValid([[0, 0], [0.1, 2]], descriptor),
      wrong_root_type: schemaValueIsValid({}, descriptor),
      wrong_row_shape: schemaValueIsValid([[0, 1, 2]], descriptor),
      wrong_scalar_type: schemaValueIsValid([[0, "2"]], descriptor),
    };
  }
  if (caseName === "save-success-after-edit") {
    let resolve;
    const store = createRefinedBlastStore({ schema: schema(), revision: 1, draft: { scenario_id: "one", scenario_kind: "external", building_placement: {}, load_provider: { provider_id: "lbe_segment", provider_input: {} } }, fetch: () => new Promise((done) => { resolve = done; }) });
    const saving = store.save("project-1");
    store.updateDraft((draft) => { draft.scenario_kind = "internal"; });
    resolve({ ok: true, status: 200, json: async () => ({ project: { revision: 2 } }) });
    await saving;
    return store.getState();
  }
  if (caseName === "generated-revision-reconciliation") {
    const validation = {
      project_id: "project-1", project_revision: 7, fingerprint: "validation-fingerprint", findings: [],
      generation_gate: {
        project_id: "project-1", project_revision: 7, validation_fingerprint: "validation-fingerprint",
        allowed: true, blocking_error_ids: [], unacknowledged_warning_ids: []
      }
    };
    const store = createRefinedBlastStore({
      project_id: "project-1", revision: 7, persisted_draft_revision: 3, draft_revision: 3,
      draft: { scenario_id: "scenario-1", scenario_kind: "external", building_placement: {}, load_provider: {} },
      validation,
    });
    const wrong = store.applyGeneratedRevision({ project_id: "project-1", scenario_id: "scenario-1", revision: 9 }, 7);
    const applied = store.applyGeneratedRevision({ project_id: "project-1", scenario_id: "scenario-1", revision: 8 }, 7);
    return { wrong, applied, state: store.getState(), can_generate: store.canGenerate() };
  }
  if (caseName === "persisted-migration-source") {
    const store = createRefinedBlastStore({
      schema: {
        assets: [{
          asset_id: "asset-a", default_structural_system: "rc_box",
          allowed_structural_systems: ["rc_box"],
          building_recipe_schema: { type: "object", properties: {} },
        }],
        providers: {
          solver_complete_ale_fsi: {
            input_schema: { type: "object", properties: {} },
          },
        },
      },
      asset_id: "asset-a",
      building: { asset_id: "asset-a", structural_system: "rc_box" },
      draft: {
        scenario_id: "scenario-1", scenario_kind: "external",
        building_placement: {},
        load_provider: { provider_id: "solver_complete_ale_fsi", provider_input: {} },
      },
    });
    store.restorePersistedProject({
      project_id: "project-1", revision: 2,
      building: { asset_id: "asset-a", structural_system: "rc_box" },
      project: {
        building_reference: { asset_id: "asset-a" },
        scenario_set: [{
          scenario_id: "scenario-1", scenario_kind: "external",
          building_placement: {},
          load_provider: { provider_id: "solver_complete_ale_fsi", provider_input: {} },
        }],
      },
      provider_input_migrations: [{
        scenario_id: "scenario-1", provider_id: "solver_complete_ale_fsi",
        source_schema_version: "phase18.solver_blast.config@3",
        target_schema_version: "phase18.solver_blast.config@4",
      }],
    }, "project-1");
    return store.getState().provider_input_migrations;
  }
  throw new Error(`unknown case: ${caseName}`);
}

runCase(process.argv[2]).then((result) => {
  process.stdout.write(`${JSON.stringify(result)}\n`);
}).catch((error) => {
  console.error(error && error.stack ? error.stack : error);
  process.exitCode = 1;
});
