import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { useApp } from "../store";
import type { AttachmentIdsResult, AttachmentJob, ConnectionTestResult } from "../types";

const svg = { fill: "none", stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
const UploadIcon = () => (<svg viewBox="0 0 24 24" {...svg}><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><path d="M7 10l5-5 5 5M12 5v12" /></svg>);
const FileCheckIcon = () => (<svg viewBox="0 0 24 24" {...svg}><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><path d="M14 2v6h6M9 15l2 2 4-4" /></svg>);
const PaperclipIcon = () => (<svg viewBox="0 0 24 24" {...svg}><path d="M21.44 11.05 12.25 20.24a5 5 0 0 1-7.07-7.07l9.19-9.19a3.5 3.5 0 0 1 4.95 4.95l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" /></svg>);
const LockIcon = () => (<svg viewBox="0 0 24 24" {...svg}><rect x="3" y="11" width="18" height="10" rx="2" /><path d="M7 11V7a5 5 0 0 1 10 0v4" /></svg>);

export default function Attachments() {
  const { jira, rally, setJira, setRally, jiraVerified, rallyVerified, setJiraVerified, setRallyVerified,
          connectionsSaved, connectionsSavedAt, saveConnections, forgetConnections } = useApp();
  const [testing, setTesting] = useState(false);
  const [results, setResults] = useState<ConnectionTestResult[]>([]);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  const inputRef = useRef<HTMLInputElement | null>(null);
  const [ids, setIds] = useState<AttachmentIdsResult | null>(null);
  const [uploading, setUploading] = useState(false);

  const [dryRun, setDryRun] = useState(false);
  const [job, setJob] = useState<AttachmentJob | null>(null);
  const [busy, setBusy] = useState(false);
  const poll = useRef<number | null>(null);

  useEffect(() => () => { if (poll.current) window.clearInterval(poll.current); }, []);

  async function test() {
    setTesting(true); setError(""); setResults([]);
    try {
      const res = await api.testConnections(jira.base_url ? jira : undefined, rally.api_key ? rally : undefined);
      setResults(res);
      setJiraVerified(res.some((r) => r.system === "jira" && r.ok));
      setRallyVerified(res.some((r) => r.system === "rally" && r.ok));
    } catch (e: any) { setError(e.message || "Connection test failed"); }
    finally { setTesting(false); }
  }

  async function onSaveCreds() {
    setSaving(true); setError("");
    try { await saveConnections(); }
    catch (e: any) { setError(e.message || "Could not save credentials"); }
    finally { setSaving(false); }
  }

  async function onUpload(file: File) {
    setUploading(true); setError(""); setJob(null);
    try { setIds(await api.uploadAttachmentIds(file)); }
    catch (e: any) { setError(e.message); setIds(null); }
    finally { setUploading(false); }
  }

  const ridField = jira.rally_id_field || "Rally ID";
  const canRunLive = !!(jira.base_url && jira.email && jira.api_token && rally.api_key);

  async function run(dry: boolean) {
    if (!ids?.rally_ids.length) return;
    setBusy(true); setError("");
    try {
      const started = await api.runAttachments({
        jira, rally, rally_id_field: ridField, rally_ids: ids.rally_ids, dry_run: dry,
      });
      setJob(started);
      poll.current = window.setInterval(async () => {
        try {
          const j = await api.attachmentJob(started.job_id);
          setJob(j);
          if (j.state === "done" || j.state === "failed") { if (poll.current) window.clearInterval(poll.current); }
        } catch { /* keep polling */ }
      }, 1200);
    } catch (e: any) { setError(e.message); }
    finally { setBusy(false); }
  }

  const rResult = (sys: string) => results.find((r) => r.system === sys);
  const done = job && (job.state === "done" || job.state === "failed");

  return (
    <>
      <div className="att-hero">
        <div className="att-hero-ico"><PaperclipIcon /></div>
        <div className="att-hero-body">
          <h1 className="att-hero-title">Transfer Rally attachments</h1>
          <p className="att-hero-text">
            Attach Rally files to <strong>already-created</strong> Jira issues. Upload a CSV of Rally IDs and
            Portage resolves each to its Jira issue by the Rally-ID field, then transfers every attachment across.
          </p>
          <div className="att-steps">
            <span className="att-step"><span className="n">1</span> Upload Rally IDs</span>
            <span className="att-arrow">→</span>
            <span className="att-step"><span className="n">2</span> Resolve to Jira issues</span>
            <span className="att-arrow">→</span>
            <span className="att-step"><span className="n">3</span> Transfer attachments</span>
          </div>
          <div className="att-hero-note">✓ Re-runs are safe — files already attached are skipped.</div>
        </div>
      </div>

      {/* ---- Connections ---- */}
      <div className="grid cols-2">
        <div className="card">
          <div className="spread">
            <div><p className="card-title">Jira — target</p><p className="card-sub">Where attachments are uploaded.</p></div>
            <ResultBadge r={rResult("jira")} verified={jiraVerified} />
          </div>
          <div className="field">
            <label>Base URL</label>
            <input value={jira.base_url} placeholder="https://your-org.atlassian.net" onChange={(e) => setJira({ base_url: e.target.value })} />
          </div>
          <div className="grid cols-2">
            <div className="field">
              <label>Deployment</label>
              <select value={jira.deployment} onChange={(e) => setJira({ deployment: e.target.value as any })}>
                <option value="cloud">Jira Cloud</option>
                <option value="server">Server / Data Center</option>
              </select>
            </div>
            <div className="field">
              <label>Email {jira.deployment === "server" ? "/ username" : ""}</label>
              <input value={jira.email} placeholder="you@company.com" onChange={(e) => setJira({ email: e.target.value })} />
            </div>
          </div>
          <div className="field">
            <label>API token</label>
            <input type="password" value={jira.api_token} placeholder="paste token" onChange={(e) => setJira({ api_token: e.target.value })} />
          </div>
          <div className="field">
            <label>Rally ID field <span className="muted">(used to find each issue)</span></label>
            <input value={jira.rally_id_field} placeholder="Rally ID  or  customfield_12345" onChange={(e) => setJira({ rally_id_field: e.target.value })} />
            <div className="hint">The Jira field that stores the Rally FormattedID. Matched via JQL to locate the issue.</div>
          </div>
        </div>

        <div className="card">
          <div className="spread">
            <div><p className="card-title">Rally — source</p><p className="card-sub">Where attachments are read from.</p></div>
            <ResultBadge r={rResult("rally")} verified={rallyVerified} />
          </div>
          <div className="field">
            <label>Base URL</label>
            <input value={rally.base_url} onChange={(e) => setRally({ base_url: e.target.value })} />
          </div>
          <div className="field">
            <label>API key</label>
            <input type="password" value={rally.api_key} placeholder="_abc123…" onChange={(e) => setRally({ api_key: e.target.value })} />
            <div className="hint">Rally → Settings → API Keys. Required to download attachment bytes.</div>
          </div>
          <div className="field">
            <label>Project ObjectID <span className="muted">(optional filter)</span></label>
            <input value={rally.project_object_id || ""} placeholder="e.g. 822923710301"
              onChange={(e) => setRally({ project_object_id: e.target.value })} />
            <div className="hint">Restrict lookups to this Rally project only — work items in any other project are skipped.</div>
          </div>
        </div>
      </div>

      {/* ---- Connection actions ---- */}
      <div className="card conn-actions">
        <div className="conn-status">
          <span className={`conn-status-ico ${connectionsSaved ? "ok" : ""}`}><LockIcon /></span>
          <div>
            <div className="conn-status-title">{connectionsSaved ? "Credentials saved" : "Credentials not saved"}</div>
            <div className="conn-status-sub">
              {connectionsSaved
                ? `Encrypted at rest${connectionsSavedAt ? ` · ${connectionsSavedAt}` : ""}`
                : "Save to keep your API keys across reloads — stored encrypted, never in the browser."}
            </div>
          </div>
        </div>
        <div className="conn-actions-btns">
          <button className="btn" onClick={test} disabled={testing || (!jira.base_url && !rally.api_key)}>
            {testing ? "Testing…" : "Test connections"}
          </button>
          <button className="btn primary" onClick={onSaveCreds} disabled={saving || (!jira.api_token && !rally.api_key)}>
            {saving ? "Saving…" : connectionsSaved ? "Update saved" : "Save credentials"}
          </button>
          {connectionsSaved && <button className="btn ghost" onClick={forgetConnections}>Forget</button>}
        </div>
      </div>
      {error && <p className="badge err" style={{ marginTop: 12 }}>{error}</p>}

      {/* ---- Rally IDs ---- */}
      <div className="card">
        <p className="card-title">Rally IDs</p>
        <p className="card-sub">Upload a CSV listing the Rally work items (a column like <code>Rally ID</code> or <code>Formatted ID</code>).</p>
        <div className="wf-drop" onClick={() => inputRef.current?.click()}
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => { e.preventDefault(); const f = e.dataTransfer.files?.[0]; if (f) onUpload(f); }}>
          <input ref={inputRef} type="file" accept=".csv" style={{ display: "none" }}
            onChange={(e) => { const f = e.target.files?.[0]; if (f) onUpload(f); }} />
          <div className="wf-drop-ico"><UploadIcon /></div>
          <div className="wf-drop-text">
            <strong>{uploading ? "Reading…" : "Drop a .csv of Rally IDs, or click to browse"}</strong>
            <span>.csv only · we read the IDs and discard the file</span>
          </div>
          <button type="button" className="btn wf-drop-cta" onClick={(e) => { e.stopPropagation(); inputRef.current?.click(); }}>Browse</button>
        </div>
        {ids && (
          <div className="wf-file">
            <div className="wf-file-ico"><FileCheckIcon /></div>
            <div className="wf-file-meta">
              <strong>{ids.filename}</strong><br />
              <span><b>{ids.rally_ids.length}</b> Rally IDs from column “{ids.id_column}” · {ids.row_count} rows</span>
            </div>
          </div>
        )}
        {ids && (
          <div style={{ marginTop: 12 }}>
            {ids.rally_ids.slice(0, 24).map((r) => <span key={r} className="tag">{r}</span>)}
            {ids.rally_ids.length > 24 && <span className="muted"> +{ids.rally_ids.length - 24} more</span>}
          </div>
        )}
      </div>

      {/* ---- Run ---- */}
      <div className="card">
        <div className="spread">
          <div>
            <p className="card-title" style={{ margin: 0 }}>Transfer attachments</p>
            <p className="card-sub" style={{ margin: "2px 0 0" }}>
              {ids ? <>Ready to process <b>{ids.rally_ids.length}</b> work item(s) with field <code>{ridField}</code>.</> : "Upload Rally IDs to begin."}
            </p>
          </div>
          <label className="row" style={{ fontWeight: 400 }}>
            <input type="checkbox" style={{ width: "auto" }} checked={dryRun} onChange={(e) => setDryRun(e.target.checked)} />
            Dry run (resolve & discover only)
          </label>
        </div>

        <div className="btn-row" style={{ marginTop: 14 }}>
          <button className="btn primary" onClick={() => run(dryRun)}
            disabled={busy || !ids?.rally_ids.length || (!dryRun && !canRunLive) || (job?.state === "running")}>
            {busy || job?.state === "running" ? "Running…" : dryRun ? "Preview (dry run)" : "Start attachment transfer"}
          </button>
          {!dryRun && !canRunLive && <span className="muted" style={{ alignSelf: "center" }}>Set Jira credentials + a Rally API key to run live.</span>}
        </div>

        {job && (
          <>
            <div className="pv-stats" style={{ marginTop: 18 }}>
              <div className="pv-stat"><span className="num">{job.resolved}</span><span className="lbl">Resolved</span></div>
              <div className="pv-stat"><span className="num">{job.uploaded}</span><span className="lbl">Uploaded</span></div>
              <div className="pv-stat"><span className="num">{job.exists}</span><span className="lbl">Already there</span></div>
              <div className="pv-stat"><span className="num" style={{ color: job.errors ? "var(--danger)" : undefined }}>{job.errors}</span><span className="lbl">Errors</span></div>
            </div>

            <div className="spread" style={{ margin: "18px 0 8px" }}>
              <p className="card-title" style={{ margin: 0 }}>{job.dry_run ? "Dry run" : "Transfer"} {job.state === "running" ? "in progress" : job.state}</p>
              <span className={`badge ${job.state === "done" ? "ok" : job.state === "failed" ? "err" : "neutral"}`}>{job.state}</span>
            </div>
            <div className="progress"><span style={{ width: `${job.progress}%` }} /></div>
            <p className="muted" style={{ marginTop: 6, fontSize: 12 }}>{job.processed_ids} of {job.total_ids} work items · {job.unresolved} unresolved</p>

            <p className="card-title" style={{ marginTop: 18 }}>Live log</p>
            <div className="console">
              {job.log.length === 0 ? "waiting for updates…" : job.log.map((l, i) => <div key={i}>{l}</div>)}
            </div>

            {done && job.items.length > 0 && (
              <>
                <div className="spread" style={{ margin: "18px 0 8px" }}>
                  <p className="card-title" style={{ margin: 0 }}>Results <span className="muted" style={{ fontWeight: 400 }}>· {job.items.length} rows</span></p>
                  <a className="btn sm primary" href={api.attachmentReportUrl(job.job_id)} download>↓ Download report (.csv)</a>
                </div>
                <div className="table-wrap table-scroll">
                  <table className="table">
                    <thead><tr><th>Rally ID</th><th>Jira key</th><th>File</th><th>Status</th><th>Detail</th></tr></thead>
                    <tbody>
                      {job.items.map((it, i) => (
                        <tr key={i}>
                          <td>{it.rally_id}</td>
                          <td>{it.jira_key || "—"}</td>
                          <td>{it.file_name || "—"}</td>
                          <td><StatusBadge s={it.status} /></td>
                          <td style={{ maxWidth: 360, whiteSpace: "normal" }}>{it.detail}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </>
        )}
      </div>
    </>
  );
}

function ResultBadge({ r, verified }: { r?: ConnectionTestResult; verified: boolean }) {
  if (r) return <span className={`badge ${r.ok ? "ok" : "err"}`}>{r.ok ? "connected" : "failed"}</span>;
  return <span className={`badge ${verified ? "ok" : "neutral"}`}>{verified ? "connected" : "not tested"}</span>;
}

function StatusBadge({ s }: { s: string }) {
  const cls = s === "uploaded" ? "ok" : s === "error" ? "err"
    : s === "exists" || s === "no attachments" || s === "dry-run" ? "neutral" : "warn";
  return <span className={`badge ${cls}`}>{s}</span>;
}
