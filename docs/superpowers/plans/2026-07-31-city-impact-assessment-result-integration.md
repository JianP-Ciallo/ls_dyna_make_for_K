# City Impact Assessment Result Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Register an explicitly selected external LS-DYNA city result, derive evidence-bound per-object FSI/pressure/stress/displacement metrics, and render/export a truthful numerical-response assessment without inventing engineering risk levels.

**Architecture:** A new result-source module owns external-path validation, evidence hashes, source priority, and atomic registration. Existing solver parsers are extended with pressure impulse and noise-resistant causality metrics; the city-impact service consumes the resolved source and emits a versioned assessment used by both the Web UI and HTML/JSON export. The completed `web_phase17_city_street_blast_response_v3_details` solve is a read-only acceptance fixture outside the repository.

**Tech Stack:** Python 3 standard library, existing `unittest` suite, existing local HTTP API, vanilla JavaScript/CSS, LS-DYNA ASCII outputs (`d3hsp`, `dbfsi`, `glstat`, `elout`, `nodout`) and `d3plot*` evidence.

## Global Constraints

- Do not modify `E:\K文件模型\web_phase17_city_street_blast_response_v3_details`.
- Do not copy the full `d3plot*` series into the workspace project.
- Do not trust a junction, symlink, or external path until the user explicitly selects and registers it.
- Bind every assessment to `model.k`, `model.json`, required result files, semantic objects, and response objects.
- Keep engineering risk `unavailable` unless an applicable reviewed or user-confirmed threshold profile exists.
- Never map `N*s` force impulse into a `Pa*s` pressure-impulse field.
- A completed solve is not sufficient: object-level causality and observation-window gates remain blocking.
- Preserve existing Phase 16A/16B readers by accepting the v1 object-metrics schema while writing v2.
- Work with the existing dirty worktree; stage and commit only files named by each task.

---

## File Structure

- Create `lsprepost_mcp/city_result_source.py`: validate, hash, register, revalidate, and resolve city result directories.
- Create `tests/test_city_result_source.py`: result-source contract and tamper regression tests.
- Modify `lsprepost_mcp/solver_results.py`: pressure impulse and post-FSI object response metrics.
- Modify `tests/test_solver_results.py`: parser red/green tests.
- Modify `lsprepost_mcp/city_impact.py`: source-aware quality checks, metrics v2, assessment states, and report rendering.
- Modify `tests/test_city_impact.py`: source-aware assessment and report tests.
- Modify `lsprepost_mcp/web/city_impact_api.py`: native selection, registration, analysis, and report payloads.
- Modify `lsprepost_mcp/web/app.py`: new API route.
- Modify `tests/test_web_api.py`: endpoint validation.
- Modify `lsprepost_mcp/web/static/index.html`: result source and assessment panels.
- Modify `lsprepost_mcp/web/static/app.js`: select/register/read/render actions.
- Modify `lsprepost_mcp/web/static/styles.css`: compact assessment tables and gate states.
- Modify `tests/test_web_static.py`: static Web contract.
- Modify `docs/reviews/city-street/CITY_STREET_BLAST_SCENE.zh-CN.md`: operator workflow and interpretation boundary.

---

### Task 1: Controlled External Result Registration

**Files:**
- Create: `lsprepost_mcp/city_result_source.py`
- Create: `tests/test_city_result_source.py`

**Interfaces:**
- Produces: `register_city_result_source(project: Path, result_dir: Path) -> JSONDict`
- Produces: `resolve_city_result_source(project: Path) -> JSONDict`
- Produces: `validate_city_result_source(project: Path, record: JSONDict) -> JSONDict`
- Produces: `CITY_RESULT_SOURCE_SCHEMA_VERSION = "phase17.city_result_source.v1"`

- [ ] **Step 1: Write failing registration and source-priority tests**

