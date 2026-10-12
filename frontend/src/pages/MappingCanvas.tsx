import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { useCopilotPage, useDataChanged } from "../copilot/CopilotContext";
import type { CatalogField, FieldMap, GeneratedCode, MappingCatalog, MappingTemplate, ValueMap } from "../types";

type Conn = { source: string; target: string };
type Point = { x: number; y: number };

const TYPE_TRANSFORM: Record<string, string> = { array: "labels", number: "number", date: "date" };

// Per-artifact version naming, e.g. "User Story" -> jira_us_mapping_v1.
const ARTIFACT_SLUG: Record<string, string> = {
  Epic: "epic", Feature: "feature", "User Story": "us", Task: "task", Defect: "defect",
};
function mappingBase(artifact: string): string {
  const slug = ARTIFACT_SLUG[artifact] ?? artifact.toLowerCase().replace(/\s+/g, "_");
  return `jira_${slug}_mapping`;
}
function nextVersion(base: string, saved: MappingTemplate[]): number {
  const re = new RegExp(`^${base}_v(\\d+)$`);
  let max = 0;
  for (const s of saved) {
    const m = s.name ? re.exec(s.name) : null;
    if (m) max = Math.max(max, parseInt(m[1], 10));
  }
  return max + 1;
}

export default function MappingStudio() {
  const [catalog, setCatalog] = useState<MappingCatalog | null>(null);
  const [artifact, setArtifact] = useState<string>("Feature");
  const [conns, setConns] = useState<Record<string, Conn[]>>({});
  const [saved, setSaved] = useState<MappingTemplate[]>([]);
  const [templateId, setTemplateId] = useState<number | null>(null);
  const [name, setName] = useState("Rally → Jira mapping");
  const [version, setVersion] = useState(1);
  const [status, setStatus] = useState("");
  const [code, setCode] = useState<GeneratedCode | null>(null);
  const valueMapsRef = useRef<ValueMap[]>([]);

  useCopilotPage({ mapping_id: templateId ?? undefined, artifact });
  // A copilot edit is saved as a new version; list it without disturbing the canvas.
  useDataChanged(["mapping"], (r) => {
    api.listMappings().then(setSaved).catch(() => {});
    setStatus(r.name ? `Copilot saved ${r.name}. Select it in the dropdown to open it.` : "Copilot saved a new mapping version.");
  });

  const containerRef = useRef<HTMLDivElement | null>(null);
  const portRefs = useRef<Record<string, HTMLElement | null>>({});
  const [ports, setPorts] = useState<Record<string, Point>>({});
  const [drag, setDrag] = useState<{ from: string; p: Point } | null>(null);
  const [dropKey, setDropKey] = useState<string>("");
  const [tick, setTick] = useState(0);

  // ---- load catalog + saved templates + default value maps ----
  useEffect(() => {
    api.mappingCatalog().then((c) => {
      setCatalog(c);
      setConns(c.defaults);                       // open with the clean defaults drawn
      if (!c.artifacts.includes(artifact)) setArtifact(c.artifacts[0]);
    }).catch(() => {});
    api.listMappings().then(setSaved).catch(() => {});
    api.defaultTemplate().then((t) => { valueMapsRef.current = t.value_maps || []; }).catch(() => {});
  }, []);

  useEffect(() => {
    const onResize = () => setTick((t) => t + 1);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  const leftFields: CatalogField[] = useMemo(() => {
    if (!catalog) return [];
    return [...catalog.common.rally, ...(catalog.specific[artifact]?.rally ?? [])];
  }, [catalog, artifact]);
  const rightFields: CatalogField[] = useMemo(() => {
    if (!catalog) return [];
    return [...catalog.common.jira, ...(catalog.specific[artifact]?.jira ?? [])];
  }, [catalog, artifact]);

  const jiraType = useMemo(() => {
    const m: Record<string, string> = {};
    if (catalog) {
      const all = [catalog.common.jira, ...Object.values(catalog.specific).map((s) => s.jira)].flat();
      all.forEach((f) => { m[f.key] = f.data_type; });
    }
    return m;
  }, [catalog]);

  const activeConns = conns[artifact] ?? [];

  // ---- measure port centres relative to the canvas ----
  useLayoutEffect(() => {
    const cont = containerRef.current;
    if (!cont) return;
    const cr = cont.getBoundingClientRect();
    const next: Record<string, Point> = {};
    for (const [k, el] of Object.entries(portRefs.current)) {
      if (!el) continue;
      const r = el.getBoundingClientRect();
      next[k] = { x: r.left + r.width / 2 - cr.left, y: r.top + r.height / 2 - cr.top };
    }
    setPorts(next);
  }, [catalog, artifact, activeConns.length, tick, leftFields.length, rightFields.length]);

  // ---- drag lifecycle ----
  useEffect(() => {
    if (!drag) return;
    const move = (e: PointerEvent) => {
      const cr = containerRef.current?.getBoundingClientRect();
      if (!cr) return;
      setDrag((d) => (d ? { ...d, p: { x: e.clientX - cr.left, y: e.clientY - cr.top } } : d));
    };
    const up = () => { setDrag(null); setDropKey(""); };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    return () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
  }, [drag?.from]);

  function startDrag(sourceKey: string, e: React.PointerEvent) {
    e.preventDefault();
    const cr = containerRef.current?.getBoundingClientRect();
    if (!cr) return;
    setDrag({ from: sourceKey, p: { x: e.clientX - cr.left, y: e.clientY - cr.top } });
  }
  function completeDrop(targetKey: string) {
    if (!drag) return;
    addConn(drag.from, targetKey);
    setDrag(null); setDropKey("");
  }
  function addConn(source: string, target: string) {
    setConns((prev) => {
      const list = prev[artifact] ?? [];
      if (list.some((c) => c.source === source && c.target === target)) return prev;
      return { ...prev, [artifact]: [...list, { source, target }] };
    });
  }
  function removeConn(c: Conn) {
    setConns((prev) => ({ ...prev, [artifact]: (prev[artifact] ?? []).filter((x) => !(x.source === c.source && x.target === c.target)) }));
  }

  // ---- template load / save ----
  function loadTemplate(t: MappingTemplate) {
    const byArtifact: Record<string, Conn[]> = {};
    Object.entries(t.profiles ?? {}).forEach(([atype, maps]) => {
      byArtifact[atype] = [];
      maps.forEach((m) => {
        const cols = m.sources?.length ? m.sources : (m.source ? [m.source] : []);
        cols.forEach((s) => byArtifact[atype].push({ source: s, target: m.target }));
      });
    });
    setConns(byArtifact);
    setName(t.name); setVersion(t.version ?? 1); setTemplateId(t.id ?? null);
    valueMapsRef.current = t.value_maps?.length ? t.value_maps : valueMapsRef.current;
  }

  async function save() {
    if (!catalog) return;
    const base = mappingBase(artifact);
    const v = nextVersion(base, saved);
    const vname = `${base}_v${v}`;
    setStatus("Saving…");
    try {
      // Always persist a brand-new version (never overwrite).
      const s = await api.saveMapping({ ...buildTemplate(), id: undefined, name: vname, version: v });
      setSaved(await api.listMappings());
      setTemplateId(s.id ?? null); setName(s.name); setVersion(s.version ?? v);
      setStatus(`Saved ${s.name}.`);
    } catch (e: any) { setStatus(e.message); }
  }

  async function deleteVersion() {
    if (!templateId || !catalog) return;
    setStatus("Deleting…");
    try {
      await api.deleteMapping(templateId);
      setSaved(await api.listMappings());
      setTemplateId(null); setName("Rally → Jira mapping"); setVersion(1);
      setConns(catalog.defaults);
      setStatus("Version deleted.");
    } catch (e: any) { setStatus(e.message); }
  }

  // Consolidate all artifacts' connections into one template object.
  function buildTemplate(): MappingTemplate {
    const profiles: Record<string, FieldMap[]> = {};
    for (const atype of catalog!.artifacts) {
      const byTarget: Record<string, string[]> = {};
      (conns[atype] ?? []).forEach((c) => { (byTarget[c.target] ??= []).push(c.source); });
      profiles[atype] = Object.entries(byTarget).map(([target, sources]) => ({
        sources, source: sources[0], target,
        target_type: jiraType[target] ?? "", transform: TYPE_TRANSFORM[jiraType[target]] ?? "",
      }));
    }
    return {
      id: templateId ?? undefined,
      name, description: "Built in the visual mapper.",
      version: templateId ? version + 1 : 1,
      issue_type_field: "Issue Type",
      field_maps: profiles["Feature"] ?? [],
      profiles,
      value_maps: valueMapsRef.current,
    };
  }

  async function viewCode() {
    setStatus("Generating…");
    try {
      const g = await api.generateCode({ ...buildTemplate(), version });
      setCode(g); setStatus("");
    } catch (e: any) { setStatus(e.message); }
  }

  function path(a: Point, b: Point): string {
    const dx = Math.max(40, Math.abs(b.x - a.x) / 2);
    return `M ${a.x} ${a.y} C ${a.x + dx} ${a.y}, ${b.x - dx} ${b.y}, ${b.x} ${b.y}`;
  }

  const connectedLeft = new Set(activeConns.map((c) => c.source));
  const connectedRight = new Set(activeConns.map((c) => c.target));

  if (!catalog) return <div className="card"><div className="empty">Loading fields…</div></div>;

  return (
    <>
      <div className="card">
        <div className="spread" style={{ marginBottom: 14 }}>
          <div>
            <p className="card-title">Field mapper</p>
            <p className="card-sub">Drag from a Rally field to a Jira field to connect them. Two Rally fields into one Jira field = fallback (first non-empty wins).</p>
          </div>
          <div className="btn-row">
            <select value={templateId ?? "new"} onChange={(e) => {
              const v = e.target.value;
              setStatus("");
              if (v === "new") { setConns(catalog.defaults); setName("Rally → Jira mapping"); setVersion(1); setTemplateId(null); return; }
              if (v === "blank") { setConns({}); setName("New mapping"); setVersion(1); setTemplateId(null); return; }
              const t = saved.find((s) => String(s.id) === v);
              if (t) loadTemplate(t);
            }}>
              <option value="new">Default connections</option>
              <option value="blank">Blank canvas</option>
              {saved.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
            {templateId && <button className="btn ghost" onClick={deleteVersion}>Delete version</button>}
            <button className="btn" onClick={viewCode}>View generated code</button>
            <button className="btn primary" onClick={save}>Save as new version</button>
          </div>
        </div>

        <div className="grid cols-2" style={{ marginBottom: 8 }}>
          <div className="field" style={{ margin: 0 }}>
            <label>Next version {templateId ? <span className="badge neutral" style={{ marginLeft: 6 }}>editing {name}</span> : null}</label>
            <input value={`${mappingBase(artifact)}_v${nextVersion(mappingBase(artifact), saved)}`} readOnly />
          </div>
          <div className="field" style={{ margin: 0 }}>
            <label>Artifact</label>
            <select value={artifact} onChange={(e) => setArtifact(e.target.value)}>
              {catalog.artifacts.map((a) => <option key={a} value={a}>{a}</option>)}
            </select>
          </div>
        </div>

        <div className="row" style={{ justifyContent: "space-between", margin: "6px 0 14px" }}>
          <span className="map-hint">Showing <strong>common</strong> fields + fields specific to <strong>{artifact}</strong>. · {activeConns.length} connection{activeConns.length === 1 ? "" : "s"}</span>
          <div className="btn-row">
            <button className="btn sm" onClick={() => setConns((p) => ({ ...p, [artifact]: catalog.defaults[artifact] ?? [] }))}>Auto-map</button>
            <button className="btn sm ghost" onClick={() => setConns((p) => ({ ...p, [artifact]: [] }))}>Clear</button>
          </div>
        </div>

        <div className="map-canvas" ref={containerRef}>
          {/* left: Rally */}
          <div className="map-col">
            <div className="map-col-head">Rally — source</div>
            <FieldList fields={catalog.common.rally} side="left" prefix="Common" onPort={(k, el) => (portRefs.current["L:" + k] = el)}
              connected={connectedLeft} onDown={startDrag} dropKey="" />
            {(catalog.specific[artifact]?.rally?.length ?? 0) > 0 && (
              <FieldList fields={catalog.specific[artifact].rally} side="left" prefix={`${artifact} only`} onPort={(k, el) => (portRefs.current["L:" + k] = el)}
                connected={connectedLeft} onDown={startDrag} dropKey="" />
            )}
          </div>

          <div />{/* spacer where the lines live */}

          {/* right: Jira */}
          <div className="map-col">
            <div className="map-col-head" style={{ textAlign: "right" }}>Jira — destination</div>
            <FieldList fields={catalog.common.jira} side="right" prefix="Common" onPort={(k, el) => (portRefs.current["R:" + k] = el)}
              connected={connectedRight} dropKey={dropKey} onEnter={(k) => drag && setDropKey(k)} onLeave={(k) => dropKey === k && setDropKey("")} onUp={completeDrop} />
            {(catalog.specific[artifact]?.jira?.length ?? 0) > 0 && (
              <FieldList fields={catalog.specific[artifact].jira} side="right" prefix={`${artifact} only`} onPort={(k, el) => (portRefs.current["R:" + k] = el)}
                connected={connectedRight} dropKey={dropKey} onEnter={(k) => drag && setDropKey(k)} onLeave={(k) => dropKey === k && setDropKey("")} onUp={completeDrop} />
            )}
          </div>

          <svg className="map-svg">
            {activeConns.map((c, i) => {
              const a = ports["L:" + c.source]; const b = ports["R:" + c.target];
              if (!a || !b) return null;
              const mid = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
              return (
                <g key={i} className="map-conn">
                  <path className="map-hit" d={path(a, b)} />
                  <path className="map-link" d={path(a, b)} />
                  <circle className="map-mid" cx={mid.x} cy={mid.y} r={4} />
                  <g className="map-del" transform={`translate(${mid.x}, ${mid.y})`} onClick={() => removeConn(c)}>
                    <circle r="8.5" />
                    <text textAnchor="middle" dominantBaseline="central">✕</text>
                  </g>
                </g>
              );
            })}
            {drag && ports["L:" + drag.from] && (
              <path className="map-link-temp" d={path(ports["L:" + drag.from], drag.p)} />
            )}
          </svg>
        </div>

        {status && <p className="muted" style={{ marginTop: 14 }}>{status}</p>}
        {valueMapsRef.current.length > 0 && (
          <div className="callout" style={{ marginTop: 14 }}>
            <strong>Value maps</strong> carried into this template:{" "}
            {valueMapsRef.current.map((v) => <span key={v.field} className="tag">{v.field}: {Object.keys(v.values).length}</span>)}
          </div>
        )}
      </div>

      {code && <CodeModal code={code} onClose={() => setCode(null)} />}
    </>
  );
}

function CodeModal({ code, onClose }: { code: GeneratedCode; onClose: () => void }) {
  const [copied, setCopied] = useState(false);
  function copy() { navigator.clipboard.writeText(code.code).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500); }); }
  function download() {
    const blob = new Blob([code.code], { type: "text/x-python" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = code.filename; a.click();
    URL.revokeObjectURL(a.href);
  }
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <div>
            <p className="card-title" style={{ margin: 0 }}>Generated mapping</p>
            <p className="muted" style={{ margin: "2px 0 0", fontSize: 12 }}><code>{code.filename}</code></p>
          </div>
          <div className="btn-row">
            <button className="btn sm" onClick={copy}>{copied ? "Copied ✓" : "Copy"}</button>
            <button className="btn sm" onClick={download}>Download</button>
            <button className="btn sm ghost" onClick={onClose}>Close ✕</button>
          </div>
        </div>
        <pre className="code-view"><code>{code.code}</code></pre>
      </div>
    </div>
  );
}

function FieldList({ fields, side, prefix, onPort, connected, onDown, dropKey, onEnter, onLeave, onUp }: {
  fields: CatalogField[]; side: "left" | "right"; prefix: string;
  onPort: (key: string, el: HTMLElement | null) => void; connected: Set<string>;
  onDown?: (key: string, e: React.PointerEvent) => void; dropKey: string;
  onEnter?: (key: string) => void; onLeave?: (key: string) => void; onUp?: (key: string) => void;
}) {
  return (
    <>
      <div className="map-col-sub" style={side === "right" ? { textAlign: "right" } : undefined}>{prefix}</div>
      {fields.map((f) => (
        <div key={f.key}
          className={`map-node ${side} ${connected.has(f.key) ? "connected" : ""} ${dropKey === f.key ? "drop" : ""}`}
          onPointerDown={side === "left" && onDown ? (e) => onDown(f.key, e) : undefined}
          onPointerEnter={side === "right" && onEnter ? () => onEnter(f.key) : undefined}
          onPointerLeave={side === "right" && onLeave ? () => onLeave(f.key) : undefined}
          onPointerUp={side === "right" && onUp ? () => onUp(f.key) : undefined}>
          <span className="node-main">
            <span className="node-label">{f.label}</span>
            <span className="node-type">{f.data_type}</span>
          </span>
          <span className="port" ref={(el) => onPort(f.key, el)} />
        </div>
      ))}
    </>
  );
}
