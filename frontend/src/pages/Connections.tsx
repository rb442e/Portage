import { useState } from "react";
import { api } from "../api";
import { useApp } from "../store";
import type { ConnectionTestResult, JiraMetaField } from "../types";

export default function Connections() {
  const { jira, rally, setJira, setRally, setJiraVerified, setRallyVerified,
          jiraMeta, setJiraMeta,
          connectionsSaved, connectionsSavedAt, saveConnections, forgetConnections } = useApp();
  const [testing, setTesting] = useState(false);
  const [discovering, setDiscovering] = useState(false);
  const [saving, setSaving] = useState(false);
  const [results, setResults] = useState<ConnectionTestResult[]>([]);
  const [error, setError] = useState("");
  const [discoverMsg, setDiscoverMsg] = useState("");

  async function onSave() {
    setSaving(true); setError("");
    try { await saveConnections(); }
    catch (e: any) { setError(e.message || "Could not save credentials"); }
    finally { setSaving(false); }
  }

  async function test() {
    setTesting(true); setError(""); setResults([]);
    try {
      const res = await api.testConnections(
        jira.base_url ? jira : undefined,
        rally.api_key ? rally : undefined,
      );
      setResults(res);
      const jiraOk = res.some((r) => r.system === "jira" && r.ok);
      setJiraVerified(jiraOk);
      setRallyVerified(res.some((r) => r.system === "rally" && r.ok));
      if (jiraOk && jira.project_key) await discover();
    } catch (e: any) {
      setError(e.message || "Connection test failed");
    } finally {
      setTesting(false);
    }
  }

  async function discover() {
    setDiscovering(true); setDiscoverMsg("");
    try {
      const meta = await api.discoverJira(jira);
      setJiraMeta(meta);
      // Auto-fill any custom-field IDs we can confidently suggest (don't clobber
      // values the user has already typed).
      const s = meta.suggestions || {};
      const patch: Record<string, string> = {};
      (["sprint_field", "story_points_field", "team_field", "epic_link_field", "rally_id_field"] as const)
        .forEach((k) => { if (!(jira as any)[k] && s[k]) patch[k] = s[k]; });
      if (Object.keys(patch).length) setJira(patch as any);
      const filled = Object.keys(patch).length;
      setDiscoverMsg(
        `Found ${meta.issue_types.length} issue types and ${meta.custom_fields.length} custom fields`
        + (filled ? ` · auto-filled ${filled} field ID${filled > 1 ? "s" : ""}.` : ".")
      );
    } catch (e: any) {
      setDiscoverMsg(`Discovery failed: ${e.message}`);
    } finally {
      setDiscovering(false);
    }
  }

  const result = (sys: string) => results.find((r) => r.system === sys);
  const catalog = jiraMeta?.custom_fields ?? [];

  return (
    <>
      <div className="callout" style={{ marginBottom: 20 }}>
        🔒 API tokens are held in memory for this session only and are never written to disk or localStorage.
        They are sent to your backend solely to authenticate against Jira/Rally.
      </div>

      <div className="grid cols-2">
        {/* ---- Jira target ---- */}
        <div className="card">
          <div className="spread">
            <div>
              <p className="card-title">Jira — target</p>
              <p className="card-sub">Where work items will be created.</p>
            </div>
            <ResultBadge r={result("jira")} />
          </div>
          <div className="field">
            <label>Base URL</label>
            <input value={jira.base_url} placeholder="https://your-org.atlassian.net"
              onChange={(e) => setJira({ base_url: e.target.value })} />
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
              <label>Project key</label>
              <input value={jira.project_key} placeholder="TLPLSSIF" onChange={(e) => setJira({ project_key: e.target.value })} />
            </div>
          </div>
          <div className="field">
            <label>Email {jira.deployment === "server" ? "/ username" : ""}</label>
            <input value={jira.email} placeholder="you@company.com" onChange={(e) => setJira({ email: e.target.value })} />
          </div>
          <div className="field">
            <label>API token</label>
            <input type="password" value={jira.api_token} placeholder="paste token"
              onChange={(e) => setJira({ api_token: e.target.value })} />
            <div className="hint">Create at id.atlassian.com → Security → API tokens (Cloud), or a PAT (DC).</div>
          </div>

          <details>
            <summary style={{ cursor: "pointer", fontWeight: 600, margin: "6px 0" }}>Advanced — custom field IDs</summary>
            <p className="hint" style={{ marginTop: 8 }}>
              {catalog.length
                ? "Discovered from your Jira instance — pick from the dropdowns. Best guesses are pre-filled."
                : "Optional. Run “Discover fields” below to auto-detect these, or enter IDs manually."}
            </p>
            <div className="grid cols-2">
              <CustomFieldPicker label="Sprint field" value={jira.sprint_field} catalog={catalog} onChange={(v) => setJira({ sprint_field: v })} ph="customfield_10020" />
              <CustomFieldPicker label="Story points field" value={jira.story_points_field} catalog={catalog} onChange={(v) => setJira({ story_points_field: v })} ph="customfield_10016" />
              <CustomFieldPicker label="Team field" value={jira.team_field} catalog={catalog} onChange={(v) => setJira({ team_field: v })} ph="customfield_10001" />
              <CustomFieldPicker label="Epic link field" value={jira.epic_link_field} catalog={catalog} onChange={(v) => setJira({ epic_link_field: v })} ph="(blank = use parent)" />
              <CustomFieldPicker label="Rally ID field" value={jira.rally_id_field} catalog={catalog} onChange={(v) => setJira({ rally_id_field: v })} ph="customfield_12345" />
            </div>
          </details>
        </div>

        {/* ---- Rally source ---- */}
        <div className="card">
          <div className="spread">
            <div>
              <p className="card-title">Rally — source</p>
              <p className="card-sub">Optional. Needed only to pull attachments live from Rally.</p>
            </div>
            <ResultBadge r={result("rally")} />
          </div>
          <div className="field">
            <label>Base URL</label>
            <input value={rally.base_url} onChange={(e) => setRally({ base_url: e.target.value })} />
          </div>
          <div className="field">
            <label>API key</label>
            <input type="password" value={rally.api_key} placeholder="_abc123…"
              onChange={(e) => setRally({ api_key: e.target.value })} />
            <div className="hint">Rally → Settings → API Keys. Used only to download attachments.</div>
          </div>
          <div className="field">
            <label>Project ObjectID <span className="muted">(optional filter)</span></label>
            <input value={rally.project_object_id || ""} placeholder="e.g. 822923710301"
              onChange={(e) => setRally({ project_object_id: e.target.value })} />
            <div className="hint">Restrict Rally lookups to this project only — work items in any other project are skipped.</div>
          </div>
          <div className="callout" style={{ marginTop: 10 }}>
            You can migrate work items without Rally credentials by uploading a converted CSV.
            Rally creds unlock live attachment transfer.
          </div>
        </div>
      </div>

      <div className="card">
        <div className="btn-row">
          <button className="btn primary" onClick={test} disabled={testing || (!jira.base_url && !rally.api_key)}>
            {testing ? "Testing…" : "Test connections"}
          </button>
          <button className="btn" onClick={discover} disabled={discovering || !jira.base_url || !jira.api_token || !jira.project_key}>
            {discovering ? "Discovering…" : "Discover fields"}
          </button>
          <button className="btn" onClick={onSave} disabled={saving || (!jira.api_token && !rally.api_key)}>
            {saving ? "Saving…" : "Save credentials"}
          </button>
          {connectionsSaved && (
            <span className="row" style={{ gap: 8, alignSelf: "center" }}>
              <span className="badge ok" title={connectionsSavedAt ? `Saved ${connectionsSavedAt}` : undefined}>Saved · encrypted</span>
              <button className="btn ghost sm" onClick={forgetConnections}>Forget</button>
            </span>
          )}
        </div>
        {error && <p className="badge err" style={{ marginTop: 14 }}>{error}</p>}
        {results.map((r) => (
          <div key={r.system} className="field" style={{ marginTop: 12 }}>
            <div className="spread">
              <span><strong style={{ textTransform: "capitalize" }}>{r.system}</strong> — {r.ok ? r.account : r.detail}</span>
              <span className={`badge ${r.ok ? "ok" : "err"}`}>{r.ok ? "connected" : "failed"}</span>
            </div>
          </div>
        ))}
        {discoverMsg && <div className="callout" style={{ marginTop: 14 }}>🔎 {discoverMsg}</div>}
        {jiraMeta && jiraMeta.warnings.map((w, i) => (
          <div key={i} className="callout warn" style={{ marginTop: 8 }}>⚠ {w}</div>
        ))}
        {jiraMeta && jiraMeta.issue_types.length > 0 && (
          <div style={{ marginTop: 14 }}>
            <p className="card-sub" style={{ marginBottom: 8 }}>Issue types available in {jira.project_key}:</p>
            {jiraMeta.issue_types.map((t) => (
              <span key={t.id} className="tag">{t.name}{t.subtask ? " · sub-task" : ""}</span>
            ))}
          </div>
        )}
      </div>
    </>
  );
}

