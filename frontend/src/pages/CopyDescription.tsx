import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useApp } from "../store";
import type { CopyDescriptionResult, CopyDescIdsResult, CopyDescJob } from "../types";

const svg = { width: 16, height: 16, fill: "none", stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
const UploadIcon = () => (<svg viewBox="0 0 24 24" {...svg}><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><path d="M7 10l5-5 5 5M12 5v12" /></svg>);
const DownloadIcon = () => (<svg viewBox="0 0 24 24" {...svg}><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><path d="M7 10l5 5 5-5M12 15V3" /></svg>);

export default function CopyDescription() {
  const { jira, rally } = useApp();
  const [rallyId, setRallyId] = useState("");
  const [jiraKey, setJiraKey] = useState("");
  const [busy, setBusy] = useState<"" | "preview" | "apply">("");
  const [error, setError] = useState("");
  const [result, setResult] = useState<CopyDescriptionResult | null>(null);

  const rallyReady = !!rally.api_key;
  const jiraReady = !!(jira.base_url && jira.api_token);

  async function preview() {
    if (!rallyId.trim()) return;
    setBusy("preview"); setError(""); setResult(null);
    try {
      setResult(await api.copyDescriptionPreview({ jira, rally, rally_id: rallyId, jira_key: jiraKey }));
    } catch (e: any) { setError(e.message || "Preview failed"); }
    finally { setBusy(""); }
  }

  async function apply() {
    if (!rallyId.trim() || !jiraKey.trim()) return;
    setBusy("apply"); setError("");
    try {
      setResult(await api.copyDescriptionApply({ jira, rally, rally_id: rallyId, jira_key: jiraKey }));
    } catch (e: any) { setError(e.message || "Copy failed"); }
    finally { setBusy(""); }
  }

  return (
    <>
      <div style={{ marginBottom: 18 }}>
        <h1 style={{ margin: "0 0 4px", fontSize: 20, fontWeight: 700, letterSpacing: "-0.02em" }}>Copy Description</h1>
        <p className="muted" style={{ margin: 0, fontSize: 13 }}>
          Copy a Rally artifact's description into a Jira issue, keeping tables in the same format
          ({jira.deployment === "cloud" ? "ADF tables for Jira Cloud" : "wiki tables for Server / Data Center"}).
        </p>
      </div>

      {(!rallyReady || !jiraReady) && (
        <div className="card" style={{ borderLeft: "3px solid var(--danger)" }}>
          <p style={{ margin: 0, fontSize: 13 }}>
            {!rallyReady && "A Rally API key is required. "}
            {!jiraReady && "Jira base URL and API token are required. "}
            Set them in <Link to="/connections">Connections</Link>.
          </p>
        </div>
      )}

      <div className="card">
        <p className="card-title" style={{ margin: "0 0 12px" }}>Single issue</p>
        <div className="grid cols-2">
          <div className="field">
            <label>Rally Formatted ID</label>
            <input value={rallyId} placeholder="F139943" onChange={(e) => setRallyId(e.target.value)} />
            <div className="hint">Source artifact whose description (with tables) is read from Rally.</div>
          </div>
          <div className="field">
            <label>Jira issue key</label>
            <input value={jiraKey} placeholder="PN-123" onChange={(e) => setJiraKey(e.target.value)} />
            <div className="hint">Target issue whose description will be replaced.</div>
          </div>
        </div>

        <div className="btn-row" style={{ marginTop: 8 }}>
          <button className="btn" disabled={!rallyReady || !rallyId.trim() || busy !== ""} onClick={preview}>
            {busy === "preview" ? "Reading…" : "Preview"}
          </button>
          <button className="btn primary" disabled={!rallyReady || !jiraReady || !rallyId.trim() || !jiraKey.trim() || busy !== ""} onClick={apply}>
            {busy === "apply" ? "Copying…" : "Copy to Jira"}
          </button>
          {error && <span style={{ color: "var(--danger)", fontSize: 13, alignSelf: "center" }}>{error}</span>}
        </div>
      </div>

      {result && (
        <div className="card">
          <div className="spread" style={{ marginBottom: 12 }}>
            <div className="row" style={{ gap: 10, flexWrap: "wrap" }}>
              <span className="tag">{result.format === "adf" ? "ADF (Cloud)" : "Wiki (Server/DC)"}</span>
              <span className="tag">{result.tables_found} table{result.tables_found === 1 ? "" : "s"}</span>
              {result.applied
                ? <span className="tag" style={{ color: "var(--success)", borderColor: "var(--success)" }}>Applied</span>
                : <span className="tag">Preview</span>}
            </div>
          </div>
          <p className="muted" style={{ margin: "0 0 10px", fontSize: 13 }}>{result.message}</p>
          {result.has_source && (
            <pre style={{
              margin: 0, padding: 14, background: "var(--surface-2)", border: "1px solid var(--border)",
              borderRadius: 8, fontSize: 12.5, lineHeight: 1.5, overflowX: "auto", whiteSpace: "pre-wrap",
            }}>{result.text_preview}</pre>
          )}
        </div>
      )}

      <BulkCopy rallyReady={rallyReady} jiraReady={jiraReady} />
    </>
  );
}

function BulkCopy({ rallyReady, jiraReady }: { rallyReady: boolean; jiraReady: boolean }) {
  const { jira, rally } = useApp();
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [ridField, setRidField] = useState(jira.rally_id_field || "Rally ID");
  const [ids, setIds] = useState<CopyDescIdsResult | null>(null);
  const [tablesOnly, setTablesOnly] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const [job, setJob] = useState<CopyDescJob | null>(null);
  const [starting, setStarting] = useState(false);
  const [filterTables, setFilterTables] = useState(false);
  const poll = useRef<number | null>(null);

  useEffect(() => () => { if (poll.current) window.clearInterval(poll.current); }, []);

  async function onUpload(file: File) {
    setUploading(true); setError(""); setJob(null);
    try { setIds(await api.uploadCopyDescIds(file)); }
    catch (e: any) { setError(e.message); setIds(null); }
    finally { setUploading(false); }
  }

  async function run(dryRun: boolean) {
    if (!ids?.rally_ids.length) return;
    setStarting(true); setError(""); setJob(null); setFilterTables(false);
    try {
      const started = await api.copyDescBulk({
        jira, rally, rally_id_field: ridField, rally_ids: ids.rally_ids,
        id_map: ids.id_map || {},
        dry_run: dryRun, tables_only: tablesOnly,
      });
      setJob(started);
      poll.current = window.setInterval(async () => {
        try {
          const j = await api.copyDescJob(started.job_id);
          setJob(j);
          if (j.state === "done" || j.state === "failed") { if (poll.current) window.clearInterval(poll.current); }
        } catch { /* keep polling */ }
      }, 1200);
    } catch (e: any) { setError(e.message); }
    finally { setStarting(false); }
  }

  const running = job && (job.state === "queued" || job.state === "running");
  const items = job ? (filterTables ? job.items.filter((i) => i.tables_found > 0) : job.items) : [];
  const mapped = ids ? Object.keys(ids.id_map || {}).length : 0;
  const hasMap = !!ids?.key_column && mapped > 0;

  return (
    <div className="card">
      <p className="card-title" style={{ margin: "0 0 4px" }}>Bulk — detect &amp; copy</p>
      <p className="muted" style={{ margin: "0 0 14px", fontSize: 13 }}>
        Upload a CSV of Rally IDs. A <strong>dry run detects which descriptions contain tables</strong> (no writes);
        applying copies them into the matching Jira issues. Identify the target either by a
        <strong> post-import map</strong> (Rally ID + Jira key columns) or by the <strong>Rally-ID field</strong> on each issue.
      </p>

      <div className="grid cols-2" style={{ alignItems: "end" }}>
        <div className="field">
          <label>Rally IDs CSV <span className="muted">(add a Jira Key/ID column to skip lookup)</span></label>
          <input ref={inputRef} type="file" accept=".csv,text/csv" style={{ display: "none" }}
            onChange={(e) => { const f = e.target.files?.[0]; if (f) onUpload(f); }} />
          <div className="row" style={{ gap: 10 }}>
            <button className="btn" disabled={!rallyReady} onClick={() => inputRef.current?.click()}><UploadIcon /> Choose CSV</button>
            <span className="muted" style={{ fontSize: 13 }}>
              {uploading ? "Reading…" : ids ? `${ids.rally_ids.length} IDs · column "${ids.id_column}"` : "No file selected"}
            </span>
          </div>
        </div>
        <div className="field">
          <label>Jira Rally-ID field</label>
          <input value={ridField} placeholder="Rally ID or customfield_12345" disabled={hasMap}
            onChange={(e) => setRidField(e.target.value)} />
          <div className="hint">
            {hasMap ? "Not needed — Jira keys were provided in the CSV." : "Field used to find each Jira issue by its Rally ID."}
          </div>
        </div>
      </div>

      {ids && (
        <p className="muted" style={{ margin: "10px 0 0", fontSize: 12.5 }}>
          {hasMap
            ? `Identification: using Jira keys from column "${ids.key_column}" (${mapped} mapped) — no lookup needed.`
            : `Identification: resolving each Jira issue by the "${ridField}" field (requires the Rally ID to be stamped at creation).`}
        </p>
      )}

      <label className="row" style={{ gap: 8, marginTop: 12, fontSize: 13 }}>
        <input type="checkbox" checked={tablesOnly} onChange={(e) => setTablesOnly(e.target.checked)} />
        When applying, only copy descriptions that contain a table
      </label>

      <div className="btn-row" style={{ marginTop: 14 }}>
        <button className="btn" disabled={!rallyReady || !ids?.rally_ids.length || starting || !!running} onClick={() => run(true)}>
          {starting ? "Starting…" : "Dry run — detect tables"}
        </button>
        <button className="btn primary" disabled={!rallyReady || !jiraReady || !ids?.rally_ids.length || starting || !!running} onClick={() => run(false)}>
          Apply — copy descriptions
        </button>
        {error && <span style={{ color: "var(--danger)", fontSize: 13, alignSelf: "center" }}>{error}</span>}
      </div>

      {job && (
        <div style={{ marginTop: 16 }}>
          <div className="spread" style={{ marginBottom: 8 }}>
            <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
              <span className="tag">{job.dry_run ? "Dry run" : "Apply"}</span>
              <span className="tag">{job.processed_ids}/{job.total_ids} processed</span>
              <span className="tag">{job.with_tables} with tables</span>
              {!job.dry_run && <span className="tag" style={{ color: "var(--success)", borderColor: "var(--success)" }}>{job.applied} applied</span>}
              {job.unresolved > 0 && <span className="tag">{job.unresolved} unresolved</span>}
              {job.errors > 0 && <span className="tag" style={{ color: "var(--danger)", borderColor: "var(--danger)" }}>{job.errors} errors</span>}
            </div>
            <div className="row" style={{ gap: 12 }}>
              <label className="row" style={{ gap: 6, fontSize: 12.5 }}>
                <input type="checkbox" checked={filterTables} onChange={(e) => setFilterTables(e.target.checked)} />
                Only with tables
              </label>
              <a className="btn ghost sm" href={api.copyDescReportUrl(job.job_id)}><DownloadIcon /> Report</a>
            </div>
          </div>

          <div style={{ height: 6, background: "var(--surface-2)", borderRadius: 999, overflow: "hidden" }}>
            <div style={{ width: `${job.progress}%`, height: "100%", background: "var(--primary)", transition: "width .2s" }} />
          </div>

          <div className="table-scroll" style={{ marginTop: 12 }}>
            <table className="table">
              <thead>
                <tr>
                  <th>Rally ID</th><th>Jira</th>
                  <th style={{ textAlign: "right", width: 80 }}>Tables</th>
                  <th style={{ width: 100 }}>Status</th><th>Detail</th>
                </tr>
              </thead>
              <tbody>
                {items.map((it, n) => (
                  <tr key={`${it.rally_id}-${n}`}>
                    <td style={{ fontFamily: "ui-monospace, Menlo, monospace" }}>{it.rally_id}</td>
                    <td style={{ fontFamily: "ui-monospace, Menlo, monospace" }}>{it.jira_key || "—"}</td>
                    <td style={{ textAlign: "right", fontWeight: it.tables_found ? 700 : 400 }}>{it.tables_found || ""}</td>
                    <td><span className="tag" style={it.status === "error" || it.status === "unresolved" ? { color: "var(--danger)", borderColor: "var(--danger)" } : it.status === "applied" ? { color: "var(--success)", borderColor: "var(--success)" } : undefined}>{it.status}</span></td>
                    <td className="muted" style={{ fontSize: 12.5 }}>{it.detail}</td>
                  </tr>
                ))}
                {items.length === 0 && (
                  <tr><td colSpan={5} className="muted" style={{ textAlign: "center", padding: 20 }}>
                    {running ? "Working…" : "No rows to show."}
                  </td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

