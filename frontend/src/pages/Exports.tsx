import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api";
import type { ExportPreview, ExportRecord } from "../types";

const svg = { fill: "none", stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
const SearchIcon = () => (<svg viewBox="0 0 24 24" {...svg}><circle cx="11" cy="11" r="7" /><path d="m21 21-4.3-4.3" /></svg>);
const StackIcon = () => (<svg viewBox="0 0 24 24" {...svg}><path d="M12 2 2 7l10 5 10-5-10-5Z" /><path d="m2 17 10 5 10-5M2 12l10 5 10-5" /></svg>);
const DownloadIcon = () => (<svg viewBox="0 0 24 24" {...svg}><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><path d="M7 10l5 5 5-5M12 15V3" /></svg>);

function fmtDate(s: string): string {
  if (!s) return "—";
  return s.replace("T", " ").slice(0, 16);
}

export default function Exports() {
  const [searchParams] = useSearchParams();
  const [records, setRecords] = useState<ExportRecord[]>([]);
  const [selected, setSelected] = useState<ExportRecord | null>(null);
  const [activeFile, setActiveFile] = useState("");
  const [preview, setPreview] = useState<ExportPreview | null>(null);
  const [loading, setLoading] = useState(false);
  const [q, setQ] = useState(searchParams.get("mid") ?? "");

  useEffect(() => {
    const mid = searchParams.get("mid");
    api.exportsList().then((r) => {
      setRecords(r);
      const first = mid ? r.find((x) => x.migration_id === mid) ?? r[0] : r[0];
      if (first) selectExport(first);
    }).catch(() => {});
  }, []);  // eslint-disable-line react-hooks/exhaustive-deps

  const filtered = records.filter((r) => {
    const s = q.trim().toLowerCase();
    if (!s) return true;
    return (r.migration_id || "").toLowerCase().includes(s)
      || (r.label || "").toLowerCase().includes(s)
      || r.export_id.toLowerCase().includes(s);
  });

  function firstFile(rec: ExportRecord): string {
    return rec.files.find((f) => f.name === "jira_all_issues.csv")?.name || rec.files[0]?.name || "";
  }

  function selectExport(rec: ExportRecord) {
    setSelected(rec);
    const f = firstFile(rec);
    setActiveFile(f);
    if (f) loadPreview(rec.export_id, f); else setPreview(null);
  }

  async function loadPreview(id: string, file: string) {
    setLoading(true);
    try { setPreview(await api.exportPreview(id, file)); }
    catch { setPreview(null); } finally { setLoading(false); }
  }

  function pickFile(name: string) {
    setActiveFile(name);
    if (selected) loadPreview(selected.export_id, name);
  }

  const ident = (r: ExportRecord) => r.migration_id || r.export_id.slice(0, 8).toUpperCase();

  return (
    <div className="exp">
      <header className="exp-head">
        <div style={{ minWidth: 0 }}>
          <h1 className="exp-h1">Exports <span className="exp-count">{records.length}</span></h1>
          <p className="exp-sub">Generated Jira import files — browse in-tool or download for the CSV importer.</p>
        </div>
        <label className="exp-search">
          <SearchIcon />
          <input placeholder="Search Migration ID or source…" value={q} onChange={(e) => setQ(e.target.value)} />
        </label>
      </header>

      {records.length === 0 ? (
        <div className="exp-empty-card">
          <div className="exp-empty-ico"><StackIcon /></div>
          <p>No exports yet</p>
          <span>Generate Jira import files from a migration and they'll appear here.</span>
        </div>
      ) : (
        <div className="exp-grid">
          <aside className="exp-side">
            {filtered.length === 0 ? (
              <div className="exp-noresult">No match for “{q}”.</div>
            ) : filtered.map((rec) => (
              <button key={rec.export_id} className={`exp-rec ${selected?.export_id === rec.export_id ? "is-active" : ""}`}
                onClick={() => selectExport(rec)}>
                <span className="exp-rec-ico"><StackIcon /></span>
                <span className="exp-rec-body">
                  <span className="exp-rec-id">{ident(rec)}</span>
                  <span className="exp-rec-meta">
                    <span className={`exp-tag ${rec.kind === "batch" ? "is-batch" : ""}`}>{rec.kind || "export"}</span>
                    {rec.total} rows · {rec.files.length} files
                  </span>
                  <span className="exp-rec-date">{fmtDate(rec.created_at)}</span>
                </span>
              </button>
            ))}
          </aside>

          <section className="exp-detail">
            {selected ? (
              <>
                <div className="exp-detail-head">
                  <div className="exp-detail-id" style={{ minWidth: 0 }}>
                    <span className="exp-detail-label">Migration ID</span>
                    <h2>{ident(selected)}</h2>
                  </div>
                  <a className="exp-btn-primary" href={api.exportZipUrl(selected.export_id)}><DownloadIcon /> Download all (.zip)</a>
                </div>

                <div className="exp-stats">
                  <div className="exp-stat"><span className="exp-stat-k">Kind</span><span className="exp-stat-v" style={{ textTransform: "capitalize" }}>{selected.kind || "export"}</span></div>
                  <div className="exp-stat"><span className="exp-stat-k">Rows</span><span className="exp-stat-v">{selected.total}</span></div>
                  <div className="exp-stat"><span className="exp-stat-k">Files</span><span className="exp-stat-v">{selected.files.length}</span></div>
                  <div className="exp-stat"><span className="exp-stat-k">Created</span><span className="exp-stat-v" style={{ fontSize: 13 }}>{fmtDate(selected.created_at)}</span></div>
                </div>

                <div className="exp-files">
                  {selected.files.map((f) => (
                    <button key={f.name} className={`exp-file ${activeFile === f.name ? "is-active" : ""}`} onClick={() => pickFile(f.name)}>
                      {f.name} <span className="exp-file-rows">{f.rows}</span>
                    </button>
                  ))}
                </div>

                <div className="exp-preview-bar">
                  <span>
                    {preview ? <>Showing {Math.min(preview.rows.length, preview.total_rows)} of {preview.total_rows} rows · {preview.columns.length} columns</>
                      : loading ? "Loading…" : ""}
                  </span>
                  {activeFile && <a className="exp-btn-ghost" href={api.exportFileUrl(selected.export_id, activeFile)}><DownloadIcon /> {activeFile}</a>}
                </div>

                {preview && preview.columns.length > 0 ? (
                  <div className="exp-table-wrap">
                    <table className="exp-table">
                      <thead>
                        <tr>
                          <th className="exp-rownum">#</th>
                          {preview.columns.map((c) => <th key={c}>{c}</th>)}
                        </tr>
                      </thead>
                      <tbody>
                        {preview.rows.map((row, i) => (
                          <tr key={i}>
                            <td className="exp-rownum">{i + 1}</td>
                            {preview.columns.map((c) => <td key={c} title={String(row[c] ?? "")}>{String(row[c] ?? "")}</td>)}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <div className="exp-empty-detail"><p>{loading ? "Loading preview…" : "No file selected"}</p></div>
                )}

                {preview?.truncated && (
                  <p className="exp-hint">Preview capped at {preview.rows.length} rows — download the file for the full {preview.total_rows} rows.</p>
                )}
              </>
            ) : (
              <div className="exp-empty-detail">
                <div className="exp-empty-ico"><StackIcon /></div>
                <p>Select an export</p>
                <span>Pick a migration on the left to preview its files.</span>
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
