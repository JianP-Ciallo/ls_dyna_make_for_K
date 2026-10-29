# Fixed-building TNT interface integration

**Goal:** Add the previously retained TNT + air + FSI workflow to the existing fixed-building interface, and show pressure histories as results.

**Authority:** User approved the five-part in-chat design and instructed execution on 2026-10-23. Continue implementation without further routine approval requests. New whole-building generation, native solves and full regressions still require separate scope, timing and explicit approval.

**Architecture:** Keep the current three-column layout and four editor tabs. Preserve the existing external-pressure workflow for old scenes. Add a separate versioned TNT service with metadata-only estimation, explicit asynchronous export, sealed portable template and run-bound result reading. Reuse the retained exporter and its dependencies without overwriting existing main-project modules. The TNT result viewer belongs to the current scenario page.

**Global constraints:**
- Do not modify CPU response pages, backend, routes or data.
- Preserve other conversations' current UI, navigation, drafts and existing results.
- Never launch a solver, generate the actual whole-building scene or run broad test discovery in this task.
- Preserve original thresholds and historical numerical evidence. Production coupling defaults do not inherit the small-fixture Q8 setting.
- Opening the page, saving and previewing must not load the whole finite-element geometry or generate a mesh.
- Real result curves must bind to the exported scene revision and monitor element IDs; preserve native clocks, pressure basis and sample positions.

**Review focus:** stale exports and async responses; legacy scene/draft compatibility; archive/path integrity; result/run identity and pressure signs; accidental CPU or heavy-runtime side effects.

## Tasks

- [x] 1. Deploy the sealed retained TNT resource and minimal exporter dependency closure; create a lazy metadata-only schema/estimate service and save/list/load API. Test tiny fixtures, revision conflicts and no heavy imports on ordinary navigation.
- [x] 2. Add explicit, snapshot-bound export with scope confirmation, queue/status and ZIP download. Test small-model K content, archive integrity and stale-identity rejection. Do not invoke actual whole-building export.
- [x] 3. Add run-bound native result reading, pressure/overpressure curves and CSV export, preserving actual clocks and sampling metadata. Test saved binary evidence and invalid/mismatched runs without a solver.
- [x] 4. Add TNT/air+FSI/monitor/output editor and model overlays in the existing layout, preserve legacy pressure scenes, add results view and empty state. Test browser save/reload, placement, stale preview, no curve upload and no solver requests.
- [x] 5. Run related tests and one independent review, verify CPU/main baseline preservation, apply only the scoped delta to the main project and remove newly generated reproducible intermediates.

## Execution ledger

- Setup: branch `codex/fixed-building-tnt-integration` based on main-project HEAD; current main source overlaid byte-for-byte so recent UI edits remain the baseline. Baseline source hashes are in `artifacts/fixed-building-tnt-integration-20261023-01/main-baseline.json` in the main project.
- Ruling: retain all pre-existing dirty files in the isolated worktree; do not commit or copy unrelated changes back. Only a hash-checked feature allowlist may be applied to main.
- Ruling: shell skill helpers assume POSIX and per-task commits; use this ledger and scoped pytest commands on Windows, with a final independent review. No blanket cleanup or automatic merge.
- Baseline: 26 related tests passed; the initial sandbox temporary-directory failure was resolved by specifying a workspace-local pytest base directory.
- Tasks 1–4: RED→GREEN checks cover metadata-only behavior, revisions, small native K generation, raw historical binout, native clocks, monitor identity, CSV text safety, restored downloads and result view state.
- Final review: five findings reproduced and fixed in one pass; 43 Python checks and 19 real-HTTP browser checks plus three controlled-result UI checks passed before the final navigation identity refinement.
- Ruling: TNT uses a distinct URL query `tnt_scene_id` and draft identity. Only the pressure page query allowlist is extended; independent workflow query fields and all CPU sources remain unchanged. A Node-backed navigation test first reproduced query loss, then passed after the scoped extension.
- Ruling: rough generation timing in the confirmation is not a measurement or authorization to generate the real building during this implementation. Actual native building generation/solve remains unrun.
- Final main-project validation: 44 targeted Python tests passed (19.21 s after concurrent shared-adapter additions), 19 real-HTTP browser assertions and three controlled-result UI checks passed. The default smoke passed 20 tests and four subtests. Six pure navigation-state checks also passed against the current shared session code.
- Draft diagnostic: the first main browser run failed its reload assertion once. The complete diagnostic rerun passed; six further immediate-reload trials, with beforeunload/pagehide/storage telemetry, all restored the entered values. No JavaScript exception or repeatable production cause was found; the original failure and diagnostics are retained, and no speculative shared-navigation fix was made.
- Preservation: all 58 baseline paths containing `cpu_response` or `cpu-response` remain byte-identical. The feature allowlist contains no CPU source. Another chat subsequently extended the shared app/workspace/navigation/session adapters; those additions were preserved and the related tests rerun. Only this task's TNT delta was applied, without committing unrelated dirty files.
- Cleanup: removed 2,075 reproducible files (222,678,446 bytes), including test base directories, duplicate screenshots, test scenes and unpacked preview caches. Production resources, unit fixtures, provenance, failure records, final screenshots and test logs remain. No historical result tree was cleaned.
- Preview: the task's own server is available at `http://127.0.0.1:8900/structural-pressure`, using main-project source and isolated runtime data. The pre-existing main service was not stopped or restarted. No native solve, actual whole-building generation or full regression was run.

