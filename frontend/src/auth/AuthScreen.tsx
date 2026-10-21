import { useEffect, useRef, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { api } from "../api";
import type { AuthConfig, AuthUser } from "../types";

type View = "signin" | "signup" | "signup-code" | "pending" | "forgot" | "reset" | "otp" | "otp-code";

function strength(pw: string, min: number): { score: number; label: string } {
  if (!pw) return { score: 0, label: "" };
  const kinds = [/[a-z]/, /[A-Z]/, /\d/, /[^A-Za-z0-9]/].filter((r) => r.test(pw)).length;
  let score = pw.length >= min ? 1 : 0;
  if (score && pw.length >= min + 4) score++;
  if (score && (kinds >= 3 || pw.length >= 20)) score++;
  if (score && pw.length >= 16 && kinds >= 2) score++;
  return { score, label: ["Too short", "Fair", "Good", "Strong", "Very strong"][score] };
}

function PasswordField({ id, label, value, onChange, autoComplete, min, aside, meter }: {
  id: string; label: string; value: string; onChange: (v: string) => void; autoComplete: string;
  min?: number; aside?: ReactNode; meter?: boolean;
}) {
  const [show, setShow] = useState(false);
  const s = strength(value, min ?? 10);
  return (
    <div className="auth-field">
      <div className="auth-label-row">
        <label className="auth-label" htmlFor={id}>{label}</label>
        {aside}
      </div>
      <div className="auth-pw">
        <input id={id} type={show ? "text" : "password"} value={value} autoComplete={autoComplete} required
          minLength={meter ? min : undefined} onChange={(e) => onChange(e.target.value)} />
        <button type="button" className="auth-pw-toggle" onClick={() => setShow(!show)}
          aria-label={show ? "Hide password" : "Show password"}>{show ? "Hide" : "Show"}</button>
      </div>
      {meter && (
        <div className="auth-meter" aria-live="polite">
          <div className="auth-meter-bar">{[1, 2, 3, 4].map((i) => <span key={i} className={s.score >= i ? `on s${s.score}` : ""} />)}</div>
          <span className="auth-meter-text">{value ? s.label : `At least ${min} characters. A short phrase works well.`}</span>
        </div>
      )}
    </div>
  );
}

function CodeField({ value, onChange, inputRef }: { value: string; onChange: (v: string) => void; inputRef: React.RefObject<HTMLInputElement> }) {
  return (
    <div className="auth-field">
      <label className="auth-label" htmlFor="auth-code">6-digit code</label>
      <input id="auth-code" ref={inputRef} className="auth-code" inputMode="numeric" autoComplete="one-time-code"
        maxLength={6} placeholder="000000" value={value} onChange={(e) => onChange(e.target.value.replace(/\D/g, "").slice(0, 6))} />
    </div>
  );
}

export default function AuthScreen({ onSignedIn, notice }: { onSignedIn: (u: AuthUser) => void; notice?: string }) {
  const [config, setConfig] = useState<AuthConfig | null>(null);
  const [view, setView] = useState<View>("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(notice ?? "");
  const [info, setInfo] = useState("");
  const [cooldown, setCooldown] = useState(0);
  const codeRef = useRef<HTMLInputElement>(null);
  const min = config?.password_min ?? 10;

  useEffect(() => { api.authConfig().then(setConfig).catch(() => setConfig(null)); }, []);
  useEffect(() => {
    if (cooldown <= 0) return;
    const t = setTimeout(() => setCooldown(cooldown - 1), 1000);
    return () => clearTimeout(t);
  }, [cooldown]);
  useEffect(() => { if (view.endsWith("code") || view === "reset") codeRef.current?.focus(); }, [view]);

  const go = (v: View) => { setView(v); setError(""); setInfo(""); setCode(""); if (v === "signin" || v === "signup") setPassword(""); };

  async function act(fn: () => Promise<void>) {
    setBusy(true); setError("");
    try { await fn(); } catch (e: any) { setError(e.message); } finally { setBusy(false); }
  }
  const startCooldown = () => setCooldown(config?.resend_seconds ?? 30);

  const signIn = (e: FormEvent) => { e.preventDefault(); void act(async () => onSignedIn((await api.login(email.trim(), password)).user)); };
  const signUp = (e?: FormEvent) => {
    e?.preventDefault();
    void act(async () => { await api.signup(email.trim(), password); startCooldown(); setView("signup-code"); setCode(""); });
  };
  const verifySignup = (e: FormEvent) => {
    e.preventDefault();
    void act(async () => {
      const r = await api.signupVerify(email.trim(), code);
      if (r.status === "signed_in" && r.user) onSignedIn(r.user); else { setPassword(""); setView("pending"); }
    });
  };
  const sendReset = (e?: FormEvent) => {
    e?.preventDefault();
    void act(async () => { await api.forgotPassword(email.trim()); startCooldown(); setPassword(""); setCode(""); setView("reset"); });
  };
  const doReset = (e: FormEvent) => { e.preventDefault(); void act(async () => onSignedIn((await api.resetPassword(email.trim(), code, password)).user)); };
  const sendOtp = (e?: FormEvent) => {
    e?.preventDefault();
    void act(async () => { await api.requestCode(email.trim()); startCooldown(); setCode(""); setView("otp-code"); });
  };
  const verifyOtp = (e: FormEvent) => { e.preventDefault(); void act(async () => onSignedIn((await api.verifyCode(email.trim(), code)).user)); };

  const noEmail = config && !config.email_configured;
  const resend = (fn: () => void) => (
    <button type="button" className="auth-link" disabled={cooldown > 0 || busy} onClick={fn}>
      {cooldown > 0 ? `Resend in ${cooldown}s` : "Resend code"}
    </button>
  );
  const emailField = (autoFocus = false) => (
    <div className="auth-field">
      <label className="auth-label" htmlFor="auth-email">Work email</label>
      <input id="auth-email" type="email" autoComplete="email" required autoFocus={autoFocus} value={email}
        placeholder="you@company.com" onChange={(e) => setEmail(e.target.value)} />
    </div>
  );
  const alerts = (
    <>
      {error && <div className="auth-error" role="alert">{error}</div>}
      {info && <div className="auth-info" role="status">{info}</div>}
    </>
  );

  let body: ReactNode;
  if (view === "signin") body = (
    <form onSubmit={signIn} noValidate={false}>
      <h1 className="auth-title">Welcome back</h1>
      <p className="auth-sub">Sign in to continue to Portage.</p>
      {emailField(true)}
      <PasswordField id="auth-password" label="Password" value={password} onChange={setPassword} autoComplete="current-password"
        aside={<button type="button" className="auth-link small" onClick={() => go("forgot")}>Forgot password?</button>} />
      {alerts}
      <button className="btn primary auth-submit" disabled={busy || !email.trim() || !password}>{busy ? "Signing in…" : "Sign in"}</button>
      <div className="auth-divider"><span>or</span></div>
      <button type="button" className="btn auth-alt" disabled={busy || !!noEmail} onClick={() => go("otp")}>Email me a sign-in code</button>
    </form>
  );
  else if (view === "signup") body = (
    <form onSubmit={signUp}>
      <h1 className="auth-title">Create your account</h1>
      <p className="auth-sub">We'll email you a code to confirm your address.</p>
      {emailField(true)}
      <PasswordField id="auth-new-password" label="Password" value={password} onChange={setPassword} autoComplete="new-password" min={min} meter />
      {alerts}
      <button className="btn primary auth-submit" disabled={busy || !!noEmail || !email.trim() || password.length < min}>
        {busy ? "Creating account…" : "Create account"}
      </button>
      <p className="auth-fine">New accounts outside your organisation's approved domains are reviewed by an admin before they can sign in.</p>
    </form>
  );
  else if (view === "signup-code" || view === "otp-code") body = (
    <form onSubmit={view === "signup-code" ? verifySignup : verifyOtp}>
      <button type="button" className="auth-back" onClick={() => go(view === "signup-code" ? "signup" : "signin")}>← Back</button>
      <h1 className="auth-title">Check your email</h1>
      <p className="auth-sub">
        {view === "signup-code" ? "We sent a verification code to " : "If this address can sign in, we sent a code to "}
        <b>{email.trim()}</b>. It expires in {config?.code_ttl_minutes ?? 10} minutes.
      </p>
      <CodeField value={code} onChange={setCode} inputRef={codeRef} />
      {alerts}
      <button className="btn primary auth-submit" disabled={busy || code.length !== 6}>
        {busy ? "Verifying…" : view === "signup-code" ? "Verify and continue" : "Sign in"}
      </button>
      <div className="auth-links">
        <span className="auth-muted">Didn't get it? Check spam.</span>
        {resend(view === "signup-code" ? () => signUp() : () => sendOtp())}
      </div>
    </form>
  );
  else if (view === "pending") body = (
    <div className="auth-done">
      <div className="auth-done-ico" aria-hidden>✓</div>
      <h1 className="auth-title">Request sent</h1>
      <p className="auth-sub">Your email is verified. An admin will review your account and we'll email <b>{email.trim()}</b> when it's ready.</p>
      <button className="btn auth-submit" onClick={() => go("signin")}>Back to sign in</button>
    </div>
  );
  else if (view === "forgot") body = (
    <form onSubmit={sendReset}>
      <button type="button" className="auth-back" onClick={() => go("signin")}>← Back to sign in</button>
      <h1 className="auth-title">Reset your password</h1>
      <p className="auth-sub">Enter your account's email and we'll send you a code to set a new password.</p>
      {emailField(true)}
      {alerts}
      <button className="btn primary auth-submit" disabled={busy || !email.trim() || !!noEmail}>{busy ? "Sending…" : "Send reset code"}</button>
    </form>
  );
  else if (view === "reset") body = (
    <form onSubmit={doReset}>
      <button type="button" className="auth-back" onClick={() => go("forgot")}>← Back</button>
      <h1 className="auth-title">Set a new password</h1>
      <p className="auth-sub">If an account exists for <b>{email.trim()}</b>, we emailed a reset code. You'll be signed out of other devices.</p>
      <CodeField value={code} onChange={setCode} inputRef={codeRef} />
      <PasswordField id="auth-reset-password" label="New password" value={password} onChange={setPassword} autoComplete="new-password" min={min} meter />
      {alerts}
      <button className="btn primary auth-submit" disabled={busy || code.length !== 6 || password.length < min}>
        {busy ? "Saving…" : "Reset password and sign in"}
      </button>
      <div className="auth-links"><span className="auth-muted">Didn't get it? Check spam.</span>{resend(() => sendReset())}</div>
    </form>
  );
  else body = (
    <form onSubmit={sendOtp}>
      <button type="button" className="auth-back" onClick={() => go("signin")}>← Back to sign in</button>
      <h1 className="auth-title">Sign in with a code</h1>
      <p className="auth-sub">We'll email you a one-time code. No password needed.</p>
      {emailField(true)}
      {alerts}
      <button className="btn primary auth-submit" disabled={busy || !email.trim() || !!noEmail}>{busy ? "Sending…" : "Send code"}</button>
    </form>
  );

  const tabs = view === "signin" || view === "signup";
  return (
    <div className="auth-screen">
      <div className="auth-shell">
        <aside className="auth-aside">
          <div className="auth-brand">
            <div className="brand-mark">P</div>
            <div>
              <div className="auth-brand-name">Portage</div>
              <div className="auth-brand-tag">carry your work across</div>
            </div>
          </div>

          <div className="auth-aside-main">
            <p className="auth-eyebrow">ALM migration platform</p>
            <h2 className="auth-hero">Move Rally work into Jira, intact.</h2>
            <p className="auth-lede">Hierarchy, links, attachments and history arrive the way your teams left them.</p>

            <div className="auth-art-text">Data Migration</div>

            <ul className="auth-points">
              <li><b>Map visually</b><span>Drag fields across, reuse templates and catalogs.</span></li>
              <li><b>Check before you move</b><span>Dry-run every work item, then create it live or export files.</span></li>
              <li><b>Ask Sora</b><span>A private assistant that proposes changes for you to approve.</span></li>
            </ul>
          </div>

          <div className="auth-aside-foot">
            <span>Self-hosted</span><span>Your data stays on your servers</span><span>Role-based access</span>
          </div>
        </aside>

        <main className="auth-panel">
          {tabs && (
            <div className="auth-tabs" role="tablist">
              <button role="tab" aria-selected={view === "signin"} className={view === "signin" ? "on" : ""} onClick={() => go("signin")}>Sign in</button>
              {config?.signup_open !== false && (
                <button role="tab" aria-selected={view === "signup"} className={view === "signup" ? "on" : ""} onClick={() => go("signup")}>Create account</button>
              )}
            </div>
          )}
          {noEmail && (
            <div className="auth-error" role="alert">
              Email isn't set up on this server, so verification codes can't be sent. An administrator must set
              <code> PORTAGE_SMTP_HOST</code> (or <code>PORTAGE_AUTH_DEV_LOG_CODES=1</code> for local testing) and restart Portage.
            </div>
          )}
          {body}
          {config?.dev_codes && <p className="auth-dev">Development mode: emails are written to the Portage server log instead of being sent.</p>}
        </main>
      </div>
    </div>
  );
}
