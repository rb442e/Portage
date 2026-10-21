import { Fragment, useEffect, useRef, useState, type ReactNode } from "react";
import {
  attachmentUrl, copilotApi, notifyDataChanged, streamChat,
  type AttachmentRef, type ConversationSummary, type CopilotSettings, type CopilotStatus, type Proposal,
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
  attachments?: AttachmentRef[];
  error?: string;
}
interface Pending { key: string; name: string; status: "uploading" | "ready" | "error"; ref?: AttachmentRef; preview?: string; error?: string }

const MAX_ATTACHMENTS = 5;
const ACCEPT = ".txt,.md,.csv,.tsv,.json,.log,.yaml,.yml,.xml,.sql,image/png,image/jpeg,image/gif,image/webp";
const ROUTES: Record<string, string> = {
  "/": "Dashboard", "/connections": "Connections", "/mapping": "Mapping Studio", "/lookups": "Jira Catalog", "/migrate": "Migrate",
  "/attachments": "Attachments", "/exports": "Exports", "/split": "Split File", "/copy-description": "Copy Description",
  "/reports": "Reports", "/settings": "Settings",
};

const svg = { fill: "none", stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
const ClipIcon = () => (<svg width="16" height="16" viewBox="0 0 24 24" {...svg}><path d="m21.4 11-9.2 9.2a5 5 0 0 1-7.1-7.1l9.2-9.2a3.5 3.5 0 0 1 5 5l-9.2 9.2a2 2 0 0 1-2.8-2.8l8.5-8.5" /></svg>);
const CameraIcon = () => (<svg width="16" height="16" viewBox="0 0 24 24" {...svg}><path d="M4 8h3l2-3h6l2 3h3v11H4z" /><circle cx="12" cy="13" r="3.5" /></svg>);
const FileIcon = () => (<svg width="16" height="16" viewBox="0 0 24 24" {...svg}><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" /><path d="M14 3v5h5" /></svg>);
const SendIcon = () => (<svg width="18" height="18" viewBox="0 0 24 24" {...svg} strokeWidth={2.4}><path d="M12 19V5" /><path d="m5 12 7-7 7 7" /></svg>);
const StopIcon = () => (<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><rect x="5" y="5" width="14" height="14" rx="2.5" /></svg>);

function Chip({ name, thumb, kind, state, error, onRemove }: {
  name: string; thumb?: string; kind?: string; state?: string; error?: string; onRemove?: () => void;
}) {
  return (
    <span className={`cp-chip ${state ?? ""}`} title={error ?? name}>
      {thumb ? <img src={thumb} alt="" /> : <FileIcon />}
      <span className="cp-chip-name">{state === "uploading" ? "Uploading…" : state === "error" ? error : name}</span>
      {onRemove && <button type="button" aria-label={`Remove ${name}`} onClick={onRemove}>✕</button>}
    </span>
  );
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
  if (p.preview.kind === "mcp_server") {
    rows.push(<Line key="url" sign="+">{p.preview.transport === "sse" ? "SSE" : "Streamable HTTP"}: {p.preview.url}</Line>);
    rows.push(<Line key="enabled" sign="+">{p.preview.enabled_for_sora ? "Read-only tools enabled for Sora after approval" : "Server saved; not enabled for Sora"}</Line>);
  } else if (p.preview.kind === "catalog") {
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
      {p.status === "applied" && p.tool === "propose_mcp_server" && <div className="cp-proposal-sub">Added <code>{p.result?.name}</code> to Settings → MCP servers.</div>}
      {p.status === "applied" && p.result?.name && p.tool !== "propose_mcp_server" && <div className="cp-proposal-sub">Saved as <code>{p.result.name}</code>. Pick it in the mapping dropdown.</div>}
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
      <label>Vision model (reads screenshots you attach)
        <input list="cp-models" value={s.vision_model ?? ""} onChange={(e) => set({ vision_model: e.target.value })} />
      </label>
      {llm?.reachable && llm.vision_model_available === false && (
        <div className="cp-llm bad">Vision model not installed. Run: ollama pull {s.vision_model}</div>
      )}
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
  const fileRef = useRef<HTMLInputElement | null>(null);
  const [pending, setPending] = useState<Pending[]>([]);
  const [dragging, setDragging] = useState(false);
  const [notice, setNotice] = useState("");

  function addFiles(files: File[]) {
    setNotice("");
    const room = Math.max(MAX_ATTACHMENTS - pending.length, 0);
    if (files.length > room) setNotice(`You can attach up to ${MAX_ATTACHMENTS} files per message.`);
    files.slice(0, room).forEach((file) => {
      const key = uid();
      const preview = file.type.startsWith("image/") ? URL.createObjectURL(file) : undefined;
      setPending((p) => [...p, { key, name: file.name, status: "uploading", preview }]);
      copilotApi.upload(file)
        .then((ref) => setPending((p) => p.map((x) => (x.key === key ? { ...x, status: "ready", ref } : x))))
        .catch((e: Error) => setPending((p) => p.map((x) => (x.key === key ? { ...x, status: "error", error: e.message } : x))));
    });
  }
  function removePending(key: string) {
    const gone = pending.find((p) => p.key === key);
    if (gone?.preview) URL.revokeObjectURL(gone.preview);
    if (gone?.ref) void copilotApi.deleteAttachment(gone.ref.id).catch(() => {});
    setPending((p) => p.filter((x) => x.key !== key));
  }

  async function captureScreen() {
    if (!navigator.mediaDevices?.getDisplayMedia) { setNotice("Screen capture is not available in this browser. Paste or attach an image instead."); return; }
    try {
      const stream = await navigator.mediaDevices.getDisplayMedia({ video: true });
      const video = document.createElement("video");
      video.srcObject = stream; video.muted = true;
      await video.play();
      await new Promise((r) => setTimeout(r, 250));            // let the first frame render
      const scale = Math.min(1, 1600 / video.videoWidth);       // keep it small enough to upload and to read
      const canvas = document.createElement("canvas");
      canvas.width = Math.round(video.videoWidth * scale); canvas.height = Math.round(video.videoHeight * scale);
      canvas.getContext("2d")?.drawImage(video, 0, 0, canvas.width, canvas.height);
      stream.getTracks().forEach((t) => t.stop());
      const blob = await new Promise<Blob | null>((r) => canvas.toBlob(r, "image/png"));
      if (blob) addFiles([new File([blob], `screenshot-${new Date().toTimeString().slice(0, 8).replace(/:/g, "")}.png`, { type: "image/png" })]);
    } catch (e: any) {
      if (e?.name !== "NotAllowedError") setNotice(e?.message ?? "Could not capture the screen.");
    }
  }

  const pageLabel = [ROUTES[page.route] ?? page.route, page.artifact, page.lookup_kind].filter(Boolean).join(" · ");
  const hasImage = pending.some((p) => p.preview);
  const needsVision = hasImage && status?.llm.reachable && status.llm.vision_model_available === false;

  const refreshStatus = () => copilotApi.status().then(setStatus).catch(() => setStatus(null));

  useEffect(() => { if (open) { refreshStatus(); inputRef.current?.focus(); } }, [open]);
  useEffect(() => { if (open) copilotApi.suggestions(page.route).then(setSuggestions).catch(() => {}); }, [open, page.route]);
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs]);
  useEffect(() => { if (open && queued) { void send(queued); clearQueued(); } }, [open, queued]);  // eslint-disable-line react-hooks/exhaustive-deps

  const patchLast = (fn: (m: Msg) => Msg) => setMsgs((ms) => ms.map((m, i) => (i === ms.length - 1 ? fn(m) : m)));

  async function send(text: string) {
    const ready = pending.filter((p) => p.ref);
    const message = text.trim() || (ready.length ? "Please review what I attached." : "");
    if (!message || busy || pending.some((p) => p.status === "uploading")) return;
    pending.forEach((p) => p.preview && URL.revokeObjectURL(p.preview));
    setInput(""); setPending([]); setNotice(""); setView("chat"); setBusy(true);
    setMsgs((ms) => [...ms,
      { id: uid(), role: "user", text: message, steps: [], proposals: [], attachments: ready.map((p) => p.ref!) },
      { id: uid(), role: "assistant", text: "", steps: [], proposals: [] }]);
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    try {
      await streamChat({ message, conversation_id: convId, page, attachments: ready.map((p) => p.ref!.id) }, (e) => {
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

  function newChat() { abortRef.current?.abort(); setMsgs([]); setConvId(""); setPending([]); setNotice(""); setView("chat"); }

  async function openHistory() {
    setView("history");
    setHistory(await copilotApi.conversations().catch(() => []));
  }
  async function loadConversation(id: string) {
    const c = await copilotApi.conversation(id);
    const byId = new Map(c.proposals.map((p) => [p.id, p]));
    setMsgs(c.messages.map((m) => ({
      id: uid(), role: m.role, text: m.content, skill: m.meta.skill, steps: [], attachments: m.meta.attachments,
      proposals: (m.meta.proposals ?? []).map((pid) => byId.get(pid)).filter((p): p is Proposal => !!p),
    })));
    setConvId(id); setView("chat");
  }

  if (!open) return null;
  const llmDown = status && !(status.llm.reachable && status.llm.model_available);

  return (
    <aside className={`cp-drawer ${dragging ? "dragging" : ""}`} role="complementary" aria-label="Sora"
      onDragOver={(e) => { if (e.dataTransfer.types.includes("Files")) { e.preventDefault(); setDragging(true); } }}
      onDragLeave={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDragging(false); }}
      onDrop={(e) => { e.preventDefault(); setDragging(false); addFiles(Array.from(e.dataTransfer.files)); }}>
      {dragging && <div className="cp-drop">Drop files or screenshots to give Sora context</div>}
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
                <p className="muted">Add context with the paperclip, by dragging a file in, or by pasting a screenshot (⌘V). Start with @mapping, @catalog, @migration, @guide or @lineage to pick a skill. ⌘K / Ctrl+K toggles Sora.</p>
              </div>
            )}
            {msgs.map((m) => (
              <div key={m.id} className={`cp-msg ${m.role}`}>
                {m.role === "assistant" && <div className="cp-skill"><SoraIcon size={18} />{m.skill ?? "Sora"}</div>}
                {m.attachments && m.attachments.length > 0 && (
                  <div className="cp-attached">
                    {m.attachments.map((a) => <Chip key={a.id} name={a.name} kind={a.kind} thumb={a.kind === "image" ? attachmentUrl(a.id) : undefined} />)}
                  </div>
                )}
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
            <div className="cp-ctx">
              <span className="cp-chip page" title="Sora can see which page you are on">Context: {pageLabel}</span>
              {pending.map((p) => (
                <Chip key={p.key} name={p.name} thumb={p.preview} state={p.status} error={p.error} onRemove={() => removePending(p.key)} />
              ))}
            </div>
            {(notice || needsVision) && (
              <div className="cp-notice">{notice || `Screenshots need a vision model. Run: ollama pull ${status?.settings.vision_model}`}</div>
            )}
            <div className="cp-box">
              <textarea ref={inputRef} rows={2} value={input} placeholder="Message Sora…  (Enter to send, Shift+Enter for a new line)"
                onChange={(e) => setInput(e.target.value)}
                onPaste={(e) => {
                  const files = Array.from(e.clipboardData.files);
                  if (files.length) {
                    e.preventDefault();
                    addFiles(files.map((f) => (f.name === "image.png" ? new File([f], `pasted-${new Date().toTimeString().slice(0, 8).replace(/:/g, "")}.png`, { type: f.type }) : f)));
                  }
                }}
                onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); void send(input); } }} />
              <div className="cp-compose-bar">
                <button type="button" className="cp-icon" title="Attach a file or screenshot" aria-label="Attach a file or screenshot" onClick={() => fileRef.current?.click()}><ClipIcon /></button>
                <button type="button" className="cp-icon" title="Capture your screen" aria-label="Capture your screen" onClick={() => void captureScreen()}><CameraIcon /></button>
                <input ref={fileRef} type="file" multiple hidden accept={ACCEPT}
                  onChange={(e) => { addFiles(Array.from(e.target.files ?? [])); e.target.value = ""; }} />
                <span className="cp-grow" />
                {busy
                  ? <button type="button" className="cp-send" title="Stop" aria-label="Stop" onClick={() => abortRef.current?.abort()}><StopIcon /></button>
                  : <button type="submit" className="cp-send" title="Send (Enter)" aria-label="Send"
                      disabled={(!input.trim() && !pending.some((p) => p.ref)) || pending.some((p) => p.status === "uploading")}><SendIcon /></button>}
              </div>
            </div>
          </form>
          <div className="cp-foot">
            {status?.settings.redact ? "Emails and secrets in text are masked before reaching the local model." : "Redaction is off."}
            {hasImage && " Text inside screenshots cannot be masked; they are read only by your local vision model."}
          </div>
        </>
      )}
    </aside>
  );
}
