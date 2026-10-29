import { writeLatestProjectId, writeSessionDraft } from "./refined_blast_persistence.js";

const SAVE_TIMEOUT_MS = 10000;

function newProjectMetadata(options = {}) {
  const now = new Date().toISOString();
  const projectId = options.projectId ?? `refined-blast-${Date.now()}`;
  return options.project ?? {
    schema_version: "refined_building_blast@1", project_id: projectId,
    preset_reference: "browser_draft", preset_version: "1",
    project_overrides: {}, expert_extensions: {}, confirmation_records: [], provenance: {},
    created_at: now, updated_at: now
  };
}

export async function saveCurrentDraft(session, isActive) {
  if (!isActive(session)) return;
  session.saveAbortController?.abort();
  const controller = typeof AbortController === "function" ? new AbortController() : null;
  session.saveAbortController = controller;
  session.saveTimedOut = false;
  if (controller && typeof setTimeout === "function") {
    session.saveTimeoutId = setTimeout(() => {
      if (session.saveAbortController !== controller) return;
      session.saveTimedOut = true;
      controller.abort();
    }, SAVE_TIMEOUT_MS);
  }
  try {
    const requestOptions = controller ? { signal: controller.signal } : {};
    if (!session.projectId) {
      session.projectMetadata ??= newProjectMetadata();
      const state = await session.store.save(
        null,
        session.store.projectCreatePayload(
          session.projectMetadata,
          "refined_blast_create@2",
        ),
        requestOptions,
      );
      if (isActive(session)) {
        session.projectId = state.project_id ?? session.projectMetadata.project_id;
        if (session.projectId) {
          writeLatestProjectId(session.localStorage, session.projectId);
          writeSessionDraft(session.sessionStorage, null);
          history.replaceState({ workspace: "refined-blast" }, "", `/refined-building-blast?project_id=${encodeURIComponent(session.projectId)}`);
        }
      }
      return state;
    }
    return await session.store.save(session.projectId, undefined, requestOptions);
  } catch (error) {
    if (error?.name === "AbortError" && session.saveTimedOut) {
      const timeout = new Error("草稿保存超时，请重试");
      timeout.code = "save_timeout";
      throw timeout;
    }
    throw error;
  } finally {
    if (session.saveTimeoutId !== null && typeof clearTimeout === "function") {
      clearTimeout(session.saveTimeoutId);
    }
    session.saveTimeoutId = null;
    if (session.saveAbortController === controller) {
      session.saveAbortController = null;
    }
    session.saveTimedOut = false;
  }
}

