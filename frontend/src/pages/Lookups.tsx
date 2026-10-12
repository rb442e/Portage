import { useEffect, useRef, useState, type ReactNode } from "react";
import { api } from "../api";
import LookupHistory from "../components/LookupHistory";
import { useCopilotPage, useDataChanged } from "../copilot/CopilotContext";
import type { LookupCsvPreview, LookupKind, LookupTable } from "../types";

interface Row { source: string; target: string; }

const KINDS: { kind: LookupKind; label: string; src: string; tgt: string; blurb: string }[] = [
  { kind: "sprint", label: "Sprint", src: "Rally iteration / sprint", tgt: "Jira sprint (name or ID)",
    blurb: "Translate Rally iteration names to the sprints in your Jira board." },
  { kind: "version", label: "Version", src: "Rally release / milestone", tgt: "Jira fix version (name or ID)",
    blurb: "Map Rally releases and milestones to the fix versions in your Jira project." },
  { kind: "user", label: "User", src: "Rally user", tgt: "Jira user (email or accountId)",
    blurb: "Map Rally owners and creators to the matching Jira account." },
  { kind: "team", label: "Team", src: "Rally team", tgt: "Jira team (name or Atlassian Team ID)",
    blurb: "Map Rally teams to their Jira team or Atlassian Team ID." },
];