## Follow-up: outdoor placement and interactive camera

The user clarified that TNT must only be outside the building, and requested a freely movable view. This supersedes the earlier indoor-placement UI scope. Preserve historical indoor records and numerical evidence, the three-column layout, CPU sources and the original thresholds. No actual whole-building generation, native solve or full regression is authorized.

- [x] Reproduce missing exterior enforcement and fixed SVG projection with failing focused checks.
- [x] Enforce cylinder/circle intersection against the conservative building outer envelope in save, estimate, preview and export. Keep historical indoor scene IDs read-only; preserve rejected old browser drafts until backed up.
- [x] Replace only the TNT scene projection with the existing local Three/OrbitControls dependencies. Drag rotates, right drag pans and wheel zooms; presets remain freely rotatable. Preserve camera on parameter edits, resize and reload.
- [x] Independent read-only review: no blocking findings. A later focused browser test reproduced an uncaught error when the shared draft protection rejected new-scene creation; the UI now displays that refusal and preserves the draft through download before new-scene creation.
- [x] Complete related main-project checks, apply the hash-checked scoped delta, refresh the isolated preview and clean this round's reproducible intermediates.

Follow-up acceptance: 53 related main-project Python tests passed in 16.52 seconds; 19 existing UI assertions and three controlled-result cases passed, and four focused browser groups passed against the refreshed main preview (outside-only geometry, rotate/pan/zoom with pose persistence, historical indoor read-only behavior, old-draft preservation/backup/new-scene recovery). The first camera restore check was adjusted from byte-exact comparison to a 1e-8 floating-point tolerance after measuring a 1e-14 coordinate difference. No production camera correction was needed for that test precision issue.

The 11-path follow-up delta contains no shared navigation or CPU source. All 62 protected paths (58 existing CPU-related paths and four shared adapters) remain byte-identical to the follow-up baseline. The 8900 preview was refreshed with main source and its existing isolated data; the original main service was not restarted. Cleanup removed 390 generated/redundant files totaling 125,563,102 bytes; active preview data and historical results were not cleaned. Evidence is under `artifacts/fixed-building-tnt-ui-fix-20261023-01`.

## Follow-up: direct TNT dragging

The user requested direct mouse dragging while retaining the exterior restriction, free camera, existing layout and CPU boundary. Drag the orange marker or cylinder along the horizontal plane at its existing height; the left-side height field remains available. Validate both the whole cylinder at the candidate point and the swept path against the existing conservative building envelope. Hold the last valid position on rejection; Escape, lost pointer capture and focus loss cancel to the drag origin. No solver or new backend endpoint is involved.

