import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useApp } from "../store";
import type { JobStatus } from "../types";

function Stat({ value, label }: { value: string | number; label: string }) {
  return (
    <div className="card stat">
      <span className="stat-value">{value}</span>
      <span className="stat-label">{label}</span>
    </div>
  );
}

export default function Dashboard() {
  const { jiraVerified, rallyVerified, source } = useApp();
  const [jobs, setJobs] = useState<JobStatus[]>([]);
  const [health, setHealth] = useState<string>("checking…");

  useEffect(() => {
    api.health().then((h) => setHealth(`online · v${h.version}`)).catch(() => setHealth("offline"));
    api.jobs().then(setJobs).catch(() => {});
  }, []);

  const totalCreated = jobs.reduce((n, j) => n + j.created, 0);
  const totalAttach = jobs.reduce((n, j) => n + j.attachments_uploaded, 0);

  return (
    <>
      <div className="grid cols-4">
        <Stat value={jobs.length} label="Migration runs" />
        <Stat value={totalCreated} label="Work items created" />
        <Stat value={totalAttach} label="Attachments moved" />
        <Stat value={source ? source.row_count : "—"} label="Loaded source rows" />
      </div>

      <div className="card">
        <p className="card-title">Getting started</p>
        <p className="card-sub">Four steps take you from a Rally export to live Jira work items — no CSV import.</p>
        <div className="grid cols-4">
          <StepCard n={1} title="Connect" body="Add your Jira API token and (optionally) a Rally API key." to="/connections" done={jiraVerified} />
          <StepCard n={2} title="Map" body="Match source fields to Jira fields, or use the built-in template." to="/mapping" done={false} />
          <StepCard n={3} title="Preview" body="Dry-run the migration and review every planned work item." to="/migrate" done={false} />
          <StepCard n={4} title="Migrate" body="Create issues live, preserve hierarchy, and move attachments." to="/migrate" done={false} />
        </div>
      </div>

      <div className="grid cols-2">
        <div className="card">
          <p className="card-title">System status</p>
          <div className="field"><div className="spread"><span>Backend API</span><span className="badge ok">{health}</span></div></div>
          <div className="field"><div className="spread"><span>Rally source</span>
            <span className={`badge ${rallyVerified ? "ok" : "neutral"}`}>{rallyVerified ? "connected" : "not verified"}</span></div></div>
          <div className="field"><div className="spread"><span>Jira target</span>
            <span className={`badge ${jiraVerified ? "ok" : "neutral"}`}>{jiraVerified ? "connected" : "not verified"}</span></div></div>
        </div>

        <div className="card">
          <p className="card-title">Recent runs</p>
          {jobs.length === 0 ? (
            <div className="empty">No migrations yet. <Link to="/migrate" className="btn ghost">Start one →</Link></div>
          ) : (
            <table className="table">
              <thead><tr><th>State</th><th>Created</th><th>Failed</th><th>Attachments</th></tr></thead>
              <tbody>
                {jobs.slice(0, 6).map((j) => (
                  <tr key={j.job_id}>
                    <td><span className={`badge ${j.state === "done" ? "ok" : j.state === "failed" ? "err" : "neutral"}`}>{j.state}</span></td>
                    <td>{j.created}</td><td>{j.failed}</td><td>{j.attachments_uploaded}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </>
  );
}

function StepCard({ n, title, body, to, done }: { n: number; title: string; body: string; to: string; done: boolean }) {
  return (
    <Link to={to} className="card" style={{ display: "block" }}>
      <div className="row" style={{ marginBottom: 8 }}>
        <span className={`step-num ${done ? "" : ""}`} style={{ background: done ? "var(--success)" : "var(--primary)", color: "white" }}>{done ? "✓" : n}</span>
        <strong>{title}</strong>
      </div>
      <p className="muted" style={{ margin: 0, fontSize: 13 }}>{body}</p>
    </Link>
  );
}