```python
class CityResultSourceTests(unittest.TestCase):
    def test_registers_matching_external_result_without_copying_d3plot(self):
        record = register_city_result_source(self.project, self.result)
        self.assertEqual("registered_external", record["source_kind"])
        self.assertEqual(self.model_hash, record["model_sha256"])
        self.assertIn("d3plot01", record["evidence"])
        self.assertFalse((self.project / "d3plot01").exists())

    def test_rejects_result_with_different_model_hash(self):
        (self.result / "model.k").write_text("*KEYWORD\n$changed\n*END\n")
        with self.assertRaisesRegex(ValueError, "model.k hash"):
            register_city_result_source(self.project, self.result)

    def test_prefers_valid_internal_solver_run_over_registered_external_result(self):
        self._write_completed_internal_run()
        register_city_result_source(self.project, self.result)
        resolved = resolve_city_result_source(self.project)
        self.assertEqual("solver_run", resolved["source_kind"])
```

- [ ] **Step 2: Run registration tests and verify RED**

Run:

```powershell
python -m unittest tests.test_city_result_source -v
```

Expected: import failure because `city_result_source` does not exist.

- [ ] **Step 3: Implement path, model, output, sequence, and semantic validation**

Implement:

```python
CITY_RESULT_SOURCE_SCHEMA_VERSION = "phase17.city_result_source.v1"
REQUIRED_TEXT_OUTPUTS = ("d3hsp", "dbfsi", "glstat", "elout", "nodout")

def register_city_result_source(project: Path, result_dir: Path) -> JSONDict:
    project = project.resolve()
    result = result_dir.resolve()
    _require_city_model(project)
    _require_city_model(result)
    _require_matching_model_contract(project, result)
    evidence = _build_result_evidence(result)
    record = {
        "schema_version": CITY_RESULT_SOURCE_SCHEMA_VERSION,
        "source_kind": "registered_external",
        "project_name": project.name,
        "result_dir": str(result),
        "model_sha256": _sha256(result / "model.k"),
        "model_json_sha256": _sha256(result / "model.json"),
        "evidence": evidence,
        "registered_at": _utc_now(),
        "registered_by": "lsprepost_mcp.web",
    }
    _atomic_write_record(project, record)
    return {**record, "validation": {"ok": True, "issues": []}}
```

Evidence must include all required text outputs and the continuous sorted
`d3plot`, `d3plot01`, ... sequence. Hash files in 1 MiB chunks.

- [ ] **Step 4: Add tamper and stale-record tests**

```python
def test_registered_output_change_is_invalid_evidence(self):
    record = register_city_result_source(self.project, self.result)
    (self.result / "dbfsi").write_text("changed\n", encoding="utf-8")
    validation = validate_city_result_source(self.project, record)
    self.assertFalse(validation["ok"])
    self.assertIn("dbfsi", validation["changed_files"])

def test_invalid_new_registration_preserves_previous_record(self):
    first = register_city_result_source(self.project, self.result)
    (self.other_result / "nodout").unlink()
    with self.assertRaisesRegex(ValueError, "nodout"):
        register_city_result_source(self.project, self.other_result)
    self.assertEqual(first["result_dir"], read_json(self.record_path)["result_dir"])
```

- [ ] **Step 5: Run Task 1 tests and commit**

Run:

```powershell
python -m unittest tests.test_city_result_source -v
python -m compileall -q lsprepost_mcp/city_result_source.py
```

Commit:

```powershell
git add lsprepost_mcp/city_result_source.py tests/test_city_result_source.py
git commit -m "feat: register city solver result sources"
```

---

### Task 2: Pressure Impulse and Noise-Resistant Object Causality

**Files:**
- Modify: `lsprepost_mcp/solver_results.py`
- Modify: `tests/test_solver_results.py`

**Interfaces:**
- Extends: `parse_dbfsi(text: str) -> JSONDict`
- Extends: `parse_city_object_responses(dbfsi_text, elout_text, nodout_text, response_objects) -> dict[str, JSONDict]`
- Produces per surface: `positive_pressure_impulse_pa_s`
- Produces per object: pre-arrival peaks, post-arrival peaks, signal-to-noise ratio, consecutive-sample arrival, and `pre_arrival_quiet`

