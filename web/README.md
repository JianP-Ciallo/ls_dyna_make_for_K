# Workbench development and builds

The production UI lives in `../lsprepost_mcp/web/static/`. The Python server
always serves that directory, even when a stale `web/dist/index.html` exists.

From `web/`, `npm run dev` uses Vite to serve this same source and forwards
`/api` to the local Python server at `127.0.0.1:8765`. Start that backend
separately with the repository's normal Web startup script.

`npm run build` copies the complete workbench to `web/dist/`, retaining native
ES modules, the import map, vendored Three.js and demo assets. It does not
publish or start anything. `build:vite` remains a compatibility alias for the
same build command; `dev:vite` remains an alias for Vite development.

`node scripts/build-workbench.mjs <output-directory>` creates a standalone
static copy in another directory. The Python API is still required for live
project operations. Existing output files are preserved unless replaced by
an asset with the same relative path.

The old React files under `src/` and `web/index.html` are archived prototypes;
they are not inputs to the development server or release build.

Use the repository's `web-runtime` and `refined-api` focused test groups. The
runtime harnesses load the real persistence, HTTP and autosave modules. Full
regressions and heavy provider workflows retain the opt-in policy in AGENTS.md.

## Workspace layout

Both workbenches start with configuration and preview as the main areas. In the
refined workbench, the eight configuration steps share one left panel; the
preview toolbar can collapse it. The usage guide, camera choices and additional
operations expand on demand. The legacy task panel opens from the top bar;
operation errors reveal its log panel, and background updates mark its button.

`workbench_chrome.css` and `workbench_chrome.js` provide shared tool menus,
keyboard dismissal and the legacy layout rules. Refined page layout remains in
`refined_blast_workbench.css`. Field values, project persistence and launch
confirmation rules are unchanged by this layout pass.

With the local backend running, execute the read-only browser layout check from
the repository root:

```powershell
node web/tests/workbench-layout.e2e.cjs http://127.0.0.1:8765
```

It checks both pages at 1440, 1024 and 390 pixels, task/configuration panel
visibility, navigation, layer and assessment access, menu dismissal and page
width. All non-GET API requests are blocked by the test. Screenshots go to
`var/tmp/frontend-simplification/`. Set `PLAYWRIGHT_NODE_MODULES` to an external
Node modules directory or `CHROME_EXECUTABLE` to a local Chrome executable when
using a shared browser runtime; otherwise the local Playwright install is used.