- [x] Reproduce missing dragging with real pointer input before implementation.
- [x] Synchronize legal drag positions to X/Y, invalidate preview and retain the camera. Reject full-radius endpoint intersection, segment crossing and leaving the air buffer.
- [x] Capture the drag pointer and suspend camera controls only during object dragging; restore controls on release/cancel. Route OrbitControls through the container so wheel input over the marker still zooms.
- [x] Independent read-only review: no blocking finding. Ten focused real-browser assertions and four existing exterior/camera/history groups passed in the isolated implementation checkout.
- [x] Apply only the scoped frontend delta, verify related UI/API behavior in the main preview, and remove this round's reproducible intermediates while preserving history and user data.

Drag acceptance: ten real-pointer checks passed on the current main preview, including full-path collision blocking, a valid exterior route, oblique 3D dragging, Escape/lost-capture rollback, camera recovery and persisted drag coordinates. Six related API/navigation tests passed in 0.78 seconds. The existing 19 UI assertions, four exterior/camera/history groups and three controlled-result checks also passed. Browser checks explicitly forbid package generation, solver and CPU requests.

Harness corrections were verified without speculative production fixes: wait for preview operation completion, scene/draft restoration and a stable visible marker before assertions; deliver the next pointer event after releasePointerCapture so the browser processes lostpointercapture. Initial failed records remain under `artifacts/fixed-building-tnt-drag-20261023-01`.

The seven-path delta contains only four TNT static files, one focused browser test and these two documents. No backend, shared adapter or CPU source was modified; the running main preview did not require a restart. Cleanup removed 64 generated/redundant files (95,374,849 bytes), including the stopped development preview's unpacked cache, pytest temporary files and only explicitly recorded test scene IDs. User-modified scene records would be retained; none of the recorded test IDs had been modified. Historical results and numerical thresholds remain unchanged.

## Follow-up: mouse-controlled TNT height

The user requested height dragging in addition to the existing X/Y interaction. Add a separate ↕ handle alongside the orange marker: dragging up raises the cylinder, down lowers it, X/Y stay fixed. Use the drag-start camera's metres-per-pixel scale so this remains usable even from top view. Keep the existing free camera, data contracts, building geometry, thresholds and CPU boundary. No solver or native building generation is authorized.

- [x] Reproduce the missing height handle with a focused browser test before implementation.
- [x] Add a separate height mode to the existing pointer-capture lifecycle; validate the full cylinder, vertical swept interval, ground and air buffer before updating the height input. Invalidate preview, preserve the camera and restore all position fields on cancellation.
- [x] Independent read-only review found no blocking issue. Eleven focused height checks and ten existing X/Y drag checks passed in the isolated checkout. One height case uses a controlled elevated-envelope UI response to prove that a fast sweep with two legal endpoints cannot pass through the building; no native model is changed.
- [x] Apply the scoped static delta, finish main-preview/API and existing-page checks, and clean this round's test data and caches while preserving user data and historical evidence.

Height acceptance: eleven real-browser height checks passed on the main preview, including saved-height/placement-estimate agreement, oblique and top-view adjustment, roof/ground/air rejection, cancellation, camera preservation, reload recovery and a controlled swept-path case. Ten existing X/Y checks, 19 existing UI assertions, four exterior/camera/history groups and three controlled-result cases passed; six API/navigation tests passed in 0.83 seconds. The first roof test was corrected to target an actual interior height using the current camera scale; its original negative-ground target and failure remain recorded.

Only seven paths changed: four TNT static files, the new height browser test and the two task documents. All 63 protected paths, including the TNT backend and CPU/shared adapters, remain byte-identical. No live service restart was necessary. Cleanup removed 62 generated/redundant files (95,681,134 bytes), including the stopped development-preview cache, API-test temporary files, duplicate images and explicitly recorded test scenes whose revisions still matched test ownership. Historical results, thresholds, user-modified data and necessary evidence remain. Final hashes and logs are under `artifacts/fixed-building-tnt-height-drag-20261023-01`.