- [ ] **Step 1: Write failing pressure-impulse test**

```python
def test_parse_dbfsi_integrates_positive_pressure_rise(self):
    parsed = parse_dbfsi(
        "time=0\n111 0 0 0 0 0\n"
        "time=0.001\n111 1000 0 0 0 0\n"
        "time=0.002\n111 0 0 0 0 0\n"
    )
    self.assertAlmostEqual(
        1.0,
        parsed["surfaces"][0]["positive_pressure_impulse_pa_s"],
    )
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```powershell
python -m unittest tests.test_solver_results.SolverResultTests.test_parse_dbfsi_integrates_positive_pressure_rise -v
```

Expected: missing `positive_pressure_impulse_pa_s`.

- [ ] **Step 3: Implement trapezoidal positive-pressure integration**

Inside `_dbfsi_surface_metrics`, subtract the first pressure as baseline and
integrate `max(pressure - baseline, 0.0)`:

```python
pressure_impulse = sum(
    0.5 * (left_rise + right_rise) * (right_time - left_time)
    for (left_time, left_rise), (right_time, right_rise)
    in pairwise(positive_pressure_history)
)
```

Return the value as `positive_pressure_impulse_pa_s`. Keep
`fsi_impulse_magnitude_n_s` unchanged.

- [ ] **Step 4: Write failing pre-arrival-noise and consecutive-sample tests**

```python
def test_city_response_does_not_treat_single_early_noise_sample_as_arrival(self):
    result = parse_city_object_responses(
        dbfsi_with_arrival_at_2ms,
        elout_with_early_1pa_noise_and_two_500pa_post_arrival_states,
        nodout_history,
        response_objects,
    )["building"]
    self.assertTrue(result["pre_arrival_quiet"])
    self.assertEqual(0.002, result["structural_arrival_time_s"])
    self.assertEqual(500.0, result["post_arrival_peak_structural_pressure_pa"])

def test_city_response_flags_material_pre_arrival_response(self):
    result = parse_city_object_responses(
        dbfsi_with_arrival_at_2ms,
        elout_with_1000pa_pre_arrival_and_500pa_post_arrival,
        nodout_history,
        response_objects,
    )["building"]
    self.assertFalse(result["pre_arrival_quiet"])
    self.assertIsNone(result["structural_arrival_time_s"])
```

- [ ] **Step 5: Run causality tests and verify RED**

Run:

```powershell
python -m unittest tests.test_solver_results.SolverResultTests.test_city_response_does_not_treat_single_early_noise_sample_as_arrival tests.test_solver_results.SolverResultTests.test_city_response_flags_material_pre_arrival_response -v
```

Expected: missing new fields or old `1e-12` arrival behavior.

- [ ] **Step 6: Implement per-state aggregation and causality diagnostics**

For each object:

- aggregate maximum absolute pressure and principal stress by state time;
- compute pre-FSI peaks;
- compute post-FSI peaks;
- set quiet limits to `max(100 Pa, 5% of the post-arrival peak)`;
- require pre-arrival peaks not to exceed their quiet limits;
- require two consecutive post-arrival states exceeding `100 Pa`;
- preserve all-run peak fields for backward compatibility;
- add `post_arrival_observation_s`.

- [ ] **Step 7: Run parser suite and commit**

Run:

```powershell
python -m unittest tests.test_solver_results -v
python -m compileall -q lsprepost_mcp/solver_results.py
```

Commit:

```powershell
git add lsprepost_mcp/solver_results.py tests/test_solver_results.py
git commit -m "fix: harden city object response causality"
```

---

### Task 3: Source-Aware Assessment and Metrics v2

**Files:**
- Modify: `lsprepost_mcp/city_impact.py`
- Modify: `tests/test_city_impact.py`

**Interfaces:**
- Consumes: `resolve_city_result_source(project) -> JSONDict`
- Consumes: extended `parse_city_object_responses(...)`
- Produces: `CITY_METRICS_SCHEMA_VERSION = "phase17.city_object_metrics.v2"`
- Produces: `build_city_impact_assessment(project_path: Path) -> JSONDict`
- Produces assessment fields: `response_acceptance`, `result_source`, `anomalies`

- [ ] **Step 1: Write failing spaced-termination and source-resolution tests**

```python
def test_assessment_accepts_spaced_normal_termination(self):
    self._write_d3hsp("N o r m a l    t e r m i n a t i o n")
    result = build_city_impact_assessment(self.project)
    self.assertNotIn(
        "solver.normal_termination",
        result["quality"]["blocking_check_ids"],
    )

