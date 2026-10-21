import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { McpProbe, McpServerDef, McpServerDefs, McpServerInput, SettingsView } from "../types";
import { useDataChanged } from "../copilot/CopilotContext";

const NAME_RE = /^[a-z][a-z0-9_-]{0,31}$/;

const TEMPLATES = [
  { label: "Python module", command: "python3", args: "-m\nyour_mcp_server" },
  { label: "npx package", command: "npx", args: "-y\n@scope/your-mcp-server" },
  { label: "uvx package", command: "uvx", args: "your-mcp-server" },
];
const JIRA_PRESET = { label: "Atlassian Jira", name: "jira", url: "https://mcp.atlassian.com/v2/mcp" };

interface EnvRow { key: string; value: string; saved: boolean }
interface Form { name: string; transport: "stdio" | "http" | "sse"; url: string; command: string; args: string; cwd: string; env: EnvRow[]; enable: boolean }

const emptyForm = (): Form => ({ name: "", transport: "stdio", url: "", command: "", args: "", cwd: "", env: [], enable: true });
const fromDef = (d: McpServerDef, enabled: boolean): Form => ({
  name: d.name, transport: d.transport ?? "stdio", url: d.url ?? "", command: d.command ?? "", args: (d.args ?? []).join("\n"), cwd: d.cwd ?? "",
  env: (d.env_keys ?? []).map((key) => ({ key, value: "", saved: true })),
  ...(d.name === "jira" && !(d.env_keys ?? []).length ? { env: [{ key: "Authorization", value: "", saved: false }] } : {}), enable: enabled,
});
const toInput = (f: Form, current?: string | null): McpServerInput => ({
  name: f.name.trim().toLowerCase(), transport: f.transport, url: f.url.trim(), command: f.command.trim(),
  args: f.args.split("\n").map((a) => a.trim()).filter(Boolean), cwd: f.cwd.trim(),
  env: f.env.filter((r) => r.key.trim()).map((r) => ({ key: r.key.trim(), value: r.value })),
  enable_for_sora: f.enable, current: current ?? null,
});

function ProbeSummary({ probe }: { probe: McpProbe }) {
  if (probe.status !== "available") {
    return <div className="mcp-result bad"><b>Could not connect.</b> {probe.error || "The server did not start."}</div>;
  }
  return (
    <div className="mcp-result ok">
      <b>Connected.</b> {probe.tool_count} read-only tool{probe.tool_count === 1 ? "" : "s"} can be used by Sora
      {(probe.blocked_count ?? 0) > 0 && <>; {probe.blocked_count} blocked</>}.
      <ToolChips probe={probe} />
    </div>
  );
}

function ToolChips({ probe }: { probe: McpProbe }) {
  if (!probe.tools?.length && !probe.blocked?.length) return null;
  return (
    <div className="mcp-tools">
      {probe.tools?.map((t) => <span key={t} className="mcp-tool ok" title="Read-only tool; availability can be controlled below">{t}</span>)}
      {probe.blocked?.map((t) => <span key={t.name} className="mcp-tool blocked" title={`Blocked: ${t.reason}`}>{t.name}</span>)}
    </div>
  );
}

