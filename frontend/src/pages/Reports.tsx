import { useEffect, useState } from "react";
import { api } from "../api";
import type { JobStatus } from "../types";

export default function Reports() {
  const [jobs, setJobs] = useState<JobStatus[]>([]);
  const [selected, setSelected] = useState<JobStatus | null>(null);

  useEffect(() => { api.jobs().then(setJobs).catch(() => {}); }, []);

  return (
    <>
      <div className="card">
        <p className="card-title">Migration history</p>
        <p className="card-sub">Every run is recorded with a full, exportable audit trail.</p>
        {jobs.length === 0 ? (
          <div className="empty">No runs recorded yet.</div>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Job</th><th>State</th><th>Total</th><th>Created</th><th>Failed</th><th>Attachments</th><th>Finished</th><th></th></tr></thead>
              <tbody>
                {jobs.map((j) => (
                  <tr key={j.job_id}>
                    <td><code>{j.job_id.slice(0, 8)}</code></td>
                    <td><span className={`badge ${j.state === "done" ? "ok" : j.state === "failed" ? "err" : "neutral"}`}>{j.state}</span></td>
                    <td>{j.total}</td><td>{j.created}</td><td>{j.failed}</td><td>{j.attachments_uploaded}</td>
                    <td className="muted">{j.finished_at?.replace("T", " ") || "—"}</td>
                    <td><button className="btn sm" onClick={() => setSelected(j)}>Details</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {selected && (
        <div className="card">
          <div className="spread">
            <p className="card-title" style={{ margin: 0 }}>Run {selected.job_id.slice(0, 8)} · {selected.items.length} items</p>
            <button className="btn sm ghost" onClick={() => setSelected(null)}>Close ✕</button>
          </div>
          <div className="table-wrap" style={{ marginTop: 12 }}>
            <table className="table">
              <thead><tr><th>Source ID</th><th>Jira key</th><th>Status</th><th>Attach.</th><th>Message</th></tr></thead>
              <tbody>
                {selected.items.map((it, i) => (
                  <tr key={i}>
                    <td>{it.external_id || "—"}</td>
                    <td>{it.jira_key || "—"}</td>
                    <td><span className={`badge ${it.status === "failed" ? "err" : "ok"}`}>{it.status}</span></td>
                    <td>{it.attachments_uploaded}</td>
                    <td style={{ maxWidth: 420, whiteSpace: "normal" }}>{it.message}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </>
  );
}