def test_assessment_reads_registered_result_instead_of_project_root(self):
    register_city_result_source(self.project, self.external_result)
    result = build_city_impact_assessment(self.project)
    self.assertEqual("registered_external", result["result_source"]["source_kind"])
    self.assertEqual(1.0, result["quality"]["global_metrics"]["time_coverage_ratio"])
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
python -m unittest tests.test_city_impact.CityImpactAssessmentTests.test_assessment_accepts_spaced_normal_termination tests.test_city_impact.CityImpactAssessmentTests.test_assessment_reads_registered_result_instead_of_project_root -v
```

Expected: spaced normal termination remains blocked and external source is ignored.

- [ ] **Step 3: Resolve source once and use it for all quality readers**

Change `_result_quality` to accept `result_dir`. Match spaced normal termination
with whitespace-tolerant logic or reuse `parse_d3hsp`. Aggregate global DBFSI
metrics from `dbfsi["surfaces"]`:

```python
global_fsi = {
    "surface_count": parsed["surface_count"],
    "state_count": parsed["state_count"],
    "peak_pressure_rise_pa": max(
        surface["peak_pressure_rise_pa"] for surface in parsed["surfaces"]
    ),
    "positive_pressure_impulse_pa_s": sum(
        surface["positive_pressure_impulse_pa_s"] for surface in parsed["surfaces"]
    ),
}
```

- [ ] **Step 4: Write failing v2 metrics and acceptance tests**

```python
def test_assessment_builds_object_metrics_from_registered_result(self):
    register_city_result_source(self.project, self.external_result)
    result = build_city_impact_assessment(self.project)
    building = self._object(result, "commercial_supermarket")
    self.assertTrue(building["metrics"]["peak_fsi_pressure_rise_pa"]["available"])
    self.assertTrue(building["metrics"]["peak_structural_pressure_pa"]["available"])
    self.assertTrue(building["metrics"]["peak_principal_stress_pa"]["available"])
    self.assertEqual("unavailable", building["risk"]["level"])

def test_partial_acceptance_when_one_object_has_short_observation_window(self):
    self._write_object_result(post_arrival_observation_s=0.016)
    result = build_city_impact_assessment(self.project)
    self.assertEqual("partial", result["response_acceptance"]["status"])
    self.assertIn(
        "residential_community.observation_window",
        result["response_acceptance"]["blocking_check_ids"],
    )
