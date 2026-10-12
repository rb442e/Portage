import { Fragment, useEffect, useRef, useState, type ReactNode } from "react";
import {
  copilotApi, notifyDataChanged, streamChat,
  type ConversationSummary, type CopilotSettings, type CopilotStatus, type Proposal,
} from "./api";
import { useCopilot } from "./CopilotContext";
import SoraIcon from "./SoraIcon";

interface Step { name: string; ok?: boolean; summary?: string }
interface Msg {
  id: string;
  role: "user" | "assistant";
  text: string;
  skill?: string;
  steps: Step[];
  proposals: Proposal[];
  error?: string;
}

const uid = () => Math.random().toString(36).slice(2, 10);
const pretty = (tool: string) => tool.replace(/^propose_/, "").replace(/_/g, " ");

// ---- tiny markdown: **bold**, `code`, "- " bullets ------------------------
function inline(text: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**")) return <strong key={i}>{part.slice(2, -2)}</strong>;
    if (part.startsWith("`") && part.endsWith("`")) return <code key={i}>{part.slice(1, -1)}</code>;
    return <Fragment key={i}>{part}</Fragment>;
  });
}
function RichText({ text }: { text: string }) {
  const out: ReactNode[] = [];
  let bullets: string[] = [];
  const flush = () => {
    if (bullets.length) out.push(<ul key={`u${out.length}`}>{bullets.map((b, i) => <li key={i}>{inline(b)}</li>)}</ul>);
    bullets = [];
  };
  text.split("\n").forEach((line, i) => {
    const m = /^\s*[-*]\s+(.*)$/.exec(line);
    if (m) { bullets.push(m[1]); return; }
    flush();
    if (line.trim()) out.push(<p key={i}>{inline(line)}</p>);
  });
  flush();
  return <>{out}</>;
}

// ---- diffs -------------------------------------------------------------------
function Line({ sign, children }: { sign: "+" | "-" | "~"; children: ReactNode }) {
  return <div className={`cp-line ${sign === "+" ? "add" : sign === "-" ? "del" : "chg"}`}><span>{sign}</span><span>{children}</span></div>;
}

function DiffView({ p }: { p: Proposal }) {
  const [all, setAll] = useState(false);
  const rows: ReactNode[] = [];
  const d = p.preview.diff;
  if (p.preview.kind === "catalog") {
    Object.entries(d.added ?? {}).forEach(([k, v]) => rows.push(<Line key={`a${k}`} sign="+">{k} → {v}</Line>));
    Object.entries(d.changed ?? {}).forEach(([k, v]) => {
      const c = v as { from: string; to: string };
      rows.push(<Line key={`c${k}`} sign="~">{k}: {c.from} → {c.to}</Line>);
    });
    Object.entries(d.removed ?? {}).forEach(([k, v]) => rows.push(<Line key={`r${k}`} sign="-">{k} → {v}</Line>));
  } else {
    Object.entries(d.artifacts ?? {}).forEach(([art, ch]) => {
      Object.entries(ch.added).forEach(([t, s]) => rows.push(<Line key={`${art}a${t}`} sign="+">{art}: {t} ← {s.join(" | ")}</Line>));
      Object.entries(ch.changed).forEach(([t, v]) => rows.push(<Line key={`${art}c${t}`} sign="~">{art}: {t} ← {v.from.join(" | ")} → {v.to.join(" | ")}</Line>));
      Object.entries(ch.removed).forEach(([t, s]) => rows.push(<Line key={`${art}r${t}`} sign="-">{art}: {t} ← {s.join(" | ")}</Line>));
    });
  }
  const shown = all ? rows : rows.slice(0, 10);
  return (
    <div className="cp-diff">
      {shown}
      {rows.length > 10 && !all && <button className="cp-link" onClick={() => setAll(true)}>Show {rows.length - 10} more</button>}
    </div>
  );
}