function ToolControls({ server, probe, disabledTools, busy, onChange }: {
  server: string; probe: McpProbe; disabledTools: string[]; busy: boolean;
  onChange: (toolName: string, available: boolean) => void;
}) {
  const tools = probe.tools ?? [];
  const [expanded, setExpanded] = useState<string | null>(null);
  if (!tools.length) return null;
  const availableCount = tools.filter((tool) => !disabledTools.includes(`ext_${server}__${tool}`)).length;
  const displayName = (name: string) => name.split(/[_-]+/).map((part) => {
    const upper = part.toUpperCase();
    return ["api", "mcp", "url", "jira", "ai"].includes(part.toLowerCase()) ? upper
      : part.charAt(0).toUpperCase() + part.slice(1);
  }).join(" ");
  return (
    <div className="mcp-tool-controls">
      <div className="mcp-tool-controls-head">
        <strong>Tools available to Sora</strong>
        <span className="mcp-tool-count">{availableCount} of {tools.length}</span>
      </div>
      <div className="mcp-tool-control-list">
        {tools.map((tool) => {
          const available = !disabledTools.includes(`ext_${server}__${tool}`);
          const isExpanded = expanded === tool;
          const detailsId = `mcp-tool-${server}-${tool}-details`;
          return (
            <div key={tool} className="mcp-tool-control-item">
              <div className="mcp-tool-control">
                <button type="button" className="mcp-tool-name" aria-expanded={isExpanded} aria-controls={detailsId}
                  onClick={() => setExpanded(isExpanded ? null : tool)}>
                  <span>{displayName(tool)}</span><span className={`mcp-tool-chevron ${isExpanded ? "open" : ""}`} aria-hidden="true">⌄</span>
                </button>
                <span className="mcp-tool-toggle">
                  <input type="checkbox" checked={available} disabled={busy}
                    aria-label={`${available ? "Disable" : "Enable"} ${displayName(tool)} for Sora`}
                    onChange={(e) => onChange(tool, e.target.checked)} />
                  <span className="mcp-tool-toggle-track" aria-hidden="true" />
                </span>
              </div>
              {isExpanded && (
                <div className="mcp-tool-details" id={detailsId}>
                  <p>{probe.tool_descriptions?.[tool] || "This tool does not provide a description."}</p>
                  <div><span>Server</span><strong>{server}</strong></div>
                  <div><span>Access</span><strong>Read-only</strong></div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function ServerDialog({ editing, enabled, onClose, onSaved }: {
  editing: McpServerDef | null; enabled: string[]; onClose: () => void; onSaved: (d: McpServerDefs) => void;
}) {
  const [form, setForm] = useState<Form>(() => editing ? fromDef(editing, enabled.includes(editing.name)) : emptyForm());
  const [error, setError] = useState("");
  const [probe, setProbe] = useState<McpProbe | null>(null);
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);
  const set = (patch: Partial<Form>) => { setForm({ ...form, ...patch }); setProbe(null); setError(""); };
  const setRow = (i: number, patch: Partial<EnvRow>) => set({ env: form.env.map((r, j) => j === i ? { ...r, ...patch } : r) });

  const nameOk = NAME_RE.test(form.name.trim().toLowerCase());
  const urlOk = /^https?:\/\//i.test(form.url.trim());
  const ready = (editing || nameOk) && (form.transport !== "stdio" ? urlOk : form.command.trim().length > 0);

  async function test() {
    setTesting(true); setError(""); setProbe(null);
    try { setProbe(await api.testMcpDraft(toInput(form, editing?.name))); }
    catch (e: any) { setError(e.message); }
    finally { setTesting(false); }
  }
  async function save() {
    setSaving(true); setError("");
    try {
      const body = toInput(form, editing?.name);
      onSaved(editing ? await api.updateMcpServer(editing.name, body) : await api.addMcpServer(body));
    } catch (e: any) { setError(e.message); }
    finally { setSaving(false); }
  }

  return (
    <div className="jc-modal-overlay" role="dialog" aria-modal="true" aria-label={editing ? "Edit MCP server" : "Add MCP server"}
      onMouseDown={(e) => { if (e.target === e.currentTarget && !saving) onClose(); }}>
      <div className="jc-modal mcp-modal">
        <div className="jc-modal-head">
          <h3>{editing ? `Edit ${editing.name}` : "Add MCP server"}</h3>
          <button className="jc-modal-x" onClick={onClose} aria-label="Close">✕</button>
        </div>
        <div className="jc-modal-body">
          <p className="mcp-lead">Connect a local process or remote MCP endpoint. Sora can only use tools the server marks as read-only.</p>

          {!editing && (
            <div className="mcp-templates">
              <span>Start from</span>
              {TEMPLATES.map((t) => (
                <button key={t.label} type="button" className="mcp-chip"
                  onClick={() => set({ command: t.command, args: t.args })}>{t.label}</button>
              ))}
              <button type="button" className="mcp-chip" onClick={() => set({ name: JIRA_PRESET.name, transport: "http", url: JIRA_PRESET.url, env: [{ key: "Authorization", value: "", saved: false }] })}>Atlassian Jira</button>
            </div>
          )}

          <div className="field"><label htmlFor="mcp-transport">Transport</label><select id="mcp-transport" value={form.transport} disabled={!!editing} onChange={(e) => set({ transport: e.target.value as Form["transport"] })}><option value="stdio">Local process (stdio)</option><option value="http">Remote server (Streamable HTTP)</option><option value="sse">Remote server (SSE)</option></select><div className="hint">Remote servers are contacted by Portage and can require header credentials.</div></div>

          <div className="field">
            <label htmlFor="mcp-name">Name</label>
            <input id="mcp-name" value={form.name} disabled={!!editing} placeholder="docs" autoComplete="off" spellCheck={false}
              onChange={(e) => set({ name: e.target.value })} />
            <div className={`hint ${form.name && !nameOk && !editing ? "bad" : ""}`}>
              {editing ? "A server's name cannot be changed."
                : "Lowercase letters, digits, - and _. Sora sees its tools as ext_<name>__<tool>."}
            </div>
          </div>

          {form.transport !== "stdio" ? <div className="field"><label htmlFor="mcp-url">Remote MCP URL</label><input id="mcp-url" className="mono" value={form.url} placeholder={form.transport === "sse" ? "https://example.com/sse" : "https://example.com/mcp"} autoComplete="url" onChange={(e) => set({ url: e.target.value })} /><div className="hint">Use the server’s {form.transport === "sse" ? "SSE" : "Streamable HTTP"} endpoint. Credentials belong in headers below.</div></div> : <>
          <div className="field">
            <label htmlFor="mcp-command">Command</label>
            <input id="mcp-command" className="mono" value={form.command} placeholder="/usr/local/bin/my-mcp-server  or  npx"
              autoComplete="off" spellCheck={false} onChange={(e) => set({ command: e.target.value })} />
            <div className="hint">An absolute path, or a program on Portage's PATH.</div>
          </div>

          <div className="field">
            <label htmlFor="mcp-args">Arguments</label>
            <textarea id="mcp-args" className="mono" rows={3} value={form.args} placeholder={"One argument per line\n-m\nmy_server"}
              spellCheck={false} onChange={(e) => set({ args: e.target.value })} />
          </div>

          <div className="field">
            <label htmlFor="mcp-cwd">Working directory <span className="mcp-opt">optional</span></label>
            <input id="mcp-cwd" className="mono" value={form.cwd} placeholder="/absolute/path/to/folder" autoComplete="off"
              spellCheck={false} onChange={(e) => set({ cwd: e.target.value })} />
          </div>
          </>}

          <div className="field">
            <label>{form.transport === "http" ? "Request headers" : "Environment variables"} <span className="mcp-opt">optional</span></label>
            {form.env.map((r, i) => (
              <div className="mcp-env-row" key={i}>
                <input className="mono" value={r.key} placeholder={form.transport === "http" ? "Authorization" : "API_TOKEN"} aria-label={form.transport === "http" ? "Header name" : "Variable name"} autoComplete="off"
                  spellCheck={false} disabled={r.saved} onChange={(e) => setRow(i, { key: e.target.value })} />
                <input type="password" value={r.value} aria-label={`Value for ${r.key || "variable"}`} autoComplete="new-password"
                  placeholder={r.saved ? "Unchanged (stored encrypted)" : form.name === "jira" && r.key === "Authorization" ? "Bearer <Atlassian service account API key>" : "Value"} onChange={(e) => setRow(i, { value: e.target.value })} />
                <button type="button" className="btn ghost sm" aria-label="Remove variable"
                  onClick={() => set({ env: form.env.filter((_, j) => j !== i) })}>Remove</button>
              </div>
            ))}
            <button type="button" className="btn sm" onClick={() => set({ env: [...form.env, { key: "", value: "", saved: false }] })}>Add variable</button>
            <div className="hint">{form.transport !== "stdio" ? <>Headers are sent only to this endpoint. Values are encrypted at rest and never shown again.{form.name === "jira" && <> Atlassian returns 401 until you add credentials. Use <code>Bearer &lt;service account API key&gt;</code>, or <code>Basic &lt;base64(email:api_token)&gt;</code> for a personal token. API token access must be enabled by your Atlassian organization. <a href="https://support.atlassian.com/atlassian-ai-gateway/docs/configure-authentication-via-api-token/" target="_blank" rel="noreferrer">Authentication setup</a>.</>}</> : "The server only receives these variables plus PATH and HOME. Values are encrypted at rest and never shown again."}</div>
          </div>

          {!editing && (
            <label className="st-switch mcp-enable">
              <input type="checkbox" checked={form.enable} onChange={(e) => set({ enable: e.target.checked })} />
              <span>Make its read-only tools available to Sora after saving</span>
            </label>
          )}

          {error && <div className="mcp-result bad" role="alert">{error}</div>}
          {probe && <ProbeSummary probe={probe} />}
        </div>
        <div className="jc-modal-foot mcp-foot">
          {!ready && <span className="hint mcp-validation">{!editing && !nameOk ? "Enter a valid server name." : form.transport !== "stdio" && !urlOk ? "Enter a valid HTTP or HTTPS URL." : "Enter a command."}</span>}
          <button type="button" className="btn" onClick={() => void test()} disabled={!ready || testing || saving}>
            {testing ? "Testing…" : "Test connection"}
          </button>
          <span className="mcp-spacer" />
          <button type="button" className="btn ghost" onClick={onClose} disabled={saving}>Cancel</button>
          <button type="button" className="btn primary" onClick={() => void save()} disabled={!ready || saving || testing}>
            {saving ? "Saving…" : editing ? "Save changes" : "Add server"}
          </button>
        </div>
      </div>
    </div>
  );
}

function ServerCard({ def, probe, checking, enabled, canEdit, busy, disabledTools, onToggle, onToggleTool, onTest, onEdit, onRemove }: {
  def: McpServerDef; probe?: McpProbe; checking: boolean; enabled: boolean; canEdit: boolean; busy: boolean;
  disabledTools: string[]; onToggle: (on: boolean) => void;
  onToggleTool: (toolName: string, available: boolean) => void;
  onTest: () => void; onEdit: () => void; onRemove: () => void;
}) {
  const [confirm, setConfirm] = useState(false);
  const state = checking ? "idle" : probe ? (probe.status === "available" ? "ok" : "err") : "idle";
  const isUi = def.source === "ui";
  const preview = isUi ? (def.transport && def.transport !== "stdio" ? def.url : [def.command, ...(def.args ?? [])].join(" ")) : "Defined by an administrator in PORTAGE_EXTERNAL_MCP_SERVERS";
  return (
    <div className="mcp-card">
      <div className="mcp-card-head">
        <span className={`dot ${state}`} title={checking ? "Checking" : probe?.status ?? "Not checked"} />
        <strong className="mcp-name">{def.name}</strong>
        <span className={`badge ${isUi ? "neutral" : "warn"}`}>{isUi ? "Added in Settings" : "Environment"}</span>
        {probe && !checking && (
          <span className={`badge ${probe.status === "available" ? "ok" : "err"}`}>
            {probe.status === "available" ? "Connected" : "Unavailable"}
          </span>
        )}
        {checking && <span className="badge neutral">Checking…</span>}
        <span className="mcp-spacer" />
        <label className="st-switch" title="Let Sora use this server's read-only tools">
          <input type="checkbox" checked={enabled} disabled={busy} onChange={(e) => onToggle(e.target.checked)} />
          <span>Available to Sora</span>
        </label>
      </div>
      <div className={`mcp-command ${isUi ? "" : "plain"}`} title={isUi ? preview : undefined}>{preview}</div>
      {probe && !checking && (probe.status === "available" ? (
        <>
          {(probe.blocked_count ?? 0) > 0 && <p className="mcp-summary">{probe.blocked_count} tool{probe.blocked_count === 1 ? "" : "s"} blocked by the read-only policy</p>}
          <ToolControls server={def.name} probe={probe} disabledTools={disabledTools} busy={busy} onChange={onToggleTool} />
        </>
      ) : <div className="mcp-result bad">{probe.error || "The server did not start."}</div>)}
      <div className="mcp-actions">
        <button className="btn sm" onClick={onTest} disabled={checking}>Test</button>
        {isUi && <button className="btn sm" onClick={onEdit} disabled={!canEdit} title={canEdit ? "" : "Editing is locked"}>Edit</button>}
        {isUi && !confirm && <button className="btn ghost sm mcp-danger" onClick={() => setConfirm(true)} disabled={!canEdit}>Remove</button>}
        {isUi && confirm && (
          <span className="mcp-confirm">
            Remove this server?
            <button className="btn sm mcp-danger-solid" onClick={onRemove} disabled={busy}>Remove</button>
            <button className="btn ghost sm" onClick={() => setConfirm(false)}>Cancel</button>
          </span>
        )}
      </div>
    </div>
  );
}

export default function ExternalMcpPanel({ enabled, onSettingsView }: { enabled: string[]; onSettingsView: (v: SettingsView) => void }) {
  const [defs, setDefs] = useState<McpServerDefs | null>(null);
  const [probes, setProbes] = useState<Record<string, McpProbe>>({});
  const [checking, setChecking] = useState<Record<string, boolean>>({});
  const [dialog, setDialog] = useState<{ editing: McpServerDef | null } | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null);
  const alive = useRef(true);
  useEffect(() => {
    // React StrictMode runs setup → cleanup → setup in development. Reset the
    // flag on setup so async probe results and their checking state still land.
    alive.current = true;
    return () => { alive.current = false; };
  }, []);

  useDataChanged(["mcp_servers"], () => {
    Promise.all([api.mcpServers(), api.settings()]).then(([d, v]) => { setDefs(d); onSettingsView(v); })
      .catch((e) => setNotice({ ok: false, text: e.message }));
  });

  const probeOne = useCallback(async (name: string) => {
    setChecking((c) => ({ ...c, [name]: true }));
    try {
      const p = await api.testMcpServer(name);
      if (alive.current) setProbes((all) => ({ ...all, [name]: p }));
    } catch (e: any) {
      if (alive.current) setProbes((all) => ({ ...all, [name]: { name, status: "unavailable", tool_count: 0, error: e.message } }));
    } finally {
      if (alive.current) setChecking((c) => ({ ...c, [name]: false }));
    }
  }, []);

  const probeAll = useCallback(async (names: string[]) => {
    for (const n of names) { if (!alive.current) return; await probeOne(n); }
  }, [probeOne]);

  useEffect(() => {
    api.mcpServers().then((d) => { setDefs(d); void probeAll(d.servers.map((s) => s.name)); })
      .catch((e) => setNotice({ ok: false, text: e.message }));
  }, [probeAll]);

  async function toggle(name: string, on: boolean) {
    if (!defs) return;
    setBusy(true); setNotice(null);
    const next = on ? [...enabled, name] : enabled.filter((n) => n !== name);
    try {
      const view = await api.saveSettings("mcp", { external_servers: next });
      onSettingsView(view);
    } catch (e: any) { setNotice({ ok: false, text: e.message }); }
    finally { setBusy(false); }
  }

  async function toggleTool(server: string, toolName: string, available: boolean) {
    if (!defs) return;
    const fullName = `ext_${server}__${toolName}`;
    const current = defs.disabled_tools ?? [];
    const next = available ? current.filter((name) => name !== fullName)
      : current.includes(fullName) ? current : [...current, fullName];
    setBusy(true); setNotice(null);
    try {
      setDefs(await api.saveExternalMcpToolAccess(next));
      setNotice({ ok: true, text: `${toolName} ${available ? "enabled" : "disabled"} for Sora.` });
    } catch (e: any) { setNotice({ ok: false, text: e.message }); }
    finally { setBusy(false); }
  }

  async function remove(name: string) {
    setBusy(true); setNotice(null);
    try {
      const d = await api.deleteMcpServer(name);
      setDefs(d); setProbes(({ [name]: _gone, ...rest }) => rest);
      setNotice({ ok: true, text: `Removed ${name}.` });
      onSettingsView(await api.settings());
    } catch (e: any) { setNotice({ ok: false, text: e.message }); }
    finally { setBusy(false); }
  }

  async function saved(d: McpServerDefs, name?: string) {
    setDefs(d); setDialog(null);
    setNotice({ ok: true, text: "Server saved." });
    onSettingsView(await api.settings());
    if (name) void probeOne(name);
  }

  if (!defs) return <div className="card muted">{notice ? notice.text : "Loading external MCP servers…"}</div>;
  const canEdit = defs.editing_enabled;
  const full = defs.servers.length >= defs.max_servers;
  return (
    <div className="card mcp-panel">
      <div className="mcp-head">
        <div>
          <p className="card-title">External MCP servers</p>
          <p className="card-sub">Connect MCP servers and choose which read-only tools Sora may call. Write-capable tools are always blocked.</p>
        </div>
        <div className="btn-row">
          <button className="btn" disabled={Object.values(checking).some(Boolean) || defs.servers.length === 0}
            onClick={() => void probeAll(defs.servers.map((s) => s.name))}>Test all</button>
          <button className="btn primary" disabled={!canEdit || full} onClick={() => setDialog({ editing: null })}
            title={!canEdit ? "Locked by the administrator" : full ? `Limit of ${defs.max_servers} servers reached` : ""}>
            Add server
          </button>
        </div>
      </div>

      {!canEdit && (
        <div className="mcp-lock" role="note">
          <span className="mcp-lock-ico" aria-hidden>🔒</span>
          <div>
            <strong>Adding servers is turned off</strong>
            <p>Starting a server runs a program on this computer. It's allowed for admins when sign-in is on; otherwise
              start Portage with{" "}<code>{defs.flag}=1</code> and reload this page. Servers defined by an administrator below still work.</p>
          </div>
        </div>
      )}
      {defs.config_error && <div className="mcp-result bad">PORTAGE_EXTERNAL_MCP_SERVERS is invalid: {defs.config_error}</div>}
      {notice && <div className={`st-msg ${notice.ok ? "ok" : "bad"}`}>{notice.text}</div>}

      {defs.servers.length === 0 ? (
        <div className="mcp-empty">
          <strong>No external servers yet</strong>
          <p>{canEdit ? "Add a server to give Sora more read-only tools, such as documentation or search." : "Ask an administrator to enable adding servers, or define them in PORTAGE_EXTERNAL_MCP_SERVERS."}</p>
        </div>
      ) : defs.servers.map((s) => (
        <ServerCard key={s.name} def={s} probe={probes[s.name]} checking={!!checking[s.name]} busy={busy}
          enabled={enabled.includes(s.name)} canEdit={canEdit} disabledTools={defs.disabled_tools ?? []}
          onToggle={(on) => void toggle(s.name, on)} onToggleTool={(tool, available) => void toggleTool(s.name, tool, available)} onTest={() => void probeOne(s.name)}
          onEdit={() => setDialog({ editing: s })} onRemove={() => void remove(s.name)} />
      ))}

      <p className="hint mcp-trust">
        Only add servers you trust: Portage starts them on this computer and sends them the arguments Sora chooses.
        Tool safety labels come from the server itself and are not an enforced permission.
      </p>

      {dialog && (
        <ServerDialog editing={dialog.editing} enabled={enabled} onClose={() => setDialog(null)}
          onSaved={(d) => void saved(d, dialog.editing?.name ?? d.servers[d.servers.length - 1]?.name)} />
      )}
    </div>
  );
}