```

- [ ] **Step 5: Run v2 tests and verify RED**

Run:

```powershell
python -m unittest tests.test_city_impact.CityImpactAssessmentTests.test_assessment_builds_object_metrics_from_registered_result tests.test_city_impact.CityImpactAssessmentTests.test_partial_acceptance_when_one_object_has_short_observation_window -v
```

Expected: missing v2 metrics and `response_acceptance`.

- [ ] **Step 6: Implement v2 metrics generation and assessment states**

Write `artifacts/city_impact_metrics.json` atomically under a
`city_impact_metrics` lock. Include:

```python
{
    "schema_version": "phase17.city_object_metrics.v2",
    "model_sha256": model_sha256,
    "result_evidence_digest": evidence_digest,
    "source": "lsprepost_mcp.parse_city_object_responses",
    "objects": object_results,
    "threshold_profile": {
        "status": "missing",
        "source": "",
        "limits": {},
    },
}
```

Continue accepting `phase16a.city_object_metrics.v1`. Set:

- numerical response `passed/partial/failed` independently;
- engineering risk `unavailable` without a trusted profile;
- normalized displacement anomaly when displacement exceeds 2% of the
  largest object bound dimension for `street_equipment`, or 5% for buildings
  and other objects. These are model-sanity warnings, not failure criteria.

- [ ] **Step 7: Run assessment suite and commit**

Run:

```powershell
python -m unittest tests.test_city_impact -v
python -m compileall -q lsprepost_mcp/city_impact.py
```

Commit:

```powershell
git add lsprepost_mcp/city_impact.py tests/test_city_impact.py
git commit -m "feat: build source-aware city impact assessments"
```

---

### Task 4: Web Registration and Analysis API

**Files:**
- Modify: `lsprepost_mcp/web/city_impact_api.py`
- Modify: `lsprepost_mcp/web/app.py`
- Modify: `tests/test_web_api.py`

**Interfaces:**
- Produces: `select_city_result_source_payload(payload: JSONDict) -> JSONDict`
- Produces POST: `/api/project/city-impact/select-result`
- Keeps GET: `/api/project/city-impact`
- Keeps POST: `/api/project/city-impact-report`

- [ ] **Step 1: Write failing endpoint tests**

```python
def test_select_city_result_requires_project_name(self):
    status, payload = request_json(
        address,
        "POST",
        "/api/project/city-impact/select-result",
        {},
    )
    self.assertEqual(400, status)
    self.assertEqual("invalid_project_name", payload["error"]["code"])

def test_select_city_result_registers_native_directory(self):
    with patch(
        "lsprepost_mcp.web.city_impact_api.native_choose_directory",
        return_value=self.result,
    ):
        status, payload = request_json(
            address,
            "POST",
            "/api/project/city-impact/select-result",
            {"project_name": self.project.name},
        )
    self.assertEqual(200, status)
    self.assertEqual("registered_external", payload["result"]["source_kind"])
```

- [ ] **Step 2: Run endpoint tests and verify RED**

Run:

```powershell
python -m unittest tests.test_web_api -v
```

Expected: route not found.

- [ ] **Step 3: Implement native selection and route**

Use `native_choose_directory("选择 LS-DYNA 城市求解结果目录")`, normalize
picker cancellation to an `ApiError`, find the workspace project by validated
project name, and call `register_city_result_source`.

- [ ] **Step 4: Run endpoint suite and commit**

Run:

```powershell
python -m unittest tests.test_web_api -v
python -m compileall -q lsprepost_mcp/web
```

Commit:

```powershell
git add lsprepost_mcp/web/city_impact_api.py lsprepost_mcp/web/app.py tests/test_web_api.py
git commit -m "feat: expose city result registration API"
```

---

### Task 5: Assessment Panel and Exported Report

**Files:**
- Modify: `lsprepost_mcp/web/static/index.html`
- Modify: `lsprepost_mcp/web/static/app.js`
- Modify: `lsprepost_mcp/web/static/styles.css`
- Modify: `lsprepost_mcp/city_impact.py`
- Modify: `tests/test_web_static.py`
- Modify: `tests/test_city_impact.py`

**Interfaces:**
- Consumes assessment `result_source`, `quality`, `response_acceptance`,
  `objects`, `anomalies`, and `threshold_profile`
- Preserves object Part highlighting

- [ ] **Step 1: Write failing static contract tests**

```python
def test_city_impact_panel_exposes_result_selection_and_separate_statuses(self):
    html = self.index_html
    js = self.app_js
    self.assertIn('id="selectCityImpactResult"', html)
    self.assertIn('id="cityImpactQuality"', html)
    self.assertIn('id="cityImpactResponseStatus"', html)
    self.assertIn('id="cityImpactRiskStatus"', html)
    self.assertIn("selectCityImpactResult", js)
    self.assertIn("post_arrival_observation_s", js)
