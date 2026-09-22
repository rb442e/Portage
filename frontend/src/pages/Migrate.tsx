import { Fragment, useEffect, useRef, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { api, type MigrationRequest, type BatchMigrationRequest } from "../api";
import { useApp } from "../store";
import type { BatchUploadItem, ExportResult, JobStatus, LookupTable, MappingTemplate, MappingValidation, ParentMapResult, PreviewResult } from "../types";

const STEPS = ["Upload", "Transform", "Preview", "Migrate"];
const BATCH_TYPES = ["Epic", "Feature", "User Story", "Task", "Defect"];

// Human-traceable id that correlates a whole workflow (preview → export → run).
function newMigrationId(): string {
  const d = new Date();
  const ymd = `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, "0")}${String(d.getDate()).padStart(2, "0")}`;
  return `MIG-${ymd}-${Math.random().toString(16).slice(2, 8).toUpperCase()}`;
}

// The in-progress workflow is persisted so leaving/reloading resumes where you
// left off; it is cleared only on an explicit "New Migration".
const WF_KEY = "portage.migrate.v1";
function readWorkflow(): any | null {
  try { const raw = localStorage.getItem(WF_KEY); return raw ? JSON.parse(raw) : null; }
  catch { return null; }
}

const svgIcon = { fill: "none", stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
const UploadIcon = () => (<svg viewBox="0 0 24 24" {...svgIcon}><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><path d="M7 10l5-5 5 5M12 5v12" /></svg>);
const FileCheckIcon = () => (<svg viewBox="0 0 24 24" {...svgIcon}><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><path d="M14 2v6h6M9 15l2 2 4-4" /></svg>);

// Canonical source types Portage emits, with sensible default Jira targets.
const NORMALIZED_TYPES = ["Epic", "Feature", "Story", "User Story", "Task", "Sub-task", "Bug", "Defect", "Test Case", "Test Set"];
const DEFAULT_TYPE_TARGET: Record<string, string> = {
  Epic: "Epic", Feature: "Feature", Story: "Story", "User Story": "Story",
  Task: "Sub-task", "Sub-task": "Sub-task", Bug: "Bug", Defect: "Bug",
  "Test Case": "Test", "Test Set": "Test",
};

// The Jira fields Portage can populate, shown like Jira's Bulk Create mapping
// screen. `candidates` drive auto-matching against the uploaded columns;
// `transform` is applied automatically for multi-value / numeric fields.
const TARGET_FIELDS: { field: string; label: string; transform?: string; candidates: string[] }[] = [
  { field: "issue_type", label: "Issue Type", candidates: ["Issue Type", "Type", "Work Item Type"] },
  { field: "summary", label: "Summary", candidates: ["Summary", "Name", "Title"] },
  { field: "description", label: "Description", candidates: ["Description", "Notes"] },
  { field: "status", label: "Status", candidates: ["Status", "Schedule State", "ScheduleState", "State"] },
  { field: "priority", label: "Priority", candidates: ["Priority", "Severity"] },
  { field: "assignee", label: "Assignee", candidates: ["Assignee", "Owner", "Owner Email"] },
  { field: "reporter", label: "Reporter", candidates: ["Reporter", "Submitted By", "Created By", "Creator"] },
  { field: "labels", label: "Labels", transform: "labels", candidates: ["Labels", "Tags"] },
  { field: "components", label: "Components", transform: "labels", candidates: ["Components", "Component"] },
  { field: "sprint", label: "Sprint", candidates: ["Sprint", "Iteration Name", "Iteration name", "Iteration"] },
  { field: "story_points", label: "Story Points", transform: "number", candidates: ["Story Points", "Plan Estimate", "PlanEstimate"] },
  { field: "team", label: "Team", candidates: ["Team", "Contributing Teams"] },
  { field: "fix_versions", label: "Fix Version/s", transform: "labels", candidates: ["Fix Version/s", "Fix Versions", "Release", "Milestones"] },
  { field: "start_date", label: "Start Date", candidates: ["Start Date", "Opened Date"] },
  { field: "due_date", label: "Due Date", candidates: ["Due Date", "Planned End Date", "Target Date"] },
  { field: "row_id", label: "Issue Id (hierarchy)", candidates: ["Issue Id", "Formatted ID", "FormattedID"] },
  { field: "parent_row_id", label: "Parent Id (hierarchy)", candidates: ["Parent Id", "Parent", "Parent Feature"] },
  { field: "external_id", label: "Rally ID", candidates: ["Rally ID", "Formatted ID", "FormattedID"] },
  { field: "links", label: "Issue Links", transform: "labels", candidates: ["Issue Links", "Link", "Links"] },
];

const _norm = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, "");

// Best-guess Jira field for each uploaded source column (first matching field
// in TARGET_FIELDS order wins, so e.g. "Formatted ID" -> row_id).
function autoMatch(columns: string[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const col of columns) {
    const ncol = _norm(col);
    for (const t of TARGET_FIELDS) {
      if (t.candidates.some((c) => _norm(c) === ncol)) { out[col] = t.field; break; }
    }
  }
  return out;
}

export default function Migrate() {
  const { jira, rally, source, setSource, jiraVerified } = useApp();
  const navigate = useNavigate();
  const [savedInit] = useState(readWorkflow);   // snapshot captured once at mount
  const [step, setStep] = useState<number>(() => savedInit?.step ?? 0);
  const [inputMode, setInputMode] = useState<"single" | "batch">(() => savedInit?.inputMode ?? "single");
  const [mappings, setMappings] = useState<MappingTemplate[]>([]);
  const [mappingId, setMappingId] = useState<number | null>(() => savedInit?.mappingId ?? null);
  const [artifactTypes, setArtifactTypes] = useState<string[]>([]);
  const [forceType, setForceType] = useState<string>(() => savedInit?.forceType ?? "");
  const [colMap, setColMap] = useState<Record<string, string>>({});
  const [saveMsg, setSaveMsg] = useState("");
  const [lookups, setLookups] = useState<LookupTable[]>([]);
  const [lookupIds, setLookupIds] = useState<number[]>(() => savedInit?.lookupIds ?? []);
  const [includeAttachments, setIncludeAttachments] = useState<boolean>(() => savedInit?.includeAttachments ?? true);
  const [typeMap, setTypeMap] = useState<Record<string, string>>(() => savedInit?.typeMap ?? {});
  const [preview, setPreview] = useState<PreviewResult | null>(() => savedInit?.preview ?? null);
  const [exportResult, setExportResult] = useState<ExportResult | null>(() => savedInit?.exportResult ?? null);
  const [exporting, setExporting] = useState(false);
  const [job, setJob] = useState<JobStatus | null>(() => savedInit?.job ?? null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [validation, setValidation] = useState<MappingValidation | null>(null);
  const [migrationId, setMigrationId] = useState<string>(() => savedInit?.migrationId ?? newMigrationId());
  const [parentMap, setParentMap] = useState<ParentMapResult | null>(() => savedInit?.parentMap ?? null);
  const [parentBusy, setParentBusy] = useState(false);
  const parentInputRef = useRef<HTMLInputElement | null>(null);
  const [splitEnabled, setSplitEnabled] = useState<boolean>(() => savedInit?.splitEnabled ?? false);
  const [splitRows, setSplitRows] = useState<number>(() => savedInit?.splitRows ?? 210);
  const poll = useRef<number | null>(null);

  useEffect(() => {
    api.listMappings().then(setMappings).catch(() => {});
    api.artifactTypes().then(setArtifactTypes).catch(() => {});
    api.listLookups().then((l) => {
      setLookups(l);
      if (!savedInit) setLookupIds(l.map((x) => x.id!).filter(Boolean));  // default-select all only for a fresh migration
    }).catch(() => {});
    // Resume a run that was mid-flight when the user navigated away, and rehydrate
    // the uploaded source into the app store after a full reload.
    if (savedInit?.source && !source) setSource(savedInit.source);
    if (savedInit?.job && savedInit.job.state === "running") startPolling(savedInit.job.job_id);
    return () => { if (poll.current) window.clearInterval(poll.current); };
  }, []);  // eslint-disable-line react-hooks/exhaustive-deps

  // Persist the workflow so it survives navigation + reload (until New Migration).
  useEffect(() => {
    const snap = { migrationId, step, inputMode, source, mappingId, forceType,
                   lookupIds, includeAttachments, typeMap, preview, exportResult, job, parentMap,
                   splitEnabled, splitRows };
    try {
      localStorage.setItem(WF_KEY, JSON.stringify(snap));
    } catch {
      // Drop the heavy parts if we hit the storage quota.
      try { localStorage.setItem(WF_KEY, JSON.stringify({ ...snap, preview: null, job: job ? { ...job, log: [] } : null })); }
      catch { /* give up silently */ }
    }
  }, [migrationId, step, inputMode, source, mappingId, forceType, lookupIds,
      includeAttachments, typeMap, preview, exportResult, job, parentMap, splitEnabled, splitRows]);

  function startPolling(jobId: string) {
    if (poll.current) window.clearInterval(poll.current);
    poll.current = window.setInterval(async () => {
      try {
        const j = await api.job(jobId);
        setJob(j);
        if (j.state === "done" || j.state === "failed") { if (poll.current) window.clearInterval(poll.current); }
      } catch { /* keep polling */ }
    }, 1200);
  }

  // The single explicit reset: wipe the persisted workflow and start fresh.
  function newMigration() {
    if (poll.current) window.clearInterval(poll.current);
    try { localStorage.removeItem(WF_KEY); } catch { /* ignore */ }
    setSource(null); setStep(0); setJob(null); setPreview(null);
    setExportResult(null); setValidation(null); setForceType(""); setError("");
    setParentMap(null);
    setMigrationId(newMigrationId());
  }

  async function onUploadParentMap(file: File) {
    setParentBusy(true); setError("");
    try { setParentMap(await api.uploadParentMap(file)); }
    catch (e: any) { setError(e.message); }
    finally { setParentBusy(false); }
  }

  // Guard the top-level action: confirm only when there is work to lose.
  function handleNewMigration() {
    const inProgress = !!(source || preview || exportResult || job);
    if (inProgress && !window.confirm(
      `Start a new migration?\n\nThe current migration ${migrationId} will be cleared from this screen. Any files you already generated remain available in Exports.`
    )) return;
    newMigration();
  }

  const selectedTemplate = mappings.find((m) => m.id === mappingId) ?? null;
  // Raw Rally exports have no Issue Type column, so a work-item type is required.
  const needsType = source?.kind === "rally_export";
  const mappingName = selectedTemplate?.name ?? "Default (rally_to_jira)";
  // Furthest step reachable given the work done so far — drives free navigation.
  const reached = (job || exportResult) ? 3 : preview ? 2 : source ? 1 : 0;
  const migStatus = job
    ? (job.state === "done" ? "Created in Jira" : job.state === "failed" ? "Run failed"
      : job.state === "running" ? "Creating…" : "Queued")
    : exportResult ? "Files exported"
    : preview ? "Previewed"
    : source ? "In progress"
    : "New";
  const migStatusClass = (job?.state === "done" || exportResult) ? "done"
    : (source || preview || job) ? "active" : "";

  // AWS "Launch instance"-style sticky summary shared across every step.
  const summaryPanel = (footer: ReactNode, extra?: ReactNode) => (
    <div className="aws-summary">
      <div className="aws-summary-head">Summary</div>
      <div className="aws-summary-body">
        <div className="aws-sum-row"><span className="k">Migration ID</span><span className="v"><code>{migrationId}</code></span></div>
        <div className="aws-sum-row"><span className="k">Source</span><span className="v" title={source?.filename}>{source?.filename ?? "—"}</span></div>
        <div className="aws-sum-row"><span className="k">Rows</span><span className="v">{source?.row_count ?? "—"}</span></div>
        <div className="aws-sum-row"><span className="k">Mapping</span><span className="v" title={mappingName}>{mappingName}</span></div>
        <div className="aws-sum-row"><span className="k">Work-item type</span><span className={`v ${needsType && !forceType ? "warn" : ""}`}>{forceType || (needsType ? "Required" : "Auto")}</span></div>
        <div className="aws-sum-row"><span className="k">Catalogs</span><span className="v">{lookupIds.length} of {lookups.length}</span></div>
        <div className="aws-sum-row"><span className="k">Attachments</span><span className="v">{includeAttachments ? "On" : "Off"}</span></div>
        <div className="aws-sum-row"><span className="k">Parent map</span><span className="v">{parentMap ? `${parentMap.count} parents` : "—"}</span></div>
        {extra}
      </div>
      <div className="aws-summary-foot">{footer}</div>
    </div>
  );

  const buildReq = (dry: boolean): MigrationRequest => ({
    source_id: source!.source_id,
    jira,
    rally: rally.api_key ? rally : null,
    mapping_id: mappingId,
    mapping: null,                       // always use a saved Studio template by reference
    force_type: forceType || null,
    lookup_ids: lookupIds,
    type_map: Object.fromEntries(Object.entries(typeMap).filter(([, v]) => v)),
    include_attachments: includeAttachments,
    dry_run: dry,
    migration_id: migrationId,
    parent_map_id: parentMap?.parent_map_id ?? null,
    split_rows: splitEnabled ? (splitRows > 0 ? splitRows : 210) : 0,
  });

  async function onUpload(file: File) {
    setBusy(true); setError("");
    try {
      const s = await api.uploadSource(file);
      setSource(s);
      setStep(1);
    } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  }

  function removeSource() {
    setSource(null);
    setStep(0);
    setPreview(null);
    setExportResult(null);
    setValidation(null);
    setForceType("");
    setError("");
  }

  async function runPreview() {
    setBusy(true); setError("");
    try {
      // Block until every Jira-ID-dependent value resolves via the catalog.
      const v = await api.validate(buildReq(true));
      setValidation(v);
      if (!v.ok) { window.scrollTo({ top: 0, behavior: "smooth" }); return; }
      setPreview(await api.preview(buildReq(true)));
      setExportResult(null);
      setStep(2);
    } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  }

  async function runExport() {
    setExporting(true); setError("");
    try {
      const res = await api.export(buildReq(false));
      setJob(null);
      setExportResult(res);
      setStep(3);
    } catch (e: any) { setError(e.message); } finally { setExporting(false); }
  }

  async function runMigration() {
    setBusy(true); setError("");
    try {
      const started = await api.run(buildReq(false));
      setJob(started);
      setStep(3);
      startPolling(started.job_id);
    } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  }

  return (
    <>
      <div className="mig-header">
        <div className="mig-header-info">
          <span className="mig-id">Migration ID <code>{migrationId}</code></span>
          <span className={`mig-status ${migStatusClass}`}>{migStatus}</span>
        </div>
        <button className="btn ghost" onClick={handleNewMigration}>+ New Migration</button>
      </div>
      <div className="seg" style={{ marginBottom: 18 }}>
        <button className={inputMode === "single" ? "active" : ""} onClick={() => setInputMode("single")}>Single export file</button>
        <button className={inputMode === "batch" ? "active" : ""} onClick={() => setInputMode("batch")}>Per-type Rally files</button>
      </div>

      {inputMode === "batch" ? <BatchFlow /> : (
      <>
      <WorkflowSteps current={step} reached={reached} onStep={setStep} />

      {error && <div className="callout warn" style={{ marginBottom: 16 }}>⚠ {error}</div>}
      {validation && <ValidationPanel v={validation} />}

      {step === 0 && (
        <UploadStep busy={busy} onUpload={onUpload} source={source} onRemove={removeSource}
          summary={summaryPanel(
            <>
              <button className="btn primary" onClick={() => setStep(1)} disabled={!source}>Continue</button>
            </>
          )} />
      )}

      {step === 1 && (
        <div className="aws-layout">
          <div className="aws-main">
            <div className="aws-section">
              <div className="aws-section-head"><span className="n">1</span><h3>Source export</h3></div>
              <div className="aws-section-body">
                {source ? (
                  <div className="wf-file">
                    <div className="wf-file-ico"><FileCheckIcon /></div>
                    <div className="wf-file-meta">
                      <strong>{source.filename}</strong><br />
                      <span>{source.row_count} rows · {source.columns.length} columns · {source.kind === "jira_all_issues" ? "converted Jira export" : "raw Rally export"}</span>
                    </div>
                    <button className="btn sm ghost" onClick={removeSource}>Remove</button>
                  </div>
                ) : <p className="muted">No file uploaded.</p>}
              </div>
            </div>

            <div className="aws-section">
              <div className="aws-section-head"><span className="n">2</span><h3>Field mapping</h3></div>
              <div className="aws-section-body">
                <div className="grid cols-2">
                  <div className="field">
                    <label>Mapping</label>
                    <select value={mappingId ?? ""} onChange={(e) => setMappingId(e.target.value ? Number(e.target.value) : null)}>
                      <option value="">Default (Auto-map from rally_to_jira)</option>
                      {mappings.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
                    </select>
                  </div>
                  <div className="field">
                    <label>Source work-item type {needsType && <span style={{ color: "var(--danger)" }}>*</span>}</label>
                    <select value={forceType} onChange={(e) => setForceType(e.target.value)}
                      style={needsType && !forceType ? { borderColor: "var(--danger)" } : undefined}>
                      <option value="">{needsType ? "— Select a work-item type —" : "Auto (from Issue Type column)"}</option>
                      {artifactTypes.map((t) => <option key={t} value={t}>{t}</option>)}
                    </select>
                  </div>
                </div>
                {selectedTemplate && (
                  <div className="callout" style={{ marginTop: 4 }}>
                    Transforming with <strong>{selectedTemplate.name}</strong> — its per-type field mapping and data types are applied. Edit it in the <strong>Mapping Studio</strong>.
                  </div>
                )}
              </div>
            </div>

            <div className="aws-section">
              <div className="aws-section-head"><span className="n">3</span><h3>Jira Catalog value mappings</h3></div>
              <div className="aws-section-body">
                {lookups.length > 0 ? (
                  <>
                    {lookups.map((lk) => {
                      const on = lookupIds.includes(lk.id!);
                      return (
                        <label key={lk.id} className="row" style={{ fontWeight: 400, marginBottom: 6 }}>
                          <input type="checkbox" style={{ width: "auto" }} checked={on}
                            onChange={(e) => setLookupIds(e.target.checked
                              ? [...lookupIds, lk.id!]
                              : lookupIds.filter((x) => x !== lk.id))} />
                          <span className="badge neutral">{lk.kind}</span> {lk.name}
                          <span className="muted">· {Object.keys(lk.entries).length} entries</span>
                        </label>
                      );
                    })}
                  </>
                ) : <p className="muted">No catalogs yet. Import lookup tables on the Jira Catalog tab.</p>}
              </div>
            </div>

            <div className="aws-section">
              <div className="aws-section-head"><span className="n">4</span><h3>Parent linking <span className="muted" style={{ fontWeight: 400, fontSize: 13 }}>· optional, applied last</span></h3></div>
              <div className="aws-section-body">
                <p className="card-sub" style={{ marginTop: 0 }}>
                  Upload a <code>parent.csv</code> (Rally ID → Jira Issue id) to resolve each work item's
                  <strong> Parent Id</strong> to the parent's real Jira issue — a VLOOKUP applied when files are generated.
                </p>
                {!parentMap ? (
                  <div className="wf-drop" onClick={() => parentInputRef.current?.click()}
                    onDragOver={(e) => e.preventDefault()}
                    onDrop={(e) => { e.preventDefault(); const f = e.dataTransfer.files?.[0]; if (f) onUploadParentMap(f); }}>
                    <input ref={parentInputRef} type="file" accept=".csv" style={{ display: "none" }}
                      onChange={(e) => { const f = e.target.files?.[0]; if (f) onUploadParentMap(f); }} />
                    <div className="wf-drop-ico"><UploadIcon /></div>
                    <div className="wf-drop-text">
                      <strong>{parentBusy ? "Reading…" : "Drop parent.csv here, or click to browse"}</strong>
                      <span>Columns like “Custom field (Rally ID)” and “Issue id”</span>
                    </div>
                    <button type="button" className="btn wf-drop-cta" onClick={(e) => { e.stopPropagation(); parentInputRef.current?.click(); }}>Browse</button>
                  </div>
                ) : (
                  <div className="wf-file">
                    <div className="wf-file-ico"><FileCheckIcon /></div>
                    <div className="wf-file-meta">
                      <strong>{parentMap.filename}</strong><br />
                      <span><b>{parentMap.count}</b> parents · “{parentMap.key_column}” → “{parentMap.value_column}”</span>
                    </div>
                    <button className="btn sm ghost" onClick={() => setParentMap(null)}>Remove</button>
                  </div>
                )}
              </div>
            </div>

            <div className="aws-section">
              <div className="aws-section-head"><span className="n">5</span><h3>Export options <span className="muted" style={{ fontWeight: 400, fontSize: 13 }}>· CSV files</span></h3></div>
              <div className="aws-section-body">
                <label className="row" style={{ fontWeight: 400 }}>
                  <input type="checkbox" style={{ width: "auto" }} checked={splitEnabled}
                    onChange={(e) => setSplitEnabled(e.target.checked)} />
                  Split large per-type files for the Jira CSV importer
                </label>
                <div className="row" style={{ marginTop: 10, gap: 10, opacity: splitEnabled ? 1 : 0.5 }}>
                  <span className="muted">Max rows per file</span>
                  <input type="number" min={1} value={splitRows} disabled={!splitEnabled}
                    style={{ width: 100 }}
                    onChange={(e) => setSplitRows(Math.max(1, Number(e.target.value) || 210))} />
                </div>
                <div className="hint" style={{ marginTop: 8 }}>
                  Files like <code>jira_feature.csv</code> over this many rows are written as
                  <code> _part01</code>, <code>_part02</code>… each with the full header. <code>jira_all_issues.csv</code> stays whole.
                </div>
              </div>
            </div>
          </div>

          {summaryPanel(
            <>
              <button className="btn primary" onClick={runPreview} disabled={busy || !source || (needsType && !forceType)}>
                {busy ? "Analyzing…" : "Continue"}
              </button>
              <button className="btn ghost aws-summary-back" onClick={() => setStep(0)}>Back</button>
              {needsType && !forceType
                && <div className="aws-summary-note" style={{ color: "var(--danger)" }}>Select a work-item type to continue.</div>}
            </>
          )}
        </div>
      )}

      {step === 2 && preview && (
        <PreviewStep preview={preview}
          summary={summaryPanel(
            <>
              <button className="btn primary" onClick={runMigration} disabled={busy || !(jiraVerified && !!jira.project_key)}>
                {busy ? "Starting…" : "Create in Jira"}
              </button>
              <button className="btn" style={{ width: "100%", marginTop: 8 }} onClick={runExport} disabled={exporting}>
                {exporting ? "Generating…" : "Export CSV files"}
              </button>
              <button className="btn ghost aws-summary-back" onClick={() => setStep(1)}>Back</button>
            </>
          )} />
      )}

      {step === 3 && job && (
        <RunStep job={job}
          summary={
            <div className="aws-summary">
              <div className="aws-summary-head">Run summary</div>
              <div className="aws-summary-body">                <div className="aws-sum-row"><span className="k">Migration ID</span><span className="v"><code>{migrationId}</code></span></div>                <div className="aws-sum-row"><span className="k">Created</span><span className="v">{job.created}</span></div>
                <div className="aws-sum-row"><span className="k">Failed</span><span className={`v ${job.failed ? "warn" : ""}`}>{job.failed}</span></div>
                <div className="aws-sum-row"><span className="k">Attachments</span><span className="v">{job.attachments_uploaded}</span></div>
                <div className="aws-sum-row"><span className="k">Progress</span><span className="v">{job.progress}%</span></div>
                <div className="aws-sum-row"><span className="k">State</span><span className="v">{job.state}</span></div>
              </div>
              <div className="aws-summary-foot">
                <button className="btn primary" onClick={newMigration} disabled={job.state === "running"}>
                  New Migration
                </button>
                {job.state === "running" && <div className="aws-summary-note">Migration in progress…</div>}
              </div>
            </div>
          } />
      )}

      {step === 3 && !job && exportResult && (
        <ExportDoneStep result={exportResult}
          onReset={newMigration}
          onOpenExports={() => navigate(`/exports?mid=${encodeURIComponent(exportResult.migration_id || migrationId)}`)} />
      )}
      </>
      )}
    </>
  );
}

function WorkflowSteps({ current, reached, onStep }: { current: number; reached: number; onStep: (i: number) => void }) {
  return (
    <div className="wf-steps">
      {STEPS.map((s, i) => (
        <Fragment key={s}>
          {i > 0 && <div className={`wf-connector ${i <= reached ? "done" : ""}`} />}
          <button type="button"
            className={`wf-step ${i === current ? "active" : ""} ${i < reached ? "done" : ""}`}
            onClick={() => { if (i <= reached) onStep(i); }} disabled={i > reached}>
            <span className="wf-step-num">{i < reached ? "✓" : i + 1}</span>
            <span className="wf-step-label">{s}</span>
          </button>
        </Fragment>
      ))}
    </div>
  );
}

function UploadStep({ busy, onUpload, source, onRemove, summary }: {
  busy: boolean; onUpload: (f: File) => void; source: any; onRemove: () => void; summary: ReactNode;
}) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const pick = () => inputRef.current?.click();
  return (
    <div className="aws-layout">
      <div className="aws-main">
        <div className="aws-section">
          <div className="aws-section-head"><h3>Import the Rally Extracts</h3></div>
          <div className="aws-section-body">
            <div className="wf-drop" onClick={pick}
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => { e.preventDefault(); const f = e.dataTransfer.files?.[0]; if (f) onUpload(f); }}>
              <input ref={inputRef} type="file" accept=".csv" style={{ display: "none" }}
                onChange={(e) => { const f = e.target.files?.[0]; if (f) onUpload(f); }} />
              <div className="wf-drop-ico"><UploadIcon /></div>
              <div className="wf-drop-text">
                <strong>{busy ? "Uploading…" : "Drop a .csv here, or click to browse"}</strong>
                <span>.csv only · we never modify your source file</span>
              </div>
              <button type="button" className="btn wf-drop-cta" onClick={(e) => { e.stopPropagation(); pick(); }}>Browse</button>
            </div>
            {source && (
              <div className="wf-file">
                <div className="wf-file-ico"><FileCheckIcon /></div>
                <div className="wf-file-meta">
                  <strong>{source.filename}</strong><br />
                  <span>{source.row_count} rows · {source.columns.length} columns · {source.kind === "jira_all_issues" ? "converted Jira export" : "raw Rally export"}</span>
                </div>
                <button className="btn sm ghost" onClick={onRemove}>Remove</button>
              </div>
            )}
          </div>
        </div>
      </div>
      {summary}
    </div>
  );
}

function PreviewStep({ preview, summary }: {
  preview: PreviewResult; summary: ReactNode;
}) {
  const warned = preview.planned.filter((p) => p.warnings.length).length;
  const attachments = preview.planned.reduce((n, p) => n + (p.fields_preview.attachments || 0), 0);

  const warnCounts = new Map<string, number>();
  for (const w of preview.warnings) warnCounts.set(w, (warnCounts.get(w) ?? 0) + 1);
  for (const p of preview.planned) for (const w of p.warnings) warnCounts.set(w, (warnCounts.get(w) ?? 0) + 1);
  const distinctWarnings = [...warnCounts.entries()].sort((a, b) => b[1] - a[1]);

  const fmt = (v: any) => {
    if (v === null || v === undefined || v === "") return "—";
    if (Array.isArray(v)) return v.length ? v.join(", ") : "—";
    return String(v);
  };

  return (
    <div className="aws-layout">
      <div className="aws-main">
        <div className="aws-section">
          <div className="aws-section-body">
            <div className="pv-stats" style={{ marginBottom: 14 }}>
              <div className="pv-stat"><span className="num">{preview.total}</span><span className="lbl">Work items</span></div>
              <div className="pv-stat"><span className="num">{Object.keys(preview.by_type).length}</span><span className="lbl">Issue types</span></div>
              <div className="pv-stat"><span className="num">{warned}</span><span className="lbl">With warnings</span></div>
              <div className="pv-stat"><span className="num">{attachments}</span><span className="lbl">Attachments</span></div>
            </div>

            {typeof preview.parents_total === "number" && preview.parents_total > 0 && (
              <div className="callout" style={{ marginBottom: 14 }}>
                Parent Id resolved for <strong>{preview.parents_resolved ?? 0}</strong> of {preview.parents_total} parent reference{preview.parents_total === 1 ? "" : "s"} via parent.csv.
              </div>
            )}

            {distinctWarnings.length > 0 && (
              <div className="warn-summary">
                <div className="warn-summary-head">
                  <span className="ico">⚠</span>
                  {distinctWarnings.length} type{distinctWarnings.length > 1 ? "s" : ""} of warning across {warned} item{warned === 1 ? "" : "s"}
                </div>
                <ul>
                  {distinctWarnings.map(([msg], i) => (
                    <li key={i}>{msg}</li>
                  ))}
                </ul>
              </div>
            )}

            <div className="table-wrap table-scroll">
              <table className="table">
                <thead><tr>
                  <th>Source ID</th><th>Parent</th><th>Jira type</th><th>Summary</th>
                  <th>Priority</th><th>Labels</th><th>Components</th><th>Sprint</th>
                  <th>Team</th><th>Story points</th><th>Attachments</th>
                </tr></thead>
                <tbody>
                  {preview.planned.slice(0, 200).map((p, i) => (
                    <tr key={i}>
                      <td>{p.external_id || "—"}</td>
                      <td>{p.parent_external_id || "—"}</td>
                      <td><span className="badge neutral">{p.jira_issue_type}</span></td>
                      <td style={{ maxWidth: 360, whiteSpace: "normal" }}>{p.summary}</td>
                      <td>{fmt(p.fields_preview.priority)}</td>
                      <td>{fmt(p.fields_preview.labels)}</td>
                      <td>{fmt(p.fields_preview.components)}</td>
                      <td>{fmt(p.fields_preview.sprint)}</td>
                      <td>{fmt(p.fields_preview.team)}</td>
                      <td>{fmt(p.fields_preview.story_points)}</td>
                      <td>{fmt(p.fields_preview.attachments)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {preview.planned.length > 200 && <p className="muted" style={{ marginTop: 10 }}>Showing first 200 of {preview.planned.length}.</p>}
          </div>
        </div>
      </div>
      {summary}
    </div>
  );
}

function ExportDoneStep({ result, onReset, onOpenExports }: {
  result: ExportResult; onReset: () => void; onOpenExports: () => void;
}) {
  return (
    <div className="done-wrap">
      <div className="aws-section">
        <div className="done-hero">
          <div className="done-badge">✓</div>
          <h2>Jira files generated successfully</h2>
          <p>{result.files.length} file{result.files.length === 1 ? "" : "s"} · {result.total} row{result.total === 1 ? "" : "s"} ready for Jira's CSV importer.</p>
            {result.migration_id && <div className="done-mig">Migration ID <code>{result.migration_id}</code></div>}
          <h3>Files</h3>
          <a className="btn sm primary" style={{ marginLeft: "auto" }} href={api.exportZipUrl(result.export_id)}>Download all (.zip)</a>
        </div>
        <div className="aws-section-body">
          <table className="table">
            <thead><tr><th>File</th><th>Rows</th><th></th></tr></thead>
            <tbody>
              {result.files.map((f) => (
                <tr key={f.name}>
                  <td>{f.name}</td>
                  <td>{f.rows}</td>
                  <td style={{ textAlign: "right" }}>
                    <a className="btn sm ghost" href={api.exportFileUrl(result.export_id, f.name)}>Download</a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="btn-row" style={{ justifyContent: "center", marginTop: 4 }}>
        <button className="btn primary" onClick={onReset}>New Migration</button>
        <button className="btn ghost" onClick={onOpenExports}>View all exports</button>
      </div>
    </div>
  );
}

function RunStep({ job, summary }: { job: JobStatus; summary: ReactNode }) {
  const done = job.state === "done" || job.state === "failed";
  return (
    <div className="aws-layout">
      <div className="aws-main">
        <div className="aws-section">
          <div className="aws-section-head">
            <h3>Migration {job.state === "running" ? "in progress" : job.state}</h3>
            <span className={`badge ${job.state === "done" ? "ok" : job.state === "failed" ? "err" : "neutral"}`} style={{ marginLeft: "auto" }}>{job.state}</span>
          </div>
          <div className="aws-section-body">
            <div className="progress"><span style={{ width: `${job.progress}%` }} /></div>
            <p className="card-title" style={{ marginTop: 18 }}>Live log</p>
            <div className="console">
              {job.log.length === 0 ? "waiting for updates…" : job.log.map((l, i) => <div key={i}>{l}</div>)}
            </div>
          </div>
        </div>

        {done && (
          <div className="aws-section">
            <div className="aws-section-head"><h3>Results</h3></div>
            <div className="aws-section-body">
              <div className="table-wrap">
                <table className="table">
                  <thead><tr><th>Source ID</th><th>Jira key</th><th>Status</th><th>Attach.</th><th>Message</th></tr></thead>
                  <tbody>
                    {job.items.map((it, i) => (
                      <tr key={i}>
                        <td>{it.external_id || "—"}</td>
                        <td>{it.jira_key || "—"}</td>
                        <td><span className={`badge ${it.status === "failed" ? "err" : "ok"}`}>{it.status}</span></td>
                        <td>{it.attachments_uploaded}</td>
                        <td style={{ maxWidth: 360, whiteSpace: "normal" }}>{it.message}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}
      </div>
      {summary}
    </div>
  );
}

function BatchFlow() {
  const { jira, jiraMeta } = useApp();
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [items, setItems] = useState<BatchUploadItem[]>([]);
  const [mappings, setMappings] = useState<MappingTemplate[]>([]);
  const [mappingId, setMappingId] = useState<number | null>(null);   // null = default (rally_to_jira)
  const [lookups, setLookups] = useState<LookupTable[]>([]);
  const [lookupIds, setLookupIds] = useState<number[]>([]);
  const [typeMap, setTypeMap] = useState<Record<string, string>>({});
  const [includeAttachments, setIncludeAttachments] = useState(true);
  const [preview, setPreview] = useState<PreviewResult | null>(null);
  const [exportResult, setExportResult] = useState<ExportResult | null>(null);
  const [validation, setValidation] = useState<MappingValidation | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api.listMappings().then(setMappings).catch(() => {});
    api.listLookups().then((l) => { setLookups(l); setLookupIds(l.map((x) => x.id!).filter(Boolean)); }).catch(() => {});
  }, []);

  const buildReq = (): BatchMigrationRequest => ({
    files: items.map((i) => ({ source_id: i.source_id, artifact_type: i.artifact_type })),
    jira,
    mapping_id: mappingId,
    mapping: null,
    lookup_ids: lookupIds,
    type_map: Object.fromEntries(Object.entries(typeMap).filter(([, v]) => v)),
    include_attachments: includeAttachments,
  });

  async function onFiles(files: FileList | null) {
    if (!files || files.length === 0) return;
    setBusy(true); setError(""); setValidation(null);
    try {
      const res = await api.uploadBatch(Array.from(files));
      setItems((prev) => [...prev, ...res.items]);
    } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  }

  function setType(i: number, t: string) {
    setValidation(null);
    setItems((its) => its.map((it, idx) => (idx === i ? { ...it, artifact_type: t } : it)));
  }
  function removeItem(i: number) { setValidation(null); setItems((its) => its.filter((_, idx) => idx !== i)); }

  async function runValidate(): Promise<MappingValidation | null> {
    try {
      const v = await api.validateBatch(buildReq());
      setValidation(v);
      if (!v.ok) window.scrollTo({ top: 0, behavior: "smooth" });
      return v;
    } catch (e: any) { setError(e.message); return null; }
  }
  async function runPreview() {
    setBusy(true); setError(""); setExportResult(null);
    try {
      const v = await runValidate();
      if (!v || !v.ok) return;
      setPreview(await api.previewBatch(buildReq()));
    } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  }
  async function runExport() {
    setBusy(true); setError("");
    try {
      const v = await runValidate();
      if (!v || !v.ok) return;
      setExportResult(await api.exportBatch(buildReq()));
    } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  }

  const ready = items.length > 0 && items.every((i) => i.artifact_type);
  const totalRows = items.reduce((n, i) => n + i.row_count, 0);

  return (
    <>
      {error && <div className="callout warn" style={{ marginBottom: 16 }}>⚠ {error}</div>}
      {validation && <ValidationPanel v={validation} />}

      <div className="card">
        <p className="card-title">1 · Upload per-type Rally exports</p>
        <p className="card-sub">Drop one CSV per work-item type — epics, features, user stories, defects. Each file's type is detected from its name; adjust if needed.</p>
        <div className="upload-drop" onClick={() => inputRef.current?.click()}
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => { e.preventDefault(); onFiles(e.dataTransfer.files); }}>
          <input ref={inputRef} type="file" accept=".csv" multiple style={{ display: "none" }}
            onChange={(e) => onFiles(e.target.files)} />
          <div style={{ fontSize: 30, marginBottom: 6 }}>⬆</div>
          <strong>{busy ? "Uploading…" : "Drop .csv files here or click to browse"}</strong>
          <p className="muted" style={{ marginTop: 6 }}>Select multiple files at once — one per work-item type.</p>
        </div>

        {items.length > 0 && (
          <div className="table-wrap" style={{ marginTop: 16 }}>
            <table className="table">
              <thead><tr><th>File</th><th>Artifact type</th><th>Rows</th><th>Columns</th><th>Validation</th><th></th></tr></thead>
              <tbody>
                {items.map((it, i) => (
                  <tr key={it.source_id}>
                    <td>{it.filename}</td>
                    <td>
                      <select value={it.artifact_type} onChange={(e) => setType(i, e.target.value)}>
                        <option value="">— pick —</option>
                        {BATCH_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
                      </select>
                    </td>
                    <td>{it.row_count}</td>
                    <td>{it.columns.length}</td>
                    <td>{it.warnings.length
                      ? <span className="badge warn" title={it.warnings.join("\n")}>{it.warnings.length} warning{it.warnings.length === 1 ? "" : "s"}</span>
                      : <span className="badge ok">ok</span>}</td>
                    <td style={{ textAlign: "right" }}><button className="btn sm ghost" onClick={() => removeItem(i)}>✕</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {items.length > 0 && (
        <div className="card">
          <p className="card-title">2 · Mapping &amp; Jira Catalog</p>
          <div className="grid cols-2">
            <div className="field">
              <label>Mapping</label>
              <select value={mappingId ?? ""} onChange={(e) => setMappingId(e.target.value ? Number(e.target.value) : null)}>
                <option value="">Default (Auto-map from rally_to_jira)</option>
                {mappings.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
              </select>
              <div className="hint">Default uses the per-artifact rules from rally_to_jira.py. Saved Studio versions appear here.</div>
            </div>
            <div className="field">
              <label>Attachments</label>
              <label className="row" style={{ fontWeight: 400, marginTop: 8 }}>
                <input type="checkbox" style={{ width: "auto" }} checked={includeAttachments}
                  onChange={(e) => setIncludeAttachments(e.target.checked)} />
                Include attachment URLs in the import files
              </label>
            </div>
          </div>

          {lookups.length > 0 && (
            <div className="field">
              <label>Jira Catalog value mappings to apply</label>
              <div className="hint" style={{ marginBottom: 8 }}>Translate Rally values (sprint, version, user, team) to their Jira equivalents.</div>
              {lookups.map((lk) => {
                const on = lookupIds.includes(lk.id!);
                return (
                  <label key={lk.id} className="row" style={{ fontWeight: 400, marginBottom: 6 }}>
                    <input type="checkbox" style={{ width: "auto" }} checked={on}
                      onChange={(e) => setLookupIds(e.target.checked ? [...lookupIds, lk.id!] : lookupIds.filter((x) => x !== lk.id))} />
                    <span className="badge neutral">{lk.kind}</span> {lk.name}
                    <span className="muted">· {Object.keys(lk.entries).length} entries</span>
                  </label>
                );
              })}
            </div>
          )}

          <details style={{ marginTop: 8 }}>
            <summary style={{ cursor: "pointer", fontWeight: 600, margin: "6px 0" }}>Issue type mapping</summary>
            <div className="table-wrap" style={{ marginTop: 8 }}>
              <table className="table">
                <thead><tr><th>Source type</th><th>→ Jira issue type</th></tr></thead>
                <tbody>
                  {NORMALIZED_TYPES.map((t) => {
                    const current = typeMap[t] ?? DEFAULT_TYPE_TARGET[t] ?? "";
                    return (
                      <tr key={t}>
                        <td>{t}</td>
                        <td>
                          {jiraMeta && jiraMeta.issue_types.length ? (
                            <select value={current} onChange={(e) => setTypeMap({ ...typeMap, [t]: e.target.value })}>
                              <option value="">— default ({DEFAULT_TYPE_TARGET[t] || "same"}) —</option>
                              {jiraMeta.issue_types.map((it) => <option key={it.id} value={it.name}>{it.name}</option>)}
                            </select>
                          ) : (
                            <input value={current} onChange={(e) => setTypeMap({ ...typeMap, [t]: e.target.value })} />
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </details>

          <div className="btn-row" style={{ marginTop: 16 }}>
            <button className="btn" onClick={async () => { setBusy(true); await runValidate(); setBusy(false); }} disabled={busy || !ready}>Validate mappings</button>
            <button className="btn" onClick={runPreview} disabled={busy || !ready}>{busy ? "Working…" : "Preview"}</button>
            <button className="btn primary" onClick={runExport} disabled={busy || !ready}>{busy ? "Working…" : `Generate import files (${totalRows} rows)`}</button>
          </div>
          {!ready && <p className="hint" style={{ marginTop: 8 }}>Assign an artifact type to every file to continue.</p>}
        </div>
      )}

      {preview && (
        <div className="card">
          <p className="card-title">Preview · {preview.total} work items</p>
          <div style={{ marginBottom: 8 }}>
            {Object.entries(preview.by_type).map(([t, n]) => <span key={t} className="tag">{t}: {n}</span>)}
          </div>
          {preview.warnings.map((w, i) => <div key={i} className="callout warn" style={{ marginBottom: 8 }}>⚠ {w}</div>)}
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Source ID</th><th>Parent</th><th>Jira type</th><th>Summary</th></tr></thead>
              <tbody>
                {preview.planned.slice(0, 100).map((p, i) => (
                  <tr key={i}>
                    <td>{p.external_id || "—"}</td>
                    <td>{p.parent_external_id || "—"}</td>
                    <td><span className="badge neutral">{p.jira_issue_type}</span></td>
                    <td style={{ maxWidth: 360, whiteSpace: "normal" }}>{p.summary}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {preview.planned.length > 100 && <p className="muted" style={{ marginTop: 10 }}>Showing first 100 of {preview.planned.length}.</p>}
        </div>
      )}

      {exportResult && (
        <div className="card">
          <div className="spread">
            <p className="card-title" style={{ margin: 0 }}>Import files ready · {exportResult.total} rows</p>
            <a className="btn sm primary" href={api.exportZipUrl(exportResult.export_id)}>Download all (.zip)</a>
          </div>
          <table className="table" style={{ marginTop: 10 }}>
            <thead><tr><th>File</th><th>Rows</th><th></th></tr></thead>
            <tbody>
              {exportResult.files.map((f) => (
                <tr key={f.name}>
                  <td>{f.name}</td>
                  <td>{f.rows}</td>
                  <td style={{ textAlign: "right" }}>
                    <a className="btn sm ghost" href={api.exportFileUrl(exportResult.export_id, f.name)}>Download</a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="hint" style={{ marginTop: 8 }}>In Jira: System → External System Import → CSV, then map the columns to fields.</p>
        </div>
      )}
    </>
  );
}

function ValidationPanel({ v }: { v: MappingValidation }) {
  if (v.ok) return null;
  return (
    <div className="card val-error" style={{ marginBottom: 16 }}>
      <p className="card-title">⚠ {v.total_missing} unmapped value{v.total_missing === 1 ? "" : "s"} — fix before migrating</p>
      <p className="card-sub">
        These Jira-ID-dependent values have no entry in their mapping file. Add them in the{" "}
        <strong>Jira Catalog</strong> tab, then re-validate. Empty values are skipped automatically.
      </p>
      {v.issues.map((iss, i) => (
        <div key={i} className="val-issue">
          <div className="val-issue-head">
            <span><span className="badge warn">{iss.mapping_file}</span> &nbsp;<strong>{iss.field}</strong></span>
            <span className="muted">{iss.missing_count} value{iss.missing_count === 1 ? "" : "s"} · {iss.affected_rows} row{iss.affected_rows === 1 ? "" : "s"} affected</span>
          </div>
          <div className="val-vals">
            {iss.missing_values.slice(0, 30).map((x) => <span key={x} className="val-chip">{x || "(blank)"}</span>)}
            {iss.missing_values.length > 30 && <span className="muted">+{iss.missing_values.length - 30} more</span>}
          </div>
        </div>
      ))}
    </div>
  );
}
