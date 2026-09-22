import { useEffect, useState } from "react";
import { api } from "../api";
import { useApp } from "../store";
import type { CanonicalFieldDef, FieldMap, MappingTemplate } from "../types";

const TRANSFORMS = ["", "labels", "number", "date"];
const TYPE_TRANSFORM: Record<string, string> = { array: "labels", number: "number", date: "date" };
const TYPE_BADGE: Record<string, string> = {
  string: "neutral", text: "neutral", number: "ok", date: "ok", datetime: "ok",
  duration: "ok", user: "warn", option: "warn", array: "neutral", id: "neutral", url: "neutral",
};

// A blank per-type template (when the user starts from scratch).
const blankTemplate = (types: string[]): MappingTemplate => ({
  name: "New mapping", description: "", issue_type_field: "Issue Type",
  field_maps: [], value_maps: [],
  profiles: Object.fromEntries(types.map((t) => [t, []])),
});

export default function MappingStudio() {
  const { source } = useApp();
  const [defs, setDefs] = useState<CanonicalFieldDef[]>([]);
  const [dataTypes, setDataTypes] = useState<string[]>([]);
  const [artifactTypes, setArtifactTypes] = useState<string[]>([]);
  const [saved, setSaved] = useState<MappingTemplate[]>([]);
  const [tpl, setTpl] = useState<MappingTemplate | null>(null);
  const [activeType, setActiveType] = useState<string>("Feature");
  const [status, setStatus] = useState("");

  const typeOf = (field: string) => defs.find((d) => d.field === field)?.data_type ?? "";

  useEffect(() => {
    api.fields().then(setDefs).catch(() => {});
    api.dataTypes().then(setDataTypes).catch(() => {});
    api.artifactTypes().then((t) => { setArtifactTypes(t); if (t.length) setActiveType(t.includes("Feature") ? "Feature" : t[0]); }).catch(() => {});
    refresh();
    api.defaultTemplate().then((t) => setTpl((cur) => cur ?? t)).catch(() => {});
  }, []);

  function refresh() { api.listMappings().then(setSaved).catch(() => {}); }
  function update(patch: Partial<MappingTemplate>) { setTpl((t) => (t ? { ...t, ...patch } : t)); }

  const profiles = tpl?.profiles ?? {};
  const hasProfiles = Object.keys(profiles).length > 0;
  const rows: FieldMap[] = hasProfiles ? (profiles[activeType] ?? []) : (tpl?.field_maps ?? []);

  function setRows(next: FieldMap[]) {
    if (!tpl) return;
    if (hasProfiles) update({ profiles: { ...profiles, [activeType]: next } });
    else update({ field_maps: next });
  }
  function updateRow(i: number, patch: Partial<FieldMap>) {
    setRows(rows.map((m, idx) => (idx === i ? { ...m, ...patch } : m)));
  }
  // Changing the destination auto-fills its data type + implied transform.
  function setTarget(i: number, target: string) {
    const dt = typeOf(target);
    updateRow(i, { target, target_type: dt, transform: TYPE_TRANSFORM[dt] ?? rows[i].transform ?? "" });
  }
  function setSources(i: number, text: string) {
    const parts = text.split(",").map((s) => s.trim()).filter(Boolean);
    updateRow(i, { sources: parts, source: "" });
  }
  function addRow() { setRows([...rows, { sources: [], source_type: "string", target: "", target_type: "", transform: "" }]); }
  function removeRow(i: number) { setRows(rows.filter((_, idx) => idx !== i)); }

  async function save() {
    if (!tpl) return;
    setStatus("Saving…");
    try {
      const s = await api.saveMapping({ ...tpl, id: tpl.id ?? undefined });
      setTpl(s); refresh(); setStatus(`Saved “${s.name}”.`);
    } catch (e: any) { setStatus(e.message); }
  }

  const srcText = (m: FieldMap) => (m.sources?.length ? m.sources.join(", ") : (m.source ?? ""));
  const sourceCols = source?.columns ?? [];

  if (!tpl) return <div className="card"><div className="empty">Loading mapping…</div></div>;

  return (
    <>
      <div className="card">
        <div className="spread">
          <div>
            <p className="card-title">Mapping template</p>
            <p className="card-sub">See what each Rally field maps to in Jira, per work-item type — with the data type on both sides. Edit anything, then save it as a reusable template.</p>
          </div>
          <div className="btn-row">
            <select value={tpl.id ?? "default"} onChange={(e) => {
              const v = e.target.value;
              setStatus("");
              if (v === "default") { api.defaultTemplate().then(setTpl); return; }
              if (v === "new") { setTpl(blankTemplate(artifactTypes)); return; }
              const found = saved.find((s) => String(s.id) === v);
              if (found) setTpl(found);
            }}>
              <option value="default">Default Rally → Jira mapping</option>
              <option value="new">➕ New blank template</option>
              {saved.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
            <button className="btn primary" onClick={save}>Save template</button>
          </div>
        </div>

        <div className="grid cols-2">
          <div className="field"><label>Template name</label>
            <input value={tpl.name} onChange={(e) => update({ name: e.target.value })} /></div>
          <div className="field"><label>Issue-type source column</label>
            <input value={tpl.issue_type_field} onChange={(e) => update({ issue_type_field: e.target.value })} /></div>
        </div>

        {hasProfiles && (
          <div className="field">
            <label>Work item type</label>
            <div className="steps" style={{ marginBottom: 0 }}>
              {artifactTypes.map((t) => (
                <div key={t} className={`step ${t === activeType ? "active" : ""}`}
                  style={{ cursor: "pointer" }} onClick={() => setActiveType(t)}>
                  {t} <span className="muted" style={{ marginLeft: 6 }}>{(profiles[t] ?? []).length}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {source && <datalist id="src-cols">{sourceCols.map((c) => <option key={c} value={c} />)}</datalist>}

        <div className="table-wrap" style={{ marginTop: 8 }}>
          <table className="table">
            <thead><tr>
              <th style={{ width: "24%" }}>Rally field</th>
              <th>Source type</th>
              <th></th>
              <th style={{ width: "20%" }}>Jira field</th>
              <th>Dest. type</th>
              <th>Transform</th>
              <th></th>
            </tr></thead>
            <tbody>
              {rows.length === 0 && <tr><td colSpan={7}><div className="empty">No fields mapped for {activeType}. Add one below.</div></td></tr>}
              {rows.map((m, i) => (
                <tr key={i}>
                  <td>
                    <input list={source ? "src-cols" : undefined} value={srcText(m)}
                      placeholder="Rally column" onChange={(e) => setSources(i, e.target.value)} />
                    {m.note && <div className="muted" style={{ fontSize: 11, marginTop: 3 }}>{m.note}</div>}
                  </td>
                  <td>
                    <select value={m.source_type ?? ""} onChange={(e) => updateRow(i, { source_type: e.target.value })}>
                      <option value="">—</option>
                      {dataTypes.map((t) => <option key={t} value={t}>{t}</option>)}
                    </select>
                  </td>
                  <td className="muted">→</td>
                  <td>
                    <select value={m.target} onChange={(e) => setTarget(i, e.target.value)}>
                      <option value="">— choose —</option>
                      {defs.map((d) => <option key={d.field} value={d.field}>{d.label}</option>)}
                    </select>
                  </td>
                  <td>
                    <select value={m.target_type ?? typeOf(m.target)} onChange={(e) => updateRow(i, { target_type: e.target.value })}>
                      <option value="">—</option>
                      {dataTypes.map((t) => <option key={t} value={t}>{t}</option>)}
                    </select>
                  </td>
                  <td>
                    <select value={m.transform ?? ""} onChange={(e) => updateRow(i, { transform: e.target.value })}>
                      {TRANSFORMS.map((t) => <option key={t} value={t}>{t || "none"}</option>)}
                    </select>
                  </td>
                  <td><button className="btn sm ghost" onClick={() => removeRow(i)}>✕</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="btn-row" style={{ marginTop: 14 }}>
          <button className="btn" onClick={addRow}>+ Add field for {hasProfiles ? activeType : "all types"}</button>
          {status && <span className="muted" style={{ alignSelf: "center" }}>{status}</span>}
        </div>

        {tpl.value_maps.length > 0 && (
          <div className="callout" style={{ marginTop: 14 }}>
            <strong>Value maps</strong> (applied at migration):{" "}
            {tpl.value_maps.map((v) => <span key={v.field} className="tag">{v.field}: {Object.keys(v.values).length}</span>)}
          </div>
        )}
      </div>

      <div className="card">
        <p className="card-title">Data types</p>
        <p className="card-sub">Every field has a type on both the Rally (source) and Jira (destination) side — change either from the dropdowns above.</p>
        <div>{dataTypes.map((t) => <span key={t} className={`badge ${TYPE_BADGE[t] ?? "neutral"}`} style={{ marginRight: 6 }}>{t}</span>)}</div>
      </div>
    </>
  );
}