```

- [ ] **Step 2: Run static test and verify RED**

Run:

```powershell
python -m unittest tests.test_web_static -v
```

Expected: new controls are absent.

- [ ] **Step 3: Implement compact operational UI**

Add:

- result-source row and “选择求解结果” button;
- solver quality gate list;
- separate numerical-response and engineering-risk statuses;
- one scan-friendly object table with columns for arrival, FSI pressure,
  structural pressure, principal stress, displacement, observation window,
  and acceptance;
- anomaly list and engineering notice.

Use existing risk chips only for threshold-backed engineering risk. Use a
distinct pass/partial/fail state for numerical response.

- [ ] **Step 4: Write failing HTML report content test**

```python
def test_exported_report_contains_source_quality_objects_and_limitations(self):
    report = write_city_impact_report(self.project)
    html = Path(report["html_path"]).read_text(encoding="utf-8")
    self.assertIn("结果来源与证据", html)
    self.assertIn("求解质量门禁", html)
    self.assertIn("对象级数值响应", html)
    self.assertIn("工程风险：无法评估", html)
    self.assertIn("住宅小区", html)
```

- [ ] **Step 5: Run report test and verify RED**

Run:

```powershell
python -m unittest tests.test_city_impact.CityImpactAssessmentTests.test_exported_report_contains_source_quality_objects_and_limitations -v
```

Expected: report lacks the new sections.

- [ ] **Step 6: Implement expanded JSON/HTML report**

Render:

1. source path, registration time, evidence digest, model hashes;
2. solver time, coverage, cycle, energy deviation, termination;
3. global FSI summary;
4. per-object metrics and gate outcomes;
5. anomaly list;
6. numerical-response conclusion;
7. engineering-risk limitation and next actions.

- [ ] **Step 7: Run Web/report suites and commit**

Run:

```powershell
python -m unittest tests.test_web_static tests.test_city_impact -v
```

Commit:

```powershell
git add lsprepost_mcp/web/static/index.html lsprepost_mcp/web/static/app.js lsprepost_mcp/web/static/styles.css lsprepost_mcp/city_impact.py tests/test_web_static.py tests/test_city_impact.py
git commit -m "feat: expand city impact assessment report"
```

---

### Task 6: Register and Analyze the Completed v3 Details Case

**Files:**
- Runtime create: `workspace/projects/web_phase17_city_street_blast_response_v3_details/artifacts/city_result_source.json`
- Runtime create: `workspace/projects/web_phase17_city_street_blast_response_v3_details/artifacts/city_impact_metrics.json`
- Runtime create: `workspace/projects/web_phase17_city_street_blast_response_v3_details/artifacts/city_impact_assessment.json`
- Runtime create: `workspace/projects/web_phase17_city_street_blast_response_v3_details/artifacts/city_impact_report.html`
- Modify: `docs/reviews/city-street/CITY_STREET_BLAST_SCENE.zh-CN.md`

**Interfaces:**
- Consumes external read-only directory:
  `E:\K文件模型\web_phase17_city_street_blast_response_v3_details`
- Produces workspace-only assessment artifacts

- [ ] **Step 1: Capture external input evidence before analysis**

Run:

```powershell
Get-Item -LiteralPath 'E:\K文件模型\web_phase17_city_street_blast_response_v3_details\model.k','E:\K文件模型\web_phase17_city_street_blast_response_v3_details\model.json','E:\K文件模型\web_phase17_city_street_blast_response_v3_details\dbfsi','E:\K文件模型\web_phase17_city_street_blast_response_v3_details\elout','E:\K文件模型\web_phase17_city_street_blast_response_v3_details\nodout' |
  Select-Object FullName,Length,LastWriteTime
