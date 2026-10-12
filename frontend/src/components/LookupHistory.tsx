import { useEffect, useState } from "react";
import { api } from "../api";
import type { EntryDiff, LookupVersion } from "../types";

export default function LookupHistory({ lookupId, label, onClose, onRestored }: {
  lookupId: number; label: string; onClose: () => void; onRestored: () => void;
}) {
  const [versions, setVersions] = useState<LookupVersion[]>([]);
  const [diff, setDiff] = useState<{ version: number; data: EntryDiff } | null>(null);
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => { api.lookupVersions(lookupId).then(setVersions).catch((e) => setMsg(e.message)); }, [lookupId]);

  async function compare(v: number) {
    setMsg("");
    try { setDiff({ version: v, data: await api.lookupDiff(lookupId, v) }); } catch (e: any) { setMsg(e.message); }
  }
  async function restore(v: number) {
    setBusy(true); setMsg("");
    try { await api.restoreLookup(lookupId, v); onRestored(); onClose(); } catch (e: any) { setMsg(e.message); } finally { setBusy(false); }
  }

  const rows = diff ? [
    ...Object.entries(diff.data.added).map(([k, v]) => `+ ${k} → ${v}`),
    ...Object.entries(diff.data.changed).map(([k, v]) => `~ ${k}: ${v.from} → ${v.to}`),
    ...Object.entries(diff.data.removed).map(([k, v]) => `- ${k} → ${v}`),
  ] : [];

  return (
    <div className="jc-modal-overlay" onClick={onClose}>
      <div className="jc-modal" onClick={(e) => e.stopPropagation()}>
        <div className="jc-modal-head">
          <h3>{label} catalog history</h3>
          <button className="jc-modal-x" onClick={onClose} title="Close">✕</button>
        </div>
        <div className="jc-modal-body">
          {versions.length === 0 && !msg && <p className="muted">No history yet. Versions are recorded each time the catalog is saved.</p>}
          <table className="jc-table">
            <thead><tr><th>Version</th><th>Saved</th><th>By</th><th>Entries</th><th /></tr></thead>
            <tbody>
              {versions.map((v, i) => (
                <tr key={v.version}>
                  <td>v{v.version}{i === 0 && <span className="tag" style={{ marginLeft: 6 }}>current</span>}</td>
                  <td>{v.created_at}<div className="muted" style={{ fontSize: 12 }}>{v.message}</div></td>
                  <td><span className={`badge ${v.author === "copilot" ? "ok" : "neutral"}`}>{v.author}</span></td>
                  <td>{v.size}</td>
                  <td style={{ whiteSpace: "nowrap" }}>
                    {i > 0 && <button className="btn sm ghost" onClick={() => compare(v.version)}>Compare to current</button>}
                    {i > 0 && <button className="btn sm" disabled={busy} onClick={() => restore(v.version)}>Restore</button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {diff && (
            <div className="cp-diff" style={{ marginTop: 14 }}>
              <div className="muted" style={{ marginBottom: 6 }}>v{diff.version} → current: {diff.data.summary}</div>
              {rows.slice(0, 50).map((r, i) => <div key={i} className={`cp-line ${r[0] === "+" ? "add" : r[0] === "-" ? "del" : "chg"}`}><span>{r[0]}</span><span>{r.slice(2)}</span></div>)}
            </div>
          )}
          {msg && <p className="jc-modal-msg">{msg}</p>}
        </div>
      </div>
    </div>
  );
}