function ProposalCard({ p, onChange }: { p: Proposal; onChange: (p: Proposal) => void }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function act(kind: "apply" | "reject") {
    setBusy(true); setErr("");
    try {
      if (kind === "apply") {
        const r = await copilotApi.apply(p.id);
        onChange(r.proposal);
        notifyDataChanged(r.result.refresh ?? [], r.result);
      } else {
        onChange((await copilotApi.reject(p.id)).proposal);
      }
    } catch (e: any) { setErr(e.message); } finally { setBusy(false); }
  }

  return (
    <div className={`cp-proposal ${p.status}`}>
      <div className="cp-proposal-head">
        <strong>{p.preview.title}</strong>
        <span className={`cp-pill ${p.status}`}>{p.status}</span>
      </div>
      <div className="cp-proposal-sub">
        {p.preview.catalog && <>Catalog: {p.preview.catalog} · </>}
        {p.preview.base && <>From: {p.preview.base} · </>}
        {p.preview.summary}
      </div>
      <DiffView p={p} />
      {p.status === "pending" && (
        <div className="cp-actions">
          <button className="btn sm primary" disabled={busy} onClick={() => act("apply")}>{busy ? "Working…" : "Apply"}</button>
          <button className="btn sm" disabled={busy} onClick={() => act("reject")}>Reject</button>
        </div>
      )}
      {p.status === "applied" && p.result?.name && <div className="cp-proposal-sub">Saved as <code>{p.result.name}</code>. Pick it in the mapping dropdown.</div>}
      {p.status === "applied" && !p.result?.name && <div className="cp-proposal-sub">Applied. Previous values are kept in the catalog's History.</div>}
      {err && <div className="cp-error">{err}</div>}
    </div>
  );
}

// ---- settings ----------------------------------------------------------------
function SettingsPanel({ status, onSaved }: { status: CopilotStatus | null; onSaved: () => void }) {
  const [s, setS] = useState<CopilotSettings | null>(status?.settings ?? null);
  const [msg, setMsg] = useState("");
  useEffect(() => setS(status?.settings ?? null), [status]);
  if (!s) return <div className="cp-empty">Loading…</div>;
  const set = (patch: Partial<CopilotSettings>) => setS({ ...s, ...patch });
  const llm = status?.llm;
  return (
    <div className="cp-settings">
      <div className={`cp-llm ${llm?.reachable && llm.model_available ? "ok" : "bad"}`}>
        {!llm?.reachable ? "Ollama is not reachable. Run `ollama serve`."
          : !llm.model_available ? `Model not installed. Run: ollama pull ${s.model}`
          : `Ollama connected · ${s.model}`}
      </div>
      <label>Ollama URL<input value={s.base_url} onChange={(e) => set({ base_url: e.target.value })} /></label>
      <label>Model
        <input list="cp-models" value={s.model} onChange={(e) => set({ model: e.target.value })} />
        <datalist id="cp-models">{llm?.models.map((m) => <option key={m} value={m} />)}</datalist>
      </label>
      <label>Mode
        <select value={s.mode} onChange={(e) => set({ mode: e.target.value as CopilotSettings["mode"] })}>
          <option value="propose">Propose changes (you approve)</option>
          <option value="readonly">Read-only (no changes)</option>
        </select>
      </label>
      <label className="cp-check"><input type="checkbox" checked={s.redact} onChange={(e) => set({ redact: e.target.checked })} />
        Mask emails and secrets before sending to the model</label>
      <div className="cp-actions">
        <button className="btn sm primary" onClick={async () => {
          try { await copilotApi.saveSettings(s); setMsg("Saved"); onSaved(); } catch (e: any) { setMsg(e.message); }
        }}>Save</button>
        {msg && <span className="muted">{msg}</span>}
      </div>
    </div>
  );
}

// ---- drawer ------------------------------------------------------------------
export default function CopilotDrawer() {
  const { open, setOpen, page, queued, clearQueued } = useCopilot();
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [convId, setConvId] = useState("");
  const [view, setView] = useState<"chat" | "history" | "settings">("chat");
  const [status, setStatus] = useState<CopilotStatus | null>(null);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [history, setHistory] = useState<ConversationSummary[]>([]);
  const abortRef = useRef<AbortController | null>(null);
  const endRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);

  const refreshStatus = () => copilotApi.status().then(setStatus).catch(() => setStatus(null));

  useEffect(() => { if (open) { refreshStatus(); inputRef.current?.focus(); } }, [open]);
  useEffect(() => { if (open) copilotApi.suggestions(page.route).then(setSuggestions).catch(() => {}); }, [open, page.route]);
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs]);
  useEffect(() => { if (open && queued) { void send(queued); clearQueued(); } }, [open, queued]);  // eslint-disable-line react-hooks/exhaustive-deps

  const patchLast = (fn: (m: Msg) => Msg) => setMsgs((ms) => ms.map((m, i) => (i === ms.length - 1 ? fn(m) : m)));

  async function send(text: string) {
    const message = text.trim();
    if (!message || busy) return;
    setInput(""); setView("chat"); setBusy(true);
    setMsgs((ms) => [...ms,
      { id: uid(), role: "user", text: message, steps: [], proposals: [] },
      { id: uid(), role: "assistant", text: "", steps: [], proposals: [] }]);
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    try {
      await streamChat({ message, conversation_id: convId, page }, (e) => {
        switch (e.type) {
          case "meta": setConvId(e.conversation_id); patchLast((m) => ({ ...m, skill: e.skill.label })); break;
          case "token": patchLast((m) => ({ ...m, text: m.text + e.text })); break;
          case "tool_call": patchLast((m) => ({ ...m, steps: [...m.steps, { name: e.name }] })); break;
          case "tool_result": patchLast((m) => ({
            ...m, steps: m.steps.map((s, i) => (i === m.steps.length - 1 ? { ...s, ok: e.ok, summary: e.summary } : s)) })); break;
          case "proposal": patchLast((m) => ({ ...m, proposals: [...m.proposals, e.proposal] })); break;
          case "error": patchLast((m) => ({ ...m, error: e.message })); break;
        }
      }, ctrl.signal);
    } catch (e: any) {
      if (e.name !== "AbortError") patchLast((m) => ({ ...m, error: e.message }));
    } finally { setBusy(false); abortRef.current = null; }
  }

  function newChat() { abortRef.current?.abort(); setMsgs([]); setConvId(""); setView("chat"); }

  async function openHistory() {
    setView("history");
    setHistory(await copilotApi.conversations().catch(() => []));
  }
  async function loadConversation(id: string) {
    const c = await copilotApi.conversation(id);
    const byId = new Map(c.proposals.map((p) => [p.id, p]));
    setMsgs(c.messages.map((m) => ({
      id: uid(), role: m.role, text: m.content, skill: m.meta.skill, steps: [],
      proposals: (m.meta.proposals ?? []).map((pid) => byId.get(pid)).filter((p): p is Proposal => !!p),
    })));
    setConvId(id); setView("chat");
  }

  if (!open) return null;
  const llmDown = status && !(status.llm.reachable && status.llm.model_available);

  return (
    <aside className="cp-drawer" role="complementary" aria-label="Sora">
      <header className="cp-head">
        <div className="cp-title"><SoraIcon size={26} /> <span>Sora</span>
          {status?.settings.mode === "readonly" && <span className="cp-pill pending">read-only</span>}
        </div>
        <div className="cp-head-actions">
          <button className="cp-icon" title="New chat" onClick={newChat}>＋</button>
          <button className="cp-icon" title="History" onClick={openHistory}>↺</button>
          <button className="cp-icon" title="Settings" onClick={() => setView(view === "settings" ? "chat" : "settings")}>⚙</button>
          <button className="cp-icon" title="Close (Esc)" onClick={() => setOpen(false)}>✕</button>
        </div>
      </header>

      {view === "settings" && <SettingsPanel status={status} onSaved={refreshStatus} />}

      {view === "history" && (
        <div className="cp-history">
          {history.length === 0 && <div className="cp-empty">No conversations yet.</div>}
          {history.map((h) => (
            <div key={h.id} className="cp-history-row">
              <button className="cp-link" onClick={() => loadConversation(h.id)}>{h.title || "Untitled"}</button>
              <span className="muted">{h.updated_at}</span>
              <button className="cp-icon" title="Delete" onClick={async () => { await copilotApi.deleteConversation(h.id); setHistory((x) => x.filter((c) => c.id !== h.id)); }}>✕</button>
            </div>
          ))}
        </div>
      )}

      {view === "chat" && (
        <>
          <div className="cp-body">
            {llmDown && <div className="cp-llm bad">Local model unavailable. Open ⚙ to check Ollama.</div>}
            {msgs.length === 0 && (
              <div className="cp-welcome">
                <SoraIcon size={56} className="cp-hero" />
                <h3>Hi, I'm Sora</h3>
                <p>Ask about your mappings, catalogs, uploads or migration runs. Changes I propose only happen after you click Apply.</p>
                <div className="cp-suggest">
                  {suggestions.map((s) => <button key={s} onClick={() => send(s)}>{s}</button>)}
                </div>
                <p className="muted">Tip: start with @mapping, @catalog, @migration or @guide to pick a skill. Press ⌘K / Ctrl+K to toggle.</p>
              </div>
            )}
            {msgs.map((m) => (
              <div key={m.id} className={`cp-msg ${m.role}`}>
                {m.role === "assistant" && <div className="cp-skill"><SoraIcon size={18} />{m.skill ?? "Sora"}</div>}
                {m.steps.length > 0 && (
                  <div className="cp-steps">
                    {m.steps.map((s, i) => (
                      <div key={i} className={`cp-step ${s.ok === false ? "bad" : ""}`}>
                        {s.ok === undefined ? "…" : s.ok ? "✓" : "!"} {pretty(s.name)}{s.ok === false && s.summary ? ` — ${s.summary}` : ""}
                      </div>
                    ))}
                  </div>
                )}
                {m.text ? <div className="cp-text"><RichText text={m.text} /></div>
                  : m.role === "assistant" && busy && m === msgs[msgs.length - 1] && !m.error && <div className="cp-typing"><i /><i /><i /></div>}
                {m.proposals.map((p) => (
                  <ProposalCard key={p.id} p={p} onChange={(np) => setMsgs((ms) => ms.map((x) => ({ ...x, proposals: x.proposals.map((q) => (q.id === np.id ? np : q)) })))} />
                ))}
                {m.error && <div className="cp-error">{m.error}</div>}
              </div>
            ))}
            <div ref={endRef} />
          </div>

          <form className="cp-input" onSubmit={(e) => { e.preventDefault(); void send(input); }}>
            <textarea ref={inputRef} rows={2} value={input} placeholder="Message Sora…  (Enter to send, Shift+Enter for a new line)"
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void send(input); } }} />
            {busy
              ? <button type="button" className="btn sm" onClick={() => abortRef.current?.abort()}>Stop</button>
              : <button type="submit" className="btn sm primary" disabled={!input.trim()}>Send</button>}
          </form>
          <div className="cp-foot">{status?.settings.redact ? "Emails and secrets are masked before reaching the local model." : "Redaction is off."}</div>
        </>
      )}
    </aside>
  );
}