const svg = { fill: "none", stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
const IconSprint = () => (<svg width="20" height="20" viewBox="0 0 24 24" {...svg}><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M9 4v16M15 4v16" /></svg>);
const IconVersion = () => (<svg width="20" height="20" viewBox="0 0 24 24" {...svg}><path d="M20.6 13.4l-7.2 7.2a2 2 0 0 1-2.8 0L2 12V2h10l8.6 8.6a2 2 0 0 1 0 2.8z" /><circle cx="7" cy="7" r="1.3" fill="currentColor" stroke="none" /></svg>);
const IconUser = () => (<svg width="20" height="20" viewBox="0 0 24 24" {...svg}><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" /><circle cx="12" cy="7" r="4" /></svg>);
const IconTeam = () => (<svg width="20" height="20" viewBox="0 0 24 24" {...svg}><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" /><circle cx="9" cy="7" r="4" /><path d="M23 21v-2a4 4 0 0 0-3-3.87M16 3.1a4 4 0 0 1 0 7.75" /></svg>);
const IconImport = () => (<svg width="16" height="16" viewBox="0 0 24 24" {...svg}><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><path d="M7 10l5 5 5-5M12 15V3" /></svg>);
const IconPlus = () => (<svg width="16" height="16" viewBox="0 0 24 24" {...svg}><path d="M12 5v14M5 12h14" /></svg>);
const IconTrash = () => (<svg width="16" height="16" viewBox="0 0 24 24" {...svg}><path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m2 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" /></svg>);
const IconClose = () => (<svg width="20" height="20" viewBox="0 0 24 24" {...svg}><path d="M18 6L6 18M6 6l12 12" /></svg>);
const IconInfo = () => (<svg width="18" height="18" viewBox="0 0 24 24" {...svg}><circle cx="12" cy="12" r="10" /><path d="M12 16v-4M12 8h.01" /></svg>);
const IconEmpty = () => (<svg width="46" height="46" viewBox="0 0 24 24" {...svg}><rect x="3" y="5" width="18" height="14" rx="2" /><path d="M3 10h18M9 5v14" /></svg>);

const ICONS: Record<LookupKind, ReactNode> = { sprint: <IconSprint />, version: <IconVersion />, user: <IconUser />, team: <IconTeam /> };

function entriesToRows(entries: Record<string, string>): Row[] {
  return Object.entries(entries).map(([source, target]) => ({ source, target }));
}
function rowsToEntries(rows: Row[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const r of rows) {
    const s = r.source.trim();
    if (s) out[s] = r.target.trim();
  }
  return out;
}

export default function Lookups() {
  const [kind, setKind] = useState<LookupKind>("sprint");
  const [table, setTable] = useState<LookupTable | null>(null);
  const [name, setName] = useState("");
  const [rows, setRows] = useState<Row[]>([]);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [dirty, setDirty] = useState(false);
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);
  const [importOpen, setImportOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);

  const meta = KINDS.find((k) => k.kind === kind)!;

  useCopilotPage({ lookup_kind: kind });
  // Reload after the copilot changes a catalog, unless the user has unsaved edits.
  useDataChanged(["lookups"], () => { refreshCounts(); if (!dirty) load(kind); else setStatus("The copilot changed this catalog. Save or discard your edits, then reload."); });

  useEffect(() => { load(kind); }, [kind]);  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { refreshCounts(); }, []);

  async function refreshCounts() {
    try {
      const all = await api.listLookups();
      const c: Record<string, number> = {};
      for (const lk of all) c[lk.kind] = (c[lk.kind] ?? 0) + Object.keys(lk.entries).length;
      setCounts(c);
    } catch { /* ignore */ }
  }

  async function load(k: LookupKind) {
    setStatus(""); setDirty(false);
    const label = KINDS.find((x) => x.kind === k)!.label;
    try {
      const list = await api.listLookups(k);
      const t = list[0] ?? null;
      setTable(t);
      setName(t?.name ?? `${label} catalog`);
      setRows(t ? entriesToRows(t.entries) : []);
    } catch {
      setTable(null); setName(`${label} catalog`); setRows([]);
    }
  }

  function updateRow(i: number, patch: Partial<Row>) {
    setRows((rs) => rs.map((r, idx) => (idx === i ? { ...r, ...patch } : r)));
    setDirty(true);
  }
  function addRow() { setRows((rs) => [...rs, { source: "", target: "" }]); setDirty(true); }
  function removeRow(i: number) { setRows((rs) => rs.filter((_, idx) => idx !== i)); setDirty(true); }
  function clearRows() { setRows([]); setDirty(true); }

  async function save() {
    setBusy(true); setStatus("Saving…");
    try {
      const payload: LookupTable = {
        id: table?.id,
        name: name.trim() || `${meta.label} catalog`,
        kind,
        side: "rally_to_jira",
        entries: rowsToEntries(rows),
      };
      const saved = await api.saveLookup(payload);
      setTable(saved); setRows(entriesToRows(saved.entries)); setDirty(false);
      setStatus(`Saved ${Object.keys(saved.entries).length} mappings`);
      refreshCounts();
    } catch (e: any) { setStatus(e.message); } finally { setBusy(false); }
  }

  async function removeCatalog() {
    if (!table?.id) { setRows([]); setName(`${meta.label} catalog`); setDirty(false); return; }
    setBusy(true);
    try {
      await api.deleteLookup(table.id);
      setTable(null); setRows([]); setName(`${meta.label} catalog`); setDirty(false);
      setStatus("Catalog deleted");
      refreshCounts();
    } catch (e: any) { setStatus(e.message); } finally { setBusy(false); }
  }

  function onImported(entries: Record<string, string>, mode: "replace" | "merge") {
    setRows((rs) => {
      if (mode === "replace") return entriesToRows(entries);
      const map = new Map(rs.map((r) => [r.source.trim(), r.target] as const));
      for (const [s, t] of Object.entries(entries)) map.set(s, t);
      return Array.from(map, ([source, target]) => ({ source, target }));
    });
    setDirty(true);
    setImportOpen(false);
    setStatus(`Loaded ${Object.keys(entries).length} rows from CSV — review and Save`);
  }

  const countFor = (k: LookupKind) => (k === kind ? rows.length : counts[k] ?? 0);

  return (
    <div className="jc">
      <header className="jc-head">
        <div className="jc-head-icon">
          <svg width="26" height="26" viewBox="0 0 24 24" {...svg}><path d="M4 7h16M4 12h16M4 17h16" /><circle cx="8" cy="7" r="0" /></svg>
        </div>
        <div>
          <h1 className="jc-title">Jira Catalog</h1>
          <p className="jc-desc">Map Rally values to their Jira equivalents. Applied automatically during migration.</p>
        </div>
      </header>

      <div className="jc-shell">
        <nav className="jc-nav">
          <div className="jc-nav-title">Fields</div>
          {KINDS.map((k) => (
            <button key={k.kind} className={`jc-nav-item ${k.kind === kind ? "active" : ""}`} onClick={() => setKind(k.kind)}>
              <span className="jc-nav-ico">{ICONS[k.kind]}</span>
              {k.label}
              <span className="jc-nav-count">{countFor(k.kind)}</span>
            </button>
          ))}
        </nav>

        <section className="jc-panel">
          <div className="jc-panel-head">
            <div>
              <h2 className="jc-panel-title">{meta.label} mappings</h2>
              <p className="jc-panel-sub">{meta.blurb}</p>
            </div>
            <div className="jc-actions">
              <button className="jc-btn" onClick={() => setImportOpen(true)}><IconImport /> Import CSV</button>
              {table?.id && <button className="jc-btn" onClick={() => setHistoryOpen(true)}>History</button>}
              <button className="jc-btn primary" onClick={save} disabled={busy}>{busy ? "Saving…" : "Save"}</button>
            </div>
          </div>

          <div className="jc-toolbar">
            <div className="jc-name-field">
              <input value={name} onChange={(e) => { setName(e.target.value); setDirty(true); }} placeholder="Catalog name" />
            </div>
            <span className="jc-loz default">{rows.length} {rows.length === 1 ? "row" : "rows"}</span>
            {dirty && <span className="jc-loz moved">Unsaved</span>}
          </div>

          {rows.length === 0 ? (
            <div className="jc-empty">
              <div className="jc-empty-ico"><IconEmpty /></div>
              <h4>No {meta.label.toLowerCase()} mappings yet</h4>
              <p>Add a row or import a CSV to translate Rally {meta.label.toLowerCase()} values into Jira.</p>
            </div>
          ) : (
            <table className="jc-table">
              <thead>
                <tr>
                  <th>{meta.src}</th>
                  <th className="jc-th-arrow"></th>
                  <th>{meta.tgt}</th>
                  <th className="jc-th-act"></th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => (
                  <tr key={i}>
                    <td><input className="jc-cell-input" value={r.source} placeholder={meta.src}
                      onChange={(e) => updateRow(i, { source: e.target.value })} /></td>
                    <td className="jc-arrow">→</td>
                    <td><input className="jc-cell-input" value={r.target} placeholder={meta.tgt}
                      onChange={(e) => updateRow(i, { target: e.target.value })} /></td>
                    <td>
                      <button className="jc-row-del" onClick={() => removeRow(i)} title="Remove row"><IconTrash /></button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          <div className="jc-foot">
            <button className="jc-btn" onClick={addRow}><IconPlus /> Add row</button>
            {rows.length > 0 && <button className="jc-btn subtle" onClick={clearRows}>Clear all</button>}
            <span className="jc-spacer" />
            {status && <span className="jc-status">{status}</span>}
            {table?.id && <button className="jc-btn danger" onClick={removeCatalog} disabled={busy}><IconTrash /> Delete catalog</button>}
          </div>

          <div className="jc-section-msg">
            <span className="ico"><IconInfo /></span>
            <div>Each row maps a <strong>{meta.src}</strong> to a <strong>{meta.tgt}</strong>. These translations run automatically when you migrate to Jira.</div>
          </div>
        </section>
      </div>

      {importOpen && <ImportModal kind={kind} meta={meta} onClose={() => setImportOpen(false)} onImported={onImported} />}
      {historyOpen && table?.id && (
        <LookupHistory lookupId={table.id} label={meta.label} onClose={() => setHistoryOpen(false)}
          onRestored={() => { load(kind); refreshCounts(); setStatus("Catalog restored"); }} />
      )}
    </div>
  );
}

function ImportModal({ kind, meta, onClose, onImported }: {
  kind: LookupKind;
  meta: { label: string; src: string; tgt: string };
  onClose: () => void;
  onImported: (entries: Record<string, string>, mode: "replace" | "merge") => void;
}) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<LookupCsvPreview | null>(null);
  const [sourceCol, setSourceCol] = useState("");
  const [targetCol, setTargetCol] = useState("");
  const [mode, setMode] = useState<"replace" | "merge">("replace");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  async function onFile(f: File) {
    setFile(f); setMsg("Parsing…"); setPreview(null);
    try {
      const p = await api.parseLookupCsv(f, kind);
      setPreview(p);
      setSourceCol(p.suggested_source || p.columns[0] || "");
      setTargetCol(p.suggested_target || p.columns[1] || p.columns[0] || "");
      setMsg("");
    } catch (e: any) { setMsg(e.message); }
  }

  async function doLoad() {
    if (!file || !sourceCol || !targetCol) return;
    setBusy(true); setMsg("Loading…");
    try {
      const { entries } = await api.extractLookup(file, sourceCol, targetCol);
      onImported(entries, mode);
    } catch (e: any) { setMsg(e.message); } finally { setBusy(false); }
  }

  return (
    <div className="jc-modal-overlay" onClick={onClose}>
      <div className="jc-modal" onClick={(e) => e.stopPropagation()}>
        <div className="jc-modal-head">
          <h3>Import {meta.label} mappings</h3>
          <button className="jc-modal-x" onClick={onClose} title="Close"><IconClose /></button>
        </div>
        <div className="jc-modal-body">
          <div className="jc-drop" onClick={() => inputRef.current?.click()}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => { e.preventDefault(); const f = e.dataTransfer.files?.[0]; if (f) onFile(f); }}>
            <div className="jc-drop-ico"><IconImport /></div>
            <strong>{file ? file.name : "Drop a .csv or click to browse"}</strong>
            <div>Then choose which columns to map.</div>
            <input ref={inputRef} type="file" accept=".csv" style={{ display: "none" }}
              onChange={(e) => { const f = e.target.files?.[0]; if (f) onFile(f); }} />
          </div>

          {preview && (
            <>
              <div className="jc-form-row">
                <div>
                  <label className="jc-form-label">Source column ({meta.src})</label>
                  <select className="jc-select" value={sourceCol} onChange={(e) => setSourceCol(e.target.value)}>
                    {preview.columns.map((c) => <option key={c} value={c}>{c}</option>)}
                  </select>
                </div>
                <div>
                  <label className="jc-form-label">Target column ({meta.tgt})</label>
                  <select className="jc-select" value={targetCol} onChange={(e) => setTargetCol(e.target.value)}>
                    {preview.columns.map((c) => <option key={c} value={c}>{c}</option>)}
                  </select>
                </div>
              </div>
              <div style={{ marginTop: 14 }}>
                <label className="jc-form-label">When importing</label>
                <select className="jc-select" value={mode} onChange={(e) => setMode(e.target.value as "replace" | "merge")}>
                  <option value="replace">Replace all rows in the editor</option>
                  <option value="merge">Merge into existing rows</option>
                </select>
              </div>
              {preview.sample.length > 0 && (
                <table className="jc-preview-table">
                  <thead><tr><th>{sourceCol || "source"}</th><th>{targetCol || "target"}</th></tr></thead>
                  <tbody>
                    {preview.sample.slice(0, 5).map((r, i) => (
                      <tr key={i}><td>{r[sourceCol]}</td><td>{r[targetCol]}</td></tr>
                    ))}
                  </tbody>
                </table>
              )}
            </>
          )}
          {msg && <p className="jc-modal-msg">{msg}</p>}
        </div>
        <div className="jc-modal-foot">
          <button className="jc-btn subtle" onClick={onClose}>Cancel</button>
          <button className="jc-btn primary" onClick={doLoad} disabled={busy || !preview || !sourceCol || !targetCol}>
            {busy ? "Loading…" : "Load into editor"}
          </button>
        </div>
      </div>
    </div>
  );
}
