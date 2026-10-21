import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import ExternalMcpPanel from "./ExternalMcpPanel";
import type { McpConnection, SettingsField, SettingsSection, SettingsView, SettingValue } from "../types";

type Drafts = Record<string, Record<string, SettingValue>>;
const same = (a: SettingValue, b: SettingValue) => JSON.stringify(a) === JSON.stringify(b);

function Control({ f, value, onChange }: { f: SettingsField; value: SettingValue; onChange: (v: SettingValue) => void }) {
  switch (f.type) {
    case "bool":
      return (
        <label className="st-switch">
          <input type="checkbox" checked={value as boolean} onChange={(e) => onChange(e.target.checked)} />
          <span>{value ? "On" : "Off"}</span>
        </label>
      );
    case "int":
      return <input type="number" min={f.min ?? undefined} max={f.max ?? undefined} value={value as number}
        onChange={(e) => onChange(e.target.value === "" ? "" : Number(e.target.value))} />;
    case "choice":
      return (
        <select value={value as string} onChange={(e) => onChange(e.target.value)}>
          {f.choices.map((c) => <option key={c} value={c}>{f.labels[c] ?? c}</option>)}
        </select>
      );
    case "multi": {
      const chosen = value as string[];
      const toggle = (c: string) => onChange(chosen.includes(c) ? chosen.filter((x) => x !== c) : [...chosen, c]);
      return (
        <div className="st-multi">
          {f.choices.map((c) => (
            <label key={c} className={c.startsWith("propose_") ? "write" : ""}>
              <input type="checkbox" checked={chosen.includes(c)} onChange={() => toggle(c)} /> {c}
            </label>
          ))}
        </div>
      );
    }
    default:
      return <input value={value as string} onChange={(e) => onChange(e.target.value)} />;
  }
}

function SourceBadge({ f }: { f: SettingsField }) {
  if (f.source === "saved") return <span className="badge ok">saved</span>;
  if (f.source === "env") return <span className="badge warn" title={f.env}>from environment</span>;
  return <span className="badge neutral">default</span>;
}

function SectionForm({ section, draft, setDraft, onSave, onReset, busy }: {
  section: SettingsSection; draft: Record<string, SettingValue>;
  setDraft: (key: string, v: SettingValue) => void;
  onSave: () => void; onReset: (key?: string) => void; busy: boolean;
}) {
  const fields = section.fields.filter((f) => !f.hidden);
  const dirty = fields.some((f) => !same(draft[f.key], f.value));
  const anySaved = fields.some((f) => f.source === "saved");
  return (
    <div className="card">
      <p className="card-title">{section.label}</p>
      <p className="card-sub">{section.summary}</p>
      {fields.map((f) => (
        <div className="st-field" key={f.key}>
          <div className="st-label">
            <span>{f.label}</span>
            <SourceBadge f={f} />
            {f.help && <div className="hint">{f.help}{f.env && <> Env: <code>{f.env}</code></>}</div>}
          </div>
          <div className="st-control">
            <Control f={f} value={draft[f.key]} onChange={(v) => setDraft(f.key, v)} />
            {f.source === "saved" && (
              <button className="btn ghost sm" onClick={() => onReset(f.key)} disabled={busy}>Reset</button>
            )}
          </div>
        </div>
      ))}
      <div className="btn-row" style={{ marginTop: 6 }}>
        <button className="btn primary" disabled={!dirty || busy} onClick={onSave}>Save changes</button>
        {anySaved && <button className="btn" disabled={busy} onClick={() => onReset()}>Reset section</button>}
      </div>
    </div>
  );
}

function CopyBlock({ text }: { text: string }) {
  const [done, setDone] = useState(false);
  return (
    <div className="st-code">
      <button className="btn sm" onClick={async () => {
        try { await navigator.clipboard.writeText(text); setDone(true); setTimeout(() => setDone(false), 1500); } catch { /* clipboard blocked */ }
      }}>{done ? "Copied" : "Copy"}</button>
      <pre>{text}</pre>
    </div>
  );
}

