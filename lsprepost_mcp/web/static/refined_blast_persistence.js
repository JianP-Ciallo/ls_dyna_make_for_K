const LATEST_PROJECT_KEY = "refined-blast.latest-project";
const SESSION_DRAFT_KEY = "refined-blast.session-draft";
const SESSION_DRAFT_SCHEMA = "refined-blast-session-draft@1";
const PROJECT_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_.-]*$/;

function safeRead(storage, key) {
  try { return storage?.getItem?.(key) ?? null; }
  catch (_) { return null; }
}

export function safeStorageWrite(storage, key, value) {
  try {
    if (value === null || value === undefined) storage?.removeItem?.(key);
    else storage?.setItem?.(key, value);
  } catch (_) {}
}

export function readLatestProjectId(storage) {
  const value = safeRead(storage, LATEST_PROJECT_KEY);
  return typeof value === "string" && PROJECT_ID_PATTERN.test(value) ? value : null;
}

export function writeLatestProjectId(storage, projectId) {
  safeStorageWrite(storage, LATEST_PROJECT_KEY,
    typeof projectId === "string" && PROJECT_ID_PATTERN.test(projectId) ? projectId : null);
}

export function readSessionDraft(storage) {
  const raw = safeRead(storage, SESSION_DRAFT_KEY);
  if (!raw) return null;
  try {
    const envelope = JSON.parse(raw);
    if (envelope?.schema_version !== SESSION_DRAFT_SCHEMA
        || !envelope.snapshot || typeof envelope.snapshot !== "object"
        || Array.isArray(envelope.snapshot)) return null;
    const snapshot = envelope.snapshot;
    if (typeof snapshot.asset_id !== "string" || !snapshot.asset_id
        || !snapshot.building || typeof snapshot.building !== "object"
        || !snapshot.draft || typeof snapshot.draft !== "object") return null;
    return snapshot;
  } catch (_) { return null; }
}

export function writeSessionDraft(storage, snapshot) {
  if (!snapshot) {
    safeStorageWrite(storage, SESSION_DRAFT_KEY, null);
    return;
  }
  safeStorageWrite(storage, SESSION_DRAFT_KEY, JSON.stringify({
    schema_version: SESSION_DRAFT_SCHEMA,
    snapshot,
  }));
}

export function clearRecovery({ localStorage, sessionStorage } = {}) {
  safeStorageWrite(localStorage, LATEST_PROJECT_KEY, null);
  safeStorageWrite(sessionStorage, SESSION_DRAFT_KEY, null);
}