function CustomFieldPicker({ label, value, catalog, onChange, ph }: {
  label: string; value: string; catalog: JiraMetaField[]; onChange: (v: string) => void; ph: string;
}) {
  // With a discovered catalog, offer a dropdown of custom fields; otherwise a
  // plain text input for manual entry.
  if (catalog.length === 0) {
    return (
      <div className="field">
        <label>{label}</label>
        <input value={value} placeholder={ph} onChange={(e) => onChange(e.target.value)} />
      </div>
    );
  }
  const known = catalog.some((f) => f.id === value);
  return (
    <div className="field">
      <label>{label}</label>
      <select value={known || !value ? value : "__manual__"} onChange={(e) => onChange(e.target.value === "__manual__" ? value : e.target.value)}>
        <option value="">— skip this field —</option>
        {catalog.map((f) => <option key={f.id} value={f.id}>{f.name} ({f.id})</option>)}
        {value && !known && <option value={value}>{value} (manual)</option>}
      </select>
    </div>
  );
}

function Field({ label, value, ph, onChange }: { label: string; value: string; ph: string; onChange: (v: string) => void }) {
  return (
    <div className="field">
      <label>{label}</label>
      <input value={value} placeholder={ph} onChange={(e) => onChange(e.target.value)} />
    </div>
  );
}

function ResultBadge({ r }: { r?: ConnectionTestResult }) {
  if (!r) return <span className="badge neutral">not verified</span>;
  return <span className={`badge ${r.ok ? "ok" : "err"}`}>{r.ok ? "connected" : "failed"}</span>;
}
