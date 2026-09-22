import { useRef, useState } from "react";
import { api } from "../api";
import type { SplitResult } from "../types";

const svg = { width: 16, height: 16, fill: "none", stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
const UploadIcon = () => (<svg viewBox="0 0 24 24" {...svg}><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><path d="M7 10l5-5 5 5M12 5v12" /></svg>);
const DownloadIcon = () => (<svg viewBox="0 0 24 24" {...svg}><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><path d="M7 10l5 5 5-5M12 15V3" /></svg>);

function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`;
  return `${(n / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

export default function SplitFile() {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [maxRows, setMaxRows] = useState(1000);
  const [hasHeader, setHasHeader] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<SplitResult | null>(null);

  function pick(f: File | null) {
    setFile(f);
    setResult(null);
    setError("");
  }

  async function split() {
    if (!file) return;
    setBusy(true); setError(""); setResult(null);
    try {
      setResult(await api.splitFile(file, maxRows, hasHeader));
    } catch (e: any) {
      setError(e.message || "Split failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div style={{ marginBottom: 18 }}>
        <h1 style={{ margin: "0 0 4px", fontSize: 20, fontWeight: 700, letterSpacing: "-0.02em" }}>Split File</h1>
        <p className="muted" style={{ margin: 0, fontSize: 13 }}>
          Split a large CSV into smaller part files. The header row is kept in every part. Standalone — not part of a migration.
        </p>
      </div>

      <div className="card">
        <div className="grid cols-2" style={{ alignItems: "end" }}>
          <div className="field">
            <label>File</label>
            <input ref={inputRef} type="file" accept=".csv,text/csv" style={{ display: "none" }}
              onChange={(e) => pick(e.target.files?.[0] ?? null)} />
            <div className="row" style={{ gap: 10 }}>
              <button className="btn" onClick={() => inputRef.current?.click()}><UploadIcon /> Choose CSV</button>
              <span className="muted" style={{ fontSize: 13, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {file ? `${file.name} · ${fmtBytes(file.size)}` : "No file selected"}
              </span>
            </div>
          </div>
          <div className="field">
            <label>Rows per file</label>
            <input type="number" min={1} value={maxRows}
              onChange={(e) => setMaxRows(Math.max(1, parseInt(e.target.value || "0", 10) || 0))} />
          </div>
        </div>

        <label className="row" style={{ gap: 8, marginTop: 14, fontSize: 13 }}>
          <input type="checkbox" checked={hasHeader} onChange={(e) => setHasHeader(e.target.checked)} />
          First row is a header — repeat it in every part
        </label>

        <div className="btn-row" style={{ marginTop: 16 }}>
          <button className="btn primary" disabled={!file || busy || maxRows < 1} onClick={split}>
            {busy ? "Splitting…" : "Split file"}
          </button>
          {error && <span style={{ color: "var(--danger)", fontSize: 13, alignSelf: "center" }}>{error}</span>}
        </div>
      </div>

      {result && (
        <div className="card">
          <div className="spread" style={{ marginBottom: 14 }}>
            <div>
              <p className="card-title" style={{ margin: 0 }}>{result.parts.length} file{result.parts.length === 1 ? "" : "s"} created</p>
              <p className="muted" style={{ margin: "2px 0 0", fontSize: 13 }}>
                {result.total_rows.toLocaleString()} rows · {fmtBytes(result.total_size)} total
              </p>
            </div>
            <a className="btn primary" href={api.splitZipUrl(result.split_id)}><DownloadIcon /> Download all (.zip)</a>
          </div>

          <table className="table">
            <thead>
              <tr>
                <th>File</th>
                <th style={{ textAlign: "right", width: 110 }}>Rows</th>
                <th style={{ textAlign: "right", width: 110 }}>Size</th>
                <th style={{ width: 90 }}></th>
              </tr>
            </thead>
            <tbody>
              {result.parts.map((p) => (
                <tr key={p.name}>
                  <td style={{ fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace", fontSize: 13 }}>{p.name}</td>
                  <td style={{ textAlign: "right", fontVariantNumeric: "tabular-nums" }}>{p.rows.toLocaleString()}</td>
                  <td style={{ textAlign: "right", fontVariantNumeric: "tabular-nums" }}>{fmtBytes(p.size)}</td>
                  <td style={{ textAlign: "right" }}>
                    <a className="btn ghost sm" href={api.splitFileUrl(result.split_id, p.name)}>Download</a>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
