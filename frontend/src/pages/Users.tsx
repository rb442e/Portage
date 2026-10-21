import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api } from "../api";
import { ROLE_LABEL, useAuth } from "../auth/AuthContext";
import type { Role, UserDirectory } from "../types";

const ROLE_HELP: Record<Role, string> = {
  admin: "Everything, plus users, settings, saved connections and MCP servers.",
  member: "Run migrations, edit mappings and catalogs, apply Sora's proposals.",
  viewer: "View everything and ask Sora questions. Cannot change anything.",
};

function when(v?: string | null) {
  if (!v) return "Never";
  const d = new Date(v.replace(" ", "T") + "Z");
  return isNaN(d.getTime()) ? v : d.toLocaleString();
}

export default function Users() {
  const { user: me } = useAuth();
  const [dir, setDir] = useState<UserDirectory | null>(null);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("member");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [confirm, setConfirm] = useState<string | null>(null);
  const [approveAs, setApproveAs] = useState<Record<string, Role>>({});

  useEffect(() => { api.users().then(setDir).catch((e) => setMsg({ ok: false, text: e.message })); }, []);

  async function run(action: () => Promise<UserDirectory>, done: string) {
    setBusy(true); setMsg(null);
    try { setDir(await action()); setMsg({ ok: true, text: done }); return true; }
    catch (e: any) { setMsg({ ok: false, text: e.message }); return false; }
    finally { setBusy(false); setConfirm(null); }
  }

  async function invite(e: FormEvent) {
    e.preventDefault();
    const address = email.trim().toLowerCase();
    if (await run(() => api.addUser(address, role), `${address} can now sign in as ${ROLE_LABEL[role]}.`)) setEmail("");
  }

  if (!dir) return <div className="card muted">{msg ? msg.text : "Loading users…"}</div>;
  const pending = dir.users.filter((u) => u.status === "pending");
  const people = dir.users.filter((u) => u.status !== "pending");
  const counts = people.filter((u) => u.status === "active").reduce<Record<string, number>>((a, u) => ({ ...a, [u.role]: (a[u.role] ?? 0) + 1 }), {});
  return (
    <div className="st">
      <header className="st-head">
        <h1 className="st-h1">Users &amp; access</h1>
        <p className="muted">People sign in with a one-time code sent to their email. Roles decide what they can do.</p>
      </header>

      {msg && <div className={`st-msg ${msg.ok ? "ok" : "bad"}`}>{msg.text}</div>}

      <div className="um-roles">
        {(["admin", "member", "viewer"] as Role[]).map((r) => (
          <div className="um-role" key={r}>
            <div className="spread"><span className={`um-badge ${r}`}>{ROLE_LABEL[r]}</span><b>{counts[r] ?? 0}</b></div>
            <p>{ROLE_HELP[r]}</p>
          </div>
        ))}
      </div>

      {pending.length > 0 && (
        <div className="card um-requests">
          <p className="card-title">Access requests <span className="um-count">{pending.length}</span></p>
          <p className="card-sub">These people verified their email and are waiting for approval. They get an email either way.</p>
          {pending.map((u) => (
            <div className="um-request" key={u.email}>
              <span className="um-avatar" aria-hidden>{(u.name || u.email)[0].toUpperCase()}</span>
              <div className="um-request-who">
                <div className="um-email">{u.name || u.email}</div>
                <div className="um-meta">{u.email} · requested {when(u.created_at)}</div>
              </div>
              <select value={approveAs[u.email] ?? "viewer"} aria-label={`Role for ${u.email}`} disabled={busy}
                onChange={(e) => setApproveAs({ ...approveAs, [u.email]: e.target.value as Role })}>
                {dir.roles.map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
              </select>
              <button className="btn primary sm" disabled={busy}
                onClick={() => void run(() => api.updateUser(u.email, { status: "active", role: approveAs[u.email] ?? "viewer" }),
                  `${u.email} was approved as ${ROLE_LABEL[approveAs[u.email] ?? "viewer"]}.`)}>Approve</button>
              <button className="btn ghost sm mcp-danger" disabled={busy}
                onClick={() => void run(() => api.updateUser(u.email, { status: "rejected" }), `${u.email}'s request was declined.`)}>Decline</button>
            </div>
          ))}
        </div>
      )}

      <div className="card">
        <p className="card-title">Add a person</p>
        <p className="card-sub">They sign in with a code, or set a password with "Create account" or "Forgot password" using this address.</p>
        <form className="um-invite" onSubmit={invite}>
          <input type="email" required placeholder="name@company.com" value={email} aria-label="Email address"
            onChange={(e) => setEmail(e.target.value)} disabled={busy} />
          <select value={role} onChange={(e) => setRole(e.target.value as Role)} aria-label="Role" disabled={busy}>
            {dir.roles.map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
          </select>
          <button className="btn primary" disabled={busy || !email.trim()}>Add user</button>
        </form>
        <p className="hint um-policy">
          {dir.allowed_domains.length
            ? <>Anyone at {dir.allowed_domains.map((d) => <code key={d}>@{d}</code>)} can also sign in and starts as a Viewer.</>
            : <>Only people added here (or listed in <code>PORTAGE_ADMIN_EMAILS</code>) can sign in. Set <code>PORTAGE_ALLOWED_EMAIL_DOMAINS</code> to let a whole domain sign in as Viewers.</>}
        </p>
      </div>

      <div className="card">
        <p className="card-title">People</p>
        <p className="card-sub">Changes apply on the person's next request. Disabling someone signs them out everywhere.</p>
        <div className="table-wrap">
          <table className="table um-table">
            <thead><tr><th>User</th><th>Role</th><th>Status</th><th>Last sign-in</th><th /></tr></thead>
            <tbody>
              {people.map((u) => {
                const self = u.email === me.email;
                const pinned = dir.admin_emails.includes(u.email);
                return (
                  <tr key={u.email} className={u.status !== "active" ? "um-off" : ""}>
                    <td>
                      <div className="um-user">
                        <span className="um-avatar" aria-hidden>{(u.name || u.email)[0].toUpperCase()}</span>
                        <div>
                          <div className="um-email">{u.name || u.email}{self && <span className="um-you">You</span>}</div>
                          <div className="um-meta">{u.name ? `${u.email} · ` : ""}{pinned ? "Admin from PORTAGE_ADMIN_EMAILS" : u.invited_by ? `Added by ${u.invited_by}` : ""}</div>
                        </div>
                      </div>
                    </td>
                    <td>
                      <select value={u.role} disabled={busy || self || pinned} aria-label={`Role for ${u.email}`}
                        onChange={(e) => void run(() => api.updateUser(u.email, { role: e.target.value as Role }), `${u.email} is now ${ROLE_LABEL[e.target.value as Role]}.`)}>
                        {dir.roles.map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
                      </select>
                    </td>
                    <td><span className={`badge ${u.status === "active" ? "ok" : u.status === "rejected" ? "err" : "neutral"}`}>{u.status === "active" ? "Active" : u.status === "rejected" ? "Declined" : "Disabled"}</span></td>
                    <td className="muted">{when(u.last_login_at)}</td>
                    <td className="um-actions">
                      {!self && (confirm === u.email ? (
                        <>
                          <span className="um-confirm">Remove access?</span>
                          <button className="btn sm mcp-danger-solid" disabled={busy}
                            onClick={() => void run(() => api.removeUser(u.email), `${u.email} was removed.`)}>Remove</button>
                          <button className="btn ghost sm" onClick={() => setConfirm(null)}>Cancel</button>
                        </>
                      ) : (
                        <>
                          <button className="btn sm" disabled={busy || (pinned && u.status === "active")}
                            onClick={() => void run(() => api.updateUser(u.email, { status: u.status === "active" ? "disabled" : "active" }),
                              u.status === "active" ? `${u.email} was disabled and signed out.` : `${u.email} can sign in again.`)}>
                            {u.status === "active" ? "Disable" : "Enable"}
                          </button>
                          <button className="btn ghost sm mcp-danger" disabled={busy || pinned} onClick={() => setConfirm(u.email)}>Remove</button>
                        </>
                      ))}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