function McpConnect() {
  const [conn, setConn] = useState<McpConnection | null>(null);
  const [tab, setTab] = useState<"vscode" | "generic" | "shell">("vscode");
  useEffect(() => { api.mcpConnection().then(setConn).catch(() => setConn(null)); }, []);
  if (!conn) return null;
  return (
    <div className="card">
      <p className="card-title">Connect an MCP client</p>
      <p className="card-sub">
        Portage's MCP server runs over stdio: your client starts it. These values are for this installation.
        Approvals stay in Portage: agents can only propose, and you apply under Ask Sora, History.
      </p>
      <div className="st-tabs small">
        <button className={tab === "vscode" ? "on" : ""} onClick={() => setTab("vscode")}>VS Code (mcp.json)</button>
        <button className={tab === "generic" ? "on" : ""} onClick={() => setTab("generic")}>Other clients</button>
        <button className={tab === "shell" ? "on" : ""} onClick={() => setTab("shell")}>Run manually</button>
      </div>
      <CopyBlock text={tab === "vscode" ? conn.vscode : tab === "generic" ? conn.generic : conn.shell} />
    </div>
  );
}

export default function Settings() {
  const [view, setView] = useState<SettingsView | null>(null);
  const [drafts, setDrafts] = useState<Drafts>({});
  const [tab, setTab] = useState("sora");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const adopt = (v: SettingsView) => {
    setView(v);
    setDrafts(Object.fromEntries(v.sections.map((s) => [s.key, Object.fromEntries(s.fields.map((f) => [f.key, f.value]))])));
  };
  useEffect(() => { api.settings().then(adopt).catch((e) => setMsg({ ok: false, text: e.message })); }, []);

  const section = useMemo(() => view?.sections.find((s) => s.key === tab), [view, tab]);

  async function run(action: () => Promise<SettingsView>, done: string) {
    setBusy(true); setMsg(null);
    try { adopt(await action()); setMsg({ ok: true, text: done }); }
    catch (e: any) { setMsg({ ok: false, text: e.message }); }
    finally { setBusy(false); }
  }

  function save(s: SettingsSection) {
    const changed = Object.fromEntries(s.fields.filter((f) => !f.hidden && !same(drafts[s.key][f.key], f.value)).map((f) => [f.key, drafts[s.key][f.key]]));
    return run(() => api.saveSettings(s.key, changed), `${s.label} settings saved`);
  }

  if (!view) return <div className="card muted">{msg ? msg.text : "Loading settings…"}</div>;
  const eff = view.effective_mcp;
  return (
    <div className="st">
      <header className="st-head">
        <h1 className="st-h1">Settings</h1>
        <p className="muted">Product settings. A saved value wins over an environment variable, which wins over the default.</p>
      </header>

      <div className="st-tabs">
        {view.sections.map((s) => <button key={s.key} className={tab === s.key ? "on" : ""} onClick={() => { setTab(s.key); setMsg(null); }}>{s.label}</button>)}
        <button className={tab === "system" ? "on" : ""} onClick={() => { setTab("system"); setMsg(null); }}>System</button>
      </div>

      {msg && <div className={`st-msg ${msg.ok ? "ok" : "bad"}`}>{msg.text}</div>}

      {tab === "mcp" && (
        <div className={`st-msg ${eff.enabled ? "ok" : "bad"}`}>
          {!eff.enabled ? "MCP access is off: connected clients see no tools."
            : <>MCP clients can currently <b>{eff.read_only ? "read only" : "read and propose changes"}</b>
              {eff.hidden_tools.length > 0 && <>, with {eff.hidden_tools.length} tool{eff.hidden_tools.length > 1 ? "s" : ""} hidden</>}.
              {eff.read_only && drafts.mcp && !drafts.mcp.read_only && " Sora's mode is read-only, which also applies to MCP."}</>}
        </div>
      )}

      {section && (
        <SectionForm section={section} draft={drafts[section.key] ?? {}} busy={busy}
          setDraft={(k, v) => setDrafts({ ...drafts, [section.key]: { ...drafts[section.key], [k]: v } })}
          onSave={() => save(section)}
          onReset={(key) => run(() => api.resetSetting(section.key, key), key ? "Reset to default" : `${section.label} reset`)} />
      )}
      {tab === "mcp" && <>
        <ExternalMcpPanel enabled={eff.external_servers} onSettingsView={setView} />
        <McpConnect />
      </>}

      {tab === "system" && (
        <div className="card">
          <p className="card-title">System</p>
          <p className="card-sub">Set by environment variables when Portage starts. Change them and restart to apply.</p>
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Item</th><th>Value</th><th>Environment variable</th></tr></thead>
              <tbody>
                {view.system.map((r) => (
                  <tr key={r.label}><td>{r.label}</td><td style={{ whiteSpace: "normal", wordBreak: "break-all" }}>{r.value}</td><td>{r.env ? <code>{r.env}</code> : "—"}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="hint" style={{ marginTop: 10 }}>Secrets such as Jira and Rally tokens are never stored in settings.</p>
        </div>
      )}
    </div>
  );
}