```

Save the displayed values in the task log; do not write to the external folder.

- [ ] **Step 2: Register and build the assessment**

Run:

```powershell
python -c "from pathlib import Path; from lsprepost_mcp.city_result_source import register_city_result_source; from lsprepost_mcp.city_impact import write_city_impact_report; p=Path(r'E:\workplace\codex_mcp_k\workspace\projects\web_phase17_city_street_blast_response_v3_details'); r=Path(r'E:\K文件模型\web_phase17_city_street_blast_response_v3_details'); print(register_city_result_source(p,r)); print(write_city_impact_report(p))"
```

Expected: source validation passes and report status is `partial` unless the
new causality metrics prove a stronger blocker.

- [ ] **Step 3: Assert case facts without forcing a pass**

Run:

```powershell
python -c "import json; from pathlib import Path; p=Path(r'E:\workplace\codex_mcp_k\workspace\projects\web_phase17_city_street_blast_response_v3_details\artifacts\city_impact_assessment.json'); r=json.loads(p.read_text(encoding='utf-8')); assert r['quality']['global_metrics']['time_coverage_ratio'] >= .99; assert r['threshold_profile']['status'] == 'missing'; assert all(any(metric.get('available') for metric in obj['metrics'].values()) for obj in r['objects'] if obj['object_id'] in {'commercial_supermarket','residential_community','subway_entrance','traffic_light_1'}); print(r['response_acceptance']['status']); print(r['response_acceptance']['blocking_check_ids'])"
```

- [ ] **Step 4: Verify external result files were not modified**

Repeat Step 1 and compare size and `LastWriteTime` for every listed file.

- [ ] **Step 5: Document operator workflow and case limitations**

Add exact Web steps and the case conclusion to
`docs/reviews/city-street/CITY_STREET_BLAST_SCENE.zh-CN.md`. State that
residential observation length, causality noise, and traffic-light response
remain visible blockers when present.

- [ ] **Step 6: Commit documentation only**

```powershell
git add docs/reviews/city-street/CITY_STREET_BLAST_SCENE.zh-CN.md
git commit -m "docs: explain city impact assessment workflow"
```

Runtime artifacts remain ignored and are not committed.

---

### Task 7: Full Regression and Visual Verification

**Files:**
- No production changes unless a failing test identifies a defect

**Interfaces:**
- Verifies all previous task outputs together

- [ ] **Step 1: Run focused Python suites**

```powershell
python -m unittest tests.test_city_result_source tests.test_solver_results tests.test_city_impact tests.test_web_api tests.test_web_static -v
```

- [ ] **Step 2: Run the full Python suite**

```powershell
python -m unittest discover -s tests
```

Expected: zero failures; existing environment-dependent tests may remain
explicitly skipped.

- [ ] **Step 3: Compile production modules**

```powershell
python -m compileall -q lsprepost_mcp
```

- [ ] **Step 4: Run Web frontend contract and E2E tests**

```powershell
powershell -ExecutionPolicy Bypass -File scripts/test_phase17_web.ps1
```

- [ ] **Step 5: Start the Web server on a free local port**

Use the repository's existing Web start command. If the default port is
occupied, choose another free port and record it.

- [ ] **Step 6: Verify the assessment panel in Playwright**

At desktop and mobile viewport widths:

- select `web_phase17_city_street_blast_response_v3_details`;
- open “影响评估”;
- verify result source, quality summary, response status, risk limitation,
  object table, and anomaly list are visible without overlap;
- click commercial supermarket and verify Part 19 highlighting;
- export the report and verify the success summary;
- capture screenshots.

- [ ] **Step 7: Inspect final diff and evidence**

```powershell
git diff --check
git status --short
```

Confirm unrelated user changes were not reverted or staged.

- [ ] **Step 8: Report the real case conclusion**

Report measured values, every blocking gate, generated report paths, tests,
and the local Web URL. Do not claim engineering safety or final city-model
acceptance when thresholds or object gates remain unavailable.
